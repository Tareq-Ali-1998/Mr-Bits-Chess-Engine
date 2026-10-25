-- Mr. Bits game database (plan 03), with every review fix applied. Create it with:  python tools/mrbits_db/db.py --init
-- NOTE: foreign_keys is per connection. Every importer and the dashboard must run
--       "PRAGMA foreign_keys = ON;" right after connecting; this line only covers the creating connection.
PRAGMA journal_mode = WAL;     -- persistent: stored in the file
PRAGMA foreign_keys = ON;

CREATE TABLE games (
  game_id              TEXT PRIMARY KEY,   -- lichess 8-char id, e.g. 'tN252leL' (never the 12-char fullId)
  created_at           INTEGER NOT NULL,   -- unix ms (lichess createdAt)
  last_move_at         INTEGER,            -- unix ms
  rated                INTEGER NOT NULL CHECK (rated IN (0,1)),
  variant              TEXT,               -- standard / fromPosition / ...
  source               TEXT,               -- friend / lobby / pool / arena / ...
  initial_fen          TEXT,               -- NULL = standard start; needed to replay SAN -> UCI
  speed                TEXT,               -- ultraBullet / bullet / blitz / rapid / classical / correspondence
  clock_initial_s      INTEGER,            -- NULL for correspondence
  clock_increment_s    INTEGER,
  our_color            TEXT NOT NULL CHECK (our_color IN ('white','black')),
  opponent_id          TEXT,               -- lowercase lichess id (stable key)
  opponent_name        TEXT,
  opponent_title       TEXT,               -- 'BOT', 'GM', ... or NULL (untitled): filter humans with IS NOT 'BOT'
  our_rating           INTEGER,            -- before the game
  our_rating_diff      INTEGER,            -- NULL for casual games (lichess omits ratingDiff)
  opponent_rating      INTEGER,
  opponent_rating_diff INTEGER,
  our_accuracy         INTEGER,            -- players.*.analysis.accuracy, only when lichess analysed the game
  opponent_accuracy    INTEGER,
  result               TEXT CHECK (result IN ('win','loss','draw','aborted')),
  status               TEXT,               -- lichess status name: mate, resign, outoftime, timeout, stalemate, draw, ...
  opening_eco          TEXT,
  opening_name         TEXT,
  plies                INTEGER,
  pgn                  TEXT,
  synced_at            INTEGER
);

CREATE TABLE moves (                       -- every ply of both sides, from lichess
  game_id   TEXT NOT NULL REFERENCES games(game_id),
  ply       INTEGER NOT NULL,              -- 1-based index in the move list (1 = White's first move from startpos)
  by_us     INTEGER NOT NULL,
  uci       TEXT NOT NULL,                 -- converted from lichess SAN with python-chess
  san       TEXT,                          -- lichess `moves` field is SAN
  clock_cs  INTEGER,                       -- mover's clock after the move (lichess `clocks`, centiseconds)
  think_ms  INTEGER,                       -- NULL for ply 1-2; see the formula in the plan
  PRIMARY KEY (game_id, ply)
);

CREATE TABLE engine_moves (                -- one row per move Mr. Bits decided (from telemetry)
  game_id         TEXT NOT NULL,           -- no FK to games: telemetry can arrive before (or without) the lichess sync
  ply             INTEGER NOT NULL,        -- moves in the `position` command + 1
  received_at     INTEGER,
  wtime_ms INTEGER, btime_ms INTEGER, winc_ms INTEGER, binc_ms INTEGER,
  movetime_ms     INTEGER,                 -- `go movetime` (lichess-bot's first move)
  allowed_s       INTEGER,
  path            TEXT,
  legal_moves     INTEGER,
  workers         INTEGER,
  best_move       TEXT,
  best_score      INTEGER,                 -- centipawns from Mr. Bits' point of view
  stockfish_depth INTEGER,                 -- needs a `stockfishDepth` field in the telemetry line
  t_legal_ms REAL, t_dispatch_ms REAL, t_search_ms REAL, t_merge_ms REAL, t_tiecheck_ms REAL, t_total_ms REAL,
  engine_version  TEXT,                    -- the build that played; filter games with EXISTS (... em.engine_version = :v)
  PRIMARY KEY (game_id, ply)
);

CREATE TABLE worker_runs (
  game_id      TEXT NOT NULL,
  ply          INTEGER NOT NULL,
  worker       INTEGER NOT NULL,
  root_moves   TEXT,
  status       TEXT,                       -- ok / timeout / crash / error
  depth        INTEGER,
  best_move    TEXT,
  best_score   INTEGER,
  setup_ms     REAL,
  search_ms    REAL,
  nodes        INTEGER,
  leaf_nodes   INTEGER,
  pruned       INTEGER,
  request_json  TEXT,
  response_json TEXT,
  PRIMARY KEY (game_id, ply, worker),
  FOREIGN KEY (game_id, ply) REFERENCES engine_moves(game_id, ply) ON DELETE CASCADE
);

CREATE TABLE worker_depths (
  game_id TEXT NOT NULL, ply INTEGER NOT NULL, worker INTEGER NOT NULL, depth INTEGER NOT NULL,
  nodes INTEGER, pruned INTEGER, ms REAL, best_move TEXT, score INTEGER,
  PRIMARY KEY (game_id, ply, worker, depth),
  FOREIGN KEY (game_id, ply, worker) REFERENCES worker_runs(game_id, ply, worker) ON DELETE CASCADE
);

CREATE TABLE root_candidates (
  game_id TEXT NOT NULL, ply INTEGER NOT NULL, worker INTEGER NOT NULL, move TEXT NOT NULL,
  score INTEGER, exact INTEGER, depth INTEGER,  -- depth = the worker's last completed depth
  PRIMARY KEY (game_id, ply, worker, move),
  FOREIGN KEY (game_id, ply) REFERENCES engine_moves(game_id, ply) ON DELETE CASCADE
);

CREATE TABLE position_analysis (           -- position AFTER ply N (ply 0 = initial position)
  game_id TEXT NOT NULL, ply INTEGER NOT NULL,
  sf_depth INTEGER, sf_cp INTEGER, sf_mate INTEGER, sf_best_move TEXT,   -- sf_cp / sf_mate from White's point of view
  PRIMARY KEY (game_id, ply)
);

CREATE TABLE events (
  event_key TEXT PRIMARY KEY,              -- '<telemetry file>:<byte offset of its line>:<n-th event in that line>'
  ts INTEGER NOT NULL, game_id TEXT, ply INTEGER,
  level TEXT, source TEXT, message TEXT
);

CREATE TABLE sync_state (
  source TEXT PRIMARY KEY, cursor TEXT, updated_at INTEGER
);

CREATE INDEX idx_games_created ON games(created_at);
CREATE INDEX idx_games_filters ON games(result, speed, our_color);
CREATE INDEX idx_games_opp     ON games(opponent_id);
CREATE INDEX idx_engine_path   ON engine_moves(path);
CREATE INDEX idx_events_game   ON events(game_id, ply);
