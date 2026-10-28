"""
schema.sql itself: it is applied at every engine start and by db.py --init, so it must be safe to apply again,
safe to apply from two programs at the same moment, all or nothing, and fast to read for the dashboard.

  * applying it again keeps every row and changes nothing;
  * two programs applying it at the same moment never fail (everything after the PRAGMAs is ONE transaction:
    before, two engines starting together could fail with "view v_games already exists" and lose a game);
  * a reader never sees a view missing while another program applies it;
  * a failure halfway leaves the database exactly as it was;
  * no queries.py statement ever scans engine_moves or worker_runs: one game, a page of games, a filtered
    count and engine_health() only search them through indexes.
"""
import re
import sqlite3
import threading
import unittest
from typing import Any, Callable

from helpers import (DatabaseTestCase, add_engine_game, add_engine_move, add_event, db, load_fixture, local_ms,
                     queries, store_telemetry_line)
from test_queries import LOCAL_GAME, build_dataset, worker

ENGINE_TABLES = {"engine_moves", "worker_runs", "em", "w"}  # (em and w: their names inside the views)
FILTER_SETS = ({}, {"result": "win"}, {"synced": False}, {"local": False}, {"had_timeouts": True},
               {"had_timeouts": False}, {"had_worker_failures": True}, {"had_no_kernel_answer": True},
               {"had_stalemate_override": True}, {"opponent_kind": "human", "rated": True},
               {"date_from": "2026-10-21", "date_to": "2026-10-23"}, {"opponent_rating_min": 1500},
               {"engine_version": ["build-A", "build-B"]})

Call = Callable[[sqlite3.Connection], Any]


def build_edge_cases(con: sqlite3.Connection) -> None:
    """Rows the views must handle, besides test_queries' dataset."""
    # Played by hand: no answer at all (every worker failed, no search time, no depth), a move whose time
    # wasn't recorded, a worker with a search time but no depth, and an only move.
    add_engine_game(con, LOCAL_GAME, local_ms(2026, 10, 23, 12), engine_version=None)
    add_engine_move(con, LOCAL_GAME, 5, path="no_kernel_answer", t_total_ms=3100.0, stockfish_depth=14,
                    workers=(worker(1, status="timeout", depth=None, search_ms=None),
                             worker(2, status="error", depth=None, search_ms=None)))
    add_engine_move(con, LOCAL_GAME, 7, t_total_ms=None,
                    workers=(worker(1, depth=4, search_ms=None), worker(2, status="no_moves", depth=None,
                                                                        search_ms=12.5)))
    add_engine_move(con, LOCAL_GAME, 9, path="only_move", t_total_ms=3.0)
    add_event(con, local_ms(2026, 10, 23, 12, 5), LOCAL_GAME, None, "go failed: x  -> exiting", level="error")
    # The old plan's per-move example as a game of its own.
    telemetry = load_fixture("plan03_telemetry_example.json")["telemetry"]
    add_engine_game(con, telemetry["gameId"], telemetry["receivedAt"], engine_version=telemetry["engineVersion"])
    store_telemetry_line(con, telemetry)


def schema_objects(con: sqlite3.Connection) -> dict[tuple[str, str], str]:
    """{(type, name): CREATE statement} of every table, index and view (SQLite's own left out)."""
    rows = con.execute("SELECT type, name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite~_%' ESCAPE '~'")
    return {(kind, name): sql for kind, name, sql in rows}


def scanned(con: sqlite3.Connection, sql: str) -> set[str]:
    """The tables (or aliases) a statement reads with a full SCAN, from EXPLAIN QUERY PLAN."""
    details = [row[3] for row in con.execute("EXPLAIN QUERY PLAN " + sql)]
    return {match.group(1) for detail in details if (match := re.match(r"SCAN (\S+)", detail))}


