"""Shared helpers for the engine tests: a game driven exactly like lichess-bot, the engine's child processes,
and the test database.

Run the tests from PowerShell (or cmd), never from Git Bash: Git Bash puts Git's own libstdc++-6.dll first on
PATH, and then the engines load the wrong C runtime.
"""
import ctypes
import json
import os
import pathlib
import sqlite3
import subprocess
import time
from ctypes import wintypes

import chess
import chess.engine

ENGINES_DIRECTORY = pathlib.Path(__file__).resolve().parent.parent
ROOT_DIRECTORY = ENGINES_DIRECTORY.parent
ENGINE_UCI_EXE = ENGINES_DIRECTORY / "Engine UCI.exe"
KERNEL_EXE_NAME = "Kernel.exe"

# The same opponent every test plays against (python-chess sends it as UCI_Opponent after "ucinewgame").
OPPONENT = chess.engine.Opponent(name="Demolito_L4", title="BOT", rating=1692, is_engine=True)


# ############################################################################
# The engine's child processes (Toolhelp32: no psutil needed)
# ############################################################################

class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD),
                ("szExeFile", ctypes.c_wchar * 260)]


_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
_kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
_kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
_kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
_kernel32.OpenProcess.restype = wintypes.HANDLE
_kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
_ntdll = ctypes.WinDLL("ntdll")
_ntdll.NtSuspendProcess.argtypes = [wintypes.HANDLE]
_ntdll.NtResumeProcess.argtypes = [wintypes.HANDLE]

PROCESS_TERMINATE = 0x0001
PROCESS_SUSPEND_RESUME = 0x0800
INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value


def all_processes():
    """[(pid, parent pid, exe name)] of every process running now."""
    snapshot = _kernel32.CreateToolhelp32Snapshot(0x00000002, 0)     # TH32CS_SNAPPROCESS
    if snapshot == INVALID_HANDLE_VALUE:
        raise OSError(ctypes.get_last_error())
    processes = []
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(entry)
        ok = _kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while ok:
            processes.append((entry.th32ProcessID, entry.th32ParentProcessID, entry.szExeFile))
            ok = _kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        _kernel32.CloseHandle(snapshot)
    return processes


def children_of(parent_pid, exe_name=None):
    """The pids of the processes started by parent_pid (only the ones named exe_name, if given)."""
    return sorted(pid for pid, ppid, name in all_processes()
                  if ppid == parent_pid and (exe_name is None or name.lower() == exe_name.lower()))


def is_running(pid):
    return any(p == pid for p, _, _ in all_processes())


def _with_process(pid, access, action):
    handle = _kernel32.OpenProcess(access, False, pid)
    if not handle:
        raise OSError(ctypes.get_last_error(), f"OpenProcess({pid}) failed")
    try:
        return action(handle)
    finally:
        _kernel32.CloseHandle(handle)


def kill_process(pid):
    """Only ever used on processes this test started (the engine and its own Kernel workers)."""
    _with_process(pid, PROCESS_TERMINATE, lambda handle: _kernel32.TerminateProcess(handle, 9))


def suspend_process(pid):
    """A frozen worker: alive, but it never answers (the hung worker case)."""
    _with_process(pid, PROCESS_SUSPEND_RESUME, lambda handle: _ntdll.NtSuspendProcess(handle))


def wait_until(condition, timeout_s, step_s=0.05):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(step_s)
    return condition()


# ############################################################################
# A game, driven exactly like lichess-bot 2024.6.6.2 (lib/engine_wrapper.py)
# ############################################################################

def engine_environment(database_file):
    """The engine's environment: the normal one, plus the test database instead of the real one."""
    environment = dict(os.environ)
    environment["MRBITS_DATABASE_FILE"] = str(database_file)
    return environment


def open_engine(database_file, cwd, exe=ENGINE_UCI_EXE):
    # silence_stderr: false in config.yml -> lichess-bot passes stderr=subprocess.DEVNULL (engine_wrapper.py:52)
    return chess.engine.SimpleEngine.popen_uci([str(exe)], timeout=10., debug=False, setpgrp=True,
                                               stderr=subprocess.DEVNULL, cwd=str(cwd),
                                               env=engine_environment(database_file))


