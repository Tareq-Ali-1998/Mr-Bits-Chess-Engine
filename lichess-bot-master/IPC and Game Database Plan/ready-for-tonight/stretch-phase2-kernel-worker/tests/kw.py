"""Helpers for the Kernel worker prototype tests (file mode runner, worker client, memory info)."""
import ctypes
import json
import os
import re
import subprocess
import time
from ctypes import wintypes

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN = os.path.join(HERE, "bin")

TIMING_KEYS = ("searchMs", "setupMs")


# ---------------------------------------------------------------- file mode
def file_request(pos, max_depth=None, seconds=5):
    """The exact keys Engine UCI's ChessState::serializeObject() writes, plus the optional maxDepth."""
    d = {
        "engineColor": pos["engineColor"],
        "allowedEngineTimeInSeconds": seconds,
        "previousMoves": pos["moves"],
        "bestMove": "",
        "bestMoveScore": 0,
        "movesForThisThread": pos["rootMoves"],
        "report": "",
    }
    if max_depth is not None:
        d["maxDepth"] = max_depth
    return d


REPORT_FIELDS = {
    "depth": r"The current depth: (-?\d+)",
    "leafNodes": r"The number of all the final states \(Leaf Nodes\): (-?\d+)",
    "nodes": r"The number of all the inner and final states: (-?\d+)",
    "pruned": r"The number of all pruned branches: (-?\d+)",
    "totalMs": r"The total Process consumed time in milliseconds: (-?\d+)",
}


def parse_report(report):
    out = {}
    for k, rx in REPORT_FIELDS.items():
        m = re.search(rx, report)
        out[k] = int(m.group(1)) if m else None
    return out


def run_file_mode(exe, json_path, request, timeout=600):
    with open(json_path, "w") as f:
        json.dump(request, f, indent=4)
    t0 = time.perf_counter()
    p = subprocess.run([exe, json_path], capture_output=True, timeout=timeout)
    wall_ms = (time.perf_counter() - t0) * 1000
    with open(json_path) as f:
        out = json.load(f)
    rep = parse_report(out.get("report", ""))
    return {
        "returncode": p.returncode,
        "stdout": p.stdout,
        "stderr": p.stderr,
        "wallMs": wall_ms,
        "bestMove": out.get("bestMove"),
        "score": out.get("bestMoveScore"),
        "keys": sorted(out.keys()),
        **rep,
    }


# ---------------------------------------------------------------- memory
class PROCESS_MEMORY_COUNTERS_EX(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
        ("PrivateUsage", ctypes.c_size_t),
    ]


_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.K32GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
_k32.K32GetProcessMemoryInfo.restype = wintypes.BOOL


def memory_of(popen):
    c = PROCESS_MEMORY_COUNTERS_EX()
    c.cb = ctypes.sizeof(c)
    if not _k32.K32GetProcessMemoryInfo(wintypes.HANDLE(int(popen._handle)), ctypes.byref(c), c.cb):
        raise OSError(ctypes.get_last_error())
    return {
        "workingSetKB": c.WorkingSetSize // 1024,
        "peakWorkingSetKB": c.PeakWorkingSetSize // 1024,
        "privateKB": c.PrivateUsage // 1024,
    }


# ---------------------------------------------------------------- worker
class Worker:
    def __init__(self, exe, stderr_path):
        self.stderr_file = open(stderr_path, "wb")
        self.p = subprocess.Popen([exe, "--worker"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=self.stderr_file, bufsize=0)
        self.raw_lines = []

    def send(self, obj):
        line = json.dumps(obj, separators=(",", ":")).encode() + b"\n"
        self.p.stdin.write(line)
        self.p.stdin.flush()

    def recv(self):
        line = self.p.stdout.readline()
        if not line:
            raise EOFError("worker closed stdout (exit code %r)" % self.p.poll())
        self.raw_lines.append(line)
        if not line.endswith(b"\n") or line.endswith(b"\r\n"):
            raise ValueError("bad line ending: %r" % line[-5:])
        return json.loads(line)

    def request(self, obj):
        self.send(obj)
        return self.recv()

    def memory(self):
        return memory_of(self.p)

    def quit(self, timeout=10):
        try:
            self.send({"type": "quit"})
            self.p.stdin.close()
        except OSError:
            pass
        try:
            rc = self.p.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.p.kill()  # only ever our own child
            rc = self.p.wait()
        rest = self.p.stdout.read()
        self.stderr_file.close()
        return rc, rest


def search_request(pos, rid, max_depth, time_ms=1000):
    return {"type": "search", "id": rid, "engineColor": pos["engineColor"], "moves": pos["moves"],
            "rootMoves": pos["rootMoves"], "timeMs": time_ms, "maxDepth": max_depth}


def strip_timing(ans):
    """An answer without the fields that legitimately change between runs (timings, the id)."""
    a = {k: v for k, v in ans.items() if k not in TIMING_KEYS and k != "id"}
    a["perDepth"] = [{k: v for k, v in e.items() if k != "ms"} for e in ans.get("perDepth", [])]
    return a
