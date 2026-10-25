"""Stream, filter, disk-deduplicate, sample and split the raw evaluation archive.

The GPU is not used. Nothing modifies or unpacks the original archive.
"""

from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import io
import itertools
import json
import os
from pathlib import Path
import sqlite3
import time

import chess
import numpy as np

from .data import RECORD_DTYPE, SPLITS, compute_manifest_fingerprint, sha256_file
from .features import FEATURE_VERSION, board_from_fen, encode_board, feature_contract, position_key


def _integer(value):
    return isinstance(value, int) and not isinstance(value, bool)


def inspect_record(raw: str, policy: dict):
    """Return (accepted tuple or None, reason). Never turn a mate into pawns."""
    try:
        record = json.loads(raw)
    except (ValueError, TypeError):
        return None, "invalid_json"
    if not isinstance(record, dict) or not isinstance(record.get("fen"), str):
        return None, "missing_fen"
    if len(record["fen"].split()) != 4:
        return None, "not_four_field_source_fen"
    try:
        board = board_from_fen(record["fen"])
    except (ValueError, TypeError):
        return None, "invalid_orthodox_position"
    if board.is_game_over(claim_draw=False):
        return None, "terminal_position"
    evaluations = record.get("evals")
    if not isinstance(evaluations, list) or not evaluations:
        return None, "missing_evaluations"
    # Broken entries cannot be silently ignored in favor of an older label.
    for entry in evaluations:
        if not isinstance(entry, dict) or not _integer(entry.get("depth")) or not _integer(entry.get("knodes")):
            return None, "malformed_analysis_metadata"
        if entry["depth"] < 0 or entry["knodes"] < 0 or entry["knodes"] > 2**63 - 1:
            return None, "invalid_analysis_metadata"
    selected = max(evaluations, key=lambda x: (x["depth"], x["knodes"]))
    depth, knodes = selected["depth"], selected["knodes"]
    if not policy["min_depth"] <= depth <= policy["max_depth"]:
        return None, "depth_outside_policy"
    if knodes < policy["min_knodes"]:
        return None, "insufficient_search_nodes"
    pvs = selected.get("pvs")
    if not isinstance(pvs, list) or not pvs or not isinstance(pvs[0], dict):
        return None, "missing_first_pv"
    pv = pvs[0]
    if "mate" in pv:
        return None, "mate_label"
    if not _integer(pv.get("cp")):
        return None, "invalid_cp_label"
    cp = pv["cp"]
    if abs(cp) > policy["max_abs_cp"]:
        return None, "extreme_cp_label"
    line = pv.get("line")
    if not isinstance(line, str) or not line.split():
        return None, "missing_pv_line"
    replay = board.copy(stack=False)
    moves = line.split()
    if len(moves) > 1024:
        return None, "excessive_pv_length"
    try:
        for text in moves if policy["pv_validation"] == "full" else moves[:1]:
            # parse_uci handles standard-position UCI_Chess960 castling notation.
            move = replay.parse_uci(text)
            if move == chess.Move.null() or move not in replay.legal_moves:
                return None, "illegal_pv_line"
            replay.push(move)
    except (ValueError, TypeError):
        return None, "illegal_pv_line"
    packed = encode_board(board)
    return (position_key(packed), packed.tobytes(), cp, depth, knodes), "accepted_candidate"


def inspect_chunk(payload):
    lines, policy = payload
    return [inspect_record(line, policy) for line in lines]


@contextmanager
def open_records(path: Path):
    if path.suffix == ".zst":
        try:
            import zstandard
        except ImportError:
            try:
                from compression import zstd
            except ImportError as exc:
                raise RuntimeError("Install zstandard to stream .zst archives on Python <3.14") from exc
            with zstd.open(path, "rt", encoding="utf-8") as stream:
                yield stream
        else:
            with path.open("rb") as raw:
                with zstandard.ZstdDecompressor().stream_reader(raw, read_across_frames=True) as decoded:
                    with io.TextIOWrapper(decoded, encoding="utf-8") as stream:
                        yield stream
    elif path.suffix in (".jsonl", ".ndjson"):
        with path.open("r", encoding="utf-8") as stream:
            yield stream
    else:
        raise ValueError("Input must be .jsonl, .ndjson, or .jsonl.zst")


def split_for_key(key: bytes, seed: int = 20261023) -> str:
    seed_bytes = str(seed).encode("ascii") + b"/" + key
    slot = int.from_bytes(hashlib.blake2b(seed_bytes, digest_size=8, person=b"mrbits-split-v1").digest(), "big") % 10000
    return "train" if slot < 9000 else "validation" if slot < 9500 else "test"


def _atomic_json(path: Path, value):
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(path)


