# Kernel experiments

Start with [the application/dashboard guide](../../Mr%20Bits%20Docs/START_HERE_KERNELS_AND_DASHBOARD.md). Double-click `Launch Server.bat` in the application folder to choose a Kernel; double-click `Launch Dashboard.bat` for the database viewer.

| Version | Policy | Notes |
|---|---|---|
| original | Existing search | `engines/Kernel.cpp` |
| v1 | Your Large/top-four experiment | User-owned policy remains intact |
| v2 | Large root + Small internal ordering; keep all candidates | [README](v2/README.md) |
| v3 | Root-only cutoff: eight quiet moves plus captures/EP/promotions; no cutoff in check | [README](v3/README.md) |
| v4 | Small ordinary leaves, 0/100 blend; Small sorting from depth six; keep all moves | [README](v4/README.md) |
| v5 | Small ordering + 50/50 handcrafted/Small leaves; no candidate deletion | [README](v5/README.md) |
| v6 | Same as v5 plus guarded one-ply late quiet move reductions and full-depth re-search | [README](v6/README.md) |
| v7 | Independent legal generation + mate/stalemate + bounded quiescence + Small blend and quiet ordering | [README](v7/README.md) |
| v8 | V7 legal/tactical search, with 100% Small static evaluation | [README](v8/README.md) |
| v9 | Large ranks every expanded candidate list; keep three; original static score | [README](v9/README.md) |
| v10 | Same Large top-three beam; 50/50 original/Small static score | [README](v10/README.md) |
| v11 | Retain all legal candidates; Small-only value, PVS re-search, bounded exact-position value cache | [README](v11/README.md) |

Read the [three-section v5/v6 explanation](V5_V6_README.md) for the ordering/reduction pair. The versions live in `v1/Kernel-v1.cpp`, etc. V1–v6 retain the original move-generation and terminal conventions; v4/v5/v6 deliberately change ordinary leaf evaluation. V5/v6 use a new shared [search core](Neural%20Search.hpp) with incremental undo guards; the earlier versions do not use it. Related disabled ordering experiments were removed from v2/v3/v4 to improve readability.

V7 deliberately changes the move-generation and terminal foundation. Its separate [position/undo](V7%20Position.hpp) and [search](V7%20Search.hpp) code generate legal moves, recognize mate/stalemate, extend tactical leaves up to six plies, and estimate whether another iteration fits the clock. It retains every supplied legal root candidate and uses no LMR or fixed top-k deletion. The older versions do not include these headers. Start with its [short guide](v7/README.md).

Read [How V7 works](v7/HOW_V7_WORKS.md) for a five-part illustrated explanation. [V8](v8/README.md) retains that foundation and isolates the position-score choice: 100% Small instead of V7's 50/50 blend. It reuses V7's position helper and has a separate [search policy](V8%20Search.hpp). [Numerical operation counts](../Neural%20Networks/OPERATION_COUNTS.md) cover both trained networks and sorting `m` moves.

V9/V10 deliberately explore aggressive Large-ranked beam search, including a three-move limit in check and in expanded quiescence lists. Root limits apply to each worker's assigned subset. Their scores describe the retained tree, and discarded root moves remain visible in the reply. V11 explores PVS and exact static-value reuse while retaining every legal ordinary candidate. Read each version's short guide before comparing displayed depths; the variants search different trees.

## Public neural functions in every Kernel

```cpp
void SortTheMovesWithLargeNeuralNetwork(vector<int16_t>& moves);
void SortTheMovesWithSmallNeuralNetwork(vector<int16_t>& moves);
float EvaluatePositionWithSmallNeuralNetwork(
    const int8_t (&position)[8][8], const mrbits::nn::State& state);
float EvaluatePositionWithLargeNeuralNetwork(
    const int8_t (&position)[8][8], const mrbits::nn::State& state);
```

Both value functions return **White-perspective pawn units**. Their state explicitly supplies White-to-move, retained castling mask (WK1/WQ2/BK4/BQ8), and raw EP file (-1 none,0..7 a..h). v4–v8 convert Small's result to engine-perspective centipawns at the leaf boundary. The Large value wrapper is available in every Kernel and remains uncalled by search; adding it does not change any version's evaluation policy.

