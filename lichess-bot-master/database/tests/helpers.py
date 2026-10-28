"""
Shared test helpers: imports of the database modules, a fresh temporary database per test, the fixtures,
fake lichess HTTP answers, and engine data written the way Engine UCI.exe writes it.

The tests never touch the network (sockets are blocked below), the token, config.yml or the real
mrbits.sqlite: every DatabaseTestCase points db.DB_PATH at a temporary file and sync_lichess.CONFIG_PATH at
a file that doesn't exist, and removes LICHESS_TOKEN / LICHESS_BOT_TOKEN from the environment while it runs.
"""
from __future__ import annotations

import contextlib
import io
import json
import logging
import os
import socket
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional, Union
from unittest import mock

import chess
import requests

DATABASE_DIR = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
if str(DATABASE_DIR) not in sys.path:
    sys.path.insert(0, str(DATABASE_DIR))

import db  # noqa: E402
import queries  # noqa: E402,F401  (re-exported for the test modules)
import sync_lichess  # noqa: E402

DUMMY_TOKEN = "lip_dummyTokenForTests0000"  # not a real token: the tests never read the real one


def _no_network(*args: Any, **kwargs: Any) -> None:
    raise RuntimeError("the tests must never use the network")


socket.socket.connect = _no_network  # type: ignore[method-assign]
socket.socket.connect_ex = _no_network  # type: ignore[method-assign]
socket.create_connection = _no_network  # type: ignore[assignment]

# The sync's warnings are checked with assertLogs where they matter; elsewhere keep the test output clean.
logging.getLogger(sync_lichess.__name__).addHandler(logging.NullHandler())


# ############################################################################
# Temporary database
# ############################################################################

class DatabaseTestCase(unittest.TestCase):
    """Every test gets a new database in a temporary folder (db.DB_PATH points there) and self.con."""

    def setUp(self) -> None:
        """Create the temporary database and patch the paths and the environment."""
        temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(temp.cleanup)  # registered first, so it runs last (after the connections closed)
        self.tmp = Path(temp.name)
        self.db_path = self.tmp / "mrbits.sqlite"
        for patcher in (mock.patch.object(db, "DB_PATH", self.db_path),
                        mock.patch.object(sync_lichess, "CONFIG_PATH", self.tmp / "missing-config.yml"),
                        mock.patch.dict(os.environ)):
            patcher.start()
            self.addCleanup(patcher.stop)
        for variable in (sync_lichess.TOKEN_ENV, sync_lichess.LICHESS_BOT_TOKEN_ENV):
            os.environ.pop(variable, None)  # (the patched environment is restored after the test)
        quiet(db.init)
        self.con = db.connect()
        self.addCleanup(self.con.close)

    def ids(self, rows: list[dict[str, Any]]) -> set[str]:
        """The game_id of every row."""
        return {row["game_id"] for row in rows}


