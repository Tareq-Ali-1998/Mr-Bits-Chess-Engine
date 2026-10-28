import contextlib
import csv
import io
import json
from pathlib import Path
import tempfile
import unittest

from chesslab.experiments import compare_runs, main
from chesslab.models import model_statistics


class ExperimentTests(unittest.TestCase):
    def test_clone_custom_activation_and_width_without_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            source = directory / "base.json"
            source.write_text(json.dumps({"model": {"name": "small"}}), encoding="utf-8")
            output = directory / "gelu.json"
            arguments = ["new", "--base", str(source), "--output", str(output),
                         "--activation", "gelu", "--hidden", "32", "16", "--epochs", "7"]
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(arguments), 0)
            result = json.loads(output.read_text())
            self.assertEqual(result["model"]["activation"], "gelu")
            self.assertEqual(result["model"]["hidden"], [32, 16])
            self.assertEqual(result["epochs"], 7)
            self.assertEqual(json.loads(source.read_text()), {"model": {"name": "small"}})
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                main(arguments)

    def test_comparison_groups_incompatible_data_and_selects_same_epoch_mae(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            runs = []
            for index, fingerprint in enumerate(["dataset-a", "dataset-a", "dataset-b"]):
                run = directory / f"run-{index}"
                run.mkdir(); runs.append(run)
                config = {"model": {"name": "small"}, "batch_size": 128}
                (run / "config.json").write_text(json.dumps(config), encoding="utf-8")
                (run / "data_manifest.json").write_text(json.dumps({"fingerprint": fingerprint}), encoding="utf-8")
                records = [{"epoch": 1, "step": 10, "val_huber": 1.0, "val_mae_cp": 20,
                            "train_seconds": 2},
                           {"epoch": 2, "step": 20, "val_huber": 0.5 + index / 10,
                            "val_mae_cp": 30, "train_seconds": 3}]
                with (run / "metrics.csv").open("w", encoding="utf-8", newline="") as stream:
                    writer = csv.DictWriter(stream, fieldnames=list(records[0]))
                    writer.writeheader(); writer.writerows(records)
            report = compare_runs(runs)
            self.assertEqual([len(group) for group in report["comparable_groups"]], [2, 1])
            row = report["comparable_groups"][0][0]
            self.assertEqual(row["best_epoch"], 2)
            self.assertEqual(row["mae_cp_at_best_epoch"], 30)
            self.assertEqual(row["training_seconds"], 5)
            self.assertEqual(row["parameters"], model_statistics("small")["parameters"])
            self.assertNotIn("test_metrics", row)


if __name__ == "__main__":
    unittest.main()
