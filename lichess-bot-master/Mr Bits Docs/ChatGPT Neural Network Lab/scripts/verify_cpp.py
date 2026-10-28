"""Compile and verify exported C++ evaluators against the actual FP32 checkpoints.

All inference/latency measurements are CPU-only. No retraining or engine edits.
Run from any directory; defaults resolve relative to this lab's directory.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import random
import shutil
import statistics
import struct
import subprocess
import sys
import tempfile
import time
import zlib

LAB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB))

import chess
import numpy as np
import torch

from chesslab.data import PositionDataset, sha256_file
from chesslab.features import decode_position, encode_board, expand_numpy
from chesslab.models import load_checkpoint, model_statistics

RELEASE = "clean-10m-20261026T080646Z"


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def resolve(path: Path) -> Path:
    return path.resolve() if path.is_absolute() else (LAB / path).resolve()


def corpus(data: Path, count: int, seed: int):
    dataset = PositionDataset(data, "validation")
    if len(dataset) < count:
        raise ValueError("Not enough prepared validation positions")
    rows, details, seen = [], [], set()

    def add(board: chess.Board, source: str, **extra):
        packed = encode_board(board)
        raw = packed.tobytes()
        if raw in seen:
            return
        seen.add(raw)
        rows.append(packed)
        details.append({"index": len(rows) - 1, "source": source,
                        "fen": board.fen(en_passant="fen"), **extra})

    for index in np.linspace(0, len(dataset) - 1, count, dtype=np.int64):
        add(decode_position(dataset.records[int(index)]["position"]), "prepared_validation", row=int(index))
    fingerprint = dataset.manifest["fingerprint"]
    dataset.close()
    if len(rows) < count:
        raise ValueError("Selected validation rows unexpectedly contain duplicate visible inputs")

    def walk(board: chess.Board, moves: list[str], source: str):
        add(board, source)
        for move in moves:
            candidate = chess.Move.from_uci(move)
            if candidate not in board.legal_moves:
                raise ValueError(f"Bad verification fixture: {source}: {move}")
            board.push(candidate)
            add(board, source, last_move=move)

    walk(chess.Board(), ["e2e4", "a7a6", "e4e5", "d7d5", "e5d6"], "legal_en_passant_capture")
    walk(chess.Board(), ["f2f3", "e7e5", "g2g4", "d8h4"], "legal_checkmate_walk")
    castles = "r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1"
    walk(chess.Board(castles), ["e1g1", "e8c8"], "white_kingside_black_queenside_castle")
    walk(chess.Board(castles), ["e1c1", "e8g8"], "white_queenside_black_kingside_castle")
    rights_squares = [chess.H1, chess.A1, chess.H8, chess.A8]
    for rights in range(16):
        for turn in (chess.WHITE, chess.BLACK):
            board = chess.Board(castles)
            board.turn = turn
            board.castling_rights = sum(chess.BB_SQUARES[sq] for bit, sq in enumerate(rights_squares) if rights & (1 << bit))
            add(board, "castling_flag_combinations", castling_bits=rights)
    for file_index in range(8):
        file = chess.FILE_NAMES[file_index]
        walk(chess.Board(), [f"{file}2{file}4"], "white_double_push_all_ep_files")
        walk(chess.Board(), ["a2a3", f"{file}7{file}5"], "black_double_push_all_ep_files")
    for fen, prefix, source in (
        ("4k3/P7/8/8/8/8/7p/4K3 w - - 0 1", "a7a8", "white_promotion"),
        ("4k3/7P/8/8/8/8/p7/4K3 b - - 0 1", "a2a1", "black_promotion"),
        ("1r2k3/P7/8/8/8/8/8/4K3 w - - 0 1", "a7b8", "white_capture_promotion"),
        ("4k3/8/8/8/8/8/p7/1R2K3 b - - 0 1", "a2b1", "black_capture_promotion"),
    ):
        for piece in "qrbn":
            walk(chess.Board(fen), [prefix + piece], source + "_" + piece)
    for fen in (
        "7k/5Q2/6K1/8/8/8/8/8 b - - 0 1",
        "7k/6Q1/6K1/8/8/8/8/8 b - - 0 1",
        "7k/8/8/8/8/8/8/K7 w - - 0 1",
        "7k/8/8/8/8/8/8/K7 b - - 0 1",
    ):
        add(chess.Board(fen), "terminal_or_sparse_corners")
    rng = random.Random(seed)
    for game in range(8):
        board = chess.Board()
        for ply in range(33):
            add(board, "deterministic_legal_walk", game=game, ply=ply)
            legal = list(board.legal_moves)
            if not legal:
                break
            board.push(legal[rng.randrange(len(legal))])
    array = np.stack(rows)
    return array, {"schema": "chesslab.cpp-corpus.v1", "seed": seed,
                   "prepared_validation_positions": count, "total_unique_positions": len(rows),
                   "dataset_fingerprint": fingerprint,
                   "packed_sha256": hashlib.sha256(array.tobytes()).hexdigest(),
                   "positions": details}


def run(command, env, *, timeout=600):
    result = subprocess.run([str(item) for item in command], cwd=LAB, env=env,
                            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    if result.returncode:
        raise RuntimeError(f"Command failed ({result.returncode}): {command}\n{result.stdout}\n{result.stderr}")
    return result


def find_compiler(argument: str | None) -> Path:
    if argument:
        candidate = shutil.which(argument) or argument
    else:
        candidate = shutil.which("g++") or shutil.which("clang++")
        if candidate is None and os.name == "nt":
            candidate = r"C:\My Programs\CodeBlocks\MinGW\bin\g++.exe"
    if not candidate or not Path(candidate).is_file():
        raise ValueError("No C++17 compiler found; pass --compiler /path/to/g++ or clang++")
    return Path(candidate).resolve()


def compile_driver(compiler: Path, include: Path, output: Path, build: str, env):
    headers = {name: sha256_file(include / name) for name in ("common.hpp", "Small/Small.hpp", "Large/Large.hpp")}
    flags = ["-O3", "-DNDEBUG", "-std=c++17", "-pthread", "-Wall", "-Wextra"]
    if platform.machine().lower() in ("amd64", "x86_64", "x64", "i386", "i686"):
        flags += ["-mno-avx", "-mno-avx2", "-mno-fma"] if build == "portable" else ["-mavx2", "-mfma"]
    elif build != "portable":
        raise ValueError("AVX2 build requires an x86 host")
    if os.name == "nt":
        flags += ["-static-libstdc++", "-static-libgcc"]
    command = [compiler, *flags, "-I", include, LAB / "cpp/verify_cpp.cpp", "-o", output]
    result = run(command, env)
    if headers != {name: sha256_file(include / name) for name in headers}:
        raise RuntimeError("Headers changed during compilation; rerun against a stable source snapshot")
    return {"command": [str(value) for value in command], "stdout": result.stdout, "stderr": result.stderr,
            "source_sha256": sha256_file(LAB / "cpp/verify_cpp.cpp"), "header_sha256": headers,
            "executable_sha256": sha256_file(output)}


def benchmark_torch(model, inputs, rounds: int, minimum_seconds: float):
    with torch.inference_mode():
        for tensor in inputs[:16]:
            model(tensor)

        def measure(count, offset):
            # No per-position .item(): C++ measures numeric evaluation, not scalar
            # synchronization. Keep and consume the final output to prevent elision.
            started = time.perf_counter()
            output = None
            for index in range(count):
                output = model(inputs[(index + offset) % len(inputs)])
            seconds = time.perf_counter() - started
            return seconds, float(output.item())

        iterations = 32
        while iterations < 1048576:
            elapsed, _ = measure(iterations, 0)
            if elapsed >= minimum_seconds:
                break
            iterations *= 2
        timings, sink = [], 0.0
        for index in range(rounds):
            elapsed, output = measure(iterations, index * 31)
            timings.append(elapsed * 1e9 / iterations)
            sink += output
    median = statistics.median(timings)
    return {"iterations_per_round": iterations, "rounds": rounds,
            "median_ns_per_position": median, "positions_per_second": 1e9 / median,
            "min_ns_per_position": min(timings), "max_ns_per_position": max(timings),
            "round_ns_per_position": timings, "consumed_output_checksum": sink,
            "scope": "Pre-expanded [1,782] CPU FP32 inputs; Python/PyTorch dispatch included; one model call per position"}


def negative_load_tests(executable: Path, model_name: str, weights: Path, output: Path, env):
    original = weights.read_bytes()
    if len(original) < 68 or original[:8] != b"MRBNN001":
        raise ValueError("Unexpected exported weight format")
    results = []
    with tempfile.TemporaryDirectory(prefix="negative-weights-", dir=output) as directory:
        path = Path(directory) / "bad.bin"

        def rejected(name: str, data: bytes | bytearray | None):
            if data is not None:
                path.write_bytes(data)
            elif path.exists():
                path.unlink()
            result = subprocess.run([str(executable), "--check-load", model_name, str(path)],
                                    cwd=LAB, env=env, capture_output=True, text=True, timeout=60)
            # Normal exception rejection must return1, not a crash/access violation.
            passed = result.returncode == 1 and "Error:" in result.stderr
            results.append({"case": name, "passed": passed, "returncode": result.returncode,
                            "message": result.stderr.strip()})

        rejected("missing_file", None)
        rejected("empty", b"")
        rejected("truncated_header", original[:20])
        rejected("truncated_payload", original[:-4])
        rejected("trailing_bytes", original + b"x")
        bad = bytearray(original); bad[0] ^= 1; rejected("wrong_magic", bad)
        bad = bytearray(original); struct.pack_into("<I", bad, 8, 2 if model_name == "small" else 1); rejected("wrong_model_id", bad)
        bad = bytearray(original); struct.pack_into("<I", bad, 12, 783); rejected("wrong_input_dimension", bad)
        bad = bytearray(original); bad[40] = 1; rejected("nonzero_reserved_flag", bad)
        bad = bytearray(original); bad[-1] ^= 1; rejected("corrupt_payload_crc", bad)
        for name, value in (("nan_with_valid_crc", math.nan), ("positive_inf_with_valid_crc", math.inf), ("negative_inf_with_valid_crc", -math.inf)):
            bad = bytearray(original)
            struct.pack_into("<f", bad, 64, value)
            struct.pack_into("<I", bad, 36, zlib.crc32(memoryview(bad)[64:]) & 0xFFFFFFFF)
            rejected(name, bad)
    return {"passed": all(item["passed"] for item in results), "cases": results,
            "note": "Nonfinite cases have recomputed valid CRCs, isolating float validation. Legitimate negative weights are not errors."}


def verify_one(name, checkpoint, weights_root, rows, out, executables, env, args):
    checkpoint = resolve(checkpoint)
    model, saved = load_checkpoint(checkpoint, "cpu")
    model.float().eval()
    folder = weights_root / name.capitalize()
    weights = folder / "weights.bin"
    metadata = json.loads((folder / "model.json").read_text(encoding="utf-8"))
    checkpoint_hash = sha256_file(checkpoint)
    if metadata.get("checkpoint_sha256") != checkpoint_hash or metadata.get("sha256") != sha256_file(weights):
        raise ValueError("Weight/checkpoint sidecar provenance mismatch")
    inputs = [torch.from_numpy(expand_numpy(row)).reshape(1, -1) for row in rows]
    with torch.inference_mode():
        expected = np.array([model(tensor).item() for tensor in inputs], dtype=np.float32)
    if not np.isfinite(expected).all():
        raise ValueError("Nonfinite Torch reference")
    corpus_file = out / f"{name}-corpus.bin"
    with corpus_file.open("wb") as handle:
        handle.write(struct.pack("<8sI", b"MRBTST01", len(rows)))
        for row, score in zip(rows, expected):
            handle.write(row.tobytes())
            handle.write(struct.pack("<f", float(score)))
    parameter_values = np.frombuffer(weights.read_bytes(), dtype="<f4", offset=64)
    report = {"model": name, "checkpoint": str(checkpoint), "checkpoint_sha256": checkpoint_hash,
              "weights": str(weights), "weights_sha256": metadata["sha256"],
              "statistics": model_statistics(saved["model_spec"]), "parameter_finite": bool(np.isfinite(parameter_values).all()),
              "negative_parameters": int((parameter_values < 0).sum()),
              "reference_precision": "CPU FP32; torch.inference_mode; no autocast",
              "reference_scores_pawns": expected.tolist(), "corpus_sha256": sha256_file(corpus_file),
              "absolute_tolerance_pawns": args.atol, "relative_tolerance": args.rtol, "builds": {}}
    for build, executable in executables.items():
        raw_path = out / f"{name}-{build}-driver.json"
        command = [executable, name, weights, corpus_file, raw_path, "--rounds", str(args.rounds),
                   "--min-seconds", str(args.min_seconds)]
        if args.skip_benchmark:
            command.append("--skip-benchmark")
        run(command, env)
        result = json.loads(raw_path.read_text(encoding="utf-8"))
        actual = np.array(result["scores"], dtype=np.float64)
        if actual.shape != expected.shape or not np.isfinite(actual).all():
            raise ValueError("C++ returned malformed/nonfinite outputs")
        errors = np.abs(actual - expected.astype(np.float64))
        tolerances = args.atol + args.rtol * np.abs(expected.astype(np.float64))
        mismatch = np.flatnonzero(errors > tolerances)
        incremental_tolerance = float(args.atol + args.rtol * np.max(np.abs(expected)))
        checks = {"scores_match_torch": not len(mismatch),
                  "kernel_adapter_exact": result["adapter_max_abs_pawns"] == 0,
                  "private_workspaces_exact": result["private_workspace_max_abs_pawns"] == 0,
                  "fresh_accumulator_matches": result["accumulator_reset_max_abs_pawns"] <= incremental_tolerance,
                  "bounded_delta_matches": result["delta_max_abs_pawns"] <= incremental_tolerance,
                  "bounded_roundtrip_matches": result["roundtrip_max_abs_pawns"] <= incremental_tolerance}
        result.update({"checks": checks, "passed": all(checks.values()),
                       "max_abs_error_pawns": float(errors.max()), "mean_abs_error_pawns": float(errors.mean()),
                       "max_abs_error_centipawns": float(errors.max() * 100),
                       "mismatched_positions": mismatch.tolist(), "incremental_check_tolerance_pawns": incremental_tolerance})
        report["builds"][build] = result
    first_executable = next(iter(executables.values()))
    report["malformed_weight_rejection"] = negative_load_tests(first_executable, name, weights, out, env)
    if not args.skip_benchmark:
        report["torch_single_position_benchmark"] = benchmark_torch(model, inputs, args.rounds, args.min_seconds)
        baseline = report["torch_single_position_benchmark"]["median_ns_per_position"]
        for result in report["builds"].values():
            result["cpp_vs_torch_latency_ratio"] = baseline / result["benchmark_prebuilt_features"]["median_ns_per_position"]
    report["passed"] = (report["parameter_finite"] and report["malformed_weight_rejection"]["passed"]
                        and all(result["passed"] for result in report["builds"].values()))
    write_json(out / f"{name}-verification.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path("data") / RELEASE)
    parser.add_argument("--small-checkpoint", type=Path, default=Path("runs") / RELEASE / "small/best.pt")
    parser.add_argument("--large-checkpoint", type=Path, default=Path("runs") / RELEASE / "large/best.pt")
    parser.add_argument("--weights-root", type=Path, default=Path("../../engines/Neural Networks"))
    parser.add_argument("--output", type=Path, default=Path("reports") / f"cpp-inference-{RELEASE}")
    parser.add_argument("--compiler")
    parser.add_argument("--models", nargs="+", choices=("small", "large"), default=["small", "large"])
    parser.add_argument("--builds", nargs="+", choices=("portable", "avx2"), default=["portable", "avx2"])
    parser.add_argument("--validation-positions", type=int, default=256)
    parser.add_argument("--seed", type=int, default=20261027)
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--min-seconds", type=float, default=0.1)
    parser.add_argument("--atol", type=float, default=2e-4)
    parser.add_argument("--rtol", type=float, default=2e-5)
    parser.add_argument("--skip-benchmark", action="store_true")
    args = parser.parse_args()
    if not 128 <= args.validation_positions <= 10000 or not 1 <= args.rounds <= 31 or not 0.01 <= args.min_seconds <= 5:
        parser.error("Require 128–10000 validation rows, 1–31 rounds, 0.01–5 minimum seconds")
    if not math.isfinite(args.atol) or not math.isfinite(args.rtol) or args.atol < 0 or args.rtol < 0:
        parser.error("Tolerances must be finite and nonnegative")
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    out, include = resolve(args.output), resolve(args.weights_root)
    out.mkdir(parents=True, exist_ok=True)
    rows, description = corpus(resolve(args.data), args.validation_positions, args.seed)
    write_json(out / "corpus.json", description)
    compiler = find_compiler(args.compiler)
    env = dict(os.environ)
    env["PATH"] = str(compiler.parent) + os.pathsep + env.get("PATH", "")
    version = run([compiler, "--version"], env).stdout
    suffix = ".exe" if os.name == "nt" else ""
    portable = out / ("verify-cpp-portable" + suffix)
    builds = {"portable": compile_driver(compiler, include, portable, "portable", env)}
    capability = json.loads(run([portable, "--cpu-info"], env).stdout)
    executables = {"portable": portable} if "portable" in args.builds else {}
    skipped = []
    if "avx2" in args.builds:
        if capability["runtime_avx2"] and capability["runtime_fma"]:
            avx = out / ("verify-cpp-avx2" + suffix)
            builds["avx2"] = compile_driver(compiler, include, avx, "avx2", env)
            executables["avx2"] = avx
        else:
            skipped.append("AVX2/FMA build skipped: runtime CPU support not detected")
    if not executables:
        raise ValueError("No requested build can execute on this host")
    summary = {"schema": "chesslab.cpp-verification.v1", "created_at_utc": datetime.now(timezone.utc).isoformat(),
               "harness_python_sha256": sha256_file(Path(__file__)),
               "host": {"platform": platform.platform(), "machine": platform.machine(), "processor": platform.processor()},
               "torch": {"version": torch.__version__, "threads": torch.get_num_threads(),
                         "interop_threads": torch.get_num_interop_threads(), "config": torch.__config__.show()},
               "compiler": {"path": str(compiler), "version": version}, "compilation": builds,
               "runtime_cpu": capability, "skipped": skipped, "corpus": {k: v for k, v in description.items() if k != "positions"},
               "benchmark_scope": "Warm CPU serial per-position inference. C++ prebuilt sparse features and packed-adapter timing reported separately; Torch pre-expanded FP32 inputs include Python/PyTorch dispatch. No thread-affinity pin or host-isolation guarantee. Four-thread checks test correctness only, not speed.",
               "models": {}}
    for name in dict.fromkeys(args.models):
        print(f"Verifying {name}: {len(rows)} positions, {', '.join(executables)}", flush=True)
        result = verify_one(name, getattr(args, name + "_checkpoint"), include, rows, out, executables, env, args)
        summary["models"][name] = {"passed": result["passed"], "report": f"{name}-verification.json"}
        write_json(out / "summary.json", summary)
    summary["passed"] = all(result["passed"] for result in summary["models"].values())
    write_json(out / "summary.json", summary)
    print(json.dumps({"passed": summary["passed"], "output": str(out), "models": summary["models"]}, indent=2))
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        raise SystemExit(f"C++ verification failed: {error}")