def prepare(args) -> dict:
    source, output = Path(args.input).resolve(), Path(args.output).resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    if args.max_positions <= 0 or args.max_records < 0 or args.workers < 1 or args.chunk_size < 1:
        raise ValueError("max-positions/workers/chunk-size must be positive; max-records is >=0 (0=all)")
    if not 1 <= args.min_depth <= args.max_depth <= 65535 or args.min_knodes < 1 or not 1 <= args.max_abs_cp < 2**31:
        raise ValueError("Invalid quality thresholds")
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"Choose a new empty output directory; refusing to overwrite {output}")
    output.mkdir(parents=True, exist_ok=True)
    policy = {name: getattr(args, name) for name in ("min_depth", "max_depth", "min_knodes", "max_abs_cp", "pv_validation")}
    counts = Counter()
    started = time.monotonic()
    scan_hash = hashlib.sha256()
    database_path = output / ".prepare.sqlite"
    connection = sqlite3.connect(database_path)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=NORMAL")
    connection.execute("PRAGMA cache_size=-65536")
    connection.execute("CREATE TABLE positions (key BLOB PRIMARY KEY, position BLOB NOT NULL, cp INTEGER NOT NULL, depth INTEGER NOT NULL, knodes INTEGER NOT NULL) WITHOUT ROWID")
    stopped_early = False
    console = None
    try:
        from rich.console import Console
        console = Console()
    except ImportError:
        pass

    def show(message):
        if console:
            console.print(message)
        else:
            print(message, flush=True)

    def chunks(stream):
        limited = stream if args.max_records == 0 else itertools.islice(stream, args.max_records)
        while True:
            chunk = list(itertools.islice(limited, args.chunk_size))
            if not chunk:
                return
            for line in chunk:
                scan_hash.update(line.encode("utf-8"))
            yield chunk, policy

    # Bounded in-flight work avoids ProcessPoolExecutor prefetching a huge archive.
    def evaluated(stream, executor):
        iterator = chunks(stream)
        if executor is None:
            for payload in iterator:
                yield inspect_chunk(payload)
        else:
            while True:
                batch = list(itertools.islice(iterator, args.workers * 2))
                if not batch:
                    return
                for result in executor.map(inspect_chunk, batch):
                    yield result

    executor = ProcessPoolExecutor(max_workers=args.workers) if args.workers > 1 else None
    try:
        show(f"[bold cyan]Preparing {source.name}[/bold cyan] | workers={args.workers} | sampling={args.sampling}")
        show(f"[yellow]Quality policy:[/yellow] depth {args.min_depth}..{args.max_depth}; knodes >= {args.min_knodes}; |cp| <= {args.max_abs_cp}; PV={args.pv_validation}")
        last_update = time.monotonic()
        with open_records(source) as stream:
            for result_chunk in evaluated(stream, executor):
                for accepted, reason in result_chunk:
                    counts["records_processed"] += 1
                    if accepted is None:
                        counts[reason] += 1
                        continue
                    counts["accepted_candidates"] += 1
                    key, packed, cp, depth, knodes = accepted
                    prior = connection.execute("SELECT position, cp, depth, knodes FROM positions WHERE key=?", (key,)).fetchone()
                    if prior is None:
                        connection.execute("INSERT INTO positions VALUES (?,?,?,?,?)", accepted)
                        counts["unique_accepted"] += 1
                    else:
                        if prior[0] != packed:
                            raise RuntimeError("Position-key collision detected; refusing ambiguous deduplication")
                        counts["duplicate_candidates"] += 1
                        if prior[1] != cp:
                            counts["conflicting_duplicate_labels"] += 1
                        if (depth, knodes) > (prior[2], prior[3]):
                            connection.execute("UPDATE positions SET cp=?,depth=?,knodes=? WHERE key=?", (cp, depth, knodes, key))
                    if args.sampling == "prefix" and counts["unique_accepted"] >= args.max_positions:
                        stopped_early = True
                        break
                connection.commit()
                if time.monotonic() - last_update >= 2 or stopped_early:
                    elapsed = time.monotonic() - started
                    show(f"[cyan]Scanned[/cyan] {counts['records_processed']:,} | [green]clean unique[/green] {counts['unique_accepted']:,} | {counts['records_processed']/max(elapsed,.001):,.0f} records/s | {elapsed:.0f}s")
                    _atomic_json(output / "preparation_progress.json", {"status": "scanning", "counts": dict(counts), "seconds": elapsed})
                    last_update = time.monotonic()
                if stopped_early:
                    break
        if not counts["unique_accepted"]:
            raise ValueError("No positions passed the quality policy; inspect rejection counts in failure.json")
        # Hash order selects a deterministic approximately uniform subset of unique
        # accepted inputs from the scanned pool. It is not whole-archive sampling
        # unless the whole archive was scanned. No random reservoir lives in RAM.
        count = min(counts["unique_accepted"], args.max_positions)
        query = "SELECT key,position,cp,depth,knodes FROM positions ORDER BY key LIMIT ?"
        split_counts = Counter({s: 0 for s in SPLITS})
        for key, *_ in connection.execute(query, (count,)):
            split_counts[split_for_key(key, args.seed)] += 1
        arrays = {
            split: np.lib.format.open_memmap(output / f"{split}.npy", mode="w+", dtype=RECORD_DTYPE, shape=(split_counts[split],))
            for split in SPLITS
        }
        indexes = Counter()
        coverage = {s: {"side": Counter(), "abs_cp_bucket": Counter(), "pieces": Counter()} for s in SPLITS}
        for key, packed, cp, depth, knodes in connection.execute(query, (count,)):
            split = split_for_key(key, args.seed)
            values = np.frombuffer(packed, dtype=np.uint8)
            arrays[split][indexes[split]] = (values, cp, depth, knodes, np.frombuffer(key, dtype=np.uint8))
            indexes[split] += 1
            coverage[split]["side"]["white" if values[64] else "black"] += 1
            magnitude = abs(cp)
            bucket = "0-100" if magnitude <= 100 else "101-300" if magnitude <= 300 else "301-600" if magnitude <= 600 else "601-1500" if magnitude <= 1500 else "1501+"
            coverage[split]["abs_cp_bucket"][bucket] += 1
            coverage[split]["pieces"][str(int(np.count_nonzero(values[:64])))] += 1
        for array in arrays.values():
            array.flush()
        arrays.clear()
        manifest = {
            "schema": "chesslab.prepared.v1",
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "feature_version": FEATURE_VERSION,
            "features": feature_contract(),
            "target": {"perspective": "white", "units_on_disk": "centipawns", "neural_units": "pawns", "mate_labels": "rejected"},
            "quality": policy,
            "source": {"filename": source.name, "bytes": source.stat().st_size, "scanned_content_sha256": scan_hash.hexdigest(), "full_archive_sha256": None},
            "sampling": {"method": args.sampling, "max_records": args.max_records, "max_positions": args.max_positions, "prefix_stopped_at_cap": stopped_early, "warning": "Hash selection is representative only of the scanned accepted pool, not necessarily the complete archive. Read-ahead chunks can contribute to scanned_content_sha256 beyond records_processed."},
            "split": {"seed": args.seed, "method": "independent position hash buckets 90/5/5; no augmentation", "history_grouping": "unavailable in source"},
            "audit_counts": dict(counts),
            "counts": dict(split_counts),
            "coverage": coverage,
            "files": {f"{s}.npy": {"sha256": sha256_file(output / f"{s}.npy"), "bytes": (output / f"{s}.npy").stat().st_size} for s in SPLITS},
            "preparation_seconds": round(time.monotonic() - started, 3),
            "label_caveat": "Quality filters are evidence controls, not proof of teacher correctness or 95% move recall.",
        }
        manifest["fingerprint"] = compute_manifest_fingerprint(manifest)
        _atomic_json(output / "manifest.json", manifest)
        _atomic_json(output / "preparation_progress.json", {"status": "complete", "fingerprint": manifest["fingerprint"], "counts": dict(split_counts)})
        connection.close()
        if not args.keep_index:
            database_path.unlink(missing_ok=True)
            for suffix in ("-wal", "-shm"):
                Path(str(database_path) + suffix).unlink(missing_ok=True)
        show(f"[bold green]Prepared {count:,} positions[/bold green] | train={split_counts['train']:,}, validation={split_counts['validation']:,}, test={split_counts['test']:,}")
        show(f"[cyan]Manifest:[/cyan] {output / 'manifest.json'}")
        return manifest
    except BaseException as exc:
        connection.close()
        _atomic_json(output / "failure.json", {"error": str(exc), "counts": dict(counts), "note": "Partial directory is not a complete dataset. Use a new empty output directory for a retry."})
        raise
    finally:
        if executor:
            executor.shutdown(wait=True, cancel_futures=True)


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--max-positions", type=int, default=100000)
    p.add_argument("--max-records", type=int, default=2000000, help="Bound the scan; 0 scans the full archive")
    p.add_argument("--sampling", choices=("prefix", "reservoir"), default="reservoir", help="reservoir uses deterministic bottom-hash sampling over the scanned deduplicated pool")
    p.add_argument("--min-depth", type=int, default=20)
    p.add_argument("--max-depth", type=int, default=80)
    p.add_argument("--min-knodes", type=int, default=1000, help="1000 knodes = 1,000,000 searched nodes")
    p.add_argument("--max-abs-cp", type=int, default=1500)
    p.add_argument("--pv-validation", choices=("full", "first"), default="full")
    p.add_argument("--workers", type=int, default=max(1, min(8, (os.cpu_count() or 2) - 2)))
    p.add_argument("--chunk-size", type=int, default=256)
    p.add_argument("--seed", type=int, default=20261023)
    p.add_argument("--keep-index", action="store_true")
    return p


def main():
    prepare(parser().parse_args())


if __name__ == "__main__":
    main()
