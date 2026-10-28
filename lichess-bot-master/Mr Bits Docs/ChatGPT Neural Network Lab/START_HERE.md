# 🚀 Tareq, start here


> **27 October update:** Both full small/large runs are complete. Read [the trained-network guide](docs/TRAINED_NETWORKS_AND_CPP_GUIDE.md) first. The raw archive is now under `Chess Dataset/` inside this lab; use the allowlisted packager below for any new upload. The original transfer ZIP was removed as requested and can be rebuilt. These instructions describe a fresh GPU session, not a required repeat of completed training.
**One path from this folder to your first GPU results. Updated 23 October 2026.**

> The platform we have discussed is **Nebius**. No instance is running on your behalf. Keep the original 22 GB archive on your computer for now: this upload includes a prepared 100k pilot and a small CPU-trained demonstration checkpoint.

## 1. Upload the prepared ZIP

The generated file is **`Mr_Bits_Neural_Lab_Upload.zip`**, beside this project folder. Its `.zip.sha256` file contains the upload checksum. The ZIP includes the source, configurations, guides, tests, pilot data, and demonstration results. It excludes your original engine, account files, raw archive, virtual environments, and unrelated runs.

To rebuild it after changes, from Windows PowerShell in this folder:

```powershell
python package_upload.py --force
```

Choose a Linux GPU image with a functioning NVIDIA driver and ordinary Python **3.12**, preferably on the **RTX PRO 6000 Blackwell 96 GB**. Python 3.11–3.14 is supported by the package, but 3.12 avoids the local 3.14 TorchScript compatibility warning. Keep the working directory on persistent storage.

In Nebius, copy the machine's real public address and SSH username. In the following PowerShell command, replace `SSH_USER` and `SERVER_IP` with those actual values:

```powershell
scp "..\Mr_Bits_Neural_Lab_Upload.zip" "..\Mr_Bits_Neural_Lab_Upload.zip.sha256" "SSH_USER@SERVER_IP:~/"
ssh SSH_USER@SERVER_IP
```

Inside the Linux SSH terminal:

```bash
cd ~
sha256sum -c Mr_Bits_Neural_Lab_Upload.zip.sha256
unzip Mr_Bits_Neural_Lab_Upload.zip
cd 'ChatGPT Neural Network Lab'
python3 verify_upload.py
```

Expected: the ZIP checksum matches, followed by `PASS: ... extracted upload files match their checksums.` If `unzip` is unavailable, Python can extract it:

```bash
python3 -m zipfile -e Mr_Bits_Neural_Lab_Upload.zip .
```

Run that fallback from `~` before entering the extracted folder. Choose a new extraction location for a later bundle so it cannot mix old and new code silently.

## 2. Verify the machine before training

```bash
bash scripts/00_setup.sh
bash scripts/01_check.sh --require-cuda
```

Read the output. We need successful **CUDA forward/backward/optimizer** and **BF16** checks on the expected device. Setup records diagnostics and installed packages. If a check fails, stop there and share `diagnostics/environment.json`; do not let the machine spend hours training on the CPU by accident.

Verify the prepared data:

```bash
.venv/bin/python -c "from chesslab.data import verify_dataset; print(verify_dataset('data/local-100k')['counts'])"
```

Expected counts: `train=89995`, `validation=4979`, `test=5026`.

## 3. Measure speed, then run the two starting experiments

The benchmark trains disposable copies for a few steps. It does not update a saved model:

```bash
bash scripts/07_benchmark.sh small data/local-100k benchmarks/small-batches.json \
  --device cuda --batches 1024 4096 16384 --steps 30

bash scripts/07_benchmark.sh large data/local-100k benchmarks/large-batches.json \
  --device cuda --batches 1024 4096 16384 --steps 30
```

For the first comparison, keep the configured batch 2,048 so a throughput test does not silently change the learning recipe. We can compare other batch sizes later. A memory-safe, faster batch is not automatically the most accurate batch.

If `tmux` is installed, start a session so losing SSH does not kill training:

```bash
tmux new -s chesslab
```

Inside the session, return to this lab folder if necessary, then:

