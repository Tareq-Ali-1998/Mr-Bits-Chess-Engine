"""
The Mr. Bits game database: lichess-bot-master/database/mrbits.sqlite.

Every Python program that uses the database connects through this module, so the file is always found
next to this script (never relative to the working directory: sqlite3.connect() would silently create an
empty database somewhere else) and every connection gets the same settings.

    python database/db.py --init        create the database, or bring an existing one up to schema.sql
    python database/db.py --backup      a safe copy in database/backup/mrbits-YYYY-MM-DD_HH-MM.sqlite
    python database/db.py --check       integrity check and the number of rows in every table
    python database/db.py --recent [N]  the newest N engine moves and events (default 12), a quick look
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Union

HERE = Path(__file__).resolve().parent
DB_PATH = HERE / "mrbits.sqlite"
SCHEMA = HERE / "schema.sql"
BUSY_TIMEOUT_MS = 5000  # wait up to 5 s when Engine UCI.exe is writing, instead of failing at once

PathLike = Union[str, Path]


def _open(path: Path) -> sqlite3.Connection:
    """Open `path` with the settings every connection needs (SQLite forgets foreign_keys per connection)."""
    con = sqlite3.connect(path)
    con.execute("PRAGMA foreign_keys = ON")
    con.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
    return con


def _database_path(path: Optional[PathLike]) -> Path:
    """The given path, or DB_PATH (read at call time, so tests can point DB_PATH at a temporary file)."""
    return Path(path) if path is not None else DB_PATH


def connect(path: Optional[PathLike] = None) -> sqlite3.Connection:
    """
    Connect to the database, which must exist already.

    :param path: The database file (default: DB_PATH, next to this script).
    :return: A connection with foreign keys on, a 5 s busy timeout, and sqlite3.Row rows (dict(row) works).
    """
    path = _database_path(path)
    if not path.exists():
        raise FileNotFoundError(f"The database {path} does not exist yet: run  python database/db.py --init")
    con = _open(path)
    con.row_factory = sqlite3.Row
    return con


def init(path: Optional[PathLike] = None) -> None:
    """
    Create the database from schema.sql, or apply schema.sql again to an existing one.

    The schema only creates what is missing and re-creates the views, so running this again is harmless
    and is also how an existing database gets new tables, indexes and views. Data is never deleted.

    :param path: The database file (default: DB_PATH).
    """
    path = _database_path(path)
    existed = path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    con = _open(path)
    try:
        con.executescript(SCHEMA.read_text(encoding="utf-8"))
        tables = _names(con, "table")
        views = _names(con, "view")
        journal_mode = con.execute("PRAGMA journal_mode").fetchone()[0]
    finally:
        con.close()
    action = "Updated" if existed else "Created"
    print(f"{action} {path} from {SCHEMA.name}: {len(tables)} tables, {len(views)} views, "
          f"journal_mode={journal_mode}" + (" (existing data kept)" if existed else ""))


def backup(destination: Optional[PathLike] = None) -> Path:
    """
    Copy the database with SQLite's online backup, never a plain file copy.

    With WAL on, the newest data can still sit in mrbits.sqlite-wal, so copying mrbits.sqlite alone can
    give an old or broken database. The backup API copies a consistent snapshot, even while Engine UCI.exe
    or the dashboard have the database open. The copy is switched to a single self-contained file.

    :param destination: Where to write the copy (default: database/backup/mrbits-YYYY-MM-DD_HH-MM.sqlite).
    :return: The path of the copy.
    """
    source = connect()
    try:
        if destination is None:
            target_path = _free_backup_path(DB_PATH.parent / "backup", datetime.now().strftime("%Y-%m-%d_%H-%M"))
        else:
            target_path = Path(destination)
            if target_path.exists():
                raise FileExistsError(f"{target_path} already exists: not overwriting it")
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target = sqlite3.connect(target_path)
        try:
            source.backup(target)
            target.execute("PRAGMA journal_mode = DELETE")
        finally:
            target.close()
    finally:
        source.close()
    print(f"Backed up {DB_PATH} to {target_path}")
    return target_path


def check(path: Optional[PathLike] = None) -> dict[str, Any]:
    """
    Check the database and count the rows of every table.

    :param path: The database file (default: DB_PATH).
    :return: {"integrity": [...] (["ok"] when fine), "foreign_key_errors": int, "journal_mode": str,
              "tables": {table: rows}}.
    """
    con = connect(path)
    try:
        integrity = [row[0] for row in con.execute("PRAGMA integrity_check")]
        foreign_key_errors = len(con.execute("PRAGMA foreign_key_check").fetchall())
        journal_mode = con.execute("PRAGMA journal_mode").fetchone()[0]
        tables = {table: con.execute(f"SELECT COUNT(*) FROM {_quoted(table)}").fetchone()[0]
                  for table in _names(con, "table")}
    finally:
        con.close()
    return {"integrity": integrity, "foreign_key_errors": foreign_key_errors, "journal_mode": journal_mode,
            "tables": tables}


def is_healthy(report: dict[str, Any]) -> bool:
    """Whether a check() report found nothing wrong."""
    return report["integrity"] == ["ok"] and report["foreign_key_errors"] == 0


def print_check(report: dict[str, Any], path: Optional[PathLike] = None) -> None:
    """Print a check() report."""
    broken_links = report["foreign_key_errors"]
    print(f"Database: {_database_path(path)}")
    print(f"integrity_check: {'; '.join(report['integrity'])}")
    print("foreign keys: ok" if broken_links == 0 else f"foreign keys: {broken_links} rows point at a missing row")
    print(f"journal_mode: {report['journal_mode']}")
    print("rows per table:")
    width = max((len(table) for table in report["tables"]), default=0)
    for table, rows in report["tables"].items():
        print(f"  {table:<{width}}  {rows}")


def recent(limit: int = 12, path: Optional[PathLike] = None) -> dict[str, list[dict[str, Any]]]:
    """
    The newest engine moves and events, for a quick look before the dashboard exists.

    :param limit: How many of each, newest first (at least 1).
    :param path: The database file (default: DB_PATH).
    :return: {"moves": [engine_moves rows], "events": [events rows]}.
    """
    if limit < 1:
        raise ValueError(f"--recent needs a number of rows of at least 1, not {limit}")
    con = connect(path)
    try:
        moves = con.execute("SELECT game_id, ply, path, best_move, best_score, allowed_seconds, workers, t_total_ms, "
                            "received_at FROM engine_moves ORDER BY received_at DESC, ply DESC LIMIT ?", (limit,))
        moves = [dict(row) for row in moves]
        events = con.execute("SELECT at, game_id, ply, level, source, message FROM events "
                             "ORDER BY event_id DESC LIMIT ?", (limit,))
        events = [dict(row) for row in events]
    finally:
        con.close()
    return {"moves": moves, "events": events}


def print_recent(report: dict[str, list[dict[str, Any]]]) -> None:
    """Print a recent() report (local times)."""
    print(f"The newest {len(report['moves'])} engine moves:")
    for move in report["moves"]:
        when = datetime.fromtimestamp(move["received_at"] / 1000).strftime("%Y-%m-%d %H:%M:%S")
        score = "" if move["best_score"] is None else f"score {move['best_score']}"
        took = "?" if move["t_total_ms"] is None else f"{move['t_total_ms']:.0f} ms"
        print(f"  {when}  {move['game_id']}  ply {move['ply']:>3}  {move['path']:<18} {move['best_move'] or '-':<6} "
              f"{score:<11} {move['workers']} workers, allowed {move['allowed_seconds']} s, took {took}")
    print(f"The newest {len(report['events'])} events (a normal game has none):")
    for event in report["events"]:
        when = datetime.fromtimestamp(event["at"] / 1000).strftime("%Y-%m-%d %H:%M:%S")
        ply = "-" if event["ply"] is None else event["ply"]
        print(f"  {when}  {event['level']:<7}  {event['game_id'] or '-'}  ply {ply}  {event['source']}: "
              f"{event['message']}")


def _names(con: sqlite3.Connection, kind: str) -> list[str]:
    """The names of the tables or views ("table" / "view"), SQLite's own tables left out."""
    rows = con.execute("SELECT name FROM sqlite_master WHERE type = ? AND name NOT LIKE 'sqlite~_%' ESCAPE '~' "
                       "ORDER BY name", (kind,))
    return [row[0] for row in rows]


