import argparse
import copy
import json
from pathlib import Path
import random
import tempfile
import unittest

import chess
import numpy as np

from chesslab.data import PositionDataset, compute_manifest_fingerprint, load_manifest, verify_dataset
from chesslab.features import encode_fen, position_key
from chesslab.prepare import inspect_record, prepare, split_for_key


POLICY = {"min_depth": 20, "max_depth": 80, "min_knodes": 1000, "max_abs_cp": 1500, "pv_validation": "full"}


def example_record():
    return {"fen": " ".join(chess.STARTING_FEN.split()[:4]), "evals": [
        {"depth": 24, "knodes": 2000, "pvs": [{"cp": 25, "line": "e2e4 e7e5 g1f3"}]}
    ]}


class PreparationTests(unittest.TestCase):
    def inspect(self, record):
        return inspect_record(json.dumps(record), POLICY)

    def test_select_deepest_then_nodes_first_pv_only(self):
        record = example_record()
        record["evals"].append({"depth": 25, "knodes": 3000, "pvs": [{"cp": 70, "line": "d2d4 d7d5"}, {"cp": 45, "line": "e2e4"}]})
        record["evals"].append({"depth": 25, "knodes": 4000, "pvs": [{"cp": 85, "line": "g1f3"}]})
        accepted, reason = self.inspect(record)
        self.assertEqual(reason, "accepted_candidate")
        self.assertEqual(accepted[2:], (85, 25, 4000))

    def test_no_fallback_from_mate_or_anomalous_best(self):
        for pv, depth, reason in [({"mate": 3, "line": "e2e4"}, 30, "mate_label"), ({"cp": 30, "line": "e2e4"}, 245, "depth_outside_policy")]:
            record = example_record()
            record["evals"].append({"depth": depth, "knodes": 4000, "pvs": [pv]})
            self.assertEqual(self.inspect(record)[1], reason)

    def test_rejects_illegal_later_pv_move_not_just_first(self):
        record = example_record()
        record["evals"][0]["pvs"][0]["line"] = "e2e4 e7e4"
        self.assertEqual(self.inspect(record)[1], "illegal_pv_line")

    def test_chess960_castling_notation_in_standard_board(self):
        record = example_record()
        record["fen"] = "r3k2r/8/8/8/8/8/8/R3K2R w KQkq -"
        record["evals"][0]["pvs"][0]["line"] = "e1h1 e8a8"
        self.assertEqual(self.inspect(record)[1], "accepted_candidate")

    def test_rejection_categories(self):
        for mutate, expected in [
            (lambda r: r.update(fen="8/8/8/8/8/8/8/8 w - -"), "invalid_orthodox_position"),
            (lambda r: r["evals"][0].update(knodes=999), "insufficient_search_nodes"),
            (lambda r: r["evals"][0]["pvs"][0].update(cp=1501), "extreme_cp_label"),
            (lambda r: r["evals"][0].update(depth=True), "malformed_analysis_metadata"),
        ]:
            record = copy.deepcopy(example_record()); mutate(record)
            self.assertEqual(self.inspect(record)[1], expected)

    def test_dedup_splits_manifest_and_file_integrity(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            source = directory / "fixture.jsonl"
            rng = random.Random(21)
            board = chess.Board()
            records = []
            for i in range(220):
                if board.is_game_over() or i % 40 == 0:
                    board = chess.Board()
                move = rng.choice(list(board.legal_moves))
                record = {"fen": " ".join(board.fen(en_passant="fen").split()[:4]), "evals": [{"depth": 24, "knodes": 2000, "pvs": [{"cp": i, "line": move.uci()}]}]}
                records.append(record)
                board.push(move)
            duplicate = copy.deepcopy(records[0])
            duplicate["evals"][0].update(depth=30, knodes=8000)
            duplicate["evals"][0]["pvs"][0]["cp"] = 123
            records.extend([duplicate, duplicate])
            source.write_text("\n".join(map(json.dumps, records)) + "\n", encoding="utf-8")
            args = argparse.Namespace(input=str(source), output=str(directory / "prepared"), max_positions=1000, max_records=0, workers=1, chunk_size=32, seed=20261023, sampling="reservoir", keep_index=False, **POLICY)
            manifest = prepare(args)
            self.assertEqual(manifest["audit_counts"]["records_processed"], len(records))
            self.assertGreaterEqual(manifest["audit_counts"]["duplicate_candidates"], 2)
            verify_dataset(directory / "prepared")
            allkeys = set()
            found = False
            original_key = position_key(encode_fen(records[0]["fen"]))
            for split in ("train", "validation", "test"):
                dataset = PositionDataset(directory / "prepared", split)
                for row in dataset.records:
                    key = row["key"].tobytes()
                    self.assertNotIn(key, allkeys); allkeys.add(key)
                    self.assertEqual(split_for_key(key), split)
                    if key == original_key:
                        found = True
                        self.assertEqual(int(row["cp"]), 123)
                if len(dataset):
                    packed, raw_cp = dataset[0]
                    self.assertEqual(tuple(packed.shape), (78,))
                    self.assertEqual(tuple(raw_cp.shape), (1,))
                dataset.close()
            self.assertTrue(found)
            self.assertEqual(sum(manifest["counts"].values()), len(allkeys))
            with self.assertRaises(FileExistsError):
                prepare(args)
            changed = copy.deepcopy(manifest)
            changed["quality"]["min_depth"] = 1
            manifest_path = directory / "prepared" / "manifest.json"
            manifest_path.write_text(json.dumps(changed), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "fingerprint mismatch"):
                load_manifest(directory / "prepared")
            # A timestamp is descriptive rather than part of the release identity.
            changed = copy.deepcopy(manifest)
            changed["created_utc"] = "updated descriptive timestamp"
            self.assertEqual(compute_manifest_fingerprint(changed), manifest["fingerprint"])


if __name__ == "__main__":
    unittest.main()
