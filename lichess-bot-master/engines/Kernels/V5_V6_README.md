# ♟️ v2.1 & v2.2 — two ways to spend the search budget

**Read this first.** Three short sections, with print page breaks. Start with **v2.1**, then compare **v2.2** under the same clock and worker count.

## 🟩 1 / 3 · The foundation: keep your engine, add Small

Both began as copies of your original `Kernel.cpp`, keeping its move representation, generator, incremental state, and worker protocol. The original, the v1.x ordering family, and the Small-only v2.0 experiment remain separate.

| Decision | v2.1 | v2.2 |
|---|---|---|
| Ordinary leaf score | 50% handcrafted + 50% Small | Same |
| Ordering at depth 1–2 | Your simple heuristic | Same |
| Ordering at depth 3+ | Small, when time permits | Same |
| Delete a fixed number of moves? | No | No |
| Search late quiet moves one ply shallower? | No | With guards and re-search |
| Active neural model | Small only | Small only |

**Why Small?** Its 216,961 parameters cost much less to evaluate than Large's 17.86 million in earlier local measurements. Frequent calls must earn back their cost. Lower prediction error alone does not establish stronger equal-time play.

The leaf calculation is:

```text
neural engine score = White-pawn output × 100 × engine-color sign
leaf score = round(0.5 × your score + 0.5 × neural engine score)
```

White's sign is +1; Black's is −1. Turn, castling, and en-passant flags follow the current branch.

The **50/50 blend is an untuned starting point**, not a confidence percentage. Ordinary scores are clamped below the existing terminal threshold; the original king-capture terminal score takes priority.

Worst-case search remains `O(b^d)` for branching factor `b` and depth `d`. Small's roughly 0.87 MB of weights load once per worker. Search undo saves changed-state information rather than copying full boards.

<div style="page-break-after: always;"></div>

## 🟪 2 / 3 · v2.2 asks a cheaper question first

V2.1 uses ordinary alpha-beta at the requested depth. It provides the comparison for the new evaluator and ordering policy.

V2.2 adds **late-move reductions (LMR)** inside the tree. After promising moves have been searched, a later quiet move receives a one-ply-shorter search first.

```text
Late quiet internal move
          ↓
 Search one ply shallower
          ↓
 Improves the pre-move bound?
     Yes → search again at full depth
     No  → keep the reduced result
```

At maximizing nodes, improvement means **score > alpha**; at minimizing nodes, **score < beta**. The full-depth re-search happens before that result can improve the bound or cause a cutoff.

A reduction requires **at least four plies remaining**, and starts only with the **fifth ordered move**. These moves stay at full depth:

- Every root candidate assigned to the worker.
- The first four internal moves, captures, en passant, promotions, and castling.
- Moves while the king is attacked, checking moves, and moves exposing their own king.
- Advanced pawn pushes: destination ranks 6–8 for White, 1–3 for Black.

Missing or duplicate kings disable reductions conservatively. The geometric check guard protects this experiment; it does not replace the original legality rules.

With the existing even-depth iterations, LMR normally first appears at root depth six. Shallower runs can correctly report zero probes.

**The tradeoff:** a reduced result that fails to improve the bound can still hide a deeper tactic. Re-search helps when the shallow probe looks promising; it cannot prove every quiet move is unimportant. This is selective depth, not guaranteed safe pruning or a top-five retention claim.

LMR is an established idea; the [official Stockfish search implementation](https://github.com/official-stockfish/Stockfish/blob/master/src/search.cpp) is a useful reference for reduce-and-re-search. This implementation is a small adaptation to Mr. Bits, not Stockfish's search code.

<div style="page-break-after: always;"></div>

## 🟦 3 / 3 · Run, inspect, and compare

In `lichess-bot-master`, open **`Launch Server.bat`**, then choose **`v2.1`** or **`v2.2`**. Both require `engines/Neural Networks/Small/weights.bin`; Large weights are unnecessary. The launcher builds as needed and checks the worker offline before starting the bot. Stop the existing bot before switching versions.

**Historical machine status, before family renaming:** the former v6 passed earlier tests, but a later rebuilt binary was blocked before startup: `WinError 4551`, confirmed by Code Integrity event 3077. That earlier execution check was **blocked**. It does not establish the startup result of a newly named build; use the launcher's actual startup check. No security settings changed. Microsoft's [Smart App Control guidance](https://support.microsoft.com/en-us/windows/security/threat-malware-protection/smart-app-control-frequently-asked-questions) explains trusted signing if that control is responsible.

Small ordering requires **`max(5, ceil(move_count / 8))` milliseconds** remaining; otherwise your heuristic orders the same candidates. This reserve cannot interrupt model loading or an admitted batch. Leaf evaluation stays consistent as time runs down.

The undo guard restores state on returns, timeouts, and exceptions. The existing loop discards interrupted iterations.

For offline policy tests, from the application folder:

```powershell
python engines/tests/run_kernel_v56_tests.py
```

Reports go to the lab's `diagnostics/kernel-v5-v6-20261029/`. Worker JSON counts neural ordering, neural leaves, reductions, and re-searches. **SQLite does not preserve these extra counters yet.** The dashboard retains its existing version, depth, node, timing, outcome, and candidate views.

**Earlier offline verification, under the former v5/v6 labels:** 752 policy checks passed for each version. The earlier verified worker builds also reached depth six with two assigned root candidates:

| Starting position / side | v2.1 nodes / choice | v2.2 nodes / choice |
|---|---|---|
| Initial board / White | 84,762 / `b1c3` | 55,971 / `b1c3` |
| After `e2e4` / Black | 100,319 / `e7e5` | 39,487 / `c7c5` |

These are node counts summed across all iterations from single workers, not full-engine throughput or playing strength. The changed Black choice makes the selectivity tradeoff visible. Full replies, timings, build hashes, and requests are saved in the diagnostic folder.

Compare equal clocks, positions, opponents, and worker counts. V2.2's reported depth and exact-score labels describe its selective policy, not uniform-depth minimax.

Original legality/draw limitations and lack of quiescence remain. Measure tactical misses and equal-time games before tuning; no strength gain is established.

Details: [v2.1](v2.1/README.md) · [v2.2](v2.2/README.md) · [shared constants and search](Neural%20Search.hpp).
