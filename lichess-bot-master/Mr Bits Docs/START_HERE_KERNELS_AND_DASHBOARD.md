# ♟️ Start here: choose your Kernel and watch the games

## 1. Start the application and choose a version

In `lichess-bot-master`, double-click **[`Launch Server.bat`](../Launch%20Server.bat)**.

It lists **original and v1–v11**, and discovers future folders named `v12`, `v13`, etc. Enter the number or folder name. Press Enter to keep the currently configured selection.

The launcher checks the source/shared-header hashes, builds the selected Kernel and Engine UCI when needed, saves `engines/kernel-selection.json`, then starts the same existing bot application. The first build can take a little time; the console shows which build is running. Later launches reuse unchanged binaries. No files, models or packages are downloaded.

**Stop the existing application before switching.** The Kernel selection is fixed for each running Engine UCI process. Restart through the BAT to apply a new choice; do not switch during an active game.

| Choice | Experiment |
|---|---|
| `original` | Existing original search policy |
| `v1` | Your Large-network ordering and aggressive top-four pruning |
| `v2` | Large near the root, Small internally; **ordering only, no candidate deletion** |
| `v3` | Similar mixed ordering; root keeps **eight quiet moves plus all captures/EP/promotions**, with all moves retained while in check |
| `v4` | **Small-only ordinary leaf evaluation**, 0% handcrafted / 100% neural; Small ordering at depth 6+, no candidate deletion |
| `v5` | Small ordering at depth 3+ with a time reserve; **50/50 handcrafted/Small leaves**, retain every candidate |
| `v6` | V5's foundation plus guarded late quiet move reductions; full-depth re-search when the reduced result improves the bound |
| `v7` | Legal search with mate/stalemate detection, bounded quiescence, Small quiet ordering, and measured-growth clock admission |
| `v8` | V7's legal/tactical search with 100% Small neural static evaluation, retaining exact terminal rules |
| `v9` | Large ranks every expanded list and keeps three; original static score |
| `v10` | The same Large top-three beam; 50/50 original/Small static score |
| `v11` | Small-only static value, PVS re-search and bounded exact-position value cache; all legal ordinary candidates retained |

Use **v2** as the classical-leaf ordering baseline. For the newest pair, read the [short v5/v6 guide](../engines/Kernels/V5_V6_README.md), start with **v5**, then compare **v6**. No version has a demonstrated strength advantage yet. Root limits apply per worker's assigned subset, not globally across the position.

Short version notes: [v2](../engines/Kernels/v2/README.md), [v3](../engines/Kernels/v3/README.md), [v4](../engines/Kernels/v4/README.md), [v5](../engines/Kernels/v5/README.md), [v6](../engines/Kernels/v6/README.md). V4/v5/v6 use only the Small weights.

For the tactical-foundation experiment, read [v7's three-section guide](../engines/Kernels/v7/README.md). V7 also requires only Small weights. It changes legality and leaf search, so compare it by tactical correctness and equal-time play rather than nominal depth alone.

The new [five-part V7 walkthrough](../engines/Kernels/v7/HOW_V7_WORKS.md) explains the exact sorting, search, and evaluation flow. [V8](../engines/Kernels/v8/README.md) keeps that foundation and switches ordinary static scores to 100% Small; choose **8 / v8** to try it. Both require only Small weights. Read the [numerical operation guide](../engines/Neural%20Networks/OPERATION_COUNTS.md) for per-position and per-sort costs.

For the aggressive experiments, choose **9 / v9** ([guide](../engines/Kernels/v9/README.md)) or **10 / v10** ([guide](../engines/Kernels/v10/README.md)). V9 requires Large; V10 requires both models. Each keeps only three candidates per expanded list, including check evasions; root selection is per worker. For a full-width alternative, choose **11 / v11** ([guide](../engines/Kernels/v11/README.md)); it requires only Small and tests PVS plus exact static-value reuse. Compare time and tactical results as well as depth.

The latest local v6 rebuild is currently blocked by Windows Application Control before startup (`WinError 4551`). V5 passed its current checks; use it first. The [v5/v6 guide](../engines/Kernels/V5_V6_README.md) separates earlier successful tests from this newer policy block.

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
