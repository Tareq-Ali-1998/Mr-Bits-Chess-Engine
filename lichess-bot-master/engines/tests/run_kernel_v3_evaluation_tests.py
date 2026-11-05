"""Offline checks for V3.1--V3.4 static-scoring percentages.

--syntax-only compiles each actual variant's harness without creating/running an
executable. Normal mode exercises the real trained Small model, never a bot.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time

import chess

from run_kernel_v7_tests import q_boards, write_report
from run_kernel_v9_v11_tests import Diagnostic

ENGINES = Path(__file__).resolve().parents[1]
PROFILES = {"v3.1": (1, 100, 0), "v3.2": (2, 0, 100),
            "v3.3": (3, 80, 20), "v3.4": (4, 20, 80)}
REPORTS = ENGINES.parent / "Mr Bits Docs/ChatGPT Neural Network Lab/diagnostics/v3-evaluation-matrix-20261105"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def expected_score(white_pawns, classic_cp, engine_white, small_weight, legacy_weight):
    neural_cp = white_pawns * 100 * (1 if engine_white else -1) if small_weight else None
    if not small_weight:
        value = classic_cp
    elif not legacy_weight:
        value = neural_cp
    else:
        value = (small_weight * neural_cp + legacy_weight * classic_cp) / 100
    value = max(-99999, min(99999, value))
    return math.floor(value + .5) if value >= 0 else math.ceil(value - .5)


def reference_checks():
    cases = [(1.235, 999999, True, 100, 0, 124),
             (1.235, 999999, False, 100, 0, -124),
             (None, 321, True, 0, 100, 321),
             (None, -250000, False, 0, 100, -99999),
             (1, 200, True, 80, 20, 120),
             (1, 200, True, 20, 80, 180)]
    for row in cases:
        assert expected_score(*row[:-1]) == row[-1], row
    return len(cases)


def function_body(text, name):
    match = re.search(r"\binline\s+(?:void|bool|int)\s+" + re.escape(name) + r"\s*\(", text)
    assert match, name
    start = text.index("{", match.end())
    level = 1
    index = start + 1
    while level:
        if text[index] == "{": level += 1
        elif text[index] == "}": level -= 1
        index += 1
    # Ignore explanatory comments; keep every token of the actual search body.
    body = re.sub(r"//[^\n]*|/\*.*?\*/", "", text[start:index], flags=re.S)
    return re.sub(r"\s+", " ", body).strip()


def unchanged_search_checks():
    base = (ENGINES / "Kernels/V7 Search.hpp").read_text(encoding="utf-8")
    matrix = (ENGINES / "Kernels/V3 Evaluation Search.hpp").read_text(encoding="utf-8")
    functions = ("ShouldStartNextIteration", "DeadlineExceeded", "MateScore",
                 "CanUseNeuralOrdering", "OrderMoves", "TerminalScore", "Quiescence", "Search")
    for name in functions:
        # Error messages identify the new family; their wording is not search behavior.
        actual = function_body(matrix, name).replace('"Invalid V3 ', '"Invalid v7 ')
        assert function_body(base, name) == actual, name
    assert "std::isfinite(whitePawns)" in function_body(matrix, "EvaluateStatic")
    return list(functions)


def runtime_checks(api, version, small, legacy):
    initial = chess.Board()
    # These are first, before the model can be successfully loaded in this process.
    for fen in ("7k/6Q1/5K2/8/8/8/8/8 b - - 0 1",
                "7k/5K2/6Q1/8/8/8/8/8 b - - 0 1"):
        board = chess.Board(fen)
        for color in (False, True):
            row = api.ask(op="position", fen=fen, engineWhite=color,
                qDepth=0, searchDepth=2, forbidModel=True)
            assert row["ok"] and row["restored"], row
            expected = (-1000000 if board.turn == color else 1000000) if board.is_checkmate() else 0
            assert row["qScore"] == row["searchScore"] == expected, row
            assert row["qStats"]["staticEvaluations"] == row["searchStats"]["staticEvaluations"] == 0, row
            api.checks += 4
    missing = api.ask(op="value", fen=initial.fen(), forbidModel=True)
    assert missing["ok"] == (small == 0) and missing["restored"], missing
    if small == 0:
        assert missing["staticStats"]["smallStaticEvaluations"] == 0, missing
        q = api.ask(op="position", fen=initial.fen(), qDepth=0, forbidModel=True)
        assert q["ok"] and q["qStats"]["smallStaticEvaluations"] == 0, q
        api.checks += 2
    else:
        assert "Cannot open neural weight file" in missing.get("error", ""), missing
    api.checks += 2

    boards = [initial, *q_boards()]
    boards.extend(board.mirror() for board in list(boards))
    for board in boards:
        for color in (False, True):
            row = api.ask(op="value", fen=board.fen(en_passant="fen"), engineWhite=color)
            assert row["ok"] and row["restored"] and row["version"] == version, row
            assert (row["smallWeight"], row["legacyWeight"]) == (small, legacy), row
            expected = expected_score(row.get("nnWhitePawns"), row["legacyCp"], color, small, legacy)
            assert row["score"] == expected, row
            stats = row["staticStats"]
            assert stats["staticEvaluations"] == 1, row
            assert stats["smallStaticEvaluations"] == int(small > 0), row
            assert stats["legacyStaticEvaluations"] == int(legacy > 0), row
            assert stats["smallOrderingCalls"] == stats["heuristicOrderingCalls"] == 0, row
            cap = api.ask(op="position", fen=board.fen(en_passant="fen"), engineWhite=color, qDepth=0)
            assert cap["ok"] and cap["restored"] and cap["qScore"] == expected, cap
            assert cap["qStats"]["smallStaticEvaluations"] == int(small > 0), cap
            api.checks += 9

    # Deliberately perturb only the classic globals. The pure Small variant must
    # ignore them; mixed/classic variants must follow the formula and clamp.
    for color in (False, True):
        for engine, opponent in ((1000000, 0), (-1000000, 0), (321, -12)):
            row = api.ask(op="value", fen=initial.fen(), engineWhite=color,
                engineScore=engine, opponentScore=opponent)
            assert row["ok"] and row["restored"], row
            expected = expected_score(row.get("nnWhitePawns"), engine - opponent, color, small, legacy)
            assert row["score"] == expected, row
            if not legacy:
                original = api.ask(op="value", fen=initial.fen(), engineWhite=color)
                assert row["score"] == original["score"], (row, original)
            api.checks += 3
    # Static percentages do not alter V3.0's ordering or candidate retention.
    for board in boards[:3]:
        for depth in (1, 3):
            row = api.ask(op="ordering", fen=board.fen(en_passant="fen"), depth=depth, reverse=True)
            assert row["ok"] and row["restored"], row
            assert row["inputCount"] == row["orderedCount"] == board.legal_moves.count(), row
            assert row["orderingStats"]["staticEvaluations"] == 0, row
            api.checks += 3


def verify(version, args):
    started = time.perf_counter()
    profile, small, legacy = PROFILES[version]
    folder = args.report_dir / version
    api = None
    report = {"version": version, "small_weight": small, "legacy_weight": legacy,
        "status": "failed", "native_execution_performed": False,
        "started_utc": datetime.now(timezone.utc).isoformat()}
    env = dict(os.environ)
    env["PATH"] = str(Path(args.cxx).parent) + os.pathsep + env.get("PATH", "")
    try:
        paths = [Path(__file__), ENGINES / "tests/kernel_v3_evaluation_test.cpp",
            ENGINES / "tests/kernel_v7_test.cpp", ENGINES / "Kernels/V7 Search.hpp",
            ENGINES / "Kernels/V7 Position.hpp", ENGINES / "Kernels/V3 Evaluation Search.hpp",
            ENGINES / f"Kernels/{version}/Kernel-{version}.cpp"]
        report["source_sha256"] = {str(p.relative_to(ENGINES)): digest(p) for p in paths}
        report["python_reference_checks"] = reference_checks()
        report["unchanged_search_functions"] = unchanged_search_checks()
        with tempfile.TemporaryDirectory(prefix="mrbits-static-matrix-") as temp:
            executable = Path(temp) / f"matrix-{version}.exe"
            command = [args.cxx, "-std=c++17", "-O2", f"-DMRBITS_TEST_V3_EVAL_PROFILE={profile}",
                "-I", str(ENGINES), str(ENGINES / "tests/kernel_v3_evaluation_test.cpp")]
            command += ["-fsyntax-only"] if args.syntax_only else ["-o", str(executable)]
            compiled = subprocess.run(command, env=env, text=True, capture_output=True, timeout=args.timeout)
            report["compile"] = {"command": command, "exit_code": compiled.returncode,
                "stderr": compiled.stderr, "stdout": compiled.stdout}
            assert compiled.returncode == 0, compiled.stderr
            if args.syntax_only:
                report["status"] = "syntax_checked_runtime_pending"
            else:
                report["executable_sha256"] = digest(executable)
                report["small_weights_sha256"] = digest(args.weights_dir / "Small/weights.bin")
                api = Diagnostic(executable, args.weights_dir, env, args.timeout)
                report["native_execution_performed"] = True
                runtime_checks(api, version, small, legacy)
                api.close()
                report["status"] = "passed"
    except Exception as error:
        report["status"] = "blocked" if isinstance(error, OSError) and getattr(error, "winerror", None) == 4551 else "failed"
        report["error"] = f"{type(error).__name__}: {error}"
    finally:
        if api:
            api.terminate()
            report["runtime_checks"] = api.checks
            write_report(folder / "transcript.json", {"requests_and_replies": api.transcript})
        report["seconds"] = time.perf_counter() - started
        write_report(folder / ("syntax-verification.json" if args.syntax_only else "verification.json"), report)
    print(f"{version}: {report['status']}", flush=True)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--versions", nargs="+", choices=tuple(PROFILES), default=list(PROFILES))
    parser.add_argument("--syntax-only", action="store_true")
    parser.add_argument("--cxx", default=shutil.which("g++"))
    parser.add_argument("--weights-dir", type=Path, default=ENGINES / "Neural Networks")
    parser.add_argument("--report-dir", type=Path, default=REPORTS)
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args(argv)
    if not args.cxx or args.timeout <= 0: parser.error("g++ and a positive timeout are required")
    args.cxx = shutil.which(args.cxx) or str(Path(args.cxx).resolve())
    args.weights_dir = args.weights_dir.resolve()
    reports = [verify(version, args) for version in args.versions]
    return 0 if all(r["status"] in ("passed", "syntax_checked_runtime_pending") for r in reports) else 1


if __name__ == "__main__":
    raise SystemExit(main())
