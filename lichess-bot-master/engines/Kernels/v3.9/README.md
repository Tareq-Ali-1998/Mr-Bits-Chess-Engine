# ♟️ V3.9 · Small chooses ten above depth two

<div style="border-left:5px solid #7c3aed;background:#f5f3ff;color:#312e81;padding:10px 14px"><strong>STATIC SCORING: 50% Small neural network + 50% main-Kernel handcrafted scoring.</strong></div>

**5 November 2026 revision:** this unchanged search experiment moved from `v3.5` to **`v3.9`** to make room for the scoring controls. Historical records/build stamps keep their original names.

**Version identity:** `v3.9` was previously called `v12`. Historical verification counts, build stamps and diagnostic paths below retain that earlier identity; they are not fresh execution results for renamed binaries. [Family map](../VERSION_FAMILIES.md).

<style>
body{font-family:Segoe UI,Arial,sans-serif;line-height:1.35;color:#223047}h1,h2{color:#2354a5}h3{color:#17795e}table{border-collapse:collapse;width:100%}th,td{border:1px solid #cbd5e1;padding:.3em .45em}th{background:#edf3fc}pre{white-space:pre-wrap;font-size:.84em}@media print{body{font-size:10pt;line-height:1.22}h1{font-size:18pt}h2{font-size:14pt}h3{font-size:11pt}table,pre{break-inside:avoid}}@page{size:A4;margin:15mm}
</style>

<div style="border-left:5px solid #16a34a;background:#f0fdf4;color:#14532d;padding:10px 14px;">
<strong>🟢 Your experiment, precisely:</strong> copy V3.0, let Small rank every candidate when <strong>more than two ordinary plies remain</strong>, and search only the first ten. In the last two levels, preserve generation order: <strong>no neural sorting and no heuristic sorting</strong>.
</div>

V3.9 keeps V3.0's legal-move foundation, make/unmake restoration, terminal rules, bounded quiescence, and **50% handcrafted / 50% Small** static evaluation. Its separate [search policy](../V12%20Search.hpp) changes ordering and candidate selection. The original and V3.0 remain separate versions. Read [How V3.0 works](../v3.0/HOW_V3_0_WORKS.md) for that common foundation.

## 🟦 1 / 2 · Where the ten-move limit applies

Here, **depth means ordinary plies remaining**, not how far we have traveled from the root. One ply is one player's move. The root uses the requested iteration depth; each ordinary recursive move reduces it by one.

| Search stage | Ordering | Candidates eligible to continue |
|---|---|---|
| Root, depth **3+** | Small ranks the worker's entire supplied legal list | First ten, or all if fewer |
| Internal ordinary node, depth **3+** | Small ranks the complete generated legal list | First ten, or all if fewer |
| Ordinary depth **2 or 1** | **None**; retain generation/input order | All legal candidates; ordinary alpha-beta can cut off |
| Depth **0** → quiescence | **None**, including no cheap heuristic sort | V3.0's tactical eligibility rules; **no top-ten filter** |

```text
Example: an iteration requested at depth 6

remaining depth 6 → Small ranks all; keep ≤10
                5 → Small ranks all; keep ≤10
                4 → Small ranks all; keep ≤10
                3 → Small ranks all; keep ≤10
                2 → no sorting; all ordinary legal candidates
                1 → no sorting; all ordinary legal candidates
                0 → unsorted quiescence, up to 6 extra plies
```

**Every ordinary candidate competes for those ten slots:** quiet moves, captures, en passant, promotions, and check evasions. There is **no exemption while in check**. A checked node with eleven legal escapes can lose the eleventh-ranked escape; legal generation prevents illegal moves, but cannot make this deletion tactically safe.

Lists of two to ten are still Small-sorted at depth 3+, although no move is discarded. Empty and singleton lists skip sorting and its network work. Small scores each committed child once, restores the parent state, then sorts the saved scores; inference does not run inside the comparison function. White prefers higher White-perspective values; Black prefers lower values. Exact ties keep input order.

**The root cap is per worker subset.** If one worker receives twelve root moves, it keeps ten. If twelve workers each receive one move, all twelve roots can still be searched. V3.9 does not build one global ten-move shortlist across workers. At shallow depths, supplied root order is preserved; internal nodes preserve their generator's order.

Quiescence still recognizes mate/stalemate first. Outside check it uses stand pat and searches captures, en passant and promotions; in check it considers all legal evasions. Its six-ply hard cap remains. “All eligible” does not mean every move must be searched: ordinary alpha-beta and quiescence cutoffs still apply.

<div style="page-break-before:always;"></div>

## 🟪 2 / 2 · The cost, the score, and the honest comparison

### What one ranking call costs

The top-ten limit saves **future recursive work**. It does not reduce the number of child positions evaluated to produce the ranking.

```text
m candidates → make / encode / Small / undo for every candidate
             → sort m saved scores → retain min(m, 10) → recurse
```

For a depth-3+ list with `m ≥ 2`, ranking costs **`O(m × Csmall + m log m)`** time and `O(m)` temporary score storage, in addition to the network's fixed weights/scratch. This excludes recursive searches. With `A` active inputs, Small uses **`32,896 + 256A` useful floating-point arithmetic operations** per position: at most **42,624** for a legal input (`A ≤ 38`). Ranking thirty moves therefore needs up to **1,278,720** such operations, before encoding, sorting, memory traffic and recursion. These are mathematical counts, not CPU instructions or measured milliseconds. [Full operation counts](../../Neural%20Networks/OPERATION_COUNTS.md).

For `d ≥ 3`, a simple no-cutoff ordinary-tree estimate is `10^(d−2) × b²` leaves when the two final levels have branching factor `b`, rather than `b^d`. Actual worker root allocation, smaller lists, terminals and cutoffs change this. Quiescence adds variable work and can branch beyond ten. The tree remains exponential; greater displayed depth alone does not prove a better search.

### How a position receives its score

Nonterminal static evaluation remains V3.0's **50/50 handcrafted/Small blend**, converted to engine-perspective centipawns and clamped away from mate scores. Small receives the current board, actual side to move, castling rights and en-passant file. **Large is not used by this policy.** Exact mate/stalemate results take priority over static evaluation.

At completed depths 3+, the returned score describes the **beam-restricted tree**. A discarded root is not a searched loss or a proven inferior move. Depths 1–2 have no ordinary beam restriction, but still use bounded quiescence. V3.9 explicitly reports this distinction as `scoreScope`.

### Run it and measure what happened

Stop the existing bot, open **`Launch Server.bat`**, and select **`v3.9`**. Only Small weights are required. The dashboard's version filter includes V3.9; open **`Launch Dashboard.bat`** to inspect recorded completed moves.

Worker `searchPolicy` reports `smallOrderingCalls`, `smallRankedMoves`, `beamOrderingBatches`, `beamTruncations`, and `beamDiscardedMoves`. The root has separate `rootCandidatesBefore`, `rootCandidatesRetained`, and `rootCandidatesDiscarded` counts. `heuristicOrderingCalls` should remain **zero**. These extra counters live in worker JSON/diagnostics; the current SQLite writer does not persist them or stream in-flight searches.

Compare V3.9 against V3.0 with the same weights, positions, root assignments, worker count and clock. Track tactical misses, legal best-move retention, elapsed time, completed depth, nodes and eventually equal-time games. **No 95% retention, Elo improvement or optimal width is established.** Ten is an experimental setting.

**Verification provenance:** before family renaming, the top-ten policy compiled and 45 Python launcher/build checks passed. The [offline runner](../../tests/run_kernel_v12_tests.py) has a `--syntax-only` mode; native behavioral checks for the newly named artifact must be reported separately from those historical results. From `engines`, run `python tests/run_kernel_v12_tests.py` once offline native execution is available. This test starts no online bot.

V3.0's clock admission remains, but a running model load or ranking batch cannot be interrupted midway. V3.9 has no time-based heuristic fallback: an admitted high-depth ranking uses Small. Inherited limits also remain: no repetition/fifty-move/insufficient-material adjudication here, and a nonterminal checked position can be statically evaluated at the quiescence cap.

<div style="border-left:5px solid #8b5cf6;background:#f5f3ff;color:#312e81;padding:10px 14px;">
<strong>What comes next:</strong> this experiment is now <strong>v3.9</strong> in the legal/quiescence family. The former v7 is v3.0; its temporary legacy folder has been retired. The proposed search-table experiment (previously called V13) stays a plan until we discuss the <strong>combined worker memory upper bound</strong> first. Its future family label has not been assigned.
</div>

Read the [V13 memory proposal](../../../Mr%20Bits%20Docs/V13_MEMORY_PLAN.md) before that discussion: fixed arrays and estimated process RAM are different quantities.
