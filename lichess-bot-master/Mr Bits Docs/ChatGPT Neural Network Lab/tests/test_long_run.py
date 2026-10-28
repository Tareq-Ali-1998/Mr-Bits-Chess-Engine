"""Exercise the Linux launcher's orchestration without a GPU or large archive."""
from __future__ import annotations

import ast
import contextlib
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

import numpy as np

from chesslab.data import (
    RECORD_DTYPE, compute_manifest_fingerprint, sha256_file, verify_dataset,
)
from chesslab.features import FEATURE_VERSION


LAB_ROOT = Path(__file__).resolve().parents[1]
SOURCE_CONTENT = b"Synthetic archive fixture; never decompressed.\n"
SOURCE_SHA256 = hashlib.sha256(SOURCE_CONTENT).hexdigest()
TAG = "unit-long-run"
POLICY = {"min_depth": 20, "max_depth": 80, "min_knodes": 1000,
          "max_abs_cp": 1500, "pv_validation": "full"}


def fixture_launcher():
    """Run the real inline program, replacing only its pinned source identity."""
    script = (LAB_ROOT / "scripts" / "09_long_run.sh").read_text(encoding="utf-8")
    source = script.split("<<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
    tree = ast.parse(source, filename="09_long_run.sh:inline")
    replacements = {"EXPECTED_BYTES": len(SOURCE_CONTENT),
                    "EXPECTED_SHA256": SOURCE_SHA256}
    found = set()
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name) and target.id in replacements:
                node.value = ast.copy_location(ast.Constant(replacements[target.id]), node.value)
                found.add(target.id)
    if found != set(replacements):
        raise AssertionError("Launcher source identity assignments changed; review this harness")
    return compile(ast.fix_missing_locations(tree), "09_long_run.sh:inline", "exec")


class FakeProcess:
    """Only the injected process boundary is simulated; file validation is real."""

    def __init__(self, command, effect, pid):
        self.command = command
        self.effect = effect
        self.pid = pid
        self.returncode = None

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        if self.returncode is None:
            self.returncode = self.effect(self.command)
        return self.returncode


class LongRunTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.launcher = fixture_launcher()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.source = self.root / "fixture.jsonl.zst"
        self.source.write_bytes(SOURCE_CONTENT)
        self.data = self.root / "data" / TAG
        self.runs = self.root / "runs" / TAG
        self.status_path = self.root / "logs" / (TAG + ".status.json")
        (self.root / "configs").mkdir()
        for model in ("small", "large"):
            (self.root / "configs" / (model + ".json")).write_text(
                (LAB_ROOT / "configs" / (model + ".json")).read_text(encoding="utf-8"),
                encoding="utf-8")
        self.commands = []
        self.spawn_options = []
        self.output = ""

    def make_dataset(self):
        self.data.mkdir(parents=True, exist_ok=True)
        counts = {"train": 4, "validation": 1, "test": 1}
        for split, count in counts.items():
            records = np.zeros(count, dtype=RECORD_DTYPE)
            records["cp"] = np.arange(count) * 25
            np.save(self.data / (split + ".npy"), records, allow_pickle=False)
        manifest = {
            "schema": "chesslab.prepared.v1", "feature_version": FEATURE_VERSION,
            "source": {"filename": self.source.name, "bytes": len(SOURCE_CONTENT)},
            "quality": POLICY,
            "sampling": {"method": "reservoir", "max_records": 12, "max_positions": 6},
            "split": {"seed": 20261023}, "counts": counts,
            "files": {split + ".npy": {"sha256": sha256_file(self.data / (split + ".npy"))}
                      for split in counts},
        }
        manifest["fingerprint"] = compute_manifest_fingerprint(manifest)
        (self.data / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        return manifest

    def process_effect(self, command):
        if "chesslab.prepare" in command:
            self.make_dataset()
        elif "chesslab.train" in command:
            directory = Path(command[command.index("--run") + 1])
            directory.mkdir(parents=True, exist_ok=True)
            # Deliberately not torch checkpoints: no subprocess executes these.
            (directory / "last.pt").write_bytes(b"completed-epoch fixture")
            (directory / "best.pt").write_bytes(b"best-epoch fixture")
        return 0

    def execute(self, extra=(), effect=None):
        self.commands = []
        self.spawn_options = []
        operation = effect or self.process_effect

        def spawn(command, **kwargs):
            self.commands.append(list(command))
            self.spawn_options.append(kwargs)
            return FakeProcess(command, operation, pid=1000 + len(self.commands))

        fake_fcntl = types.ModuleType("fcntl")
        fake_fcntl.LOCK_EX, fake_fcntl.LOCK_NB = 1, 2
        fake_fcntl.flock = Mock()
        argv = ["09_long_run.sh", "--input", str(self.source), "--tag", TAG,
                "--positions", "6", "--scan-records", "12", "--epochs", "2",
                "--batch-size", "2", "--prep-workers", "1", *extra]
        stdout, stderr = io.StringIO(), io.StringIO()
        code = 0
        with contextlib.ExitStack() as stack:
            stack.enter_context(contextlib.chdir(self.root))
            stack.enter_context(patch.object(sys, "argv", argv))
            stack.enter_context(patch.object(sys, "platform", "linux"))
            stack.enter_context(patch.dict(sys.modules, {"fcntl": fake_fcntl}))
            stack.enter_context(patch("shutil.disk_usage", return_value=types.SimpleNamespace(free=100 * 2**30)))
            stack.enter_context(patch("subprocess.Popen", side_effect=spawn))
            stack.enter_context(patch("signal.signal"))
            stack.enter_context(patch("os.killpg", create=True))
            stack.enter_context(contextlib.redirect_stdout(stdout))
            stack.enter_context(contextlib.redirect_stderr(stderr))
            try:
                exec(self.launcher, {"__name__": "__main__"})
            except SystemExit as exc:
                code = exc.code
        self.output = stdout.getvalue() + stderr.getvalue()
        return code

    def status(self):
        return json.loads(self.status_path.read_text(encoding="utf-8"))

    def module_commands(self, name):
        return [command for command in self.commands if name in command]

    def test_incomplete_source_fails_before_any_subprocess(self):
        self.source.write_bytes(SOURCE_CONTENT[:-1])
        self.assertEqual(self.execute(), 1)
        self.assertEqual(self.commands, [])
        self.assertEqual(self.status()["stage"], "source verification")
        self.assertIn("Archive is incomplete", self.status()["message"])

    def test_equal_size_wrong_source_hash_fails_before_any_subprocess(self):
        self.source.write_bytes(b"X" + SOURCE_CONTENT[1:])
        self.assertEqual(self.execute(), 1)
        self.assertEqual(self.commands, [])
        self.assertEqual(self.status()["state"], "failed")
        self.assertIn("checksum differs", self.status()["message"])

    def test_fresh_pipeline_checks_real_numpy_files_and_uses_cuda(self):
        self.assertEqual(self.execute(), 0, self.output)
        self.assertEqual(len(self.commands), 8)
        self.assertEqual(self.status()["state"], "complete")
        doctor = self.module_commands("chesslab.doctor")[0]
        self.assertIn("--require-cuda", doctor)
        self.assertIn("--strict-deps", doctor)
        benchmark = self.module_commands("chesslab.benchmark")[0]
        self.assertEqual(benchmark[benchmark.index("--model") + 1], "large")
        preparation = self.module_commands("chesslab.prepare")[0]
        self.assertEqual(preparation[preparation.index("--max-records") + 1], "12")
        self.assertEqual(preparation[preparation.index("--max-positions") + 1], "6")
        self.assertEqual(preparation[preparation.index("--sampling") + 1], "reservoir")
        training = self.module_commands("chesslab.train")
        self.assertEqual(len(training), 2)
        for command in [benchmark, *training]:
            self.assertEqual(command[command.index("--device") + 1], "cuda")
        for command in training:
            self.assertNotIn("--resume", command)
            config = json.loads(Path(command[command.index("--config") + 1]).read_text())
            self.assertEqual((config["epochs"], config["batch_size"], config["workers"]), (2, 2, 0))
            self.assertEqual(config["amp"], "bfloat16")
        for options in self.spawn_options:
            self.assertTrue(options["start_new_session"])
            self.assertEqual(options["cwd"], self.root)
            self.assertEqual(options["env"]["PYTHONUNBUFFERED"], "1")
        manifest = verify_dataset(self.data)
        binding = json.loads((self.runs / "data-binding.json").read_text())
        self.assertEqual(binding, {"source_sha256": SOURCE_SHA256,
                                  "prepared_fingerprint": manifest["fingerprint"]})
        self.assertEqual(len([c for c in self.commands if "scripts/05_evaluate.sh" in c]), 2)
        self.assertIn("--include-test", self.module_commands("chesslab.experiments")[0])

    def test_rerun_reuses_dataset_and_resumes_both_existing_checkpoints(self):
        self.assertEqual(self.execute(), 0, self.output)
        original = {path.name: path.read_bytes() for path in self.data.iterdir()}
        self.assertEqual(self.execute(), 0, self.output)
        self.assertFalse(self.module_commands("chesslab.prepare"))
        for command in self.module_commands("chesslab.train"):
            run = Path(command[command.index("--run") + 1])
            self.assertEqual(Path(command[command.index("--resume") + 1]), run / "last.pt")
        self.assertEqual({path.name: path.read_bytes() for path in self.data.iterdir()}, original)
        self.assertEqual(self.status()["state"], "complete")

    def test_changed_plan_fails_before_commands_and_preserves_results(self):
        self.assertEqual(self.execute(), 0, self.output)
        plan = (self.runs / "plan.json").read_bytes()
        checkpoint = (self.runs / "small" / "last.pt").read_bytes()
        self.assertEqual(self.execute(["--batch-size", "4"]), 1)
        self.assertEqual(self.commands, [])
        self.assertIn("different plan", self.status()["message"])
        self.assertEqual((self.runs / "plan.json").read_bytes(), plan)
        self.assertEqual((self.runs / "small" / "last.pt").read_bytes(), checkpoint)

    def test_partial_preparation_is_preserved_without_restarting_prepare(self):
        self.data.mkdir(parents=True)
        partial = self.data / ".prepare.sqlite"
        partial.write_bytes(b"partial preparation must survive")
        self.assertEqual(self.execute(), 1)
        self.assertIn("Partial preparation exists", self.status()["message"])
        self.assertFalse(self.module_commands("chesslab.prepare"))
        self.assertFalse(self.module_commands("chesslab.train"))
        self.assertEqual(partial.read_bytes(), b"partial preparation must survive")

    def test_corrupt_numpy_file_is_rejected_before_training(self):
        self.make_dataset()
        path = self.data / "train.npy"
        contents = bytearray(path.read_bytes())
        contents[-1] ^= 1
        path.write_bytes(contents)
        self.assertEqual(self.execute(), 1)
        self.assertIn("Checksum mismatch: train.npy", self.status()["message"])
        self.assertEqual(self.status()["stage"], "large data preparation")
        self.assertFalse(self.module_commands("chesslab.train"))
        self.assertEqual(path.read_bytes(), contents)

    def test_prepared_binding_mismatch_is_rejected_before_training(self):
        self.make_dataset()
        self.runs.mkdir(parents=True)
        binding = {"source_sha256": SOURCE_SHA256, "prepared_fingerprint": "another-release"}
        (self.runs / "data-binding.json").write_text(json.dumps(binding), encoding="utf-8")
        self.assertEqual(self.execute(), 1)
        self.assertIn("source/data binding", self.status()["message"])
        self.assertFalse(self.module_commands("chesslab.train"))
        self.assertEqual(json.loads((self.runs / "data-binding.json").read_text()), binding)

    def test_failed_training_records_stage_and_stops_later_work(self):
        def fail_small_training(command):
            if "chesslab.train" in command:
                return 7
            return self.process_effect(command)

        self.assertEqual(self.execute(effect=fail_small_training), 1)
        self.assertEqual(self.status()["state"], "failed")
        self.assertEqual(self.status()["stage"], "small training")
        self.assertEqual(len(self.module_commands("chesslab.train")), 1)
        self.assertFalse(any("scripts/05_evaluate.sh" in c for c in self.commands))
        self.assertFalse(self.module_commands("chesslab.experiments"))
        self.assertTrue((self.data / "manifest.json").exists())


if __name__ == "__main__":
    unittest.main()
