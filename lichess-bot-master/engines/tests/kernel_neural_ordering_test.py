"""Independent legal-child tests for the two uncalled Kernel neural sorters.

Uses python-chess and the actual trained FP32 checkpoints. Starts only an
isolated C++ test main, never the production engine main, Stockfish, or a bot.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ENGINES = Path(__file__).resolve().parents[1]
LAB = ENGINES.parent / "Mr Bits Docs" / "ChatGPT Neural Network Lab"
sys.path.insert(0, str(LAB))

import chess
import numpy as np
import torch
from chesslab.features import encode_board, expand_numpy
from chesslab.models import load_checkpoint


def fixtures():
    cases = []
    def add(name, board):
        assert board.is_valid(), name
        rows = []
        for move in board.legal_moves:
            tag = 0
            if board.is_castling(move):
                tag = 4 if chess.square_file(move.to_square) > chess.square_file(move.from_square) else 5
            elif board.is_en_passant(move):
                tag = 3
            elif move.promotion:
                tag = {chess.QUEEN: 1, chess.KNIGHT: 2, chess.ROOK: 6, chess.BISHOP: 7}[move.promotion]
            sr, sc = 7 - chess.square_rank(move.from_square), chess.square_file(move.from_square)
            dr, dc = 7 - chess.square_rank(move.to_square), chess.square_file(move.to_square)
            child = board.copy(); child.push(move)
            rows.append({"move": sr | sc << 3 | dr << 6 | dc << 9 | tag << 12,
                         "uci": move.uci(), "child": encode_board(child).tolist()})
        cases.append({"name": name, "parent": encode_board(board).tolist(), "moves": rows})
    add("start_white", chess.Board())
    board = chess.Board(); board.push_uci("e2e4"); add("black_after_e4", board)
    for name, fen in (
        ("white_both_castles", "r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1"),
        ("black_both_castles", "r3k2r/8/8/8/8/8/8/R3K2R b KQkq - 0 1"),
        ("white_ep", "4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 1"),
        ("black_ep", "4k3/8/8/8/3Pp3/8/8/4K3 b - d3 0 1"),
        ("white_promotion_capture", "1r2k3/P7/8/8/8/8/8/4K3 w - - 0 1"),
        ("black_promotion_capture", "4k3/8/8/8/8/8/p7/1R2K3 b - - 0 1"),
        ("rights_already_lost", "r3k2r/8/8/8/8/8/8/R3K2R w - - 0 1"),
        ("corner_rook_capture", "r3k2r/8/8/8/8/8/7Q/4K3 w kq - 0 1"),
    ):
        add(name, chess.Board(fen))
    children = [row for case in cases for row in case["moves"]]
    inputs = torch.from_numpy(np.stack([expand_numpy(np.array(row["child"], dtype=np.uint8)) for row in children]))
    for name in ("small", "large"):
        model, _ = load_checkpoint(LAB / "runs" / "clean-10m-20261026T080646Z" / name / "best.pt")
        with torch.inference_mode():
            scores = model(inputs).squeeze(1).tolist()
        for row, score in zip(children, scores):
            row[name] = score
    return cases


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", default=shutil.which("g++"))
    parser.add_argument("--output", type=Path, default=LAB / "diagnostics" / "kernel-neural-ordering-20261028")
    args = parser.parse_args()
    if not args.compiler:
        parser.error("g++ is required; set --compiler")
    torch.set_num_threads(1)
    out = args.output.resolve(); out.mkdir(parents=True, exist_ok=True)
    data = fixtures(); data_path = out / "fixtures.json"
    data_path.write_text(json.dumps(data, allow_nan=False) + "\n", encoding="utf-8")
    binary = out / ("test.exe" if os.name == "nt" else "test")
    command = [args.compiler, "-std=c++17", "-O2", "-I", str(ENGINES),
               str(ENGINES / "tests" / "kernel_neural_ordering_test.cpp"), "-o", str(binary)]
    env = dict(os.environ)
    env["PATH"] = str(Path(args.compiler).resolve().parent) + os.pathsep + env.get("PATH", "")
    build = subprocess.run(command, capture_output=True, text=True, env=env, timeout=180)
    (out / "compile.log").write_text(build.stdout + build.stderr, encoding="utf-8")
    build.check_returncode()
    # Verify model discovery does not require the process working directory.
    with tempfile.TemporaryDirectory() as unrelated_cwd:
        result = subprocess.run([str(binary), str(data_path)], cwd=unrelated_cwd,
                                capture_output=True, text=True, env=env, timeout=180)
    report = {"passed": result.returncode == 0, "positions": len(data),
              "unique_legal_children": sum(len(case["moves"]) for case in data),
              "engine_colors_tested": ["black", "white"], "command": command,
              "stdout": result.stdout, "stderr": result.stderr,
              "production_engine_main_started": False,
              "source_sha256": {name: hashlib.sha256((ENGINES / name).read_bytes()).hexdigest()
                                for name in ("Kernel.cpp", "Neural Networks/Move Ordering.hpp",
                                             "tests/kernel_neural_ordering_test.cpp")}}
    (out / "verification.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(result.stdout or result.stderr, end="")
    result.check_returncode()


if __name__ == "__main__":
    main()
