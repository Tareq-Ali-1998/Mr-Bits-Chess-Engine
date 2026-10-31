"""Runner bookkeeping tests; no compiler, executable, network, or OS policy calls."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

import run_kernel_v56_tests as runner


class RunnerStatusTests(unittest.TestCase):
    def test_explicit_application_control_denial_is_blocked(self):
        error = OSError("An Application Control policy has blocked this file")
        error.winerror = 4551
        self.assertEqual(runner.failure_status(error), "blocked")

    def test_other_errors_remain_failures(self):
        errors = [PermissionError(13, "Access denied"), OSError(4551, "errno alone is not WinError"),
                  RuntimeError("assertion failed"), subprocess.CalledProcessError(1, "fake compiler"),
                  subprocess.TimeoutExpired("fake executable", 1)]
        for error in errors:
            with self.subTest(error=type(error).__name__):
                self.assertEqual(runner.failure_status(error), "failed")

    def test_failed_takes_priority_over_blocked(self):
        self.assertEqual(runner.aggregate_status([{"status": "passed"}, {"status": "blocked"}]), "blocked")
        self.assertEqual(runner.aggregate_status([{"status": "blocked"}, {"status": "failed"}]), "failed")
        self.assertEqual(runner.aggregate_status([{"status": "passed"}]), "passed")
        self.assertEqual(runner.aggregate_status([]), "failed")

    def test_successful_receipt_archived_byte_for_byte(self):
        with tempfile.TemporaryDirectory(prefix="v56 receipt ") as temporary:
            path = Path(temporary) / "receipt.json"
            original = b'{"status":"passed","checks":752}\n'
            path.write_bytes(original)
            runner.save(path, {"status": "blocked", "error": "fixture policy denial"})
            archived = list((path.parent / "history").glob("*.json"))
            self.assertEqual(len(archived), 1)
            self.assertEqual(archived[0].read_bytes(), original)
            self.assertEqual(json.loads(path.read_text())["status"], "blocked")
            runner.save(path, {"status": "failed"})
            self.assertEqual(len(list((path.parent / "history").glob("*.json"))), 1)

    def test_invalid_existing_json_is_not_claimed_as_success(self):
        with tempfile.TemporaryDirectory(prefix="v56 receipt ") as temporary:
            path = Path(temporary) / "receipt.json"
            path.write_text("malformed old report")
            runner.save(path, {"status": "blocked"})
            self.assertFalse((path.parent / "history").exists())


if __name__ == "__main__":
    unittest.main()
