"""Offline v3.9 legality, strict-depth beam, undo, Q and worker-protocol checks.

Use --syntax-only while native execution is unavailable. That mode checks the
real diagnostic translation unit without creating or running an executable.
Normal mode never starts a bot, Stockfish, database writer or cloud job. A
Windows policy block ends the run; the executable is not retried or bypassed.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

import chess

from run_kernel_v7_tests import (
    fixture_boards, gather_q_positions, q_boards, reference_q, write_report,
)
from run_kernel_v9_v11_tests import Diagnostic, check_position, digest, rounded_cp

ENGINES = Path(__file__).resolve().parents[1]
BEAM_WIDTH = 10
REPORTS = ENGINES.parent / f"Mr Bits Docs/ChatGPT Neural Network Lab/diagnostics/kernel-family-v3.9-top{BEAM_WIDTH}"
CHECK_EVASIONS = "4r1k1/8/8/8/8/8/2BQ4/4K3 w - - 0 1"


def no_ordering(stats):
    assert stats["smallOrderingCalls"] == stats["heuristicOrderingCalls"] == 0, stats
    assert stats["smallRankedMoves"] == stats["beamOrderingBatches"] == 0, stats
    assert stats["beamDiscardedMoves"] == stats["beamTruncations"] == 0, stats


def model_free_checks(api):
    """Must run first: the process has not successfully loaded Small yet."""
    board = chess.Board()
    names = [move.uci() for move in reversed(list(board.legal_moves))]
    for color in (False, True):
        for depth in (0, 1, 2):
            for subset in ([], names[:1], names[:2], names[:7], names):
                for root_ordering in (False, True):
                    answer = api.ask(op="ordering", fen=board.fen(), engineWhite=color,
                        depth=depth, moves=subset, rootOrdering=root_ordering,
                        forbidModel=True)
                    assert answer["ok"] and answer["restored"], answer
                    assert answer["ordered"] == subset, answer
                    stats = answer["orderStats"]
                    no_ordering(stats)
                    assert stats["rootCandidatesBefore"] == (len(subset) if root_ordering else 0), answer
                    assert stats["rootCandidatesRetained"] == stats["rootCandidatesBefore"], answer
                    assert stats["rootCandidatesDiscarded"] == 0, answer
                    api.checks += 8
        # Even beyond the threshold, zero/one candidate needs no network call.
        for depth in (3, 6, 30):
            for subset in ([], names[:1]):
                answer = api.ask(op="ordering", fen=board.fen(), engineWhite=color,
                    depth=depth, moves=subset, forbidModel=True)
                assert answer["ok"] and answer["restored"] and answer["ordered"] == subset, answer
                no_ordering(answer["orderStats"])
                api.checks += 4
    # A failed lazy load must leave every board/global field unchanged.
    failed = api.ask(op="ordering", fen=board.fen(), depth=3, moves=names, forbidModel=True)
    assert not failed["ok"] and failed["restored"], failed
    assert "Cannot open neural weight file" in failed["error"], failed
    api.checks += 3
    expired = api.ask(op="root", fen=board.fen(), depth=4, moves=names,
        expired=True, forbidModel=True)
    assert expired["ok"] and expired["restored"] and expired["rootScores"] == [], expired
    no_ordering(expired["rootStats"])
    assert expired["rootStats"]["deadlineAborts"] > 0, expired
    api.checks += 5
    replay = api.ask(op="replay", engineWhite=True, roots=names,
        maxDepth=0, allowedSeconds=0, forbidModel=True)
    assert replay["ok"], replay
    result = replay["answer"]
    assert result["status"] == "no_completed_depth" and result["rootScores"] == [], result
    assert result["searchPolicy"]["scoreScope"] == "no_completed_iteration", result
    api.checks += 3
    for fen in ("7k/6Q1/5K2/8/8/8/8/8 b - - 0 1",
                "7k/5K2/6Q1/8/8/8/8/8 b - - 0 1"):
        terminal = chess.Board(fen)
        for color in (False, True):
            answer = api.ask(op="position", fen=fen, engineWhite=color,
                searchDepth=3, qDepth=0, forbidModel=True)
            expected = (-1000000 if terminal.turn == color else 1000000) if terminal.is_checkmate() else 0
            assert answer["ok"] and answer["restored"], answer
            assert answer["searchScore"] == answer["qScore"] == expected, answer
            no_ordering(answer["searchStats"])
            no_ordering(answer["qStats"])
            api.checks += 4


def ordering_checks(api):
    boards = [chess.Board(), chess.Board(CHECK_EVASIONS),
        chess.Board("7k/P7/8/8/8/8/8/7K w - - 0 1"),
        chess.Board("1r5k/P7/8/8/8/8/8/7K w - - 0 1"),
        chess.Board("k7/8/8/5PpK/8/8/8/8 w - g6 0 1")]
    boards.extend(board.mirror() for board in list(boards))
    assert boards[1].is_check() and boards[1].legal_moves.count() == 6
    for index, board in enumerate(boards):
        for color in (False, True):
            for depth in (2, 3, 6):
                answer = api.ask(id=f"rank-{index}-{color}-{depth}", op="ordering",
                    fen=board.fen(en_passant="fen"), engineWhite=color,
                    depth=depth, reverse=True, facts=True)
                assert answer["ok"] and answer["restored"], answer
                names = answer["inputMoves"]
                ranked = sorted(answer["smallScores"], key=lambda row: row["whitePawns"],
                    reverse=bool(board.turn))
                expected = names if depth <= 2 else [row["move"] for row in ranked[:BEAM_WIDTH]]
                assert answer["ordered"] == expected, answer
                stats = answer["orderStats"]
                if depth <= 2:
                    no_ordering(stats)
                else:
                    assert stats["smallOrderingCalls"] == stats["beamOrderingBatches"] == 1, answer
                    assert stats["smallRankedMoves"] == len(names), answer
                    assert stats["beamDiscardedMoves"] == max(0, len(names) - BEAM_WIDTH), answer
                    assert stats["beamTruncations"] == int(len(names) > BEAM_WIDTH), answer
                    assert stats["heuristicOrderingCalls"] == 0, answer
                api.checks += 8
    # Check both sides of the new ten-move boundary; smaller lists still sort.
    initial = chess.Board()
    for size in (2, 5, 6, 9, 10, 11):
        subset = [move.uci() for move in reversed(list(initial.legal_moves))][:size]
        answer = api.ask(op="ordering", fen=initial.fen(), moves=subset,
            depth=3, facts=True, rootOrdering=True)
        assert answer["ok"] and answer["restored"], answer
        expected = [row["move"] for row in sorted(answer["smallScores"],
            key=lambda row: row["whitePawns"], reverse=True)[:BEAM_WIDTH]]
        assert answer["ordered"] == expected and set(expected) <= set(subset), answer
        stats = answer["orderStats"]
        assert stats["smallRankedMoves"] == size and stats["smallOrderingCalls"] == 1, answer
        assert stats["rootCandidatesBefore"] == size, answer
        assert stats["rootCandidatesRetained"] == min(size, BEAM_WIDTH), answer
        assert stats["rootCandidatesDiscarded"] == stats["beamDiscardedMoves"] == max(0, size - BEAM_WIDTH), answer
        api.checks += 6
    return len(boards)


def static_and_q_checks(api):
    boards = [*q_boards(), chess.Board(CHECK_EVASIONS)]
    boards.extend(board.mirror() for board in list(boards))
    positions = {}
    for board in boards:
        gather_q_positions(board.copy(stack=False), 2, positions)
    values = {}
    for index, (fen, board) in enumerate(positions.items()):
        both_colors = []
        for color in (False, True):
            answer = api.ask(id=f"value-{index}-{color}", op="position",
                fen=fen, engineWhite=color, staticOnly=True)
            assert answer["ok"] and answer["restored"], answer
            expected = rounded_cp(.5 * answer["legacyCp"] +
                .5 * answer["nnWhitePawns"] * 100 * (1 if color else -1))
            assert answer["staticScore"] == expected, answer
            values[(fen, color)] = expected
            both_colors.append(expected)
            api.checks += 3
        assert both_colors[0] == -both_colors[1], (fen, both_colors)
        api.checks += 1
    for index, board in enumerate(boards):
        for color in (False, True):
            for depth in (0, 1, 2):
                answer = api.ask(id=f"q-{index}-{color}-{depth}", op="position",
                    fen=board.fen(en_passant="fen"), engineWhite=color, qDepth=depth)
                assert answer["ok"] and answer["restored"], answer
                expected = reference_q(board.copy(stack=False), depth, color, values)
                assert answer["qScore"] == expected, (expected, answer)
                no_ordering(answer["qStats"])
                if board.is_check() and board.legal_moves.count() == 6 and depth == 1:
                    # Full-window Q must visit all six legal evasions in generation order.
                    assert answer["qStats"]["qNodes"] == 7, answer
                api.checks += 5
    return len(positions)


def search_and_root_checks(api):
    boards = [chess.Board(), chess.Board().mirror(), chess.Board(CHECK_EVASIONS)]
    for index, board in enumerate(boards):
        for color in (False, True):
            for depth in (0, 1, 2, 3):
                answer = api.ask(id=f"internal-{index}-{color}-{depth}", op="position",
                    fen=board.fen(en_passant="fen"), engineWhite=color, searchDepth=depth)
                assert answer["ok"] and answer["restored"], answer
                stats = answer["searchStats"]
                assert stats["heuristicOrderingCalls"] == 0, answer
                if depth <= 2:
                    no_ordering(stats)
                else:
                    # Only this node is above depth two; its whole legal list is ranked.
                    count = board.legal_moves.count()
                    assert stats["smallOrderingCalls"] == stats["beamOrderingBatches"] == 1, answer
                    assert stats["smallRankedMoves"] == count, answer
                    assert stats["beamDiscardedMoves"] == max(0, count - BEAM_WIDTH), answer
                api.checks += 6
        # Real root entry, not just the ordering helper, including an in-check root.
        roots = [move.uci() for move in reversed(list(board.legal_moves))]
        expected = api.ask(op="ordering", fen=board.fen(), depth=3, moves=roots, facts=True)
        assert expected["ok"], expected
        for depth in (1, 2, 3):
            answer = api.ask(op="root", fen=board.fen(), engineWhite=bool(board.turn),
                depth=depth, moves=roots)
            assert answer["ok"] and answer["restored"], answer
            retained = roots if depth <= 2 else expected["ordered"]
            assert answer["retained"] == retained, answer
            assert [row["move"] for row in answer["rootScores"]] == retained, answer
            assert answer["bestMove"] in retained, answer
            stats = answer["rootStats"]
            assert stats["rootCandidatesBefore"] == len(roots), answer
            assert stats["rootCandidatesRetained"] == len(retained), answer
            assert stats["rootCandidatesDiscarded"] == len(roots) - len(retained), answer
            assert stats["heuristicOrderingCalls"] == 0, answer
            if depth <= 2:
                no_ordering(stats)
            api.checks += 9


def replay_checks(api):
    initial = chess.Board()
    black = initial.copy()
    black.push_uci("e2e4")
    cases = [("white-all", [], initial, True), ("black-all", ["e2e4"], black, False)]
    for label, history, board, color in cases:
        roots = [move.uci() for move in reversed(list(board.legal_moves))]
        ranks = api.ask(op="ordering", fen=board.fen(en_passant="fen"), engineWhite=color,
            moves=roots, depth=3, facts=True)
        assert ranks["ok"], ranks
        for depth in (2, 4):
            response = api.ask(id=f"replay-{label}-{depth}", op="replay", moves=history,
                engineWhite=color, roots=roots, maxDepth=depth, allowedSeconds=300)
            assert response["ok"], response
            result = response["answer"]
            assert result["status"] == "ok" and result["depth"] == depth, result
            policy = result["searchPolicy"]
            assert policy["name"] == "v3.9" and policy["beamWidth"] == BEAM_WIDTH and policy["minDepth"] == 3, result
            assert policy["rootBeamScope"] == "per_worker_subset", result
            assert policy["beamInCheck"] and not policy["beamInQuiescence"], result
            assert not policy["quiescenceOrdering"] and not policy["timeFallbackOrdering"], result
            assert policy["scoreScope"] == ("full_width_ordinary_search" if depth == 2 else "beam_restricted_tree"), result
            searched = [row["move"] for row in result["rootScores"]]
            expected = roots if depth == 2 else ranks["ordered"]
            assert searched == expected and result["bestMove"] in searched, result
            assert result["unsearchedRootMoves"] == [move for move in roots if move not in searched], result
            stats = policy["counters"]
            assert stats["rootCandidatesBefore"] == len(roots), result
            assert stats["rootCandidatesRetained"] == len(expected), result
            assert stats["rootCandidatesDiscarded"] == len(roots) - len(expected), result
            if depth == 2:
                no_ordering(stats)
            assert result["totalNodes"] == sum(row["nodes"] for row in result["perDepth"]), result
            for row in result["perDepth"]:
                assert row["nodes"] == row["searchPolicy"]["regularNodes"] + row["searchPolicy"]["qNodes"], row
                assert row["searchPolicy"]["heuristicOrderingCalls"] == 0, row
                assert row["scoreScope"] == ("no_completed_iteration" if not row["completed"] else
                    "beam_restricted_tree" if row["depth"] >= 3 else "full_width_ordinary_search"), row
            api.checks += 16
    # Both worker subsets exceed ten: each keeps ten, not ten globally.
    worker_history = ["e2e4", "e7e5"]
    worker_board = chess.Board()
    for move in worker_history:
        worker_board.push_uci(move)
    all_roots = [move.uci() for move in reversed(list(worker_board.legal_moves))]
    midpoint = len(all_roots) // 2
    assert midpoint > BEAM_WIDTH and len(all_roots) - midpoint > BEAM_WIDTH
    retained = []
    for worker, roots in enumerate((all_roots[:midpoint], all_roots[midpoint:])):
        response = api.ask(id=f"worker-subset-{worker}", op="replay", moves=worker_history,
            engineWhite=True, roots=roots, maxDepth=4, allowedSeconds=300)
        assert response["ok"], response
        result = response["answer"]
        searched = {row["move"] for row in result["rootScores"]}
        assert result["status"] == "ok" and result["depth"] == 4, result
        assert len(searched) == BEAM_WIDTH and searched <= set(roots), result
        assert set(result["unsearchedRootMoves"]) == set(roots) - searched, result
        assert result["searchPolicy"]["rootBeamScope"] == "per_worker_subset", result
        retained.extend(searched)
        api.checks += 5
    assert len(set(retained)) == 2 * BEAM_WIDTH, retained
    api.checks += 1
    for label, history, kind in (("empty-worker", [], None),
            ("fools-mate", ["f2f3", "e7e5", "g2g4", "d8h4"], "checkmate")):
        response = api.ask(id=label, op="replay", moves=history,
            engineWhite=True, roots=[], maxDepth=4)
        assert response["ok"] and response["answer"]["status"] == "no_moves", response
        result = response["answer"]
        assert result["rootScores"] == [] and result["unsearchedRootMoves"] == [], result
        if kind:
            assert result["terminal"] == {"kind": kind, "score": -1000000}, result
        else:
            assert "terminal" not in result, result
        api.checks += 3


def verify(args):
    started = time.perf_counter()
    report = {"schema": "mrbits.v12-diagnostics.v1", "version": "v3.9", "legacy_version": "v12", "status": "failed",
        "started_utc": datetime.now(timezone.utc).isoformat(), "python_chess": chess.__version__,
        "native_execution_requested": not args.syntax_only,
        "native_execution_performed": False,
        "scope": "Offline renamed-main V12 harness. Independent python-chess legality/perft and Q oracle; direct Small child ranking. No online bot or Stockfish."}
    env = dict(os.environ)
    env["PATH"] = str(Path(args.cxx).parent) + os.pathsep + env.get("PATH", "")
    api = None
    try:
        sources = [Path(__file__), ENGINES / "tests/kernel_family_versions.py", ENGINES / "Kernels/kernel_tools.py",
            ENGINES / "tests/kernel_v12_test.cpp",
            ENGINES / "tests/run_kernel_v7_tests.py", ENGINES / "tests/run_kernel_v9_v11_tests.py",
            ENGINES / "Kernels/v3.9/Kernel-v3.9.cpp", ENGINES / "Kernels/V7 Position.hpp",
            ENGINES / "Kernels/V12 Search.hpp", ENGINES / "Chess State.hpp",
            ENGINES / "Neural Networks/common.hpp", ENGINES / "Neural Networks/Small/Small.hpp",
            ENGINES / "Neural Networks/Large/Large.hpp",
            ENGINES / "Neural Networks/Move Ordering.hpp"]
        report["source_sha256"] = {str(path.relative_to(ENGINES)): digest(path) for path in sources}
        weights = args.weights_dir / "Small/weights.bin"
        if not args.syntax_only:
            if not weights.is_file():
                raise FileNotFoundError(f"Missing Small weights: {weights}")
            report["small_weights_sha256"] = digest(weights)
        with tempfile.TemporaryDirectory(prefix="mrbits-v12-oracle-") as temporary:
            executable = Path(temporary) / "kernel_v12_test.exe"
            command = [args.cxx, "-std=c++17", "-O2", "-I", str(ENGINES),
                str(ENGINES / "tests/kernel_v12_test.cpp")]
            command += ["-fsyntax-only"] if args.syntax_only else ["-o", str(executable)]
            compiled = subprocess.run(command, text=True, capture_output=True, env=env, timeout=args.timeout)
            report["compile"] = {"command": command, "exit_code": compiled.returncode,
                "stderr": compiled.stderr, "stdout": compiled.stdout}
            assert compiled.returncode == 0, compiled.stderr
            if args.syntax_only:
                report["status"] = "syntax_checked_execution_pending"
                report["native_execution_performed"] = False
                report["note"] = "The actual V12 translation unit passed compiler syntax checks. No executable was created or run; runtime correctness is still pending."
            else:
                report["executable_sha256"] = digest(executable)
                api = Diagnostic(executable, args.weights_dir, env, args.timeout)
                report["native_execution_performed"] = True
                report["phases"] = []
                print("model-free thresholds and failure/expiry restoration...", flush=True)
                model_free_checks(api)
                report["phases"].append({"name": "model-free thresholds and failure/expiry restoration", "status": "passed"})
                phases = (("Small direct ranking, full-list eligibility and top-ten cutoff", ordering_checks),
                    ("unchanged 50/50 values and independent unpruned Q oracle", static_and_q_checks),
                    ("ordinary search depths and real root entry", search_and_root_checks),
                    ("worker protocol, score scope and per-worker omissions", replay_checks))
                fixtures = fixture_boards()
                for name, board, depth in fixtures:
                    check_position(api, name, board, depth)
                report["oracle_positions"] = len(fixtures)
                for name, phase in phases:
                    print(name + "...", flush=True)
                    result = phase(api)
                    report["phases"].append({"name": name, "status": "passed", "result": result})
                api.close()
                report["status"] = "passed"
    except Exception as error:
        report["status"] = "blocked" if isinstance(error, OSError) and getattr(error, "winerror", None) == 4551 else "failed"
        report["error"] = f"{type(error).__name__}: {error}"
    finally:
        if api:
            api.terminate()
            report["checks"] = api.checks
            write_report(args.report_dir / "transcript.json", {"requests_and_replies": api.transcript})
        report.update(seconds=time.perf_counter() - started, completed_utc=datetime.now(timezone.utc).isoformat())
        write_report(args.report_dir / ("syntax-verification.json" if args.syntax_only else "verification.json"), report)
    print(f"v3.9: {report['status']}; {report.get('checks', 0)} runtime checks; {report['seconds']:.2f}s", flush=True)
    if report["status"] not in ("passed", "syntax_checked_execution_pending"):
        print(report.get("error", "See diagnostic report"), flush=True)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--syntax-only", action="store_true")
    parser.add_argument("--cxx", default=shutil.which("g++"))
    parser.add_argument("--weights-dir", type=Path, default=ENGINES / "Neural Networks")
    parser.add_argument("--report-dir", type=Path, default=REPORTS)
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args(argv)
    if not args.cxx or args.timeout <= 0:
        parser.error("g++ and a positive timeout are required")
    args.cxx = shutil.which(args.cxx) or str(Path(args.cxx).resolve())
    args.weights_dir = args.weights_dir.resolve()
    report = verify(args)
    return 0 if report["status"] in ("passed", "syntax_checked_execution_pending") else 1


if __name__ == "__main__":
    raise SystemExit(main())
