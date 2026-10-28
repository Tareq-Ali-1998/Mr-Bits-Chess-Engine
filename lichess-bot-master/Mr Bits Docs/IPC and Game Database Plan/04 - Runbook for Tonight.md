# 🌙 Tonight's Runbook — What's Done, and What's Left for You

**Written by Claude Opus 5.5, for Tareq.** 🤝 *v1, October 25: Phase 1 (one Stockfish) · **v2, October 27: the Kernel worker pool, the game database, one `ChessState` and the clean folders are in your folder, built and tested there***

<div style="background:linear-gradient(90deg,#0f766e,#1d4ed8);color:#ffffff;border-radius:14px;padding:16px 22px;margin:16px 0;">

**Tonight in one sentence:** everything is built and tested in your real folder (28 Kernel workers alive all game, every move in `database\mrbits.sqlite`, one `ChessState`, three clean folders), so what's left is **3 live games**, **a look at the database**, the **first lichess sync**, and **your commit**. ≈ 1 hour. 🚀

</div>

---

## ✅ What I did in your folder (October 27)

| What | Where | Proof |
|---|---|---|
| **The engine** | `engines\`: `Engine UCI.cpp`, `Kernel.cpp`, and the new `Chess State.hpp`, `Kernel Workers.hpp`, `Game Database.hpp`, `Engine Log.hpp`, `sqlite\`, `Build Engines.bat`, `tests\`. Both `.exe` built with `Build Engines.bat` (stamp `2026-10-27_02-36-51`) | The 3 engine tests, run from your real folder: **183/183**, **27/27**, and **0 mismatches** against your production `Kernel.exe` |
| **The database** | `database\`: `schema.sql`, `db.py`, `queries.py`, `sync_lichess.py`, `tests\` | `python -m unittest discover -s tests`: **130/130** |
| **The folders** | `Mr Bits Docs\` holds this plan now. Deleted: `input\`, `history\`, `stockfish.old\`, the two `stockfish-windows-x86-64-avx2.exe.old`, and the plan's old `tested-files\` | The Stockfish copies were byte-identical to `engines\stockfish\` and used by nothing (checked: no code reference, no process) |
| **A rollback copy of Phase 1** | `engines\backup-phase1\` (git ignores it): Phase 1's `Engine UCI.cpp`, `Engine UCI.exe`, `Stockfish Handler.hpp` | Byte-identical to what was in `engines\` before (hashes checked) |
| **Small edits** | `.gitignore` (the new folders), `extra_game_handlers.py` (its comment only) | `git status` below |

<div style="background:#fffbeb;border-left:6px solid #d97706;border-radius:10px;padding:12px 18px;margin:16px 0;color:#1e293b;">

**⚠️ Ground rules**
1. **PowerShell or `Launch Server.bat` only, never Git Bash.** Git Bash puts Git's own `libstdc++-6.dll` first on PATH, so the engines would run on a different C runtime.
2. **After every rebuild: `Build Engines.bat test`** (it builds, checks that Windows lets both `.exe` run, then plays the test games). Smart App Control still blocks some fresh builds: just run the `.bat` again.
3. **Nobody prints `config.yml`:** it holds the token. `sync_lichess.py` reads it and never prints it.

</div>

**Paste this first in every new PowerShell window:**

```powershell
$repo = "C:\Users\tareq\Desktop\Mr_Bits"
$lb   = "$repo\lichess-bot-master"
```

---

## Step 1 · Three live games (yours, 45–60 min)

Start the bot the usual way: **double-click `Launch Server.bat`**.

1. **At bot startup**, lichess-bot opens and closes the engine once to check it: Stockfish starts and stops once, and **no Kernel worker starts** (they start with each game). The database (`database\mrbits.sqlite`) already exists, empty: the first game writes its first rows.
2. **Play 3 games** (challenge the bot, or let matchmaking run). Try for one longer game (more than 80 plies, i.e. past move 41: the Stockfish endgame path).
3. **While a game runs**, in a second PowerShell (paste the 2 variables first):

```powershell
Get-Process Kernel, stockfish* -ErrorAction SilentlyContinue | Where-Object { $_.Path -like "$lb\*" } | Group-Object ProcessName | Select-Object Name, Count
#   expect: Kernel 28 and stockfish... 1, per game that's running
$log = Get-ChildItem "$lb\engines\logs\uci_*.log" | Sort-Object LastWriteTime | Select-Object -Last 1
Get-Content $log.FullName -Tail 15            # live: >> commands, << answers, "go -> bestmove took N ms (kernel, game '...')"
Select-String -Path $log.FullName -Pattern '!!'   # must stay empty
```

4. **After each game:** no `Kernel` and no `stockfish` process is left from `$lb`.

✅ **Done when** 3 games finish normally (any result 😄), with no `!!` line in their logs.

What's normal and not a reason to roll back:
- the first two moves of each side are Stockfish's (depth 14–20, well under a second);
- a Kernel move thinks up to the ladder's budget (≈ 50–66 s in a 2–3 minute game: see the README's side discoveries);
- once more than 80 plies are played (ply 82 and later), Stockfish plays on purpose: depth 18–26 with 15 s or more on your clock (~0.5–3 s), 14–16 with less.

---

## Step 2 · Look at the database (5 min)

```powershell
cd $lb
python database\db.py --check                 # integrity check, foreign keys + the number of rows in every table
python database\db.py --recent                # the newest 12 moves (what decided each one, how long it took) and events
python database\db.py --recent 40             # ... or the newest 40
```

The moves look like this (two lines from the fault test, where every worker was killed before ply 13, so Stockfish played it; a Kernel move shows its score and how many workers searched it):

```text
  2026-10-27 03:10:43  pOoLtEsT  ply  15  kernel             e1g1   score -110  28 workers, allowed 5 s, took 1902 ms
  2026-10-27 03:10:39  pOoLtEsT  ply  13  no_kernel_answer   b5c6               0 workers, allowed 3 s, took 72 ms
