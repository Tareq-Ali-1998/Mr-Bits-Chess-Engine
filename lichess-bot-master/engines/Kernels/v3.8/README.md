# ♟️ V3.8 · Ask a cheaper question before doing more work

<div style="border-left:5px solid #7c3aed;background:#f5f3ff;color:#312e81;padding:10px 14px"><strong>STATIC SCORING: 100% Small neural network + 0% main-Kernel handcrafted scoring.</strong></div>

**5 November 2026 revision:** this unchanged search experiment moved from `v3.4` to **`v3.8`** to make room for the scoring controls. Historical records/build stamps keep their original names.

**Version identity:** `v3.8` was previously called `v11`. Historical verification counts, build stamps and diagnostic paths below retain that earlier identity; they are not fresh execution results for renamed binaries. [Family map](../VERSION_FAMILIES.md).

<style>
body{font-family:Segoe UI,Arial,sans-serif;line-height:1.4;color:#223047}h1,h2{color:#2354a5}table{border-collapse:collapse;width:100%}th,td{border:1px solid #cbd5e1;padding:.35em .5em}th{background:#edf3fc}pre{white-space:pre-wrap;font-size:.86em}@media print{body{font-size:10pt;line-height:1.25}h1{font-size:18pt}h2{font-size:14pt}table,pre{break-inside:avoid}}@page{size:A4;margin:15mm}
</style>

<div style="border-left:5px solid #16a34a;background:#f0fdf4;color:#14532d;padding:12px 16px;">
<strong>🟢 My alternative experiment:</strong> retain every legal ordinary candidate, use Small for the position score, and save work with narrow-window searches plus a small, exact-input evaluation cache. V3.6/V3.7 investigate aggressive deletion; V3.8 investigates doing less repeated work while preserving V3.1's full-width search result.
</div>

V3.8 began as an exact PowerShell copy of V3.1. Its changes live in [V11 Search.hpp](../V11%20Search.hpp); the existing [V3.0 position helper](../V7%20Position.hpp) still handles legal moves and exact undo. Read [How V3.0 works](../v3.0/HOW_V3_0_WORKS.md) for the common foundation.

## 🟦 1 / 2 · Two ways to avoid unnecessary work

### A. Principal variation search: test the current best first

At an ordinary internal node, V3.8 searches the first move with the full current alpha-beta window. Later candidates get a narrow **one-centipawn scout window** when that window fits.

```text
First candidate → full-window search → establish the current bound
Later candidate → scout: can this move improve that bound?
                      |
         no ----------+---------- yes, without a cutoff
         |                                  |
  keep the bound                  repeat with the full window
                                            |
                                    update the best score
```

For a maximizing node, the scout window is `[alpha, alpha+1]`; for a minimizing node, it is `[beta−1, beta]`. A scout that finds a possible improvement inside the original window triggers a **full-window re-search at the same depth**. A scout that establishes a cutoff already provides the bound needed to stop that node.

This changes search windows, **not move depth or candidate count**. No fixed top-three list, late-move reduction, or neural confidence filter is used. The root retains the ordinary full-window loop over every supplied legal candidate. Quiescence retains the V3.1 algorithm rather than adding scouts there.

Good ordering makes scouts useful: the first move is more likely to establish a strong bound. Poor ordering can cause extra re-searches and make PVS slower. We must measure the tradeoff; the name of the technique is not a speed guarantee.

PVS is an established search technique, not a new invention claimed here. The [official Stockfish search implementation](https://github.com/official-stockfish/Stockfish/blob/master/src/search.cpp) is a primary example of narrow non-PV searches followed by full PV searches. V3.8's much smaller implementation was written independently for this engine; it does not copy Stockfish's search code or reproduce its other pruning rules.

### B. Remember an identical static neural evaluation

Searching different move orders can reach an identical position. Iterative deepening also repeats work. V3.8 stores recently computed **raw Small White-pawn values** in a fixed-size direct-mapped cache.

```text
64 piece codes + actual side to move + castling rights + raw EP file
                              |
                        choose a cache slot
                              |
                 compare the COMPLETE stored input
                     /                     \
                 exact hit                  miss
                    |                         |
           reuse raw White score       call Small; store it
                     \                       /
                     convert to engine centipawns
```

The hash chooses a slot; it does not establish identity. A hit requires equality of **all 64 piece codes and every state flag**. Different positions sharing a slot replace one another and count as collisions. They never reuse each other's score merely because the hash matched.

The cache stores the network's White-perspective float, so the engine's color is applied **after lookup**. That preserves the same sign contract when White and Black engines view the same input. Missing weights, exceptions, and non-finite outputs never create valid new entries.

<div style="page-break-before:always;"></div>

## 🟪 2 / 2 · What remains, what costs, and what to measure

| Part | V3.8 policy |
|---|---|
| Static position score | **100% Small**, rounded/clamped engine-perspective centipawns |
| Terminal results | Rule-based mate/stalemate, recognized before static evaluation |
| Ordinary candidates | Every legal candidate retained; alpha-beta may cut subtrees |
| Ordering | Your cheap heuristic, tactical prefix, Small quiet-tail ordering from remaining depth 3 when time permits |
| Leaf extension | V3.1's bounded quiescence, up to six extra plies |
| New work-saving features | Internal PVS scouts/re-searches and cached static Small values |
| Large weights | Not required |

The cache contains **4,096 entries**. With the current x64 layout of 76 bytes per entry, its array uses **311,296 bytes: 304 KiB per worker process**. The worker reports the compiler's actual `sizeof` as `staticCacheBytes`. Memory is bounded; it does not grow with game length or node count.

Each lookup constructs and hashes the 64-square/state key and may compare that complete key. A hit skips a Small forward pass, but is not free. A miss still pays the forward pass; an overwrite can evict something useful. The cache is cleared at request setup, then reused across that request's iterative-deepening passes. It stores **static values only**: no search scores, depths, mate-distance values, or alpha/beta bounds. This is not a search transposition table.

Halfmove counts and repetition history are not Small's inputs, so they are not part of this raw-model cache key. The cache establishes identical **neural inputs**, not identical complete draw-rule history; terminal/rule adjudication belongs before a static lookup.

The shared quiet-move sorter still performs its own Small evaluations. Those calls do not use this new static cache. That is a concrete boundary of the current experiment, not an assumed saving.

### ⏱️ Complexity and visible counters

Worst-case search remains exponential, bounded by the ordinary depth plus the six-ply extension. PVS aims to improve practical cutoff work, not its worst-case complexity. A cache lookup costs `O(64)` input work on this fixed board; a miss adds the [Small inference cost](../../Neural%20Networks/OPERATION_COUNTS.md). The bounded table costs `O(4096)` storage.

Worker `searchPolicy` counters expose:

- `pvsScouts` / `pvsResearches`: narrow-window attempts and full-window retries.
- `cacheHits` / `cacheMisses` / `cacheCollisions`: static lookup outcomes.
- `nnForwardCalls`: **static-evaluator** forward passes only; quiet-sort forwards are separate.
- Existing regular/Q nodes, ordering batches, cap hits, terminals, and deadline observations.

These extra counters remain in worker JSON/diagnostics; the current SQLite writer does not preserve them. Existing dashboard records still show the selected version, move history, timing, depth, and node totals.

### ▶️ How to try it

Stop the existing bot, run `Launch Server.bat`, and select **v3.8**. Only Small weights are needed. Compare V3.8 with V3.1 using identical weights, positions, root assignments, hardware, and time controls. Test score agreement with PVS/cache disabled, then measure node counts, elapsed time, cache hit rate, re-search rate, tactical results, and eventually games.

The inherited limitations remain: no repetition/fifty-move/insufficient-material draw adjudication here; quiescence can reach its hard cap while still in check; clock checks cannot interrupt individual model loads, inference batches, or legal-generation batches. Neither greater depth nor fewer nodes alone establishes greater playing strength.

<div style="border-left:5px solid #8b5cf6;background:#f5f3ff;color:#312e81;padding:12px 16px;">
<strong>💜 Why I chose this experiment:</strong> your fast make/search/unmake loop deserves an approach that keeps tactical candidates available. V3.8 asks, “Can we reject an unpromising continuation with a cheaper window, and can we avoid evaluating an identical input twice?” Both savings are observable and can be checked against the unchanged full-window result.
</div>

**Verified offline, 31 October 2026:** 61,762 checks passed, including four-way PVS/cache on/off score agreement, collision/flag/sign/exception checks, and 136 independent legality/perft fixtures. Tests exercised 1,652 scouts and 152 re-searches. The actual worker passed startup and seven searches; three fixed-depth full-root cases matched V3.1's best move and score. Total node counts increased in two cases and fell in one, so this is a correctness result, not proof of a speed or strength gain. Repeat from `lichess-bot-master`: `python engines/tests/run_kernel_v9_v11_tests.py --versions v3.8`. Receipts: lab `diagnostics/kernel-v9-v11-20261031/v11/`.
