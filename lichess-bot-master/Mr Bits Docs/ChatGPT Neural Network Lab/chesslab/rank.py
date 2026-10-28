"""Rank legal child positions and evaluate a frozen full-child benchmark."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import time
from typing import Any

import chess
import numpy as np
import torch

from .features import FEATURE_VERSION, encode_fen, expand_batch
from .models import load_checkpoint
from .teacher import board_key, finite_cp, parse_board, read_benchmark, terminal_score, white_order_key


def rank_position(model: torch.nn.Module, fen: str, device: str = "cpu") -> dict[str, Any]:
    """Evaluate all nonterminal legal children in one batch; never prune a move."""
    started = time.perf_counter()
    board = parse_board(fen)
    result: dict[str, Any] = {"fen": board.fen(en_passant="fen"), "parent_key": board_key(board),
                              "turn": "white" if board.turn else "black", "ranked": [],
                              "terminal": terminal_score(board), "feature_version": FEATURE_VERSION,
                              "counter_history_policy": "clocks normalized; repetition history unsupported"}
    if result["terminal"] is not None:
        result["timing"] = {"wall_seconds": time.perf_counter() - started,
                            "neural_batch_seconds": 0.0, "predicted_children": 0, "legal_children": 0}
        return result
    children: list[dict[str, Any]] = []
    packed: list[np.ndarray] = []
    needs_prediction: list[int] = []
    for move in sorted(board.legal_moves, key=lambda m: m.uci()):
        board.push(move)
        try:
            exact = terminal_score(board)
            child = {"move": move.uci(), "child_key": board_key(board), "score": exact,
                     "source": "exact_terminal" if exact is not None else "neural"}
            if exact is None:
                needs_prediction.append(len(children))
                packed.append(encode_fen(board.fen(en_passant="fen")))
            children.append(child)
        finally:
            board.pop()
    batch_seconds = 0.0
    if packed:
        batch_started = time.perf_counter()
        compact = torch.from_numpy(np.stack(packed)).to(device)
        model.eval()
        with torch.inference_mode():
            predictions = model(expand_batch(compact)).detach().float().cpu()
        if predictions.shape != (len(packed), 1) or not torch.isfinite(predictions).all().item():
            raise ValueError("Model must return finite White-pawn scores of shape [B,1]")
        batch_seconds = time.perf_counter() - batch_started
        for index, prediction in zip(needs_prediction, predictions[:, 0].tolist()):
            children[index]["score"] = {"kind": "cp", "cp": prediction * 100.0}
            children[index]["pawns_white"] = prediction
    # Input is UCI sorted, so stable score sorting resolves neural ties by UCI.
    children.sort(key=lambda child: white_order_key(child["score"]), reverse=board.turn == chess.WHITE)
    for index, child in enumerate(children, 1):
        child["rank"] = index
    result["ranked"] = children
    result["timing"] = {"wall_seconds": time.perf_counter() - started,
                        "neural_batch_seconds": batch_seconds,
                        "predicted_children": len(packed), "legal_children": len(children)}
    return result


def wilson_interval(successes: int, total: int) -> dict[str, Any]:
    if not 0 <= successes <= total:
        raise ValueError("Invalid binomial counts")
    if total == 0:
        return {"successes": 0, "total": 0, "rate": None, "wilson95": None}
    z = 1.959963984540054
    rate = successes / total
    denominator = 1 + z * z / total
    center = (rate + z * z / (2 * total)) / denominator
    radius = z * math.sqrt(rate * (1 - rate) / total + z * z / (4 * total * total)) / denominator
    return {"successes": successes, "total": total, "rate": rate,
            "wilson95": [max(0.0, center - radius), min(1.0, center + radius)]}


def _parent_measurements(record: dict, ranked: list[dict], near_cp: float) -> dict:
    predicted = [row["move"] for row in ranked]
    teacher = {row["move"]: row["score"] for row in record["children"]}
    if len(predicted) != len(teacher) or set(predicted) != set(teacher):
        raise ValueError("Prediction and benchmark legal move sets differ")
    if not predicted:
        raise ValueError("Cannot measure recall on an empty legal move set")
    turn_white = record["turn"] == "white"
    preference = {move: white_order_key(score) for move, score in teacher.items()}
    best_key = (max if turn_white else min)(preference.values())
    best_moves = {move for move, value in preference.items() if value == best_key}
    chosen = predicted[0]
    strict = {str(k): bool(best_moves.intersection(predicted[:k])) for k in (1, 5, 7)}
    best_cp = finite_cp(teacher[next(iter(best_moves))])
    chosen_cp = finite_cp(teacher[chosen])
    near = None
    regret = None
    if best_cp is not None:
        sign = 1 if turn_white else -1
        acceptable = {move for move, score in teacher.items()
                      if (cp := finite_cp(score)) is not None and sign * (best_cp - cp) <= near_cp}
        near = {str(k): bool(acceptable.intersection(predicted[:k])) for k in (1, 5, 7)}
        if chosen_cp is not None:
            regret = max(0.0, sign * (best_cp - chosen_cp))
    mate_miss = preference[chosen][0] != best_key[0]
    return {"parent_key": record["parent_key"], "turn": record["turn"],
            "legal_moves": len(predicted),
            "best_teacher_moves": sorted(best_moves), "neural_top1": chosen,
            "strict_best": strict, "near_best": near, "top1_cp_regret": regret,
            "mate_category_disagreement": mate_miss}


def _summarize(rows: list[dict], near_cp: float) -> dict:
    finite_rows = [row for row in rows if row["near_best"] is not None]
    regrets = [row["top1_cp_regret"] for row in rows if row["top1_cp_regret"] is not None]
    legal_counts = [row["legal_moves"] for row in rows]
    return {"parents": len(rows),
            "legal_move_coverage": {"min": min(legal_counts) if legal_counts else None,
                                    "median": float(np.median(legal_counts)) if legal_counts else None,
                                    "max": max(legal_counts) if legal_counts else None,
                                    "parents_with_at_most_5_moves": sum(n <= 5 for n in legal_counts)},
            "strict_best_recall": {f"@{k}": wilson_interval(sum(row["strict_best"][str(k)] for row in rows), len(rows)) for k in (1, 5, 7)},
            "near_best_recall": {"tolerance_cp": near_cp, "eligible_finite_score_parents": len(finite_rows),
                                 **{f"@{k}": wilson_interval(sum(row["near_best"][str(k)] for row in finite_rows), len(finite_rows)) for k in (1, 5, 7)}},
            "cp_regret": {"comparable_parents": len(regrets),
                          "mean": float(np.mean(regrets)) if regrets else None,
                          "median": float(np.median(regrets)) if regrets else None,
                          "p95": float(np.quantile(regrets, .95)) if regrets else None,
                          "max": max(regrets) if regrets else None},
            "mate_category_disagreements": sum(row["mate_category_disagreement"] for row in rows)}


def evaluate_benchmark(model: torch.nn.Module, path: str | Path, *, device: str = "cpu",
                       near_cp: float = 25, expected_data_fingerprint: str | None = None) -> dict:
    if near_cp < 0:
        raise ValueError("Near-best tolerance must be nonnegative")
    header, records = read_benchmark(path)
    if expected_data_fingerprint is not None and header["data_fingerprint"] != expected_data_fingerprint:
        raise ValueError("Benchmark leakage audit was performed against a different prepared dataset")
    measurements = []
    # Separate the first cold legal-position pass from reported warmed timings.
    warmup_started = time.perf_counter()
    rank_position(model, records[0]["fen"], device)
    warmup_seconds = time.perf_counter() - warmup_started
    for record in records:
        prediction = rank_position(model, record["fen"], device)
        metrics = _parent_measurements(record, prediction["ranked"], near_cp)
        metrics["timing"] = prediction["timing"]
        measurements.append(metrics)
    elapsed = [row["timing"]["wall_seconds"] for row in measurements]
    return {"schema": "chesslab.ranking-report.v1", "feature_version": FEATURE_VERSION,
            "benchmark_purpose": header.get("purpose", "test"),
            "data_fingerprint": header["data_fingerprint"], "teacher": header["teacher"],
            "ranking_timing": {"device": device, "torch_cpu_threads": torch.get_num_threads(),
                               "warmup_parents": 1, "warmup_wall_seconds": warmup_seconds,
                               "timed_parents": len(measurements), "total_wall_seconds": sum(elapsed),
                               "mean_parent_ms": 1000 * float(np.mean(elapsed)),
                               "median_parent_ms": 1000 * float(np.median(elapsed)),
                               "p95_parent_ms": 1000 * float(np.quantile(elapsed, .95)),
                               "scope": "legal generation, terminal checks, feature encoding, batch inference with CPU result synchronization, sorting; excludes checkpoint/benchmark loading and teacher work"},
            "method": {"unit": "one complete legal-child parent", "ties": "any exactly tied teacher-best move counts; neural ties sorted by UCI",
                       "near_best": "finite teacher scores only; distinct from strict best",
                       "cp_regret": "finite best and chosen teacher scores only; mate categories kept separate",
                       "interval": "Wilson 95%; descriptive position-level intervals, not an Elo estimate or independence proof"},
            "overall": _summarize(measurements, near_cp),
            "by_turn": {turn: _summarize([r for r in measurements if r["turn"] == turn], near_cp) for turn in ("white", "black")},
            "positions": measurements}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--fen")
    source.add_argument("--benchmark")
    parser.add_argument("--top", type=int, default=7)
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    parser.add_argument("--cpu-threads", type=int, default=1,
                        help="PyTorch CPU threads (default 1); reported with benchmark timings")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--near-cp", type=float, default=25)
    parser.add_argument("--output", help="Write benchmark report JSON")
    args = parser.parse_args(argv)
    if args.top < 1 or args.cpu_threads < 1:
        parser.error("--top and --cpu-threads must be positive")
    torch.set_num_threads(args.cpu_threads)
    model, checkpoint = load_checkpoint(args.checkpoint, args.device)
    if args.benchmark:
        fingerprint = checkpoint.get("data_fingerprint")
        if not isinstance(fingerprint, str) or not fingerprint:
            raise ValueError("Benchmark evaluation requires a checkpoint's prepared-data fingerprint")
        result = evaluate_benchmark(model, args.benchmark, device=args.device,
                                    near_cp=args.near_cp, expected_data_fingerprint=fingerprint)
        if args.output:
            output = Path(args.output)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        print(json.dumps(result if args.json or not args.output else result["overall"], indent=2, allow_nan=False))
    else:
        result = rank_position(model, args.fen, args.device)
        result["top"] = result["ranked"][:args.top]
        if args.json:
            print(json.dumps(result, indent=2, allow_nan=False))
        else:
            print(f"{result['turn'].title()} to move; all {len(result['ranked'])} legal moves retained")
            if result["terminal"]:
                print(f"Exact terminal result: {result['terminal']}")
            for row in result["ranked"]:
                marker = "*" if row["rank"] <= args.top else " "
                score = row["score"]
                display = f"{score['cp']/100:+.4f} pawns (White)" if score["kind"] == "cp" else str(score)
                print(f"{marker} {row['rank']:3} {row['move']:5} {display} [{row['source']}]")


if __name__ == "__main__":
    main()
