# ⚽ Start the longer server run through SFTP

**26 October 2026.** The small GPU pilot has already completed successfully. This launcher automates the next larger experiment; it does not create a cloud machine.

## What it will do

1. Check the full raw archive's exact byte count and SHA-256 against the original local file.
2. Check available scratch space and CUDA/BF16, then exercise the large network on disposable pilot batches.
3. Scan up to **20 million raw records**, retain up to **10 million unique accepted positions** under the existing strict quality policy, and create stable train/validation/test splits.
4. Train the small and large models **sequentially**, each for up to 20 epochs, with batch 2,048, zero loader workers, BF16 and validation early stopping.
5. Save checkpoints, TensorBoard events, plots, test metrics, checked exports and a comparison report.

This selection is from a bounded scanned pool, not the entire archive. Training ten million accepted positions is a substantial first scaling experiment, not the final 95% move-retention result. Runtime has not been measured for this job; it could finish before the match ends or take longer. The early preparation stage uses CPU, so GPU utilization may be low during that stage.

## 1. Finish the archive upload

Using your existing SFTP view, finish uploading:

```text
/home/Mr-Bits-Neural-Lab/raw/lichess_db_eval.jsonl.zst
```

Expected size: **22,423,777,007 bytes**. Some file browsers display this as about 20.88 GiB instead of 22.42 decimal GB. Both describe the same bytes.

Keep the laptop awake and SFTP connected until the transfer completes. Leave the file compressed. The launcher requires the completed file; size alone is insufficient, so it also hashes the entire source before using it.

The original source's SHA-256 is:

```text
b2856cafa4d323b2641a43e2d25b716313febeef2fbed9b1472f7a036a368215
```

## 2. Upload one new small file

In SFTP's local pane, find:

```text
C:\Users\tareq\Desktop\Mr_Bits\lichess-bot-master\Mr Bits Docs\ChatGPT Neural Network Lab\scripts\09_long_run.sh
```

Upload it to the server's outer working folder:

```text
/home/Mr-Bits-Neural-Lab/09_long_run.sh
```

This avoids requiring your SFTP account to write into root-owned extracted subfolders. In the server's Workflow terminal, copy it into the lab:

```bash
cd '/home/Mr-Bits-Neural-Lab/ChatGPT Neural Network Lab'
cp ../09_long_run.sh scripts/09_long_run.sh
bash -n scripts/09_long_run.sh
bash scripts/09_long_run.sh --help
```

## 3. Start the detached job once

From that same lab directory, after SFTP reports the full archive transfer complete:

```bash
mkdir -p logs
nohup bash scripts/09_long_run.sh \
  --input /home/Mr-Bits-Neural-Lab/raw/lichess_db_eval.jsonl.zst \
  > logs/big-10m-v1.log 2>&1 < /dev/null &
echo $! > logs/big-10m-v1.pid
```

The default tag is `big-10m-v1`. A pipeline lock rejects duplicate launches for the same experiment. Check that it is running:

```bash
ps -p "$(cat logs/big-10m-v1.pid)" -o pid,etime,args
tail -n 40 -f logs/big-10m-v1.log
```

The log first reports source checksum verification, then GPU preflight and preparation. Hashing 22 GB is a real disk read and can take a while without intermediate progress lines. If it reports `FAILED`, read the reason before proceeding. It requires at least **20 GiB free beyond the already uploaded archive** for the deduplication index and generated artifacts; preparation stores all accepted scanned keys before sampling.

Once the process is confirmed alive and the log shows the expected stage, SSH can disconnect and the laptop can sleep. The **Nebius VM must remain running**. `Ctrl+C` exits the `tail` viewer without stopping the detached job.

## 4. Watch or return later

Stage/status:

```bash
cat logs/big-10m-v1.status.json
tail -n 60 logs/big-10m-v1.log
```

GPU:

```bash
nvidia-smi -l 2
```

TensorBoard, in another terminal:

```bash
bash scripts/06_monitor.sh runs/big-10m-v1
```

Use the localhost SSH tunnel described in START_HERE to see browser charts. TensorBoard data appears after training begins; CPU data preparation is reported in the log and `data/big-10m-v1/preparation_progress.json` instead.

Results:

```text
data/big-10m-v1/                  prepared release and manifest
runs/big-10m-v1/plan.json         frozen run plan
runs/big-10m-v1/source.json       verified raw source
runs/big-10m-v1/data-binding.json source-to-prepared-release binding
runs/big-10m-v1/small/            first model and results
runs/big-10m-v1/large/            second model and results
runs/big-10m-v1/comparison.json   final report
logs/big-10m-v1.log              complete durable console output
logs/big-10m-v1.status.json      latest stage / complete / failed
```

## Recovery

If a training phase is interrupted, launch the same command again after confirming the old process has stopped. It verifies source/data and resumes from each model's `last.pt`; complete runs return without adding extra epochs. Unfinished epoch work is replayed.

Preparation currently cannot resume a partial compressed scan. If it fails and leaves a nonempty dataset folder without a completed manifest, preserve that folder for inspection. Choose a new tag, such as `--tag big-10m-v2`, for a fresh preparation attempt. Do not delete the raw archive or overwrite completed experiment directories.

The launcher was syntax-checked and independently reviewed locally. Nine isolated tests passed for source guards, command construction, actual tiny NumPy integrity checks, checkpoint resume, unchanged plans, partial-data preservation and child failures. They do not exercise actual Linux signals, locks or GPU work. The launcher has not yet completed this multi-million-position run on the server; its first log/status output is the next evidence to inspect. Save results before shutting down or deleting the VM/disk.
