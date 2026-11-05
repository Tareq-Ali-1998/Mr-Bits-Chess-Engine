# Kernel experiments

Start with [the application/dashboard guide](../../Mr%20Bits%20Docs/START_HERE_KERNELS_AND_DASHBOARD.md). Double-click `Launch Server.bat` in the application folder to choose a Kernel; double-click `Launch Dashboard.bat` for the database viewer.

**Use `v3.0` for the former V7 baseline.** The temporary legacy `v7` folder and launcher entry have been retired, and `v3.0` is the selected replacement. Its legal search, quiescence, move ordering and 50/50 static evaluation are unchanged. The v3.1-v3.4 controls vary only static evaluation weights. The controller-owned **100-ply** Stockfish threshold remains unchanged.

Open **Launch Server.bat** and choose **`v3.0`** to run that baseline. Stop an existing application before starting another run or changing strategy. The launcher builds matching components when needed and checks native Kernel startup before starting the bot.

Read the [family map and migration guide](VERSION_FAMILIES.md) first. Shared implementation header names and test-script filenames retain their historical names so the current family implementations and archived evidence remain traceable. Family names are the public selection identities.

| Version | Policy | Notes |
|---|---|---|
| original | Existing search | `engines/Kernel.cpp` |
| v1.0 | Your Large/top-four experiment | [README](v1.0/README.md) |
| v1.1 | Large root + Small internal ordering; keep all candidates | [README](v1.1/README.md) |
| v1.2 | Root-only cutoff: eight quiet moves plus captures/EP/promotions; no cutoff in check | [README](v1.2/README.md) |
| v2.0 | Small ordinary leaves, 0/100 blend; Small sorting from depth six; keep all moves | [README](v2.0/README.md) |
| v2.1 | Small ordering + 50/50 handcrafted/Small leaves; no candidate deletion | [README](v2.1/README.md) |
| v2.2 | Same as v2.1 plus guarded one-ply late quiet move reductions and full-depth re-search | [README](v2.2/README.md) |
| v3.0 | Independent legal generation + mate/stalemate + bounded quiescence + Small blend and quiet ordering | [README](v3.0/README.md) |
| v3.1 | V3.0 legal/tactical search, with 100% Small static evaluation | [README](v3.1/README.md) |
| v3.2 | Same v3.0 search; 0% Small / 100% handcrafted static score | [README](v3.2/README.md) |
| v3.3 | Same v3.0 search; 80% Small / 20% handcrafted static score | [README](v3.3/README.md) |
| v3.4 | Same v3.0 search; 20% Small / 80% handcrafted static score | [README](v3.4/README.md) |
| v3.6 | Large ranks every expanded candidate list; keep three; original static score | [README](v3.6/README.md) |
| v3.7 | Same Large top-three beam; 50/50 original/Small static score | [README](v3.7/README.md) |
| v3.8 | Retain all legal candidates; Small-only value, PVS re-search, bounded exact-position value cache | [README](v3.8/README.md) |
| v3.9 | V3.0's 50/50 value; Small top-ten at remaining depth 3+; generation order at depth 2 or less and in quiescence | [README](v3.9/README.md) |

Read the [three-section v2.1/v2.2 explanation](V5_V6_README.md) for the ordering/reduction pair. The versions live in `v1.0/Kernel-v1.0.cpp`, etc. The v1.x and v2.x families retain the original move-generation and terminal conventions; v2.0/v2.1/v2.2 deliberately change ordinary leaf evaluation. V2.1/v2.2 use a new shared [search core](Neural%20Search.hpp) with incremental undo guards; the earlier versions do not use it. Related disabled ordering experiments were removed from v1.1/v1.2/v2.0 to improve readability.

V3.0 deliberately changes the move-generation and terminal foundation. Its separate [position/undo](V7%20Position.hpp) and [search](V7%20Search.hpp) code generate legal moves, recognize mate/stalemate, extend tactical leaves up to six plies, and estimate whether another iteration fits the clock. It retains every supplied legal root candidate and uses no LMR or fixed top-k deletion. The older versions do not include these headers. Start with its [short guide](v3.0/README.md).

Read [How V3.0 works](v3.0/HOW_V3_0_WORKS.md) for the shared foundation. **The scoring controls are v3.0-v3.4:** 50/50, 100/0, 0/100, 80/20 and 20/80 respectively, with **Small first, handcrafted second**. Their legal generation, ordering, candidate retention, quiescence and time policy match v3.0; only static scoring changes. A 0% component is skipped in that evaluator. V3.2 still uses Small for the unchanged quiet-move ordering. V3.5 is intentionally unassigned because the existing pure-Small v3.1 already covers that duplicate. The four derivatives share [V3 Evaluation Search.hpp](V3%20Evaluation%20Search.hpp), based on the unchanged V7 search body with compile-time static-evaluation weights. [Operation counts](../Neural%20Networks/OPERATION_COUNTS.md) cover both networks and sorting `m` moves.

