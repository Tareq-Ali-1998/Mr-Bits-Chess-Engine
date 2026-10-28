# Neural evaluators for Mr. Bits

**Trained weights, native C++17 inference, no search integration yet.**

Read the short [time-complexity README](TIME_COMPLEXITY_README.md) for separate position-evaluation and full move-sorting bounds for both networks.

Read [the illustrated lesson and results](../../Mr%20Bits%20Docs/ChatGPT%20Neural%20Network%20Lab/docs/TRAINED_NETWORKS_AND_CPP_GUIDE.md) first, then [Small](Small/README.md) or [Large](Large/README.md). These evaluators were exported from the completed `clean-10m-20261026T080646Z` run.

**28 October update:** `Kernel.cpp` now exposes two neural move-ordering functions, as requested, without calling them anywhere in search. Their shared implementation is [Move Ordering.hpp](Move%20Ordering.hpp). See [Kernel experiments](../Kernels/README.md) for the `v1`, `v2`, and `v3` copies, state-restoration contract, and build commands. Engine UCI and Stockfish integration were not edited for this addition.

```text
Neural Networks/
  common.hpp          shared features, checked loader, arithmetic kernels
  example.cpp         runnable starting-position example
  Small/
    Small.hpp         782 -> 256 -> 64 -> 1, ReLU hidden layers
    weights.bin       actual trained FP32 parameters, 867,908 bytes
    model.json        checkpoint/source hashes and exact binary layout
    README.md         usage and performance explanation
  Large/
    Large.hpp         782 -> 1024 -> 8 residual blocks -> 256 -> 1
    weights.bin       actual trained FP32 parameters, 71,432,260 bytes
    model.json        checkpoint/source hashes and exact binary layout
    README.md         usage and performance explanation
```

The `.hpp` files contain the implementation. The `.bin` files contain the learned numbers; keep them with the deployment. A 17.8-million-number C++ source initializer would slow parsing and compilation and make reviews impractical. Loading a compact file **once at startup** adds no disk access to subsequent evaluation calls. No PyTorch, Python, CUDA, or third-party C++ libraries are needed by the executable.

## Try the C++ example

In this directory, with GCC or Clang:

```bash
g++ -std=c++17 -O3 -Wall -Wextra -Wpedantic example.cpp -o nn_example
./nn_example small Small/weights.bin
./nn_example large Large/weights.bin
```

On Windows PowerShell the executable is `nn_example.exe`; run `./nn_example.exe ...`. A compiler path containing spaces must be invoked with PowerShell's `&` operator.

If the **deployment CPU** supports AVX2 and FMA, build a separate faster executable:

```bash
g++ -std=c++17 -O3 -mavx2 -mfma example.cpp -o nn_example_avx2
```

That executable requires those CPU instructions. There is no runtime instruction dispatcher. Use the default portable build for unknown machines. Keep the compile settings consistent across translation units including these headers; do not mix portable and AVX2 definitions in one executable. Avoid `-ffast-math`: the loader's finite-value checks and numerical agreement are part of this deployment contract.

## What goes into the function?

Your existing `int8_t board[8][8]` representation is supported directly: row0 is rank8; column0 is filea; low-three-bit types are `1=P, 3=N, 4=B, 5=R, 6=Q, 7=K`; bit3 means White. Supply side to move, retained castling rights, and the current raw en-passant target file explicitly. Castling bits are `1=WK, 2=WQ, 4=BK, 8=BQ`; EP is `-1` for none or `0..7` for filesa..h. Do not infer those state values only from which pieces remain on the board.

The returned `float` is **White-perspective pawns**: multiply by100 for centipawns. It is a learned estimate with a linear, unbounded output. The caller resolves checkmate, stalemate, repetition, and rule-based draws first. Neither model sees move history or halfmove clocks.

Create one model at startup, share it through `const` references, and give each worker its own `Model::Workspace`. Each evaluation uses fixed scratch storage and does not allocate memory. Optional raw-accumulator update methods are available for a later measured make/unmake integration; they are not wired into the engine today.

## Reproduce the exports

From the lab directory, using its Python environment:

```bash
python -m chesslab.export_cpp --checkpoint runs/clean-10m-20261026T080646Z/small/best.pt --output "../../engines/Neural Networks/Small/weights.bin" --reuse-existing
python -m chesslab.export_cpp --checkpoint runs/clean-10m-20261026T080646Z/large/best.pt --output "../../engines/Neural Networks/Large/weights.bin" --reuse-existing
```

The exporter accepts only these exact frozen architectures and activations. Future network variants need a matching exporter and inference implementation; they cannot silently reuse this binary ABI. Existing exports are reused only when both the source checkpoint hash and exported file hash match.

`weights.bin` is ignored by Git to keep large generated artifacts out of source history. Before publishing later, attach the trained weights/checkpoints as versioned release assets, include their `model.json` manifests, and document how to download them. Keep the current local copies: this task does not upload or publish anything.
