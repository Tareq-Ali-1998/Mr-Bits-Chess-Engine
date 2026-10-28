"""Local, read-only Mr. Bits game dashboard. No imports, bot launches or online calls."""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
import re
import sqlite3
import sys
from urllib.parse import parse_qs, unquote, urlsplit
import webbrowser

HERE = Path(__file__).resolve().parent
DATABASE_DIR = HERE.parent
DEFAULT_DATABASE = DATABASE_DIR / "mrbits.sqlite"
if str(DATABASE_DIR) not in sys.path:
    sys.path.insert(0, str(DATABASE_DIR))
import queries  # noqa: E402; existing read API, always given our read-only connection

try:
    import chess
    import chess.pgn
except ImportError:
    chess = None

# Kernel identity comes ONLY from explicit recorded kernel= tokens. A timestamp
# or current selector file is not evidence about the executable used in an old game.
def recorded_kernel(build):
    tokens = [part.strip().lower()[7:] for part in (build or "").split(";")
              if part.strip().lower().startswith("kernel=")]
    if len(tokens) != 1:
        return "unknown"
    value = tokens[0]
    return value if value == "original" or re.fullmatch(r"v[1-9][0-9]*", value) else "unknown"


GAMES_CTE = """
WITH recorded_builds AS (
  SELECT game_id, NULLIF(trim(engine_version), '') AS build FROM engine_games
    WHERE NULLIF(trim(engine_version), '') IS NOT NULL
  UNION ALL
  SELECT game_id, NULLIF(trim(engine_version), '') AS build FROM engine_moves
), mapped AS (
  SELECT game_id, recorded_kernel(build) AS variant FROM recorded_builds
), labels AS (
  SELECT game_id, CASE WHEN count(DISTINCT variant) > 1 THEN 'mixed'
                      ELSE max(variant) END AS kernel_variant
  FROM mapped GROUP BY game_id
), tagged AS (
  SELECT v.*, coalesce(l.kernel_variant, 'unknown') AS kernel_variant
  FROM v_games v LEFT JOIN labels l ON l.game_id = v.game_id
)
"""
STATIC_FILES = {"/": ("index.html", "text/html; charset=utf-8"),
                "/style.css": ("style.css", "text/css; charset=utf-8"),
                "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                "/favicon.svg": ("favicon.svg", "image/svg+xml")}


@contextmanager
def read_connection(path: Path):
    """One consistent snapshot per request; never silently create a database."""
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError("Game database not found. Start with the existing database/mrbits.sqlite file.")
    con = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5)
    con.row_factory = sqlite3.Row
    con.create_function("recorded_kernel", 1, recorded_kernel, deterministic=True)
    try:
        con.execute("PRAGMA query_only = ON")
        con.execute("PRAGMA busy_timeout = 5000")
        con.execute("BEGIN")
        yield con
    finally:
        con.close()


def _all(con, sql, args=()):
    return [dict(row) for row in con.execute(sql, args)]


def filters(params):
    allowed = {"result", "speed", "kernel", "opponent", "date_from", "date_to", "limit", "offset"}
    if set(params) - allowed:
        raise ValueError("Unsupported filter")
    if any(len(values) != 1 for values in params.values()):
        raise ValueError("Each filter must have one value")
    clauses, args = [], []
    for key in ("result", "speed", "kernel", "opponent", "date_from", "date_to"):
        value = params.get(key, [""])[0].strip()
        if not value:
            continue
        if len(value) > 200:
            raise ValueError("Filter is too long")
        if key == "result" and value not in ("win", "loss", "draw", "aborted", "pending"):
            raise ValueError("Unknown result")
        if key == "kernel" and value not in ("original", "unknown", "mixed") and not re.fullmatch(r"v[1-9][0-9]*", value):
            raise ValueError("Unknown Kernel variant")
        if key.startswith("date_"):
            date.fromisoformat(value)
        if key == "opponent":
            clauses.append("instr(lower(g.opponent_name), lower(?)) > 0")
        elif key == "date_from":
            clauses.append("g.local_date >= ?")
        elif key == "date_to":
            clauses.append("g.local_date <= ?")
        elif key == "result" and value == "pending":
            clauses.append("g.result IS NULL")
            continue
        else:
            clauses.append(f"g.{'kernel_variant' if key == 'kernel' else key} = ?")
        args.append(value)
    return (" WHERE " + " AND ".join(clauses) if clauses else ""), args


