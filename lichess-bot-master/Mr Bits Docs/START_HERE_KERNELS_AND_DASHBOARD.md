# ♟️ Start here: choose your Kernel and watch the games

## 1. Start the application and choose a version

In `lichess-bot-master`, double-click **[`Launch Server.bat`](../Launch%20Server.bat)**.

It lists **original**, **v1.0-v1.2**, **v2.0-v2.2**, and **v3.0-v3.4** and **v3.6-v3.9**. Enter the full version name, such as **`v3.6`**, or its displayed menu number. These are family/revision labels: `v3.10` follows `v3.6`; do not treat them as decimal numbers. Press Enter to keep the current selection. The temporary **`v7`** entry has been retired; **`v3.0`** is the selected replacement for that same baseline. [Complete mapping](../engines/Kernels/VERSION_FAMILIES.md).

The launcher checks the source/shared-header hashes, builds the selected Kernel and Engine UCI when needed, checks Kernel startup, saves `engines/kernel-selection.json`, then starts the same existing bot application. The first build can take a little time; the console shows which build is running. Later launches reuse unchanged binaries. No files, models or packages are downloaded.

**The current bot keeps playing unchanged. This migration does not stop it, replace its running executable, or change its active selection. Stop the existing application before switching.** The Kernel selection is fixed for each running Engine UCI process. Restart through the BAT to apply a new choice; do not switch during an active game.

| Choice | Experiment |
|---|---|
| `original` | Existing original search policy |
| `v1.0` | Your Large-network ordering and aggressive top-four pruning |
| `v1.1` | Large near the root, Small internally; **ordering only, no candidate deletion** |
| `v1.2` | Similar mixed ordering; root keeps **eight quiet moves plus all captures/EP/promotions**, with all moves retained while in check |
| `v2.0` | **Small-only ordinary leaf evaluation**, 0% handcrafted / 100% neural; Small ordering at depth 6+, no candidate deletion |
| `v2.1` | Small ordering at depth 3+ with a time reserve; **50/50 handcrafted/Small leaves**, retain every candidate |
| `v2.2` | V2.1's foundation plus guarded late quiet move reductions; full-depth re-search when the reduced result improves the bound |
| `v3.0` | Legal search with mate/stalemate detection, bounded quiescence, Small quiet ordering, and measured-growth clock admission |
| `v3.1` | V3.0's legal/tactical search with 100% Small neural static evaluation, retaining exact terminal rules |
| `v3.2` | Same search; 0% Small / 100% handcrafted static scoring |
| `v3.3` | Same search; 80% Small / 20% handcrafted static scoring |
| `v3.4` | Same search; 20% Small / 80% handcrafted static scoring |
| `v3.6` | Large ranks every expanded list and keeps three; original static score |
| `v3.7` | The same Large top-three beam; 50/50 original/Small static score |
| `v3.8` | Small-only static value, PVS re-search and bounded exact-position value cache; all legal ordinary candidates retained |
| `v3.9` | V3.0's 50/50 score; Small ranks all candidates and keeps ten only at remaining depth 3+; no sorting at depth 2 or less or in quiescence |

Use **v1.1** as the classical-leaf ordering baseline. For the newest pair, read the [short v2.1/v2.2 guide](../engines/Kernels/V5_V6_README.md), start with **v2.1**, then compare **v2.2**. No version has a demonstrated strength advantage yet. Root limits apply per worker's assigned subset, not globally across the position.

Short version notes: [v1.1](../engines/Kernels/v1.1/README.md), [v1.2](../engines/Kernels/v1.2/README.md), [v2.0](../engines/Kernels/v2.0/README.md), [v2.1](../engines/Kernels/v2.1/README.md), [v2.2](../engines/Kernels/v2.2/README.md). V2.0/v2.1/v2.2 use only the Small weights.