class Game:
    """One game: the engine plays one side, the test plays the other with fixed replies."""

    REPLIES = ["e7e5", "b8c6", "g8f6", "f8c5", "d7d6", "a7a6", "h7h6", "c8e6", "d8d7", "e8c8"]
    WHITE_REPLIES = ["e2e4", "g1f3", "f1c4", "b1c3", "d2d3", "a2a3", "h2h3", "c1e3", "d1d2", "e1c1"]

    def __init__(self, database_file, cwd, *, engine_is_white=True, game_id="tN252leL", clock_ms=9000,
                 inc_ms=3000, move_overhead_ms=2000, exe=ENGINE_UCI_EXE):
        self.database_file = database_file
        self.engine_is_white = engine_is_white
        self.board = chess.Board()
        self.white_clock = self.black_clock = clock_ms / 1000
        self.increment = inc_ms / 1000
        self.move_overhead = move_overhead_ms / 1000
        self.moves = []             # one dict per engine move: ply, fen_before, legal_moves, bestmove, ms
        self.reply_index = 0
        start = time.perf_counter()
        self.engine = open_engine(database_file, cwd, exe)
        self.handshake_ms = (time.perf_counter() - start) * 1000
        self.pid = self.engine.transport.get_pid()
        # EngineWrapper.configure(): uci_options (empty in config.yml) + game_specific_options(game)
        self.engine.configure({} if game_id is None else {"GameId": game_id})
        # get_opponent_info() -> send_opponent_information()
        self.engine.send_opponent_information(opponent=OPPONENT, engine_rating=1700)
        if not engine_is_white:
            self.play_the_opponent_move()

    def play_the_opponent_move(self):
        replies = self.REPLIES if self.engine_is_white else self.WHITE_REPLIES
        reply = None
        if self.reply_index < len(replies):
            reply = chess.Move.from_uci(replies[self.reply_index])
        self.reply_index += 1
        if reply not in self.board.legal_moves:
            reply = sorted(self.board.legal_moves, key=lambda move: move.uci())[0]
        self.board.push(reply)

    def play_engine_move(self):
        """One "go" exactly like lichess-bot sends it. Returns the move record of this test."""
        if len(self.board.move_stack) < 2:
            # first_move_time(): the first move of each side gets "go movetime 10000"
            limit = chess.engine.Limit(time=10, clock_id="first move")
            ponder = False
        else:
            # game_clock_time(): the engine's own clock minus move_overhead
            white = self.white_clock - (self.move_overhead if self.engine_is_white else 0)
            black = self.black_clock - (0 if self.engine_is_white else self.move_overhead)
            limit = chess.engine.Limit(white_clock=max(0.0, white), black_clock=max(0.0, black),
                                       white_inc=self.increment, black_inc=self.increment, clock_id="real time")
            ponder = True       # config.yml engine.ponder: true (Mr. Bits ignores "go ponder")
        record = {"ply": len(self.board.move_stack) + 1, "fen_before": self.board.fen(),
                  "legal_moves": sorted(move.uci() for move in self.board.legal_moves)}
        start = time.perf_counter()
        result = self.engine.play(self.board, limit, info=chess.engine.INFO_ALL, ponder=ponder, draw_offered=False,
                                  root_moves=None)
        elapsed = time.perf_counter() - start
        record["bestmove"] = result.move.uci() if result.move else None
        record["ms"] = elapsed * 1000
        record["legal"] = result.move is not None and result.move in self.board.legal_moves
        self.moves.append(record)
        if not record["legal"]:
            raise AssertionError(f"illegal move {record['bestmove']} at ply {record['ply']}")
        self.board.push(result.move)
        if len(self.board.move_stack) > 2:
            if self.engine_is_white:
                self.white_clock = self.white_clock - elapsed + self.increment
            else:
                self.black_clock = self.black_clock - elapsed + self.increment
        self.play_the_opponent_move()
        return record

    def finish(self):
        """EngineWrapper.__exit__: ping(), then quit(). Returns how long it took (ms)."""
        start = time.perf_counter()
        self.engine.ping()
        self.engine.quit()
        self.engine.close()
        return (time.perf_counter() - start) * 1000

    def close_quietly(self):
        try:
            self.engine.close()
        except Exception:
            pass


# ############################################################################
# The test database
# ############################################################################

def connect(database_file):
    connection = sqlite3.connect(str(database_file))
    connection.row_factory = sqlite3.Row
    return connection


def rows(database_file, sql, parameters=()):
    with connect(database_file) as connection:
        return [dict(row) for row in connection.execute(sql, parameters)]


def wait_for_engine_moves(database_file, game_id, count, timeout_s=5):
    """The engine writes each move after "bestmove", in its own thread: wait until all of them are there."""
    def are_all_there():
        try:
            return rows(database_file, "SELECT COUNT(*) AS n FROM engine_moves WHERE game_id = ?",
                        (game_id,))[0]["n"] >= count
        except sqlite3.Error:
            return False
    return wait_until(are_all_there, timeout_s)


class Checker:
    """Collects PASS/FAIL lines, so one run shows every problem at once."""

    def __init__(self, name):
        self.name = name
        self.results = []

    def check(self, condition, label, details=""):
        self.results.append({"ok": bool(condition), "label": label, "details": details})
        print(f"  {'PASS' if condition else 'FAIL'}  {label}" + (f"   ({details})" if details else ""), flush=True)
        return bool(condition)

    @property
    def ok(self):
        return all(result["ok"] for result in self.results)

    def summary(self):
        failed = [result for result in self.results if not result["ok"]]
        return {"name": self.name, "passed": len(self.results) - len(failed), "failed": len(failed),
                "failures": failed}


def write_json(path, data):
    pathlib.Path(path).write_text(json.dumps(data, indent=1, default=str), encoding="utf-8")
