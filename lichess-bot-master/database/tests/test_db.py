"""Tests of db.py: init, connect, backup, check, recent and the command line."""
import sqlite3
import unittest
from pathlib import Path
from unittest import mock

from helpers import DatabaseTestCase, add_engine_game, add_engine_move, add_event, db, quiet, run_main

TABLES = {"games", "moves", "engine_games", "engine_moves", "worker_runs", "worker_depths", "root_candidates",
          "events", "position_analysis", "sync_state"}
VIEWS = {"v_games", "v_engine_moves", "v_moves"}


def names(con: sqlite3.Connection, kind: str) -> set[str]:
    """The tables, views or indexes of a database (SQLite's own left out)."""
    rows = con.execute("SELECT name FROM sqlite_master WHERE type = ? AND name NOT LIKE 'sqlite~_%' ESCAPE '~'",
                       (kind,))
    return {row[0] for row in rows}


class TestPaths(unittest.TestCase):
    """The database and the schema sit next to db.py, whatever the working directory."""

    def test_default_paths(self) -> None:
        here = Path(db.__file__).resolve().parent
        self.assertEqual(db.DB_PATH, here / "mrbits.sqlite")
        self.assertEqual(db.SCHEMA, here / "schema.sql")
        self.assertTrue(db.SCHEMA.exists())


class TestInit(DatabaseTestCase):
    """db.init(): creates, and can run again safely."""

    def test_creates_every_table_and_view_in_wal_mode(self) -> None:
        self.assertEqual(names(self.con, "table"), TABLES)
        self.assertEqual(names(self.con, "view"), VIEWS)
        self.assertEqual(self.con.execute("PRAGMA journal_mode").fetchone()[0], "wal")

    def test_init_twice_is_harmless_and_keeps_the_data(self) -> None:
        add_engine_game(self.con, "keepMe01", first_move_at=1)
        add_engine_move(self.con, "keepMe01", 1, workers=({"worker": 1, "depth": 5},))
        quiet(db.init)
        quiet(db.init)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM worker_runs").fetchone()[0], 1)
        self.assertEqual(self.con.execute("SELECT max_depth FROM v_engine_moves").fetchone()[0], 5)
        self.assertEqual(names(self.con, "table"), TABLES)
        self.assertEqual(names(self.con, "view"), VIEWS)

    def test_init_says_what_it_did(self) -> None:
        code, out, _ = run_main(db.main, ["--init"])
        self.assertEqual(code, 0)
        self.assertIn("Updated", out)
        self.assertIn("existing data kept", out)
        self.assertIn("10 tables, 3 views, journal_mode=wal", out)

    def test_init_upgrades_an_older_database(self) -> None:
        with self.con:
            self.con.execute("DROP VIEW v_moves")
            self.con.execute("DROP INDEX idx_events_at")
        quiet(db.init)
        self.assertIn("v_moves", names(self.con, "view"))
        self.assertIn("idx_events_at", names(self.con, "index"))

    def test_init_creates_the_folder(self) -> None:
        path = self.tmp / "new" / "folder" / "mrbits.sqlite"
        quiet(db.init, path)
        self.assertTrue(path.exists())


class TestConnect(DatabaseTestCase):
    """db.connect(): the settings every connection needs."""

    def test_foreign_keys_on_and_busy_timeout(self) -> None:
        con = db.connect()
        self.addCleanup(con.close)
        self.assertEqual(con.execute("PRAGMA foreign_keys").fetchone()[0], 1)
        self.assertEqual(con.execute("PRAGMA busy_timeout").fetchone()[0], 5000)

    def test_foreign_keys_are_enforced(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError):
            with self.con:
                self.con.execute("INSERT INTO worker_runs (game_id, ply, worker, status) "
                                 "VALUES ('orphan01', 1, 1, 'ok')")

    def test_a_plain_sqlite3_connection_would_not_enforce_them(self) -> None:
        """The reason connect() exists: SQLite forgets foreign_keys for every new connection."""
        plain = sqlite3.connect(self.db_path)
        self.addCleanup(plain.close)
        self.assertEqual(plain.execute("PRAGMA foreign_keys").fetchone()[0], 0)

    def test_rows_work_like_dicts(self) -> None:
        add_engine_game(self.con, "dictRow1", first_move_at=5, engine_version="b1")
        row = self.con.execute("SELECT game_id, engine_version FROM engine_games").fetchone()
        self.assertEqual(dict(row), {"game_id": "dictRow1", "engine_version": "b1"})

    def test_a_missing_database_is_an_error_and_is_not_created(self) -> None:
        missing = self.tmp / "nothing-here.sqlite"
        with self.assertRaises(FileNotFoundError) as caught:
            db.connect(missing)
        self.assertIn("db.py --init", str(caught.exception))
        self.assertFalse(missing.exists())


