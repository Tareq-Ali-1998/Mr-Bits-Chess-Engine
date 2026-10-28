# ⏱️ Neural evaluation and move sorting: the actual complexity

<style>
body{font-family:Segoe UI,Arial,sans-serif;line-height:1.45;max-width:1000px;margin:auto}h1,h2{color:#2456a6}table{border-collapse:collapse;width:100%}th,td{border:1px solid #bbb;padding:.35em .5em;text-align:left}blockquote{border-left:4px solid #16865b;padding:.4em .8em;background:#edf8f1}pre{white-space:pre-wrap;font-size:.9em}@media print{body{font-size:10pt;line-height:1.28}h1{font-size:18pt}h2{font-size:13pt}.page-break{break-before:page;page-break-before:always}pre,table{break-inside:avoid}}@page{size:A4;margin:15mm}
</style>

**Mr. Bits · Current C++ implementation · 28 October 2026**

> Bro, both evaluators are formally **O(1) for our fixed networks on an 8×8 board**. That does not mean equal speed: Small and Large perform very different amounts of work. These expanded formulas show what that constant contains. 💙

## 1. Evaluating one position 🧠

| Symbol | Meaning |
|---|---|
| `S` | Board squares: **64** |
| `P` | Occupied squares/pieces: at most **32 in legal chess** |
| `A` | Active binary inputs: `P + White-turn flag + retained castling flags + 1 EP option`; at most **38 for legal positions** |
| `W`, `H` | Projection width and final hidden width |
| `B` | Residual blocks: **8** for Large |

Our mathematical input has 782 features, but almost all are zero. The C++ adapter scans the board, sorts the `P` piece-feature indices, and appends state flags: **`O(S + P log(P+1))`**. The first layer then adds only the `A` active weight columns: **`O(A×W)`**. Later layers are dense, including when ReLU produces zeros.

### 🟢 Small: `782 → 256 → 64 → 1`

Using `Ws=256`, `Hs=64`, its complete board-to-score bound is:

```text
Csmall = O(S + P log(P+1) + A×Ws + Ws×Hs + Hs)
       = O(S + P log(P+1) + A×256 + 16,448)
```

The sparse projection performs `A×256` additions. The remaining layers perform **`256×64 + 64 = 16,448` multiply-accumulates (MACs)**. With `A=38`, the first projection adds **9,728** weight values. Biases, feature validation, resets and ReLUs add lower-order work covered by the bound.

### 🟠 Large: `782 → 1024 → 8 residual blocks → 256 → 1`

Each block has **two dense `1024×1024` matrices**, plus its residual addition and ReLUs. Using `Wl=1024`, `Hl=256`:

```text
Clarge = O(S + P log(P+1) + A×Wl + 2B×Wl² + Wl×Hl + Hl)
       = O(S + P log(P+1) + A×1024 + 17,039,616)
```

After the sparse projection, there are **`16×1024² + 1024×256 + 256 = 17,039,616` MACs**. At `A=38`, the projection adds **38,912** values. The residual/bias/activation terms are lower order here. These counts distinguish additions from MACs; they are not exact CPU instruction counts.

**Why no `782×W` term?** The deployed first layer skips zero inputs. A fully dense implementation would perform **216,640 MACs for Small** or **17,840,384 for Large**, excluding biases and activations. Our current sorter rebuilds the sparse projection for each child; it does **not** use incremental accumulator updates yet.

<div class="page-break"></div>

## 2. Sorting one complete move list ♟️

Let **`m = moves.size()`**. Both public functions follow this workflow:

```text
validate moves → save parent once → [commit → evaluate → restore] × m
               → sort cached scores → write ordered moves back
```

Each move gets **one** evaluation. The comparator only compares stored scores and input indices for ties, so inference is multiplied by `m`, not by `m log m`. Validation and writing the result each cost `O(m)`. Applying a move and deriving its flags cost `O(1)`; restoring the current 216-byte parent snapshot also costs `O(1)` on our fixed board.

**Which turn?** The vector-only functions infer the moving color from the first move's source piece and validate that every move has that color. White sorts higher scores first; Black sorts lower scores first. The child receives the opposite side to move. `ENGINE_COLOR` identifies the bot, not necessarily the side moving at a recursive node; it is not used to choose this ordering direction.

| Full sorting call | Time complexity, after loading weights |
|---|---|
| Small network | **`O(m×Csmall + m log m)`** |
| Large network | **`O(m×Clarge + m log m)`** |

With the architecture terms expanded, using maximum `P` and `A` across the children:

```text
Small: O(m×[S + P log(P+1) + A×Ws + Ws×Hs + Hs] + m log m)
Large: O(m×[S + P log(P+1) + A×Wl + 2B×Wl² + Wl×Hl + Hl] + m log m)
```

Parent snapshot/restore contributes `O(m×S)` when parameterizing board size; it is already covered by each formula's board-scan term. More precisely, differing child costs contribute `Σ C(child)` instead of `m×Cmax`.

**For fixed networks, both sorters simplify to `O(m log m)`**, with a substantial linear evaluation term hidden in that notation. In practical move lists, Large's dense evaluation work can dominate sorting. For illustration, 40 child evaluations perform **657,920 post-projection MACs with Small**, versus **681,584,640 with Large**, before counting projections and other work. This is not a measured runtime ratio.

### Startup, empty lists and memory 📦

- **Empty list:** `O(1)` return, with no model loading. **One move:** still evaluated once.
- **First nonempty call:** adds **`O(N)`** loading/CRC/finite-value validation for that model's `N` parameters, plus filesystem lookup. Models are then cached **per process**; weights are not read for every position.
- **Extra score storage:** `O(m)` for a fresh call; the thread-local buffer retains capacity for the largest list seen. Inference scratch is fixed below, plus the fixed parent snapshot.

| Resident storage | Small | Large |
|---|---:|---:|
| Parameters `N` | 216,961 | 17,858,049 |
| FP32 weights | 867,844 bytes | 71,432,196 bytes |
| Workspace per calling thread | 2,304 bytes | 13,312 bytes |

AVX2/FMA, caches and memory bandwidth change execution time, **not these Big-O classes** on fixed hardware. Training sample counts and epochs do not enter inference complexity. A forward pass does no chess-tree search; these formulas cover **one position or one move list**, not the whole alpha-beta tree.

Verified against [Small.hpp](Small/Small.hpp), [Large.hpp](Large/Large.hpp), [common.hpp](common.hpp) and [Move Ordering.hpp](Move%20Ordering.hpp). See the [full guide](../../Mr%20Bits%20Docs/ChatGPT%20Neural%20Network%20Lab/docs/TRAINED_NETWORKS_AND_CPP_GUIDE.md) for measured CPU timings.