V3.6/V3.7 deliberately explore aggressive Large-ranked beam search, including a three-move limit in check and in expanded quiescence lists. Root limits apply to each worker's assigned subset. Their scores describe the retained tree, and discarded root moves remain visible in the reply. V3.8 explores PVS and exact static-value reuse while retaining every legal ordinary candidate. Read each version's short guide before comparing displayed depths; the variants search different trees.

V3.9 is a separate V3.0 copy. At ordinary remaining depth greater than two, Small ranks the complete candidate list and only the first ten continue; checked positions have the same limit. At depth two or less, moves retain generation order with no heuristic or neural sorting. Quiescence keeps its tactical eligibility rules and six-ply cap, but performs no sorting or top-ten filtering. Root limits remain per worker. See the [short V3.9 guide](v3.9/README.md).

## Public neural functions in every Kernel

```cpp
void SortTheMovesWithLargeNeuralNetwork(vector<int16_t>& moves);
void SortTheMovesWithSmallNeuralNetwork(vector<int16_t>& moves);
float EvaluatePositionWithSmallNeuralNetwork(
    const int8_t (&position)[8][8], const mrbits::nn::State& state);
float EvaluatePositionWithLargeNeuralNetwork(
    const int8_t (&position)[8][8], const mrbits::nn::State& state);
```

Both value functions return **White-perspective pawn units**. Their state explicitly supplies White-to-move, retained castling mask (WK1/WQ2/BK4/BQ8), and raw EP file (-1 none,0..7 a..h). The neural-leaf families convert Small's result to engine-perspective centipawns at the leaf boundary. The Large value wrapper is available in every Kernel and remains uncalled by search; adding it does not change any version's evaluation policy.

The sorters infer the moving side from source pieces, score each committed child once, restore all mutated board/counter/bitboard/score state even on exceptions, and rank White high first / Black low first. They retain all moves themselves; version policy decides any later deletion. Empty lists do not load models. Exact ties retain input order. Input must describe moves for one side at the current initialized node; full legality is not checked by the NN helper.

Weights load once per model per process, with per-thread scratch. The board is still global: do not run mutating sort calls concurrently on the same process's board. Existing worker processes have separate state. [Evaluation/sorting complexity](../Neural%20Networks/TIME_COMPLEXITY_README.md).

## Build and selection

`Launch Server.bat` discovers family folders such as `v3.6` containing `Kernel-v3.6.cpp`, with numeric major/minor ordering. It builds/selects the chosen version and updates Engine UCI if necessary before launching the existing application. The menu keeps the currently configured selection; it falls back to original when none is configured. Selection is saved in `engines/kernel-selection.json` and applies to newly started engine processes.

Normal startup also performs one offline Kernel `hello`/`quit` check before saving the selection or starting the bot. A blocked executable, timeout, bad protocol response, or failed startup stops the launch. `--prepare-only` still builds/selects without executing the Kernel; `--list` only lists choices. An earlier V2.2 startup check with App Control enabled returned `4551`; the [v2.1/v2.2 status note](V5_V6_README.md) records that historical result.

Build only, without selecting or starting games:

```powershell
# From lichess-bot-master; compile current source if needed:
& 'engines/Kernels/Build Version.bat' v1.1
```

All managed builds use C++17 and -O2. A source-hash/UTC build label, dependency hashes, compiler identity/build recipe and executable SHA256 are saved in a generated `.build.json` receipt. Unchanged builds are reused. Only the source's project include dependencies invalidate it; changing an unrelated version or a launcher description does not force a rebuild. Compatible older receipts can be validated and upgraded without recompiling; their original compilation or recovery provenance is preserved. A failed compile preserves the previous executable and stops startup. The original source is never overwritten with a variant. Existing production processes must stop before their executables can be rebuilt.

