# ♟️ v7 — give the search a stronger tactical foundation

**New: read [How V7 works](HOW_V7_WORKS.md) for the illustrated five-part explanation**, including exactly when moves are sorted, what stays eligible, quiescence, evaluation, and clock decisions. This file remains the short reference.

**My choice for the next experiment:** legal continuations, correct mate/stalemate recognition, and a short tactical search beyond the ordinary leaf. V7 began as a copy of your original Kernel; the original and v1–v6 remain separate.

## 🟩 1 / 3 · What changes

| Area | V7 decision |
|---|---|
| Move generation | Independent generator using your compact moves and occupancy masks; reject moves leaving the king attacked |
| Root | Validate every supplied move; retain the worker's complete assigned subset |
| Regular ordering | Captures/promotions first with your heuristic; Small orders only the quiet tail from depth 3 |
| Leaf | Quiescence: continue tactical exchanges and check evasions, up to six extra plies |
| Static evaluation | 50% handcrafted score + 50% Small, in engine-perspective centipawns |
| Pruning | Ordinary alpha-beta; no fixed top-k deletion or late-move reductions |
| Terminal positions | Legal checkmate or stalemate, recognized before neural evaluation |

The new generator explicitly handles pins, king adjacency, all four promotion types, castling through attacked squares, and en passant that exposes the king. It requires a genuine preceding opposing pawn double push for en passant. Castling requires the correct home king and same-color rook; queenside b-file emptiness matters, but an attack on that square does not forbid castling.

Replay history is checked move by move. An illegal history is rejected and rolled back. The worker's root list is a subset, so an empty assigned list alone is never called stalemate.

Independent score recomputation also caught an inherited Black en-passant update using the wrong color's piece-square tables. V7 corrects that incremental update for both engine colors; the earlier versions remain unchanged.

## 🟪 2 / 3 · Avoid evaluating halfway through an exchange

```text
Normal depth reaches zero
           ↓
Generate legal moves; recognize mate/stalemate
           ↓
In check? Search every legal evasion
Otherwise: static score + captures/EP/promotions
           ↓
Repeat up to six extra plies; return the score
```

A normal static cutoff is allowed only outside check. Quiet promotions remain tactical moves. Quiescence uses cheap ordering, with no neural move-sorting batches.

At the hard extension cap, v7 still recognizes mate/stalemate first. A remaining nonterminal position is evaluated statically, **including a position still in check**. That bounded approximation is counted as `qCheckCapHits`; the extension is not proof that every exchange was fully settled.

Checkmate scores start at ±1,000,000 with ply distance favoring faster wins and slower losses. Ordinary blended scores are clamped to ±99,999. Small's White-pawn output is multiplied by 100 and signed for the engine's color; its turn/castling/en-passant flags follow the actual branch.

Search undo restores only touched squares, counters, masks, and running scores, including on exceptions. Worst-case work can grow to `O(b^(d+6))`; the extra tactical work must justify its cost. There is no new quiescence delta pruning or transposition table. Repetition, the fifty-move rule, and insufficient-material adjudication are **not implemented here**.

## 🟦 3 / 3 · Clock, use, and measurements

Choose **`7` / `v7`** in `Launch Server.bat`. Only Small weights are required. The launcher checks the worker offline before starting the bot. Stop an existing bot before changing versions.

Small quiet ordering requires at least `max(5, ceil(quiet_count / 8))` milliseconds remaining. Otherwise the same quiet moves retain heuristic ordering. The leaf evaluator stays consistent.

Online iterative deepening now estimates the next iteration from measured growth, with a 25% safety factor and 5 ms reserve. It stops admitting new iterations after 80% of the budget is consumed. The hard deadline still discards unfinished iterations. These checks cannot interrupt an individual model load, inference batch, or legal-generation batch; this is not a hard real-time guarantee. Fixed-depth tests keep the existing even-depth sequence.

Offline checks:

```powershell
# From lichess-bot-master:
python engines/tests/run_kernel_v7_tests.py
```

Reports belong under the lab's `diagnostics/kernel-v7-20261029/`. Read the reported compile/run status; Windows policy can block startup independently of compilation.

Local verification passed **73,448 checks**, including 136 independent positions, starting-position perft depth 4 (**197,281**), Kiwipete depth 3 (**97,862**), quiescence comparisons and mate-in-one searches for both engine colors. The compiled worker also passed JSON-protocol, quiet-neural-ordering, Black en-passant replay, and one-second-budget checks. These establish tested behavior, not a strength rating. Move-rule references: [FIDE Articles 3.7–3.9](https://handbook.fide.com/chapter/E012023); independent oracle: [python-chess](https://python-chess.readthedocs.io/en/latest/core.html#chess.Board.legal_moves).

Worker JSON records regular/Q nodes, static evaluations, quiet-ordering calls, cap hits, mates, stalemates, and deadline observations. `nodes` describes the last completed iteration; `totalNodes` sums all iterations, including an interrupted attempt. Extra `searchPolicy` counters are not yet persisted by the SQLite writer.

Compare tactical fixtures and equal-time games against v5 before judging strength. Legal/Q node counts differ from the older pseudo-legal trees; timing and tactical accuracy give the useful comparison. The 50/50 blend and six-ply cap are starting parameters, not measured optimal settings. Code: [position/undo](../V7%20Position.hpp) · [search/constants](../V7%20Search.hpp).