class TestSchema(DatabaseTestCase):
    """schema.sql against a database full of games (self.con, made by db.init())."""

    def setUp(self) -> None:
        """Fill the database."""
        super().setUp()
        build_dataset(self.con)
        build_edge_cases(self.con)
        self.schema = db.SCHEMA.read_text(encoding="utf-8")

    def counts(self, con: sqlite3.Connection) -> dict[str, int]:
        """The number of rows in every table."""
        tables = [name for kind, name in schema_objects(con) if kind == "table"]
        return {table: con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] for table in tables}

    def calls(self) -> list[tuple[str, Call]]:
        """Every queries.py function, with the filters, orders and games of the dataset."""
        games = [row[0] for row in self.con.execute("SELECT game_id FROM v_games ORDER BY game_id")]
        moves = self.con.execute("SELECT game_id, ply FROM engine_moves ORDER BY game_id, ply").fetchall()
        calls: list[tuple[str, Call]] = [
            ("filter_choices", lambda con: queries.filter_choices(con=con)),
            ("results_by_day", lambda con: queries.results_by_day(con=con)),
            ("results_by_day local=False", lambda con: queries.results_by_day(local=False, con=con)),
            ("rating_history", lambda con: queries.rating_history(con=con)),
            ("results_by_opponent_rating", lambda con: queries.results_by_opponent_rating(con=con)),
            ("results_by_opponent_rating 500", lambda con: queries.results_by_opponent_rating(500, con=con)),
            ("engine_health", lambda con: queries.engine_health(con=con)),
            ("engine_health 3", lambda con: queries.engine_health(3, con=con)),
            ("recent_events", lambda con: queries.recent_events(con=con)),
            ("list_games page 2", lambda con: queries.list_games(limit=4, offset=4, con=con)),
        ]
        for order_by in sorted(queries.ORDER_BY_COLUMNS):
            calls.append((f"list_games order_by={order_by}",
                          lambda con, o=order_by: queries.list_games(order_by=o, descending=False, limit=None,
                                                                     con=con)))
        for filters in FILTER_SETS:
            calls.append((f"list / count {filters}",
                          lambda con, f=filters: (queries.list_games(limit=None, con=con, **f),
                                                  queries.count_games(con=con, **f))))
        for game_id in games + ["noSuchGm"]:
            calls.append((f"game {game_id}",
                          lambda con, g=game_id: (queries.game_overview(g, con=con), queries.game_moves(g, con=con),
                                                  queries.engine_moves(g, con=con), queries.game_events(g, con=con))))
        for game_id, ply in moves:
            calls.append((f"move {game_id} {ply}",
                          lambda con, g=game_id, p=ply: queries.move_detail(g, p, con=con)))
        return calls

    def test_applying_it_again_keeps_every_row_and_changes_nothing(self) -> None:
        objects, counts = schema_objects(self.con), self.counts(self.con)
        answers = [call(self.con) for _, call in self.calls()]
        self.con.executescript(self.schema)
        self.assertEqual(schema_objects(self.con), objects)
        self.assertEqual(self.counts(self.con), counts)
        self.assertEqual([call(self.con) for _, call in self.calls()], answers)

    def test_everything_after_the_pragmas_is_one_transaction(self) -> None:
        code = "\n".join(line.split("--", 1)[0] for line in self.schema.splitlines())   # the comments left out
        statements = [" ".join(statement.split()) for statement in code.split(";") if statement.strip()]
        begin = statements.index("BEGIN IMMEDIATE")
        # (journal_mode can't change inside a transaction, so only the PRAGMAs may come first)
        self.assertTrue(statements[:begin] and all(statement.startswith("PRAGMA") for statement in statements[:begin]))
        self.assertEqual(statements.count("BEGIN IMMEDIATE"), 1)
        self.assertEqual(statements.count("COMMIT"), 1)
        self.assertEqual(statements[-1], "COMMIT")

    def test_two_programs_applying_it_at_the_same_moment_never_fail(self) -> None:
        errors: list[str] = []

        def apply() -> None:
            try:
                con = db.connect()          # (a 5 s busy timeout, like Engine UCI.exe's)
                try:
                    con.executescript(self.schema)
                finally:
                    con.close()
            except sqlite3.Error as error:
                errors.append(repr(error))

        for _ in range(20):
            threads = [threading.Thread(target=apply) for _ in range(6)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
        self.assertEqual(errors, [])

    def test_a_reader_never_sees_a_view_missing(self) -> None:
        stop = threading.Event()
        failures: list[str] = []

        def read() -> None:
            while not stop.is_set():
                con = db.connect()              # a new connection per read, as queries.py does without con=
                try:
                    for view in ("v_games", "v_engine_moves", "v_moves"):
                        con.execute(f"SELECT COUNT(*) FROM {view}").fetchone()
                except sqlite3.Error as error:
                    failures.append(repr(error))
                finally:
                    con.close()

        reader = threading.Thread(target=read)
        reader.start()
        try:
            for _ in range(40):
                self.con.executescript(self.schema)
        finally:
            stop.set()
            reader.join()
        self.assertEqual(failures, [])

    def test_a_failure_halfway_changes_nothing(self) -> None:
        objects, counts = schema_objects(self.con), self.counts(self.con)
        anchor = "DROP VIEW IF EXISTS v_moves;"
        self.assertEqual(self.schema.count(anchor), 1)
        broken = self.schema.replace(anchor, "CREATE TABLE engine_games (x);\n" + anchor)  # fails: it exists
        con = db.connect()
        try:
            with self.assertRaises(sqlite3.Error):
                con.executescript(broken)
            con.execute("ROLLBACK")                    # what Engine UCI.exe does (db.init closes the connection)
        finally:
            con.close()
        self.assertEqual(schema_objects(self.con), objects)
        self.assertEqual(self.counts(self.con), counts)

    def test_no_query_scans_the_engine_tables(self) -> None:
        """Every statement every queries.py call runs, explained: engine_moves and worker_runs only by index."""
        statements: list[str] = []
        calls = self.calls()            # (before the trace: its own setup queries aren't the dashboard's)
        self.con.set_trace_callback(statements.append)  # (sqlite3 gives the SQL with the values filled in)
        try:
            for _, call in calls:
                call(self.con)
        finally:
            self.con.set_trace_callback(None)
        self.assertGreater(len(statements), 100)
        for sql in dict.fromkeys(statements):
            with self.subTest(sql=sql[:100]):
                self.assertEqual(scanned(self.con, sql) & ENGINE_TABLES, set())


if __name__ == "__main__":
    unittest.main()
