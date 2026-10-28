# ♟️ Mr. Bits

**A personal C++ chess engine that started with a friend's challenge.**

🟦 C++17 · 🟩 Classical search · 🟨 Bit manipulation · 🟪 Parallel workers · ♟️ Lichess

[The story](#the-story) · [Inside the Kernel](#inside-the-kernel) · [Run it](#run-it-locally) · [Reading guide](#where-to-start-reading)

<a id="the-story"></a>

## 🟨 “Can you code a chess engine?”

Around **2022–2023**, one of my friends started playing chess. I was usually sitting next to him doing competitive programming. One day, he asked me:

> Can you code a chess engine?

That question stayed in my head. I started working on it, and I barely slept for the next three or four days. I wanted to see my own code look at a position, explore its possibilities, and choose a move.

I remember the first working launch reaching **depth 6**, and later reaching **depth 8 in a complicated position**. Seeing the search go further after changing a representation or removing repeated work kept pulling me back.

After that first intense start, I returned to the engine every once in a while. I would learn another algorithm, rethink part of the recursion, rewrite something, or try an optimization that had been sitting in my head. Some ideas came from competitive programming; others came from staring at this particular problem until I found a better way to handle it.

Mr. Bits became one of my favorite personal projects. **The part I am proudest of is the flow inside `Kernel.cpp`: committing a move, searching what follows, and returning everything to exactly where it was.**

<a id="inside-the-kernel"></a>

## 🟦 Inside the Kernel

My main focus was the cost of searching a position. Work repeated at every node adds up quickly, so I spent a lot of time on representation, precomputation, and the details of making and undoing moves.

### A move fits in 16 bits

I chose to pack a move into an `int16_t`. Each row or column needs three bits; four coordinates use twelve bits, leaving four for a move-type tag, including special moves.

```text
           A single 16-bit move
┌───────────┬────────┬────────┬──────────┬──────────┐
│ move type │ to col │ to row │ from col │ from row │
│  4 bits   │ 3 bits │ 3 bits │  3 bits  │  3 bits  │
└───────────┴────────┴────────┴──────────┴──────────┘
 high bits                                  low bits
```

That representation carries through move generation, ordering, and recursion: compact move lists, with coordinates extracted through shifts and masks.

### Finding pieces through two integers

I maintain two 64-bit `long long` masks: `whitePieces` and `blackPieces`. Each set bit identifies an occupied square for that color. The search takes the **most significant set bit**, clears it from a local copy, and uses lookup tables to recover the piece's row and column.

This lets it visit the pieces directly without scanning all 64 board squares just to find them. The traversal follows occupied bits; the board supplies the actual pieces. Saving that discovery work at every node was exactly the kind of optimization I enjoyed.

### Make the move. Search. Put it back.

The original recursive search changes the current board in place. It saves the captured-piece information, occupancy masks, and running scores, then restores the state after exploring the child.

```text
Save changed-state information
             ↓
       MakeChanges(move)
             ↓
     Search the child position
             ↓
   Restore masks and scores
             ↓
      ReturnChanges(move, …)
             ↓
      Explore the next move
```

Getting this right took real attention. Captures, counters, castling, promotions, and en passant all have to survive that round trip. The recursive path avoids copying a full board for every child, while material and piece-square contributions are updated incrementally. Precomputed move and square tables remove more repeated work.

This is the part of the source I would most like another programmer to read.

### Making search order count

I worked on handcrafted move ordering, iterative deepening, alpha-beta pruning, and selective search. My simple heuristic uses capture values and piece-square changes to put promising moves earlier. Other ordering paths use shallow search results.

Learning how much the **order of exploration** changes alpha-beta's work was a big part of this project. I cared about each node's cost and how much useful search I could finish before the clock ran out. I want to compare that work with other engines on the same positions, hardware, and time budget, accounting for different pruning policies.

## 🟪 Learning to run the search in parallel

I also spent a lot of time on the threading side. The original controller split root moves across threads, launched separate Kernel executables, waited for their answers, and combined the results. Working through that taught me about distributing work, isolating search state, coordinating results, and respecting time limits.

The current controller keeps Kernel worker processes alive, exchanges requests through stdin/stdout pipes, and handles deadlines, shutdown, and worker replacement. This is a later evolution of the original process-and-file approach.

## 🟩 Taking it onto Lichess

Connecting through **lichess-bot** meant I could watch my engine play other bots under a real clock. The upstream bridge handles Lichess communication; my C++ UCI controller connects it to the search workers and Stockfish support.

```text
Lichess ↔ lichess-bot (Python) ↔ Engine UCI (C++)
                                  ├─ Kernel workers: selected search version
                                  ├─ Stockfish support
                                  └─ SQLite → local game dashboard
```

Stockfish supplies legal root candidates and supports configured opening, endgame, and fallback paths. Mr. Bits has its own search and evaluation; the dashboard records which decision path produced a move.

There is now also a **local SQLite database and browser dashboard** for replaying recorded moves, inspecting worker depths and timings, and comparing labeled engine versions.

## 🧠 The next chapter: neural experiments

Neural networks came later, after the classical engine and its optimizations. Separate Kernel versions now let me experiment with learned evaluation and ordering while keeping the original baseline.

Small has **216,961 parameters**; Large has **17,858,049**. Both use native C++ inference with a sparse first projection. The [complexity guide](lichess-bot-master/engines/Neural%20Networks/TIME_COMPLEXITY_README.md) and [training/inference report](lichess-bot-master/Mr%20Bits%20Docs/ChatGPT%20Neural%20Network%20Lab/docs/TRAINED_NETWORKS_AND_CPP_GUIDE.md) explain their costs. Playing strength and best-move retention still need tactical and equal-time game testing.

**I wrote the original engine myself.** Later refactoring, neural experiment infrastructure, tooling, and documentation include AI assistance. The recent Git history reflects publishing and organizing a project that began years earlier. The Lichess bridge, Stockfish, and supporting libraries belong to their respective authors; my from-scratch work is the custom engine.

## Run it locally

### Requirements

The integrated engine currently targets **Windows x64**, using Win32 process and pipe APIs. The training lab has a separate Linux/GPU workflow.

- **Python 3.11 or later**; the commands below use **Python 3.12** with the pinned bot dependencies.
- **MinGW-w64 GCC and G++**, supporting C++17, with `gcc` and `g++` on `PATH`.
- An **AVX2-capable CPU** for the bundled Stockfish executable. Other CPUs require a compatible Stockfish build and a corresponding path adjustment in `Stockfish Handler.hpp`.
- A Lichess BOT account and an OAuth token with `bot:play`. Follow the upstream [account/token setup](https://github.com/lichess-bot-devs/lichess-bot/wiki/How-to-create-a-Lichess-OAuth-token) and [BOT upgrade instructions](https://github.com/lichess-bot-devs/lichess-bot/wiki/How-to-Upgrade-to-a-BOT-account).

The normal C++ engine does **not** require PyTorch or a GPU. SQLite's C source is bundled for the local build.

### 1. Prepare Python and configuration

Clone or download this repository. From **PowerShell at the repository root**:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r .\lichess-bot-master\requirements.txt
Copy-Item .\lichess-bot-master\config.yml.default .\lichess-bot-master\config.yml
```

On a new checkout, edit `lichess-bot-master/config.yml`. Keep the rest of the copied template and update these existing values; replace the template's entire `engine.uci_options` mapping with `{}`:

```yaml
token: "YOUR_LICHESS_BOT_TOKEN"

engine:
  dir: "./engines/"
  name: "Engine UCI.exe"
  protocol: "uci"
  ponder: false
  uci_options: {}
```

This is an excerpt, not a replacement for the full configuration. Review the challenge and matchmaking settings before starting online play. Your real configuration and token stay outside Git.

### 2. Initialize the database and start the original engine

In the same PowerShell window:

```powershell
Set-Location .\lichess-bot-master
..\.venv\Scripts\python.exe database\db.py --init
..\.venv\Scripts\python.exe engines\Kernels\launch_server.py --version original
```

The launcher builds or reuses the selected Kernel and UCI controller, then starts the bot. Omit `--version original` to open the version menu. Add `--prepare-only` to build/select without starting online play.

**`original` works without neural weights.** Raw datasets, training runs, and trained `weights.bin` files are excluded from Git. Neural versions require the appropriate local exports under `engines/Neural Networks/Small/` and `Large/`; choose `original` if you do not have them. See the [neural deployment guide](lichess-bot-master/engines/Neural%20Networks/README.md) for their format and export steps.

### 3. Open the dashboard

In another PowerShell window, from `lichess-bot-master`:

```powershell
..\.venv\Scripts\python.exe database\dashboard\server.py --open
```

The viewer opens at **http://127.0.0.1:8765/** and refreshes newly recorded moves every five seconds. Full two-sided replay and completed results use the existing synchronization step:

```powershell
..\.venv\Scripts\python.exe database\sync_lichess.py
```

The dashboard reads local data; the explicit sync command contacts Lichess. Empty or incomplete records stay visibly empty or incomplete.

For an already configured Python environment, **`Launch Server.bat`** and **`Launch Dashboard.bat`** provide the same entry points. They use plain `python`, so launch them from an activated environment or ensure your default Python has the dependencies above. Stop the existing application before changing versions.

## The Kernel experiments

| Version | Main idea |
|---|---|
| `original` | The existing classical search baseline |
| `v1` | My Large-network ordering and aggressive top-four experiment |
| `v2` | Large near the root, Small internally; retain every candidate |
| `v3` | Gentler root filtering: eight quiet moves plus captures/promotions; retain everything while in check |
| `v4` | Small-network ordinary leaf scoring, initially 0% handcrafted / 100% neural; Small ordering from depth six |

The menu discovers version folders so new ideas can be added without replacing the original source. Root cutoffs apply to each worker's assigned subset. These are experiments to measure, not a ranking of strongest to weakest. [Policies, build commands, and tests](lichess-bot-master/engines/Kernels/README.md).

## Where to start reading

For the engine itself, start with [Kernel.cpp](lichess-bot-master/engines/Kernel.cpp), then [Engine UCI.cpp](lichess-bot-master/engines/Engine%20UCI.cpp) and [Stockfish Handler.hpp](lichess-bot-master/engines/Stockfish%20Handler.hpp). These are the main custom-engine entry points.

| Guide | What it explains |
|---|---|
| [Start here](lichess-bot-master/Mr%20Bits%20Docs/START_HERE_KERNELS_AND_DASHBOARD.md) | Version selection, launching, and viewing games |
| [Documentation index](lichess-bot-master/Mr%20Bits%20Docs/README.md) | Reviews, design notes, and the project's reading map |
| [Neural training lab](lichess-bot-master/Mr%20Bits%20Docs/ChatGPT%20Neural%20Network%20Lab/README.md) | Data preparation, training, evaluation, and reproducible experiments |
| [Dashboard](lichess-bot-master/database/dashboard/README.md) | Recorded metrics, replay, live-refresh behavior, and interpretation |

## What comes next

I will keep improving the organization and explanations as the engine develops. My priorities are stronger correctness/tactical tests, fair version comparisons, better training coverage, efficient evaluation, and clearer release artifacts for the neural models. Every change should earn its place through correctness, measured speed, memory use, or a clearer understanding of the tradeoff.

I would like this repository to show both the engine and how I think through engineering problems. Questions, reproducible positions, benchmark results, and thoughtful criticism are welcome. This is a personal project I care about, and I intend to keep learning from it.

## Credits and licenses

Thank you to [Lichess](https://lichess.org/), [lichess-bot](https://github.com/lichess-bot-devs/lichess-bot), [Stockfish](https://github.com/official-stockfish/Stockfish), [python-chess](https://github.com/niklasf/python-chess), and [nlohmann/json](https://github.com/nlohmann/json).

The upstream [lichess-bot README](lichess-bot-master/README.md) remains available. Existing license notices are retained, including [lichess-bot's AGPLv3 license](lichess-bot-master/LICENSE) and [Stockfish's GPLv3 license](lichess-bot-master/engines/stockfish/Copying.txt). These components retain their own authorship and licensing.
