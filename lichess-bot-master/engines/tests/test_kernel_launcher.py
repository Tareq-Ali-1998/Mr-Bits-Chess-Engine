"""Isolated launcher/build tests. Never launch lichess-bot or write its config."""
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Kernels"))
import kernel_tools as tools
import launch_server as launcher


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="kernel launcher ")
        self.root = Path(self.temp.name) / "engines"
        self.root.mkdir(); (self.root / "Kernels").mkdir()
        (self.root / "Kernel.cpp").write_text("int main() {return 0;}")

    def tearDown(self):
        self.temp.cleanup()

    def variant(self, name):
        folder = self.root / "Kernels" / name; folder.mkdir()
        source = folder / f"Kernel-{name}.cpp"; source.write_text("int main() {return 0;}")
        return source

    def test_discovery_is_numeric_and_requires_source(self):
        for name in ("v12", "v11", "v10", "v9", "v8", "v7", "v6", "v5", "v2", "v1", "v0", "v01", "bad"):
            self.variant(name)
        (self.root / "Kernels/v3").mkdir()
        self.assertEqual(tools.versions(self.root), ["original", "v1", "v2", "v5", "v6", "v7", "v8", "v9", "v10", "v11", "v12"])
        for value in ("../v1", "v0", "v01", "V2", "v-1"):
            with self.assertRaises(ValueError): tools.paths(value, self.root)

    def test_family_discovery_sorts_major_and_minor_numerically(self):
        for name in ("v3.10", "v3.2", "v3.0", "v1.10", "v1.2", "v1.0", "v2.0", "v7",
                     "v0.1", "v03.1", "v3.01", "v3.", "v3.1.2"):
            self.variant(name)
        (self.root / "Kernels/v3.1").mkdir() # A folder without its matching source is not a version.
        self.assertEqual(tools.versions(self.root),
                         ["original", "v1.0", "v1.2", "v1.10", "v2.0", "v3.0", "v3.2", "v3.10", "v7"])
        for value in ("../v3.2", "v3.2/../../escape", "v0.1", "v03.1", "v3.01", "v3.", "v3.1.2",
                      "v3.-1", "v3.2.exe", "V3.2", "v3.2\n"):
            self.assertFalse(tools.version_name(value), value)
            with self.assertRaises(ValueError): tools.paths(value, self.root)
        for value in ("v1.0", "v3.2", "v3.10", "v10.0", "v7"):
            self.assertTrue(tools.version_name(value), value)
            source, binary = tools.paths(value, self.root)
            self.assertEqual(source, self.root / "Kernels" / value / f"Kernel-{value}.cpp")
            self.assertEqual(binary, source.with_suffix(".exe"))

    def test_family_weight_requirements_match_the_preserved_policy(self):
        small = self.root / "Neural Networks/Small/weights.bin"
        large = self.root / "Neural Networks/Large/weights.bin"
        small.parent.mkdir(parents=True); large.parent.mkdir(parents=True)
        with patch.dict(os.environ, {"MRBITS_NEURAL_WEIGHTS_DIR": str(small.parents[1])}):
            small.write_bytes(b"presence fixture")
            for version in ("v2.0", "v2.1", "v2.2", "v3.0", "v3.1", "v3.2", "v3.3", "v3.4", "v3.8", "v3.9", "v7"):
                tools.require_weights(version, engines=self.root)
            for version in ("v1.0", "v1.1", "v1.2", "v3.6", "v3.7"):
                with self.assertRaises(FileNotFoundError): tools.require_weights(version, engines=self.root)
            small.unlink(); large.write_bytes(b"presence fixture")
            tools.require_weights("v3.6", engines=self.root)
            for version in ("v1.0", "v1.1", "v1.2", "v2.0", "v2.1", "v2.2", "v3.0", "v3.1", "v3.2", "v3.3", "v3.4", "v3.7", "v3.8", "v3.9"):
                with self.assertRaises(FileNotFoundError): tools.require_weights(version, engines=self.root)
            small.write_bytes(b"presence fixture")
            for version in tools.LEGACY_TO_FAMILY.values(): tools.require_weights(version, engines=self.root)

    def test_evaluation_matrix_labels_and_shifted_policy_mapping(self):
        for version, percentage in (("v3.0", 50), ("v3.1", 100), ("v3.2", 0),
                                    ("v3.3", 80), ("v3.4", 20)):
            self.assertIn(f"{percentage}% Small / {100-percentage}% handcrafted", launcher.DESCRIPTIONS[version])
        self.assertEqual({old: tools.LEGACY_TO_FAMILY[old] for old in ("v8", "v9", "v10", "v11", "v12")},
                         {"v8": "v3.1", "v9": "v3.6", "v10": "v3.7", "v11": "v3.8", "v12": "v3.9"})
        self.assertNotIn("v3.5", launcher.DESCRIPTIONS)

    def test_family_selection_is_atomic_and_requires_its_own_executable(self):
        source = self.variant("v3.2")
        with self.assertRaises(FileNotFoundError): tools.select("v3.2", engines=self.root)
        source.with_suffix(".exe").write_bytes(b"not executable; selection fixture only")
        tools.select("v3.2", engines=self.root)
        self.assertEqual(json.loads((self.root / "kernel-selection.json").read_text()), {"version": "v3.2"})
        self.assertFalse(list(self.root.glob("*.tmp")))

    def test_menu_accepts_dotted_family_name_and_preserves_legacy_default(self):
        available = ["original", "v1.0", "v3.0", "v3.2", "v7"]
        with patch.object(launcher, "ENGINES", self.root), patch("builtins.input", return_value="v3.2"), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(launcher.choose(available), "v3.2")
        (self.root / "kernel-selection.json").write_text('{"version":"v7"}')
        with patch.object(launcher, "ENGINES", self.root), patch("builtins.input", return_value=""), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(launcher.choose(available), "v7")

    def test_retired_v7_keeps_history_alias_and_uses_canonical_selection(self):
        source = self.variant("v3.0")
        source.with_suffix(".exe").write_bytes(b"canonical selection fixture only")
        tools.select("v3.0", engines=self.root)
        available = tools.versions(self.root)
        self.assertEqual(available, ["original", "v3.0"])
        self.assertNotIn("v7", launcher.DESCRIPTIONS)
        self.assertEqual(tools.LEGACY_TO_FAMILY["v7"], "v3.0")
        with patch.object(launcher, "ENGINES", self.root), patch("builtins.input", return_value=""), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(launcher.choose(available), "v3.0")

    def test_selection_is_atomic_and_requires_binary(self):
        self.variant("v2")
        with self.assertRaises(FileNotFoundError): tools.select("v2", engines=self.root)
        _, binary = tools.paths("v2", self.root); binary.write_bytes(b"fixture")
        tools.select("v2", engines=self.root)
        self.assertEqual(json.loads((self.root / "kernel-selection.json").read_text()), {"version": "v2"})
        self.assertFalse(list(self.root.glob("*.tmp")))

    def test_new_variants_use_small_weights_without_large(self):
        small = self.root / "Neural Networks/Small/weights.bin"
        small.parent.mkdir(parents=True)
        small.write_bytes(b"only the presence is checked at startup")
        with patch.dict(os.environ, {"MRBITS_NEURAL_WEIGHTS_DIR": str(small.parents[1])}):
            for version in ("original", "v4", "v5", "v6", "v7", "v8", "v11", "v12"):
                tools.require_weights(version, engines=self.root)
            for version in ("v1", "v2", "v3", "v9", "v10"):
                with self.assertRaises(FileNotFoundError):
                    tools.require_weights(version, engines=self.root)
            small.unlink()
            for version in ("v5", "v6", "v7", "v8", "v11", "v12"):
                with self.assertRaises(FileNotFoundError):
                    tools.require_weights(version, engines=self.root)

    def test_v9_needs_only_large_but_v10_needs_both(self):
        model_root = self.root / "Neural Networks"
        large = model_root / "Large/weights.bin"
        large.parent.mkdir(parents=True)
        large.write_bytes(b"presence-only fixture")
        with patch.dict(os.environ, {"MRBITS_NEURAL_WEIGHTS_DIR": str(model_root)}):
            tools.require_weights("v9", engines=self.root)
            with self.assertRaises(FileNotFoundError):
                tools.require_weights("v10", engines=self.root)
            small = model_root / "Small/weights.bin"
            small.parent.mkdir(parents=True)
            small.write_bytes(b"presence-only fixture")
            tools.require_weights("v10", engines=self.root)
            large.unlink()
            with self.assertRaises(FileNotFoundError):
                tools.require_weights("v9", engines=self.root)

    def test_build_cache_detects_source_and_binary_changes(self):
        source = self.variant("v2"); binary = source.with_suffix(".exe"); calls=[]
        def compile(command, **kwargs):
            calls.append(command); Path(command[-1]).write_bytes(b"compiled fixture")
        with patch.object(tools, "compiler_environment", return_value=("fake-g++", dict(os.environ))), \
             patch.object(tools.subprocess, "run", side_effect=compile), contextlib.redirect_stdout(io.StringIO()):
            tools.build_kernel("v2", engines=self.root)
            tools.build_kernel("v2", engines=self.root)
            self.assertEqual(len(calls), 1)
            source.write_text("int main(){ return 1; }")
            tools.build_kernel("v2", engines=self.root); self.assertEqual(len(calls), 2)
            binary.write_bytes(b"changed binary")
            tools.build_kernel("v2", engines=self.root); self.assertEqual(len(calls), 3)

    def test_obsolete_saved_build_manifest_cannot_override_current_source(self):
        source = self.variant("v7")
        binary = source.with_suffix(".exe")
        binary.write_bytes(b"old installed fixture")
        receipt = binary.with_suffix(".build.json")
        receipt.write_text('{"stamp":"old-build"}')
        tools.write_json(self.root / "backup-runtime/retained-builds.json", {
            "schema": "mrbits.retained-builds.v1", "builds": {"Kernels/v7/Kernel-v7.exe": {
                "stamp": "old-build", "executable_sha256": tools.digest(binary),
                "receipt_sha256": tools.digest(receipt)
            }}})
        source.write_text("int main(){return 100;}\n")
        calls = []
        def compile(command, **kwargs):
            calls.append(command)
            Path(command[-1]).write_bytes(b"current-source fixture")
        with patch.object(tools, "compiler_environment", return_value=("fake-g++", dict(os.environ))), \
             patch.object(tools.subprocess, "run", side_effect=compile), \
             contextlib.redirect_stdout(io.StringIO()):
            tools.build_kernel("v7", engines=self.root)
        self.assertEqual(len(calls), 1)
        self.assertEqual(binary.read_bytes(), b"current-source fixture")
        self.assertEqual(json.loads(receipt.read_text())["origin"], "local_compilation")

    def test_failed_compile_preserves_previous_executable(self):
        source=self.variant("v3"); binary=source.with_suffix(".exe"); binary.write_bytes(b"old valid executable")
        with patch.object(tools, "compiler_environment", return_value=("fake-g++", dict(os.environ))), \
             patch.object(tools.subprocess, "run", side_effect=subprocess.CalledProcessError(1,"compiler")), \
             contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(subprocess.CalledProcessError): tools.build_kernel("v3", engines=self.root)
        self.assertEqual(binary.read_bytes(), b"old valid executable")
        self.assertFalse(binary.with_suffix(".build.json").exists())

    def test_shared_search_header_change_invalidates_build_cache(self):
        source = self.variant("v5")
        source.write_text('#include "Kernels/Neural Search.hpp"\nint main() {return 0;}\n')
        header = self.root / "Kernels/Neural Search.hpp"
        header.write_text("// search policy revision one")
        calls = []
        def compile(command, **kwargs):
            calls.append(command)
            Path(command[-1]).write_bytes(b"compiled fixture")
        with patch.object(tools, "compiler_environment", return_value=("fake-g++", dict(os.environ))), \
             patch.object(tools.subprocess, "run", side_effect=compile), \
             contextlib.redirect_stdout(io.StringIO()):
            tools.build_kernel("v5", engines=self.root)
            tools.build_kernel("v5", engines=self.root)
            self.assertEqual(len(calls), 1)
            header.write_text("// search policy revision two")
            tools.build_kernel("v5", engines=self.root)
            self.assertEqual(len(calls), 2)

    def test_denied_compiler_start_reports_compiler_and_native_error(self):
        source = self.variant("v1"); binary = source.with_suffix(".exe")
        binary.write_bytes(b"old executable")
        denied = PermissionError(13, "compiler launch denied", "fake-g++")
        with patch.object(tools, "compiler_environment", return_value=("fake-g++", dict(os.environ))), \
             patch.object(tools.subprocess, "run", side_effect=denied), \
             contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(RuntimeError) as caught:
                tools.build_kernel("v1", engines=self.root)
        message = str(caught.exception)
        self.assertIn("Could not start compiler 'fake-g++'", message)
        self.assertIn(str(binary), message); self.assertIn(str(denied), message)
        self.assertNotIn("executable is in use", message)
        self.assertIs(caught.exception.__cause__, denied)
        self.assertEqual(binary.read_bytes(), b"old executable")

    def test_denied_executable_install_preserves_binary_and_receipt(self):
        source = self.variant("v1"); binary = source.with_suffix(".exe")
        receipt = binary.with_suffix(".build.json")
        binary.write_bytes(b"old executable"); receipt.write_text("{}")
        denied = PermissionError(13, "executable replacement denied", str(binary))
        replace = os.replace
        def install(source_path, target_path):
            if Path(target_path) == binary: raise denied
            return replace(source_path, target_path)
        def compile(command, **kwargs):
            Path(command[-1]).write_bytes(b"new executable")
        with patch.object(tools, "compiler_environment", return_value=("fake-g++", dict(os.environ))), \
             patch.object(tools.subprocess, "run", side_effect=compile), \
             patch.object(tools.os, "replace", side_effect=install), \
             contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(RuntimeError) as caught:
                tools.build_kernel("v1", engines=self.root)
        message = str(caught.exception)
        self.assertIn("Could not install executable", message)
        self.assertIn(str(binary), message); self.assertIn(str(denied), message)
        self.assertNotIn("executable is in use", message)
        self.assertIs(caught.exception.__cause__, denied)
        self.assertEqual(binary.read_bytes(), b"old executable")
        self.assertEqual(receipt.read_text(), "{}")
        self.assertFalse(binary.with_name(binary.stem + ".building.exe").exists())

    def test_denied_receipt_install_reports_installed_binary_and_preserves_primary(self):
        source = self.variant("v1"); binary = source.with_suffix(".exe")
        receipt = binary.with_suffix(".build.json")
        binary.write_bytes(b"old executable"); receipt.write_text("{}")
        denied = PermissionError(13, "receipt replacement denied", str(receipt))
        cleanup_denied = PermissionError(13, "receipt temporary cleanup denied")
        replace, unlink = os.replace, Path.unlink
        def install(source_path, target_path):
            if Path(target_path) == receipt: raise denied
            return replace(source_path, target_path)
        def remove(path, *args, **kwargs):
            if path.name.startswith(receipt.name + ".") and path.suffix == ".tmp":
                raise cleanup_denied
            return unlink(path, *args, **kwargs)
        def compile(command, **kwargs):
            Path(command[-1]).write_bytes(b"new executable")
        warnings = io.StringIO()
        with patch.object(tools, "compiler_environment", return_value=("fake-g++", dict(os.environ))), \
             patch.object(tools.subprocess, "run", side_effect=compile), \
             patch.object(tools.os, "replace", side_effect=install), \
             patch.object(Path, "unlink", new=remove), \
             contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(warnings):
            with self.assertRaises(RuntimeError) as caught:
                tools.build_kernel("v1", engines=self.root)
        message = str(caught.exception)
        self.assertIn("was installed, but could not write build receipt", message)
        self.assertIn(str(receipt), message); self.assertIn(str(denied), message)
        self.assertIs(caught.exception.__cause__, denied)
        self.assertEqual(binary.read_bytes(), b"new executable")
        self.assertEqual(receipt.read_text(), "{}")
        self.assertIn(str(cleanup_denied), warnings.getvalue())

    def test_temporary_cleanup_failure_does_not_hide_compile_failure(self):
        source = self.variant("v1"); binary = source.with_suffix(".exe")
        temporary = binary.with_name(binary.stem + ".building.exe")
        binary.write_bytes(b"old executable")
        failed = subprocess.CalledProcessError(1, "fake-g++")
        cleanup_denied = PermissionError(13, "temporary cleanup denied", str(temporary))
        unlink = Path.unlink
        def remove(path, *args, **kwargs):
            if path == temporary: raise cleanup_denied
            return unlink(path, *args, **kwargs)
        def compile(command, **kwargs):
            Path(command[-1]).write_bytes(b"partial compilation")
            raise failed
        warnings = io.StringIO()
        with patch.object(tools, "compiler_environment", return_value=("fake-g++", dict(os.environ))), \
             patch.object(tools.subprocess, "run", side_effect=compile), \
             patch.object(Path, "unlink", new=remove), \
             contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(warnings):
            with self.assertRaises(subprocess.CalledProcessError) as caught:
                tools.build_kernel("v1", engines=self.root)
        self.assertIs(caught.exception, failed)
        self.assertIn(str(cleanup_denied), warnings.getvalue())
        self.assertEqual(binary.read_bytes(), b"old executable")

    def test_temporary_cleanup_failure_alone_is_reported(self):
        source = self.variant("v1"); binary = source.with_suffix(".exe")
        temporary = binary.with_name(binary.stem + ".building.exe")
        cleanup_denied = PermissionError(13, "temporary cleanup denied", str(temporary))
        unlink = Path.unlink
        def remove(path, *args, **kwargs):
            if path == temporary: raise cleanup_denied
            return unlink(path, *args, **kwargs)
        def compile(command, **kwargs):
            Path(command[-1]).write_bytes(b"new executable")
        with patch.object(tools, "compiler_environment", return_value=("fake-g++", dict(os.environ))), \
             patch.object(tools.subprocess, "run", side_effect=compile), \
             patch.object(Path, "unlink", new=remove), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(RuntimeError) as caught:
                tools.build_kernel("v1", engines=self.root)
        self.assertIn("Could not remove temporary file", str(caught.exception))
        self.assertIn(str(temporary), str(caught.exception))
        self.assertIs(caught.exception.__cause__, cleanup_denied)
        self.assertEqual(binary.read_bytes(), b"new executable")
        self.assertTrue(binary.with_suffix(".build.json").is_file())

    def test_prepare_only_never_starts_bot_and_selects_after_builds(self):
        events=[]
        with patch.object(sys,"argv",["launcher","--version","v4","--prepare-only"]), \
             patch.object(launcher,"versions",return_value=["original","v4"]), \
             patch.object(launcher,"require_weights",side_effect=lambda v:events.append("weights")), \
             patch.object(launcher,"build_kernel",side_effect=lambda *a,**k:events.append("kernel")), \
             patch.object(launcher,"build_controller",side_effect=lambda **k:events.append("controller")), \
             patch.object(launcher,"probe_kernel_startup") as probe, \
             patch.object(launcher,"select",side_effect=lambda v:events.append("select")), \
             patch.object(launcher.subprocess,"call") as start, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(launcher.main(),0); start.assert_not_called(); probe.assert_not_called()
        self.assertEqual(events,["weights","kernel","controller","select"])

    def test_kernel_startup_probe_validates_ready_without_starting_bot(self):
        binary = self.root / "Kernels/v6/Kernel-v6.exe"
        env = {"PATH": "compiler directory"}
        result = subprocess.CompletedProcess([str(binary)], 0,
                    stdout='{"type":"ready","protocol":1,"engineVersion":"kernel-test"}\n', stderr="")
        with patch.object(launcher.subprocess, "run", return_value=result) as run, \
             patch.object(launcher.subprocess, "call") as start:
            launcher.probe_kernel_startup(binary, env)
        run.assert_called_once_with([str(binary)], input='{"type":"hello"}\n{"type":"quit"}\n',
                                    capture_output=True, text=True, timeout=15, env=env, cwd=launcher.ENGINES)
        start.assert_not_called()

    def test_kernel_startup_probe_rejects_invalid_protocol_responses(self):
        binary = self.root / "Kernel.exe"
        for response in ("", "not json\n", "[]\n", '{"type":"ready","protocol":2}\n',
                         '{"type":"ready","protocol":true}\n', '{"type":"error","protocol":1}\n',
                         '{"type":"ready","protocol":1}\n{"type":"ready","protocol":1}\n'):
            with self.subTest(response=response):
                result = subprocess.CompletedProcess([str(binary)], 0, stdout=response, stderr="")
                with patch.object(launcher.subprocess, "run", return_value=result):
                    with self.assertRaisesRegex(RuntimeError, "Invalid Kernel startup response") as caught:
                        launcher.probe_kernel_startup(binary, {})
                self.assertIn(str(binary), str(caught.exception))

    def test_kernel_startup_probe_reports_exit_and_timeout(self):
        binary = self.root / "Kernel.exe"
        result = subprocess.CompletedProcess([str(binary)], 23, stdout="", stderr="worker startup error")
        with patch.object(launcher.subprocess, "run", return_value=result):
            with self.assertRaisesRegex(RuntimeError, "exit code 23: worker startup error"):
                launcher.probe_kernel_startup(binary, {})
        timeout = subprocess.TimeoutExpired([str(binary)], 15)
        with patch.object(launcher.subprocess, "run", side_effect=timeout) as run:
            with self.assertRaisesRegex(RuntimeError, "timed out after 15 seconds") as caught:
                launcher.probe_kernel_startup(binary, {})
        self.assertIs(caught.exception.__cause__, timeout)
        run.assert_called_once()

    def test_kernel_startup_probe_reports_os_error_without_retry(self):
        binary = self.root / "Kernel.exe"
        denied = PermissionError(13, "startup denied", str(binary))
        with patch.object(launcher.subprocess, "run", side_effect=denied) as run:
            with self.assertRaisesRegex(RuntimeError, "Could not start Kernel startup check") as caught:
                launcher.probe_kernel_startup(binary, {})
        self.assertIn(str(denied), str(caught.exception))
        self.assertIs(caught.exception.__cause__, denied)
        run.assert_called_once()

    def test_blocked_kernel_stops_before_saving_selection_or_starting_bot(self):
        binary = self.root / "Kernels/v6/Kernel-v6.exe"
        denied = OSError("Application control denied startup")
        denied.winerror = 4551
        with patch.object(sys, "argv", ["launcher", "--version", "v6"]), \
             patch.object(launcher, "versions", return_value=["original", "v6"]), \
             patch.object(launcher, "require_weights"), \
             patch.object(launcher, "build_kernel", return_value=binary), \
             patch.object(launcher, "build_controller"), \
             patch.object(launcher.subprocess, "run", side_effect=denied) as probe_run, \
             patch.object(launcher, "select") as select, \
             patch.object(launcher.subprocess, "call") as start:
            with self.assertRaisesRegex(RuntimeError, "Windows App Control blocked Kernel startup") as caught:
                launcher.main()
        self.assertIn("WinError 4551", str(caught.exception))
        self.assertIn(str(binary), str(caught.exception))
        self.assertIs(caught.exception.__cause__, denied)
        probe_run.assert_called_once(); select.assert_not_called(); start.assert_not_called()

    def test_normal_start_probes_before_saving_selection_and_starting_bot(self):
        events = []
        binary = self.root / "Kernel.exe"
        def build(*args, **kwargs):
            events.append("kernel"); return binary
        def probe(path, env):
            self.assertEqual(path, binary); self.assertIn("PATH", env); events.append("probe")
        def start(*args, **kwargs):
            events.append("bot"); return 7
        with patch.object(sys, "argv", ["launcher", "--version", "original"]), \
             patch.object(launcher, "versions", return_value=["original"]), \
             patch.object(launcher, "require_weights", side_effect=lambda v: events.append("weights")), \
             patch.object(launcher, "build_kernel", side_effect=build), \
             patch.object(launcher, "build_controller", side_effect=lambda **k: events.append("controller")), \
             patch.object(launcher, "probe_kernel_startup", side_effect=probe), \
             patch.object(launcher, "select", side_effect=lambda v: events.append("select")), \
             patch.object(launcher.subprocess, "call", side_effect=start), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(launcher.main(), 7)
        self.assertEqual(events, ["weights", "kernel", "controller", "probe", "select", "bot"])

    def test_list_does_not_build_probe_select_or_start(self):
        with patch.object(sys, "argv", ["launcher", "--list"]), \
             patch.object(launcher, "versions", return_value=["original", "v5", "v6"]), \
             patch.object(launcher, "require_weights") as weights, \
             patch.object(launcher, "build_kernel") as kernel, \
             patch.object(launcher, "build_controller") as controller, \
             patch.object(launcher, "probe_kernel_startup") as probe, \
             patch.object(launcher, "select") as select, \
             patch.object(launcher.subprocess, "call") as start, \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(launcher.main(), 0)
        for operation in (weights, kernel, controller, probe, select, start): operation.assert_not_called()

    def test_menu_accepts_folder_name_and_number(self):
        with patch.object(launcher,"ENGINES",self.root), patch("builtins.input",side_effect=["wrong","2"]), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(launcher.choose(["original","v1","v4"]),"v4")
        with patch.object(launcher,"ENGINES",self.root), patch("builtins.input",return_value="v4"), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(launcher.choose(["original","v4"]),"v4")

    @unittest.skipUnless(shutil.which("g++"), "g++ is required")
    def test_real_compiler_handles_spaces_and_string_build_stamp(self):
        source=self.variant("v4")
        source.write_text('#include <iostream>\nint main(){std::cout << MRBITS_BUILD_STAMP;}\n')
        with contextlib.redirect_stdout(io.StringIO()):
            binary=tools.build_kernel("v4", engines=self.root)
        result=subprocess.run([str(binary)],capture_output=True,text=True,check=True,
                              env=tools.compiler_environment()[1])
        self.assertTrue(result.stdout.startswith("v4-"))
        meta=json.loads(binary.with_suffix(".build.json").read_text())
        self.assertEqual(result.stdout,meta["stamp"])


if __name__ == "__main__": unittest.main()
