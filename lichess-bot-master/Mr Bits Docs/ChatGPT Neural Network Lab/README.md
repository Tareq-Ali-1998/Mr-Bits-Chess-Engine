<style>
body{max-width:1080px;margin:2rem auto;padding:0 1.2rem;font-family:Segoe UI,Arial,sans-serif;line-height:1.7}h1,h2{color:#2563eb}h2{margin-top:2.3rem}table{border-collapse:collapse;width:100%;margin:1rem 0}th,td{border:1px solid #8886;padding:.6rem;text-align:left;vertical-align:top}blockquote{border-left:5px solid #3b82f6;padding:.5rem 1rem;background:#3b82f60d}pre{overflow:auto;padding:1rem;border:1px solid #8885;border-radius:8px;line-height:1.4}.green{color:#15803d}.gold{color:#a16207}.red{color:#b91c1c}@media(prefers-color-scheme:dark){h1,h2{color:#93c5fd}.green{color:#86efac}.gold{color:#fde68a}.red{color:#fca5a5}}
</style>

# ♟️🧠 ChatGPT Neural Network Lab

**Mr. Bits · First runnable training lab · 23 October 2026**

> Bro, this folder is the actual experiment now: prepare trustworthy examples, train two networks, watch the learning, save the results, and measure whether the best move survives in our top five or seven. 💙
>
> Your original C++ engine is unchanged. This is a separate lab, with one general evaluator per experiment and no phase-specific networks.

## Current results and C++ deployment - 27 October 2026

**The two 10-million-position runs have completed and are backed up locally.** Start with [the trained networks and C++ guide](docs/TRAINED_NETWORKS_AND_CPP_GUIDE.md) to understand their actual inputs, results, costs, and engine interfaces. The original `Kernel.cpp` remains unchanged; choosing search integration and measuring top-5/top-7 retention are separate next steps.

The raw archive now lives in **`Chess Dataset/lichess_db_eval.jsonl.zst` inside this lab**. The obsolete upload ZIP and verified download ZIP were removed after checking the extracted run files. Prepared data and all trained checkpoints remain in `data/clean-10m-20261026T080646Z/` and `runs/clean-10m-20261026T080646Z/`.

**For future server transfers, build an upload ZIP with `package_upload.py`; do not upload the whole local lab recursively.** The lab now also contains the 22.42 GB raw archive, environments, and downloaded results. The packager deliberately excludes those large local artifacts. The first-run instructions below remain useful for a new machine; no GPU instance or retraining is required to read or verify the existing C++ exports.

## 🚀 Start here: the short version

**For one complete Windows-upload-to-results sequence, follow [START_HERE.md](START_HERE.md).** The [experiment guide](docs/EXPERIMENTS.md) explains how to add more architectures/activations, and [HANDOFF.md](HANDOFF.md) preserves the work state for future sessions.

After the GPU pilot, [LONG_RUN.md](docs/LONG_RUN.md) describes the new unattended multi-million-position pipeline, source verification, SFTP-only transfer, logging and recovery. Its new launcher must be uploaded separately if you already extracted the original ZIP.

The folder includes a **real, prepared 100,000-position pilot** at `data/local-100k/`. Upload this whole folder to your Linux machine. You do **not** need to upload the 22 GB raw archive for the first run.

On the server, open a terminal in this folder:

```bash
cd '/path/to/ChatGPT Neural Network Lab'

# 1. Create a local environment and verify the actual GPU.
bash scripts/00_setup.sh
bash scripts/01_check.sh --require-cuda

# 2. Measure useful batch sizes on this particular machine.
bash scripts/07_benchmark.sh small data/local-100k benchmarks/small-batches.json \
  --device cuda --batches 1024 4096 16384 --steps 30

# 3. Train the small model. This starts a NEW run.
bash scripts/03_train.sh small data/local-100k runs/pilot-small --device cuda

# 4. Plot, evaluate, and export it.
bash scripts/05_evaluate.sh runs/pilot-small data/local-100k

# 5. Train the larger experiment separately.
bash scripts/03_train.sh large data/local-100k runs/pilot-large --device cuda
bash scripts/05_evaluate.sh runs/pilot-large data/local-100k

# 6. Compare the existing checkpoints. This command never starts training.
bash scripts/04_compare.sh data/local-100k runs
```

The scripts create artifacts under `runs/`, `benchmarks/`, and `diagnostics/`. Use `bash script.sh`; executable file permissions are not required. Paths containing spaces are supported.

The RTX PRO 6000 Blackwell **96 GB** is our starting machine. There is no evidence yet that buying more VRAM would improve these models. Nebius lists the H200 with **141 GB**; choose between machines later using measured positions/second and cost, rather than assuming capacity determines accuracy. [Official machine specifications](https://docs.nebius.com/compute/virtual-machines/types)

The setup script reuses a working CUDA PyTorch when possible; otherwise it installs the reference **PyTorch 2.10.0 / CUDA 12.8** wheel. It performs real GPU computation and does not install host drivers. Use a GPU image with an NVIDIA driver already present. [Official PyTorch installation commands](https://pytorch.org/get-started/previous-versions/#v2100)

For cloud setup, SSH, persistent disks, downloads, and troubleshooting, read the [Nebius runbook](docs/NEBIUS_RUNBOOK.md).

## 🗺️ What we built

```text
Your raw Lichess archive                     Already prepared pilot
          │                                          │
          ▼                                          │
 stream → filter → validate full PV → deduplicate     │
          │                                          │
          ▼                                          ▼
     compact, hashed train / validation / test records
                            │
              ┌─────────────┴─────────────┐
              ▼                           ▼
       SMALL evaluator             LARGE experiment
       216,961 parameters         17,858,049 parameters
              │                           │
              └─────────────┬─────────────┘
                            ▼
               loss curves + held-out metrics
                            │
                            ▼
             score ALL legal children of a position
                            │
                            ▼
                compare top 5 / 7 with a teacher
                            │
                            ▼
                  test inside Mr. Bits later
```

| Tool | What it does |
|---|---|
| `chesslab.prepare` | Streams raw records, applies the quality policy, deduplicates on disk, and writes stable splits |
| `chesslab.benchmark` | Measures disposable real training steps across batch sizes; changes no trained checkpoint |
| `chesslab.train` | Trains, validates, shows progress, logs, checkpoints, and resumes |
| `chesslab.metrics` | Reports regression errors and simple baselines on a frozen split |
| `chesslab.plot` | Writes learning curves; SVG fallback works without matplotlib |
| `chesslab.teacher` | Builds a separate complete-legal-move benchmark using an explicitly supplied Stockfish executable |
| `chesslab.rank` | Scores legal children and measures top-k recall against that benchmark |
| `chesslab.export` | Exports TorchScript and a feature/score contract after numerical checks |
| `chesslab.kernel_adapter` | Maps your existing Kernel board values to the lab's compact input; tested offline |
| `chesslab.experiments` | Creates, catalogs, and compares independent variant configurations using reusable data |

## 📦 Our first real dataset

The prepared pilot was built locally from your existing archive. It is a hash-selected subset of the accepted positions in the **first 160,000 records**. It is not a random sample of the entire archive.

| Observed result | Count |
|---|---:|
| Raw records processed | 160,000 |
| Accepted unique candidates before the 100k cap | 112,771 |
| Selected pilot positions | 100,000 |
| Training | 89,995 |
| Validation | 4,979 |
| Test | 5,026 |
| Outside the depth policy | 32,559 |
| Insufficient search nodes | 4,077 |
| Structurally invalid orthodox positions | 796 |
| Selected mate labels | 8,430 |
| Selected extreme centipawn labels | 1,367 |

Rejection categories are the **first failed check**, not overlapping diagnoses. For example, a mate position with an anomalous selected depth is counted under depth. The counts sum to the processed records.

The three `.npy` files occupy **10,800,576 bytes**. Local preparation took **11.621 seconds with six workers**; that is an observation for this bounded prefix on this computer, not a full-archive or server speed promise. Exact settings, file checksums, coverage, and the dataset fingerprint live in [the manifest](data/local-100k/manifest.json).

For a larger run, scan a broader pool before claiming representative strength. The full archive contains analyses from varied Stockfish versions and budgets; thresholds cannot make every label correct. The publisher explains the source format and recommends selecting the highest-depth analysis's first PV. [Lichess evaluation format](https://database.lichess.org/#evals)

### Our conservative default quality policy

| Check | Default behavior |
|---|---|
| Input format | Require the archive's four-field standard-chess FEN |
| Board validity | Reject unsupported/invalid orthodox states and terminal parents |
| Analysis selection | Highest depth; break ties by greater `knodes`; use its first PV only |
| Depth | Keep **20 through 80**; reject suspiciously high values as well as shallow labels |
| Search budget | Require **1,000 knodes**, meaning one million searched nodes |
| Label type | Keep finite integer cp; reject mate from this regression dataset |
| Score range | Keep **−1,500 to +1,500 cp** |
| Principal variation | Replay the **entire selected saved line legally**, including castling notation |
| Duplicates | Same visible input has one record; prefer greater depth/node evidence within the scanned pool |
| Splits | Independent deterministic position-hash buckets, approximately 90/5/5 |

**“Passes the policy” means stronger evidence, not guaranteed truth.** A valid PV can still be strategically mistaken. The archive does not supply complete version/search-history metadata for every label. We do not fall back to an older finite score when the selected analysis says mate or has disallowed metadata.

Read [how data preparation works](docs/DATA_PIPELINE.md) before changing thresholds or scaling up.

## 🔢 Exact inputs and outputs

The input contract remains **`board782_v1`**, as in the earlier notebook:

```text
                     ONE POSITION → 782 floats

 12 piece planes × 64 squares      side      castle       en passant
 ┌───────────────────────────┐     ┌─┐     ┌────────┐    ┌───────────┐
 │ 768 binary piece features │  +  │1│  +  │4 flags │ +  │9 options  │
 └───────────────────────────┘     └─┘     └────────┘    └───────────┘

 Training batch: [batch,782]         Prediction: [batch,1]
 Example target: cp=69 → +0.69       Units: White-perspective pawns
```

The twelve planes are `P,N,B,R,Q,K,p,n,b,r,q,k`, in that order. Squares run **a8 through h8, then a7 through h7, down to a1 through h1**. White to move is 1; Black is 0. Castling flags are retained rights in `K,Q,k,q` order. EP has nine one-hot options: none, then files a through h. Preserve the recorded target file even if an EP capture is not currently legal.

The compact on-disk input is **78 bytes**: 64 piece codes and the same 14 flags. The GPU expands a batch directly into 782 float features; we do not store billions of mostly zero floats.

The output is one signed number: positive favors White, negative favors Black. `+9` is a teacher-style score, not proof that a queen is physically missing. This is a numerical prediction, with no final sigmoid, ReLU, or move classification.

The source has no reliable halfmove clock or repetition history. The network cannot determine all history-dependent draws. Legality, exact terminal results, and draw rules belong to the engine. The ranking tool explicitly normalizes unsupported counters/history and handles supported terminal children outside the network.

### Compatibility with your engine

Your `Kernel.cpp` uses type codes `1 pawn, 3 knight, 4 bishop, 5 rook, 6 queen, 7 king`, with bit 3 indicating White. The lab uses contiguous codes `1..6` for White and `7..12` for Black. **The numbers must be mapped; they are not interchangeable.** Both board layouts use row 0 as rank 8.

`kernel_adapter.py` performs that mapping and validates the resulting position. It requires actual side-to-move, retained castling rights, and EP file explicitly. It does not guess missing state or infer rights from whether pieces happen to sit on their original squares. Later we will port this small contract into C++ and test numerical agreement before integration.

## 🧠 Two runnable networks

### 🟢 Small: our practical starting evaluator

```text
782 → Linear256 → ReLU → Linear64 → ReLU → Linear1

2 hidden transformations · 3 Linear layers · 216,961 parameters
```

This is the simpler model to understand, debug, and benchmark for CPU inference. Its accuracy still has to be learned and measured; its shape does not make it a strong chess player by itself.

### 🔵 Large: deliberately more capacity

```text
782 → Linear1024 → ReLU
           │
           ▼
      8 residual blocks TOTAL
      h → Linear1024 → ReLU → Linear1024 ──┐
      └────────────────────────────────────+ → ReLU
           │
           ▼
      Linear256 → ReLU → Linear1

18 hidden transformations · 19 Linear layers · 17,858,049 parameters
```

The second layer in each residual branch starts at zero, so the branch initially adds an identity correction. This is a deliberate initialization choice for our normalization-free experiment, not evidence of chess strength.

This implementation **enlarges the experimental model beyond the earlier 3.6-million-parameter design**. Checkpoint metadata and the configurations in this folder define the models we actually run.

| Property | Small | Large |
|---|---:|---:|
| Parameters | 216,961 | 17,858,049 |
| Dense MACs per position | 216,640 | 17,840,384 |
| FP32 weights alone | 0.83 MiB | 68.12 MiB |
| Weights + gradients + two FP32 AdamW moments | 3.31 MiB | 272.49 MiB |
| Hidden activation | ReLU | ReLU with residual additions |
| Output | One signed linear score | One signed linear score |

MACs omit activations, biases, and residual additions. Memory rows omit activations, workspaces, allocator reservations, and the CUDA context. They are calculated components, not peak GPU requirements.

The large model performs about **82×** the dense arithmetic. It is a research candidate; we may eventually use a successful large model offline or near the top of search rather than at every CPU search node.

## 🔁 What training actually does

```text
sample: one position + one teacher score
batch: a group used for one weight update
epoch: one pass over the training positions

For each batch:
  compact positions → GPU feature expansion → prediction
                                      │
       teacher cp / 100 ───────────────┤
                                      ▼
                                Huber error
                                      │
                                      ▼
                            gradients → AdamW update

After each epoch: validate → log → checkpoint → continue/early stop
```

Training uses **Huber loss with delta 1 pawn**, AdamW with learning rate `0.0003`, weight decay `0.0001`, and gradient-norm clipping at 1. Targets are clipped to ±15 pawns in the loss contract, although the default prepared dataset already excludes labels beyond that range. Raw cp errors are also reported so changing the preparation policy cannot hide clipped tails.

The pilot configurations use **batch 2,048 and up to five epochs**. On the bundled data, that is **44 updates per epoch**, or at most **220 updates**. Full configurations use batch 4,096 and up to 20 epochs. These are starting budgets, not promises of convergence.

The two presets are our first experiments. MLP/residual widths and depths, ReLU/GELU/SiLU/tanh activations, seeds, batches, and epoch caps are configurable. Every variant gets a new configuration/run directory and can reuse the same prepared data; see [experiments](docs/EXPERIMENTS.md).

The best checkpoint tracks the lowest observed validation Huber loss. Early-stopping patience is separate: improvement must exceed `0.0001` to reset its five-epoch counter. Weights never update from validation/test data. More detail is in the actual JSON configuration saved beside every checkpoint.

CUDA training uses **BF16 autocast**, with FP32 parameters/optimizer state and an FP32 loss. CPU training uses FP32. A GPU capability check must succeed before this recipe is used. Autocast changes suitable operation precision; it does not halve every allocation. [PyTorch automatic mixed precision](https://docs.pytorch.org/docs/stable/amp.html)

### Why a bigger batch is not automatically better

Increasing a batch from 2,048 to 16,384 makes each update use eight times more positions, but gives eight times fewer updates per epoch. Larger batches can improve throughput and reduce gradient noise; they change optimization too. Do not compare “five epochs” alone and assume the learning effort is equivalent.

`07_benchmark.sh` measures actual loader + transfer + feature expansion + forward/backward + optimizer steps. Its batch recommendation means **highest measured throughput with memory headroom**, not best accuracy. Start with the pilot batch, then compare a faster batch using validation loss and a reasonable update budget. Filling all 96 GB is not an objective.

### What you will see

In an interactive terminal, Rich shows a colored progress bar, batch loss, validation MAE, ETA, and active GPU memory. At epoch boundaries it prints a durable summary. Redirected logs remain readable.

```text
Epoch 3/5 train       ━━━━━━━━━━━━━━━  76%  loss 0.8421  GPU ... MiB
Epoch 3: train ... | val ... | MAE ... cp | ... pos/s | BEST

The numbers above illustrate the display, not a promised training result.
```

Every run saves:

| Artifact | Meaning |
|---|---|
| `config.json`, `environment.json`, `data_manifest.json` | Exactly what was run |
| `metrics.csv`, `metrics.jsonl` | Epoch curves and detailed validation measurements |
| `tensorboard/` | Live scalar events when TensorBoard is installed |
| `best.pt` | Lowest observed validation-loss checkpoint |
| `last.pt` | Last complete epoch boundary, including optimizer and random states |
| `result.json` | Final status, best epoch, and checkpoint locations |
| `curves.png` or `curves.svg` | Saved diagrams of learning |
| `test.json`, `ranking.json` | Explicit evaluation results when requested |
| `exports/model-<checkpoint-hash>.ts` | Checked export for a particular checkpoint; repeated evaluation reuses only intact matching files |

For live browser charts, in another terminal:

```bash
bash scripts/06_monitor.sh runs/pilot-small
```

Connect via the SSH tunnel in the runbook. TensorBoard binds to localhost. You can also run `python -m chesslab.plot --run runs/pilot-small` after an epoch; it draws from the saved CSV.

### Resume after a disconnect or interruption

Use `tmux` if available so an SSH disconnect does not stop training. If a process stops, resume the same run:

```bash
.venv/bin/python -m chesslab.train \
  --data data/local-100k --config configs/pilot_small.json \
  --run runs/pilot-small --device cuda \
  --resume runs/pilot-small/last.pt --epochs 15
```

`--epochs 15` means **15 total completed epochs**, not 15 additional epochs. Incomplete epoch work is discarded; resume begins at the last atomically saved complete boundary. A CPU FP32 run cannot be resumed as CUDA BF16, and changing data fingerprints or training settings is rejected. Use a new run for a new experiment. Same-device deterministic resume is tested; cross-hardware bitwise identity is not promised.

## 🎯 Our top-five / top-seven goal

There are two separate questions:

1. Does the network predict stored scalar evaluations well?
2. When we score all legal children, does a teacher-best move appear in the first five or seven?

The first does not prove the second. A parent FEN and one saved PV do not label all legal alternatives.

The lab therefore includes an independent benchmark builder. It requires a **Linux Stockfish binary you explicitly choose**; the Windows executable in your repository cannot run directly on Linux. It gives every nonterminal legal child a controlled node budget, keeps mate and terminal results typed, and checks overlap against the prepared training data. Test benchmarks exclude both training and validation positions and their candidate children.

```bash
# Start tiny: full-child search multiplies work by the number of legal moves.
.venv/bin/python -m chesslab.teacher \
  --data data/local-100k --split test --positions 20 \
  --engine /absolute/path/to/stockfish \
  --nodes 50000 --threads 4 --hash-mb 256 \
  --output benchmarks/teacher-test.jsonl

.venv/bin/python -m chesslab.rank \
  --checkpoint runs/pilot-small/best.pt \
  --benchmark benchmarks/teacher-test.jsonl \
  --output runs/pilot-small/ranking.json
```

This first modest node cap is a **workflow check**, not a definitive best-move oracle. Increase the budget, audit label stability, and use hundreds/thousands of representative positions before making a portfolio claim. Search budgets influence which move the teacher calls best.

The report separates strict teacher-best recall@1/@5/@7 from near-best recall within 25 cp, includes sample counts and Wilson 95% confidence intervals, and treats mate disagreements separately from finite cp regret. “95% recall” is an empirical target on a defined benchmark; it is not a guarantee for every chess position.

For a live position:

```bash
.venv/bin/python -m chesslab.rank \
  --checkpoint runs/pilot-small/best.pt --top 7 \
  --fen '7r/1p3k2/p1bPR3/5p2/2B2P1p/8/PP4P1/3K4 b - - 0 1'
```

The model scores resulting boards, not move IDs. White prefers larger scores; Black prefers smaller scores. All legal moves are retained in the result. For search integration, use this ordering before experimenting with selective reductions. Discarding everything below rank seven can lose the only saving move even if average recall is high.

Read the [move-ranking and teacher-benchmark guide](docs/MOVE_RANKING.md) for the exact metric definitions and limitations.

## 📈 What counts as an encouraging result?

Report raw cp MAE/RMSE, score bias, fractions within 25/50/100 cp, score-range breakdowns, and material-coverage breakdowns. The latter are diagnostics; we are still training one general model.

Compare against constant-zero and basic material baselines. Learning a low training loss while losing to material on the test split is not a finished evaluator. Move-ranking recall, CPU evaluation latency, tactical tests, and equal-time engine games will determine whether the network earns a place in the engine.

The first local CPU run and checks are recorded in [local verification](docs/LOCAL_VERIFICATION.md). GPU throughput, final strength, and the 95% goal still need server experiments.

## 🧰 Scaling up after the pilot

Use local CPU preparation or a CPU server when practical. Preparation does not use the GPU. The bundled pilot already avoids GPU idle time for the first session. For larger datasets, choose where the archive and CPU/storage bandwidth are available; a GPU VM is not inherently faster at parsing JSON.

For example, after placing the archive on the server:

```bash
# 1M selected positions from a broader bounded pool; writes a NEW directory.
bash scripts/02_prepare.sh /data/lichess_db_eval.jsonl.zst data/million \
  --max-positions 1000000 --max-records 5000000 --workers 16

# Full configuration, fresh weights, new experiment.
.venv/bin/python -m chesslab.train \
  --data data/million --config configs/small.json \
  --run runs/million-small --device cuda
```

`--max-records 0` scans the entire archive and can require substantial CPU time and disk space for the SQLite deduplication index. That is deliberately not the first default. Never compare a new dataset's metrics with an old dataset's test numbers as if the evaluation set were identical. Freeze a common independent benchmark for cross-scale comparisons.

The data files use **108 bytes per record plus small `.npy` headers**. One million is about 108 MB; ten million about 1.08 GB. The temporary SQLite index is larger and depends on the number of accepted positions in the scanned pool, before sampling. The earlier notebook's 64-byte record was a possible future packing target; this implementation keeps explicit quality metadata and keys for easier auditing.

## 🧪 Tests and boundaries

```bash
.venv/bin/python -m unittest discover -s tests -v
```

Tests cover encoding, original-Kernel piece mapping, EP/castling handling, label selection, mate/anomalous-depth rejection, full-PV legality, deduplication/splits, model shapes, metrics, epoch-boundary resume, fingerprint guards, legal-child ranking, complete benchmark validation, and TorchScript parity.

The lab is single-device. It does not launch cloud machines, send data to external services, or modify your engine. The export is an inference artifact plus a contract; production C++ integration and engine strength testing are separate next steps. Large generated artifacts are ignored by the lab's Git rules.
