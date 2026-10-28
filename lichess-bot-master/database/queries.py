"""
The dashboard's read API: plain functions that return lists of dicts (one dict per row).

They read the views of schema.sql (v_games, v_engine_moves, v_moves); the rating curve reads the games
table, a move's details read the per-worker tables, the event lists read the events table, and engine_health
reads the moves and workers of its last games directly. Every value from the caller reaches SQLite as a bound
parameter; the only name put into the SQL text, the ORDER BY column, must be in ORDER_BY_COLUMNS. The views
read each game's engine figures one game at a time, through indexes, so these calls stay fast as the games
pile up (tests/test_schema.py checks that no statement here ever scans engine_moves or worker_runs).

Every function takes an optional `con=`: pass one connection (from db.connect()) to reuse it; without it the
function opens and closes its own, which also works from any thread (a sqlite3 connection belongs to the
thread that opened it).

The traps the filters avoid (see plan 03, section 7):
  * opponent_kind is v_games.opponent_kind: untitled humans have a NULL title, so `title <> 'BOT'` would
    drop them all;
  * lost_on_time means status 'outoftime' AND result 'loss': an outoftime game can be a draw;
  * date_from / date_to are LOCAL dates (v_games.local_date), both included;
  * rating_diff_min / max only match rated games (lichess sends no rating change for casual games);
  * games the sync hasn't fetched yet (synced = 0) have no result, speed or rating change, so a filter on
    those leaves them out; synced=False lists them;
  * a game Engine UCI played without a GameId (by hand, a GUI, a smoke test) is stored as 'local-<unix ms>'
    and is never synced: local=False leaves those out, local=True lists only them;
  * numbers given as text (what a web form returns) are converted ('1500' -> 1500: SQLite would compare the
    text as text, above every number, and a minimum would match no game), and True / False filters refuse
    text (bool('false') is True).
"""
from __future__ import annotations

import json
import math
import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import date, datetime
from typing import Any, Optional, Union

try:
    from . import db  # imported as part of the "database" package
except ImportError:
    import db  # run from the database folder, or with it on sys.path

Row = dict[str, Any]
Choice = Union[str, Sequence[str], None]  # one value, or any of several (an empty list means "no filter")
DateLike = Union[str, date, None]

ORDER_BY_COLUMNS = frozenset({
    "game_id", "started_at", "local_date", "our_color", "result", "status", "lost_on_time", "rated", "speed",
    "time_control", "opponent_name", "opponent_title", "opponent_kind", "opponent_rating", "our_rating",
    "our_rating_diff", "opponent_rating_diff", "opening_eco", "opening_name", "plies", "engine_moves",
    "kernel_moves", "stockfish_moves", "had_stalemate_override", "had_no_kernel_answer", "avg_move_ms",
    "max_move_ms", "max_depth", "worker_timeouts", "worker_failures", "engine_version", "synced",
})  # every column of v_games


# ############################################################################
# Games list
# ############################################################################

def list_games(*, order_by: str = "started_at", descending: bool = True, limit: Optional[int] = 100,
               offset: int = 0, con: Optional[sqlite3.Connection] = None, **filters: Any) -> list[Row]:
    """
    One page of v_games rows, with the dashboard's filters.

    Filters (all optional, combined with AND; see _games_where for the details):
        result, speed, time_control, our_color, opponent_kind, status, opening_eco, engine_version: a value or
            a list
        rated, lost_on_time, had_stalemate_override, had_no_kernel_answer, had_timeouts, had_worker_failures,
            synced, local: True / False
        opponent, opening: part of the opponent's name / of the opening's name, any case
        opponent_rating_min / _max, rating_diff_min / _max: numbers, both ends included
        date_from / date_to: local dates 'YYYY-MM-DD', both included

    :param order_by: A v_games column (ORDER_BY_COLUMNS); games without a value come last.
    :param descending: Newest / biggest first.
    :param limit: Rows per page (None = all).
    :param offset: Rows to skip (page number * limit).
    :return: The v_games rows as dicts.
    """
    if order_by not in ORDER_BY_COLUMNS:
        raise ValueError(f"order_by must be one of the v_games columns, not {order_by!r}")
    if (limit is not None and limit < 0) or offset < 0:
        raise ValueError("limit and offset can't be negative")
    where, params = _games_where(**filters)
    direction = "DESC" if descending else "ASC"
    sql = (f"SELECT * FROM v_games{where} "
           f"ORDER BY {order_by} IS NULL, {order_by} {direction}, game_id {direction} LIMIT ? OFFSET ?")
    with _connection(con) as c:
        return _fetch_all(c, sql, [*params, -1 if limit is None else limit, offset])


