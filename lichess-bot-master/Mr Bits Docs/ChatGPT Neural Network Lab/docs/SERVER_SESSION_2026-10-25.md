# Server session: 25 October 2026

This record is based on terminal output supplied by Tareq. Commands are run by him on the server; the assistant has no direct SSH session.

## Verified milestone

- Remote working directory: `/home/Mr-Bits-Neural-Lab/ChatGPT Neural Network Lab`.
- ZIP checksum passed and `verify_upload.py` verified 71 payload files.
- Ubuntu initially lacked `ensurepip`. Installing `python3.12-venv`, followed by `python3 -m venv --system-site-packages .venv`, resolved that prerequisite.
- `00_setup.sh` installed Torch 2.10.0+cu128 and the reference dependencies into the server's Python 3.12 environment.
- Both setup's doctor and the explicit `01_check.sh --require-cuda --strict-deps` completed successfully.
- Passed checks: CPU FP32, real lab CPU step, CUDA FP32, CUDA BF16, real deterministic lab CUDA step, NumPy/Torch bridge, chess rules, Zstandard, Rich, PNG plotting, and TensorBoard event writing.

The first actual GPU/software compatibility milestone is complete. Do not repeat setup unless a new failure or environment change warrants it.

## Data status

`data/local-100k/` was included in the ZIP. It contains 89,995 train / 4,979 validation / 5,026 test positions from a bounded source-prefix pilot. The original 22 GB archive is separate; its transfer to `../raw/lichess_db_eval.jsonl.zst` was requested, but completion has not yet been verified.

## Next checkpoint

Measure the small model's real batch throughput with the same zero-worker loader used by the starter pilot:

```bash
bash scripts/07_benchmark.sh small data/local-100k benchmarks/small-batches.json \
  --device cuda --workers 0 --batches 1024 2048 4096 16384 --steps 30
```

Then run the small pilot with its existing batch-2,048/five-epoch configuration in a fresh run directory:

```bash
bash scripts/03_train.sh small data/local-100k runs/pilot-small --device cuda
bash scripts/05_evaluate.sh runs/pilot-small data/local-100k
```

Review actual benchmark output and learning curves. Benchmark throughput alone does not select an accuracy-optimal batch. The pilot is an end-to-end test before broader data preparation and serious scaling; no 95% retention claim is warranted.

## Completed first small-model GPU pilot

Tareq supplied the successful benchmark, five-epoch training, and evaluation/export output.

| Requested batch | Observed training positions/s | Peak allocated MiB |
|---:|---:|---:|
| 1,024 | 109,682 | 76.42 |
| 2,048 | 145,490 | 84.52 |
| 4,096 | 131,891 | 101.71 |
| 16,384 | 138,786 | 198.67 |

Each trial measured only 30 steps after two warm-ups; some trials lasted less than one second. Batch 2,048 was fastest in these observations, not a proven universal optimum. The small network's low memory footprint is expected from its 216,961 parameters; this does not demonstrate full GPU compute utilization.

The actual `runs/pilot-small` run used CUDA BF16 autocast, batch 2,048, seed 20261023, five epochs and 220 optimizer updates. Validation Huber decreased from 1.0492 to 0.88409; validation MAE decreased from 136.2 to about 120.0 cp. Best epoch: 5.

Test evaluation on 5,026 positions reported MAE 118.9413 cp, RMSE 221.3048 cp, 54.60% within 50 cp, and 70.47% within 100 cp. Reference MAEs: constant zero 137.1301 cp; basic material 155.8575 cp. These are finite-cp regression metrics, not move-retention accuracy. Low-material test MAE was 216.66 cp, indicating substantial remaining weakness.

Plotting generated `runs/pilot-small/curves.png`; serialized export parity had zero measured max absolute difference. Best checkpoint SHA-256: `b6f5adbb205d98675ba03251b30aaea7f4d5ce72d5ec4ee3f564f6c35575be11`.

The earlier CPU demo used a different seed and batch, and made 880 updates rather than 220. Its lower error is not evidence that CPU training is inherently better. Compare fixed data and controlled learning budgets.

The trailing `bash: runs/pilot-small/: Is a directory` was caused by entering the folder path as a command after successful evaluation. To inspect it, use `ls -lh runs/pilot-small`.

## Next actions after this result

1. Benchmark the large model with the same loader settings, then run and evaluate its fresh five-epoch pilot in `runs/pilot-large`.
2. Confirm the full raw archive actually exists and has finished transferring at `../raw/lichess_db_eval.jsonl.zst`.
3. Prepare a broader accepted dataset in a new directory before serious scaling. Keep the 100k pilot as the initial workflow reference, not the final strength test.
4. Use validation for subsequent tuning. A low regression loss does not establish the 95% move-retention goal.

The large model and custom variants have not yet produced supplied server results.

## Unattended large run started: 26 October

Tareq uploaded the new launcher and started the documented nohup command. `ps` confirmed parent PID120565. The source checksum stage completed, all CUDA/BF16 checks passed again, and the full large architecture completed its disposable GPU preflight: batch2,048,10measuredsteps,20,480examples in0.18888seconds, about108,427positions/s and416.47MiB peak allocated. This is a short workload measurement, not a sustained-training prediction.

At the latest supplied output, `big-10m-v1` had entered CPU preparation with16workers. It reported226,560raw records scanned and159,523clean unique candidates at23seconds. The active plan remains up to20million scanned records, up to10million selected accepted positions, then sequential small/large training and evaluation. Full-scale training has not yet been observed in supplied output.

The user's laptop can disconnect after the confirmed nohup start. The NebiusVM must stay running. Use the existing log/status files to check progress; do not rerun setup or launch the pipeline again while its PID is alive.

## Completion confirmed on return

The next supplied server inspection confirms state `complete`, stage `finished`, at `2026-10-25T23:23:43.619042+00:00` (26October03:23Dubai). Elapsed wall time was7,632.34seconds, approximately2hours7minutes12seconds. Both experiments finished with evaluation/export and the final comparison report. The prepared manifest and both final checkpoints exist, and the process search returned no matching active job.

Full quality metrics have not yet been supplied; the last30log lines show only the end of one model's bucketed report. Do not infer a winner, exact selected count, number of epochs, or move-retention rate from that tail. Next actions are artifact backup through SFTP and a concise full-results summary. Existing outputs should be reused, not restarted.

## Subsequent complete scalar summary

The user then supplied exact counts and both result/test summaries. The accepted release has10,000,000positions:9,001,091train,499,588validation,499,321test. Both models completed20epochs and selected epoch20 as their best validation checkpoint.

| Model | Test MAE, cp | Test RMSE, cp |
|---|---:|---:|
| Small | 117.47 | 199.78 |
| Large | 90.82 | 173.57 |
| Constant zero | 168.39 | Not supplied |
| Basic material | 177.94 | Not supplied |

Large reduces same-test MAE by about22.7% relative to small,46.1% relative to zero, and49.0% relative to material. These are scalar errors against the stored teacher distribution, not accuracy percentages, Elo, or top-k move retention. The larger design is the leading scalar predictor in this comparison; deployment still depends on move ranking and inference cost.

The full curves and checkpoint artifacts have not yet been inspected locally. Epoch20 being best means the cap was reached at the observed best validation point; it does not prove convergence, that more epochs help, or that all tactical subsets generalize. Next: inspect curves/coverage and construct a complete-legal-child validation benchmark, preserving an independent final ranking test for frozen decisions.

This progress record was written after the initial upload. The server ZIP is still the valid uploaded snapshot; no reupload is needed for these commands.
