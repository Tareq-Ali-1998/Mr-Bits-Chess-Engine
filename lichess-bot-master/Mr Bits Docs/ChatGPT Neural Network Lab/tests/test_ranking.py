import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import chess
import chess.engine
import numpy as np
import torch

from chesslab.export import export_checkpoint
from chesslab.rank import _parent_measurements, _summarize, evaluate_benchmark, rank_position, wilson_interval
from chesslab.teacher import (FEATURE_VERSION, SCHEMA, board_key, build_parent_record,
                              overlapping_keys, read_benchmark, terminal_score,
                              validate_benchmark_record, white_order_key)


class ZeroModel(torch.nn.Module):
    def forward(self, inputs):
        return inputs.sum(dim=1, keepdim=True) * 0


class SquareModel(torch.nn.Module):
    def forward(self, inputs):
        weights = torch.arange(782, device=inputs.device, dtype=torch.float32)
        return (inputs * weights).sum(dim=1, keepdim=True) / 100


class FakeEngine:
    def __init__(self):
        self.calls = []
        self.clears = 0

    def configure(self, options):
        assert options == {"Clear Hash": None}
        self.clears += 1

    def analyse(self, board, limit):
        self.calls.append((board_key(board), limit.nodes))
        return {"score": chess.engine.PovScore(chess.engine.Cp(0), chess.WHITE),
                "nodes": limit.nodes, "depth": 2}


def fake_teacher_metadata():
    return {"id": {"name": "deterministic test double"}, "sha256": "0" * 64,
            "nodes_per_child": 2,
            "score_policy": "last score update without upper/lower bound inside fixed node cap"}


