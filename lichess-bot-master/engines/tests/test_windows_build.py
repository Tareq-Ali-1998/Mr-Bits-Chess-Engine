"""File-sharing regression checks; no engine, antivirus or service is started/stopped."""
import contextlib
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Kernels"))
import windows_build


class ReplacementTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "Windows sharing semantics")
    def test_transient_denial_retries_identical_staging_file(self):
        denied = PermissionError("scanner still reading")
        denied.winerror = 32
        with tempfile.TemporaryDirectory() as directory:
            staging, target = Path(directory) / "new.exe", Path(directory) / "current.exe"
            staging.write_bytes(b"new binary"); target.write_bytes(b"old binary")
            real_replace = os.replace
            attempts = []
            def replace(source, destination):
                attempts.append((source, destination))
                if len(attempts) < 3:
                    raise denied
                real_replace(source, destination)
            with patch.object(windows_build.os, "replace", side_effect=replace), \
                 patch.object(windows_build.time, "sleep") as sleep, \
                 contextlib.redirect_stdout(io.StringIO()):
                windows_build.replace_executable(staging, target)
            self.assertEqual(len(attempts), 3)
            self.assertEqual(target.read_bytes(), b"new binary")
            self.assertEqual(sleep.call_count, 2)

    @unittest.skipUnless(os.name == "nt", "Windows sharing semantics")
    def test_permanent_denial_preserves_both_files_and_original_error(self):
        denied = PermissionError("persistent lock"); denied.winerror = 5
        with tempfile.TemporaryDirectory() as directory:
            staging, target = Path(directory) / "new.exe", Path(directory) / "current.exe"
            staging.write_bytes(b"new binary"); target.write_bytes(b"old binary")
            with patch.object(windows_build.os, "replace", side_effect=denied) as replace, \
                 patch.object(windows_build.os, "rename", side_effect=denied), \
                 patch.object(windows_build.time, "sleep") as sleep, \
                 contextlib.redirect_stdout(io.StringIO()), self.assertRaises(PermissionError) as caught:
                windows_build.replace_executable(staging, target)
            self.assertIs(caught.exception, denied)
            self.assertEqual(replace.call_count, 9); self.assertEqual(sleep.call_count, 8)
            self.assertEqual(target.read_bytes(), b"old binary")
            self.assertEqual(staging.read_bytes(), b"new binary")

    @unittest.skipUnless(os.name == "nt", "Windows installer fallback")
    def test_mapped_destination_fallback_preserves_previous_binary(self):
        denied = PermissionError("mapped destination"); denied.winerror = 5
        with tempfile.TemporaryDirectory() as directory:
            staging, target = Path(directory) / "new.exe", Path(directory) / "current.exe"
            staging.write_bytes(b"new binary"); target.write_bytes(b"old binary")
            with windows_build.build_lock(target), \
                 patch.object(windows_build.os, "replace", side_effect=denied), \
                 patch.object(windows_build.time, "sleep"), contextlib.redirect_stdout(io.StringIO()):
                windows_build.replace_executable(staging, target)
            self.assertEqual(target.read_bytes(), b"new binary")
            backups = list(target.parent.glob("*.old"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_bytes(), b"old binary")
            self.assertFalse(staging.exists())

    @unittest.skipUnless(os.name == "nt", "Windows installer fallback")
    def test_fallback_install_failure_restores_previous_path(self):
        denied = PermissionError("mapped destination"); denied.winerror = 5
        with tempfile.TemporaryDirectory() as directory:
            staging, target = Path(directory) / "new.exe", Path(directory) / "current.exe"
            staging.write_bytes(b"new binary"); target.write_bytes(b"old binary")
            real_rename = os.rename
            def rename(source, destination):
                if source == staging:
                    raise PermissionError("failed to install new file")
                return real_rename(source, destination)
            with windows_build.build_lock(target), \
                 patch.object(windows_build.os, "replace", side_effect=denied), \
                 patch.object(windows_build.os, "rename", side_effect=rename), \
                 patch.object(windows_build.time, "sleep"), contextlib.redirect_stdout(io.StringIO()), \
                 self.assertRaises(PermissionError):
                windows_build.replace_executable(staging, target)
            self.assertEqual(target.read_bytes(), b"old binary")
            self.assertEqual(staging.read_bytes(), b"new binary")
            self.assertFalse(list(target.parent.glob("*.old")))

    def test_concurrent_managed_build_is_refused_then_lock_releases(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "current.exe"
            with windows_build.build_lock(target):
                with self.assertRaisesRegex(RuntimeError, "Another build"):
                    with windows_build.build_lock(target):
                        self.fail("second builder must not enter")
            with windows_build.build_lock(target):
                pass

    @unittest.skipUnless(os.name == "nt", "Windows sharing semantics")
    def test_real_windows_handle_is_detected_without_modifying_file(self):
        import ctypes as c
        from ctypes import wintypes as w
        kernel = c.WinDLL("kernel32", use_last_error=True)
        kernel.CreateFileW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, c.c_void_p, w.DWORD, w.DWORD, w.HANDLE]
        kernel.CreateFileW.restype = w.HANDLE
        kernel.CloseHandle.argtypes = [w.HANDLE]
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "held.exe"
            target.write_bytes(b"fixture only; never executed")
            handle = kernel.CreateFileW(str(target), 0x80000000, 3, None, 3, 0, None)
            self.assertNotEqual(handle, w.HANDLE(-1).value)
            try:
                with patch.object(windows_build, "file_users", return_value=["Fixture owner (PID 123)"]), \
                     self.assertRaises(RuntimeError) as caught:
                    windows_build.check_replace_access(target)
                self.assertIn("No compilation was started", str(caught.exception))
                self.assertIn("Fixture owner (PID 123)", str(caught.exception))
                self.assertEqual(target.read_bytes(), b"fixture only; never executed")
            finally:
                kernel.CloseHandle(handle)
            windows_build.check_replace_access(target)


if __name__ == "__main__":
    unittest.main()