def count_games(*, con: Optional[sqlite3.Connection] = None, **filters: Any) -> int:
    """The number of games list_games would return without limit and offset (same filters), for paging."""
    where, params = _games_where(**filters)
    with _connection(con) as c:
        return c.execute(f"SELECT COUNT(*) FROM v_games{where}", params).fetchone()[0]


CHOICE_FILTERS = ("result", "speed", "time_control", "our_color", "opponent_kind", "status", "opening_eco",
                  "engine_version")


def filter_choices(*, con: Optional[sqlite3.Connection] = None) -> dict[str, Any]:
    """
    What the filters can be set to, for the dashboard's drop-down lists and date pickers.

    :return: {"result": [...], "speed": [...], ... (every CHOICE_FILTERS column: the values present, sorted),
              "first_date": 'YYYY-MM-DD' or None, "last_date": ...}
    """
    with _connection(con) as c:
        rows = _fetch_all(c, f"SELECT local_date, {', '.join(CHOICE_FILTERS)} FROM v_games")
    choices: dict[str, Any] = {column: sorted({row[column] for row in rows} - {None}) for column in CHOICE_FILTERS}
    dates = [row["local_date"] for row in rows]
    choices["first_date"] = min(dates, default=None)
    choices["last_date"] = max(dates, default=None)
    return choices


def _games_where(*, result: Choice = None, speed: Choice = None, time_control: Choice = None,
                 our_color: Choice = None, rated: Optional[bool] = None, opponent_kind: Choice = None,
                 opponent: Optional[str] = None, opponent_rating_min: Optional[int] = None,
                 opponent_rating_max: Optional[int] = None, rating_diff_min: Optional[int] = None,
                 rating_diff_max: Optional[int] = None, status: Choice = None, lost_on_time: Optional[bool] = None,
                 date_from: DateLike = None, date_to: DateLike = None, opening: Optional[str] = None,
                 opening_eco: Choice = None, had_stalemate_override: Optional[bool] = None,
                 had_no_kernel_answer: Optional[bool] = None, had_timeouts: Optional[bool] = None,
                 had_worker_failures: Optional[bool] = None, engine_version: Choice = None,
                 synced: Optional[bool] = None, local: Optional[bool] = None) -> tuple[str, list[Any]]:
    """
    The WHERE clause of list_games / count_games and its parameters. None means "don't filter on this".

    :param result: 'win', 'loss', 'draw', 'aborted'.
    :param speed: 'bullet', 'blitz', 'rapid', 'classical', 'correspondence'.
    :param time_control: The v_games label: '3+2', '1+0', '0.5+0', 'corr'.
    :param our_color: 'white' or 'black'.
    :param rated: True = rated games, False = casual games.
    :param opponent_kind: 'bot' or 'human'.
    :param opponent: Part of the opponent's name, any case ('_' is just a character, not a wildcard).
    :param opponent_rating_min: The opponent's rating at least this (a number, or text such as '1500').
    :param opponent_rating_max: The opponent's rating at most this.
    :param rating_diff_min: Our rating change at least this (rated games only).
    :param rating_diff_max: Our rating change at most this (rated games only).
    :param status: lichess status: 'mate', 'resign', 'outoftime', 'timeout', 'draw', 'stalemate', ...
    :param lost_on_time: True = lost on time (status 'outoftime' AND result 'loss'), False = synced and not.
    :param date_from: First local date, 'YYYY-MM-DD' (or a datetime.date), included.
    :param date_to: Last local date, included.
    :param opening: Part of the opening's name, any case ('Sicilian', 'italian game').
    :param opening_eco: The ECO code: 'C50', or a list of codes.
    :param had_stalemate_override: True = the engine overrode a stalemating move in the game.
    :param had_no_kernel_answer: True = at least one move had no usable Kernel answer (Stockfish played it).
    :param had_timeouts: True = at least one Kernel worker timed out in the game.
    :param had_worker_failures: True = at least one Kernel worker died or failed ('dead' / 'error').
    :param engine_version: The build that played (engine_games.engine_version).
    :param synced: True = the lichess sync has the game, False = only the engine's data so far.
    :param local: True = only the games Engine UCI played without a GameId ('local-...': never on lichess, so
                  never synced), False = leave them out (what the dashboard wants by default).
    :return: (" WHERE ..." or "", parameters).
    """
    where = _Where()
    where.one_of("result", result)
    where.one_of("speed", speed)
    where.one_of("time_control", time_control)
    where.one_of("our_color", our_color)
    where.one_of("opponent_kind", opponent_kind)
    where.one_of("status", status)
    where.one_of("opening_eco", opening_eco)
    where.one_of("engine_version", engine_version)
    where.flag("rated", rated)
    where.flag("lost_on_time", lost_on_time)
    where.flag("had_stalemate_override", had_stalemate_override)
    where.flag("had_no_kernel_answer", had_no_kernel_answer)
    where.flag("synced", synced)
    where.at_least_one("worker_timeouts", "had_timeouts", had_timeouts)
    where.at_least_one("worker_failures", "had_worker_failures", had_worker_failures)
    if local is not None:  # (lichess ids are 8 letters or digits: never a '-')
        where.add("game_id LIKE 'local-%'" if _bool("local", local) else "game_id NOT LIKE 'local-%'")
    if opponent:
        where.add("instr(lower(opponent_name), lower(?)) > 0", opponent)
    if opening:
        where.add("instr(lower(opening_name), lower(?)) > 0", opening)
    where.at_least("opponent_rating", _number("opponent_rating_min", opponent_rating_min))
    where.at_most("opponent_rating", _number("opponent_rating_max", opponent_rating_max))
    if rating_diff_min is not None or rating_diff_max is not None:
        where.add("rated = 1")
        where.at_least("our_rating_diff", _number("rating_diff_min", rating_diff_min))
        where.at_most("our_rating_diff", _number("rating_diff_max", rating_diff_max))
    where.at_least("local_date", _iso_date(date_from))
    where.at_most("local_date", _iso_date(date_to))
    return where.sql(), where.params


