# v3 — neural ordering with a small root-only experiment

This version starts from the current `v1/Kernel-v1.cpp`. It changes move ordering and root candidate retention. The leaf evaluation, alpha–beta search rules, move generator, time controls, worker protocol, and shared neural evaluation/rollback code stay the same.

| Search location | Policy |
|---|---|
| Root, total depth 2 | Existing simple heuristic; retain all moves |
| Root, total depth 4 or greater | Large network orders every supplied candidate, then apply the retention rule below |
| Internal node, remaining depth 3 or greater | Small network orders all generated moves; discard none |
| Internal node, remaining depth 2 | Existing simple heuristic; discard none |
| Internal node, remaining depth 1 | Existing generator order |

The iterative-deepening loop still visits even root depths. These thresholds refer to the existing depth counters, not a newly defined search depth.

## Root retention: eight quiet moves plus every capture and promotion

After neural ordering, each worker keeps:

- The first **eight quiet moves** in that order.
- **Every capture**, including en passant and the engine's existing king-capture terminal mechanism.
- **Every promotion**, including non-capturing underpromotions.

With many workers, a typical worker may receive fewer than eight candidates, so this root cap can be inactive. Inspect assigned/unsearched root moves in the dashboard to verify actual omissions. That is an intentionally gentle first cutoff, not a guarantee that this version reduces branching in every position.

The retained moves keep their neural order. Eight is a quiet-move allowance, **not a total-move cap**. It applies separately to each worker's supplied root subset; it is not a global limit of eight moves for the bot.

If the moving king is attacked, missing, or duplicated, the root retains **all candidates**. A compact, read-only geometric attack guard checks pawn, knight, king, bishop, rook, and queen attacks with blockers. It exists only to disable this pruning experiment; it does not change the engine's legality rules or generate evasions. The castling-specific helper is intentionally not reused for arbitrary king locations.

## Parameters to change

The constants are together in `namespace v3_ordering` in [Kernel-v3.cpp](Kernel-v3.cpp):

```cpp
root_neural_min_depth = 4;
internal_small_min_depth = 3;
simple_ordering_min_depth = 2;
root_quiet_limit = 8;
```

The Large network therefore runs near the root rather than at every internal node. The Small network guides deeper internal ordering while all those continuations remain available. This is a performance/strength hypothesis, not a measured improvement.

## What can still go wrong

**A quiet check, sacrifice, or essential quiet move can still be excluded at the root.** The guard protects an already attacked king; it does not prove that a discarded move is irrelevant. A neural score is approximate, and the root cap can lose strength even if it allows a deeper completed search. The existing pseudo-legal internal move generation and terminal behavior also remain unchanged.

Use the ordering-only v2 as the useful comparison. Assess v3 with equal-time games and tactical cases before treating it as an improvement. No Elo gain is claimed here, and creating this source does not select it for production play.

The shared neural helper still evaluates each candidate after making it, restores the parent state, caches one score per candidate, and sorts those scores. No neural evaluation occurs inside a sorting comparator. Removing the related commented-out ordering experiments only makes this version easier to read.

For a compile-only check, from the `engines` directory:

```powershell
g++ -std=c++17 -O2 -I. -fsyntax-only 'Kernels/v3/Kernel-v3.cpp'
```
