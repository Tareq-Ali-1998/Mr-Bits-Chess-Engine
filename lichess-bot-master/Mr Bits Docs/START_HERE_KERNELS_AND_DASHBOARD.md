# ♟️ Start here: choose your Kernel and watch the games

## 1. Start the application and choose a version

In `lichess-bot-master`, double-click **[`Launch Server.bat`](../Launch%20Server.bat)**.

It lists **original, v1, v2, v3, v4**, and future folders named `v5`, `v6`, etc. Enter the number or folder name. Press Enter to keep the currently configured selection.

The launcher checks the source/shared-header hashes, builds the selected Kernel and Engine UCI when needed, saves `engines/kernel-selection.json`, then starts the same existing bot application. The first build can take a little time; the console shows which build is running. Later launches reuse unchanged binaries. No files, models or packages are downloaded.

**Stop the existing application before switching.** The Kernel selection is fixed for each running Engine UCI process. Restart through the BAT to apply a new choice; do not switch during an active game.

| Choice | Experiment |
|---|---|
| `original` | Existing original search policy |
| `v1` | Your Large-network ordering and aggressive top-four pruning |
| `v2` | Large near the root, Small internally; **ordering only, no candidate deletion** |
| `v3` | Similar mixed ordering; root keeps **eight quiet moves plus all captures/EP/promotions**, with all moves retained while in check |
| `v4` | **Small-only ordinary leaf evaluation**, 0% handcrafted / 100% neural; Small ordering at depth 6+, no candidate deletion |

Start with **v2** as the ordering baseline, then compare the other experiments. No version has a demonstrated strength advantage yet. Root limits apply per worker's assigned subset, not globally across the position.

Short version notes: [v2](../engines/Kernels/v2/README.md), [v3](../engines/Kernels/v3/README.md), [v4](../engines/Kernels/v4/README.md).

## 2. Open the visual database dashboard

Double-click **[`Launch Dashboard.bat`](../Launch%20Dashboard.bat)** in the same folder.

Your browser opens **[http://127.0.0.1:8765/](http://127.0.0.1:8765/)**. Keep its console running. Ctrl+C stops the local dashboard server.

You can inspect games, moves, decision paths, timings, worker depths/nodes, candidate scores, events, recorded build labels and version comparisons. Select a game, then a move for details. The page refreshes every **five seconds** while visible; pause Auto refresh when desired. Replay stays at your selected position unless you enable Follow latest.

**Live progress means newly recorded, completed moves.** In-flight search nodes, unfinished depths and individual NN calls are not streamed by the current database. The dashboard reads existing records and never starts games or modifies game data.

The local database was empty during implementation. It will show honest empty states until the bot records moves. Full two-sided replay, finished results, ratings and openings require the existing Lichess sync:

```powershell
# From lichess-bot-master, after games have finished:
python database/sync_lichess.py
```

That explicit command uses your existing configuration and contacts Lichess. The dashboard itself does neither. [Detailed dashboard guide](../database/dashboard/README.md).

## 3. Understand the measurements

New engine records identify the **configured Kernel** and available actual worker build IDs. Historical unlabeled records remain Unknown; the dashboard never assigns today's version to old games. Stockfish opening/endgame/fallback paths remain visible and do not imply neural evaluation.

Compare like clock settings, opponents, openings and worker counts. Win percentages from a handful of games are observations, not Elo or a 95% move-retention guarantee.

For developers: `Launch Server.bat --list` only lists versions. `Launch Server.bat --version v4 --prepare-only` builds/selects without starting the bot. Build only a version with `engines/Kernels/Build Version.bat v4`. Production executables were not replaced by the implementation checks; your first launcher run prepares them as needed.
