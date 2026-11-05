"""Verify family v3.0/v3.1 against python-chess; never start the online bot.

From lichess-bot-master: python engines/tests/run_kernel_v7_tests.py
An explicit Windows policy block stops the run; it is never retried or bypassed.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import random
import shutil
import subprocess
import tempfile
import time

import chess

from kernel_family_versions import canonical_version, legacy_version, kernel_source

ENGINES = Path(__file__).resolve().parents[1]
REPORTS = ENGINES.parent / "Mr Bits Docs/ChatGPT Neural Network Lab/diagnostics/kernel-family-v3.0"


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_report(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        previous = path.read_bytes()
        try:
            passed = json.loads(previous).get("status") == "passed"
        except (ValueError, AttributeError):
            passed = False
        if passed:
            history = path.parent / "history"
            history.mkdir(exist_ok=True)
            target = history / f"{path.stem}-{hashlib.sha256(previous).hexdigest()[:12]}.json"
            if not target.exists():
                target.write_bytes(previous)
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def perft(board: chess.Board, depth: int) -> int:
    if depth == 0:
        return 1
    if depth == 1:
        return board.legal_moves.count()
    nodes = 0
    for move in list(board.legal_moves):
        board.push(move)
        nodes += perft(board, depth - 1)
        board.pop()
    return nodes


def fixture_boards():
    named = [
        ("initial", chess.STARTING_FEN, 4),
        ("kiwipete", "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1", 3),
        ("rook_ep_endgame", "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1", 3),
        ("castle_promotion", "r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1", 3),
        ("underpromotions", "rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8", 3),
        ("queenside_b_attacked", "1r5k/8/8/8/8/8/8/R3K3 w Q - 0 1", 2),
        ("castle_through_check", "k4r2/8/8/8/8/8/8/4K2R w K - 0 1", 2),
        ("ep_exposes_king", "k7/8/8/r4PpK/8/8/8/8 w - g6 0 1", 2),
        ("ep_legal", "k7/8/8/5PpK/8/8/8/8 w - g6 0 1", 2),
        ("pinned_attacker", "4k3/8/4n3/8/2K5/8/8/4R3 w - - 0 1", 2),
        ("quiet_promotions", "7k/P7/8/8/8/8/8/7K w - - 0 1", 2),
        ("capture_promotions", "1r5k/P7/8/8/8/8/8/7K w - - 0 1", 2),
        ("stalemate", "7k/5K2/6Q1/8/8/8/8/8 b - - 0 1", 2),
        ("checkmate", "7k/6Q1/5K2/8/8/8/8/8 b - - 0 1", 2),
    ]
    fixtures = []
    for name, fen, depth in named:
        board = chess.Board(fen)
        assert board.is_valid(), (name, board.status())
        fixtures.append((name, board, depth))
        mirrored = board.mirror()
        assert mirrored.is_valid()
        fixtures.append((name + "_mirrored", mirrored, min(depth, 2)))
    rng = random.Random(20261029)
    for game in range(4):
        board = chess.Board()
        for ply in range(80):
            moves = list(board.legal_moves)
            if not moves:
                break
            board.push(rng.choice(moves))
            if ply % 3 == 0:
                fixtures.append((f"seeded_{game}_{ply}", board.copy(stack=False), 0))
    return fixtures


def q_boards():
    return [chess.Board(fen) for fen in (
        "4k3/8/8/3q4/4P3/8/8/4K3 w - - 0 1",
        "4r2k/8/8/8/8/8/3B4/4K3 w - - 0 1",
        "7k/P7/8/8/8/8/8/7K w - - 0 1",
        "k7/8/8/5PpK/8/8/8/8 w - g6 0 1",
    )]


def tactical_moves(board: chess.Board):
    moves = list(board.legal_moves)
    return moves if board.is_check() else [move for move in moves if board.is_capture(move) or move.promotion]


def gather_q_positions(board, depth, output):
    if board.is_checkmate() or board.is_stalemate():
        return
    output[board.fen(en_passant="fen")] = board.copy(stack=False)
    if depth == 0:
        return
    for move in tactical_moves(board):
        board.push(move)
        gather_q_positions(board, depth - 1, output)
        board.pop()


def reference_q(board, depth, engine_white, static_scores, ply=0):
    maximizing = board.turn == engine_white
    if board.is_checkmate():
        return -1000000 + min(ply, 128) if maximizing else 1000000 - min(ply, 128)
    if board.is_stalemate():
        return 0
    stand = static_scores[(board.fen(en_passant="fen"), engine_white)]
    if depth == 0:
        return stand
    scores = [] if board.is_check() else [stand]
    for move in tactical_moves(board):
        board.push(move)
        scores.append(reference_q(board, depth - 1, engine_white, static_scores, ply + 1))
        board.pop()
    return max(scores) if maximizing else min(scores)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", choices=("v3.0", "v3.1", "v7", "v8"), default="v3.0")
    parser.add_argument("--cxx", default=shutil.which("g++"))
    parser.add_argument("--report-dir", type=Path)
    parser.add_argument("--weights-dir", type=Path, default=ENGINES / "Neural Networks")
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args(argv)
    legacy = legacy_version(args.version)
    version = canonical_version(args.version)
    args.report_dir = args.report_dir or (ENGINES.parent /
        f"Mr Bits Docs/ChatGPT Neural Network Lab/diagnostics/kernel-family-{version}")
    if not args.cxx or args.timeout <= 0:
        parser.error("g++ and a positive timeout are required")
    weights = args.weights_dir.resolve() / "Small/weights.bin"
    if not weights.is_file():
        parser.error(f"Missing Small weights: {weights}")
    compiler = shutil.which(args.cxx) or str(Path(args.cxx).resolve())
    environment = dict(os.environ)
    environment["PATH"] = str(Path(compiler).parent) + os.pathsep + environment.get("PATH", "")
    sources = [Path(__file__), ENGINES / "tests/kernel_family_versions.py", ENGINES / "Kernels/kernel_tools.py",
               ENGINES / "tests/kernel_v7_test.cpp", kernel_source(ENGINES, version),
               ENGINES / "Kernels/V7 Position.hpp", ENGINES / ("Kernels/V7 Search.hpp" if legacy == "v7"
                   else "Kernels/V3 Evaluation Search.hpp"),
               ENGINES / "Chess State.hpp", ENGINES / "Neural Networks/Move Ordering.hpp",
               ENGINES / "Neural Networks/common.hpp", ENGINES / "Neural Networks/Small/Small.hpp"]
    report = {"schema": f"mrbits.{legacy}-diagnostics.v1", "status": "failed", "version": version, "legacy_version": legacy,
              "started_utc": datetime.now(timezone.utc).isoformat(), "python_chess": chess.__version__,
              "source_sha256": {str(path.relative_to(ENGINES)): sha256(path) for path in sources},
              "small_weights_sha256": sha256(weights), "phases": [],
              "scope": f"Offline renamed-main {version} harness; independent python-chess legality/perft/Q oracle. No bot, Stockfish, database, cloud or security-setting changes."}
    started = time.perf_counter()
    checks = 0
    try:
        print("Building independent chess fixtures...", flush=True)
        fixtures = fixture_boards()
        first, expected = [], {}
        for name, board, depth in fixtures:
            case = {"id": name, "op": "position", "fen": board.fen(en_passant="fen"),
                    "engineWhite": bool(board.turn), "perftDepth": depth}
            first.append(case)
            expected[name] = {"legal": sorted(move.uci() for move in board.legal_moves),
                              "inCheck": board.is_check(), "perft": perft(board, depth)}
        terminal_boards = [board for name, board, _ in fixtures if name.startswith(("checkmate", "stalemate"))]
        for index, board in enumerate(terminal_boards):
            for engine_white in (False, True):
                name = f"terminal_{index}_{engine_white}"
                first.append({"id": name, "op": "position", "fen": board.fen(), "engineWhite": engine_white,
                              "searchDepth": 2, "qDepth": 0, "forbidModel": True})
                maximizing = board.turn == engine_white
                expected[name] = {"searchScore": (-1000000 if maximizing else 1000000) if board.is_checkmate() else 0,
                                  "qScore": (-1000000 if maximizing else 1000000) if board.is_checkmate() else 0}
        first.append({"id": "expired", "op": "position", "fen": chess.STARTING_FEN, "engineWhite": True,
                      "searchDepth": 2, "expired": True, "forbidModel": True})
        expected["expired"] = {"searchScore": 0}
        first.append({"id": "exception_restore", "op": "position", "fen": chess.STARTING_FEN,
                      "engineWhite": True, "searchDepth": 1, "forbidModel": True})
        expected["exception_restore"] = {"ok": False}

        with tempfile.TemporaryDirectory(prefix=f"mrbits-{version}-verification-") as temporary:
            executable = Path(temporary) / f"kernel_{version}_test.exe"
            command = [compiler, "-std=c++17", "-O2", "-I", str(ENGINES),
                       str(ENGINES / "tests/kernel_v7_test.cpp"), "-o", str(executable)]
            if legacy == "v8":
                command.insert(1, "-DMRBITS_TEST_V8")
            compiled = subprocess.run(command, capture_output=True, text=True, env=environment, timeout=args.timeout)
            report["compile"] = {"command": command, "exit_code": compiled.returncode,
                                 "stdout": compiled.stdout, "stderr": compiled.stderr}
            if compiled.returncode:
                raise RuntimeError(f"{version} diagnostic compilation failed")
            report["executable_sha256"] = sha256(executable)

            def execute(name, cases):
                nonlocal checks
                phase = {"name": name, "cases": len(cases), "started": False}
                report["phases"].append(phase)
                print(f"Verifying {name}: {len(cases)} cases...", flush=True)
                clock = time.perf_counter()
                executed = subprocess.run([str(executable), str(args.weights_dir.resolve())],
                                          input="\n".join(json.dumps(case) for case in cases) + "\n",
                                          capture_output=True, text=True, env=environment, timeout=args.timeout)
                phase.update(started=True, seconds=time.perf_counter() - clock, exit_code=executed.returncode,
                             stderr=executed.stderr)
                if executed.returncode:
                    phase["stdout"] = executed.stdout
                    raise RuntimeError(f"{name}: diagnostic process failed")
                replies = [json.loads(line) for line in executed.stdout.splitlines() if line.strip()]
                if len(replies) != len(cases):
                    raise AssertionError(f"{name}: expected {len(cases)} replies; got {len(replies)}")
                write_report(args.report_dir / f"{name}.json", {"requests": cases, "replies": replies})
                for request, reply in zip(cases, replies):
                    if request["id"] != reply.get("id"):
                        raise AssertionError((request["id"], reply))
                    checks += reply.get("check_count", 0)
                return replies

            replies = execute("legality-perft-terminals", first)
            for reply in replies:
                name = reply["id"]
                wanted = expected[name]
                assert reply.get("restored") is True, reply
                assert reply["ok"] == wanted.get("ok", True), reply
                for key, value in wanted.items():
                    assert reply.get(key) == value, (name, key, reply.get(key), value)
                    checks += 1
                checks += 2
            report["oracle_positions"] = len(fixtures)
            report["perft_counts"] = {name: values["perft"] for name, values in expected.items()
                                      if "perft" in values and values["perft"] > 1000}

            qpositions = {}
            tactical = q_boards()
            for board in [*tactical, *(board.mirror() for board in tactical)]:
                assert board.is_valid()
                gather_q_positions(board, 2, qpositions)
            evaluation_cases = [{"id": str(index), "op": "position", "fen": fen, "engineWhite": engine_white,
                                 "staticOnly": True}
                                for index, (fen, engine_white) in enumerate((fen, color) for fen in qpositions for color in (False, True))]
            evaluations = execute("static-evaluation-oracle", evaluation_cases)
            static_scores = {}
            for case, reply in zip(evaluation_cases, evaluations):
                assert reply["ok"] and reply["restored"], reply
                static_scores[(case["fen"], case["engineWhite"])] = reply["staticScore"]
                if legacy == "v8":
                    raw = reply["nnWhitePawns"] * 100 * (1 if case["engineWhite"] else -1)
                    raw = min(99999, max(-99999, raw))
                    # std::lround rounds halfway away from zero, unlike Python round.
                    expected_cp = math.floor(raw + .5) if raw >= 0 else math.ceil(raw - .5)
                    assert reply["staticScore"] == expected_cp, (case, reply, expected_cp)
                    assert reply["poisonedScores"] == [expected_cp, expected_cp], reply
                    checks += 2
            for fen in qpositions:
                assert static_scores[(fen, True)] == -static_scores[(fen, False)], fen
                checks += 1
            q_cases, q_expected = [], {}
            for index, board in enumerate([*tactical, *(board.mirror() for board in tactical)]):
                for color in (False, True):
                    for cap in (0, 2):
                        name = f"q_{index}_{color}_{cap}"
                        q_cases.append({"id": name, "op": "position", "fen": board.fen(en_passant="fen"),
                                        "engineWhite": color, "qDepth": cap})
                        q_expected[name] = reference_q(board, cap, color, static_scores)
            q_replies = execute("quiescence-oracle", q_cases)
            for case, reply in zip(q_cases, q_replies):
                assert reply["ok"] and reply["restored"], reply
                assert reply["qScore"] == q_expected[reply["id"]], reply
                assert reply["qStats"]["smallOrderingCalls"] == 0, reply
                if case["qDepth"] == 0 and chess.Board(case["fen"]).is_check():
                    assert reply["qStats"]["qCheckCapHits"] == 1, reply
                checks += 4

            mate_board = chess.Board("7k/5Q2/5K2/8/8/8/8/8 w - - 0 1")
            mate_cases = []
            for index, board in enumerate((mate_board, mate_board.mirror())):
                assert board.is_valid()
                for color in (False, True):
                    mate_cases.append({"id": f"mate_in_one_{index}_{color}", "op": "position",
                                       "fen": board.fen(), "engineWhite": color, "searchDepth": 1})
            for case, reply in zip(mate_cases, execute("mate-distance-search", mate_cases)):
                assert reply["ok"] and reply["restored"], reply
                maximizing = chess.Board(case["fen"]).turn == case["engineWhite"]
                assert reply["searchScore"] == (999999 if maximizing else -999999), reply
                checks += 3

            clock_values = [(1000, 0, 1, 0), (1000, 100, 10, 0), (1000, 850, 1, 1),
                            (1000, 400, 100, 10), (0, 0, 1, 1), (10, 6, .1, .1),
                            (1000, 100, 5, 10), (1000, 100, 0, 0)]
            clocks = [{"id": f"clock_{i}", "op": "clock", "allowedMs": a, "elapsedMs": e,
                       "lastIterationMs": last, "previousIterationMs": previous}
                      for i, (a, e, last, previous) in enumerate(clock_values)]
            for request, reply in zip(clocks, execute("clock-admission", clocks)):
                a, e, last, previous = (request[key] for key in ("allowedMs", "elapsedMs", "lastIterationMs", "previousIterationMs"))
                last = max(.25, last)
                growth = min(64, max(2, last / max(previous, .25))) if previous > 0 else 16
                admit = a > 0 and e < .8 * a and a - e > 5 and a - e >= max(2 * last, last * growth) * 1.25 + 5
                assert reply["ok"] and reply["admit"] == admit, reply
                checks += 1

            replay_cases = [
                {"id": "white_root", "op": "replay", "engineWhite": True, "moves": [], "roots": ["e2e4", "g1f3"], "maxDepth": 2},
                {"id": "black_root", "op": "replay", "engineWhite": False, "moves": ["e2e4"], "roots": ["e7e5", "c7c5"], "maxDepth": 2},
                {"id": "empty_subset", "op": "replay", "engineWhite": True, "moves": [], "roots": [], "maxDepth": 2},
                {"id": "invalid_history", "op": "replay", "engineWhite": True, "moves": ["e2e5"], "roots": ["g1f3"], "maxDepth": 2},
                {"id": "invalid_root", "op": "replay", "engineWhite": True, "moves": [], "roots": ["e2e5"], "maxDepth": 2},
                {"id": "duplicate_root", "op": "replay", "engineWhite": True, "moves": [], "roots": ["e2e4", "e2e4"], "maxDepth": 2},
                {"id": "wrong_side", "op": "replay", "engineWhite": False, "moves": [], "roots": ["e2e4"], "maxDepth": 2},
                {"id": "expired_request", "op": "replay", "engineWhite": True, "moves": [], "roots": ["e2e4"], "maxDepth": 0, "allowedSeconds": 0},
            ]
            for request, reply in zip(replay_cases, execute("worker-api", replay_cases)):
                if request["id"] in {"invalid_history", "invalid_root", "duplicate_root", "wrong_side"}:
                    assert not reply["ok"], reply
                else:
                    assert reply["ok"], reply
                    answer = reply["answer"]
                    expected_status = "no_moves" if not request["roots"] else "no_completed_depth" if request["id"] == "expired_request" else "ok"
                    assert answer["status"] == expected_status, reply
                    if expected_status == "ok":
                        assert answer["bestMove"] in request["roots"] and len(answer["rootScores"]) == len(request["roots"]), reply
                        assert answer["searchPolicy"]["name"] == version, reply
                        if legacy == "v8":
                            assert answer["searchPolicy"]["legacyWeight"] == 0, reply
                            assert answer["searchPolicy"]["smallWeight"] == 100, reply
                    if request["id"] == "empty_subset":
                        assert answer.get("terminal") not in ("stalemate", "checkmate"), reply
                checks += 1
            report["status"] = "passed"
    except Exception as error:
        report["status"] = "blocked" if isinstance(error, OSError) and getattr(error, "winerror", None) == 4551 else "failed"
        report["error"] = f"{type(error).__name__}: {error}"
        if isinstance(error, OSError):
            report["os_error"] = {"winerror": getattr(error, "winerror", None), "errno": error.errno,
                                  "filename": error.filename, "message": str(error)}
    report.update(checks=checks, seconds=time.perf_counter() - started, completed_utc=datetime.now(timezone.utc).isoformat())
    write_report(args.report_dir / "verification.json", report)
    print(f"{version}: {report['status']} ({checks} completed checks; {report['seconds']:.2f}s)", flush=True)
    if report["status"] != "passed":
        print(report.get("error", "See verification.json"))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