For the tactical-foundation experiment, read [v3.0's three-section guide](../engines/Kernels/v3.0/README.md). V3.0 also requires only Small weights. It changes legality and leaf search, so compare it by tactical correctness and equal-time play rather than nominal depth alone.

The new [five-part V3.0 walkthrough](../engines/Kernels/v3.0/HOW_V3_0_WORKS.md) explains the exact sorting, search, and evaluation flow. [V3.1](../engines/Kernels/v3.1/README.md) keeps that foundation and switches ordinary static scores to 100% Small; choose **`v3.1`** to try it. Both require only Small weights. Read the [numerical operation guide](../engines/Neural%20Networks/OPERATION_COUNTS.md) for per-position and per-sort costs.

**The scoring controls are v3.0-v3.4:** 50/50, 100/0, 0/100, 80/20 and 20/80 respectively, with **Small first, handcrafted second**. Their legal generation, ordering, candidate retention, quiescence and time policy match v3.0; only static scoring changes. A 0% component is skipped in that evaluator. V3.2 still uses Small for the unchanged quiet-move ordering. V3.5 is intentionally unassigned because the existing pure-Small v3.1 already covers that duplicate.

For the aggressive experiments, choose **`v3.6`** ([guide](../engines/Kernels/v3.6/README.md)) or **`v3.7`** ([guide](../engines/Kernels/v3.7/README.md)). V3.6 requires Large; V3.7 requires both models. Each keeps only three candidates per expanded list, including check evasions; root selection is per worker. For a full-width alternative, choose **`v3.8`** ([guide](../engines/Kernels/v3.8/README.md)); it requires only Small and tests PVS plus exact static-value reuse. Compare time and tactical results as well as depth.

Choose **`v3.9`** for the [Small/top-ten experiment](../engines/Kernels/v3.9/README.md). It retains V3.0's legal search and 50/50 scoring, limits ordinary lists only above depth two, and uses generation order without sorting in the last two levels and quiescence. It needs only Small weights. The root limit applies to each worker's assigned list; it is not one global ten-move shortlist.

An earlier local V2.2 rebuild was blocked by Windows Application Control before startup (`WinError 4551`). The [v2.1/v2.2 guide](../engines/Kernels/V5_V6_README.md) records the earlier successes and that later policy block. Current startup must be checked with this PC's actual Windows settings.

## 2. Open the visual database dashboard

Double-click **[`Launch Dashboard.bat`](../Launch%20Dashboard.bat)** in the same folder.

Your browser opens **[http://127.0.0.1:8765/](http://127.0.0.1:8765/)**. Keep its console running. Ctrl+C stops the local dashboard server.

You can inspect games, moves, decision paths, timings, worker depths/nodes, candidate scores, events, recorded build labels and version comparisons. Select a game, then a move for details. The page refreshes every **five seconds** while visible; pause Auto refresh when desired. Replay stays at your selected position unless you enable Follow latest.

**Live progress means newly recorded, completed moves.** In-flight search nodes, unfinished depths and individual NN calls are not streamed by the current database. The dashboard reads existing records and never starts games or modifies game data.

The dashboard shows the records present in the local database and honest empty states when none match the selected filters. Full two-sided replay, finished results, ratings and openings require the existing Lichess sync:

```powershell
# From lichess-bot-master, after games have finished:
python database/sync_lichess.py
```

That explicit command uses your existing configuration and contacts Lichess. The dashboard itself does neither. [Detailed dashboard guide](../database/dashboard/README.md).

## 3. Understand the measurements

New engine records identify the **configured Kernel** and available actual worker build IDs. Historical unlabeled records remain Unknown; the dashboard never assigns today's version to old games. Stockfish opening/endgame/fallback paths remain visible and do not imply neural evaluation.

Compare like clock settings, opponents, openings and worker counts. Win percentages from a handful of games are observations, not Elo or a 95% move-retention guarantee.

For developers: family names are strings throughout selection, telemetry and the dashboard. `Launch Server.bat --list` only lists versions. `Launch Server.bat --version v2.0 --prepare-only` builds/selects without starting the bot. Build only a version with `engines/Kernels/Build Version.bat v2.0`. The old `v7` folder has been retired and selection now points to `v3.0`. The normal launcher builds matching controller/Kernel components when needed. Stop an existing application before starting a new run; selection applies to newly started engine processes.