```bash
bash scripts/03_train.sh small data/local-100k runs/pilot-small --device cuda
bash scripts/03_train.sh large data/local-100k runs/pilot-large --device cuda
```

These run sequentially on one GPU. Watch the colored terminal progress and validation results. Detach from tmux with **Ctrl+B, then D**; reconnect later using `tmux attach -t chesslab`. If tmux is unavailable, keep the SSH session open for the short pilot or use the logging alternative in the [runbook](docs/NEBIUS_RUNBOOK.md).

Each run writes `best.pt`, `last.pt`, configurations, metrics, and its final status. Do not reuse a completed run directory for a different experiment.

## 4. Watch charts and GPU usage

In another SSH terminal, in the lab folder:

```bash
bash scripts/06_monitor.sh runs/pilot-small
```

Leave it running. In a **separate local PowerShell window**:

```powershell
ssh -N -L 6006:127.0.0.1:6006 SSH_USER@SERVER_IP
```

Open **http://127.0.0.1:6006** on your own computer. TensorBoard stays bound to the server's localhost; no public dashboard port is required. To watch both runs instead, use `bash scripts/06_monitor.sh runs`.

For actual GPU utilization, use another Linux terminal:

```bash
nvidia-smi -l 2
```

The progress bar's allocated memory is not the same measurement as `nvidia-smi`'s total device memory use. Small models can train efficiently without filling 96 GB.

## 5. Save and compare results

After both pilots finish:

```bash
bash scripts/05_evaluate.sh runs/pilot-small data/local-100k
bash scripts/05_evaluate.sh runs/pilot-large data/local-100k

.venv/bin/python -m chesslab.experiments compare \
  --runs runs/pilot-small runs/pilot-large \
  --output reports/pilot-comparison.json
```

Open the saved curves and inspect `test.json`. The comparison command uses validation results by default; do not repeatedly choose new settings using the test scores. Save a separate fixed final benchmark for serious claims.

To try the model on a position:

```bash
.venv/bin/python -m chesslab.rank \
  --checkpoint runs/pilot-small/best.pt --top 7 \
  --fen '7r/1p3k2/p1bPR3/5p2/2B2P1p/8/PP4P1/3K4 b - - 0 1'
```

For a **workflow demonstration** with the bundled low-budget teacher benchmark:

```bash
.venv/bin/python -m chesslab.rank \
  --checkpoint runs/pilot-small/best.pt \
  --benchmark benchmarks/local-teacher-test.jsonl \
  --output runs/pilot-small/demo-ranking.json
```

Those 20 positions are a development/workflow check. They are not enough to establish 95% recall or dependable pruning. Building a stronger independent benchmark requires an explicit Linux Stockfish binary and substantially more teacher work; see [move ranking](docs/MOVE_RANKING.md).

Download results before stopping/deleting the machine. First, in the Linux lab folder:

```bash
tar -czf "$HOME/mr-bits-results.tar.gz" runs reports benchmarks diagnostics
```

Then, in local PowerShell:

```powershell
scp "SSH_USER@SERVER_IP:~/mr-bits-results.tar.gz" ".\mr-bits-results.tar.gz"
```

You can also use SFTP to download `runs/`, `reports/`, `benchmarks/`, and `diagnostics/`. Confirm the downloaded archive opens locally. Stopping compute and deleting persistent disks are separate actions; keep artifacts backed up before any deletion.

## 6. Continue with new ideas

Read [experiments and variants](docs/EXPERIMENTS.md) to create another architecture or activation without rebuilding the dataset. Start with a fresh run, not a modified old checkpoint.

For interruptions, resume **the last completed epoch**, using the same configuration/data/device precision:

```bash
.venv/bin/python -m chesslab.train \
  --data data/local-100k --config configs/pilot_small.json \
  --run runs/pilot-small --device cuda \
  --resume runs/pilot-small/last.pt --epochs 15
```

That requests 15totalepochs. Partial interrupted work is replayed. The CPU demonstration run is for inspection/inference; start new CUDA runs in `runs/pilot-*`.

**When you return here, tell me the step you reached and show its output.** The persistent [handoff](HANDOFF.md) also records what has already been completed and what still needs evidence.