def _integer(params, name, default, low, high):
    value = int(params.get(name, [str(default)])[0])
    if not low <= value <= high:
        raise ValueError(f"{name} must be between {low} and {high}")
    return value


def list_games(con, params):
    where, args = filters(params)
    limit = _integer(params, "limit", 50, 1, 200)
    offset = _integer(params, "offset", 0, 0, 1_000_000)
    total = con.execute(GAMES_CTE + f"SELECT count(*) FROM tagged g{where}", args).fetchone()[0]
    rows = _all(con, GAMES_CTE + f"SELECT g.* FROM tagged g{where} "
                "ORDER BY started_at DESC, game_id DESC LIMIT ? OFFSET ?", [*args, limit, offset])
    return {"games": rows, "total": total, "limit": limit, "offset": offset}


def summary(con, params):
    where, args = filters(params)
    rows = _all(con, GAMES_CTE + f"SELECT g.* FROM tagged g{where}", args)
    outcomes = Counter(row["result"] or "pending" for row in rows)
    decided = sum(outcomes[r] for r in ("win", "draw", "loss"))
    telemetry = _all(con, GAMES_CTE +
                     "SELECT g.kernel_variant, count(*) AS engine_moves, count(em.t_total_ms) AS timed_moves, "
                     "sum(em.t_total_ms) AS total_move_ms, avg(em.t_total_ms) AS avg_move_ms "
                     "FROM tagged g JOIN engine_moves em ON em.game_id = g.game_id" + where +
                     " GROUP BY g.kernel_variant", args)
    by_variant = {r["kernel_variant"]: r for r in telemetry}
    groups, days = {}, {}
    for row in rows:
        key = row["kernel_variant"]
        group = groups.setdefault(key, {"kernel_variant": key, "games": 0, "wins": 0, "draws": 0,
                                       "losses": 0, "pending": 0, "aborted": 0, "builds": set(),
                                       "max_depth": None})
        group["games"] += 1
        group[{"win": "wins", "draw": "draws", "loss": "losses"}.get(row["result"], row["result"] or "pending")] += 1
        if row["engine_version"]:
            group["builds"].add(row["engine_version"])
        depth = row["max_depth"]
        if depth is not None:
            group["max_depth"] = max(group["max_depth"] or 0, depth)
        day = days.setdefault(row["local_date"] or "Unknown date", Counter())
        day[row["result"] or "pending"] += 1
    for key, group in groups.items():
        n = group["wins"] + group["draws"] + group["losses"]
        group["score_pct"] = 100 * (group["wins"] + group["draws"] / 2) / n if n else None
        group["decided"] = n
        group["builds"] = sorted(group["builds"])
        group.update({k: v for k, v in by_variant.get(key, {}).items() if k != "kernel_variant"})
    build_rows = _all(con, GAMES_CTE + "SELECT DISTINCT g.kernel_variant, b.build FROM tagged g "
                      "JOIN recorded_builds b ON b.game_id = g.game_id" + where +
                      (" AND " if where else " WHERE ") + "b.build IS NOT NULL", args)
    for group in groups.values():
        group["builds"] = sorted({row["build"] for row in build_rows
                                   if row["kernel_variant"] == group["kernel_variant"]})
    timed = sum(r["timed_moves"] for r in telemetry)
    return {"games": len(rows), "synced_games": sum(bool(r["synced"]) for r in rows),
            "engine_moves": sum(r["engine_moves"] for r in telemetry),
            "outcomes": {r: outcomes[r] for r in ("win", "draw", "loss", "aborted", "pending")},
            "decided": decided,
            "score_pct": 100 * (outcomes["win"] + outcomes["draw"] / 2) / decided if decided else None,
            "avg_move_ms": sum(r["total_move_ms"] or 0 for r in telemetry) / timed if timed else None,
            "versions": sorted(groups.values(), key=lambda r: r["kernel_variant"]),
            "days": [{"date": day, **{r: values[r] for r in ("win", "draw", "loss", "aborted", "pending")}}
                     for day, values in sorted(days.items())],
            "speeds": [r[0] for r in con.execute("SELECT DISTINCT speed FROM games WHERE speed IS NOT NULL ORDER BY speed")],
            "kernel_variants": [r[0] for r in con.execute(GAMES_CTE + "SELECT DISTINCT kernel_variant FROM tagged ORDER BY kernel_variant")],
            "replay_available": chess is not None,
            "version_note": "Configured Kernel comes only from recorded kernel= tokens. Unknown history stays unknown. "
                            "A configured variant does not mean every move used that Kernel or a neural network.",
            "comparison_note": "Observed results, not a controlled strength or Elo comparison. Opponents, clocks, openings "
                               "and sample sizes can differ. Score = (wins + half draws) / decided games."}


