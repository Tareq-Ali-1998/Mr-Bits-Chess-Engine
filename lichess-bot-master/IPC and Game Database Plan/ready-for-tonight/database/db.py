"""One way in to the Mr. Bits database (plan 03). Every job and the dashboard connect through here.

    python tools/mrbits_db/db.py --init     creates data/mrbits.sqlite from schema.sql (refuses if it exists)

The path comes from this file's own folder, never from the working directory (Streamlit, Datasette or the
Task Scheduler start elsewhere, and sqlite3.connect() silently creates an empty database for a wrong path).
"""
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent                     # lichess-bot-master/tools/mrbits_db
DB_PATH = HERE.parents[1] / "data" / "mrbits.sqlite"         # lichess-bot-master/data/mrbits.sqlite
SCHEMA = HERE / "schema.sql"


def connect() -> sqlite3.Connection:
    if not DB_PATH.exists():
        raise FileNotFoundError(f"{DB_PATH} does not exist: run  python {Path(__file__).name} --init  first")
    con = sqlite3.connect(DB_PATH)
    con.execute("PRAGMA foreign_keys = ON")                 # per connection: not stored in the file
    return con


def init() -> None:
    if DB_PATH.exists():
        sys.exit(f"{DB_PATH} already exists: not touching it")
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    (DB_PATH.parent / "backup").mkdir(exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.executescript(SCHEMA.read_text(encoding="utf-8"))
    con.close()
    print(f"created {DB_PATH}")


if __name__ == "__main__":
    if sys.argv[1:] == ["--init"]:
        init()
    else:
        sys.exit(__doc__)