class TestBackup(DatabaseTestCase):
    """db.backup(): SQLite's online backup, never a plain file copy."""

    def test_backup_includes_data_still_in_the_wal(self) -> None:
        writer = db.connect()
        self.addCleanup(writer.close)
        writer.execute("PRAGMA wal_autocheckpoint = 0")  # keep everything in mrbits.sqlite-wal
        for number in range(50):
            add_engine_game(writer, f"walGame{number:02d}", first_move_at=number)
        wal = self.db_path.with_name(self.db_path.name + "-wal")
        self.assertGreater(wal.stat().st_size, 0)

        target = quiet(db.backup)

        self.assertEqual(target.parent, self.tmp / "backup")
        self.assertRegex(target.name, r"^mrbits-\d{4}-\d{2}-\d{2}_\d{2}-\d{2}(-\d+)?\.sqlite$")
        copy = sqlite3.connect(target)
        self.addCleanup(copy.close)
        self.assertEqual(copy.execute("SELECT COUNT(*) FROM engine_games").fetchone()[0], 50)
        self.assertEqual(copy.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        self.assertEqual(copy.execute("PRAGMA journal_mode").fetchone()[0], "delete")  # one self-contained file

    def test_backups_never_overwrite_each_other(self) -> None:
        first = quiet(db.backup)
        second = quiet(db.backup)
        self.assertNotEqual(first, second)
        self.assertTrue(first.exists() and second.exists())
        folder = self.tmp / "backup"
        (folder / "mrbits-2026-10-27_21-05.sqlite").touch()
        (folder / "mrbits-2026-10-27_21-05-2.sqlite").touch()
        self.assertEqual(db._free_backup_path(folder, "2026-10-27_21-05").name, "mrbits-2026-10-27_21-05-3.sqlite")

    def test_backup_to_a_chosen_file_and_never_over_an_existing_one(self) -> None:
        target = self.tmp / "elsewhere" / "copy.sqlite"
        self.assertEqual(quiet(db.backup, target), target)
        with self.assertRaises(FileExistsError):
            quiet(db.backup, target)


class TestCheck(DatabaseTestCase):
    """db.check() and --check."""

    def test_check_reports_ok_and_counts_rows(self) -> None:
        add_engine_game(self.con, "count001", first_move_at=1)
        add_engine_move(self.con, "count001", 1, workers=({"worker": 1}, {"worker": 2}))
        report = db.check()
        self.assertEqual(report["integrity"], ["ok"])
        self.assertEqual(report["foreign_key_errors"], 0)
        self.assertEqual(report["journal_mode"], "wal")
        self.assertEqual(set(report["tables"]), TABLES)
        self.assertEqual(report["tables"]["worker_runs"], 2)
        self.assertTrue(db.is_healthy(report))

    def test_check_finds_rows_whose_parent_is_missing(self) -> None:
        plain = sqlite3.connect(self.db_path)  # foreign keys off: the orphan gets in
        with plain:
            plain.execute("INSERT INTO worker_runs (game_id, ply, worker, status) VALUES ('orphan01', 1, 1, 'ok')")
        plain.close()
        report = db.check()
        self.assertEqual(report["foreign_key_errors"], 1)
        self.assertFalse(db.is_healthy(report))
        code, out, _ = run_main(db.main, ["--check"])
        self.assertEqual(code, 1)
        self.assertIn("1 rows point at a missing row", out)


class TestRecent(DatabaseTestCase):
    """db.recent() and --recent: the newest engine moves and events, newest first."""

    def test_newest_first_and_limited(self) -> None:
        add_engine_game(self.con, "recent01", first_move_at=1_000)
        for ply in (1, 3, 5):
            add_engine_move(self.con, "recent01", ply, received_at=1_000 + ply, best_move=f"m{ply}", best_score=ply)
        add_event(self.con, 2_000, "recent01", 5, "1 of 28 gave no usable answer")
        add_event(self.con, 3_000, None, None, "could not start", level="error", source="stockfish")
        report = db.recent(2)
        self.assertEqual([move["ply"] for move in report["moves"]], [5, 3])
        self.assertEqual([event["message"] for event in report["events"]],
                         ["could not start", "1 of 28 gave no usable answer"])

    def test_the_command_line(self) -> None:
        add_engine_game(self.con, "recent02", first_move_at=1_000)
        add_engine_move(self.con, "recent02", 1, path="stockfish_opening", received_at=1_001, best_move="e2e4",
                        stockfish_depth=16, allowed_seconds=5)
        code, out, _ = run_main(db.main, ["--recent"])
        self.assertEqual(code, 0)
        self.assertIn("recent02  ply   1  stockfish_opening", out)
        self.assertIn("a normal game has none", out)
        code, _, err = run_main(db.main, ["--recent", "0"])
        self.assertEqual(code, 1)
        self.assertIn("at least 1", err)


class TestCommandLine(DatabaseTestCase):
    """python db.py --init | --backup | --check."""

    def test_check_and_backup(self) -> None:
        code, out, _ = run_main(db.main, ["--check"])
        self.assertEqual(code, 0)
        self.assertIn("integrity_check: ok", out)
        self.assertIn("worker_runs", out)
        code, out, _ = run_main(db.main, ["--backup"])
        self.assertEqual(code, 0)
        self.assertIn("Backed up", out)
        self.assertEqual(len(list((self.tmp / "backup").glob("mrbits-*.sqlite"))), 1)

    def test_init_creates_a_missing_database(self) -> None:
        fresh = self.tmp / "fresh" / "mrbits.sqlite"
        with mock.patch.object(db, "DB_PATH", fresh):
            code, out, _ = run_main(db.main, ["--init"])
            self.assertEqual(code, 0)
            self.assertIn("Created", out)
            con = db.connect()
            self.addCleanup(con.close)
            self.assertEqual(names(con, "table"), TABLES)

    def test_check_and_backup_need_the_database(self) -> None:
        with mock.patch.object(db, "DB_PATH", self.tmp / "missing.sqlite"):
            for action in ("--check", "--backup"):
                code, _, err = run_main(db.main, [action])
                self.assertEqual(code, 1)
                self.assertIn("--init", err)
        self.assertFalse((self.tmp / "missing.sqlite").exists())

    def test_exactly_one_action(self) -> None:
        for argv in ([], ["--init", "--check"]):
            with self.assertRaises(SystemExit):
                run_main(db.main, argv)


if __name__ == "__main__":
    unittest.main()