def _quoted(identifier: str) -> str:
    """An SQL identifier in double quotes (table names can't be bound parameters)."""
    return '"' + identifier.replace('"', '""') + '"'


def _free_backup_path(folder: Path, stamp: str) -> Path:
    """backup/mrbits-<stamp>.sqlite, or -2, -3, ... when a backup was already made in the same minute."""
    candidate = folder / f"mrbits-{stamp}.sqlite"
    number = 2
    while candidate.exists():
        candidate = folder / f"mrbits-{stamp}-{number}.sqlite"
        number += 1
    return candidate


def main(argv: Optional[list[str]] = None) -> int:
    """The command line: --init, --backup, --check or --recent [N]. Returns the exit code."""
    parser = argparse.ArgumentParser(description="The Mr. Bits game database (database/mrbits.sqlite).")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--init", action="store_true", help="create the database, or update it to schema.sql")
    action.add_argument("--backup", action="store_true", help="copy it safely into database/backup/")
    action.add_argument("--check", action="store_true", help="integrity check and row counts")
    action.add_argument("--recent", nargs="?", type=int, const=12, metavar="N",
                        help="the newest N engine moves and events (default 12)")
    args = parser.parse_args(argv)
    try:
        if args.init:
            init()
        elif args.backup:
            backup()
        elif args.recent is not None:
            print_recent(recent(args.recent))
        else:
            report = check()
            print_check(report)
            return 0 if is_healthy(report) else 1
    except (FileNotFoundError, FileExistsError, ValueError, sqlite3.Error) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
