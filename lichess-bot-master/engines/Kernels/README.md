# Kernel experiments

The [two-page complexity guide](../Neural%20Networks/TIME_COMPLEXITY_README.md) explains the per-position and full-sorting costs of both networks.

The original source stays at `engines/Kernel.cpp`. The user requested these two new functions in that original file, with **no search call sites**:

```cpp
void SortTheMovesWithLargeNeuralNetwork(vector<int16_t>& moves);
void SortTheMovesWithSmallNeuralNetwork(vector<int16_t>& moves);
```

`v1/Kernel-v1.cpp`, `v2/Kernel-v2.cpp`, and `v3/Kernel-v3.cpp` start as **byte-identical PowerShell copies of that updated original**. No different search policy has been enabled in any version. You can now edit one version without changing the others.

## What each sorter does

1. Return immediately for an empty vector, without loading weights.
2. Load its model once per process, on its first nonempty call.
3. Commit each supplied move with the existing `MakeChanges` function.
4. Evaluate the child board with the opposite side to move, retained castling rights, and the raw EP target after a double pawn push.
5. Restore the parent board, all 64 move counters, both bitboards and both existing evaluation scores, including on exceptions.
6. Sort the stored neural scores: White high first; Black low first. Exact ties keep the input order. Keep every move.

Each move gets **one** neural evaluation. The comparator never runs a network. For `m` moves and inference cost `C`, time is `O(m*C + m log m)` and score storage is `O(m)`. A fixed 216-byte parent snapshot is captured once per call and restored after each child. Scratch buffers are reused per thread and grow only when necessary.

This is ordering, not pruning: no move is discarded. No call is installed in `Magic`, iterative deepening or any leaf evaluator. Choosing those sites and testing weighted evaluations are later experiments.

## State and concurrency contract

Supply supported moves for **one side** from the current initialized Kernel position. The moving side comes from the source pieces, not `ENGINE_COLOR`. Use the normal Kernel table initialization before calling. These helpers do not perform full chess legality validation or exact mate/draw adjudication.

No extra turn argument is required by the current API: it reads the source color of the first move, validates that all sources have that color, and gives each child the opposite side to move. For example, when the bot is White but the current search node belongs to Black, the function ranks lower White-perspective scores first. The original search's `turn` flag is engine-relative (`true` means the engine's move), so it must not be confused with a `white_to_move` flag.

Castling rights use the existing home-square piece identities and move counters. This matches positions reconstructed by the Kernel's standard-start replay. If you later add arbitrary FEN input, initialize its explicit castling rights consistently; rights cannot be recovered from board occupancy alone. EP comes from the child-producing move, so the helpers do not need to push/pop `previousMoves` while inspecting children.

The networks are immutable and cached; scratch is private to a thread. **The Kernel board itself is global.** Do not call these mutating helpers concurrently on the same process's board. The existing worker processes have separate globals. Supporting multiple simultaneous boards within one process would require a separate state-ownership change.

## Weights and compilation

The shared implementation is [`../Neural Networks/Move Ordering.hpp`](../Neural%20Networks/Move%20Ordering.hpp). Trained weights remain in `engines/Neural Networks/Small/weights.bin` and `Large/weights.bin`.

The first call searches beside the executable and its ancestors, then the working directory. To select an explicit installation, set this before the process starts:

```powershell
$env:MRBITS_NEURAL_WEIGHTS_DIR = 'C:\path\to\engines\Neural Networks'
```

Missing or corrupt weights raise an exception; no move-vector write occurs until all scores succeed. The original global state is restored if inference fails. The first successful call includes weight-loading/validation time; subsequent calls reuse the same model even if the environment variable changes.

From the `engines` directory, build an experimental executable without replacing `Kernel.exe`:

```powershell
g++ -std=c++17 -O2 -I. 'Kernels/v1/Kernel-v1.cpp' -o 'Kernels/v1/Kernel-v1.exe'
```

Or run `Kernels/Build Version.bat v1` (also accepts `v2` and `v3`). The `-I.` is necessary because version files include shared engine headers from their original location. This script only compiles; it does not launch games or select a production kernel.

## Verification

From the repository root, using the lab's Python environment:

```powershell
python 'lichess-bot-master/engines/tests/kernel_neural_ordering_test.py'
```

The script generates independent python-chess children, compares both actual networks against FP32 Python outputs, checks both moving/engine colors, and verifies state restoration, special-move flags, ties, empty input, model caching and failure paths. It runs an isolated test main, not the production engine, Stockfish, or an online game. See the [trained network guide](../../Mr%20Bits%20Docs/ChatGPT%20Neural%20Network%20Lab/docs/TRAINED_NETWORKS_AND_CPP_GUIDE.md) for the measured Small/Large accuracy and CPU cost.