class _Where:
    """Collects the conditions of a WHERE clause and their bound parameters."""

    def __init__(self) -> None:
        """Start with no condition."""
        self.conditions: list[str] = []
        self.params: list[Any] = []

    def add(self, condition: str, *params: Any) -> None:
        """Add a condition with its parameters."""
        self.conditions.append(condition)
        self.params.extend(params)

    def one_of(self, column: str, value: Choice) -> None:
        """`column` equals the value, or one of the values of a list."""
        if value is None:
            return
        values = list(value) if isinstance(value, (list, tuple, set, frozenset)) else [value]
        if values:
            self.add(f"{column} IN ({', '.join('?' * len(values))})", *values)

    def flag(self, column: str, value: Optional[bool]) -> None:
        """A 0/1 column is 1 (True) or 0 (False)."""
        if value is not None:
            self.add(f"{column} = ?", int(_bool(column, value)))

    def at_least_one(self, column: str, name: str, value: Optional[bool]) -> None:
        """A count column is above 0 (True) or 0 (False); `name` is the filter's name, for the error."""
        if value is not None:
            self.add(f"{column} > 0" if _bool(name, value) else f"{column} = 0")

    def at_least(self, column: str, value: Any) -> None:
        """`column` >= value."""
        if value is not None:
            self.add(f"{column} >= ?", value)

    def at_most(self, column: str, value: Any) -> None:
        """`column` <= value."""
        if value is not None:
            self.add(f"{column} <= ?", value)

    def sql(self) -> str:
        """The WHERE clause ("" when there's no condition)."""
        return f" WHERE {' AND '.join(self.conditions)}" if self.conditions else ""


# ############################################################################
# One game
# ############################################################################

def game_overview(game_id: str, *, con: Optional[sqlite3.Connection] = None) -> Optional[Row]:
    """The v_games row of one game, or None if the database doesn't know the game."""
    with _connection(con) as c:
        return _fetch_one(c, "SELECT * FROM v_games WHERE game_id = ?", [game_id])


def game_moves(game_id: str, *, con: Optional[sqlite3.Connection] = None) -> list[Row]:
    """Every ply of the game from lichess (v_moves), in order. Empty until the sync has fetched the game."""
    with _connection(con) as c:
        return _fetch_all(c, "SELECT * FROM v_moves WHERE game_id = ? ORDER BY ply", [game_id])