```

The events are every problem the engine noticed (dead or late workers, fallbacks to Stockfish, restarts): in normal games there are **none**. To browse everything with a GUI, [DB Browser for SQLite](https://sqlitebrowser.org/) opens the file directly, and reading is always fine, even during a game. ⚠️ But *unsaved edits* hold a write lock: while one is held, every record the engine stores waits up to 5 s and is then skipped (the engine's log says `!! database: ... was not stored`). A short lock costs nothing; a long one loses the moves played meanwhile. So click *Write Changes* or *Revert Changes* before a game starts.

---

## Step 3 · The first lichess sync (after the games, 2 min)

The engine stores its own side of every move. The **results, ratings, rating changes, clocks and openings** come from lichess, through the bot's token:

```powershell
cd $lb
python database\sync_lichess.py --since 2026-10-27        # the go-live date (a local date): games from that day on
python database\db.py --check                                   # games and moves have rows now
```

Run it **between games** (it uses the bot's token and IP). Later runs need no `--since`: it continues from where it stopped.

## Step 4 · A backup (any time)

```powershell
python database\db.py --backup                # a consistent copy in database\backup\ (safe while a game runs)
```

---

<div style="background:#fef2f2;border-left:6px solid #dc2626;border-radius:10px;padding:12px 18px;margin:16px 0;color:#1e293b;">

**🔙 Rollback, any time** (an illegal move, a crash, a real hang, anything odd).

⚠️ **A rollback overwrites the new engine files**, and tonight's work isn't committed yet. Best: **commit before the live games** (the message is in the Git notes below); then going forward again is one `git restore --source=HEAD`. If you haven't committed, copy them aside first (git ignores `engines\backup-*\`):

```powershell
New-Item -ItemType Directory "$lb\engines\backup-v4" | Out-Null
Copy-Item "$lb\engines\Engine UCI.cpp", "$lb\engines\Engine UCI.exe", "$lb\engines\Kernel.cpp", "$lb\engines\Kernel.exe", "$lb\engines\Stockfish Handler.hpp", "$lb\extra_game_handlers.py" "$lb\engines\backup-v4\"
```

Press Ctrl+C in the bot's window, then stop whatever is left (Windows won't let anything replace a running `.exe`):

```powershell
Get-Process -Name "Engine UCI", Kernel, stockfish* -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -like "$lb\*" } | Stop-Process -Force
```

**A · Back to Phase 1** (one Stockfish, but the old 28 threads + JSON files). Phase 1 was never committed, so its files are in `engines\backup-phase1\`:

```powershell
cd "$lb\engines"
Copy-Item "backup-phase1\Engine UCI.exe", "backup-phase1\Engine UCI.cpp", "backup-phase1\Stockfish Handler.hpp" . -Force
git -C $repo restore --source=46151b4 -- "lichess-bot-master/engines/Kernel.cpp" "lichess-bot-master/engines/Kernel.exe"
```

Phase 1's engine creates `input\`, `history\` and `logs\` (in `lichess-bot-master\`) by itself.

**B · Back to the version from before any AI change** (your initial commit):

```powershell
cd $repo
git restore --source=46151b4 -- "lichess-bot-master/engines/Engine UCI.cpp" "lichess-bot-master/engines/Engine UCI.exe" "lichess-bot-master/engines/Kernel.cpp" "lichess-bot-master/engines/Kernel.exe" "lichess-bot-master/engines/Stockfish Handler.hpp" lichess-bot-master/extra_game_handlers.py
cd $lb
Copy-Item -Recurse engines\stockfish stockfish      # that engine looks for Stockfish in its working folder
New-Item -ItemType Directory input | Out-Null       # it writes its JSON files there, and never creates the folder
```

⚠️ In B, `extra_game_handlers.py` **must** come back too: the old engine doesn't declare `GameId`, so python-chess would refuse every game.

Restart the bot: it runs exactly like before. The new files (headers, `tests\`, `database\`) can stay: the old engines never look at them. To go forward again: `git restore --source=HEAD -- <the same files>` (if v4 is committed), or copy the files back from `engines\backup-v4\`; then delete `lichess-bot-master\stockfish\` and `input\` again.

</div>

---

## 🧷 Git notes (git is yours; these are just the facts)

**What changed, for your commit** (`git status` will show exactly these, plus the neural-network lab's own changes):

| Path | Change |
|---|---|
| `lichess-bot-master/engines/Engine UCI.cpp` · `Engine UCI.exe` | The pool, the database, no more files per move (on top of Phase 1, which was never committed) |
| `lichess-bot-master/engines/Kernel.cpp` · `Kernel.exe` | The worker `main()`; the search is unchanged |
| `lichess-bot-master/engines/Chess State.hpp` · `Kernel Workers.hpp` · `Game Database.hpp` · `Engine Log.hpp` | New |
| `lichess-bot-master/engines/Stockfish Handler.hpp` | Phase 1's persistent Stockfish (+ one comment) |
| `lichess-bot-master/engines/sqlite/` · `Build Engines.bat` · `tests/` | New (`sqlite3.o` is ignored: the `.bat` compiles it) |
| `lichess-bot-master/database/` | New (`mrbits.sqlite` and `backup/` are ignored) |
| `lichess-bot-master/Mr Bits Docs/IPC and Game Database Plan/` | The docs, moved here from `lichess-bot-master/IPC and Game Database Plan/` (git shows delete + new until you `git add -A`, then renames) |
| `lichess-bot-master/extra_game_handlers.py` | `return {"GameId": game.id}` (Phase 1) + its comment |
| `.gitignore` | The engine's logs, the database files and backups, the rollback copies (`engines/backup-*/`). `data/`, `telemetry/`, `old_history/` are gone; `input/`, `history/`, `logs/` stay only for a rollback (the old engines write them) |

A message you could use:

```
Engine UCI: persistent Kernel workers, one Stockfish, every move in SQLite

