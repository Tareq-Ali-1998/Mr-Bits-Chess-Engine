-- Mr. Bits game database: lichess-bot-master/database/mrbits.sqlite
--
-- Two writers fill it:
--   * Engine UCI.exe, during the game: engine_games, engine_moves, worker_runs, worker_depths,
--     root_candidates, events (one transaction per move, after "bestmove" is sent).
--   * database/sync_lichess.py, after the games: games, moves (results, ratings, clocks, openings).
-- Engine UCI (at every start) and "python database/db.py --init" both apply this same file, so every
-- statement can run again safely (IF NOT EXISTS, and the views are dropped and re-created), and everything
-- after the two PRAGMAs runs in ONE transaction: a second program applying it at the same moment (two games
-- starting together) waits for the first one instead of failing halfway, and a reader never sees a view that
-- is dropped and not re-created yet.
-- After adding an index here, run "python database/db.py --init" once, between games, on a database that
-- already holds many games: the index is built there, and not at the next engine start (~10 s at 3,000 games).

PRAGMA journal_mode = WAL;     -- stored in the file: readers (the dashboard) never block the engine
PRAGMA foreign_keys = ON;      -- per connection only: every program turns it on again when it connects

BEGIN IMMEDIATE;

-- ############################################################################
-- From lichess (sync_lichess.py)
-- ############################################################################

CREATE TABLE IF NOT EXISTS games (
  game_id              TEXT PRIMARY KEY,   -- lichess 8-char id, e.g. 'tN252leL'
  created_at           INTEGER NOT NULL,   -- unix ms (lichess createdAt)
  last_move_at         INTEGER,            -- unix ms
  rated                INTEGER NOT NULL CHECK (rated IN (0, 1)),
  variant              TEXT,               -- standard / fromPosition / ...
  source               TEXT,               -- friend / lobby / pool / arena / ...
  initial_fen          TEXT,               -- NULL = the standard start position
  speed                TEXT,               -- bullet / blitz / rapid / classical / correspondence
  clock_initial_s      INTEGER,            -- NULL for correspondence
  clock_increment_s    INTEGER,
  our_color            TEXT NOT NULL CHECK (our_color IN ('white', 'black')),
  opponent_id          TEXT,               -- lowercase lichess id (stable: display names can change case)
  opponent_name        TEXT,
  opponent_title       TEXT,               -- 'BOT', 'GM', ... or NULL (untitled)
  our_rating           INTEGER,            -- before the game
  our_rating_diff      INTEGER,            -- NULL for casual games (lichess omits ratingDiff)
  opponent_rating      INTEGER,
  opponent_rating_diff INTEGER,
  our_accuracy         INTEGER,            -- only when lichess analysed the game
  opponent_accuracy    INTEGER,
  result               TEXT CHECK (result IN ('win', 'loss', 'draw', 'aborted')),
  status               TEXT,               -- lichess status: mate, resign, outoftime, timeout, stalemate, draw, ...
  opening_eco          TEXT,
  opening_name         TEXT,
  plies                INTEGER,
  pgn                  TEXT,
  synced_at            INTEGER             -- unix ms of the last sync that wrote this row
);

CREATE TABLE IF NOT EXISTS moves (         -- every ply of both sides
  game_id   TEXT NOT NULL REFERENCES games(game_id) ON DELETE CASCADE,
  ply       INTEGER NOT NULL,              -- 1 = the game's first move (White's, from the normal start)
  by_us     INTEGER NOT NULL CHECK (by_us IN (0, 1)),
  uci       TEXT NOT NULL,                 -- converted from lichess's SAN with python-chess
  san       TEXT,
  clock_cs  INTEGER,                       -- the mover's clock after the move, centiseconds
  think_ms  INTEGER,                       -- time lichess charged for this ply; NULL for plies 1-2
  PRIMARY KEY (game_id, ply)
);

-- ############################################################################
-- From the engine (Engine UCI.exe)
-- ############################################################################