def engine_moves(game_id: str, *, con: Optional[sqlite3.Connection] = None) -> list[Row]:
    """
    Every move Mr. Bits decided in the game (v_engine_moves), in order.

    overhead_ms (the move's time minus its slowest worker's search) is None when no Kernel worker reported a
    search time: Stockfish's moves, only_move, no_legal_move, all workers timed out. (The view gives NULL
    there too; an older schema.sql gave the whole move, Stockfish's thinking included, hence the check here.)
    """
    with _connection(con) as c:
        moves = _fetch_all(c, "SELECT * FROM v_engine_moves WHERE game_id = ? ORDER BY ply", [game_id])
    return [_real_overhead(move) for move in moves]


def move_detail(game_id: str, ply: int, *, con: Optional[sqlite3.Connection] = None) -> dict[str, Any]:
    """
    Everything the database knows about one ply.

    :return: {
        "game_id", "ply",
        "engine_move":  the v_engine_moves row (overhead_ms as in engine_moves()), or None when Mr. Bits didn't
                        decide this ply,
        "lichess_move": the v_moves row (SAN, clock, think time), or None before the sync,
        "workers":      worker_runs rows by worker number; root_moves and unsearched_root_moves decoded from
                        JSON, plus "depths" (worker_depths, by depth) and "candidates" (its root_candidates),
        "candidates":   every worker's root_candidates together, best score first,
        "events":       the events of this ply, oldest first (game_events() has the ones without a ply) }
    """
    key = [game_id, ply]
    with _connection(con) as c:
        engine_move = _fetch_one(c, "SELECT * FROM v_engine_moves WHERE game_id = ? AND ply = ?", key)
        if engine_move is not None:
            engine_move = _real_overhead(engine_move)
        lichess_move = _fetch_one(c, "SELECT * FROM v_moves WHERE game_id = ? AND ply = ?", key)
        workers = _fetch_all(c, "SELECT * FROM worker_runs WHERE game_id = ? AND ply = ? ORDER BY worker", key)
        depths = _fetch_all(c, "SELECT * FROM worker_depths WHERE game_id = ? AND ply = ? "
                               "ORDER BY worker, depth", key)
        candidates = _fetch_all(c, "SELECT * FROM root_candidates WHERE game_id = ? AND ply = ? "
                                   "ORDER BY score IS NULL, score DESC, worker, move", key)
        events = _fetch_all(c, "SELECT * FROM events WHERE game_id = ? AND ply = ? ORDER BY at, event_id", key)
    for worker in workers:
        worker["root_moves"] = _json_list(worker["root_moves"])
        worker["unsearched_root_moves"] = _json_list(worker["unsearched_root_moves"])
        worker["depths"] = [depth for depth in depths if depth["worker"] == worker["worker"]]
        worker["candidates"] = [move for move in candidates if move["worker"] == worker["worker"]]
    return {"game_id": game_id, "ply": ply, "engine_move": engine_move, "lichess_move": lichess_move,
            "workers": workers, "candidates": candidates, "events": events}


def game_events(game_id: str, *, con: Optional[sqlite3.Connection] = None) -> list[Row]:
    """
    Every event of one game, oldest first, the ones without a ply included: Engine UCI stores its fatal ones
    ("stockfish: could not start ...", "engine: go failed ... -> exiting") with no ply, so move_detail() never
    shows them.
    """
    with _connection(con) as c:
        return _fetch_all(c, "SELECT * FROM events WHERE game_id = ? ORDER BY at, event_id", [game_id])


def recent_events(level: Choice = None, limit: Optional[int] = 100, *,
                  con: Optional[sqlite3.Connection] = None) -> list[Row]:
    """
    The newest events of every game, and those of no game (game_id None), newest first: the engine-health
    page's "timeouts and crashes" list.

    :param level: 'info', 'warning', 'error', or a list of them (None = every level).
    :param limit: How many (None = all).
    """
    if limit is not None and limit < 0:
        raise ValueError("limit can't be negative")
    where = _Where()
    where.one_of("level", level)
    with _connection(con) as c:
        return _fetch_all(c, f"SELECT * FROM events{where.sql()} ORDER BY at DESC, event_id DESC LIMIT ?",
                          [*where.params, -1 if limit is None else limit])


# ############################################################################
# Statistics for the overview page
# ############################################################################

# (wins + draws / 2) out of the decided-or-drawn games, in percent (NULL when there is none).
# "result IS 'win'" is 0 or 1 even when result is NULL (a game not synced yet), so the sums are never NULL.
_SCORE_PCT = ("ROUND(100.0 * (SUM(result IS 'win') + 0.5 * SUM(result IS 'draw')) "
              "/ NULLIF(SUM(result IN ('win', 'draw', 'loss')), 0), 1)")


