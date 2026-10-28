"""
Copy Mr. Bits' games from lichess into the game database: the games and moves tables.

    python database/sync_lichess.py                        the games since the last sync
    python database/sync_lichess.py --since 2026-10-27     from that local date on (the go-live day, first time)
    python database/sync_lichess.py --from-file games.ndjson [--user mr_bits]
                                                           offline: lichess NDJSON from a file (tests, re-imports)
    python database/sync_lichess.py --dry-run              fetch and check everything, write nothing

Two passes. First the bot's games since the cursor (GET /api/games/user/<name>, oldest first). Then, by id,
every game the engine played (engine_games) that still has no lichess data (POST /api/games/export/_ids),
which also repairs any gap the cursor might leave. Games still running are skipped: the next run gets them.
Every write is an upsert, so running it again is harmless; a file exported without some data (no moves, no
clocks, no accuracy, no opening, no PGN) keeps what is already stored instead of wiping it.

Run it between games: it shares the bot's token and IP address with lichess-bot, and lichess rate-limits both.
The token comes from the LICHESS_TOKEN (or lichess-bot's LICHESS_BOT_TOKEN) environment variable, else from
config.yml ("token"), and only ever goes into the Authorization header: it is never printed, logged or stored.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sqlite3
import sys
import time
from collections.abc import Iterable, Iterator
from contextlib import closing
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional, Union
from urllib.parse import quote

import chess
import chess.variant
import requests
import yaml

try:
    from . import db  # imported as part of the "database" package
except ImportError:
    import db  # run as a script from the database folder

logger = logging.getLogger(__name__)

LICHESS_URL = "https://lichess.org"
CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yml"  # lichess-bot-master/config.yml
TOKEN_ENV = "LICHESS_TOKEN"
LICHESS_BOT_TOKEN_ENV = "LICHESS_BOT_TOKEN"  # lichess-bot's own override of config.yml (lib/config.py)
USER_AGENT = "mr-bits-database-sync (lichess-bot-master/database/sync_lichess.py)"
EXPORT_FLAGS = {"pgnInJson": "true", "clocks": "true", "opening": "true", "accuracy": "true"}
IDS_PER_REQUEST = 300            # lichess's limit for /api/games/export/_ids
TIMEOUT_S = (10, 60)             # (connect, read: the longest silence while a stream is running)
RATE_LIMIT_WAIT_S = 60           # lichess: after a 429, wait a full minute
DAY_MS = 86_400_000
LICHESS_MIN_SINCE_MS = 1356998400070  # the API refuses an earlier "since"
SYNC_SOURCE = "lichess"          # its row in sync_state

LICHESS_GAME_ID = re.compile(r"[A-Za-z0-9]{8}")
RUNNING_STATUSES = {"created", "started"}       # not finished: lichess even holds back the last 3 moves
ABORTED_STATUSES = {"aborted", "noStart"}
LAST_MOVE_ENDS_GAME = {"mate", "stalemate", "variantEnd"}

GAME_COLUMNS = ("game_id", "created_at", "last_move_at", "rated", "variant", "source", "initial_fen", "speed",
                "clock_initial_s", "clock_increment_s", "our_color", "opponent_id", "opponent_name",
                "opponent_title", "our_rating", "our_rating_diff", "opponent_rating", "opponent_rating_diff",
                "our_accuracy", "opponent_accuracy", "result", "status", "opening_eco", "opening_name", "plies",
                "pgn", "synced_at")  # every column of the games table
# A re-import keeps these when its data lacks them (e.g. a file exported without accuracy, pgnInJson or moves).
KEPT_WHEN_MISSING = ("our_accuracy", "opponent_accuracy", "opening_eco", "opening_name", "plies", "pgn")


class SyncError(RuntimeError):
    """The sync can't go on: no token, lichess refused, a broken input file, ..."""


class NotOurGameError(ValueError):
    """Mr. Bits isn't one of the two players of a game."""


