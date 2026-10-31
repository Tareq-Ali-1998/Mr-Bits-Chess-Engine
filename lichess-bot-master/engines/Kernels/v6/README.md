# 🟪 v6 — search late quiet moves more cheaply

Read the [v5/v6 comparison](../V5_V6_README.md) first. This version starts as a copy of the original Kernel and uses the same Small-network ordering and **50% handcrafted / 50% Small** leaf evaluation as v5. Its additional experiment is **late-move reduction (LMR)**.

## The idea

After good ordering, many later quiet moves will not improve the current best result. Search selected moves **one ply shallower first**. If that probe improves alpha at a maximizing node, or beta at a minimizing node, search the same child again at its **full requested depth** before using its score.

```text
Eligible late quiet move
          ↓
Search child one ply shallower
          ↓
Improves the current bound? ── yes → repeat at full depth
          │
          no
          ↓
Keep the reduced result; continue alpha-beta
```

## Exact protections

Reduction requires at least **four remaining plies**, and the move must come **after the first four ordered candidates**. Root moves always enter search at the requested child depth. Captures, en passant, promotions, castling, advanced pawn pushes, check evasions, checking moves, and moves exposing the moving king are never reduced. Missing or duplicated king state also prevents reduction.

Every candidate remains available. Ordinary alpha-beta cutoffs still apply. Internal ordering uses Small from depth three when its time reserve permits; shallower or time-constrained nodes use the existing simple heuristic. Both networks' public APIs remain available, but only Small is used by this policy.

## What to watch

LMR is approximate: a shallow result that fails to improve the bound can hide a deeper good continuation. Re-searches protect promising probes; they do not prove that every reduced move was harmless. The inherited pseudo-legal generator and king-capture terminal scheme remain in place.

Worker replies expose `lmrProbes` and `lmrResearches` separately from alpha-beta cutoffs, alongside ordering and leaf-evaluation counts. See `perDepth[].searchPolicy`; final `searchPolicy.counters` describes the last completed iteration. An interrupted iteration keeps its own counters and does not replace the completed result.

Choose **v6** in `Launch Server.bat`. It needs the Small weights. Run the offline checks from `engines` with `python tests/run_kernel_v56_tests.py --only v6`. Compare against v5 under equal time and positions before deciding which to use regularly; no strength gain has been established.

**Current machine:** the latest rebuilt v6 executable is blocked at startup by Windows Application Control (`WinError 4551`), after earlier builds passed the offline checks. See the [combined guide](../V5_V6_README.md) for the distinction. Resolve the signing/trust policy before trying it in games.