def results_by_day(date_from: DateLike = None, date_to: DateLike = None, *, local: Optional[bool] = None,
                   con: Optional[sqlite3.Connection] = None) -> list[Row]:
    """
    Games per local date: wins, draws, losses, aborted, and not synced yet (no result known).

    score_pct = (wins + draws / 2) / (wins + draws + losses) * 100, None when no game was decided.

    :param local: As in list_games: False leaves out the 'local-...' games (they are never synced, so they would
                  count as "not synced" for ever), True counts only them, None counts every game.
    """
    where, params = _games_where(date_from=date_from, date_to=date_to, local=local)
    sql = ("SELECT local_date, COUNT(*) AS games, "
           "SUM(result IS 'win') AS wins, SUM(result IS 'draw') AS draws, SUM(result IS 'loss') AS losses, "
           "SUM(result IS 'aborted') AS aborted, SUM(result IS NULL) AS not_synced, "
           f"{_SCORE_PCT} AS score_pct "
           f"FROM v_games{where} GROUP BY local_date ORDER BY local_date")
    with _connection(con) as c:
        return _fetch_all(c, sql, params)


def rating_history(speed: Optional[str] = None, *, con: Optional[sqlite3.Connection] = None) -> list[Row]:
    """
    Our lichess rating game by game (rated games, aborted ones left out), oldest first, from the games table.

    rating_after = our_rating + our_rating_diff (None when lichess sent no rating change).
    """
    where = _Where()
    where.add("rated = 1")
    where.add("our_rating IS NOT NULL")
    where.add("result IS NOT 'aborted'")
    where.one_of("speed", speed)
    sql = ("SELECT game_id, created_at, date(created_at / 1000, 'unixepoch', 'localtime') AS local_date, speed, "
           "our_rating, our_rating_diff, our_rating + our_rating_diff AS rating_after, result, "
           f"opponent_name, opponent_rating FROM games{where.sql()} ORDER BY created_at, game_id")
    with _connection(con) as c:
        return _fetch_all(c, sql, where.params)


def results_by_opponent_rating(bucket: int = 100, *, con: Optional[sqlite3.Connection] = None) -> list[Row]:
    """
    Results against opponents grouped by rating: rating_from .. rating_to (bucket points wide).

    Only decided or drawn synced games (win / draw / loss) whose opponent rating is known.
    """
    if not isinstance(bucket, int) or bucket <= 0:
        raise ValueError(f"bucket must be a positive whole number, not {bucket!r}")
    sql = ("SELECT CAST(opponent_rating AS INTEGER) / ? * ? AS rating_from, "
           "CAST(opponent_rating AS INTEGER) / ? * ? + ? - 1 AS rating_to, COUNT(*) AS games, "
           "SUM(result IS 'win') AS wins, SUM(result IS 'draw') AS draws, SUM(result IS 'loss') AS losses, "
           f"{_SCORE_PCT} AS score_pct "
           "FROM v_games WHERE result IN ('win', 'draw', 'loss') AND opponent_rating IS NOT NULL "
           "GROUP BY rating_from ORDER BY rating_from")
    with _connection(con) as c:
        return _fetch_all(c, sql, [bucket, bucket, bucket, bucket, bucket])


# The last N games are picked first, in ONE read of v_games, and only their moves are read for the overhead
# (SQLite can't push a game filter into the grouped v_engine_moves view: grouping that view here read every
# move of every game). per_move.overhead_ms is the move's time minus its slowest worker's search: NULL when no
# worker reported a search time, and AVG / MAX skip those. CROSS JOIN keeps the join order (the N games
# outside, their moves by primary key inside): left to itself, SQLite scans every engine move of every game.
_ENGINE_HEALTH_SQL = (
    "WITH recent AS MATERIALIZED ("
    "  SELECT game_id, started_at, local_date, engine_version, result, engine_moves, kernel_moves, avg_move_ms, "
    "         max_move_ms, worker_timeouts, worker_failures, max_depth "
    "  FROM v_games WHERE engine_moves IS NOT NULL "
    "  ORDER BY started_at DESC, game_id DESC LIMIT ?), "
    "per_move AS ("
    "  SELECT em.game_id, em.t_total_ms - (SELECT MAX(w.search_ms) FROM worker_runs w "
    "                                      WHERE w.game_id = em.game_id AND w.ply = em.ply) AS overhead_ms "
    "  FROM recent r CROSS JOIN engine_moves em ON em.game_id = r.game_id), "
    "overhead AS ("
    "  SELECT game_id, AVG(overhead_ms) AS avg_overhead_ms, MAX(overhead_ms) AS max_overhead_ms "
    "  FROM per_move GROUP BY game_id) "
    "SELECT r.game_id, r.started_at, r.local_date, r.engine_version, r.result, r.engine_moves, r.kernel_moves, "
    "       r.avg_move_ms, r.max_move_ms, o.avg_overhead_ms, o.max_overhead_ms, r.worker_timeouts, "
    "       r.worker_failures, r.max_depth "
    "FROM recent r LEFT JOIN overhead o ON o.game_id = r.game_id "
    "ORDER BY r.started_at DESC, r.game_id DESC")


