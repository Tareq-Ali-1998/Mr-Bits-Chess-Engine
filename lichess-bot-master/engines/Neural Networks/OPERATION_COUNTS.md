# 🧮 What does one neural evaluation actually cost?

<style>
body{font-family:Segoe UI,Arial,sans-serif;line-height:1.43;color:#223047}h1,h2{color:#2354a5}h3{color:#17795e}table{border-collapse:collapse;width:100%}th,td{border:1px solid #cbd5e1;padding:.32em .48em}th{background:#edf3fc}pre{white-space:pre-wrap;font-size:.86em}blockquote{border-left:4px solid #16865b;background:#edf8f1;padding:.5em .8em}.page-break{break-before:page;page-break-before:always}@media print{body{font-size:10pt;line-height:1.28}h1{font-size:18pt}h2{font-size:14pt}h3{font-size:11pt}table,pre{break-inside:avoid}}@page{size:A4;margin:15mm}
</style>

**Mr. Bits · C++ FP32 inference · verified against the current source, 31 October 2026**

> Bro, the useful answer is **about 42,624 floating-point arithmetic operations for Small**, versus **34,126,336 for Large**, at the legal-position upper bound of 38 active inputs. These are clearly defined mathematical counts, **not CPU instruction counts or measured timings**. Below is exactly what they include. 💙

## 1. The input is mostly zeros — we exploit that

```text
board[8][8] + side to move + castling rights + EP file
                    │
        scan 64 squares, sort piece-feature indices
                    │
      list of A active features out of 782 inputs
                    │
     add A weight columns to the first-layer bias
                    │
           dense hidden layers → one score
```

Let `P` be the number of pieces and `A` the number of active binary inputs:

```text
A = P + (White to move ? 1 : 0) + retained castling-right count + 1
                                                                      ↑
                                                       exactly one EP option
```

The EP option is either “none” or one of eight files. For legal chess, `P ≤ 32` and **`A ≤ 38`**. Captures and lost rights usually reduce this. Black-to-move positions omit the White-turn feature. The adapter permits a larger defensive storage capacity; that capacity is not the normal chess-piece count.

**Both the public position functions and the move sorter currently use the same board adapter.** Both scan 64 squares, sort `P` piece indices, append the flags, and validate the active list. Neither public path incrementally updates the first-layer accumulator yet, although `add_feature` / `remove_feature` APIs exist.

### Our counting convention

- One **MAC** means one multiplication plus one accumulation: conventionally **2 arithmetic operations**. FMA hardware may execute both together.
- First-layer inputs are binary: adding an active weight column costs **one addition**, with no multiplication by 1. Zero columns are skipped.
- Dense MAC counts below include the useful weighted-sum work. Mathematically, an `n`-input dot product plus its bias takes `n` multiplies and `n` adds. Biases are therefore already covered by the `2 × MAC` convention; do not add them twice.
- ReLU comparisons, copying, integer/index work, memory access, feature sorting, and the implementation's extra dot-product reductions are listed separately. They are not silently called “free.”

## 2. Small: 216,961 learned parameters 🟢

```text
782 binary inputs → 256 ReLU → 64 ReLU → 1 linear White-pawn score
```

| Stage | Arithmetic in the deployed path | Other work |
|---|---:|---:|
| Sparse input → 256 | `256 × A` additions | Copy 256 biases; 256 ReLUs |
| 256 → 64 | **16,384 MACs** | 64 biases included in MAC convention; 64 ReLUs |
| 64 → 1 | **64 MACs** | 1 bias included; no output activation |
| **Total** | **`256A + 2 × 16,448`** useful FP operations | **320 ReLUs** |

At `A=38`: **9,728 projection additions + 32,896 dense operations = 42,624**.

At `A=18`, for example, this falls to **37,504**. Small does not become proportional to piece count alone: its 16,448 dense MACs remain even in an endgame. ReLU zeros are not skipped by the later dense layers.

<div class="page-break"></div>

## 3. Large: 17,858,049 learned parameters 🟠

```text
782 → 1024 ReLU → [1024 → 1024 → add skip → ReLU] × 8
                                     │
                           → 256 ReLU → 1
```

Each block is exactly `ReLU(h + second(ReLU(first(h))))`; the second dense layer has a bias but no separate ReLU before the skip addition.

| Stage | Arithmetic in the deployed path | Other work |
|---|---:|---:|
| Sparse input → 1024 | `1024 × A` additions | Copy 1,024 biases; 1,024 ReLUs |
| 16 dense 1024 → 1024 layers | **16,777,216 MACs** | 16,384 biases included; 16,384 ReLUs across blocks |
| 8 residual skip additions | **8,192 additions** | Fused into second-layer output loop |
| 1024 → 256 | **262,144 MACs** | 256 biases included; 256 ReLUs |
| 256 → 1 | **256 MACs** | 1 bias included; linear output |
| **Total** | **`1024A + 2 × 17,039,616 + 8,192`** useful FP operations | **17,664 ReLUs** |

At `A=38`: **38,912 + 34,079,232 + 8,192 = 34,126,336**.

That is roughly **801× Small's useful arithmetic at this input size**. It is **not an 801× runtime prediction**: vector instructions, cache, bandwidth, compiler flags, and CPU all matter. Small's dense weights fit into much less memory.

### Dense first layer versus our sparse first layer

| Implementation | Small | Large |
|---|---:|---:|
| Hypothetical fully dense first-layer MACs | 200,192 | 800,768 |
| Hypothetical full-network MACs | **216,640** | **17,840,384** |
| Actual sparse first-layer additions, `A=38` | **9,728** | **38,912** |
| Actual later-layer MACs | **16,448** | **17,039,616** |

The sparse projection saves substantial Small work. In Large, the sixteen `1024²` matrices dominate anyway. **Parameter count is not the number of operations in our sparse forward pass.**

### If you want the literal loop arithmetic, too

`common.hpp::dot` keeps independent partial sums. Its final reduction adds some work beyond the mathematical minimum. For all current dense widths, which are multiples of 32:

| Source path | One `n`-input row, including bias |
|---|---|
| Non-AVX four-accumulator loop | `n` multiplies + **`n+4` adds** |
| AVX2 path, counted as scalar lanes | `n` multiplies + **`n+32` adds** |

There are **65 dense output rows for Small** and **16,641 for Large**, excluding the sparse projection. Thus the source-level arithmetic counts at `A=38`, including the reductions, are:

| Count convention | Small | Large |
|---|---:|---:|
| Useful arithmetic from the formulas above | **42,624** | **34,126,336** |
| Non-AVX source arithmetic, before compiler simplification | **42,884** | **34,192,900** |
| AVX2 scalar-lane-equivalent arithmetic | **44,704** | **34,658,848** |

The AVX2 count includes its 24 lane additions plus 7 horizontal additions per dot, and the bias. More counted lane arithmetic does not mean slower execution: a vector processes eight floats together. An optimizing compiler can change instructions or remove initial additions to zero, so **none of these tables claims an exact retired instruction count**. Core inference has no output clamp; callers can convert units, round, and clamp separately in `O(1)`.

<div class="page-break"></div>

## 4. Sorting `m` moves: multiply inference by `m`, not `m log m` ♟️

```text
validate all m moves → save parent once
     → [commit move → encode child → evaluate ONCE → restore parent] × m
     → sort cached (score, original-index, move) records → copy order back
```

The comparator uses cached scores. It never calls the network. Ties preserve the input order using the stored original index. White prefers higher White-perspective scores; Black prefers lower scores. **No candidate is discarded by these public sorter functions.**

If child `i` has `Aᵢ` active inputs, the exact useful network-arithmetic sums are:

```text
Small: 32,896m + 256 × ΣAᵢ
Large: 34,087,424m + 1024 × ΣAᵢ
```

The Large constant includes its residual additions. To include literal non-AVX reductions, add **`260m`** for Small or **`66,564m`** for Large. For the AVX2 lane convention, add **`2,080m`** or **`532,512m`**, respectively. ReLUs add **`320m`** or **`17,664m`** elementwise activation decisions, counted separately.

These illustrative totals use `Aᵢ ≤ 38` for every child, so the arithmetic column is an **upper bound for legal child positions**, not a claim that every position has 38 active inputs.

| Moves `m` | Small later MACs | Small useful FP operations ≤ | Large later MACs | Large useful FP operations ≤ |
|---:|---:|---:|---:|---:|
| 20 | 328,960 | **852,480** | 340,792,320 | **682,526,720** |
| 35 | 575,680 | **1,491,840** | 596,386,560 | **1,194,421,760** |
| 40 | 657,920 | **1,704,960** | 681,584,640 | **1,365,053,440** |

Add `O(m log m)` score comparisons, `m` board scans of 64 squares, `m` piece-index sorts, move commits, flag construction, and restoration of the fixed parent snapshot. There is no universal exact comparison count for `std::sort`; it depends on the input and library implementation. The snapshot contains board, move counters, masks, and running scores; restoring it is constant on our fixed board but involves real copying.

### The Big-O answer, without hiding the expensive constant

Let `S=64`, `P≤32`, `W` be projection width, `H` head width, and `B=8` residual blocks for Large:

```text
Csmall = O(S + P log(P+1) + A×256 + 16,448)
Clarge = O(S + P log(P+1) + A×1024 + 17,039,616)

SortSmall(m) = O(m×Csmall + m log m)
SortLarge(m) = O(m×Clarge + m log m)
```

More generally, the dense terms are `WH+H` for Small and `2BW²+WH+H` for Large. **For these fixed networks and an 8×8 board, a position evaluation is formally `O(1)` and a sorter is `O(m log m)`**. The expanded formulas are more useful for engineering. The sorter needs `O(m)` cached score storage; fixed inference scratch is additional.

### Loading and memory 📦

| Storage | Small | Large |
|---|---:|---:|
| Learned parameters, including biases | 216,961 | 17,858,049 |
| Resident FP32 weight payload | **867,844 bytes** | **71,432,196 bytes** |
| Weight file including 64-byte header | **867,908 bytes** | **71,432,260 bytes** |
| Workspace per calling thread | **2,304 bytes** | **13,312 bytes** |

First use adds `O(N)` file loading, CRC and finite-value checks for `N` parameters; cached immutable weights are then reused **per process**. Multiple worker processes have separate model instances. An empty move list returns immediately without loading; a one-move public sorting call still evaluates that move. These counts describe **one forward pass or one sorter call**, not a complete search tree.

**V7/V8 connection:** their quiet-tail ordering uses this same Small sorter, so replace `m` with the number of quiet moves actually sent to it. Tactical moves receive cheap heuristic ordering. The number of whole-search forward passes depends on the visited nodes, quiescence, clock, and ordering decisions.

Source: [Small.hpp](Small/Small.hpp), [Large.hpp](Large/Large.hpp), [common.hpp](common.hpp), [Move Ordering.hpp](Move%20Ordering.hpp). For the shorter complexity guide, see [TIME_COMPLEXITY_README.md](TIME_COMPLEXITY_README.md).
