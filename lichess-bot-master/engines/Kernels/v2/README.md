# Kernel v2: order-only baseline

Derived from the current user-edited v1. Only the neural move-ordering and candidate-deletion regions change; related commented-out ordering experiments are removed. Move generation, make/unmake, leaf evaluation, alpha-beta, iterative deepening and worker messaging keep their existing implementations.

| Location | Ordering |
| --- | --- |
| Root search depth 2–3 | Existing simple heuristic |
| Root search depth 4+ | Existing heuristic, then Large when the time guard admits it |
| Internal remaining depth 3+ | Small when admitted; existing heuristic otherwise |
| Internal remaining depth 2 | Existing simple heuristic |
| Internal remaining depth 1 | Original generation order |

Root depth is the requested iteration depth. Internal depth is the number of plies still to search at that node. Normal iterative deepening visits even root depths. Lists with fewer than two moves skip ordering and model loading.

The ordering policy deletes no candidates. Every root candidate assigned to this worker remains available to its search; the worker list is a subset distributed by the parent process, rather than the complete global legal-move list. Existing alpha-beta cutoffs remain active.

Before an NN call, the time guard requires at least `max(5 ms, 1 ms × move count)` remaining for Small or `max(100 ms, 10 ms × move count)` for Large. Fixed-depth test mode (`INT_MAX` allowed milliseconds) bypasses these reserves. These are conservative admission estimates, not calibrated runtime guarantees: shared model loading and a started scoring batch remain non-interruptible. A rejected call falls back to the simple heuristic. The shared model loader, per-thread workspace, scoring helpers and weight paths are unchanged.

This version provides a baseline for measuring search speed and playing strength. It establishes no Elo or top-k move-retention result. Compile with the engines directory on the include path; the version selector/build process is managed separately.
