# Kernel experiments

Start with [the application/dashboard guide](../../Mr%20Bits%20Docs/START_HERE_KERNELS_AND_DASHBOARD.md). Double-click `Launch Server.bat` in the application folder to choose a Kernel; double-click `Launch Dashboard.bat` for the database viewer.

| Version | Policy | Notes |
|---|---|---|
| original | Existing search | `engines/Kernel.cpp` |
| v1 | Your Large/top-four experiment | User-owned policy remains intact |
| v2 | Large root + Small internal ordering; keep all candidates | [README](v2/README.md) |
| v3 | Root-only cutoff: eight quiet moves plus captures/EP/promotions; no cutoff in check | [README](v3/README.md) |
| v4 | Small ordinary leaves, 0/100 blend; Small sorting from depth six; keep all moves | [README](v4/README.md) |

The versions live in `v1/Kernel-v1.cpp`, etc. They share existing engine headers and trained weights. Move generation, make/undo, worker protocol and existing terminal rules remain shared in behavior; v4 deliberately changes ordinary leaf evaluation. Related disabled ordering experiments were removed only from v2/v3/v4 to improve readability.

## Public neural functions in every Kernel

```cpp
void SortTheMovesWithLargeNeuralNetwork(vector<int16_t>& moves);
void SortTheMovesWithSmallNeuralNetwork(vector<int16_t>& moves);
float EvaluatePositionWithSmallNeuralNetwork(
    const int8_t (&position)[8][8], const mrbits::nn::State& state);
float EvaluatePositionWithLargeNeuralNetwork(
    const int8_t (&position)[8][8], const mrbits::nn::State& state);
```

Both value functions return **White-perspective pawn units**. Their state explicitly supplies White-to-move, retained castling mask (WK1/WQ2/BK4/BQ8), and raw EP file (-1 none,0..7 a..h). v4 converts Small's result to engine-perspective centipawns at its leaf boundary. The Large value wrapper is available in every Kernel and remains uncalled by search; adding it does not change any version's evaluation policy.

The sorters infer the moving side from source pieces, score each committed child once, restore all mutated board/counter/bitboard/score state even on exceptions, and rank White high first / Black low first. They retain all moves themselves; version policy decides any later deletion. Empty lists do not load models. Exact ties retain input order. Input must describe moves for one side at the current initialized node; full legality is not checked by the NN helper.

Weights load once per model per process, with per-thread scratch. The board is still global: do not run mutating sort calls concurrently on the same process's board. Existing worker processes have separate state. [Evaluation/sorting complexity](../Neural%20Networks/TIME_COMPLEXITY_README.md).

## Build and selection

`Launch Server.bat` discovers positive-numbered `vN` folders containing `Kernel-vN.cpp`. It builds/selects the chosen version and updates Engine UCI if necessary before launching the existing application. The default remains original until the user chooses otherwise. Selection is saved in `engines/kernel-selection.json` and applies to newly started engine processes.

Build only, without selecting or starting games:

```powershell
# From lichess-bot-master:
& 'engines/Kernels/Build Version.bat' v2
```

All managed builds use C++17 and -O2. A source-hash/UTC build label, input hashes and executable SHA256 are saved in a generated `.build.json` receipt. Unchanged builds are reused; a failed compile preserves the previous executable and stops startup. The original source is never overwritten with a variant. Existing production processes must stop before their executables can be rebuilt.

`MRBITS_NEURAL_WEIGHTS_DIR` can override the shared `engines/Neural Networks` installation. Missing required weights stop the launcher before the bot starts. The menu chooses executable/source policy, not which trained weight set was used historically.

## What to measure

The [local dashboard](../../database/dashboard/README.md) compares recorded configured variants, outcomes, timing, depths/nodes and failures. Root limits are per worker subset. NN ranking does not guarantee safe pruning; v3 can still drop important quiet checks or sacrifices. v4 neural leaf values are approximate; exact terminal results retain priority. No strength gain is assumed.

Tests under `engines/tests` cover shared neural state/restoration, v2 retention/time admission, selector mapping and launcher behavior. Run `python tests/run_kernel_policy_tests.py` from `engines` to repeat the persisted v3/v4 checks. Diagnostic proofs are saved in the lab's `diagnostics/kernel-versions-20261028` and related version diagnostic folders. No online games were launched during implementation.
