# v4 — Small neural leaves and ordering from depth six

This version starts from the current v1 source and changes its move-ordering policy and ordinary leaf evaluation. It keeps every candidate move and uses the Small network throughout its active neural search path.

| Location | Behavior |
|---|---|
| Root, total iteration depth below 6 | Original supplied move order |
| Root, total iteration depth 6 or greater | Small-network ordering; retain every move |
| Internal node, remaining depth below 6 | Generator order |
| Internal node, remaining depth 6 or greater | Small-network ordering; retain every move |
| Ordinary depth-zero leaf | 0% legacy evaluation, 100% Small-network evaluation |
| Existing king-capture terminal score | Return the exact legacy terminal score before any neural leaf evaluation |

There is no candidate cap, selective move deletion, Large-network ordering, simple-heuristic ordering, or iterative-search ordering on v4's active search path. The existing alpha–beta cutoffs remain. Unused legacy helper definitions remain available for comparison.

## Leaf score and future mixing

The Small network returns a **White-perspective pawn-like float**. v4 multiplies it by 100, changes its sign when the engine plays Black, and returns an engine-perspective integer score. The sign depends on `ENGINE_COLOR`, not on whether the current node is the engine's turn. The existing engine-relative max/min search therefore receives a consistent score at every node.

The named constants are together in `namespace v4_policy` in [Kernel-v4.cpp](Kernel-v4.cpp):

```cpp
small_ordering_min_depth = 6;
legacy_evaluation_weight = 0.0;
small_neural_evaluation_weight = 100.0;
```

The weights are normalized by their sum, so `25 / 75` and `1 / 3` both represent a quarter legacy and three quarters neural. They must be nonnegative with a positive sum. This is a future experiment parameter, not evidence that a particular blend improves playing strength. The two evaluators' scales can still differ despite both being expressed in pawn-like centipawns.

Ordinary blended scores are rounded and clamped to ±99,999, below the existing terminal threshold. Non-finite neural scores are rejected. Terminal scores bypass this blend and clamp. Incremental legacy scores are still maintained by the original make/undo logic because the existing terminal mechanism uses them.

## The neural position flags

The public `EvaluatePositionWithSmallNeuralNetwork(position, state)` wrapper returns White pawns and uses the shared cached model and a thread-local workspace. v4 builds each leaf's state with:

- Actual side to move: `turn == ENGINE_COLOR` because `turn` is engine-relative.
- Retained castling rights from the existing board and move counters.
- En-passant target inferred from the **current branch's `previousMove`**, including double pushes for which no legal en-passant capture is available. Root history is not substituted for that branch move.

These helpers only read the position. No new legality, draw, time-control, or worker-protocol behavior is introduced.

## What this experiment measures

Ordering is inactive below six, but neural leaf evaluation is active at every ordinary depth-zero leaf, including shallow iterations. This increases evaluation work compared with reading the existing incremental score. Equal-time tactical tests and games are needed to determine whether the learned evaluation compensates for that cost; no strength gain is claimed.

For a compile-only check, from `engines`:

```powershell
g++ -std=c++17 -O2 -I. -fsyntax-only 'Kernels/v4/Kernel-v4.cpp'
```

Useful diagnostic APIs are `v4_policy::ShouldOrder`, `LeafState`, `BlendLeafScores`, and `EvaluateLeaf`. Call `EvaluateLeaf` only after the existing terminal condition has been handled, as both search functions do.
