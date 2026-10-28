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
        for name in ("v10", "v2", "v1", "v0", "v01", "bad"):
            self.variant(name)
        (self.root / "Kernels/v3").mkdir()
        self.assertEqual(tools.versions(self.root), ["original", "v1", "v2", "v10"])
        for value in ("../v1", "v0", "v01", "V2", "v-1"):
            with self.assertRaises(ValueError): tools.paths(value, self.root)

    def test_selection_is_atomic_and_requires_binary(self):
        self.variant("v2")
        with self.assertRaises(FileNotFoundError): tools.select("v2", engines=self.root)
        _, binary = tools.paths("v2", self.root); binary.write_bytes(b"fixture")
        tools.select("v2", engines=self.root)
        self.assertEqual(json.loads((self.root / "kernel-selection.json").read_text()), {"version": "v2"})
        self.assertFalse(list(self.root.glob("*.tmp")))

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

    def test_failed_compile_preserves_previous_executable(self):
        source=self.variant("v3"); binary=source.with_suffix(".exe"); binary.write_bytes(b"old valid executable")
        with patch.object(tools, "compiler_environment", return_value=("fake-g++", dict(os.environ))), \
             patch.object(tools.subprocess, "run", side_effect=subprocess.CalledProcessError(1,"compiler")), \
             contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(subprocess.CalledProcessError): tools.build_kernel("v3", engines=self.root)
        self.assertEqual(binary.read_bytes(), b"old valid executable")
        self.assertFalse(binary.with_suffix(".build.json").exists())

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
             patch.object(launcher,"select",side_effect=lambda v:events.append("select")), \
             patch.object(launcher.subprocess,"call") as start, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(launcher.main(),0); start.assert_not_called()
        self.assertEqual(events,["weights","kernel","controller","select"])

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