def engine_health(limit_games: int = 50, *, con: Optional[sqlite3.Connection] = None) -> list[Row]:
    """
    How the engine behaved in each of the last `limit_games` games it played, newest first.

    Per game: engine moves, Kernel moves, average and slowest move (t_total_ms), average and largest overhead
    (the move's time minus its slowest worker's search, as engine_moves() gives it), Kernel worker timeouts
    and failures (dead / error), and the deepest completed depth. The overhead figures only count moves with a
    worker search time: when Stockfish decided, no worker ran, so there is no overhead to measure.
    """
    if limit_games < 0:
        raise ValueError("limit_games can't be negative")
    with _connection(con) as c:
        return _fetch_all(c, _ENGINE_HEALTH_SQL, [limit_games])


# ############################################################################
# Helpers
# ############################################################################

@contextmanager
def _connection(con: Optional[sqlite3.Connection]) -> Iterator[sqlite3.Connection]:
    """The caller's connection, or a new one that is closed afterwards."""
    if con is not None:
        yield con
        return
    own = db.connect()
    try:
        yield own
    finally:
        own.close()


def _fetch_all(con: sqlite3.Connection, sql: str, params: Sequence[Any] = ()) -> list[Row]:
    """Run a query and return its rows as dicts, whatever the connection's row_factory is."""
    cursor = con.cursor()
    cursor.row_factory = sqlite3.Row
    return [dict(row) for row in cursor.execute(sql, params)]


def _fetch_one(con: sqlite3.Connection, sql: str, params: Sequence[Any] = ()) -> Optional[Row]:
    """The first row of a query as a dict, or None."""
    rows = _fetch_all(con, sql, params)
    return rows[0] if rows else None


def _iso_date(value: DateLike) -> Optional[str]:
    """A date as 'YYYY-MM-DD' (what v_games.local_date holds); rejects anything else."""
    if value is None:
        return None
    if isinstance(value, datetime):  # (a datetime is also a date, but its isoformat() has the time)
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    try:
        return date.fromisoformat(value).isoformat()
    except (TypeError, ValueError):
        raise ValueError(f"dates must look like 'YYYY-MM-DD', not {value!r}") from None


def _bool(name: str, value: Any) -> bool:
    """A True / False filter (1 and 0 work too). Text is refused: bool('false') and bool('0') are True."""
    if value not in (True, False):
        raise ValueError(f"{name} must be True or False, not {value!r}")
    return bool(value)


def _number(name: str, value: Any) -> Union[int, float, None]:
    """
    A number filter: an int or a float as it is, text holding a number (a web form's '1500') converted.
    SQLite compares a text value with v_games.opponent_rating (an expression, without type affinity) as text,
    which sorts above every number: '1500' would silently match no game, or every game.
    """
    if value is None:
        return None
    if isinstance(value, bool):  # (True is an int to Python, but never a rating)
        raise ValueError(f"{name} must be a number, not {value!r}")
    number = value
    if not isinstance(value, (int, float)):
        try:
            number = float(value.strip() if isinstance(value, str) else value)
        except (TypeError, ValueError):
            raise ValueError(f"{name} must be a number, not {value!r}") from None
        if number.is_integer():
            number = int(number)
    if isinstance(number, float) and not math.isfinite(number):  # nan, inf
        raise ValueError(f"{name} must be a number, not {value!r}")
    return number


def _real_overhead(move: Row) -> Row:
    """A v_engine_moves row with overhead_ms None when no worker reported a search time (see engine_moves())."""
    if move["slowest_search_ms"] is None:
        move["overhead_ms"] = None
    return move


def _json_list(text: Optional[str]) -> Any:
    """A JSON array column decoded (None stays None; text that isn't JSON is returned as it is)."""
    if text is None:
        return None
    try:
        return json.loads(text)
    except ValueError:
        return text