def replay(record, moves):
    if record is None:
        return {"frames": [], "message": "Board replay needs both sides' moves and the starting position. Sync this game first."}
    if chess is None:
        return {"frames": [], "message": "Install the project's python-chess dependency to enable board replay. Tables still work."}
    if record["variant"] not in (None, "standard", "fromPosition"):
        return {"frames": [], "message": "Board replay currently supports standard/from-position chess only."}
    frames = []
    try:
        board = chess.Board(record["initial_fen"]) if record["initial_fen"] else chess.Board()
        frames.append({"ply": 0, "fen": board.fen(), "move": None})
        if not moves and record["pgn"]:
            game = chess.pgn.read_game(io.StringIO(record["pgn"]))
            if game is None or game.errors:
                raise ValueError("Stored PGN could not be replayed completely")
            board = game.board()
            frames[0]["fen"] = board.fen()
            for ply, move in enumerate(game.mainline_moves(), 1):
                if ply > 2000 or move not in board.legal_moves:
                    raise ValueError("Stored PGN is incomplete or exceeds the replay limit")
                san = board.san(move)
                board.push(move)
                frames.append({"ply": ply, "fen": board.fen(), "move": san})
        else:
            for expected, move in enumerate(moves, 1):
                if expected > 2000 or move["ply"] != expected:
                    raise ValueError("Stored move history has a gap or exceeds the replay limit")
                action = board.parse_uci(move["uci"])
                san = board.san(action)
                board.push(action)
                frames.append({"ply": expected, "fen": board.fen(), "move": san})
    except (ValueError, IndexError, AttributeError):
        return {"frames": frames, "message": "Replay stops where the recorded history becomes incomplete or invalid."}
    return {"frames": frames, "message": "Recorded move history." if len(frames) > 1 else "Starting position; no move history recorded yet."}


def game_detail(con, game_id):
    overview = con.execute(GAMES_CTE + "SELECT * FROM tagged WHERE game_id = ?", (game_id,)).fetchone()
    if overview is None:
        return None
    source = con.execute("SELECT initial_fen, pgn, variant FROM games WHERE game_id = ?", (game_id,)).fetchone()
    moves = queries.game_moves(game_id, con=con)
    engine = queries.engine_moves(game_id, con=con)
    lichess_map, engine_map = {r["ply"]: r for r in moves}, {r["ply"]: r for r in engine}
    merged = [{"ply": ply, "lichess": lichess_map.get(ply), "engine": engine_map.get(ply)}
              for ply in sorted(lichess_map.keys() | engine_map.keys())]
    builds = [r[0] for r in con.execute("SELECT DISTINCT engine_version FROM engine_moves "
                                      "WHERE game_id = ? AND engine_version IS NOT NULL ORDER BY engine_version", (game_id,))]
    return {"game": dict(overview), "moves": merged, "events": queries.game_events(game_id, con=con),
            "recorded_move_builds": builds, "replay": replay(source, moves),
            "worker_build_note": "Worker IDs have no separate column; new builds preserve reported worker binary IDs in the recorded build labels."}


class DashboardServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, database):
        self.database = Path(database).resolve()
        super().__init__(address, Handler)


class Handler(BaseHTTPRequestHandler):
    server_version = "MrBitsLocal/1"

    def _send(self, body, status=200, content_type="application/json; charset=utf-8"):
        if not isinstance(body, bytes):
            body = json.dumps(body, allow_nan=False, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; "
                         "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        port = self.server.server_address[1]
        hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        if self.headers.get("Host", "") not in hosts:
            return self._send({"error": "Use this dashboard's localhost address."}, 403)
        origin = self.headers.get("Origin")
        if origin and origin not in {f"http://{host}" for host in hosts}:
            return self._send({"error": "Cross-origin requests are not supported."}, 403)
        request = urlsplit(self.path)
        if request.path in STATIC_FILES:
            name, content_type = STATIC_FILES[request.path]
            return self._send((HERE / name).read_bytes(), content_type=content_type)
        if not request.path.startswith("/api/"):
            return self._send({"error": "Not found"}, 404)
        try:
            params = parse_qs(request.query, keep_blank_values=True, max_num_fields=20)
            with read_connection(self.server.database) as con:
                if request.path == "/api/summary":
                    result = summary(con, params)
                elif request.path == "/api/games":
                    result = list_games(con, params)
                elif request.path.startswith("/api/game/"):
                    if params:
                        raise ValueError("This endpoint does not accept query parameters")
                    parts = request.path.split("/")
                    game_id = unquote(parts[3])
                    if not game_id or len(game_id) > 100 or "/" in game_id or "\\" in game_id:
                        raise ValueError("Invalid game ID")
                    if len(parts) == 4:
                        result = game_detail(con, game_id)
                    elif len(parts) == 6 and parts[4] == "move":
                        ply = int(parts[5])
                        if not 1 <= ply <= 10000:
                            raise ValueError("Invalid ply")
                        if queries.game_overview(game_id, con=con) is None:
                            result = None
                        else:
                            result = queries.move_detail(game_id, ply, con=con)
                    else:
                        return self._send({"error": "Not found"}, 404)
                    if result is None:
                        return self._send({"error": "Game not found"}, 404)
                else:
                    return self._send({"error": "Not found"}, 404)
            self._send(result)
        except (ValueError, TypeError):
            self._send({"error": "Invalid request or filter value."}, 400)
        except FileNotFoundError as error:
            self._send({"error": str(error)}, 503)
        except sqlite3.Error:
            self._send({"error": "The game database is busy or its schema is not ready. Try Refresh; "
                                     "see the dashboard README for database setup."}, 503)

    def do_POST(self):
        self._send({"error": "This dashboard only reads data; use GET."}, 405)

    do_PUT = do_DELETE = do_PATCH = do_POST

    def log_message(self, format, *args):
        # No game IDs, filters, database contents or filesystem paths in request logs.
        pass


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE, help="Existing game database")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--open", action="store_true", help="Open the local dashboard in your browser")
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    try:
        with read_connection(args.database) as con:
            con.execute("SELECT game_id FROM v_games LIMIT 1").fetchall()
        server = DashboardServer(("127.0.0.1", args.port), args.database)
    except (OSError, sqlite3.Error) as error:
        print(f"Cannot start dashboard: {error}", file=sys.stderr)
        return 1
    url = f"http://127.0.0.1:{args.port}/"
    print(f"Mr. Bits game dashboard: {url}", flush=True)
    print("Local only, database read-only. Ctrl+C stops it.", flush=True)
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