class RankingTests(unittest.TestCase):
    def test_white_and_black_sort_opposite_directions(self):
        for turn in (chess.WHITE, chess.BLACK):
            board = chess.Board()
            board.turn = turn
            ranked = rank_position(SquareModel(), board.fen())["ranked"]
            scores = [row["score"]["cp"] for row in ranked]
            self.assertEqual(scores, sorted(scores, reverse=turn))
            self.assertEqual({row["move"] for row in ranked}, {m.uci() for m in board.legal_moves})

    def test_ties_are_deterministic_uci(self):
        ranked = rank_position(ZeroModel(), chess.STARTING_FEN)["ranked"]
        self.assertEqual([row["move"] for row in ranked], sorted(row["move"] for row in ranked))

    def test_exact_mate_overrides_model_for_both_colors(self):
        white = chess.Board("7k/5Q2/6K1/8/8/8/8/8 w - - 0 1")
        for board in (white, white.mirror()):
            ranked = rank_position(ZeroModel(), board.fen())["ranked"]
            self.assertEqual(ranked[0]["source"], "exact_terminal")
            self.assertEqual(ranked[0]["score"]["result"], "1-0" if board.turn else "0-1")
            move = chess.Move.from_uci(ranked[0]["move"])
            board.push(move)
            self.assertTrue(board.is_checkmate())

    def test_terminal_root_returns_no_ranked_candidates(self):
        board = chess.Board("7k/6Q1/6K1/8/8/8/8/8 b - - 0 1")
        result = rank_position(ZeroModel(), board.fen())
        self.assertEqual(result["terminal"]["result"], "1-0")
        self.assertEqual(result["ranked"], [])

    def test_mate_distance_and_draw_ordering(self):
        winning = {"kind": "mate", "winner": "white", "mate": 3}
        faster = {"kind": "mate", "winner": "white", "mate": 1}
        losing = {"kind": "mate", "winner": "black", "mate": 3}
        delay = {"kind": "mate", "winner": "black", "mate": 5}
        self.assertGreater(white_order_key(faster), white_order_key(winning))
        self.assertGreater(white_order_key(winning), white_order_key({"kind": "cp", "cp": 9000}))
        self.assertGreater(white_order_key(delay), white_order_key(losing))
        self.assertEqual(white_order_key({"kind": "cp", "cp": 0}),
                         white_order_key({"kind": "terminal", "result": "1/2-1/2"}))

    def test_teacher_searches_each_nonterminal_child_independently(self):
        engine = FakeEngine()
        board = chess.Board()
        record = build_parent_record(board, engine, nodes=321)
        self.assertEqual(len(engine.calls), 20)
        self.assertEqual(engine.clears, 20)
        self.assertTrue(all(nodes == 321 for _, nodes in engine.calls))
        self.assertEqual(len(record["children"]), board.legal_moves.count())
        validate_benchmark_record(record)

    def test_last_completed_score_is_retained_when_search_ends_on_bound(self):
        class Analysis:
            def __init__(self):
                self.info = {"nodes": 100}
            def __enter__(self):
                return self
            def __exit__(self, *_):
                return False
            def __iter__(self):
                yield {"score": chess.engine.PovScore(chess.engine.Cp(12), chess.WHITE), "depth": 3, "nodes": 60}
                yield {"score": chess.engine.PovScore(chess.engine.Cp(999), chess.WHITE), "depth": 4, "nodes": 100, "lowerbound": True}
        class StreamingEngine(FakeEngine):
            def analysis(self, board, limit):
                return Analysis()
        record = build_parent_record(chess.Board(), StreamingEngine(), nodes=100)
        for child in record["children"]:
            self.assertEqual(child["score"], {"kind": "cp", "cp": 12})
            self.assertEqual(child["nodes"], 100)
            self.assertEqual(child["score_nodes"], 60)
            self.assertEqual(child["depth"], 3)

    def test_teacher_terminal_children_are_exact(self):
        board = chess.Board("7k/5Q2/6K1/8/8/8/8/8 w - - 0 1")
        record = build_parent_record(board, FakeEngine(), nodes=20)
        terminals = [child for child in record["children"] if child["score"]["kind"] == "terminal"]
        self.assertTrue(terminals)
        self.assertTrue(all(child["nodes"] == 0 for child in terminals))

    def test_partial_duplicate_and_incorrect_key_rejected(self):
        record = build_parent_record(chess.Board(), FakeEngine(), nodes=2)
        partial = copy.deepcopy(record)
        partial["children"].pop()
        duplicate = copy.deepcopy(record)
        duplicate["children"][-1] = duplicate["children"][0]
        wrong = copy.deepcopy(record)
        wrong["children"][0]["child_key"] = "00" * 16
        for malformed in (partial, duplicate, wrong):
            with self.assertRaises(ValueError):
                validate_benchmark_record(malformed)
        impossible_mate = copy.deepcopy(record)
        impossible_mate["children"][0]["score"] = {"kind": "mate", "mate": 0, "winner": "white"}
        with self.assertRaisesRegex(ValueError, "mate in zero"):
            validate_benchmark_record(impossible_mate)

    def test_tied_best_and_recall_denominator(self):
        record = build_parent_record(chess.Board(), FakeEngine(), nodes=2)
        ranked = rank_position(ZeroModel(), record["fen"])["ranked"]
        # Any equal best teacher move counts, not just one arbitrarily chosen PV.
        for child in record["children"]:
            child["score"]["cp"] = 10 if child["move"] in (ranked[0]["move"], ranked[3]["move"]) else 0
        metrics = _parent_measurements(record, ranked, near_cp=25)
        self.assertEqual(len(metrics["best_teacher_moves"]), 2)
        report = _summarize([metrics], near_cp=25)
        self.assertEqual(report["strict_best_recall"]["@1"]["successes"], 1)
        self.assertEqual(report["strict_best_recall"]["@5"]["total"], 1)
        self.assertEqual(report["strict_best_recall"]["@7"]["total"], 1)

    def test_near_best_is_not_strict_best_and_regret_sign(self):
        for turn in (chess.WHITE, chess.BLACK):
            board = chess.Board()
            board.turn = turn
            record = build_parent_record(board, FakeEngine(), nodes=2)
            ranked = rank_position(ZeroModel(), record["fen"])["ranked"]
            chosen = ranked[0]["move"]
            best = ranked[-1]["move"]
            for child in record["children"]:
                child["score"]["cp"] = 100 * (1 if turn else -1) if child["move"] == best else 80 * (1 if turn else -1)
            metric = _parent_measurements(record, ranked, near_cp=25)
            self.assertEqual(metric["neural_top1"], chosen)
            self.assertFalse(metric["strict_best"]["1"])
            self.assertTrue(metric["near_best"]["1"])
            self.assertEqual(metric["top1_cp_regret"], 20)

    def test_void_key_scan_preserves_zero_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            key = b"a" + bytes(15)
            dtype = np.dtype([("key", "u1", (16,))])
            for split in ("train", "validation"):
                rows = np.zeros(1, dtype=dtype)
                rows["key"][0] = np.frombuffer(key if split == "train" else b"b" * 16, dtype=np.uint8)
                np.save(directory / f"{split}.npy", rows)
            self.assertEqual(overlapping_keys(directory, {key, b"c" * 16}), {key})

    def test_wilson_uses_real_parent_count(self):
        self.assertIsNone(wilson_interval(0, 0)["rate"])
        interval = wilson_interval(1, 1)
        self.assertEqual(interval["total"], 1)
        self.assertLess(interval["wilson95"][0], .3)
        self.assertGreater(interval["wilson95"][1], .99)

    def test_reader_rejects_partial_benchmark_and_unverified_header(self):
        record = build_parent_record(chess.Board(), FakeEngine(), nodes=2)
        header = {"type": "header", "schema": SCHEMA, "feature_version": FEATURE_VERSION,
                  "score_pov": "white", "data_fingerprint": "test",
                  "teacher": fake_teacher_metadata(),
                  "selected_parent_keys": [record["parent_key"], "00" * 16],
                  "leakage": {"verified": True, "excluded_splits": ["train", "validation"]}}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "benchmark.jsonl"
            path.write_text(json.dumps(header) + "\n" + json.dumps(record) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "incomplete"):
                read_benchmark(path)
            header["leakage"]["verified"] = False
            path.write_text(json.dumps(header) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "verified"):
                read_benchmark(path)

    def test_complete_benchmark_report_counts_and_fingerprint(self):
        records = []
        for turn in (chess.WHITE, chess.BLACK):
            board = chess.Board()
            board.turn = turn
            record = build_parent_record(board, FakeEngine(), nodes=2)
            ranked = rank_position(ZeroModel(), record["fen"])["ranked"]
            best = ranked[0]["move"] if turn else ranked[-1]["move"]
            for child in record["children"]:
                child["score"]["cp"] = (100 if turn else -100) if child["move"] == best else 0
            records.append(record)
        header = {"type": "header", "schema": SCHEMA, "feature_version": FEATURE_VERSION,
                  "score_pov": "white", "data_fingerprint": "expected", "teacher": fake_teacher_metadata(),
                  "selected_parent_keys": [record["parent_key"] for record in records],
                  "leakage": {"verified": True, "excluded_splits": ["train", "validation"]}}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "benchmark.jsonl"
            path.write_text("\n".join(json.dumps(row) for row in [header, *records]) + "\n", encoding="utf-8")
            report = evaluate_benchmark(ZeroModel(), path, expected_data_fingerprint="expected")
            self.assertEqual(report["overall"]["strict_best_recall"]["@1"]["total"], 2)
            self.assertEqual(report["overall"]["strict_best_recall"]["@1"]["rate"], .5)
            self.assertEqual(report["by_turn"]["black"]["parents"], 1)
            self.assertEqual(report["overall"]["cp_regret"]["mean"], 50)
            self.assertEqual(report["ranking_timing"]["timed_parents"], 2)
            self.assertEqual(report["overall"]["legal_move_coverage"]["min"], 20)
            with self.assertRaisesRegex(ValueError, "different prepared"):
                evaluate_benchmark(ZeroModel(), path, expected_data_fingerprint="wrong")

    def test_export_checks_serialized_model_and_refuses_overwrite(self):
        model = torch.nn.Sequential(torch.nn.Linear(782, 8), torch.nn.ReLU(), torch.nn.Linear(8, 1)).eval()
        checkpoint = {"model_spec": {"name": "test"}, "target": {"perspective": "white", "units": "pawns", "clip_pawns": 15}}
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "dense.pt"
            source = Path(folder) / "source.pt"
            source.write_bytes(b"mock source checkpoint")
            with patch("chesslab.export.load_checkpoint", return_value=(model, checkpoint)):
                manifest = export_checkpoint(source, target, samples=7)
                self.assertTrue(target.is_file())
                self.assertTrue(target.with_suffix(".pt.json").is_file())
                self.assertLess(manifest["validation"]["max_abs_error"], 1e-5)
                self.assertEqual(torch.jit.load(str(target))(torch.zeros(3, 782)).shape, (3, 1))
                with self.assertRaises(FileExistsError):
                    export_checkpoint(source, target)
                original = target.read_bytes()
                self.assertEqual(export_checkpoint(source, target, reuse_existing=True), manifest)
                self.assertEqual(target.read_bytes(), original)
                target.write_bytes(original + b"corrupted")
                with self.assertRaises(FileExistsError):
                    export_checkpoint(source, target, reuse_existing=True)
                target.write_bytes(original)
                source.write_bytes(b"different checkpoint")
                with self.assertRaises(FileExistsError):
                    export_checkpoint(source, target, reuse_existing=True)

    def test_export_non_relu_activations(self):
        checkpoint = {"model_spec": {"name": "custom"},
                      "target": {"perspective": "white", "units": "pawns", "clip_pawns": 15}}
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "source.pt"
            source.write_bytes(b"mock source checkpoint")
            for name, activation in (("gelu", torch.nn.GELU()), ("silu", torch.nn.SiLU()), ("tanh", torch.nn.Tanh())):
                model = torch.nn.Sequential(torch.nn.Linear(782, 8), activation, torch.nn.Linear(8, 1)).eval()
                with patch("chesslab.export.load_checkpoint", return_value=(model, checkpoint)):
                    result = export_checkpoint(source, Path(folder) / f"{name}.pt", samples=9)
                    self.assertLess(result["validation"]["max_abs_error"], 1e-5)


if __name__ == "__main__":
    unittest.main()
