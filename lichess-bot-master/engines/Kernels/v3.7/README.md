# 🟣 V3.7 · Large chooses three; Small and your evaluator share the verdict

<div style="border-left:5px solid #7c3aed;background:#f5f3ff;color:#312e81;padding:10px 14px"><strong>STATIC SCORING: 50% Small neural network + 50% main-Kernel handcrafted scoring.</strong></div>

**5 November 2026 revision:** this unchanged search experiment moved from `v3.3` to **`v3.7`** to make room for the scoring controls. Historical records/build stamps keep their original names.

**Version identity:** `v3.7` was previously called `v10`. Historical verification counts, build stamps and diagnostic paths below retain that earlier identity; they are not fresh execution results for renamed binaries. [Family map](../VERSION_FAMILIES.md).

**Offline verification, 31 October 2026:** 61,804 checks passed, including independent legality/perft fixtures, direct Large-ranking parity, a Python beam/quiescence reference, and the 50/50 score contract for both engine colors. The compiled worker passed startup plus seven actual search requests. From `lichess-bot-master`, repeat with `python engines/tests/run_kernel_v9_v11_tests.py --versions v3.7`. Local receipts: lab `diagnostics/kernel-v9-v11-20261031/v10/`.

<style>
body{font-family:Segoe UI,Arial,sans-serif;line-height:1.4;color:#223047}h1,h2{color:#6d28d9}table{border-collapse:collapse;width:100%}th,td{border:1px solid #cbd5e1;padding:.3em .45em}th{background:#f5f3ff}pre{white-space:pre-wrap;font-size:.86em}@media print{body{font-size:10pt;line-height:1.25}h1{font-size:18pt}h2{font-size:14pt}table,pre{break-inside:avoid}}@page{size:A4;margin:15mm}
</style>

<div style="border-left:5px solid #8b5cf6;background:#f5f3ff;color:#4c1d95;padding:10px 14px;">
<strong>The companion to V3.6:</strong> use exactly the same aggressive Large-ranked top-three search, but judge ordinary positions using <strong>50% your original score + 50% Small</strong>. This gives the two experiments one clear difference: their static evaluator.
</div>

## 🟪 1 / 2 · Two neural networks with two different jobs

V3.7 began as an exact PowerShell copy of V3.1. It shares its new aggressive search policy with [V3.6](../v3.6/README.md) through [V9 V10 Search.hpp](../V9%20V10%20Search.hpp), while retaining the [V3.0 legal/search foundation](../v3.0/HOW_V3_0_WORKS.md).

```text
Legal candidates at a regular node / worker root
             |
     Large scores every child once
             |
  Sort, then retain only the first three
             |
       Alpha-beta continuations
             |
  50% original evaluator + 50% Small
```

Large decides **which candidate moves remain**. Small contributes to **the value returned at nonterminal static positions**, including quiescence stand-pat and cap evaluations. Neither network's scalar prediction is a confidence guarantee.

| Choice | V3.6 | V3.7 |
|---|---|---|
| Ranking | Large, every nonempty expanded list | Same |
| Retained candidates | First three, or all if fewer | Same |
| Ordinary static score | Your original score | **50% original + 50% Small** |
| In-check beam exemption | None | None |
| Tactical-move exemption | None | None |
| Clock-triggered cheap ranking | None | None |
| Required weights | Large | **Large and Small** |

### The score conversion, with an example

The original score is already in engine-perspective centipawns. Small returns White-perspective pawn units, so V3.7 converts it first:

```text
legacy_cp = engineScore - opponentScore
neural_cp = Small(board, state) × 100 × (White engine ? +1 : -1)
static_cp = round(0.5 × legacy_cp + 0.5 × neural_cp)
```

For a White engine, your evaluator's **+80 cp** and Small's **+1.20 pawns** produce **+100 cp**. For a Black engine, the same board's White advantage is negative from the engine's perspective. The actual side to move, castling rights, and en-passant file still accompany the board into the network.

Ordinary values are clamped to ±99,999. Legal checkmate is recognized before neural inference and scores around ±1,000,000 with ply distance; stalemate returns zero. Neither model overrides those terminal rules.

<div style="page-break-before:always;"></div>

## 🟧 2 / 2 · The top-three rule is deliberately strict

At every regular root/internal expansion, Large ranks the entire available candidate list, even at remaining depth one. **30 candidates → 30 evaluations → 3 retained moves**. One candidate is still evaluated; zero candidates return immediately. White's moves prefer larger White-perspective values and Black's moves prefer smaller values. Equal scores preserve incoming order.

No capture, promotion, quiet check, or check evasion gets an automatic pass. If Large places the strongest defense fourth, the search does not examine it. This can make the engine too optimistic. The 50/50 leaf blend cannot recover a move already removed by the beam.

### What happens beyond the ordinary leaf?

The inherited quiescence search allows up to six extra plies. It recognizes mate/stalemate first. At the cap it returns the blended static score, even if a nonterminal position is still checked. Otherwise:

- **In check:** start with all legal evasions, then Large-sort and retain at most three.
- **Outside check:** try the blended stand-pat bound; if expansion continues, filter to captures/en passant/promotions, then Large-sort that eligible list and retain at most three.

A stand-pat cutoff, terminal, exhausted extension, or observed deadline can return before sorting. Whenever an eligible nonempty list actually expands, Large is used; there is no Small-only or heuristic ranking fallback.

### More depth is a hypothesis to measure

The ordinary retained tree has at most three children per node, but each ranking batch still evaluates **every** candidate with Large. At up to 38 active inputs, 30 rankings cost up to **1,023,790,080 useful arithmetic operations**, plus encoding/activation/sort overhead. Small adds up to **42,624** useful operations for each static position. See [the exact counting conventions and formulas](../../Neural%20Networks/OPERATION_COUNTS.md).

The coarse worst-case search cost includes both the narrow tree and broad ranking: roughly `O(b × C_large × 3^(d+6))`, plus legal generation, sorting, and Small static work. Large's approximately 68 MiB FP32 payload is separately cached in each worker process. The number of workers therefore matters to CPU/cache/memory behavior, not just the advertised depth.

The root limit is **per worker's assigned subset**. Four workers can each search three different root moves, so the controller may compare up to twelve retained roots across those subsets. V3.7 does not introduce a global root top-three coordinator.

### Use the measurements honestly

Stop an existing bot, open `Launch Server.bat`, and choose **v3.7**. Both `Neural Networks/Large/weights.bin` and `Small/weights.bin` must be available. Model loading and ranking batches cannot be interrupted halfway through; timed search can discard an incomplete iteration after those calls finish.

Worker JSON exposes Large ranking batches/candidate counts, `beamDiscardedMoves`, root candidates before/after selection, and `unsearchedRootMoves`. `rootScores` has at most three entries for a completed iteration. `scoreScope: beam_restricted_tree` makes the restriction explicit: its exact/bound labels concern that retained tree. The SQLite writer does not yet persist the extra policy counters.

Keep the inherited draw and quiescence limits in mind. Compare V3.6/V3.7 on the same positions, hardware, weights, worker count, and time control. Track tactical misses, actual elapsed time, completed depth, and game outcomes. A deeper restricted tree can still be weaker than a shallower search that kept the decisive move; neither experiment has a demonstrated Elo advantage.

