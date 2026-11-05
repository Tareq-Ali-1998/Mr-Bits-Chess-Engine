"""Offline legality/beam/PVS/cache checks for family v3.6/v3.7/v3.8.

Never starts a bot, Stockfish, database writer or cloud job. A Windows policy
block is recorded and stops that executable; it is never retried or bypassed.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import queue
import shutil
import subprocess
import tempfile
import threading
import time

import chess

from run_kernel_v7_tests import fixture_boards, perft, write_report
from kernel_family_versions import canonical_version, legacy_version, kernel_source

ENGINES = Path(__file__).resolve().parents[1]
REPORTS = ENGINES.parent / "Mr Bits Docs/ChatGPT Neural Network Lab/diagnostics/kernel-family-v3.6-v3.8"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def rounded_cp(value):
    value = min(99999, max(-99999, value))
    return math.floor(value + .5) if value >= 0 else math.ceil(value - .5)


class Diagnostic:
    def __init__(self, executable, weights, env, timeout):
        self.process = subprocess.Popen([str(executable), str(weights)], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
        self.output = queue.Queue()
        def reader():
            for line in self.process.stdout:
                self.output.put(line)
            self.output.put(None)
        threading.Thread(target=reader, daemon=True).start()
        self.timeout = timeout
        self.transcript = []
        self.checks = 0

    def ask(self, **request):
        request.setdefault("id", str(len(self.transcript)))
        self.process.stdin.write(json.dumps(request) + "\n")
        self.process.stdin.flush()
        line = self.output.get(timeout=self.timeout)
        if line is None:
            raise RuntimeError("Diagnostic exited before its next reply: " + self.process.stderr.read())
        answer = json.loads(line)
        assert answer.get("id") == request["id"], (request, answer)
        self.transcript.append({"request": request, "reply": answer})
        self.checks += answer.get("check_count", 0)
        return answer

    def close(self):
        self.process.stdin.close()
        self.process.wait(timeout=self.timeout)
        stderr = self.process.stderr.read()
        assert self.process.returncode == 0, stderr
        self.process.stdout.close()
        self.process.stderr.close()

    def terminate(self):
        if self.process.poll() is None:
            self.process.kill()
            self.process.wait()


def check_position(api, name, board, depth):
    answer = api.ask(id=name, op="position", fen=board.fen(en_passant="fen"),
                     engineWhite=bool(board.turn), perftDepth=depth)
    assert answer["ok"] and answer["restored"], answer
    assert sorted(answer["legal"]) == sorted(m.uci() for m in board.legal_moves), answer
    assert answer["inCheck"] == board.is_check(), answer
    assert answer["perft"] == perft(board, depth), answer
    api.checks += 5


def check_static(api, version, boards):
    for index, board in enumerate(boards):
        scores = []
        for color in (False, True):
            answer = api.ask(id=f"static-{index}-{color}", op="position",
                fen=board.fen(en_passant="fen"), engineWhite=color, staticOnly=True)
            assert answer["ok"] and answer["restored"], answer
            if version == 9:
                expected = rounded_cp(answer["legacyCp"])
            elif version == 10:
                expected = rounded_cp(.5 * answer["legacyCp"] +
                    .5 * answer["nnWhitePawns"] * 100 * (1 if color else -1))
            else:
                expected = rounded_cp(answer["nnWhitePawns"] * 100 * (1 if color else -1))
            assert answer["staticScore"] == expected, answer
            scores.append(expected)
            api.checks += 3
        assert scores[0] == -scores[1], (board.fen(), scores)
        api.checks += 1


def check_beam_ordering(api, boards):
    for index, board in enumerate(boards):
        for color in (False, True):
            answer = api.ask(id=f"order-{index}-{color}", op="ordering",
                fen=board.fen(en_passant="fen"), engineWhite=color, depth=1)
            assert answer["ok"] and answer["restored"], answer
            expected = sorted(answer["largeScores"], key=lambda row: row["whitePawns"], reverse=bool(board.turn))[:3]
            assert answer["ordered"] == [row["move"] for row in expected], answer
            stats = answer["orderStats"]
            assert stats["largeRankedMoves"] == len(answer["inputMoves"]), answer
            assert stats["beamDiscardedMoves"] == max(0, len(answer["inputMoves"]) - 3), answer
            assert stats["smallOrderingCalls"] == stats["heuristicOrderingCalls"] == 0, answer
            api.checks += 6
    initial = chess.Board()
    for names in ([], ["e2e4"], ["e2e4", "g1f3"]):
        answer = api.ask(op="ordering", fen=initial.fen(), moves=names, depth=0, expired=True)
        assert answer["ok"] and answer["restored"], answer
        stats = answer["orderStats"]
        assert stats["largeOrderingCalls"] == (1 if names else 0), answer
        assert stats["largeRankedMoves"] == len(names), answer
        assert len(answer["ordered"]) == len(names), answer
        api.checks += 4


def beam_reference(api, board, depth, engine_white, facts, qremaining=6, ply=0):
    """Independent Python legal tree, top-three minimax, and bounded Q policy.

    C++ supplies only static values and direct Large child outputs; Python chooses
    the beam and recursively combines it. The selector/search under test is never
    called when gathering a node's facts.
    """
    if board.is_checkmate():
        return (-1000000 + min(ply, 128)) if board.turn == engine_white else (1000000 - min(ply, 128))
    if board.is_stalemate():
        return 0
    fen = board.fen(en_passant="fen")
    qonly = depth == 0
    key = (fen, engine_white, qonly)
    if key not in facts:
        response = api.ask(op="reference_node", fen=fen, engineWhite=engine_white, qOnly=qonly)
        assert response["ok"] and response["restored"], response
        assert sorted(response["legal"]) == sorted(m.uci() for m in board.legal_moves), response
        facts[key] = response
        api.checks += 2
    node = facts[key]
    maximizing = board.turn == engine_white
    if depth == 0 and qremaining == 0:
        return node["staticScore"]
    eligible = list(node["largeScores"])
    if qonly:
        expected_eligible = {m.uci() for m in board.legal_moves
            if board.is_check() or board.is_capture(m) or m.promotion}
        assert {r["move"] for r in eligible} == expected_eligible, (fen, eligible, expected_eligible)
        api.checks += 1
    selected = sorted(eligible, key=lambda row: row["whitePawns"], reverse=bool(board.turn))[:3]
    scores = [] if depth > 0 or board.is_check() else [node["staticScore"]]
    for row in selected:
        child = board.copy(stack=False)
        child.push_uci(row["move"])
        scores.append(beam_reference(api, child, max(0, depth - 1), engine_white,
            facts, qremaining if depth > 0 else qremaining - 1, ply + 1))
    assert scores, (fen, node)
    return max(scores) if maximizing else min(scores)


def check_beam_tree(api, boards):
    facts = {}
    for index, board in enumerate(boards):
        for color in (False, True):
            for depth in (1, 2):
                expected = beam_reference(api, board, depth, color, facts)
                answer = api.ask(id=f"beam-tree-{index}-{color}-{depth}", op="position",
                    fen=board.fen(en_passant="fen"), engineWhite=color, searchDepth=depth)
                assert answer["ok"] and answer["restored"], answer
                assert answer["searchScore"] == expected, (board.fen(), color, depth, answer, expected)
                api.checks += 3
    return len(facts)


def check_replays(api, version):
    initial = chess.Board()
    roots = [m.uci() for m in initial.legal_moves]
    black = chess.Board(); black.push_uci("e2e4")
    cases = [("white-all", [], True, roots),
             ("black-all", ["e2e4"], False, [m.uci() for m in black.legal_moves]),
             ("empty-subset", [], True, []),
             ("fools-mate", ["f2f3", "e7e5", "g2g4", "d8h4"], True, [])]
    for name, history, color, candidates in cases:
        answer = api.ask(op="replay", id=name, moves=history, engineWhite=color, roots=candidates, maxDepth=2)
        assert answer["ok"], answer
        result = answer["answer"]
        assert result["searchPolicy"]["name"] == canonical_version(f"v{version}"), result
        if candidates:
            assert result["status"] == "ok", result
            searched = {r["move"] for r in result["rootScores"]}
            wanted_count = len(candidates) if version == 11 else min(3, len(candidates))
            assert len(searched) == wanted_count, result
            assert searched <= set(candidates) and result["bestMove"] in searched, result
            assert set(result["unsearchedRootMoves"]) == set(candidates) - searched, result
            if version != 11:
                stats = result["searchPolicy"]["counters"]
                assert stats["rootCandidatesBefore"] == len(candidates), result
                assert stats["rootCandidatesRetained"] == 3, result
                assert stats["rootCandidatesDiscarded"] == len(candidates) - 3, result
        else:
            assert result["status"] == "no_moves", result
            if name == "empty-subset": assert "terminal" not in result, result
            else: assert result["terminal"] == {"kind": "checkmate", "score": -1000000}, result
        assert result["totalNodes"] == sum(d["nodes"] for d in result["perDepth"]), result
        for d in result["perDepth"]:
            assert d["nodes"] == d["searchPolicy"]["regularNodes"] + d["searchPolicy"]["qNodes"], d
        api.checks += 7


def verify_version(version, args):
    started = time.perf_counter()
    family = canonical_version(f"v{version}")
    folder = args.report_dir / family
    report = {"schema": "mrbits.v9-v11-diagnostics.v1", "version": family, "legacy_version": f"v{version}", "status": "failed",
        "started_utc": datetime.now(timezone.utc).isoformat(), "python_chess": chess.__version__}
    env = dict(os.environ)
    env["PATH"] = str(Path(args.cxx).parent) + os.pathsep + env.get("PATH", "")
    api = None
    try:
        sources = [Path(__file__), ENGINES / "tests/kernel_family_versions.py", ENGINES / "Kernels/kernel_tools.py",
            ENGINES / "tests/kernel_v9_v11_test.cpp",
            kernel_source(ENGINES, f"v{version}"), ENGINES / "Kernels/V7 Position.hpp",
            ENGINES / ("Kernels/V11 Search.hpp" if version == 11 else "Kernels/V9 V10 Search.hpp"),
            ENGINES / "Neural Networks/common.hpp", ENGINES / "Neural Networks/Small/Small.hpp",
            ENGINES / "Neural Networks/Large/Large.hpp", ENGINES / "Neural Networks/Move Ordering.hpp"]
        report["source_sha256"] = {str(p.relative_to(ENGINES)): digest(p) for p in sources}
        report["weight_sha256"] = {name: digest(args.weights_dir / name / "weights.bin")
            for name in (("Small",) if version == 11 else ("Large",) if version == 9 else ("Small", "Large"))}
        with tempfile.TemporaryDirectory(prefix=f"mrbits-v{version}-oracle-") as temp:
            executable = Path(temp) / f"kernel_v{version}_test.exe"
            command = [args.cxx, "-std=c++17", "-O2", f"-DMRBITS_TEST_VERSION={version}", "-I", str(ENGINES),
                str(ENGINES / "tests/kernel_v9_v11_test.cpp"), "-o", str(executable)]
            compiled = subprocess.run(command, text=True, capture_output=True, env=env, timeout=args.timeout)
            report["compile"] = {"command": command, "exit_code": compiled.returncode, "stderr": compiled.stderr}
            assert compiled.returncode == 0, compiled.stderr
            report["executable_sha256"] = digest(executable)
            api = Diagnostic(executable, args.weights_dir, env, args.timeout)
            expired = api.ask(id="already-expired-before-model-load", op="replay", moves=[],
                engineWhite=True, roots=["e2e4", "g1f3"], maxDepth=0,
                allowedSeconds=0, forbidModel=True)
            assert expired["ok"] and expired["answer"]["status"] == "no_completed_depth", expired
            assert expired["answer"]["rootScores"] == [], expired
            api.checks += 2
            if version == 11:
                failure = api.ask(op="cache", fen=chess.STARTING_FEN, failure=True, forbidModel=True)
                assert failure["ok"] and failure["failureNotCached"], failure
            else:
                forbidden = api.ask(op="position", fen=chess.STARTING_FEN, staticOnly=True, forbidModel=True)
                assert forbidden["ok"] == (version == 9) and forbidden["restored"], forbidden
            fixtures = fixture_boards()
            for name, board, depth in fixtures: check_position(api, name, board, depth)
            report["oracle_positions"] = len(fixtures)
            boards = [chess.Board(), chess.Board("4r1k1/8/8/8/8/8/8/3QK3 w - - 0 1"),
                chess.Board("8/8/3k4/8/3P4/8/4K3/8 w - - 0 1"),
                chess.Board("k7/8/8/5PpK/8/8/8/8 w - g6 0 1")]
            boards.extend(b.mirror() for b in list(boards))
            check_static(api, version, boards)
            if version != 11:
                check_beam_ordering(api, boards)
                report["reference_tree_nodes"] = check_beam_tree(api, boards[:3])
            else:
                ep = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1"
                for fen in (chess.STARTING_FEN, ep):
                    answer = api.ask(op="cache", fen=fen)
                    assert answer["ok"] and answer["restored"], answer
                    report["cache_bytes"] = answer["cacheBytes"]
                all_scouts = all_researches = 0
                pvs_boards = [*boards, chess.Board("7k/5Q2/5K2/8/8/8/8/8 w - - 0 1")]
                for index, board in enumerate(pvs_boards):
                    for color in (False, True):
                        answer = api.ask(op="pvs", id=f"pvs-{index}-{color}", fen=board.fen(en_passant="fen"),
                            engineWhite=color, depth=3 if index < 3 else 2)
                        assert answer["ok"] and answer["restored"], answer
                        assert len({v["score"] for v in answer["variants"]}) == 1, answer
                        for result in answer["variants"]:
                            if result["pvs"]:
                                all_scouts += result["stats"]["pvsScouts"]
                                all_researches += result["stats"]["pvsResearches"]
                            else: assert result["stats"]["pvsScouts"] == 0, answer
                        api.checks += 4
                assert all_scouts > 0 and all_researches > 0, (all_scouts, all_researches)
                report.update(pvs_scouts_observed=all_scouts, pvs_researches_observed=all_researches)
            check_replays(api, version)
            report["status"] = "passed"
            api.close()
    except Exception as error:
        report["status"] = "blocked" if isinstance(error, OSError) and getattr(error, "winerror", None) == 4551 else "failed"
        report["error"] = f"{type(error).__name__}: {error}"
    finally:
        if api:
            api.terminate()
            report["checks"] = api.checks
            write_report(folder / "transcript.json", {"requests_and_replies": api.transcript})
        report.update(seconds=time.perf_counter() - started, completed_utc=datetime.now(timezone.utc).isoformat())
        write_report(folder / "verification.json", report)
    print(f"{family}: {report['status']}; {report.get('checks', 0)} checks; {report['seconds']:.2f}s", flush=True)
    if report["status"] != "passed": print(report.get("error", "See receipt"), flush=True)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--versions", nargs="+", choices=("v3.6", "v3.7", "v3.8", "v9", "v10", "v11", "9", "10", "11"),
                        default=["v3.6", "v3.7", "v3.8"])
    parser.add_argument("--cxx", default=shutil.which("g++"))
    parser.add_argument("--weights-dir", type=Path, default=ENGINES / "Neural Networks")
    parser.add_argument("--report-dir", type=Path, default=REPORTS)
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args(argv)
    args.versions = [int(legacy_version(value if value.startswith("v") else "v" + value)[1:])
                     for value in args.versions]
    if not args.cxx or args.timeout <= 0: parser.error("g++ and positive timeout required")
    args.cxx = shutil.which(args.cxx) or str(Path(args.cxx).resolve())
    args.weights_dir = args.weights_dir.resolve()
    reports = [verify_version(version, args) for version in args.versions]
    return 0 if all(r["status"] == "passed" for r in reports) else 1


if __name__ == "__main__":
    raise SystemExit(main())
