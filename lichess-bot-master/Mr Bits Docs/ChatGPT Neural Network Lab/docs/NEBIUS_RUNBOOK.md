# ♟️ Mr. Bits: from this folder to a measured GPU experiment

**Research and operating notes checked on 23 October 2026.** This runbook prepares a Linux machine you choose. The bundle does not create a Nebius instance, spend credits, install a host driver, or start training until you run the relevant commands.

For the shortest Windows-upload-to-results sequence, begin with [START_HERE](../START_HERE.md). This runbook explains the operating details and recovery steps. Local CPU checks and Git Bash checks have been performed; **a real Nebius Linux/CUDA host has not been tested in this workspace**. GPU throughput, memory, and playing strength remain measurements for that host.

> 🟢 First prove a small run works. 🔵 Measure the complete pipeline. 🟡 Scale only after the validation report is useful.

```text
This lab's source                 Clean, versioned position shards
        │                                      │
        └──────────────────┬───────────────────┘
                           ▼
                Linux GPU machine + local venv
                           │
              doctor → benchmark → pilot
                           │
           checkpoints + curves + environment record
                           │
                    evaluate and export
```

## 1. Choose the machine and the working directory

The documented Nebius RTX PRO 6000 Blackwell Server Edition has **96 GB GDDR7**. Its single-GPU preset includes **24 vCPUs and 218 GiB system RAM**. Published platforms include `gpu-rtx6000` in `us-central1` and `gpu-rtx6000-a` in `uk-south2` / `eu-south1`; the quota and actual capacity in your account must be checked when you choose a machine. [Nebius platform catalog](https://docs.nebius.com/compute/virtual-machines/types)

Choose an NVIDIA GPU image with a working driver and standard CPython **3.11–3.14**. Python 3.12 is a practical starting choice. **Do not install another driver over the cloud image using `sudo apt` as part of this lab.** If `nvidia-smi` fails, fix the image/device configuration before training.

An H200 has a different memory/compute configuration; more VRAM does not by itself mean a shorter or cheaper run. Compare measured positions per second and total session cost for these actual models. A 96 GB GPU is already generous for them.

Upload the generated **`Mr_Bits_Neural_Lab_Upload.zip`**, rather than the entire engine repository or account-information files. The ZIP contains this lab and its prepared pilot, without a Windows virtual environment or the raw archive. Extract to a **fresh directory** so an old `.venv` cannot be accidentally reused. If your image has `unzip`, the Linux commands are:

```bash
mkdir -p "$HOME/mr-bits-upload-v1"
unzip "$HOME/Mr_Bits_Neural_Lab_Upload.zip" -d "$HOME/mr-bits-upload-v1"
cd "$HOME/mr-bits-upload-v1/ChatGPT Neural Network Lab"
python3 verify_upload.py
```

If `unzip` is absent, replace its command with `python3 -m zipfile -e "$HOME/Mr_Bits_Neural_Lab_Upload.zip" "$HOME/mr-bits-upload-v1"`; a separate archive tool is not required. Use a new extraction name if that directory already contains a previous experiment. The current directory should contain `pyproject.toml`, `chesslab/`, `configs/`, and `scripts/`. The scripts also work if the lab's absolute path contains spaces; quote paths in your own commands.

## 2. Bootstrap and record the actual environment

Run these commands **inside the lab directory**:

```bash
bash scripts/00_setup.sh --python python3
bash scripts/01_check.sh --require-cuda --strict-deps
```

The setup creates a local `.venv` with `--system-site-packages` by default, so a tested image's existing PyTorch can be reused. It keeps Torch >=2.7 when a real CUDA matrix multiplication and backward pass work. Otherwise, after checking for an NVIDIA host device, it installs the reference **Torch 2.10.0 / CUDA 12.8** wheel from PyTorch's official index. The normal requirements install does not request upgrading a working Torch. An existing `.venv` is reused.

The non-Torch direct dependencies are pinned in `requirements.txt`; the build backend is pinned in `pyproject.toml`. Torch is deliberately validated and recorded rather than forcing a downgrade of a working image build. Transitive packages still depend on the selected Python/platform, so retain `environment-pip-freeze.txt` with each session. This is a reference installation recipe, not a claim that every Python/image combination has already been tested.

The official previous-version instructions provide that wheel combination. Blackwell support was introduced with CUDA 12.8 wheels in PyTorch 2.7; the device still needs an appropriate driver and a successful real computation. RTX PRO 6000 Blackwell Server Edition is **compute capability 12.0**. The actual smoke test is more useful than trusting a package name alone. [Official installation matrix](https://pytorch.org/get-started/previous-versions/), [Blackwell support announcement](https://pytorch.org/blog/pytorch-2-7/), [NVIDIA capability list](https://developer.nvidia.com/cuda/gpus)

Setup changes packages only inside this lab's environment. If you prefer a fresh environment without inherited image packages, choose `--isolated` **when creating a new `.venv`**. It will need its own Torch installation. To work on CPU deliberately:

```bash
bash scripts/00_setup.sh --cpu --python python3
bash scripts/01_check.sh --device cpu --strict-deps
```

CPU success checks the software path; it does not validate a GPU you have not run on. A GPU-equipped Torch build can also execute this CPU check.

The doctor runs FP32 forward/backward/AdamW computation and, when the actual device supports it, a BF16 autocast matrix multiplication with backward/optimizer steps. Setup also uses `--strict-deps`, which verifies pinned direct-dependency versions, the NumPy/Torch bridge, legal-move library, compression round trip, headless PNG plotting, and a TensorBoard event write. A plain doctor command remains useful for CPU development when optional monitoring packages have not been installed; it warns that those integrations were not validated. It writes:

- `diagnostics/environment.json`: versions, actual device/capability, memory, and check results.
- `diagnostics/environment-pip-freeze.txt`: installed Python package versions.

It runs `nvidia-smi` if present and handles its absence gracefully. It does not dump environment variables or read account credentials. The doctor has a tiny workload; its elapsed time is **not a model-training benchmark**.

For direct Python commands later, activate the environment:

```bash
source .venv/bin/activate
```

The numbered Bash wrappers already select `.venv/bin/python`; they do not depend on activation. `CHESSLAB_PYTHON` can explicitly choose another interpreter for the wrappers. The setup interpreter is selected separately with `--python` or `CHESSLAB_BOOTSTRAP_PYTHON`.

## 3. Prepare reusable data before leaving a GPU idle

Preparation is mainly parsing, legal-position checks, selection, deduplication, and disk I/O. It does not need a GPU. Process on your local machine or a CPU machine when that saves paid GPU time, then copy the resulting dataset directory with its manifest intact. If preparing on the GPU machine is convenient, include that running time in the bill.

**For the first session, prefer the already prepared `data/local-100k` artifact supplied with this work.** Transfer that directory with its manifest rather than uploading the multi-gigabyte raw archive. It contains 100,000 accepted positions: 89,995 train, 4,979 validation, and 5,026 test. It is a bounded-prefix pilot; use it to check the complete training path before treating it as a representative chess benchmark. Prepared data is intentionally ignored by source Git and must be copied separately when sharing this lab.

With the existing official archive already available:

```bash
bash scripts/02_prepare.sh "/path/to/lichess_db_eval.jsonl.zst" data/pilot
```

This wrapper proposes a bounded pilot: at most **100,000 accepted positions**, scanning at most **2,000,000 source records**, selecting depth **20–80** and at least **1,000 kilo-nodes**. A kilo-node is 1,000 nodes; this threshold therefore means 1,000,000 searched nodes. These are experiment settings, not a guarantee that 100,000 records will survive.

Pass explicit preparation options to change the limits or sampling method:

```bash
bash scripts/02_prepare.sh "/path/to/archive.jsonl.zst" data/pilot --sampling reservoir
```

Reservoir sampling within a bounded prefix is still sampling **that scanned prefix**, not the whole archive. For a representative release, deliberately scan/sample across the intended corpus, record the policy, and inspect coverage. Reading a compressed stream is normally faster and needs less temporary disk than expanding the entire archive first. Preparing the raw data once also avoids reparsing FEN on every training epoch.

If you need a fresh archive, the optional downloader requires an explicit flag:

```bash
bash scripts/download_data.sh --download "/data/lichess_db_eval.jsonl.zst"
```

It uses resumable `curl`, writes to `.partial`, moves the completed file into place, and records its URL, byte count, local SHA-256, and timestamp. Completed destination files are preserved. The public archive can change between releases; its HTTP version validators are recorded before downloading, and a later resume is refused if the source changed or cannot be verified. Weak ETags alone are insufficient for byte-range recovery; the script needs a strong ETag or a matching Last-Modified validator. Preserve the old partial file and choose a new destination when validation fails. A locally computed checksum identifies your file; compare with the publisher's checksum when available for independent verification. No archive is downloaded by setup. [Official Lichess data and format](https://database.lichess.org/#evals)

Only one process may download to a destination at a time. A `.download.lock` directory records its PID and is removed on normal exit/interruption. After a hard VM/process kill, inspect that PID and confirm no matching downloader remains before removing its `pid` file and the empty lock directory. Keep the `.partial` and `.partial.source.json` files together for a verified resume.

Use a **new output directory for a new dataset release**. Keep raw archive provenance and prepared-data fingerprints alongside the experiment. Separate dataset names such as `pilot-v1` and `scale-v1` make it easier to understand what a checkpoint learned from.

## 4. Benchmark first, then train the two models explicitly

After transferring `data/local-100k` and passing the GPU doctor:

```bash
bash scripts/07_benchmark.sh small data/local-100k benchmarks/small-throughput.json --device cuda --batches 1024 4096 16384 --steps 30
bash scripts/07_benchmark.sh large data/local-100k benchmarks/large-throughput.json --device cuda --batches 1024 4096 16384 --steps 30
```

Inspect the benchmark output before planning a large run. Use the actual loader, forward pass, backward pass, and optimizer update. Model A and Model B need separate measurements. Warm-up/compilation, data preparation, validation, checkpointing, and startup are additional parts of the total session.

Launch the two pilot runs separately:

```bash
bash scripts/03_train.sh small data/local-100k runs/pilot-small --device cuda
bash scripts/03_train.sh large data/local-100k runs/pilot-large --device cuda
```

These wrappers select `configs/pilot_small.json` and `configs/pilot_large.json`. They do not silently select a large-data experiment. To use a full experiment configuration, invoke the trainer explicitly:

```bash
python -m chesslab.train --data data/local-100k --config configs/small.json --run runs/small-v1 --device cuda
```

The two starter models are conveniences. For an arbitrary supported configuration, use `bash scripts/08_experiment.sh CONFIG DATA RUN --device cuda`. See [the experiment guide](EXPERIMENTS.md) for configurable depth, widths, residual models, and ReLU/GELU/SiLU/tanh comparisons. Use a separate configuration and run directory for each variant; `python -m chesslab.experiments list` inspects configurations without starting training.

For a continuation, point to the existing run and its last checkpoint:

```bash
bash scripts/03_train.sh small data/local-100k runs/pilot-small --device cuda --resume runs/pilot-small/last.pt --epochs 10
```

`--epochs 10` means a cap of **ten completed epochs in total**, not ten additional epochs. Resume restores a completed-epoch boundary; a partially completed interrupted epoch is replayed. If the saved run already met early stopping, extending only the epoch cap does not reset its patience. Resume the same architecture, precision, and dataset contract; use a new experiment for intentional changes. Back up checkpoints and their manifests before making experiments depend on an interruptible machine.

## 5. Keep a long run alive and watch its progress

If `tmux` is already available, create a session:

```bash
tmux new -s chesslab
```

Inside it, enter the lab directory and run a training command. Detach with **Ctrl+B, then D**. Later reconnect with:

```bash
tmux attach -t chesslab
```

Alternatively, keep a log with `nohup`:

```bash
mkdir -p logs
nohup bash scripts/03_train.sh small data/local-100k runs/pilot-small --device cuda > logs/pilot-small.log 2>&1 &
printf '%s\n' "$!" > logs/pilot-small.pid
tail -f logs/pilot-small.log
```

`tmux` and `nohup` survive an SSH disconnect; neither survives the underlying VM being reclaimed or stopped. Resume from the last saved checkpoint after an interruption. Avoid starting the same run directory twice.

In another terminal, inspect utilization and power if exposed by the host:

```bash
watch -n 2 nvidia-smi
```

To view TensorBoard on the GPU host:

```bash
bash scripts/06_monitor.sh runs
```

It listens only at **127.0.0.1:6006**. On your own computer, open a separate SSH tunnel:

```bash
ssh -N -L 6006:127.0.0.1:6006 USER@GPU_HOST
```

Then browse `http://127.0.0.1:6006` locally. The script does not publish TensorBoard to the internet or change firewall rules.

## 6. Read memory and time numbers correctly

The starter pilot configs currently use a microbatch of **2,048**; benchmark other sizes before overriding it. The parameter/gradient/two-moment FP32 AdamW subtotal is about **3.31 MiB** for the 216,961-parameter small starter and **272.49 MiB** for the 17,858,049-parameter large starter. A custom architecture changes those counts: inspect its actual configuration rather than applying these figures to every variant. Those figures exclude active batches, saved activations, temporary workspaces, CUDA context, and allocator behavior. AMP does not halve every component.

If adopting planning ceilings of **10 GiB for small** and **30 GiB for large**, treat them as generous monitoring allocations, not measured requirements or an instruction to reserve that memory. Do not enlarge the network or batch merely to fill the GPU. Measure peak **allocated** and **reserved** memory through a real optimizer step; also check whole-device/process memory separately. The caching allocator makes these numbers differ. [PyTorch memory management](https://docs.pytorch.org/docs/stable/notes/cuda.html#memory-management)

```text
train presentations = training rows × completed epochs
train seconds       ≈ train presentations / measured positions per second
session seconds     = setup + preparation + training + validation + other running time
compute dollars     ≈ billed session hours × actual selected hourly rate
```

For example, if a prepared dataset contains **90,000 training rows**, five full epochs process **450,000 presentations**, not 450,000 unique positions. At a hypothetical measured 10,000 positions/second, the training loop would be 45 seconds; this is arithmetic, not a forecast for either model. Count actual final-batch samples when measuring throughput.

As checked on **23 October 2026**, the published RTX PRO 6000 rate is **$1.80 per GPU-hour on demand**, with dynamic spot pricing **from $0.79**. A floor is not a guaranteed rate, and preemptible capacity can be interrupted. Use the actual quote for your selected instance and region; add applicable tax, storage, and other charges. Stopping a VM ends compute charges but retained storage can still be billed. [Nebius pricing](https://docs.nebius.com/compute/resources/pricing)

## 7. Evaluate, compare, export, and finish the session

For one trained run:

```bash
bash scripts/05_evaluate.sh runs/pilot-small data/local-100k
```

It computes test metrics, renders training plots, and exports `model.ts`. Keep test results for decisions frozen before final reporting; do not use the test split as another tuning set. To compare **existing** small and large checkpoints:

```bash
bash scripts/04_compare.sh data/local-100k runs
```

The compare script **never starts training**. It expects `runs/pilot-small/best.pt` and `runs/pilot-large/best.pt`. Compare quality, throughput, actual total time, and runtime inference cost together.

Create a controlled sibling-move benchmark when a Stockfish binary is available:

```bash
python -m chesslab.teacher --data data/local-100k --split test --positions 100 --engine "/path/to/stockfish" --nodes 50000 --threads 4 --hash-mb 256 --output benchmarks/teacher.jsonl
bash scripts/05_evaluate.sh runs/pilot-small data/local-100k benchmarks/teacher.jsonl
```

The teacher command spends **CPU search time**, potentially for every legal candidate. Start small and inspect its record counts and provenance. It is not part of setup and is never launched automatically. Your Stockfish binary and its network files need to be valid on the host.

Before ending a paid session:

- Copy the run configurations, data manifest, checkpoints, plots, metrics, and environment report to persistent artifact storage you control.
- Confirm that the files you copied can be read; a checkpoint left only on ephemeral disk is not a backup.
- Stop the compute through your normal Nebius account interface when work is finished, and review retained disks separately.

The first useful result is a reproducible checkpoint with honest validation and runtime measurements. More training time is worthwhile when those measurements explain what it improves. 💙
