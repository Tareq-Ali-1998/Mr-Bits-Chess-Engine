"""Create independent, complete legal-child Stockfish benchmarks.

Generation is deliberately explicit: each nonterminal child receives its own
fixed-node search. Final-test parents and children are excluded from prepared
training/validation splits; validation benchmarks exclude the training split.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from typing import Any, Iterable

import chess
import chess.engine
import numpy as np

from .features import FEATURE_VERSION, decode_position, encode_fen, position_key

SCHEMA = "chesslab.teacher.v1"


def board_key(board: chess.Board) -> str:
    return position_key(encode_fen(board.fen(en_passant="fen"))).hex()


def terminal_score(board: chess.Board) -> dict[str, Any] | None:
    # History-dependent claimable draws are deliberately excluded. Input FENs
    # and board782_v1 do not carry the history needed to reproduce them.
    outcome = board.outcome(claim_draw=False)
    if outcome is None:
        return None
    return {"kind": "terminal", "result": outcome.result(),
            "termination": outcome.termination.name}


def white_order_key(score: dict[str, Any]) -> tuple[int, float]:
    """Total White-preference ordering; exact wins outrank finite cp scores."""
    kind = score.get("kind")
    if kind == "cp":
        value = score.get("cp")
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not np.isfinite(value):
            raise ValueError("Centipawn score must be finite")
        return 1, float(value)
    if kind == "mate":
        distance = score.get("mate")
        winner = score.get("winner")
        if isinstance(distance, bool) or not isinstance(distance, int) or distance < 0 or winner not in ("white", "black"):
            raise ValueError("Mate needs a nonnegative distance and explicit winner")
        return (2, -float(distance)) if winner == "white" else (0, float(distance))
    if kind == "terminal":
        result = score.get("result")
        if result == "1-0":
            return 2, 0.0
        if result == "0-1":
            return 0, 0.0
        if result == "1/2-1/2":
            return 1, 0.0
    raise ValueError(f"Unsupported score: {score!r}")


def finite_cp(score: dict[str, Any]) -> float | None:
    if score.get("kind") == "cp":
        white_order_key(score)
        return float(score["cp"])
    if score.get("kind") == "terminal" and score.get("result") == "1/2-1/2":
        return 0.0
    return None


def parse_board(fen: str) -> chess.Board:
    board = chess.Board(fen)
    if not board.is_valid():
        raise ValueError(f"Invalid orthodox position (status={board.status()}): {fen}")
    # Counters/history are outside this model's contract. Normalize all incoming
    # positions to the exact same supported state used in preparation/inference.
    return decode_position(encode_fen(board.fen(en_passant="fen")))


def validate_benchmark_record(record: dict[str, Any]) -> chess.Board:
    """Refuse partial/duplicate/misidentified legal-child sets or false terminals."""
    if record.get("type") != "position":
        raise ValueError("Expected a benchmark position record")
    board = parse_board(record["fen"])
    if record.get("parent_key") != board_key(board):
        raise ValueError("Parent key does not match its encoded position")
    if record.get("turn") != ("white" if board.turn else "black"):
        raise ValueError("Parent turn does not match FEN")
    legal = {m.uci(): m for m in board.legal_moves}
    if not legal or terminal_score(board) is not None:
        raise ValueError("Benchmark parents must be nonterminal with legal moves")
    children = record.get("children")
    if not isinstance(children, list) or len(children) != len(legal):
        raise ValueError("Benchmark must include every legal child exactly once")
    seen_moves: set[str] = set()
    seen_keys: set[str] = set()
    for child in children:
        move = child.get("move")
        if move not in legal or move in seen_moves:
            raise ValueError("Illegal or duplicate benchmark move")
        seen_moves.add(move)
        board.push(legal[move])
        try:
            key = board_key(board)
            if child.get("child_key") != key or key in seen_keys:
                raise ValueError("Incorrect or duplicate child position key")
            seen_keys.add(key)
            score = child["score"]
            white_order_key(score)
            exact = terminal_score(board)
            if exact is not None and score != exact:
                raise ValueError("Terminal child must have its exact terminal result")
            if exact is None and score.get("kind") == "terminal":
                raise ValueError("Nonterminal child mislabeled as terminal")
            if exact is None and score.get("kind") == "mate" and score["mate"] == 0:
                raise ValueError("A nonterminal child cannot already be mate in zero")
        finally:
            board.pop()
    return board


def validate_header(header: dict[str, Any]) -> None:
    if header.get("type") != "header" or header.get("schema") != SCHEMA:
        raise ValueError("Missing or unsupported benchmark header")
    if header.get("feature_version") != FEATURE_VERSION:
        raise ValueError("Benchmark feature version differs from this encoder")
    if header.get("score_pov") != "white":
        raise ValueError("Benchmark must explicitly use White-perspective scores")
    leakage = header.get("leakage", {})
    purpose = header.get("purpose", "test")
    required_splits = ["train", "validation"] if purpose == "test" else ["train"]
    if purpose not in ("test", "validation") or leakage.get("verified") is not True or leakage.get("excluded_splits") != required_splits:
        raise ValueError("Benchmark lacks verified parent/child exclusion for its declared purpose")
    if not isinstance(header.get("data_fingerprint"), str) or not header["data_fingerprint"]:
        raise ValueError("Benchmark lacks its prepared-data fingerprint")
    teacher = header.get("teacher", {})
    if not isinstance(teacher, dict) or not isinstance(teacher.get("id"), dict) or not teacher["id"].get("name"):
        raise ValueError("Benchmark lacks its teacher engine identity")
    digest = teacher.get("sha256", "")
    if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise ValueError("Benchmark lacks a valid teacher executable fingerprint")
    budget = teacher.get("nodes_per_child")
    if isinstance(budget, bool) or not isinstance(budget, int) or budget < 1:
        raise ValueError("Benchmark lacks its positive per-child node budget")
    if teacher.get("score_policy") != "last score update without upper/lower bound inside fixed node cap":
        raise ValueError("Unsupported or missing teacher scalar-score policy")
    keys = header.get("selected_parent_keys")
    if not isinstance(keys, list) or not keys or len(keys) != len(set(keys)):
        raise ValueError("Benchmark header has invalid selected parent keys")


def read_benchmark(path: str | Path, *, require_complete: bool = True) -> tuple[dict, list[dict]]:
    with Path(path).open(encoding="utf-8") as handle:
        try:
            header = json.loads(next(handle))
        except (StopIteration, json.JSONDecodeError) as exc:
            raise ValueError("Benchmark must start with a valid header") from exc
        validate_header(header)
        records = []
        seen = set()
        for line_number, line in enumerate(handle, 2):
            if not line.strip():
                raise ValueError(f"Blank benchmark line {line_number}")
            try:
                record = json.loads(line)
                validate_benchmark_record(record)
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"Invalid benchmark record at line {line_number}: {exc}") from exc
            key = record["parent_key"]
            if key in seen or key not in header["selected_parent_keys"]:
                raise ValueError("Duplicate or unselected benchmark parent")
            seen.add(key)
            records.append(record)
        if require_complete and seen != set(header["selected_parent_keys"]):
            raise ValueError("Benchmark is incomplete; resume teacher generation first")
    return header, records


def build_parent_record(board: chess.Board, engine: Any, *, nodes: int) -> dict:
    if nodes < 1:
        raise ValueError("Node budget must be positive")
    board = parse_board(board.fen(en_passant="fen"))
    if terminal_score(board) is not None:
        raise ValueError("Cannot label a terminal parent")
    record = {"type": "position", "fen": board.fen(en_passant="fen"),
              "parent_key": board_key(board), "turn": "white" if board.turn else "black",
              "children": []}
    for move in sorted(board.legal_moves, key=lambda m: m.uci()):
        board.push(move)
        try:
            child: dict[str, Any] = {"move": move.uci(), "child_key": board_key(board)}
            exact = terminal_score(board)
            if exact is not None:
                child.update(score=exact, nodes=0, score_nodes=0, depth=0, elapsed_seconds=0.0)
            else:
                # Reset between independent children to prevent earlier searches'
                # hash contents from making the labels order dependent.
                engine.configure({"Clear Hash": None})
                started = time.perf_counter()
                limit = chess.engine.Limit(nodes=nodes)
                if hasattr(engine, "analysis"):
                    info = None
                    with engine.analysis(board, limit) as analysis:
                        for update in analysis:
                            if "score" in update and not update.get("lowerbound") and not update.get("upperbound"):
                                info = dict(update)
                        search_nodes = int(analysis.info.get("nodes", 0))
                    if info is None:
                        raise ValueError("No unbounded score completed within the child node budget")
                else:
                    # Useful for small deterministic test doubles, not a way to
                    # silently accept an engine bound as a scalar label.
                    info = engine.analyse(board, limit)
                    search_nodes = int(info.get("nodes", 0))
                    if info.get("lowerbound") or info.get("upperbound"):
                        raise ValueError("Teacher returned a bound rather than a score")
                white = info["score"].pov(chess.WHITE)
                mate = white.mate()
                if mate is not None:
                    if mate == 0:
                        raise ValueError("Nonterminal mate-zero teacher result is ambiguous")
                    score = {"kind": "mate", "mate": abs(mate),
                             "winner": "white" if mate > 0 else "black"}
                else:
                    cp = white.score()
                    if cp is None:
                        raise ValueError("Teacher score has neither cp nor mate")
                    score = {"kind": "cp", "cp": int(cp)}
                child.update(score=score, nodes=search_nodes,
                             score_nodes=int(info.get("nodes", 0)),
                             depth=int(info.get("depth", 0)),
                             elapsed_seconds=round(time.perf_counter() - started, 6))
            record["children"].append(child)
        finally:
            board.pop()
    validate_benchmark_record(record)
    return record


def overlapping_keys(data_dir: Path, keys: set[bytes], *, chunk_size: int = 250_000,
                     splits: Iterable[str] = ("train", "validation")) -> set[bytes]:
    """Scan compact key columns in bounded chunks; never build a full-data set."""
    hits: set[bytes] = set()
    if not keys:
        return hits
    wanted = np.frombuffer(b"".join(sorted(keys)), dtype="V16")
    for split in splits:
        rows = np.load(data_dir / f"{split}.npy", mmap_mode="r", allow_pickle=False)
        if rows.dtype.names is None or "key" not in rows.dtype.names:
            raise ValueError(f"Prepared {split} split has no position key column")
        for offset in range(0, len(rows), chunk_size):
            current = np.ascontiguousarray(rows["key"][offset:offset + chunk_size]).view("V16").reshape(-1)
            # Void records preserve trailing zero bytes that numpy strings drop.
            mask = np.isin(current, wanted)
            hits.update(value.tobytes() for value in current[mask])
    return hits


def select_candidates(args: argparse.Namespace) -> list[chess.Board]:
    max_candidates = args.max_candidates or max(args.positions * 20, 100)
    candidates: list[chess.Board] = []
    if args.fen_jsonl:
        with Path(args.fen_jsonl).open(encoding="utf-8") as handle:
            for index, line in enumerate(handle):
                if index >= max_candidates:
                    break
                value = json.loads(line)
                fen = value if isinstance(value, str) else value["fen"]
                candidates.append(parse_board(fen))
    else:
        rows = np.load(Path(args.data) / f"{args.split}.npy", mmap_mode="r", allow_pickle=False)
        rng = np.random.default_rng(args.seed)
        indices = rng.choice(len(rows), size=min(len(rows), max_candidates), replace=False)
        candidates = [decode_position(rows[int(i)]["position"]) for i in indices]
    unique: dict[str, chess.Board] = {}
    for board in candidates:
        if terminal_score(board) is None:
            unique.setdefault(board_key(board), board)
    return list(unique.values())


def _binary_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", required=True, help="Explicit local Stockfish executable path")
    parser.add_argument("--data", required=True, help="Prepared dataset for leakage exclusion")
    parser.add_argument("--split", choices=("validation", "test"), default="test")
    parser.add_argument("--fen-jsonl", help="Optional JSONL strings or objects containing fen")
    parser.add_argument("--positions", type=int, default=100)
    parser.add_argument("--max-candidates", type=int, default=0)
    parser.add_argument("--seed", type=int, default=20261022)
    parser.add_argument("--nodes", type=int, default=50_000, help="Requested nodes PER nonterminal child")
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--hash-mb", type=int, default=256)
    parser.add_argument("--output", required=True)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args(argv)
    if min(args.positions, args.nodes, args.threads, args.hash_mb) < 1 or args.max_candidates < 0:
        parser.error("Counts, node budget, threads and hash must be positive")
    from .data import manifest_fingerprint
    data_dir = Path(args.data)
    candidates = select_candidates(args)
    parent_children: dict[str, set[bytes]] = {}
    for board in candidates:
        keys = {bytes.fromhex(board_key(board))}
        for move in list(board.legal_moves):
            board.push(move)
            keys.add(bytes.fromhex(board_key(board)))
            board.pop()
        parent_children[board_key(board)] = keys
    all_keys = set().union(*parent_children.values()) if parent_children else set()
    excluded_splits = ["train", "validation"] if args.split == "test" else ["train"]
    hits = overlapping_keys(data_dir, all_keys, splits=excluded_splits)
    accepted = [b for b in candidates if not parent_children[board_key(b)].intersection(hits)][:args.positions]
    if not accepted:
        raise ValueError("No independent parents remain; increase --max-candidates or supply independent FENs")
    engine_path = Path(args.engine).resolve(strict=True)
    output = Path(args.output)
    if output.exists() and not args.resume:
        raise FileExistsError(f"Refusing to overwrite {output}; use --resume for the same benchmark")
    requested_children = sum(b.legal_moves.count() for b in accepted)
    print(f"Selected {len(accepted)} / {args.positions} parents, {requested_children} legal children; "
          f"up to {requested_children * args.nodes:,} requested search nodes. Wall time requires measurement.", file=sys.stderr)
    engine = chess.engine.SimpleEngine.popen_uci(str(engine_path))
    try:
        # python-chess manages MultiPV itself; ordinary analyse() selects one PV.
        engine.configure({"Threads": args.threads, "Hash": args.hash_mb})
        header = {"type": "header", "schema": SCHEMA, "feature_version": FEATURE_VERSION,
                  "purpose": args.split,
                  "score_pov": "white", "history": "unsupported; counters normalized to 0/1",
                  "data_fingerprint": manifest_fingerprint(data_dir),
                  "selected_parent_keys": [board_key(b) for b in accepted],
                  "selection": {"seed": args.seed, "candidate_count": len(candidates),
                                "requested_parents": args.positions, "source": "fen_jsonl" if args.fen_jsonl else args.split},
                  "leakage": {"verified": True, "excluded_splits": excluded_splits,
                              "policy": "reject parent if parent or any legal child occurs in excluded splits",
                              "excluded_candidates": sum(bool(parent_children[board_key(b)].intersection(hits)) for b in candidates)},
                  "teacher": {"id": dict(engine.id), "executable": engine_path.name,
                              "sha256": _binary_digest(engine_path), "nodes_per_child": args.nodes,
                              "options": {"Threads": args.threads, "Hash": args.hash_mb, "MultiPV": 1},
                              "hash_policy": "Clear Hash before every nonterminal child",
                              "score_policy": "last score update without upper/lower bound inside fixed node cap"}}
        done: set[str] = set()
        if output.exists():
            previous, records = read_benchmark(output, require_complete=False)
            if previous != header:
                raise ValueError("Resume arguments/data/engine/selection differ from existing header")
            done = {r["parent_key"] for r in records}
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("a" if output.exists() else "w", encoding="utf-8", newline="\n") as handle:
            if not done and handle.tell() == 0:
                handle.write(json.dumps(header, sort_keys=True) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            for index, board in enumerate(accepted, 1):
                if board_key(board) in done:
                    continue
                record = build_parent_record(board, engine, nodes=args.nodes)
                handle.write(json.dumps(record, sort_keys=True) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
                print(f"Saved complete parent {index}/{len(accepted)}", file=sys.stderr)
        read_benchmark(output)
    finally:
        engine.quit()


if __name__ == "__main__":
    main()