CREATE TABLE IF NOT EXISTS engine_games (  -- one row per game the engine played (GameId from lichess-bot)
  game_id          TEXT PRIMARY KEY,
  our_color        TEXT CHECK (our_color IN ('white', 'black')),
  opponent_title   TEXT,                   -- from UCI_Opponent, at the game start ('BOT', 'GM', ... or NULL)
  opponent_rating  INTEGER,
  opponent_is_bot  INTEGER CHECK (opponent_is_bot IN (0, 1)),
  opponent_name    TEXT,
  first_move_at    INTEGER NOT NULL,       -- unix ms of the engine's first "go" in this game
  last_move_at     INTEGER,                -- unix ms of its last one
  engine_version   TEXT                    -- the build that played (MRBITS_BUILD_STAMP)
);

CREATE TABLE IF NOT EXISTS engine_moves (  -- one row per move Mr. Bits decided
  game_id          TEXT NOT NULL,          -- no foreign key to games: the sync usually comes later
  ply              INTEGER NOT NULL,       -- the ply being played: moves before it + 1
  received_at      INTEGER NOT NULL,       -- unix ms when "go" arrived
  wtime_ms         INTEGER,                -- the "go" parameters exactly as sent (NULL = not sent)
  btime_ms         INTEGER,
  winc_ms          INTEGER,
  binc_ms          INTEGER,
  movetime_ms      INTEGER,                -- lichess-bot's first move of each side: "go movetime 10000"
  allowed_seconds  INTEGER,                -- the time ladder's answer
  path             TEXT NOT NULL CHECK (path IN ('kernel', 'stockfish_opening', 'stockfish_endgame',
                                                 'stalemate_override', 'only_move', 'no_kernel_answer',
                                                 'no_legal_move')),
  legal_moves      INTEGER,
  workers          INTEGER,                -- Kernel workers asked (0 when Stockfish decided)
  best_move        TEXT,
  best_score       INTEGER,                -- the Kernel's score, from Mr. Bits' point of view (NULL otherwise)
  stockfish_depth  INTEGER,                -- the depth, when Stockfish chose the move
  t_legal_ms       REAL,                   -- Stockfish's legal moves
  t_kernel_ms      REAL,                   -- all the Kernel workers, one round trip
  t_tie_check_ms   REAL,                   -- the stalemate check after the Kernel's move
  t_total_ms       REAL,                   -- "go" received -> "bestmove" sent
  engine_version   TEXT,
  PRIMARY KEY (game_id, ply)
);