# ############################################################################
# Token and lichess API
# ############################################################################

def load_token(config_path: Optional[Path] = None) -> str:
    """
    The bot's lichess token. Never print or log it.

    LICHESS_TOKEN if it is set, else LICHESS_BOT_TOKEN (the variable lichess-bot itself reads), else "token" in
    lichess-bot's config.yml.

    :param config_path: lichess-bot's config.yml (default: CONFIG_PATH, next to the database folder).
    """
    for variable in (TOKEN_ENV, LICHESS_BOT_TOKEN_ENV):
        token = os.environ.get(variable, "").strip()
        if token:
            return _checked_token(token, f"the {variable} environment variable")
    path = Path(config_path) if config_path is not None else CONFIG_PATH
    try:
        with open(path, encoding="utf-8") as file:
            config = yaml.safe_load(file)
    except FileNotFoundError:
        raise SyncError(f"no token: {path} doesn't exist and {TOKEN_ENV} isn't set") from None
    except yaml.YAMLError:
        # The YAML error text quotes the broken line, which could be the token line: don't show it.
        raise SyncError(f"no token: {path} isn't valid YAML") from None
    token = config.get("token") if isinstance(config, dict) else None
    if not isinstance(token, str) or not token.strip():
        raise SyncError(f'no token: {path} has no "token" and {TOKEN_ENV} isn\'t set')
    return _checked_token(token.strip(), str(path))


def _checked_token(token: str, source: str) -> str:
    """
    The token, if an HTTP header can carry it. A line break inside it (a YAML "\\n", for example) would make
    requests raise InvalidHeader, whose message quotes the whole header, token included; a space or a non-ASCII
    character can't be in a lichess token either. The error names where the token came from, never the token.
    """
    if not all("!" <= character <= "~" for character in token):  # visible ASCII only
        raise SyncError(f"the token in {source} has a space, a line break or another character a lichess token "
                        "can't have")
    return token


def make_session(token: str) -> requests.Session:
    """A requests session that sends the token with every request (and identifies the program)."""
    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {token}", "User-Agent": USER_AGENT})
    return session


def _send(session: requests.Session, method: str, url: str, **kwargs: Any) -> requests.Response:
    """One request, always with a timeout. On HTTP 429 (too many requests) wait a minute and try once more."""
    for attempt in (1, 2):
        response = session.request(method, url, timeout=TIMEOUT_S, **kwargs)
        if response.status_code != 429:
            if response.status_code >= 400:
                response.close()
                response.raise_for_status()
            return response
        response.close()
        if attempt == 1:
            logger.warning("lichess answered 429 (too many requests): waiting %d s, then trying once more",
                           RATE_LIMIT_WAIT_S)
            time.sleep(RATE_LIMIT_WAIT_S)
    raise SyncError("lichess answered 429 (too many requests) twice: try again later")


def fetch_account(session: requests.Session) -> tuple[str, str]:
    """The bot's lichess id (lowercase) and username, from GET /api/account."""
    with _send(session, "GET", f"{LICHESS_URL}/api/account", headers={"Accept": "application/json"}) as response:
        account = response.json()
    if not isinstance(account, dict) or not account.get("id") or not account.get("username"):
        raise SyncError("lichess didn't say whose token this is (no id / username in /api/account)")
    return str(account["id"]).lower(), str(account["username"])


def export_user_games(session: requests.Session, username: str, since_ms: int) -> Iterator[dict[str, Any]]:
    """The user's finished games since `since_ms`, oldest first, streamed one by one."""
    params = {"since": str(since_ms), **EXPORT_FLAGS, "sort": "dateAsc"}
    response = _send(session, "GET", f"{LICHESS_URL}/api/games/user/{quote(username)}", params=params,
                     headers={"Accept": "application/x-ndjson"}, stream=True)
    yield from _ndjson(response)


