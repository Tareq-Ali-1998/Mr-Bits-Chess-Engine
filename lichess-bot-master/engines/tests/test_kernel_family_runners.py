"""Migration contracts: canonical CLI/source/report identity, no native test execution."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from kernel_family_versions import canonical_version, legacy_version, kernel_source
import run_kernel_policy_tests as policy
import run_kernel_v56_tests as leaf
import run_kernel_v7_tests as legal
import run_kernel_v9_v11_tests as advanced


class FamilyRunnerTests(unittest.TestCase):
    def test_aliases_resolve_to_existing_canonical_sources(self):
        for old, new in (("v2", "v1.1"), ("v3", "v1.2"), ("v4", "v2.0"),
                         ("v5", "v2.1"), ("v6", "v2.2"), ("v7", "v3.0"),
                         ("v8", "v3.1"), ("v9", "v3.6"), ("v10", "v3.7"),
                         ("v11", "v3.8"), ("v12", "v3.9")):
            self.assertEqual(canonical_version(old), new)
            self.assertEqual(legacy_version(new), old)
            self.assertEqual(kernel_source(legal.ENGINES, old), kernel_source(legal.ENGINES, new))
            self.assertTrue(kernel_source(legal.ENGINES, new).is_file(), new)

    def test_policy_canonical_cli_keeps_historical_schema_and_canonical_receipt(self):
        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(policy.subprocess, "run", side_effect=[
                    subprocess.CompletedProcess([], 0, stdout="fixture compiler", stderr=""),
                    subprocess.CompletedProcess([], 1, stdout="", stderr="deliberate compile failure")]) as run, \
                 contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(policy.main(["--only", "v1.2", "--cxx", "fake-g++", "--report-dir", temporary]), 1)
            self.assertEqual(run.call_count, 2) # Version probe and compile; no diagnostic execution.
            report = json.loads((Path(temporary) / "kernel_v1.2_policy_test.json").read_text())
            self.assertEqual(report["variant"], "v1.2")
            self.assertEqual(report["legacy_variant"], "v3")
            self.assertEqual(report["schema"], "mrbits.kernel-policy-diagnostic.v1")
            self.assertIn(str(Path("Kernels/v1.2/Kernel-v1.2.cpp")), report["source_sha256"])

    def test_leaf_canonical_cli_uses_canonical_source_and_report(self):
        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(leaf.subprocess, "run", side_effect=[
                    subprocess.CompletedProcess([], 0, stdout="fixture compiler", stderr=""),
                    subprocess.CompletedProcess([], 1, stdout="", stderr="deliberate compile failure")]) as run, \
                 contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(leaf.main(["--only", "v2.2", "--cxx", "fake-g++", "--report-dir", temporary]), 1)
            self.assertEqual(run.call_count, 2)
            report = json.loads((Path(temporary) / "kernel_v2.2_policy_test.json").read_text())
            self.assertEqual(report["variant"], "v2.2")
            self.assertEqual(report["legacy_variant"], "v6")
            self.assertEqual(report["schema"], "mrbits.v56-policy-diagnostics.v1")
            self.assertIn(str(Path("Kernels/v2.2/Kernel-v2.2.cpp")), report["source_sha256"])

    def test_legal_canonical_cli_uses_stable_header_and_historical_schema(self):
        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(legal, "fixture_boards", return_value=[]), \
                 patch.object(legal.subprocess, "run", return_value=subprocess.CompletedProcess(
                     [], 1, stdout="", stderr="deliberate compile failure")) as run, \
                 contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(legal.main(["--version", "v3.1", "--cxx", "fake-g++", "--report-dir", temporary]), 1)
            self.assertEqual(run.call_count, 1) # Compile only; no diagnostic execution.
            report = json.loads((Path(temporary) / "verification.json").read_text())
            self.assertEqual(report["version"], "v3.1")
            self.assertEqual(report["schema"], "mrbits.v8-diagnostics.v1")
            self.assertIn(str(Path("Kernels/v3.1/Kernel-v3.1.cpp")), report["source_sha256"])
            self.assertIn(str(Path("Kernels/V3 Evaluation Search.hpp")), report["source_sha256"])

    def test_advanced_cli_preserves_integer_diagnostic_macro_contract(self):
        with patch.object(advanced, "verify_version", return_value={"status": "passed"}) as verify:
            self.assertEqual(advanced.main(["--versions", "v3.6", "v3.8", "--cxx", "fake-g++"]), 0)
        self.assertEqual([call.args[0] for call in verify.call_args_list], [9, 11])
        with patch.object(advanced, "verify_version", return_value={"status": "passed"}) as verify:
            self.assertEqual(advanced.main(["--versions", "9", "v10", "--cxx", "fake-g++"]), 0)
        self.assertEqual([call.args[0] for call in verify.call_args_list], [9, 10])


if __name__ == "__main__":
    unittest.main()
