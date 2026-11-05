"""Windows file-sharing diagnostics. Never stops processes or changes protection."""
from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
import time
import uuid


@contextmanager
def build_lock(executable: Path):
    """Serialize managed builders; the OS releases the lock if a builder crashes."""
    lock_path = executable.with_suffix(".build.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0"); handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise RuntimeError(f"Another build is using '{executable}'. Let that build finish before retrying.") from error
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def file_users(path: Path) -> list[str]:
    """Ask Restart Manager about this exact path (best effort, read only)."""
    if os.name != "nt" or not path.exists():
        return []
    import ctypes as c
    from ctypes import wintypes as w

    class UniqueProcess(c.Structure):
        _fields_ = [("pid", w.DWORD), ("started", w.FILETIME)]

    class ProcessInfo(c.Structure):
        _fields_ = [("process", UniqueProcess), ("app", w.WCHAR * 256),
                    ("service", w.WCHAR * 64), ("kind", c.c_int),
                    ("status", w.ULONG), ("session", w.DWORD), ("restartable", w.BOOL)]

    try:
        manager = c.WinDLL("rstrtmgr")
        session, key = w.DWORD(), c.create_unicode_buffer(33)
        if manager.RmStartSession(c.byref(session), 0, key) != 0:
            return []
        try:
            names = (w.LPCWSTR * 1)(str(path.resolve()))
            if manager.RmRegisterResources(session, 1, names, 0, None, 0, None) != 0:
                return []
            needed, count, reason = w.UINT(), w.UINT(), w.DWORD()
            result = manager.RmGetList(session, c.byref(needed), c.byref(count), None, c.byref(reason))
            for _ in range(3):
                if result != 234:  # ERROR_MORE_DATA: the set of file users can change.
                    return []
                rows = (ProcessInfo * needed.value)()
                count.value = needed.value
                result = manager.RmGetList(session, c.byref(needed), c.byref(count), rows, c.byref(reason))
                if result == 0:
                    return [f"{row.app or row.service or 'Application'} (PID {row.process.pid}"
                            + (f", service {row.service}" if row.service else "") + ")"
                            for row in rows[:count.value]]
            return []
        finally:
            manager.RmEndSession(session)
    except (OSError, AttributeError):
        return []


def lock_detail(path: Path) -> str:
    users = file_users(path)
    return (" Windows reports these applications using this file: " + "; ".join(users) + "."
            if users else "")


def check_replace_access(path: Path) -> None:
    """Open/close a DELETE-access handle without changing or deleting the file."""
    if os.name != "nt" or not path.exists():
        return
    import ctypes as c
    from ctypes import wintypes as w
    kernel = c.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, c.c_void_p, w.DWORD, w.DWORD, w.HANDLE]
    kernel.CreateFileW.restype = w.HANDLE
    kernel.CloseHandle.argtypes = [w.HANDLE]
    handle = kernel.CreateFileW(str(path.resolve()), 0x10000, 7, None, 3, 0, None)
    if handle == w.HANDLE(-1).value:
        error = c.WinError(c.get_last_error())
        raise RuntimeError(
            f"Cannot replace executable '{path}': {error}. No compilation was started."
            + lock_detail(path)
            + " Close any bot using it. If another application keeps the handle open, save your work "
              "and restart Windows before rebuilding."
        ) from error
    kernel.CloseHandle(handle)


def replace_executable(staging: Path, destination: Path) -> None:
    """Retry the same compiled file briefly for a transient scanner handle."""
    for attempt in range(9):
        try:
            os.replace(staging, destination)
            return
        except OSError as error:
            if os.name != "nt" or getattr(error, "winerror", None) not in (5, 32, 33):
                raise
            if attempt == 8:
                if not destination.is_file():
                    raise
                _install_with_backup(staging, destination, error)
                return
            if attempt == 0:
                print("Windows temporarily denied executable replacement; waiting up to four seconds ...", flush=True)
            time.sleep(0.5)


def _install_with_backup(staging: Path, destination: Path, replace_error: OSError) -> None:
    """Normal Windows installer fallback for a mapped destination.

    Managed callers hold build_lock. Renames are individually atomic; the pair
    has a brief missing-target interval. Never execute staging or backup names.
    """
    backup = destination.with_name(destination.name + "." + uuid.uuid4().hex + ".old")
    try:
        os.rename(destination, backup)
    except OSError as error:
        replace_error.add_note(f"Could not preserve the previous executable at '{backup}': {error}")
        raise replace_error from error
    try:
        # On Windows rename refuses to overwrite a concurrently created target.
        os.rename(staging, destination)
    except OSError as install_error:
        if not destination.exists():
            try:
                os.rename(backup, destination)
            except OSError as rollback_error:
                raise RuntimeError(
                    f"Installation failed and rollback could not restore '{destination}'. "
                    f"Previous executable is preserved at '{backup}': {rollback_error}"
                ) from install_error
        else:
            raise RuntimeError(
                f"Installation stopped because '{destination}' appeared during replacement. "
                f"Previous executable is preserved at '{backup}'."
            ) from install_error
        raise replace_error from install_error
    print(f"Installed at the original executable path; previous build preserved at '{backup}'.", flush=True)