def export_games_by_id(session: requests.Session, game_ids: list[str]) -> Iterator[dict[str, Any]]:
    """Up to IDS_PER_REQUEST games by id. Running games come too (3 moves short): the caller skips them."""
    response = _send(session, "POST", f"{LICHESS_URL}/api/games/export/_ids", params=EXPORT_FLAGS,
                     data=",".join(game_ids),
                     headers={"Accept": "application/x-ndjson", "Content-Type": "text/plain"}, stream=True)
    yield from _ndjson(response)


def _ndjson(response: requests.Response) -> Iterator[dict[str, Any]]:
    """The JSON objects of an NDJSON response, one per non-empty line."""
    with response:
        for number, line in enumerate(response.iter_lines(), start=1):
            if line.strip():
                try:
                    yield json.loads(line)
                except ValueError:
                    raise SyncError(f"lichess sent a line that isn't JSON (line {number})") from None


# ############################################################################
# lichess game JSON -> rows
# ############################################################################

def game_row(game: dict[str, Any], our_id: str, synced_at: int) -> dict[str, Any]:
    """
    The games row of one lichess game (JSON of the game export API).

    :param game: The game JSON.
    :param our_id: The bot's lichess id.
    :param synced_at: Unix ms of this sync.
    :return: {column: value} for every column in GAME_COLUMNS. Raises NotOurGameError if the bot didn't play,
             ValueError if the game has no id.
    """
    if not isinstance(game.get("id"), str) or not game["id"]:
        # SQLite would store a NULL game_id (the primary key allows it), and one NULL in games makes
        # "NOT IN (SELECT game_id FROM games)" false for every game: refuse it instead.
        raise ValueError(f"no game id: {game.get('id')!r}")
    players = game.get("players") or {}
    our_color = _our_color(players, our_id)
    us = players.get(our_color) or {}
    them = players.get("black" if our_color == "white" else "white") or {}
    opponent = them.get("user") or {}
    clock = game.get("clock") or {}
    opening = game.get("opening") or {}
    return {
        "game_id": game["id"],
        "created_at": game["createdAt"],
        "last_move_at": game.get("lastMoveAt"),
        "rated": int(bool(game.get("rated"))),
        "variant": _variant(game),
        "source": game.get("source"),
        "initial_fen": _initial_fen(game),
        "speed": game.get("speed"),
        "clock_initial_s": clock.get("initial"),
        "clock_increment_s": clock.get("increment"),
        "our_color": our_color,
        "opponent_id": opponent.get("id"),
        "opponent_name": opponent.get("name") or _ai_name(them),
        "opponent_title": opponent.get("title"),
        "our_rating": us.get("rating"),
        "our_rating_diff": us.get("ratingDiff"),  # absent in casual games
        "opponent_rating": them.get("rating"),
        "opponent_rating_diff": them.get("ratingDiff"),
        "our_accuracy": (us.get("analysis") or {}).get("accuracy"),  # only once lichess analysed the game
        "opponent_accuracy": (them.get("analysis") or {}).get("accuracy"),
        "result": game_result(game.get("status"), game.get("winner"), our_color),
        "status": game.get("status"),
        "opening_eco": opening.get("eco"),
        "opening_name": opening.get("name"),
        "plies": len(_san_moves(game)) if "moves" in game else None,  # no "moves": exported with moves=false
        "pgn": game.get("pgn"),
        "synced_at": synced_at,
    }


def game_result(status: Optional[str], winner: Optional[str], our_color: str) -> str:
    """'win' / 'loss' when there is a winner, 'aborted' for an aborted game without one, else 'draw'."""
    if winner in ("white", "black"):
        return "win" if winner == our_color else "loss"
    if status in ABORTED_STATUSES:
        return "aborted"
    return "draw"