CREATE TABLE IF NOT EXISTS worker_runs (   -- one row per Kernel worker per engine move
  game_id                TEXT NOT NULL,
  ply                    INTEGER NOT NULL,
  worker                 INTEGER NOT NULL, -- 1..N
  root_moves             TEXT,             -- JSON array of the moves this worker searched, e.g. ["f1e1","h2h3"]
  status                 TEXT NOT NULL CHECK (status IN ('ok', 'timeout', 'dead', 'error', 'no_moves',
                                                         'no_completed_depth', 'rejected')),
  depth                  INTEGER,          -- the last completed depth
  best_move              TEXT,
  best_score             INTEGER,
  setup_ms               REAL,             -- replaying the game
  search_ms              REAL,
  nodes                  INTEGER,          -- the last completed depth's main search
  leaf_nodes             INTEGER,
  pruned                 INTEGER,
  total_nodes            INTEGER,          -- every iteration, an aborted last one included
  unsearched_root_moves  TEXT,             -- JSON array: from depth 6 on only the 4 best root moves are searched
  error                  TEXT,             -- the reason, when status isn't 'ok'
  PRIMARY KEY (game_id, ply, worker),
  FOREIGN KEY (game_id, ply) REFERENCES engine_moves(game_id, ply) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS worker_depths ( -- how each worker's opinion changed, depth by depth
  game_id     TEXT NOT NULL,
  ply         INTEGER NOT NULL,
  worker      INTEGER NOT NULL,
  depth       INTEGER NOT NULL,
  completed   INTEGER NOT NULL CHECK (completed IN (0, 1)),   -- 0 = cut by the clock
  ms          REAL,
  nodes       INTEGER,
  leaf_nodes  INTEGER,
  pruned      INTEGER,
  best_move   TEXT,                        -- NULL when the depth didn't complete
  score       INTEGER,
  PRIMARY KEY (game_id, ply, worker, depth),
  FOREIGN KEY (game_id, ply, worker) REFERENCES worker_runs(game_id, ply, worker) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS root_candidates (  -- "what else was considered": every searched root move's score
  game_id  TEXT NOT NULL,
  ply      INTEGER NOT NULL,
  worker   INTEGER NOT NULL,
  move     TEXT NOT NULL,
  score    INTEGER,
  exact    INTEGER CHECK (exact IN (0, 1)),   -- 0 = an upper bound ("at most this"), alpha-beta at the root
  depth    INTEGER,                           -- the worker's last completed depth
  PRIMARY KEY (game_id, ply, worker, move),
  FOREIGN KEY (game_id, ply) REFERENCES engine_moves(game_id, ply) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS events (        -- timeouts, dead workers, restarts, fallbacks
  event_id  INTEGER PRIMARY KEY AUTOINCREMENT,
  at        INTEGER NOT NULL,              -- unix ms
  game_id   TEXT,
  ply       INTEGER,
  level     TEXT NOT NULL CHECK (level IN ('info', 'warning', 'error')),
  source    TEXT NOT NULL,                 -- 'kernel workers', 'stockfish', 'engine'
  message   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS position_analysis (  -- optional: Stockfish's verdict on the position AFTER ply N
  game_id       TEXT NOT NULL,
  ply           INTEGER NOT NULL,          -- 0 = the initial position
  sf_depth      INTEGER,
  sf_cp         INTEGER,                   -- from White's point of view, like lichess's analysis
  sf_mate       INTEGER,
  sf_best_move  TEXT,
  PRIMARY KEY (game_id, ply)
);

CREATE TABLE IF NOT EXISTS sync_state (    -- where each importer stopped
  source      TEXT PRIMARY KEY,
  cursor      TEXT,
  updated_at  INTEGER
);

-- ############################################################################
-- Indexes: the dashboard's filters
-- ############################################################################

CREATE INDEX IF NOT EXISTS idx_games_created      ON games(created_at);
CREATE INDEX IF NOT EXISTS idx_games_filters      ON games(result, speed, our_color);
CREATE INDEX IF NOT EXISTS idx_games_status       ON games(status);
CREATE INDEX IF NOT EXISTS idx_games_opponent     ON games(opponent_id);
CREATE INDEX IF NOT EXISTS idx_games_rating_diff  ON games(our_rating_diff);
CREATE INDEX IF NOT EXISTS idx_engine_games_first ON engine_games(first_move_at);
CREATE INDEX IF NOT EXISTS idx_engine_moves_path  ON engine_moves(path);
CREATE INDEX IF NOT EXISTS idx_engine_moves_time  ON engine_moves(received_at);
CREATE INDEX IF NOT EXISTS idx_worker_runs_status ON worker_runs(status);
CREATE INDEX IF NOT EXISTS idx_events_game        ON events(game_id, ply);
CREATE INDEX IF NOT EXISTS idx_events_at          ON events(at);
-- v_games reads every game's engine figures through these three, one game at a time (never a scan).
CREATE INDEX IF NOT EXISTS idx_worker_runs_game_depth  ON worker_runs(game_id, depth);
CREATE INDEX IF NOT EXISTS idx_worker_runs_game_status ON worker_runs(game_id, status);
CREATE INDEX IF NOT EXISTS idx_engine_moves_game_path  ON engine_moves(game_id, path);

-- ############################################################################
-- Views: ready-made answers for the dashboard (they hold no data, so they're re-created every time)
-- ############################################################################

-- One row per game: lichess's data when the sync has run, the engine's own data always.
-- Every engine figure is a subquery on this one game, through the (game_id, ...) indexes, so reading one game,
-- or one page of games, never scans engine_moves or worker_runs (1,000 games: 0.1 ms for one game, 20-40 ms
-- for a page). A game without engine moves gets NULL counts, 0 flags and 0 timeouts / failures.
DROP VIEW IF EXISTS v_games;
CREATE VIEW v_games AS
WITH all_games AS (
  SELECT game_id FROM games
  UNION
  SELECT game_id FROM engine_games
)
SELECT a.game_id,
       COALESCE(g.created_at, e.first_move_at)                                   AS started_at,
       date(COALESCE(g.created_at, e.first_move_at) / 1000, 'unixepoch', 'localtime') AS local_date,
       COALESCE(g.our_color, e.our_color)                                        AS our_color,
       g.result,
       g.status,
       (g.status = 'outoftime' AND g.result = 'loss')                            AS lost_on_time,
       g.rated,
       g.speed,
       CASE WHEN g.game_id IS NULL THEN NULL
            WHEN g.clock_initial_s IS NULL THEN 'corr'
            ELSE printf('%g+%d', g.clock_initial_s / 60.0, g.clock_increment_s) END AS time_control,
       COALESCE(g.opponent_name, e.opponent_name)                                AS opponent_name,
       COALESCE(g.opponent_title, e.opponent_title)                              AS opponent_title,
       CASE WHEN COALESCE(g.opponent_title, e.opponent_title) = 'BOT' OR e.opponent_is_bot = 1 THEN 'bot'
            WHEN g.game_id IS NULL AND e.opponent_is_bot IS NULL THEN NULL
            ELSE 'human' END                                                     AS opponent_kind,
       COALESCE(g.opponent_rating, e.opponent_rating)                            AS opponent_rating,
       g.our_rating,
       g.our_rating_diff,
       g.opponent_rating_diff,
       g.opening_eco,
       g.opening_name,
       g.plies,
       (SELECT NULLIF(COUNT(*), 0) FROM engine_moves em WHERE em.game_id = a.game_id)       AS engine_moves,
       (SELECT SUM(em.path = 'kernel') FROM engine_moves em WHERE em.game_id = a.game_id)   AS kernel_moves,
       (SELECT SUM(em.path LIKE 'stockfish%') FROM engine_moves em
         WHERE em.game_id = a.game_id)                                           AS stockfish_moves,
       EXISTS (SELECT 1 FROM engine_moves em
                WHERE em.game_id = a.game_id AND em.path = 'stalemate_override') AS had_stalemate_override,
       EXISTS (SELECT 1 FROM engine_moves em
                WHERE em.game_id = a.game_id AND em.path = 'no_kernel_answer')   AS had_no_kernel_answer,
       (SELECT AVG(em.t_total_ms) FROM engine_moves em WHERE em.game_id = a.game_id)       AS avg_move_ms,
       (SELECT MAX(em.t_total_ms) FROM engine_moves em WHERE em.game_id = a.game_id)       AS max_move_ms,
       (SELECT MAX(w.depth) FROM worker_runs w WHERE w.game_id = a.game_id)                AS max_depth,
       (SELECT COUNT(*) FROM worker_runs w
         WHERE w.game_id = a.game_id AND w.status = 'timeout')                   AS worker_timeouts,
       (SELECT COUNT(*) FROM worker_runs w
         WHERE w.game_id = a.game_id AND w.status IN ('dead', 'error'))          AS worker_failures,
       e.engine_version,
       (g.game_id IS NOT NULL)                                                   AS synced
FROM all_games a
LEFT JOIN games g          ON g.game_id = a.game_id
LEFT JOIN engine_games e   ON e.game_id = a.game_id;

-- One row per engine move, with its workers summed up and the engine's own overhead.
-- The workers are joined row by row and grouped per move, so "WHERE game_id = ?" (and "AND ply = ?") reach the
-- primary-key indexes: one game's moves are read in under a millisecond. overhead_ms is the move's time minus
-- the slowest worker's search, and NULL when no worker searched (Stockfish's moves, the only move, ...).
DROP VIEW IF EXISTS v_engine_moves;
CREATE VIEW v_engine_moves AS
SELECT em.*,
       SUM(w.status = 'ok')                                                      AS workers_ok,
       SUM(w.status <> 'ok')                                                     AS workers_failed,
       MAX(w.depth)                                                              AS max_depth,
       SUM(w.total_nodes)                                                        AS total_nodes,
       MAX(w.search_ms)                                                          AS slowest_search_ms,
       em.t_total_ms - MAX(w.search_ms)                                          AS overhead_ms
FROM engine_moves em
LEFT JOIN worker_runs w ON w.game_id = em.game_id AND w.ply = em.ply
GROUP BY em.game_id, em.ply;

-- Every ply of a game (from lichess), with the engine's side of the plies Mr. Bits played.
DROP VIEW IF EXISTS v_moves;
CREATE VIEW v_moves AS
SELECT mv.*,
       em.path,
       em.best_score,
       em.allowed_seconds,
       em.t_total_ms
FROM moves mv
LEFT JOIN engine_moves em ON em.game_id = mv.game_id AND em.ply = mv.ply;

COMMIT;
