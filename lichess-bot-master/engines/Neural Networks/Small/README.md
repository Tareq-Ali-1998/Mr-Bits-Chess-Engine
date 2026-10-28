# ♟️ Small: the compact Mr_Bits neural evaluator

<p style="color:#2563eb"><strong>216,961 learned parameters · FP32 weights · one White-perspective pawn score</strong></p>

This component deploys the **Small best checkpoint, epoch 20**, from `clean-10m-20261026T080646Z`. It supplies a standalone C++ evaluator; it does not modify or integrate itself into `Kernel.cpp`.

```text
782 inputs → Linear(256) → ReLU → Linear(64) → ReLU → Linear(1)
```

The checkpoint was trained on 9,001,091 positions for 20 epochs, with a separate validation split and 499,321 held-out test positions. Its recorded **FP32 test MAE is 117.46930382031158 cp**. This measures agreement with filtered Stockfish search labels, not Elo, best-move recall, or pruning safety. No 95% move-retention claim has been established.

## Use it

Include `Small.hpp` and keep its exported `weights.bin`. Add the parent `Neural Networks` directory to your include search path if using the include below. The runtime weights path is relative to your program's working directory unless you pass an absolute path.

```cpp
#include <cstdint>
#include "Small/Small.hpp"

// At startup: load once, and keep this model alive.
auto model = mrbits::nn::Small::load("Small/weights.bin");

// One reusable Workspace for each search thread.
mrbits::nn::Small::Workspace workspace;

// The existing board must be std::int8_t[8][8], a8 at [0][0].
// Supply actual current rights and recorded EP state.
mrbits::nn::State state{true, 15, -1};
// float white_pawns = model.evaluate(board, state, workspace);
```

The commented final line requires your real `board` variable. For a complete compiling board example, see the [illustrated input and C++ guide](../../../Mr%20Bits%20Docs/ChatGPT%20Neural%20Network%20Lab/docs/TRAINED_NETWORKS_AND_CPP_GUIDE.md).

`State` contains `white_to_move`, `castling`, and `ep_file`. Castling bits are **White K = 1, White Q = 2, Black K = 4, Black Q = 8**. They record retained rights, not castling legality on this turn. EP is **`-1` none, `0` file a through `7` file h**. Preserve a recorded target even if no EP capture is legal.

## Board and score contract

| Kernel cell type | Black | White |
|---|---:|---:|
| Pawn | 1 | 9 |
| Knight | 3 | 11 |
| Bishop | 4 | 12 |
| Rook | 5 | 13 |
| Queen | 6 | 14 |
| King | 7 | 15 |

Empty is zero. The lower three bits are type; bit 3 marks White; higher move-related bits do not alter the represented piece. These are **Kernel codes**, not the dataset's compact piece codes.

The returned `float` is **White-perspective pawns**: `+1.25f` favors White, `-1.25f` favors Black, independent of whose turn it is. Multiply by 100 only when the receiving search interface expects centipawns. Negate for Black only when converting deliberately to a side-to-move convention.

The 782 mathematical inputs are `12×64` binary piece-square features plus turn, four castling flags, and nine one-hot EP choices. No clock or repetition history enters the network. The engine remains responsible for legality, checkmate, stalemate and history-dependent draw rules. The model is for orthodox chess. Its finite scalar output is not an exact mate or probability prediction.

## Memory, threading and performance

FP32 parameters occupy **867,844 bytes**; the actual `weights.bin` is **867,908 bytes**, including its 64-byte format header. The original Python `best.pt` is **2,651,343 bytes**, because it also carries training metadata/state. The C++ Workspace occupies **2,304 bytes** in this implementation.

Share one loaded model through `const` references between threads, with **one Workspace per thread**. Copying a model object duplicates its weights. Avoid loading on each node, constructing temporary evaluators per position, or sharing mutable scratch arrays between threads.

The first projection sums only active binary features; later layers remain dense. The original architecture has **216,640 dense Linear MACs** per position, before activations and overhead. Actual runtime depends on the CPU, compiler, caching, input handling and build options; inspect the deployment benchmark report rather than interpreting this operation count as a timing promise. Avoid `-ffast-math` in parity-focused builds because it can change numerical behavior and finite checks.

On the local CPU, median portable C++ latency was **1.652 µs** with prebuilt active features, or **2.200 µs** including compact-78 conversion. AVX2/FMA measured **0.955 µs / 1.213 µs** respectively. Maximum fresh FP32 disagreement against Python was approximately **0.000358 cp** across the two builds and 592 verification positions. These warm serial measurements exclude startup, legal move generation and search; compact conversion is not the Kernel-board conversion. See the [exact report](../../../Mr%20Bits%20Docs/ChatGPT%20Neural%20Network%20Lab/reports/cpp-inference-clean-10m-20261026T080646Z/small-verification.json) and [shared benchmark scope](../../../Mr%20Bits%20Docs/ChatGPT%20Neural%20Network%20Lab/reports/cpp-inference-clean-10m-20261026T080646Z/summary.json).

An optional accumulator path can update the first projection for feature additions/removals. It requires every changed piece **and** turn/castling/EP feature. FP32 addition/subtraction is not perfectly reversible: save/restore the parent raw accumulator (**1,024 bytes per saved Small position**) or rebuild periodically, and test make/unmake drift before integration. The ordinary `evaluate(board, state, workspace)` path is the starting interface.

## What to try first

Use the scores to **order legal moves while preserving the complete legal move set**, then measure search time and equal-time games against your existing engine. Low average score error is insufficient evidence to discard all but five moves.

The source of truth is the [full guide](../../../Mr%20Bits%20Docs/ChatGPT%20Neural%20Network%20Lab/docs/TRAINED_NETWORKS_AND_CPP_GUIDE.md), [Small FP32 test report](../../../Mr%20Bits%20Docs/ChatGPT%20Neural%20Network%20Lab/runs/clean-10m-20261026T080646Z/small/test.json), and the export metadata and deployment verification reports accompanying these files. Training/validation used bfloat16 autocast; deployment parity should compare C++ FP32 with Python FP32.