- Kernel.cpp is a worker now: Engine UCI starts 28 of them once per game and
  sends each one request line per move over a pipe (the same ChessState the
  JSON file used to hold); the answer is one line. No more input\ files,
  cmd.exe or new processes per move. The search itself is unchanged: 144/144
  answers identical to the old Kernel.exe at the same depth.
- Stockfish Handler.hpp: one Stockfish, started once per game (Phase 1).
- Chess State.hpp: the one ChessState, included by Engine UCI and Kernel.
- Game Database.hpp + database/: every move, every worker, every depth and
  every candidate move goes into database/mrbits.sqlite after "bestmove"
  (no more history\ reports); sync_lichess.py adds lichess's results.
- Build Engines.bat and tests/: build, launch check, and three tests.
- The docs moved into Mr Bits Docs/; the old Stockfish copies are deleted.
```

**Facts worth knowing:**
- **Push:** `git push` (GitHub, your upstream) and `git push gitlab main`. Never `--all` or `--mirror`: the other AI agent writes its undo snapshots into your `.git` as `refs/codex/...`.
- **Big files:** Git for Windows **silently truncates any file over 4 GiB**, and GitHub rejects files over 100 MB. The biggest new file is `engines\sqlite\sqlite3.c` (9.6 MB): fine.
- **Line endings:** warnings like *"LF will be replaced by CRLF"* are harmless (`core.autocrlf=true`).

---

## 📦 Appendix: the tests (all in `engines\tests\` and `database\tests\`)

| Test | Run it from | What it proves |
|---|---|---|
| `engine_test.py` | `cd $lb\engines; python -B tests\engine_test.py` (or `Build Engines.bat test`) | lichess-bot's startup check + 3 games, every database row checked (~1 min) |
| `kernel_workers_test.py` | `cd $lb\engines; python -B tests\kernel_workers_test.py` | dead / frozen / all-dead workers, a hard kill (~1 min) |
| `kernel_equivalence_test.py` | `cd $lb\engines; python -B tests\kernel_equivalence_test.py --reference <another Kernel.exe>` (an old file-mode one with the default `--reference-mode file`, or another worker build with `--reference-mode worker`) | the Kernel still thinks exactly like before (~1 min) |
| `database\tests\` | `cd $lb\database; python -m unittest discover -s tests` | the init, the backup, the sync (offline fixtures), every dashboard filter |

The engine tests never touch the real database (they point `MRBITS_DATABASE_FILE` at a temporary one) and play from an empty temporary folder.

— **Claude Opus 5.5** 🤖
