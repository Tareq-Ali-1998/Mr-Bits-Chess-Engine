# ♞ Mr. Bits · Game Observatory

A real local browser dashboard for `database/mrbits.sqlite`. It reads your existing game records; it does not start the bot, sync Lichess, modify the database, or contact any online service.

**Simplest:** double-click [`Launch Dashboard.bat`](../../Launch%20Dashboard.bat). It starts this local server and opens your browser.

Or, from **`lichess-bot-master`**, run:

```powershell
python database/dashboard/server.py --open
```

Open **http://127.0.0.1:8765/**. Keep that terminal open; **Ctrl+C** stops the server. Without `--open`, it prints the URL and leaves your browser alone. To choose another port, add `--port 8766`. Paths resolve relative to the script, so the default database is found even when launching from another directory.

There is no package installation or frontend build step. The server uses Python's standard library. **Board replay additionally uses `python-chess`**, already required by lichess-bot; use the bot's Python environment if another interpreter does not have it. Missing that optional import disables replay with a clear message; game tables and statistics still work. No JavaScript libraries, fonts or assets are fetched from a CDN.

## What you can see

- Overview: recorded games, synced versus engine-only coverage, wins/draws/losses, score percentage, recorded move count and mean engine time.
- Filters: opponent, result, speed, configured Kernel and date range. Clear returns to all records; pagination shows 50 games at a time.
- Results over time: the most recent 30 recorded dates in the filtered set. Summary cards and version totals still include the complete filtered set.
- Version comparison: recorded configured Kernel, game count, W/D/L, score, unresolved/aborted counts, mean engine move time, deepest recorded worker and game build stamps.
- Game inspector: board replay and flip, move timeline, recorded timing, worker/node/depth statistics, per-worker depth history, candidate scores/bounds, event history and available engine build stamps.
- Auto refresh: on by default, checks every five seconds while this tab is visible. Filters stay selected; refresh batches do not overlap. Turn it off beside Refresh when you want a fixed view.

**An empty database shows zeros, dashes and empty states. No sample games are injected.** Engine-only games can show their engine telemetry before synchronization; replay needs both sides' moves and the starting position. The portal does not guess missing moves or results.

The engine writes its telemetry during games. The existing `database/sync_lichess.py` adds completed game information, both sides' moves and results. Those are separate existing workflows, not background actions performed by this portal. See [the runbook](../../Mr%20Bits%20Docs/IPC%20and%20Game%20Database%20Plan/04%20-%20Runbook%20for%20Tonight.md).

## Read the version numbers honestly

New build records may contain:

```text
uci=<recorded build>;kernel=<original|v1|v2|v3|v4>;worker=<reported worker build>
```

The portal groups **only explicit `kernel=` tokens** from the versions recorded with games/moves. It accepts `original` and generic `vN` labels with a positive whole number, so future recorded variants such as `v40` automatically join the filter and comparison. A filename containing `v4` is not evidence of a recorded selection. Old timestamp-only stamps remain **Unknown**. Conflicting variants or a mixture of labeled and unlabeled move builds becomes **Mixed / incomplete**. It never applies today's selector setting to yesterday's games.

V1 uses your Large/top-four policy; V2 orders without dropping moves; V3 uses a root-only quiet-move cutoff with captures/promotions protected. V4 uses Small at the search leaves, with neural ordering from threshold 6; it adds no Large calls or neural hard pruning. A configured variant does not prove that a particular move invoked the network: `stockfish_opening`, `stockfish_endgame`, fallbacks and other paths remain distinct. Inspect the recorded per-move decision path. New controller builds preserve actual worker hello build IDs inside the recorded game/move build labels. There is no separate worker-build column; old rows without that metadata remain unknown.

**Score percentage = `(wins + draws / 2) / (wins + draws + losses) × 100`.** Aborted and unknown-result games are excluded from that denominator and shown separately. With no decided games, score is a dash, not 0%. An observed score difference is not an Elo estimate or proof a version is stronger: opponents, clock settings, openings, sample size and code/build changes can differ.

Search node counts do not separately count NN ranking evaluations. The recorded `pruned` value counts existing alpha-beta cutoffs, not neural candidates removed. Open a worker's details to compare assigned root moves with those listed as unsearched at its final completed depth; these lists reveal whether a per-worker root cap actually removed anything. Per-network inference counts/times are not recorded by the current schema.

Kernel scores have Mr. Bits' perspective and units as recorded by the engine. They are not relabeled as White-perspective Stockfish evaluations. Node totals represent recorded worker totals, not guaranteed unique tree nodes. Missing measurements stay unavailable. Dates in the explorer are displayed in Dubai time; date filters follow the existing database's `local_date` values.

## Local and read-only

The HTTP server binds **127.0.0.1 only**, defaults to port 8765, and exposes a fixed set of read endpoints/assets. It has no SQL console, arbitrary file browser, write APIs, credential handling, or external network calls. Each API request opens `mode=ro`, sets `query_only`, and reads one consistent SQLite snapshot. Missing databases produce an error instead of silently creating an empty file. SQLite may maintain normal WAL shared-memory/read sidecars; the portal performs no data/schema writes. Avoid `immutable` mode on a database the engine is updating.

**Live means newly completed, recorded moves.** The engine publishes telemetry after completing a move. Auto refresh can pick up those new rows and later synchronized results; it cannot show in-flight node counts, unfinished depths, or individual live neural inference calls that are not in this database. Open games refresh too. Replay stays on your selected ply unless you explicitly enable **Follow latest recorded move**; board orientation and filters are retained.

Use Refresh for an immediate check. Hidden tabs pause automatic requests and check again when visible. This is a local development dashboard, not an authenticated public hosting service; keep it on its default loopback binding.

An alternate existing database can be viewed explicitly:

```powershell
python database/dashboard/server.py --database "D:/Backups/mrbits.sqlite" --port 8766
```

## Verification

From `lichess-bot-master`:

```powershell
python -m unittest discover -s database/dashboard/tests -v
```

Tests create isolated temporary SQLite fixtures, verify empty/real-data behavior, version uncertainty, legal replay, filtering, read-only enforcement, API/static routes, and rejected writes/invalid paths. They do not access the real database, credentials or Lichess. The server also receives a separate read-only smoke check against the actual database during development.

The implementation files are `server.py`, `index.html`, `style.css`, `app.js`, and `favicon.svg`. Existing database schema, query modules and bot files remain separate.
