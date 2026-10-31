# 🟩 v5 — a balanced Small-network baseline

Read the short [v5/v6 comparison](../V5_V6_README.md) first. This version begins as a copy of the original Kernel, keeping its move representation, move generation, incremental make/undo, worker protocol, and clock rules.

The idea is to give the Small network useful work while retaining every candidate and a clear comparison against v6.

| Location | v5 policy |
|---|---|
| Root and internal remaining depth 1–2 | Existing simple heuristic |
| Root and internal remaining depth 3+ | Small-network ordering if the time reserve admits it; simple heuristic otherwise |
| Ordinary leaf | 50% existing evaluation + 50% Small evaluation |
| Candidate removal | None; ordinary alpha-beta cutoffs remain |
| Late-move reductions | Disabled |

Root depth means the total iteration depth; internal depth means plies still to search. Every supplied root move receives the full requested depth, subject to the existing deadline. Each worker receives its own subset of root moves.

## Evaluation and cost

Small returns **White-perspective pawns**. Multiply by 100, change sign when the engine is Black, then blend with the existing engine-perspective centipawn score. Ordinary scores are rounded and clamped below the existing terminal threshold. The existing king-capture terminal result takes priority over the network.

Ordering requires at least `max(5, ceil(move_count / 8))` milliseconds remaining. This is an admission reserve, not a runtime guarantee; model loading and an admitted sorting batch are not interruptible. Leaf evaluation stays consistent throughout an iteration. Lists of zero or one move skip ordering and loading.

The shared [search core](../Neural%20Search.hpp) holds named constants. The Small model loads once per process. An incremental RAII undo guard restores changed state on normal returns, deadlines, and evaluation exceptions.

## What to measure

Additional worker JSON records neural ordering calls, heuristic ordering calls, neural leaves, and deadline observations per iteration. `answer.searchPolicy.counters` belongs only to the last completed iteration; an unfinished attempt remains separately marked in `perDepth`. These extra counters are not yet stored by the SQLite writer.

V5 is a full-width baseline for this evaluator, not a claim of exhaustive legal chess search. It retains the original pseudo-legal move generation, no-generated-moves handling, and terminal/draw limitations. The 50/50 blend is a testable starting point, not calibrated confidence or a promised strength gain.