def move_rows(game: dict[str, Any], our_color: str) -> list[tuple[Any, ...]]:
    """
    The moves rows of one game: (game_id, ply, by_us, uci, san, clock_cs, think_ms).

    lichess sends the moves as space-separated SAN; python-chess replays them from the initial position to get
    each move's UCI. by_us comes from the side to move (not from the ply number: a game from a position can
    start with Black). Raises ValueError when a move doesn't replay.
    """
    sans = _san_moves(game)
    board = _start_board(_variant(game), _initial_fen(game))
    our_side = chess.WHITE if our_color == "white" else chess.BLACK
    replayed = []
    movers = []
    for ply, san in enumerate(sans, start=1):
        try:
            move = board.parse_san(san)
        except ValueError as error:
            raise ValueError(f"ply {ply} ({san}) doesn't replay: {error}") from None
        replayed.append((board.turn == our_side, move.uci(), san))
        movers.append("white" if board.turn == chess.WHITE else "black")
        board.push(move)
    clocks = _clocks(game, len(sans))
    inc_ms = _increment_ms(game)
    if clocks is None or inc_ms is None:
        thinks: list[Optional[int]] = [None] * len(sans)
    else:
        berserked = _berserked_sides(game)
        increments = [0 if mover in berserked else inc_ms for mover in movers]
        thinks = think_times(clocks, increments, game_ended_by_last_move(game.get("status"), board))
    return [(game["id"], ply, int(by_us), uci, san, None if clocks is None else clocks[ply - 1], thinks[ply - 1])
            for ply, (by_us, uci, san) in enumerate(replayed, start=1)]


def think_times(clocks: list[int], inc_ms: Union[int, list[int]], ended_by_last_move: bool) -> list[Optional[int]]:
    """
    The time lichess charged for each ply, in ms.

    :param clocks: The mover's clock after each ply, centiseconds (clocks[i-1] belongs to ply i).
    :param inc_ms: The increment, ms: one value for every ply, or a list with one value per ply (0 for the
                   plies of a player who berserked in an arena: berserk cancels his increment).
    :param ended_by_last_move: Whether the last move itself ended the game (mate, stalemate, automatic draw).
    :return: One value per ply. Plies 1 and 2 are None: lichess starts each side's clock only after its first
             move and gives no increment for it. From ply 3 on: the mover's clock after his previous move minus
             his clock now, plus the increment; but the move that ended the game gets no increment.
    """
    plies = len(clocks)
    increments = inc_ms if isinstance(inc_ms, list) else [inc_ms] * plies
    times: list[Optional[int]] = []
    for ply in range(1, plies + 1):
        if ply <= 2:
            times.append(None)
            continue
        spent = 10 * clocks[ply - 3] - 10 * clocks[ply - 1]
        if not (ply == plies and ended_by_last_move):
            spent += increments[ply - 1]
        times.append(spent)
    return times


def game_ended_by_last_move(status: Optional[str], final_position: chess.Board) -> bool:
    """
    Whether the last move itself ended the game, so lichess gave it no increment.

    True for mate, stalemate and a variant's own ending, and for a draw that the final position makes automatic
    (insufficient material, 50 moves, fivefold repetition). False when the game went on after the last move:
    resignation, a draw agreed or claimed, a flag or a player who left.
    """
    if status in LAST_MOVE_ENDS_GAME:
        return True
    if status == "draw":
        return (final_position.is_insufficient_material() or final_position.is_fifty_moves()
                or final_position.is_fivefold_repetition())
    return False


def _our_color(players: dict[str, Any], our_id: str) -> str:
    """'white' or 'black': the side whose lichess user id is ours."""
    for color in ("white", "black"):
        user = (players.get(color) or {}).get("user") or {}
        if str(user.get("id", "")).lower() == our_id.lower():
            return color
    raise NotOurGameError(f"{our_id} isn't one of its players")


def _san_moves(game: dict[str, Any]) -> list[str]:
    """The game's moves: lichess sends them as one string of space-separated SAN."""
    return (game.get("moves") or "").split()


def _variant(game: dict[str, Any]) -> Optional[str]:
    """The variant key ('standard', 'fromPosition', ...)."""
    variant = game.get("variant")
    return variant.get("key") if isinstance(variant, dict) else variant