The sorters infer the moving side from source pieces, score each committed child once, restore all mutated board/counter/bitboard/score state even on exceptions, and rank White high first / Black low first. They retain all moves themselves; version policy decides any later deletion. Empty lists do not load models. Exact ties retain input order. Input must describe moves for one side at the current initialized node; full legality is not checked by the NN helper.

Weights load once per model per process, with per-thread scratch. The board is still global: do not run mutating sort calls concurrently on the same process's board. Existing worker processes have separate state. [Evaluation/sorting complexity](../Neural%20Networks/TIME_COMPLEXITY_README.md).

## Build and selection

`Launch Server.bat` discovers positive-numbered `vN` folders containing `Kernel-vN.cpp`. It builds/selects the chosen version and updates Engine UCI if necessary before launching the existing application. The default remains original until the user chooses otherwise. Selection is saved in `engines/kernel-selection.json` and applies to newly started engine processes.

Normal startup also performs one offline Kernel `hello`/`quit` check before saving the selection or starting the bot. A blocked executable, timeout, bad protocol response, or failed startup stops the launch. `--prepare-only` still builds/selects without executing the Kernel; `--list` only lists choices. The latest v6 executable is currently blocked by Windows Application Control (`4551`); see the [v5/v6 status note](V5_V6_README.md).

Build only, without selecting or starting games:

```powershell
# From lichess-bot-master:
& 'engines/Kernels/Build Version.bat' v2
```

All managed builds use C++17 and -O2. A source-hash/UTC build label, input hashes and executable SHA256 are saved in a generated `.build.json` receipt. Unchanged builds are reused; a failed compile preserves the previous executable and stops startup. The original source is never overwritten with a variant. Existing production processes must stop before their executables can be rebuilt.

If startup reports **Could not install executable** with Windows **Access is denied**, compilation may have succeeded while replacement of the existing `.exe` failed. Stop any running bot first. A background application can also hold the file; a local investigation identified McAfee Framework Host holding `Engine UCI.exe`. Save your work, restart Windows to release outstanding handles, then run `Launch Server.bat` and choose the version again. If it persists, inspect the named file's permissions and the security application's event history. Compiler-start, executable-install, and build-receipt errors now report their own operation, path, and underlying OS error.

`MRBITS_NEURAL_WEIGHTS_DIR` can override the shared `engines/Neural Networks` installation. Missing required weights stop the launcher before the bot starts. The menu chooses executable/source policy, not which trained weight set was used historically.

V4/v5/v6/v7/v8/v11 require only Small weights. V9 requires only Large. V1/v2/v3/v10 require both Small and Large. The builder fingerprints shared headers under `engines`, `Neural Networks`, and `Kernels`, so edits to the new shared search code invalidate cached builds.

## What to measure

The [local dashboard](../../database/dashboard/README.md) compares recorded configured variants, outcomes, timing, depths/nodes and failures. Root limits are per worker subset. NN ranking does not guarantee safe pruning; v3 can still drop important quiet checks or sacrifices. v4 neural leaf values are approximate; exact terminal results retain priority. No strength gain is assumed.

Tests under `engines/tests` cover shared neural state/restoration, v2 retention/time admission, selector mapping and launcher behavior. Run `python tests/run_kernel_policy_tests.py` from `engines` to repeat the persisted v3/v4 checks. Diagnostic proofs are saved in the lab's `diagnostics/kernel-versions-20261028` and related version diagnostic folders. No online games were launched during implementation.

For v5/v6, run `python tests/run_kernel_v56_tests.py` from `engines`. Worker replies contain per-iteration neural/LMR counters, but the current SQLite writer does not preserve these extra JSON fields; the dashboard's existing depth/node/timing/version records remain available.

For v7, run `python tests/run_kernel_v7_tests.py` from `engines`. It compares legal moves, perft counts, quiescence results, root/history validation, and clock estimates against independent fixtures. Extra Q counters are also available only in worker JSON/diagnostic reports until persistence is extended.

For v8, run `python tests/run_kernel_v8_tests.py` from `engines`. It reuses the same independent oracle and also checks the neural-only unit/sign contract and invariance to handcrafted scores.

For v9/v10/v11, run `python tests/run_kernel_v9_v11_tests.py` from `engines`. It checks the strict beam, evaluation contracts, PVS equivalence and cache identity/collisions. The new policy counters remain available in worker JSON and diagnostics until SQLite persistence is extended.
