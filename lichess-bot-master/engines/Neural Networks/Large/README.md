# ♟️ Large: the residual Mr_Bits neural evaluator

<p style="color:#7c3aed"><strong>17,858,049 learned parameters · FP32 weights · one White-perspective pawn score</strong></p>

This component deploys the **Large best checkpoint, epoch 20**, from `clean-10m-20261026T080646Z`. It is a standalone C++ evaluator alongside the engine; it does not modify or integrate itself into `Kernel.cpp`.

```text
782 → Linear(1024) → ReLU
    → 8 residual blocks at width 1024
    → Linear(256) → ReLU → Linear(1)

block(h) = ReLU(h + Linear₂(ReLU(Linear₁(h))))
```

Its recorded **FP32 held-out test MAE is 90.8242293011166 cp** across 499,321 positions, compared with Small's `117.46930382031158 cp` on the same release. That is better agreement with this filtered teacher distribution. It does not establish Elo, best-move recall, or that Large improves search after paying its higher CPU cost. No 95% move-retention claim has been measured.

## Use it

Keep `Large.hpp` with its matching exported `weights.bin`. Add the parent `Neural Networks` folder to your include search path if using this include:

```cpp
#include <cstdint>
#include "Large/Large.hpp"

// Once at startup; never reload on every position.
auto model = mrbits::nn::Large::load("Large/weights.bin");

// Keep separate scratch storage for every search thread.
mrbits::nn::Large::Workspace workspace;
mrbits::nn::State state{true, 15, -1};

// board must be your existing std::int8_t[8][8] in a8..h1 order.
// float white_pawns = model.evaluate(board, state, workspace);
```

The final line is commented because this fragment does not declare your actual board. The [full illustrated guide](../../../Mr%20Bits%20Docs/ChatGPT%20Neural%20Network%20Lab/docs/TRAINED_NETWORKS_AND_CPP_GUIDE.md) has a complete board example; substitute the Large header/class/weights path there.

The weights path is resolved relative to your process's working directory, not automatically relative to this header. Use a reliably resolved path in your application.

## Exact interface contract

`State` is `{white_to_move, castling, ep_file}`. Its retained castling bits are **WK = 1, WQ = 2, BK = 4, BQ = 8**. Its EP file is **`-1` none, `0..7` files a..h**. Obtain both from actual engine state; piece placement alone cannot tell whether a king or rook previously moved.

The board uses Kernel codes: Black pawn/knight/bishop/rook/queen/king = **`1,3,4,5,6,7`**; White adds bit 3, giving **`9,11,12,13,14,15`**. Empty is zero. Higher move-related flags do not change piece identity. This interface expects `std::int8_t[8][8]`, with `a8` at `[0][0]`; it does not accept raw compact dataset codes or an `int[8][8]` byte reinterpretation.

The output is an FP32 **White-perspective pawn score**, including when Black moves. White prefers larger scores; Black prefers smaller scores. A negamax caller can deliberately convert to side-to-move perspective. Scores are neither probabilities nor mate distances, and the final linear output is not clamped to the training target range.

The input has 768 piece-square indicators plus 14 state features, with **no clock or repetition history**. Your engine must supply legal moves and exact terminal/draw handling. This is an orthodox-chess model; no opening/middlegame/endgame specialist was trained separately in this run.

## Cost and threading

| Resource | Large |
|---|---:|
| Learned FP32 parameters | 17,858,049 |
| Parameter payload, without format header | 71,432,196 bytes, about 68.123 MiB |
| Actual `weights.bin`, including 64-byte header | 71,432,260 bytes |
| Original training `best.pt` | 214,382,535 bytes |
| Dense Linear layers | 19 |
| Original dense Linear MACs per position | 17,840,384 |
| C++ Workspace | 13,312 bytes |

The training checkpoint includes optimizer state and metadata, so its file size overstates the deployed parameter payload. Conversely, the payload is not the whole process's resident memory: add Workspace arrays, containers, code and any caller-owned copies.

The first projection uses active binary features, but the sixteen `1024×1024` residual Linear layers remain dense. Sparse input handling therefore saves only a modest fraction of Large's total arithmetic. An 82-times-larger parameter count does not translate mechanically into an 82-times-slower timing; hardware and implementation must be measured.

The local warm serial CPU measurement was **3.598 ms** portable or **2.820 ms** AVX2/FMA with prebuilt active features; adding compact-78 conversion measured **4.010 ms / 2.940 ms** respectively. Python/PyTorch's FP32 call measured **2.520 ms**, so the AVX2/FMA C++ call was about **12% slower** here. It was roughly 3,000 times Small's C++ prebuilt-feature latency. This is a substantial per-node cost, not evidence to replace every search evaluation with Large. The timed compact adapter is not the Kernel-board adapter, and search/weight loading are excluded. Maximum fresh C++/Python FP32 disagreement across both builds and 592 positions was about **0.001192 cp**. [Exact Large report](../../../Mr%20Bits%20Docs/ChatGPT%20Neural%20Network%20Lab/reports/cpp-inference-clean-10m-20261026T080646Z/large-verification.json), [benchmark scope](../../../Mr%20Bits%20Docs/ChatGPT%20Neural%20Network%20Lab/reports/cpp-inference-clean-10m-20261026T080646Z/summary.json).

A loaded model can be shared through `const` references across threads; copying the object duplicates all its weights. Every concurrent call requires its **own Workspace**. Keep board/state reads race-free too. Use compiler optimizations appropriate to the actual CPU; avoid `-ffast-math` when verifying finite checks and numerical parity.

The optional accumulator interface updates only the first projection. It requires exact changed piece/turn/castling/EP features and does not make the residual blocks incremental. FP32 add/remove cycles can drift. Save/restore a parent raw accumulator (**4,096 bytes per saved Large position**) or rebuild periodically rather than assuming exact reversible arithmetic.

## A realistic role

Large is a useful quality comparator, possible selective evaluator, and possible teacher for a later smaller student. Those roles remain hypotheses until tested. Measure complete-legal-child ranking and equal-time engine play; a neural-only throughput result does not include child construction, sorting or lost search cutoffs.

Read the [full guide](../../../Mr%20Bits%20Docs/ChatGPT%20Neural%20Network%20Lab/docs/TRAINED_NETWORKS_AND_CPP_GUIDE.md), [Large FP32 test report](../../../Mr%20Bits%20Docs/ChatGPT%20Neural%20Network%20Lab/runs/clean-10m-20261026T080646Z/large/test.json), and deployment metadata/verification reports accompanying these files. Training and validation used bfloat16 autocast; exported C++ weights and the held-out test evaluation are FP32.
