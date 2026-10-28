"""Repeat the saved v3/v4 policy diagnostics without starting a bot or Stockfish.

From engines: python tests/run_kernel_policy_tests.py
Needs python-chess and a Windows/MinGW C++17 compiler. Executables are temporary;
fixtures, checksums, compiler receipts and measured results are saved as JSON.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import tempfile
import time

import chess

ENGINES = Path(__file__).resolve().parents[1]
DEFAULT_REPORT_DIR = ENGINES.parent / "Mr Bits Docs" / "ChatGPT Neural Network Lab" / "diagnostics" / "kernel-versions-20261028"
PIECE_TYPES = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 4,
               chess.ROOK: 5, chess.QUEEN: 6, chess.KING: 7}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def cells(board):
    result = []
    for row in range(8):
        for column in range(8):
            piece = board.piece_at(chess.square(column, 7 - row))
            result.append(0 if piece is None else PIECE_TYPES[piece.piece_type] + (8 if piece.color else 0))
    return result


def encoded(move, board):
    sr, sc = (move.from_square ^ 56) // 8, chess.square_file(move.from_square)
    dr, dc = (move.to_square ^ 56) // 8, chess.square_file(move.to_square)
    tag = {chess.QUEEN: 1, chess.KNIGHT: 2, chess.ROOK: 6, chess.BISHOP: 7}.get(move.promotion, 0)
    if board.is_en_passant(move):
        tag = 3
    elif board.is_castling(move):
        tag = 4 if dc == 6 else 5
    return sr | (sc << 3) | (dr << 6) | (dc << 9) | (tag << 12)


def v3_fixtures():
    """Reconstruct the same 149 focused fixtures used in the temporary run.

    Missing/duplicate kings, adjacent enemy kings, repeated candidates, and the
    final king capture are deliberate synthetic guard/terminal-scheme tests.
    They are not represented as legal game positions or online games.
    """
    cases = []
    def base(color, square):
        board = chess.Board(None)
        board.turn = color
        board.set_piece_at(square, chess.Piece(chess.KING, color))
        board.set_piece_at(chess.A8 if color else chess.A1, chess.Piece(chess.KING, not color))
        return board
    def attack(name, board, color, answer=None):
        if answer is None:
            answer = board.is_attacked_by(not color, board.king(color))
        cases.append({"id": name, "kind": "attack_guard", "fen": board.fen(en_passant="fen"),
                      "input": "A " + str(int(color)) + " " + " ".join(map(str, cells(board))),
                      "expected": str(int(answer))})
    for color, king in ((True, chess.E4), (False, chess.E5)):
        prefix = "white" if color else "black"
        enemy = not color
        attack(prefix + "_unattacked", base(color, king), color)
        for dr, dc in ((-2, -1), (-2, 1), (-1, -2), (-1, 2), (1, -2), (1, 2), (2, -1), (2, 1)):
            board = base(color, king)
            square = chess.square(chess.square_file(king) + dc, chess.square_rank(king) + dr)
            board.set_piece_at(square, chess.Piece(chess.KNIGHT, enemy))
            attack(f"{prefix}_knight_{dr}_{dc}", board, color)
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                if dr == dc == 0:
                    continue
                for piece_type in (chess.QUEEN, chess.BISHOP, chess.ROOK):
                    board = base(color, king)
                    square = chess.square(chess.square_file(king) + 2 * dc, chess.square_rank(king) + 2 * dr)
                    board.set_piece_at(square, chess.Piece(piece_type, enemy))
                    name = f"{prefix}_{chess.piece_name(piece_type)}_ray_{dr}_{dc}"
                    attack(name, board, color)
                    blocker = chess.square(chess.square_file(king) + dc, chess.square_rank(king) + dr)
                    board.set_piece_at(blocker, chess.Piece(chess.PAWN, color))
                    attack(name + "_blocked", board, color)
                board = base(color, king)
                board.remove_piece_at(board.king(enemy))
                board.set_piece_at(chess.square(chess.square_file(king) + dc, chess.square_rank(king) + dr),
                                   chess.Piece(chess.KING, enemy))
                attack(f"{prefix}_adjacent_king_{dr}_{dc}", board, color)
        for dr in (-1, 1):
            for dc in (-1, 1):
                board = base(color, king)
                board.set_piece_at(chess.square(chess.square_file(king) + dc, chess.square_rank(king) + dr),
                                   chess.Piece(chess.PAWN, enemy))
                attack(f"{prefix}_pawn_{dr}_{dc}", board, color)
        board = base(color, king)
        board.remove_piece_at(king)
        attack(prefix + "_missing_king_keep_all", board, color, True)
        board = base(color, king)
        board.set_piece_at(chess.B3, chess.Piece(chess.KING, color))
        attack(prefix + "_duplicate_king_keep_all", board, color, True)
    def retention(name, board, moves, keep_all=False):
        values = [encoded(move, board) for move in moves]
        if keep_all:
            kept = values
        else:
            kept, quiet = [], 0
            for move, value in zip(moves, values):
                if board.is_capture(move) or move.promotion:
                    kept.append(value)
                elif quiet < 8:
                    kept.append(value)
                    quiet += 1
        cases.append({"id": name, "kind": "root_retention", "fen": board.fen(en_passant="fen"),
                      "input": "R " + str(int(board.turn)) + " " + " ".join(map(str, cells(board))) +
                               " " + str(len(values)) + " " + " ".join(map(str, values)),
                      "expected": " ".join(map(str, [len(kept), *kept]))})
    board = chess.Board()
    retention("start_white_eight_quiet", board, list(board.legal_moves))
    board.push_uci("e2e4")
    retention("black_after_e4_eight_quiet", board, list(board.legal_moves))
    board = chess.Board("4k3/P7/8/3pP3/3r4/8/4K3/3R4 w - d6 0 1")
    assert not board.is_check()
    moves = list(board.legal_moves)
    moves.sort(key=lambda move: bool(board.is_capture(move) or move.promotion))
    assert sum(not board.is_capture(move) and not move.promotion for move in moves) > 8
    assert any(board.is_en_passant(move) for move in moves)
    assert sum(bool(move.promotion) for move in moves) == 4
    retention("late_captures_ep_all_underpromotions", board, moves)
    moves.append(chess.Move.from_uci("d1e8"))
    retention("late_king_capture_terminal_scheme", board, moves)
    board = chess.Board("k3r3/8/8/8/8/8/8/R3K3 w - - 0 1")
    assert board.is_check()
    retention("checked_king_all_candidates", board, [chess.Move.from_uci("e1d1")] * 10, True)
    board = chess.Board("k7/8/8/8/8/8/8/R7 w - - 0 1")
    retention("missing_king_all_candidates", board, [chess.Move.from_uci("a1b1")] * 10, True)
    board = chess.Board("k7/8/8/8/8/8/3K4/R3K3 w - - 0 1")
    retention("duplicate_king_all_candidates", board, [chess.Move.from_uci("a1b1")] * 10, True)
    assert len(cases) == 149
    return cases


def save(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument("--cxx", default=shutil.which("g++"))
    parser.add_argument("--only", choices=("v3", "v4", "both"), default="both")
    args = parser.parse_args(argv)
    if not args.cxx:
        parser.error("No g++ found; pass --cxx PATH_TO_COMPILER")
    compiler = shutil.which(args.cxx) or args.cxx
    args.report_dir.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ)
    environment["PATH"] = str(Path(compiler).resolve().parent) + os.pathsep + environment.get("PATH", "")
    version = subprocess.run([compiler, "--version"], capture_output=True, text=True, timeout=20, env=environment)
    receipts = []
    shared = [ENGINES / "Neural Networks" / name for name in
              ("common.hpp", "Move Ordering.hpp", "Small/Small.hpp", "Large/Large.hpp")]
    for variant in (("v3", "v4") if args.only == "both" else (args.only,)):
        started = datetime.now(timezone.utc).isoformat()
        test = ENGINES / "tests" / f"kernel_{variant}_policy_test.cpp"
        kernel = ENGINES / "Kernels" / variant / f"Kernel-{variant}.cpp"
        receipt = {"schema": "mrbits.kernel-policy-diagnostic.v1", "variant": variant,
                   "started_utc": started, "status": "failed", "python": platform.python_version(),
                   "python_chess": chess.__version__, "compiler": compiler,
                   "compiler_version": version.stdout.strip(),
                   "provenance": "Persistently reconstructed from the previous temporary harness; this JSON records a fresh measured run, not an imported earlier result.",
                   "scope": "Isolated renamed-main diagnostic only; no worker main, Stockfish, production executable, bot, or online game is started.",
                   "source_sha256": {str(path.relative_to(ENGINES)): sha256(path) for path in [test, kernel, *shared]},
                   "runner_sha256": sha256(Path(__file__))}
        try:
            with tempfile.TemporaryDirectory(prefix=f"mrbits-{variant}-policy-") as temporary:
                executable = Path(temporary) / f"kernel_{variant}_policy_test.exe"
                command = [compiler, "-std=c++17", "-O1", "-I", str(ENGINES), str(test), "-o", str(executable)]
                compiled = subprocess.run(command, cwd=ENGINES, env=environment, capture_output=True, text=True, timeout=120)
                receipt["compile"] = {"command": command, "exit_code": compiled.returncode,
                                      "stdout": compiled.stdout, "stderr": compiled.stderr}
                if compiled.returncode:
                    raise RuntimeError("Diagnostic compilation failed")
                if variant == "v3":
                    fixtures = v3_fixtures()
                    save(args.report_dir / "kernel_v3_policy_fixtures.json", fixtures)
                    command = [str(executable)]
                    data = "\n".join(case["input"] for case in fixtures) + "\n"
                else:
                    command = [str(executable), str(ENGINES / "Neural Networks")]
                    data = None
                    weights = ENGINES / "Neural Networks" / "Small" / "weights.bin"
                    receipt["small_weights_sha256"] = sha256(weights)
                clock = time.perf_counter()
                result = subprocess.run(command, input=data, cwd=ENGINES, env=environment,
                                        capture_output=True, text=True, timeout=90)
                receipt["run"] = {"command": command, "exit_code": result.returncode,
                                  "seconds": time.perf_counter() - clock,
                                  "stdout": result.stdout, "stderr": result.stderr}
                if result.returncode:
                    raise RuntimeError("Diagnostic execution failed")
                if variant == "v3":
                    actual = result.stdout.splitlines()
                    if len(actual) != len(fixtures):
                        raise AssertionError(f"Expected {len(fixtures)} fixture outputs, got {len(actual)}")
                    for fixture, output in zip(fixtures, actual):
                        if output != fixture["expected"]:
                            raise AssertionError(f"{fixture['id']}: expected {fixture['expected']!r}, got {output!r}")
                    receipt["diagnostic_cases_passed"] = len(fixtures)
                    receipt["case_ids"] = [case["id"] for case in fixtures]
                else:
                    matched = re.search(r"PASS (\d+) diagnostics", result.stdout)
                    if matched is None or int(matched.group(1)) != 84:
                        raise AssertionError("The expected 84-case v4 diagnostic completion marker is missing")
                    receipt["diagnostic_cases_passed"] = 84
                    receipt["case_groups"] = ["terminal priority with unavailable model", "all engine-color/turn combinations",
                        "actual Small depth-zero leaves in both searches", "EP and castling flags", "normalized blending, rounding and finite clamp",
                        "threshold five versus six", "state restoration", "all 20 starting root moves retained in input order"]
                receipt["status"] = "passed"
        except Exception as error:
            receipt["error"] = f"{type(error).__name__}: {error}"
        receipt["completed_utc"] = datetime.now(timezone.utc).isoformat()
        save(args.report_dir / f"kernel_{variant}_policy_test.json", receipt)
        receipts.append(receipt)
        print(f"{variant}: {receipt['status']} ({receipt.get('diagnostic_cases_passed', 0)} diagnostic cases)")
    save(args.report_dir / "policy-tests-summary.json",
         {"schema": "mrbits.kernel-policy-summary.v1", "completed_utc": datetime.now(timezone.utc).isoformat(),
          "status": "passed" if all(item["status"] == "passed" for item in receipts) else "failed",
          "reports": [{"variant": item["variant"], "status": item["status"],
                       "diagnostic_cases_passed": item.get("diagnostic_cases_passed", 0),
                       "file": f"kernel_{item['variant']}_policy_test.json"} for item in receipts],
          "repeat_command_from_engines": "python tests/run_kernel_policy_tests.py"})
    return 0 if all(item["status"] == "passed" for item in receipts) else 1


if __name__ == "__main__":
    raise SystemExit(main())
