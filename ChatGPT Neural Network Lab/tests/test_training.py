"""Small numerical checks of labels, optimization, checkpoint resume and isolation."""
from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import chess
import numpy as np
import torch

from chesslab.data import RECORD_DTYPE, compute_manifest_fingerprint, sha256_file
from chesslab.features import FEATURE_VERSION, encode_board, position_key
from chesslab.metrics import MetricAccumulator
from chesslab.models import build_model, canonical_spec, load_checkpoint, model_statistics
from chesslab.plot import render
from chesslab.train import benchmark_production, run_training, train_step, normalize_config
import chesslab.train as trainer


def fixture(directory: Path):
    counts = {"train": 24, "validation": 8, "test": 8}
    openings = {"train": ["e2e4", "e7e5"], "validation": ["d2d4", "d7d5"], "test": ["c2c4", "c7c5"]}
    for split, count in counts.items():
        records = np.zeros(count, dtype=RECORD_DTYPE)
        board = chess.Board()
        for move in openings[split]:
            board.push_uci(move)
        for index in range(count):
            if board.is_game_over():
                board = chess.Board()
            packed = encode_board(board)
            records[index]["position"] = packed
            records[index]["cp"] = (index % 5 - 2) * 70
            records[index]["depth"] = 20
            records[index]["knodes"] = 1000
            records[index]["key"] = np.frombuffer(position_key(packed), dtype=np.uint8)
            moves = list(board.legal_moves)
            board.push(moves[index % len(moves)])
        np.save(directory / f"{split}.npy", records, allow_pickle=False)
    manifest = {"schema": "chesslab.prepared.v1", "feature_version": FEATURE_VERSION,
                "counts": counts, "source": "synthetic numerical tests; not an accuracy experiment",
                "files": {f"{split}.npy": {"sha256": sha256_file(directory / f"{split}.npy")} for split in counts}}
    manifest["fingerprint"] = compute_manifest_fingerprint(manifest)
    (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


class TrainingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.data = self.directory / "data"
        self.data.mkdir()
        fixture(self.data)
        self.config = {"model": {"name": "small", "hidden": [16, 8]}, "seed": 123,
                       "epochs": 2, "batch_size": 8, "workers": 0, "cpu_threads": 1,
                       "amp": "float32", "tensorboard": False, "patience": 5, "min_delta": 0.0}

    def tearDown(self):
        self.temporary.cleanup()

    def quiet_training(self, config, run, resume=None):
        with contextlib.redirect_stdout(io.StringIO()):
            return run_training(self.data, config, run, torch.device("cpu"), resume)

    def test_counts_and_residual_signed_shape(self):
        small = model_statistics("small")
        self.assertEqual(small["parameters"], 216961)
        self.assertEqual(small["dense_macs"], 216640)
        large = build_model({"name": "large", "width": 16, "blocks": 2, "head": 8})
        self.assertEqual(sum(p.numel() for p in large.parameters()), model_statistics(large.model_spec)["parameters"])
        output = large(torch.zeros(3, 782))
        self.assertEqual(output.shape, (3, 1))
        self.assertTrue(torch.isfinite(output).all())
        self.assertEqual(model_statistics("large")["parameters"], 17858049)

    def test_raw_metrics_do_not_hide_clipped_tail(self):
        metrics = MetricAccumulator(clip_pawns=15)
        metrics.update(torch.tensor([[15.0], [0.0]]), torch.tensor([[3000.0], [100.0]]))
        result = metrics.result()
        self.assertEqual(result["mae_cp"], 800.0)
        self.assertEqual(result["target_clip_fraction"], 0.5)
        self.assertEqual(result["huber"], 0.25)
        with self.assertRaisesRegex(ValueError, "shape"):
            metrics.update(torch.zeros(2, 1), torch.zeros(2))

    def test_resume_matches_uninterrupted_training_and_refuses_mutations(self):
        complete = self.directory / "complete"
        resumed = self.directory / "resumed"
        self.quiet_training(self.config, complete)
        self.quiet_training({**self.config, "epochs": 1}, resumed)
        self.quiet_training(self.config, resumed, resumed / "last.pt")
        model_a, checkpoint_a = load_checkpoint(complete / "last.pt")
        model_b, checkpoint_b = load_checkpoint(resumed / "last.pt")
        for first, second in zip(model_a.parameters(), model_b.parameters()):
            self.assertTrue(torch.equal(first, second), "Resume changed deterministic model weights")
        self.assertEqual(checkpoint_a["step"], checkpoint_b["step"])
        self.assertEqual(checkpoint_a["best_metric"], checkpoint_b["best_metric"])
        with self.assertRaisesRegex(ValueError, "configuration changed"):
            self.quiet_training({**self.config, "epochs": 3, "batch_size": 4}, resumed, resumed / "last.pt")
        manifest_path = self.data / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["source"] = "A different valid synthetic release"
        manifest["fingerprint"] = compute_manifest_fingerprint(manifest)
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "fingerprint changed"):
            self.quiet_training({**self.config, "epochs": 3}, resumed, resumed / "last.pt")

    def test_ctrl_c_retains_complete_boundary_and_benchmark_writes_no_weights(self):
        run = self.directory / "interrupted"
        with patch("chesslab.train.train_step", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.quiet_training(self.config, run)
        _, checkpoint = load_checkpoint(run / "last.pt")
        self.assertEqual(checkpoint["epoch"], 0)
        self.assertTrue((run / "interrupted.json").is_file())
        result = benchmark_production(self.data, self.config, "cpu", steps=2, warmup=1)
        self.assertEqual(result["examples"], 16)
        self.assertGreater(result["examples_per_second"], 0)
        self.assertEqual(list(self.data.glob("*.pt")), [])

    def test_loss_updates_weights_and_plot_has_standalone_svg(self):
        self.quiet_training({**self.config, "epochs": 1}, self.directory / "plotted")
        output = render(self.directory / "plotted", self.directory / "curves.svg")
        self.assertIn("<svg", output.read_text(encoding="utf-8"))
        model = build_model({"name": "small", "hidden": [16, 8]})
        before = model[-1].weight.detach().clone()
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3)
        config = normalize_config(self.config)
        compressed = torch.from_numpy(np.stack([encode_board(chess.Board())] * 4))
        train_step(model, optimizer, (compressed, torch.full((4, 1), 500.0)), config, torch.device("cpu"))
        self.assertFalse(torch.equal(before, model[-1].weight))

    def test_custom_activations_names_and_preset_compatibility(self):
        for activation in ("relu", "gelu", "silu", "tanh"):
            for kind in ("mlp", "residual"):
                spec = {"name": f"custom_{kind}_{activation}", "kind": kind, "activation": activation}
                spec.update({"hidden": [12, 4]} if kind == "mlp" else {"width": 12, "blocks": 2, "head": 4})
                model = build_model(spec)
                result = model(torch.randn(3, 782))
                result.square().mean().backward()
                self.assertEqual(result.shape, (3, 1))
                self.assertTrue(torch.isfinite(result).all())
                self.assertTrue(all(torch.isfinite(parameter.grad).all() for parameter in model.parameters()))
                self.assertEqual(sum(p.numel() for p in model.parameters()), model_statistics(spec)["parameters"])
        for bad in ({"name": "../escape", "kind": "mlp", "hidden": [8]},
                    {"name": "custom_without_kind"}, {"name": "small", "activation": "softmax"},
                    {"name": "small", "unknown_architecture_field": True}):
            with self.assertRaises(ValueError):
                canonical_spec(bad)
        torch.manual_seed(777)
        first = build_model("small")
        torch.manual_seed(777)
        second = build_model({"name": "small", "activation": "relu"})
        for a, b in zip(first.parameters(), second.parameters()):
            self.assertTrue(torch.equal(a, b))

    def test_legacy_relu_checkpoint_resumes_with_explicit_activation(self):
        run = self.directory / "legacy"
        self.quiet_training({**self.config, "epochs": 1}, run)
        checkpoint = torch.load(run / "last.pt", weights_only=True)
        checkpoint["model_spec"].pop("activation", None)
        checkpoint["config"]["model"].pop("activation", None)
        torch.save(checkpoint, run / "last.pt")
        self.quiet_training(self.config, run, run / "last.pt")
        _, resumed = load_checkpoint(run / "last.pt")
        self.assertEqual(resumed["model_spec"]["activation"], "relu")
        self.assertEqual(resumed["epoch"], 2)

    def test_interrupt_after_real_step_replays_partial_epoch_exactly(self):
        complete = self.directory / "complete_step"
        resumed = self.directory / "interrupted_step"
        self.quiet_training(self.config, complete)
        calls = 0
        def interrupt_second(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise KeyboardInterrupt
            return train_step(*args, **kwargs)
        with patch("chesslab.train.train_step", side_effect=interrupt_second):
            with self.assertRaises(KeyboardInterrupt):
                self.quiet_training(self.config, resumed)
        self.assertEqual(load_checkpoint(resumed / "last.pt")[1]["step"], 0)
        self.quiet_training(self.config, resumed, resumed / "last.pt")
        first, a = load_checkpoint(complete / "last.pt")
        second, b = load_checkpoint(resumed / "last.pt")
        for x, y in zip(first.parameters(), second.parameters()):
            self.assertTrue(torch.equal(x, y))
        for key, state in a["optimizer"]["state"].items():
            for item, value in state.items():
                other = b["optimizer"]["state"][key][item]
                self.assertTrue(torch.equal(value, other) if torch.is_tensor(value) else value == other)

    def test_recovery_between_last_commit_and_best_logs_is_idempotent(self):
        run = self.directory / "commit_interruption"
        def interrupt_best(path, checkpoint):
            if path.name == "best.pt":
                raise KeyboardInterrupt
            return trainer_atomic_checkpoint(path, checkpoint)
        trainer_atomic_checkpoint = trainer._atomic_checkpoint
        with patch("chesslab.train._atomic_checkpoint", side_effect=interrupt_best):
            with self.assertRaises(KeyboardInterrupt):
                self.quiet_training({**self.config, "epochs": 1}, run)
        self.assertFalse((run / "best.pt").exists())
        self.assertEqual(load_checkpoint(run / "last.pt")[1]["epoch"], 1)
        with patch("chesslab.train.train_step", side_effect=AssertionError("Should not train another epoch")):
            recovered = self.quiet_training({**self.config, "epochs": 1}, run, run / "last.pt")
        self.assertEqual(recovered["status"], "already_completed")
        self.assertTrue((run / "best.pt").exists())
        self.assertTrue((run / "metrics.csv").exists())
        self.assertEqual(load_checkpoint(run / "best.pt")[1]["best_epoch"], 1)

    def test_actual_best_saved_below_min_delta_and_early_stop_not_bypassed(self):
        run = self.directory / "early_stop"
        config = {**self.config, "epochs": 5, "patience": 2, "min_delta": 0.1}
        values = iter([1.0, 0.98, 0.97])
        actual_evaluate = trainer.evaluate_model
        def validation(*args, **kwargs):
            result = actual_evaluate(*args, **kwargs)
            result["huber"] = next(values)
            return result
        with patch("chesslab.train.evaluate_model", side_effect=validation):
            result = self.quiet_training(config, run)
        self.assertEqual(result["status"], "early_stopped")
        self.assertEqual(result["epochs_completed"], 3)
        self.assertEqual(load_checkpoint(run / "best.pt")[1]["best_metric"], 0.97)
        with patch("chesslab.train.train_step", side_effect=AssertionError("Early stop must persist")):
            resumed = self.quiet_training(config, run, run / "last.pt")
        self.assertEqual(resumed["epochs_completed"], 3)

    def test_training_never_opens_test_and_benchmark_closes_on_error(self):
        datasets = []
        actual_dataset = trainer.PositionDataset
        def tracked(*args, **kwargs):
            dataset = actual_dataset(*args, **kwargs)
            datasets.append(dataset)
            return dataset
        with patch("chesslab.train.PositionDataset", side_effect=tracked):
            self.quiet_training({**self.config, "epochs": 1}, self.directory / "no_test_access")
            with patch("chesslab.train.train_step", side_effect=RuntimeError("injected benchmark failure")):
                with self.assertRaisesRegex(RuntimeError, "injected"):
                    benchmark_production(self.data, self.config, "cpu", steps=1, warmup=0)
        self.assertEqual([dataset.split for dataset in datasets], ["train", "validation", "train"])
        self.assertTrue(all(dataset._records is None for dataset in datasets))


if __name__ == "__main__":
    unittest.main()
