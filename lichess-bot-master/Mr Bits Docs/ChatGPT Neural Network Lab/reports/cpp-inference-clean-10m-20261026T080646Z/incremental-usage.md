# Incremental C++ inference check

The reproducible check is `cpp/incremental_stress.cpp`. From the lab directory, compile and run on a CPU supporting AVX2 and FMA:

```sh
g++ -std=c++17 -O3 -Wall -Wextra -Wpedantic -Werror -mavx2 -mfma \
  -I "../lichess-bot-master/engines/Neural Networkds" \
  cpp/incremental_stress.cpp -o incremental_stress
./incremental_stress \
  "../lichess-bot-master/engines/Neural Networkds/Small/weights.bin" \
  "../lichess-bot-master/engines/Neural Networkds/Large/weights.bin"
```

On Windows, use `incremental_stress.exe` as the output/executable name. Omit `-mavx2 -mfma` for the portable scalar implementation. AVX2 and FMA are enabled by compiler target flags; these headers do not select an instruction set at runtime. The final headers also passed a scalar smoke check and an AVX2 check without FMA.

`incremental-stress.json` records the actual trained-weight results. Across 256 starting-position/e2e4 make/unmake round trips, rebuilding every 16 round trips, the maximum score drift was about 0.000167 centipawns for Small and 0.000156 centipawns for Large. Each full rebuild restored the raw accumulator exactly. The test exits unsuccessfully if score drift reaches its 0.001-pawn diagnostic threshold or a rebuild differs. This is evidence for these bounded operations, not a universal numerical error bound.

Load each model once and keep it read-only. Share it through a `const` reference or pointer. The default model copy constructor copies the complete weight vector, so passing a model by value can copy about 0.87 MB for Small or 71.4 MB for Large. Returning `Small::load(...)` or `Large::load(...)` directly uses C++17 copy elision.

Each worker needs its own reusable `Small::Workspace` (2304 bytes) or `Large::Workspace` (13312 bytes). Model evaluation methods are `const`, and there is no mutable cache in the model. A workspace is scratch storage and must not be shared by concurrent evaluations. Regular `evaluate(features, workspace)` rebuilds the projection and overwrites scratch values; retaining a workspace between calls does not retain an incremental position automatically.

For incremental evaluation, call `reset_accumulator(workspace)` to copy the projection bias, then `add_feature(index, workspace)` for every active feature. Apply accurate feature additions/removals when the position changes, including side to move, castling rights and the recorded en-passant file. `evaluate_accumulator(workspace)` reads the raw pre-ReLU accumulator and leaves it unchanged. The caller tracks feature membership; adding an already present feature or removing an absent feature is not detected. Rebuild periodically to reset floating-point drift. The stress check demonstrates one bounded rebuild policy, rather than prescribing an engine search policy.

Input helpers check encodings and state flags, not full chess legality. The engine supplies legal state and resolves terminal positions, draws and history before using the network's unbounded White-perspective pawn score.