def quiet(function: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Call a function with its prints swallowed."""
    with contextlib.redirect_stdout(io.StringIO()):
        return function(*args, **kwargs)


def run_main(main: Callable[[list[str]], int], argv: list[str]) -> tuple[int, str, str]:
    """Run a main(argv) and return (exit code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(argv)
    return code, out.getvalue(), err.getvalue()


def local_ms(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> int:
    """Unix ms of a LOCAL date and time (the dashboard's dates are local)."""
    return int(datetime(year, month, day, hour, minute).timestamp() * 1000)


# ############################################################################
# Fixtures
# ############################################################################

def load_fixture(name: str) -> Any:
    """A JSON fixture."""
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def synthetic_games() -> list[dict[str, Any]]:
    """The synthetic edge-case games (each has '_case' and '_expected')."""
    return load_fixture("synthetic_games.json")["games"]


def synthetic_game(game_id: str) -> dict[str, Any]:
    """One synthetic game by id."""
    return next(game for game in synthetic_games() if game["id"] == game_id)


def api_examples() -> list[dict[str, Any]]:
    """The two official game JSON examples of the lichess API documentation (q7ZvsdUF, WFZ8aZWA)."""
    lines = (FIXTURES / "lichess_api_examples.ndjson").read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def write_ndjson(path: Path, games: list[dict[str, Any]]) -> Path:
    """Write games as NDJSON, like the lichess export streams them."""
    path.write_text("".join(json.dumps(game) + "\n" for game in games), encoding="utf-8")
    return path


# ############################################################################
# Fake lichess HTTP
# ############################################################################

class FakeResponse:
    """Just enough of requests.Response for sync_lichess."""

    def __init__(self, status_code: int = 200, json_body: Any = None, games: tuple[Any, ...] = ()) -> None:
        """A response with a JSON body, or NDJSON lines (one per game; bytes are sent as they are)."""
        self.status_code = status_code
        self._json = json_body
        self._lines = [game if isinstance(game, bytes) else json.dumps(game).encode() for game in games]
        self.closed = False

    def json(self) -> Any:
        """The JSON body."""
        return self._json

    def iter_lines(self) -> Any:
        """The NDJSON lines."""
        yield from self._lines

    def raise_for_status(self) -> None:
        """Like requests: an HTTPError for 4xx / 5xx."""
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} Error for url: (fake)", response=self)  # type: ignore

    def close(self) -> None:
        """Close."""
        self.closed = True

    def __enter__(self) -> "FakeResponse":
        """Context manager, like requests.Response."""
        return self

    def __exit__(self, *exc: Any) -> None:
        """Close on exit."""
        self.close()


Answer = Union[FakeResponse, Callable[[dict[str, Any]], FakeResponse]]


class FakeSession:
    """
    Stands in for requests.Session: answers (method, path) from `routes` and records every call.

    routes: {("GET", "/api/account"): FakeResponse | callable(call) -> FakeResponse | [several, in order]}
    """

    def __init__(self, routes: dict[tuple[str, str], Union[Answer, list[Answer]]]) -> None:
        """Remember the routes."""
        self.routes = routes
        self.calls: list[dict[str, Any]] = []
        self.headers: dict[str, str] = {}
        self.closed = False

    def request(self, method: str, url: str, **kwargs: Any) -> FakeResponse:
        """Record the call and answer it."""
        call = {"method": method, "url": url, **kwargs}
        self.calls.append(call)
        assert url.startswith(sync_lichess.LICHESS_URL), url
        key = (method, url[len(sync_lichess.LICHESS_URL):])
        if key not in self.routes:
            raise AssertionError(f"unexpected request {key}")
        answer = self.routes[key]
        if isinstance(answer, list):
            if not answer:
                raise AssertionError(f"too many requests {key}")
            answer = answer.pop(0)
        return answer(call) if callable(answer) else answer

    def close(self) -> None:
        """Close."""
        self.closed = True

    def __enter__(self) -> "FakeSession":
        """Context manager, like requests.Session."""
        return self

    def __exit__(self, *exc: Any) -> None:
        """Close on exit."""
        self.close()


def account(user_id: str = "mr_bits", username: str = "Mr_Bits") -> FakeResponse:
    """The answer of GET /api/account."""
    return FakeResponse(json_body={"id": user_id, "username": username, "title": "BOT"})


# ############################################################################
# Data as the two writers store it
# ############################################################################

def add_game(con: sqlite3.Connection, game_id: str, **columns: Any) -> None:
    """A games row as sync_lichess stores it (sensible defaults for the columns not given)."""
    row = {"game_id": game_id, "created_at": local_ms(2026, 10, 20, 12), "rated": 1, "variant": "standard",
           "source": "friend", "speed": "blitz", "clock_initial_s": 180, "clock_increment_s": 2,
           "our_color": "white", "result": "win", "status": "mate", "plies": 40, "synced_at": 0}
    row.update(columns)
    names = ", ".join(row)
    with con:
        con.execute(f"INSERT INTO games ({names}) VALUES ({', '.join('?' * len(row))})", list(row.values()))


def add_lichess_moves(con: sqlite3.Connection, game_id: str, sans: list[str], our_color: str = "white") -> None:
    """moves rows for a game from the start position (clock_cs and think_ms made up)."""
    board = chess.Board()
    rows = []
    for ply, san in enumerate(sans, start=1):
        move = board.parse_san(san)
        by_us = int(board.turn == (our_color == "white"))
        rows.append((game_id, ply, by_us, move.uci(), san, 18000 - ply * 10, None if ply <= 2 else 1000 + ply))
        board.push(move)
    with con:
        con.executemany(sync_lichess.INSERT_MOVE_SQL, rows)


def add_engine_game(con: sqlite3.Connection, game_id: str, first_move_at: int, **columns: Any) -> None:
    """The engine_games row Engine UCI writes when a game starts."""
    row = {"game_id": game_id, "our_color": "white", "first_move_at": first_move_at,
           "last_move_at": first_move_at + 60_000, "engine_version": "test-build"}
    row.update(columns)
    with con:
        con.execute(f"INSERT INTO engine_games ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})",
                    list(row.values()))


def add_engine_move(con: sqlite3.Connection, game_id: str, ply: int, *, path: str = "kernel",
                    t_total_ms: Optional[float] = 500.0, workers: tuple[dict[str, Any], ...] = (),
                    **columns: Any) -> None:
    """
    One engine move the way Engine UCI writes it: one transaction with the engine_moves row, a worker_runs row
    per worker, their worker_depths and their root_candidates.

    A worker is a dict of worker_runs columns (root_moves / unsearched_root_moves as Python lists) plus
    "depths": [worker_depths dicts] and "candidates": [root_candidates dicts].
    """
    move = {"game_id": game_id, "ply": ply, "received_at": columns.pop("received_at", 0), "path": path,
            "workers": len(workers), "t_total_ms": t_total_ms, "engine_version": "test-build"}
    move.update(columns)
    with con:
        con.execute(f"INSERT INTO engine_moves ({', '.join(move)}) VALUES ({', '.join('?' * len(move))})",
                    list(move.values()))
        for worker in workers:
            worker = dict(worker)
            depths = worker.pop("depths", [])
            candidates = worker.pop("candidates", [])
            for key in ("root_moves", "unsearched_root_moves"):
                if isinstance(worker.get(key), list):
                    worker[key] = json.dumps(worker[key])
            run = {"game_id": game_id, "ply": ply, "status": "ok", **worker}
            con.execute(f"INSERT INTO worker_runs ({', '.join(run)}) VALUES ({', '.join('?' * len(run))})",
                        list(run.values()))
            for depth in depths:
                row = {"game_id": game_id, "ply": ply, "worker": worker["worker"], "completed": 1, **depth}
                con.execute(f"INSERT INTO worker_depths ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})",
                            list(row.values()))
            for candidate in candidates:
                row = {"game_id": game_id, "ply": ply, "worker": worker["worker"], "depth": worker.get("depth"),
                       **candidate}
                con.execute(f"INSERT INTO root_candidates ({', '.join(row)}) "
                            f"VALUES ({', '.join('?' * len(row))})", list(row.values()))


def add_event(con: sqlite3.Connection, at: int, game_id: Optional[str], ply: Optional[int], message: str,
              level: str = "warning", source: str = "engine") -> None:
    """An events row."""
    with con:
        con.execute("INSERT INTO events (at, game_id, ply, level, source, message) VALUES (?, ?, ?, ?, ?, ?)",
                    (at, game_id, ply, level, source, message))


def store_telemetry_line(con: sqlite3.Connection, line: dict[str, Any]) -> None:
    """
    Store plan 03's per-move telemetry line the way Engine UCI fills the tables: engine_moves, then per worker
    worker_runs, worker_depths (perDepth: completed depths) and root_candidates (rootScores).
    """
    go = line.get("go", {})
    timers = line.get("timersMs", {})
    workers = []
    for worker in line.get("workers", []):
        workers.append({
            "worker": worker["worker"], "root_moves": worker.get("rootMoves"), "status": worker["status"],
            "depth": worker.get("depth"), "best_move": worker.get("bestMove"), "best_score": worker.get("score"),
            "setup_ms": worker.get("setupMs"), "search_ms": worker.get("searchMs"), "nodes": worker.get("nodes"),
            "leaf_nodes": worker.get("leafNodes"), "pruned": worker.get("pruned"),
            "total_nodes": worker.get("totalNodes"),
            "depths": [{"depth": d["depth"], "ms": d.get("ms"), "nodes": d.get("nodes"),
                        "leaf_nodes": d.get("leafNodes"), "pruned": d.get("pruned"), "best_move": d.get("bestMove"),
                        "score": d.get("score")} for d in worker.get("perDepth", [])],
            "candidates": [{"move": c["move"], "score": c.get("score"), "exact": int(bool(c.get("exact")))}
                           for c in worker.get("rootScores", [])],
        })
    add_engine_move(con, line["gameId"], line["ply"], path=line["path"], t_total_ms=timers.get("total"),
                    workers=tuple(workers), received_at=line["receivedAt"], wtime_ms=go.get("wtime"),
                    btime_ms=go.get("btime"), winc_ms=go.get("winc"), binc_ms=go.get("binc"),
                    movetime_ms=go.get("movetime"), allowed_seconds=line.get("allowedSeconds"),
                    legal_moves=line.get("legalMoves"), best_move=line.get("bestMove"),
                    best_score=line.get("bestScore"), t_legal_ms=timers.get("legal"),
                    t_kernel_ms=timers.get("search"), t_tie_check_ms=timers.get("tieCheck"),
                    engine_version=line.get("engineVersion"))