def _initial_fen(game: dict[str, Any]) -> Optional[str]:
    """The starting FEN, or None for the standard start position."""
    fen = game.get("initialFen")
    return None if fen in (None, "", "startpos") else fen


def _ai_name(side: dict[str, Any]) -> Optional[str]:
    """A name for lichess's own Stockfish opponent, which has a level instead of a user."""
    return f"lichess AI level {side['aiLevel']}" if "aiLevel" in side else None


def _start_board(variant: Optional[str], initial_fen: Optional[str]) -> chess.Board:
    """The position the game started from, with the rules of its variant."""
    if variant in (None, "standard", "fromPosition"):
        return chess.Board(initial_fen or chess.STARTING_FEN)
    if variant == "chess960":
        return chess.Board(initial_fen or chess.STARTING_FEN, chess960=True)
    board_class = chess.variant.find_variant(variant)  # ValueError for a variant python-chess doesn't know
    return board_class(initial_fen or board_class.starting_fen)


def _clocks(game: dict[str, Any], plies: int) -> Optional[list[int]]:
    """The mover's clock after each ply (centiseconds), or None when lichess sent none or they don't fit."""
    clocks = game.get("clocks")
    if clocks is None or plies == 0:
        return None
    if len(clocks) not in (plies, plies + 1):  # N + 1: lichess can add the flagged player's final clock
        logger.warning("Game %s: %d clock values for %d plies, so no clocks or think times are stored",
                       game.get("id"), len(clocks), plies)
        return None
    return [int(value) for value in clocks[:plies]]


def _increment_ms(game: dict[str, Any]) -> Optional[int]:
    """The clock increment in ms, or None for a game without a clock (correspondence)."""
    increment = (game.get("clock") or {}).get("increment")
    return None if increment is None else int(increment) * 1000


def _berserked_sides(game: dict[str, Any]) -> set[str]:
    """
    The sides ('white' / 'black') that berserked: in an arena, berserk halves a player's clock and cancels his
    increment. lichess only sends players.<color>.berserk in arena games.
    """
    players = game.get("players") or {}
    return {color for color in ("white", "black") if (players.get(color) or {}).get("berserk") is True}


# ############################################################################
# Database
# ############################################################################

def _upsert_game_sql() -> str:
    """INSERT ... ON CONFLICT(game_id) DO UPDATE over every column of GAME_COLUMNS (built once, at import)."""
    updates = [f"{column} = COALESCE(excluded.{column}, games.{column})" if column in KEPT_WHEN_MISSING
               else f"{column} = excluded.{column}"
               for column in GAME_COLUMNS if column != "game_id"]
    return (f"INSERT INTO games ({', '.join(GAME_COLUMNS)}) VALUES ({', '.join(':' + c for c in GAME_COLUMNS)}) "
            f"ON CONFLICT(game_id) DO UPDATE SET {', '.join(updates)}")


UPSERT_GAME_SQL = _upsert_game_sql()
INSERT_MOVE_SQL = ("INSERT INTO moves (game_id, ply, by_us, uci, san, clock_cs, think_ms) "
                   "VALUES (?, ?, ?, ?, ?, ?, ?)")


def game_exists(con: sqlite3.Connection, game_id: str) -> bool:
    """Whether the games table has this game already."""
    return con.execute("SELECT 1 FROM games WHERE game_id = ?", (game_id,)).fetchone() is not None


def store_game(con: sqlite3.Connection, row: dict[str, Any], moves: Optional[list[tuple[Any, ...]]]) -> bool:
    """
    Write one game in one transaction: its games row is inserted or updated, its moves replaced.

    :param moves: The moves rows, or None to keep the stored moves (the data had no moves: moves=false).
    :return: True if the game is new to the database.
    """
    is_new = not game_exists(con, row["game_id"])
    with con:  # commits at the end, or rolls everything back on an error
        con.execute(UPSERT_GAME_SQL, row)
        if moves is not None:
            con.execute("DELETE FROM moves WHERE game_id = ?", (row["game_id"],))
            con.executemany(INSERT_MOVE_SQL, moves)
    return is_new


