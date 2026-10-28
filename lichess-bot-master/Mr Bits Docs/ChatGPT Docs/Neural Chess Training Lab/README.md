<style>
:root { color-scheme:light dark; --lab-blue:#2563eb; --lab-green:#15803d; --lab-gold:#a16207; --lab-red:#b91c1c; }
body { max-width:1080px; margin:3rem auto; padding:0 1.4rem; font-family:Inter,Segoe UI,Arial,sans-serif; line-height:1.78; }
h1,h2,h3 { line-height:1.25; letter-spacing:-.02em; }
h1 { color:var(--lab-blue); font-size:2.6rem; }
h2 { margin-top:2.7rem; padding-bottom:.5rem; border-bottom:2px solid #64748b55; }
table { border-collapse:collapse; width:100%; margin:1.2rem 0; font-size:.94em; }
th,td { border:1px solid #64748b55; padding:.65rem .8rem; vertical-align:top; text-align:left; }
th { background:#64748b18; }
blockquote { border-left:5px solid var(--lab-blue); background:#2563eb0d; padding:.8rem 1.2rem; margin:1.4rem 0; }
pre { overflow:auto; padding:1rem; border:1px solid #64748b44; border-radius:9px; background:#64748b0d; line-height:1.45; }
code { font-family:Cascadia Code,Consolas,monospace; font-size:.91em; }
a { color:var(--lab-blue); }
.good { color:var(--lab-green); font-weight:700; }
.note { color:var(--lab-blue); font-weight:700; }
.watch { color:var(--lab-gold); font-weight:700; }
.critical { color:var(--lab-red); font-weight:700; }
@media (prefers-color-scheme:dark) { :root { --lab-blue:#93c5fd; --lab-green:#86efac; --lab-gold:#fde68a; --lab-red:#fca5a5; } }
@media print { body { max-width:none; margin:0; font-size:10.5pt; } h2,h3 { break-after:avoid; } pre,blockquote { break-inside:avoid; } }
</style>

# ♟️🧠 The Mr. Bits Neural Chess Training Lab

**Lab 01: one position in, one evaluation out**  
**For:** Tareq Ali · **Prepared:** 22 October 2026 · **Status:** design and learning guide

<p><span class="good">🟢 Real local data inspected</span> · <span class="note">🔵 Two exact model designs checked</span> · <span class="watch">🟡 GPU time and accuracy need a pilot</span> · <span class="critical">🔴 No promise of perfect chess</span></p>

> **Bro, this is our practical lab notebook.** It defines exactly what we will feed the networks, what they should predict, how the two designs differ, and how we will train and compare them on your proposed 96 GB Blackwell GPU.
>
> We can calculate tensor shapes, parameter counts, and parts of memory use now. We cannot honestly know the trained accuracy or real GPU runtime until we run the pilot. The aim is a reliable, useful evaluator whose improvements we can demonstrate.

This lab currently contains this guide. It does **not** contain a completed trainer, trained checkpoint, or GPU benchmark. A tiny synthetic CPU forward/backward check verified the two model definitions; no dataset training or cloud job was run. Your engine, original dataset, and earlier documents remain unchanged. `Claude Docs` was not read.

The colored styling is optional for HTML conversion. Every diagram uses plain text and works without extra rendering plugins.

## 🧭 Read this in order

1. [The whole experiment on one page](#overview)
2. [What we actually downloaded and inspected](#data)
3. [The exact input: 782 numbers](#input)
4. [The exact output: one signed score](#output)
5. [Where accuracy comes from](#accuracy)
6. [Model A: the normal network](#small)
7. [Model B: the deeper network](#deep)
8. [Activations, loss, and optimizer](#recipe)
9. [Samples, batches, epochs, and fair comparisons](#schedule)
10. [GPU, RAM, and disk memory](#memory)
11. [Time and cost estimates](#time)
12. [Our step-by-step training session](#session)
13. [How the network helps the engine](#engine)
14. [Lab organization and completion checklist](#organization)

<a id="overview"></a>

## 1. 🗺️ The whole experiment on one page

```text
YOUR EXISTING ARCHIVE                 OUR FUTURE TRAINING

lichess_db_eval.jsonl.zst
          │
          ▼
 read positions + saved teacher scores
          │
          ▼
 validate → select labels → deduplicate → split
          │
          ▼
 position encoding: 782 values ───────► Model A / Model B
 target: one White score ────────────► loss + weight updates
                                             │
                                             ▼
                                      trained checkpoint
                                             │
                                    validate + export
                                             │
                                             ▼
                                     C++ neural evaluator
                                             │
                                             ▼
                                      Mr. Bits search
```

| Question | Our initial decision |
|---|---|
| What is the task? | Predict a strong teacher's searched evaluation from a position |
| Does the network output a move? | No; it outputs one number |
| What is one input? | A vector of 782 features |
| What is one output? | A White-perspective, pawn-like score |
| How many models? | Two: small dense and deeper residual |
| How do we obtain labels? | Select existing Stockfish analyses from your archive |
| Where do we train? | Proposed Nebius RTX PRO 6000 Blackwell, 96 GB VRAM |
| Where do we evaluate during play? | Eventually inside C++, with weights loaded once |
| What do we try first in search? | Shadow/offline checks, then move ordering |
| How do we choose the winner? | Held-out prediction quality, inference cost, tactics, and equal-time engine results |

“More layers” is one experiment. It is not our definition of quality.

<a id="data"></a>

## 2. 📦 What we actually downloaded and inspected

Your [original archive](../../ChatGPT%20Neural%20Network%20Lab/Chess%20Dataset/lichess_db_eval.jsonl.zst) occupies **22,423,777,007 bytes**, or **22.42 GB decimal**. We can stream it without unpacking the full contents onto disk.

The publisher currently describes **416,442,401 positions**, flattened into **1,003,347,246 rows** in the Hugging Face representation. That larger row count includes multiple candidate lines/analyses for the same board; it is not a billion independent position-value targets. The card describes Stockfish browser analyses at varied search budgets and identifies CC0 licensing. [Official dataset card](https://huggingface.co/datasets/Lichess/chess-position-evaluations/raw/main/README.md)

**The published count is not a count we verified by scanning your entire file.** How many examples survive our final preparation rules remains unknown until preprocessing finishes.

### A bounded local quality check

For this guide, we read the first **10,000 records**, selected the maximum `(depth, knodes)` analysis, and inspected its first PV. This was a read-only prefix audit using Python 3.14.2 and python-chess 1.10.0.

| Check | What we observed in that prefix |
|---|---:|
| Parsed JSON records | 10,000 |
| Missing/invalid required record fields | 0 |
| Four-field FENs | 10,000 |
| Selected ordinary centipawn labels | 7,866 |
| Selected mate labels | 2,134 |
| Passed orthodox `python-chess.is_valid()` checks | 9,956 |
| Flagged by those checks | 44 |
| Structurally valid centipawn examples | 7,823 |
| Valid cp examples also passing proposed `depth ≥ 18` and `knodes ≥ 100` filters | 7,643 |

Most flagged cases involved castling rights; others involved piece/pawn counts. Quarantine and inspect such records instead of silently changing the board to fit the label. A basic validity check does not prove historical reachability.

**This is a prefix, not a random sample.** Do not estimate the entire dataset's mate percentage, rejection rate, or usable count from these numbers.

The prefix also contained **997 selected analyses with reported depth 245**. We have not established why those records have that value. It is a reason to audit unusual metadata, not proof of exhaustive 245-ply search or automatically excellent labels.

### What makes a label useful?

```text
useful training example
   = correctly interpreted position
   + correctly selected teacher target
   + consistent units and viewpoint
   + adequate search evidence
   + relevant coverage
```

Depth/node thresholds are candidate quality controls, not a correctness certificate. We will audit their effect on phase and tactical coverage before treating the resulting subset as a training release.

### Our first record becomes a concrete training example

```text
Position:
7r/1p3k2/p1bPR3/5p2/2B2P1p/8/PP4P1/3K4 b - -

Selected analysis: depth 46, knodes 4,189,972
First candidate:   f7g7 ...
Teacher label:    cp = 69
Training target:  y = +0.69, White's perspective
```

The official scalar-selection guidance is highest-depth analysis, then its first PV. We use node count as a documented tie-breaker. If that selected PV reports mate, route the position to a separate mate collection; do not replace it with an older finite score. [Lichess format and selection guidance](https://database.lichess.org/#evals)

### The preparation rules for this lab

1. Keep the raw archive unchanged.
2. Validate the record and supported standard-chess state.
3. Select one suitable parent-position target as described above.
4. Separate finite-cp and mate records.
5. Preserve depth, nodes, source, and rejection reasons as metadata.
6. Review unusual values and compare a small audit set with a controlled teacher.
7. Deduplicate visible inputs and split without duplicate/transformed positions crossing boundaries.
8. Sample across material, side, score range, and tactical situations.

The future PV, teacher move, and depth are **not neural inputs** in this board-only model. Otherwise the model could depend on information it will not have when your engine asks for a score.

<a id="input"></a>

## 3. 🔢 The exact input: 782 numbers

We will encode each position as a vector. Almost all its entries are 0 or 1.

```text
                  782 features
┌──────────────────────────────┬──────┬──────────┬──────────────┐
│ 12 piece planes × 64 squares│ turn │ castling │ en passant   │
│             768             │  1   │    4     │      9       │
└──────────────────────────────┴──────┴──────────┴──────────────┘
```

### Piece planes: 768 values

Use this exact plane order for feature version `board782_v1`:

| Plane | Piece | Plane | Piece |
|---:|---|---:|---|
| 0 | White pawn | 6 | Black pawn |
| 1 | White knight | 7 | Black knight |
| 2 | White bishop | 8 | Black bishop |
| 3 | White rook | 9 | Black rook |
| 4 | White queen | 10 | Black queen |
| 5 | White king | 11 | Black king |

Within each plane, scan **a8 to h8, then a7 to h7, down to a1 to h1**. Square index 0 is a8; square index 63 is h1.

```text
square_index = row_from_top × 8 + file_from_a
feature_index = plane_index × 64 + square_index
```

An empty square activates no piece plane. A White rook on e6 activates plane 3, square 20: feature **212**. A Black rook on h8 activates plane 9, square 7: feature **583**.

Implementation detail to remember later: python-chess numbers squares from a1, while this contract starts at a8. For its standard square IDs, use `lab_square = python_chess_square ^ 56` before computing the feature index. Test the corner squares explicitly.

### Auxiliary flags: 14 values

| Feature index | Meaning | Encoding |
|---|---|---|
| 768 | Side to move | 1 = White, 0 = Black |
| 769 | White kingside castling right | 1 if retained |
| 770 | White queenside castling right | 1 if retained |
| 771 | Black kingside castling right | 1 if retained |
| 772 | Black queenside castling right | 1 if retained |
| 773 | No en-passant target | One-hot option |
| 774–781 | En-passant file a–h | Remaining one-hot options |

Exactly one of the nine EP entries is active. A yes/no EP flag would lose which file matters. In standard chess, the target rank follows from the side to move.

For `board782_v1`, preserve the **recorded FEN target file**, even if no fully legal en-passant capture currently exists; `-` activates “none.” Apply the same convention during C++ inference. Do not let a FEN round-trip silently normalize this field differently between training and deployment.

Castling rights mean retained rights, not “castling is legal immediately.” The engine still checks occupancy, attacks, and legality.

### The actual tensor shapes

```text
One board's piece view:        [12, 8, 8]
Flattened pieces:             [768]
Pieces + 14 flags:            [782]

One training batch:          [4096, 782]
Network predictions:         [4096, 1]
Teacher targets:             [4096, 1]
```

Keep predictions and targets the same shape. Mixing `[batch,1]` with `[batch]` can create an unintended broadcast comparison.

For our first archive example, the 15 pieces activate 15 of the 768 piece entries. Black to move gives turn `0`, all four castling flags are `0`, and EP-none is `1`. The paired output target is `[+0.69]`. That is one complete input/target sample, with no future moves supplied to the network.

### What this version deliberately leaves to the engine

The four-field source FEN does not provide the real halfmove clock or repetition history. We must not pretend those fields are known. Version 1 predicts an approximate board-state evaluation; exact draw and terminal handling remains in the engine.

A later feature version can add a known halfmove value plus a known/unknown mask. It changes the input dimension and export contract. We will not silently change a 782-feature model into another schema.

<a id="output"></a>

## 4. 🎯 The exact output: one signed score

```text
fθ(position_features) → one real number

 +0.69 = predicted White advantage, in our teacher's pawn-like units
 -1.20 = predicted Black advantage
  0.00 = approximately equal according to the model
```

The target conversion is `cp_white / 100`. The dataset's score viewpoint is White, regardless of whose turn it is. [Official score convention](https://raw.githubusercontent.com/lichess-org/api/master/doc/specs/schemas/CloudEval.yaml)

These are teacher-style evaluations, not literal material counts. `+9` need not mean exactly one extra queen, and `0` does not prove a forced draw. [Stockfish evaluation interpretation](https://official-stockfish.github.io/docs/stockfish-wiki/Stockfish-FAQ.html#interpretation-of-the-stockfish-evaluation)

For the first local example, the target is `+0.69`. If an untrained or intermediate model predicted `+0.42`, the error would be `−0.27`. That prediction is illustrative, not a result we measured.

### The last layer stays linear

The output must allow both negative and positive values. We therefore use:

- No final ReLU, which would forbid negative scores.
- No final sigmoid, which would constrain the score to 0–1.
- No softmax, because we are not choosing one output class here.

Hidden ReLUs do not prevent a negative final score: the last layer has signed weights and a bias.

Mate labels stay separately typed. `mate: 15` is not a `+15`-pawn regression target. Exact legality, checkmate, stalemate, and rule-based draws must be handled outside the approximate network.

<a id="accuracy"></a>

## 5. 💡 Where accuracy comes from

The network's shape provides the capacity to learn. Its useful accuracy comes from several parts working together:

```text
teacher search and evaluation
            │
            ▼
consistent, relevant labels
            │
            ▼
correct features + enough diverse examples
            │
            ▼
training that improves unseen-position predictions
            │
            ▼
validated inference + useful search integration
```

The teacher searched before these labels were saved. Our network learns to approximate those expensive judgments in a direct forward pass. It does not perform that teacher search on every prediction.

It will still make mistakes. Some teacher labels also contain search-horizon or version-dependent errors. More layers or epochs cannot repair a flipped sign, conflicting PV labels, or missing tactical coverage automatically.

### What “accuracy” means for a number

This is regression, so a single classification-style percentage is not enough.

| Measurement | Beginner meaning |
|---|---|
| MAE in centipawns | Average distance between prediction and teacher score |
| Fraction within 25/50/100 cp | How often the prediction is close under each tolerance |
| Error by phase and score range | Whether a good average hides a weak endgame or tactical subset |
| Best/near-best recall@5 | Whether useful candidate moves appear in the model's first five |
| Teacher-relative regret | How much teacher value we lose by following the selected candidate |
| Equal-time engine results | Whether the full system actually plays better under a clock |

The tolerances above are proposed reporting bands, not promised results. We will compare with simple references such as a constant-zero predictor and a correct basic material evaluator before celebrating a low training loss.

Recall@5 and candidate regret need a separate benchmark with teacher evaluations of the legal children, using consistent search budgets and score perspective. A single parent-position score does not provide all those answers; neither does a partial list of saved PVs. We must construct or obtain that benchmark before claiming move-ranking quality.

No trained accuracy figure exists for these two models yet.

<a id="small"></a>

## 6. 🟢 Model A: the normal network

**Purpose:** an understandable first evaluator and a fast comparison point.

```text
       INPUT             HIDDEN 1          HIDDEN 2          OUTPUT
     782 values          256 units          64 units          1 score
         │                   │                 │                │
         └── Linear ──► ReLU └── Linear ─► ReLU └── Linear ─────►│

                 782 → 256 → 64 → 1
```

It has **two hidden layers and three Linear layers including the output**.

| Transformation | Parameters, including biases |
|---|---:|
| 782 → 256 | 200,448 |
| 256 → 64 | 16,448 |
| 64 → 1 | 65 |
| **Total** | **216,961** |

For each Linear layer, parameters equal `inputs × outputs + outputs`. The last term is the bias vector.

ReLU means `max(0,z)`. It is simple and inexpensive; it gives successive layers nonlinear interactions instead of collapsing into one linear formula. [PyTorch ReLU definition](https://docs.pytorch.org/docs/stable/generated/torch.nn.ReLU.html)

This is a starting choice, not a claim that ReLU universally beats every alternative on chess. Keep it consistent across our first two designs so we do not change every variable at once.

<a id="deep"></a>

## 7. 🔵 Model B: the deeper network

**Purpose:** test whether more capacity and a deeper computation improve unseen-position judgments enough to justify their cost.

```text
782 input values
       │
Linear 782 → 512 + ReLU
       │
       ▼
┌─────────────────────────────┐
│ Residual block, width 512   │
│                             │
│ h ─► Linear ─► ReLU ─► Linear ─┐
│ │                             + ─► ReLU ─► new h
│ └─────────────────────────────┘
└─────────────────────────────┘
       │
       │ SIX residual blocks TOTAL
       ▼
Linear 512 → 128 + ReLU
       │
Linear 128 → 1
       │
       ▼
one White-perspective score
```

One block computes:

```text
F(h) = Linear512→512(ReLU(Linear512→512(h)))
new_h = ReLU(h + F(h))
```

The shortcut lets a block learn a correction to existing features. Residual learning is an established idea for training deeper networks; this particular normalization-free chess MLP is our proposed adaptation, not an architecture whose chess strength is established by the original paper. [Original residual-learning paper](https://arxiv.org/abs/1512.03385)

### Exact layer and parameter counts

| Part | Linear layers | Parameters |
|---|---:|---:|
| Input projection, 782 → 512 | 1 | 400,896 |
| Six blocks, each with two 512 → 512 layers | 12 | 3,151,872 |
| Head, 512 → 128 | 1 | 65,664 |
| Output, 128 → 1 | 1 | 129 |
| **Total** | **15** | **3,618,561** |

That means **14 hidden transformations plus one output layer**, with **14 ReLU applications**. The input itself is not counted as a trainable layer.

### The comparison at a glance

| Property | Model A | Model B |
|---|---:|---:|
| Hidden transformations | 2 | 14 |
| Trainable parameters | 216,961 | 3,618,561 |
| FP32 weights alone | 0.83 MiB | 13.80 MiB |
| Dense matrix MACs per position | 216,640 | 3,611,776 |
| Output | One signed score | One signed score |

MAC means multiply-accumulate. These counts omit biases, activations, and shortcut additions. B has about **16.7×** the dense arithmetic, but that does not predict an exact runtime multiplier.

B changes width, depth, and shortcuts together. We are comparing two model designs, not proving the isolated effect of depth. A deeper model with lower prediction error may still be a worse per-node engine evaluator if it consumes too much search time.

Both definitions passed a synthetic CPU batch-of-eight forward/backward check with finite outputs/gradients and output shape `[8,1]`, under the locally installed PyTorch 2.10.0 CPU build. That confirms wiring and counts, not learning or GPU performance.

<a id="recipe"></a>

## 8. 🧪 Activations, loss, and optimizer

Think of training as repeating three actions: **predict → measure the error → adjust the weights**. The weights start untrained; the optimizer changes them using the examples.

### The first recipe

| Setting | Our starting proposal | Why start here? |
|---|---|---|
| Hidden activation | ReLU | Simple, inexpensive nonlinear computation |
| Output activation | None: a linear output | A score must allow both positive and negative values |
| Loss | Huber, `delta = 1.0` in pawn units | Smooth treatment of small errors, less influence from very large errors than squared error |
| Optimizer | AdamW | A practical adaptive optimizer for the first experiments |
| Learning rate | `0.0003` | An initial value to validate, not a universal optimum |
| AdamW settings | `betas=(0.9,0.999)`, `eps=1e-8`, `weight_decay=0.0001` | Explicit settings so runs can be reproduced |
| Batch size | 4,096 positions | A moderate starting batch; benchmark before increasing it |
| Precision | FP32 reference; then benchmark BF16 autocast | Establish correctness before optimizing throughput |
| Normalization / dropout | Neither in the first comparison | Keep the initial recipe understandable; add them only if evidence warrants it |
| Seed | `20261022` for the first run | Repeatable data selection and initialization, within the framework's determinism limits |

These are **our proposed hyperparameters**, not PyTorch defaults or a proven best chess recipe. In particular, specify AdamW's weight decay explicitly; the documented default is different. [AdamW reference](https://docs.pytorch.org/docs/stable/generated/torch.optim.AdamW.html)

### What the loss means

Let `e = predicted_score − target_score`. With our proposed Huber threshold:

```text
                 { 0.5 × e²       when |e| ≤ 1 pawn
Huber(error)  =  {
                 { |e| − 0.5      when |e| > 1 pawn
```

A 0.10-pawn error is treated differently from a 10-pawn error. The loss gives the optimizer a signal for learning; it is **not** itself an engine rating or the percentage of correct positions. [Huber loss definition](https://docs.pytorch.org/docs/stable/generated/torch.nn.HuberLoss.html)

For an initial finite-cp experiment, we can **clip training targets to −15 through +15 pawns** and record that choice in the model metadata. This limits extreme labels' influence but merges different decisive scores. The linear network output remains unbounded. Report both clipped-target metrics and unmodified teacher errors in score buckets so clipping cannot hide poor behavior. Mate records remain separate.

We will shuffle training examples, keep the last partial batch, and validate after each epoch. Start with a constant learning rate. Select the checkpoint with the lowest **validation Huber loss under the frozen target contract**; a strict decrease counts as improvement. Stop after three consecutive epochs without improvement, within each stage's epoch cap. If training is unstable or stalls, inspect the data and gradients first; a small learning-rate comparison such as `0.0001` versus `0.0003` is a controlled next experiment.

BF16 is a numeric representation, not a different architecture. Autocast can use lower precision for suitable operations while others remain FP32. It does **not** halve all training memory. Validate finite losses and held-out quality against the FP32 reference. [PyTorch mixed-precision recipe](https://docs.pytorch.org/tutorials/recipes/recipes/amp_recipe.html)

<a id="schedule"></a>

## 9. 🔁 Samples, batches, epochs, and fair comparisons

Four words make the training plan much easier to understand:

| Word | Plain meaning |
|---|---|
| Sample | One accepted position and its selected teacher score |
| Batch | A group processed before one optimizer update |
| Epoch | One pass over the training split |
| Checkpoint | Saved model weights and the information needed to resume or evaluate them |

```text
One accepted dataset
          │
          ├── 90% TRAIN ──► predictions → loss → weight updates
          │
          ├──  5% VALID ──► choose settings and checkpoint
          │
          └──  5% TEST  ──► final report after decisions are frozen

Validation and test labels never update the weights.
```

### How many samples and epochs?

These are **proposed accepted unique-position totals after cleaning**, not verified counts available in the archive. The table uses exact 90/5/5 counts for planning; actual grouped splits may vary slightly.

| Stage | Accepted total | Train / validation / test | Epoch cap | Updates per epoch at batch 4,096 |
|---|---:|---|---:|---:|
| Wiring check | 1,000 | 900 / 50 / 50 | A few diagnostic steps | 1 for one full training pass |
| Pilot | 100,000 | 90,000 / 5,000 / 5,000 | 5 | 22 |
| First real comparison | 1,000,000 | 900,000 / 50,000 / 50,000 | 10 | 220 |
| Scale if useful | 10,000,000 | 9,000,000 / 500,000 / 500,000 | 5 | 2,198 |
| Optional later scale | 50,000,000 | 45,000,000 / 2,500,000 / 2,500,000 | 3 | 10,987 |

The calculation is `ceil(training_positions / batch_size)`. Epoch caps are budgets, not predictions of convergence. We may stop earlier. The tiny wiring split cannot establish chess quality.

The rows are separate sizing examples, not instructions to reshuffle held-out positions into training at each stage. For serious cross-scale comparisons, reserve an additional **fixed 50,000-position final benchmark**, excluded from every stage's training and validation. It sits outside the table's totals. Use that same benchmark only after the compared runs and choices are frozen; changing stage-specific test sizes must not change the shared final comparison.

For example, the one-million-position stage uses **900,000 training positions**. Ten epochs mean **9,000,000 presentations of those positions**, not nine million unique positions. It produces at most **2,200 optimizer updates**. The ten-million-position stage at five epochs produces 45 million presentations and 10,990 updates.

For the wiring check, deliberately overfit one tiny training batch: loss should fall substantially. That is a debugging tool. A model that memorizes a batch has not demonstrated generalization.

### Prevent accidental answer leakage

Deduplicate by the actual encoded position before splitting. If the same visible input has conflicting labels, select or reconcile them with an explicit rule; do not let it appear on both sides of the evaluation.

Keep transformed copies of a position in the same split. If we later train on parent/child pairs for ranking, split their connected position groups together or purge overlaps. Game-level grouping is preferable when provenance exists, but this position archive does not supply a complete game history for each record. Exact deduplication cannot eliminate all similarity between nearby chess positions.

Do not use the first million archive records as our final representative benchmark. A prefix is useful for debugging. Training and evaluation releases should sample across the stream/shards and audit score, material, phase, side-to-move, and tactical coverage. Keep a separate naturally sampled test set if we rebalance the training distribution.

### Compare the two models honestly

Start both from fresh weights, using the same prepared splits, targets, epoch budget, and checkpoint rule. Give them comparable tuning opportunities. Report model quality **and** training time; equal epochs do not imply equal compute. Later compare a fixed compute budget as a separate experiment.

Repeat promising final configurations with three seeds and report their spread. Keep one final test set untouched across scaling stages; otherwise comparisons become difficult to interpret. During play, compare engine versions at equal wall-clock time with paired openings and enough games to report uncertainty.

For this lab's first experiment, use one general evaluator. If it works, compare phase-specific models against it using the same rules. Four models create four training and deployment problems before we know whether specialization helps.

<a id="memory"></a>

## 10. 💾 GPU memory, system RAM, and disk are different budgets

```text
DISK                         SYSTEM RAM                     GPU VRAM
raw archive + clean shards → loader + decoded batches     → active batch
checkpoints + reports         temporary shuffle buffers      model + gradients
                                                            optimizer + activations

We stream batches. The whole dataset does not live on the GPU.
```

### Your proposed machine

Nebius documents the RTX PRO 6000 Blackwell Server Edition with **96 GB GDDR7 VRAM**, including a single-GPU preset with **24 vCPUs and 218 GiB of system RAM**. Availability and account quota still need checking when we start. [Nebius instance types](https://docs.nebius.com/compute/virtual-machines/types)

The two proposed networks are small relative to that capacity. The useful question is how quickly the whole training pipeline runs, including reading and decoding data. Do not make a network enormous merely to fill the GPU.

### Calculated model memory

For ordinary FP32 AdamW with two moment buffers, the main persistent training tensors are weights, gradients, and two optimizer states: approximately **16 bytes per parameter** after the states have been initialized. This excludes temporary optimizer workspace and framework overhead.

| Calculated component | Model A | Model B |
|---|---:|---:|
| FP32 weights only, `4 × parameters` | 0.83 MiB | 13.80 MiB |
| Weights + gradients + two FP32 moments | 3.31 MiB | 55.21 MiB |
| FP32 input batch `[4096,782]` | 12.22 MiB | 12.22 MiB |
| One output tensor per Linear layer, summed for illustration | 5.02 MiB | 106.02 MiB |

**The last row is a shape-based illustration, not the saved-activation total or a measured peak.** Autograd also saves tensors needed for derivatives; shortcuts, activations, precision casts, optimizer implementation, CUDA context, and allocator behavior affect actual memory. Do not add these rows and call the result a guaranteed GPU requirement.

We will measure peak allocated/reserved GPU memory after warm-up, including a real optimizer step because AdamW initializes states lazily. PyTorch's tensor allocation, its allocator reservation, and the figure displayed by `nvidia-smi` describe different things. [CUDA memory management](https://docs.pytorch.org/docs/stable/notes/cuda.html#memory-management)

### Why we should store compact records

Expanded FP32 input features alone require `782 × 4 = 3,128 bytes` per position. Ten million positions therefore occupy **31.28 GB decimal**, before labels and other metadata.

A possible compact layout could target about **64 bytes per position** using packed piece information, flags, score, and quality fields. That is a design estimate, not a description of an existing format in this repository.

| Accepted positions | Hypothetical 64-byte records | Expanded FP32 features alone |
|---:|---:|---:|
| 100,000 | 6.4 MB | 312.8 MB |
| 1 million | 64 MB | 3.128 GB |
| 10 million | 640 MB | 31.28 GB |
| 50 million | 3.2 GB | 156.4 GB |

These figures exclude indexes, file/container overhead, labels where stated, logs, and checkpoints. Pack on disk and expand only the batches we need. Avoid keeping millions of Python objects in RAM when a compact array or columnar representation will do.

<a id="time"></a>

## 11. ⏱️ Time and cost: a useful estimate needs a measured speed

We have **no measured training throughput on your proposed GPU**. The synthetic CPU check cannot predict it. Preprocessing, loading, validation, checkpointing, and training each need separate timings.

```text
training presentations = accepted TRAIN positions × epochs actually completed
training seconds       = training presentations / measured positions per second
total billed time      = setup + preparation + training + validation + other running time
```

The following are deliberately **hypothetical throughput scenarios**, not promises for either network. Measure A and B separately.

| Stage at its full cap | Training presentations | If 1,000 positions/s | If 10,000 positions/s |
|---|---:|---:|---:|
| 100k pilot, 5 epochs | 450,000 | 7.5 minutes | 45 seconds |
| 1M comparison, 10 epochs | 9,000,000 | 2.5 hours | 15 minutes |
| 10M scale, 5 epochs | 45,000,000 | 12.5 hours | 1.25 hours |
| 50M optional, 3 epochs | 135,000,000 | 37.5 hours | 3.75 hours |

The short scenarios can be dominated by startup or validation. These figures cover the training loop at a sustained rate, not the complete session. They do not estimate how long the raw 22.42 GB archive takes to parse, validate, deduplicate, and rewrite.

As checked for this guide, Nebius lists **$1.80 per GPU-hour on demand**, with spot pricing **from $0.79** and subject to availability/change. Confirm the full instance configuration, storage, and current quote before launch; spot can be interrupted. [Nebius pricing](https://docs.nebius.com/compute/resources/pricing)

At the illustrative $1.80 rate, a **1.25-hour** training loop costs **$2.25** in GPU charges. Two models taking that long cost $4.50; three seeds for each cost $13.50. Add setup, validation, preparation done on that instance, and applicable storage/other charges. This example is arithmetic, not a complete training budget or a claim that either model will finish in 1.25 hours.

Our first spending decision should follow a short benchmark. A GPU waiting for a slow parser is still billed. Prepare reusable clean shards, monitor loader wait time, and shut down compute when the session is finished.

<a id="session"></a>

## 12. 🛠️ Our future training session, step by step

This is the sequence we will implement together. No cloud instance or training job was created for this document.

| Step | What we do | Evidence required before continuing |
|---|---|---|
| 1. Freeze the contract | Record feature order, score sign, units, label-selection rule, and data version | Hand-checked positions encode exactly as expected |
| 2. Prepare a tiny clean set | Separate mate/invalid records and retain quality metadata | Record counts and rejection reasons reconcile |
| 3. Build the trainer | Implement the two definitions and save run configurations | Forward/backward, finite losses, tiny-batch overfit check |
| 4. Check the GPU environment | Verify actual device, compatible CUDA/PyTorch build, memory, and kernels | Small real GPU training step succeeds |
| 5. Benchmark 5–10 minutes | Warm up; measure full loader + training, utilization, and peak memory | Stable positions/s for each model, plus a session estimate |
| 6. Run the 100k pilot | Train both; inspect learning curves and held-out errors | Improvement over simple baselines without sign/shape mistakes |
| 7. Run the 1M comparison | Freeze evaluation and compare best checkpoints | Phase/score-bucket metrics, inference timing, reproducible artifacts |
| 8. Scale selectively | Increase data or revise architecture according to evidence | Benefits justify extra training and inference cost |
| 9. Export and compare | Reproduce Python outputs in a small C++ evaluator | Cross-language output agreement within a specified tolerance |
| 10. Test the engine | Shadow scores, then move ordering, then controlled search experiments | Legal behavior, tactics, and equal-time game results |

NVIDIA lists this RTX PRO 6000 under **compute capability 12.0**. We should use an image/build explicitly compatible with the actual Blackwell device and run a real kernel check. A locally installed CPU-only PyTorch build cannot use the rented GPU. [NVIDIA CUDA GPU list](https://developer.nvidia.com/cuda/gpus)

For timing, include data loading and optimizer updates in the measured interval. CUDA work is asynchronous, so use appropriate synchronization/events. Record both training-loop throughput and whole-run time. Monitor temperature/power/utilization if available, but judge the pipeline by measured output rather than the GPU's advertised peak arithmetic.

Every checkpoint should travel with a manifest containing its architecture, `board782_v1`, target units/sign, clipping policy, data/split fingerprints, seed, software versions, optimizer settings, and validation metrics. Save optimizer state for resumable runs. We need to know what a weight file means months later.

<a id="engine"></a>

## 13. ♟️ How this helps Mr. Bits without gambling the search

Training on the GPU and playing on the CPU are different workloads. A large batch can make training efficient while a single-position evaluator is expensive inside a search tree.

```text
Position
   │
   ▼
Generate LEGAL moves
   │
   ▼
Make each candidate → evaluate resulting position
   │
   ▼
Order candidates using neural scores + existing search information
   │
   ▼
Search with alpha-beta and your existing correctness rules
   │
   ▼
Measure: better ordering? fewer nodes? stronger play at equal time?
```

With our White-perspective output, White generally prefers higher child scores and Black lower ones. If a negamax implementation expects side-to-move scores, convert the sign consistently at the evaluator boundary. Checkmate and rule-based draws need explicit engine handling.

**Start by changing the order in which moves are searched.** A top-five guess can miss a quiet defense, sacrifice, or forced move. A static learned score is not a proof that the other legal moves are bad. Keep full-search verification and tactical safeguards while testing any later reductions or pruning.

Also measure the cost of scoring every child. Better ordering is valuable only if it repays that evaluation cost. Model B may be more useful offline, near the top of the tree, or as a teacher for a smaller evaluator. Model A is smaller, but even its roughly 217k dense MACs per position require a real CPU benchmark at engine workloads.

Load the weights once inside the process. Avoid launching a separate program or writing per-position files in the search hot path. Export only after Python/C++ feature encoding and output agreement are verified; inference speed cannot rescue a reversed score sign.

Later, an NNUE-style design could exploit sparse piece features and incremental updates after moves. That requires designing the accumulator and update rules; the dense models described here do not automatically become efficiently updatable because their inputs are sparse. An evaluator also learns a statistical approximation of searched teacher scores; it does not reproduce the teacher's entire search inside a forward pass.

For phase specialization, first measure the general model's errors by material/phase. If endgame performance is weak, compare a phase-aware model or specialist head before training four independent networks. A specialist ensemble needs defined routing/blending, enough data per phase, consistent score calibration, and a measured inference budget.

<a id="organization"></a>

## 14. 📚 Lab organization and completion checklist

**Only this README is part of the new lab today.** This is a proposed future layout, not a list of files already implemented:

```text
ChatGPT Docs/
└── Neural Chess Training Lab/
    ├── README.md                 ← this guide, present now
    ├── configs/                  ← future experiment settings
    ├── data_manifests/           ← future fingerprints and quality reports
    ├── prepare_data.py           ← future streaming preparation
    ├── features.py               ← future exact input encoder
    ├── models.py                 ← future Model A and Model B
    ├── train.py                  ← future reproducible trainer
    ├── evaluate.py               ← future held-out analysis
    ├── export.py                 ← future deployment conversion
    └── reports/                  ← future curves, metrics, benchmark notes

Large datasets and checkpoints: separate artifact storage, outside source Git.
```

The previous [engineering review](../Mr_Bits_Independent_Engineering_Review.md) and [neural research blueprint](../Mr_Bits_Neural_Chess_Research_and_Training_Blueprint.md) give broader context. This lab fixes one concrete first experiment so we can move from research to measured results.

### What counts as a successful first release?

- [ ] One reproducible clean dataset release with counts, coverage, provenance, and rejection reasons.
- [ ] Frozen feature/target contracts and isolated train/validation/test splits.
- [ ] Two trained checkpoints with complete configurations and learning curves.
- [ ] Held-out error reports, simple-baseline comparisons, and phase/score breakdowns.
- [ ] Actual GPU throughput, peak memory, wall time, and cost records.
- [ ] CPU inference benchmarks and Python/C++ numerical agreement.
- [ ] Controlled engine tests showing whether the model helps at equal time.
- [ ] A model card describing what worked, what failed, and supported use.

> **Bro, the exciting part is that we already have the expensive ingredient: saved teacher analysis.** Our job is to turn it into clean examples, train a model that generalizes, and prove that its predictions help your search. The 96 GB GPU gives us room to experiment; careful measurement tells us which experiment deserves to become part of Mr. Bits. 💙♟️