If startup reports **Could not install executable** with Windows **Access is denied**, compilation may have succeeded while replacement of the existing `.exe` failed. The builder checks replacement access before compiling, waits up to four seconds on a temporary installation lock, and reports applications using the exact target via [Windows Restart Manager](https://learn.microsoft.com/en-us/windows/win32/api/restartmanager/nf-restartmanager-rmgetlist). A listed file user is a diagnostic clue, not proof it denies replacement. Stop any running bot first. A local investigation also found McAfee Framework Host using engine files. If an application keeps a restrictive handle open, save your work and restart Windows before rebuilding. Persistent failures need the named file's permissions and protection history checked. The builder does not stop applications or change security settings. Compiler-start, executable-install, and build-receipt errors report their own operation, path, and underlying OS error.

For a mapped destination that Windows allows to be renamed but cannot overwrite directly, the installer preserves the old file as a uniquely named `.old` backup, then places the **same compiled bytes at the original executable path**. If installation fails, it restores the old path; an unsuccessful rollback reports the preserved backup location. This is a conventional [Windows replacement strategy also used by LLVM](https://www.llvm.org/doxygen/Windows_2Path_8inc_source.html). Managed builds of the same target are serialized by an OS file lock. The two renames have a brief missing-target interval; this fallback is not an atomic replacement. Backups are never executed, and no application-trust setting changes.

`MRBITS_NEURAL_WEIGHTS_DIR` can override the shared `engines/Neural Networks` installation. Missing required weights stop the launcher before the bot starts. The menu chooses executable/source policy, not which trained weight set was used historically.

V2.0/v2.1/v2.2/v3.0/v3.1/v3.2/v3.3/v3.4/v3.8/v3.9 require only Small weights. V3.2 needs Small for ordering even though its static score is 100% handcrafted. V3.6 requires only Large. V1.0/v1.1/v1.2/v3.7 require both Small and Large. Project include dependencies are followed recursively and conservatively include inactive branches. Unsupported dynamic includes fail explicitly. The controller additionally tracks SQLite's source/header, and its object cache tracks C compiler/flags, input hashes and object integrity. Helper-script hashes remain audit metadata rather than triggering unrelated rebuilds.

The deliberate Stockfish endgame handoff is configured in `Engine UCI.cpp`:

```cpp
constexpr int STOCKFISH_ENDGAME_START_PLY = 100;
```

The controller passes this setting to each `ChessState`. The class defaults to `1000000`, which effectively disables this particular handoff. The existing strict `>` boundary is preserved: 100 completed plies do not trigger it; 101 do. A ply is one player's move, so 100 plies are 50 full White/Black move pairs. Routing, endgame depth choices and database classification use the same predicate. Opening assistance and fallback behavior remain separate from this threshold. This naming migration leaves that threshold unchanged. The normal launcher prepares the controller with family-name support when a build is needed; this threshold is independent of the chosen strategy name.

## What to measure

The [local dashboard](../../database/dashboard/README.md) compares recorded configured variants, outcomes, timing, depths/nodes and failures. Root limits are per worker subset. NN ranking does not guarantee safe pruning; v1.2 can still drop important quiet checks or sacrifices. v2.0 neural leaf values are approximate; exact terminal results retain priority. No strength gain is assumed.

Tests under `engines/tests` cover shared neural state/restoration, v1.1 retention/time admission, selector mapping and launcher behavior. Run `python tests/run_kernel_policy_tests.py` from `engines` to repeat the persisted v1.2/v2.0 checks. Diagnostic proofs are saved in the lab's `diagnostics/kernel-versions-20261028` and related version diagnostic folders. No online games were launched during implementation.

For v2.1/v2.2, run `python tests/run_kernel_v56_tests.py` from `engines`. Worker replies contain per-iteration neural/LMR counters, but the current SQLite writer does not preserve these extra JSON fields; the dashboard's existing depth/node/timing/version records remain available.

For the scoring-only v3.1-v3.4 matrix, run `python tests/run_kernel_v3_evaluation_tests.py` from `engines`. `--syntax-only` compiles the four profile diagnostics without executing native code. The matrix checks the configured percentages and zero-weight component behavior while preserving the common search policy. Compilation and native behavioral checks are separate results.

For v3.0, run `python tests/run_kernel_v7_tests.py` from `engines`. It compares legal moves, perft counts, quiescence results, root/history validation, and clock estimates against independent fixtures. Extra Q counters are also available only in worker JSON/diagnostic reports until persistence is extended.

For v3.1, run `python tests/run_kernel_v8_tests.py` from `engines`. It reuses the same independent oracle and also checks the neural-only unit/sign contract and invariance to handcrafted scores.

For v3.6/v3.7/v3.8, run `python tests/run_kernel_v9_v11_tests.py` from `engines`. It checks the strict beam, evaluation contracts, PVS equivalence and cache identity/collisions. The new policy counters remain available in worker JSON and diagnostics until SQLite persistence is extended.

For v3.9, run `python tests/run_kernel_v12_tests.py` from `engines` for offline legal-move/perft, Small-ranking, depth-threshold, undo, quiescence and worker-result checks. `--syntax-only` compiles the diagnostic translation unit without creating or running an executable; it does not establish runtime correctness. The pre-migration top-ten policy compiled successfully; renamed-artifact native execution checks must be distinguished from those earlier results. No online bot is started by this runner.