def keep_stored_clocks(con: sqlite3.Connection, moves: list[tuple[Any, ...]]) -> list[tuple[Any, ...]]:
    """
    The moves rows of data exported without clocks (lichess's default is clocks=false), with the clock_cs and
    think_ms already stored for the same ply and move put back, so a re-import doesn't wipe them.
    """
    if not moves:
        return moves
    stored = {ply: (uci, clock_cs, think_ms) for ply, uci, clock_cs, think_ms in con.execute(
        "SELECT ply, uci, clock_cs, think_ms FROM moves WHERE game_id = ?", (moves[0][0],))}
    kept = []
    for game_id, ply, by_us, uci, san, clock_cs, think_ms in moves:
        old = stored.get(ply)
        if old is not None and old[0] == uci:
            clock_cs, think_ms = old[1], old[2]
        kept.append((game_id, ply, by_us, uci, san, clock_cs, think_ms))
    return kept


def update_cursor(con: sqlite3.Connection) -> Optional[int]:
    """
    Store where the next sync starts: the newest game's createdAt minus a day (the overlap is harmless, the
    writes are upserts). :return: The cursor (unix ms), or None while the games table is empty.
    """
    newest = con.execute("SELECT MAX(created_at) FROM games").fetchone()[0]
    if newest is None:
        return None
    cursor = newest - DAY_MS
    with con:
        con.execute("INSERT INTO sync_state (source, cursor, updated_at) VALUES (?, ?, ?) "
                    "ON CONFLICT(source) DO UPDATE SET cursor = excluded.cursor, updated_at = excluded.updated_at",
                    (SYNC_SOURCE, str(cursor), now_ms()))
    return cursor


def choose_since(con: sqlite3.Connection, since: Optional[date] = None) -> int:
    """
    Where the user export starts (unix ms), in this order:
      --since (local midnight of that date); the cursor of the last sync; the engine's first game minus a day;
      7 days ago.
    """
    if since is not None:
        return max(local_midnight_ms(since), LICHESS_MIN_SINCE_MS)
    row = con.execute("SELECT cursor FROM sync_state WHERE source = ?", (SYNC_SOURCE,)).fetchone()
    if row is not None and row[0]:
        return max(int(row[0]), LICHESS_MIN_SINCE_MS)
    first_game = con.execute("SELECT MIN(first_move_at) FROM engine_games").fetchone()[0]
    if first_game is not None:
        return max(first_game - DAY_MS, LICHESS_MIN_SINCE_MS)
    return local_midnight_ms(date.today() - timedelta(days=7))


def missing_engine_games(con: sqlite3.Connection) -> list[str]:
    """
    The games the engine played (engine_games) that have no lichess data yet, oldest first. Only real lichess
    ids (8 letters or digits) are kept: a local test game's id would be asked for again at every sync.
    (NOT EXISTS, not NOT IN: a single NULL game_id in games would make NOT IN false for every game.)
    """
    rows = con.execute("SELECT e.game_id FROM engine_games e "
                       "WHERE NOT EXISTS (SELECT 1 FROM games g WHERE g.game_id = e.game_id) "
                       "ORDER BY e.first_move_at, e.game_id")
    return [row[0] for row in rows if LICHESS_GAME_ID.fullmatch(str(row[0]))]


# ############################################################################
# The sync
# ############################################################################

@dataclass
class Summary:
    """What a sync did."""

    inserted: int = 0
    updated: int = 0
    moves: int = 0
    running: int = 0
    not_ours: int = 0
    errors: int = 0
    seen: set[str] = field(default_factory=set)

    def report(self, dry_run: bool = False) -> str:
        """One line for the console."""
        games = (f"{self.inserted} games to insert, {self.updated} to update, {self.moves} moves"
                 if dry_run else f"{self.inserted} games inserted, {self.updated} updated, {self.moves} moves written")
        skipped = (f"skipped: {self.running} still running, {self.not_ours} not played by the bot, "
                   f"{self.errors} with errors")
        prefix = "lichess sync (dry run, nothing written)" if dry_run else "lichess sync"
        return f"{prefix}: {games}; {skipped}"


def import_games(con: sqlite3.Connection, games: Iterable[dict[str, Any]], our_id: str, summary: Summary,
                 dry_run: bool = False) -> None:
    """
    Store each game (one transaction per game). Running games, games the bot didn't play and games that can't
    be read are skipped and counted; a problem with one game never stops the others.
    """
    for game in games:
        if not isinstance(game, dict):
            logger.warning("Skipped a line that isn't a game: %.60r", game)
            summary.errors += 1
            continue
        game_id = str(game.get("id", "?"))
        summary.seen.add(game_id)
        if game.get("status") in RUNNING_STATUSES:
            summary.running += 1
            continue
        try:
            row = game_row(game, our_id, synced_at=now_ms())
            # Data exported with moves=false has no "moves": the stored moves stay. With clocks=false (lichess's
            # default) it has no "clocks": the stored clocks and think times of the same moves stay.
            moves = move_rows(game, row["our_color"]) if "moves" in game else None
            if moves and "clocks" not in game and game.get("clock"):
                moves = keep_stored_clocks(con, moves)
        except NotOurGameError as error:
            logger.warning("Skipped game %s: %s", game_id, error)
            summary.not_ours += 1
            continue
        except (AttributeError, KeyError, TypeError, ValueError) as error:  # (AttributeError: a broken structure)
            logger.warning("Skipped game %s: %s: %s", game_id, type(error).__name__, error)
            summary.errors += 1
            continue
        try:
            is_new = not game_exists(con, game_id) if dry_run else store_game(con, row, moves)
        except sqlite3.IntegrityError as error:  # the game's transaction was rolled back
            logger.warning("Skipped game %s: the database refused it: %s", game_id, error)
            summary.errors += 1
            continue
        if is_new:
            summary.inserted += 1
        else:
            summary.updated += 1
        summary.moves += len(moves or ())


def sync_from_lichess(con: sqlite3.Connection, session: requests.Session, since_ms: int,
                      dry_run: bool = False) -> Summary:
    """
    The two passes: the bot's games since `since_ms`, then the engine's games still missing, by id.

    The cursor in sync_state moves on after each pass that went through (never in a dry run).
    """
    our_id, username = fetch_account(session)
    summary = Summary()
    print(f"Fetching {username}'s games since {datetime.fromtimestamp(since_ms / 1000):%Y-%m-%d %H:%M} "
          "(local time)")
    with closing(export_user_games(session, username, since_ms)) as games:
        import_games(con, games, our_id, summary, dry_run)
    if not dry_run:
        update_cursor(con)
    missing = [game_id for game_id in missing_engine_games(con) if game_id not in summary.seen]
    if missing:
        print(f"Fetching {len(missing)} more games the engine played, by id")
    for start in range(0, len(missing), IDS_PER_REQUEST):
        with closing(export_games_by_id(session, missing[start:start + IDS_PER_REQUEST])) as games:
            import_games(con, games, our_id, summary, dry_run)
        if not dry_run:
            update_cursor(con)
    return summary


def read_ndjson_file(path: Path) -> list[dict[str, Any]]:
    """The games of an NDJSON file (one game JSON per line, like the export API sends)."""
    games = []
    try:
        with open(path, encoding="utf-8-sig") as file:
            for number, line in enumerate(file, start=1):
                if line.strip():
                    games.append(json.loads(line))
    except FileNotFoundError:
        raise SyncError(f"{path} doesn't exist") from None
    except UnicodeDecodeError:
        raise SyncError(f"{path} isn't UTF-8 text") from None
    except ValueError as error:
        raise SyncError(f"{path} line {number} isn't JSON: {error}") from None
    return games


def infer_our_id(games: list[Any]) -> str:
    """
    The one player id found in every game of a file: the bot. Raises SyncError when that isn't clear.
    Lines that aren't a game (not a JSON object, no players, players that aren't objects) are left out here:
    import_games() skips them too and counts them.
    """
    common: Optional[set[str]] = None
    for game in games:
        ids = _player_ids(game)
        if ids is None:
            continue
        common = ids if common is None else common & ids
    if common is not None and len(common) == 1:
        return common.pop()
    raise SyncError("can't tell which player is the bot in this file: pass --user <the bot's lichess id>")


def _player_ids(game: Any) -> Optional[set[str]]:
    """The lowercase lichess ids of a game's players, or None when it has none or its structure is broken."""
    players = game.get("players") if isinstance(game, dict) else None
    if not isinstance(players, dict) or not all(isinstance(side, dict) for side in players.values()):
        return None
    users = [side.get("user") or {} for side in players.values()]
    if not all(isinstance(user, dict) for user in users):
        return None
    return ({str(user.get("id", "")).lower() for user in users} - {""}) or None


def local_midnight_ms(day: date) -> int:
    """Unix ms of 00:00 local time on `day`."""
    return int(datetime.combine(day, datetime.min.time()).timestamp() * 1000)


def now_ms() -> int:
    """Unix ms now."""
    return int(time.time() * 1000)


# ############################################################################
# Command line
# ############################################################################

def _date_argument(text: str) -> date:
    """argparse type for --since."""
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a date like 2026-10-27: {text!r}") from None


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    """The command line options."""
    parser = argparse.ArgumentParser(description="Copy Mr. Bits' lichess games into database/mrbits.sqlite.")
    parser.add_argument("--since", type=_date_argument, metavar="YYYY-MM-DD",
                        help="start at this local date (the first time: the go-live day); default: the last sync")
    parser.add_argument("--from-file", type=Path, metavar="GAMES.ndjson",
                        help="read lichess NDJSON from this file instead of the API (offline)")
    parser.add_argument("--user", metavar="LICHESS_ID",
                        help="with --from-file: the bot's lichess id (default: the player found in every game)")
    parser.add_argument("--dry-run", action="store_true", help="fetch and check everything, write nothing")
    args = parser.parse_args(argv)
    if args.user and not args.from_file:
        parser.error("--user only goes with --from-file (otherwise the token tells who the bot is)")
    if args.since and args.from_file:
        parser.error("--since only goes with the API (a file is imported whole)")
    return args


def main(argv: Optional[list[str]] = None) -> int:
    """Run the sync. Returns the exit code."""
    args = parse_args(argv)
    try:
        con = db.connect()
    except FileNotFoundError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    try:
        summary = Summary()
        if args.from_file:
            games = read_ndjson_file(args.from_file)
            if games:
                our_id = args.user.lower() if args.user else infer_our_id(games)
                import_games(con, games, our_id, summary, args.dry_run)
        else:
            with make_session(load_token()) as session:
                summary = sync_from_lichess(con, session, choose_since(con, args.since), args.dry_run)
        print(summary.report(args.dry_run))
        return 0
    except SyncError as error:
        print(f"Sync stopped: {error}", file=sys.stderr)
    except requests.exceptions.InvalidHeader:  # its message quotes the header value, "Bearer <the token>"
        print("Sync stopped: requests refused a header, so the token has a character an HTTP header can't hold",
              file=sys.stderr)
    except requests.RequestException as error:  # every other one names the URL, never the headers
        print(f"Sync stopped, lichess didn't answer properly: {error}", file=sys.stderr)
    except sqlite3.Error as error:  # e.g. the database stayed locked longer than the busy timeout
        print(f"Sync stopped by a database error: {error}", file=sys.stderr)
    finally:
        con.close()
    return 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    sys.exit(main())
