# ✅ What has actually been tested

**23 October 2026 · local Windows CPU verification**

> Bro, these are measured results, including the weak ones. The lab is ready for its first GPU session; a strong chess evaluator is still the research objective.

## Working software and recovery

The complete suite currently passes **43 tests**. It covers encoding, the original Kernel's piece mapping, EP/castling, selected-label policy, full saved-PV legality, deduplication/splits, manifest integrity, architectures/activations, raw-score metrics, independent ranking, export parity, and experiment comparisons.

Recovery checks include a real optimizer step followed by interruption, replay of the unfinished epoch, deterministic uninterrupted-versus-resumed CPU weights, refusal of changed data/configuration/precision, and recovery between checkpoint and log commits. Early stopping cannot silently be bypassed by restarting the same checkpoint.

All **11 Bash files** pass syntax checks under Git Bash, and all **10 public help routes** work. The full CPU setup script was executed successfully in a project-local `.venv`, including the editable package install. Dependencies were installed inside that environment, without replacing the inherited working CPU Torch.

| Component | Verified local version |
|---|---|
| Python | 3.14.2, standard CPython |
| PyTorch | 2.10.0+cpu |
| NumPy | 2.4.1 |
| chess | 1.10.0 |
| Zstandard | 0.25.0 |
| Rich | 13.7.1 |
| matplotlib | 3.10.8 |
| TensorBoard | 2.20.0 |

The strict doctor passed real CPU matrix/backward/AdamW work, the actual lab feature/evaluator step, NumPy/Torch integration, compression, legal moves, Rich output, headless PNG plotting, and TensorBoard event writing.

A separate one-epoch run wrote real training/validation TensorBoard events. Their scalar values were read back, and a temporary localhost-only TensorBoard server successfully served the scalar-tags HTTP endpoint. The test server was stopped afterward. The GPU starter configurations enable TensorBoard.

## The prepared pilot is real

The read-only archive scan processed 160,000 records and found 112,771 unique candidates passing the policy. Hash selection retained 100,000: **89,995 training / 4,979 validation / 5,026 test**. This is a subset of a bounded prefix; its distribution cannot stand in for the complete archive.

The final data files occupy 10,800,576 bytes. Their checksums and the recomputed metadata fingerprint pass verification:

```text
744decab4d485b8415e617ad1fa09adf49cc4209cbe1d53bf163eadc8205e511
```

See the [manifest](../data/local-100k/manifest.json) and [data guide](DATA_PIPELINE.md) for policy and coverage.

## First real training result

`runs/local-small/` is a completed **five-epoch CPU demonstration** using batch 512, four CPU threads, no loader workers, and seed 42. Its saved configuration is the authority. The new GPU pilot configurations use seed 20261023 and batch 2,048, so they are different experiments and should not reproduce these numbers exactly.

There were **880 optimizer updates** and 449,975 training-position presentations. The recorded training-loop total is 11.53 seconds; the final cumulative epoch/validation/checkpoint timing is 12.60 seconds. Neither figure includes every process-startup cost or predicts GPU speed.

| Measurement | Result |
|---|---:|
| Validation Huber, epoch1→5 | 0.96187 → 0.72268 |
| Validation MAE, epoch1→5 | 128.85 → 103.77 cp |
| Held-out test MAE | **103.89 cp** |
| Held-out test RMSE | 197.89 cp |
| Test errors within 25 cp | 35.54% |
| Test errors within 50 cp | 56.01% |
| Test errors within 100 cp | 74.49% |
| Constant-zero test MAE | 137.13 cp |
| Basic material test MAE | 155.86 cp |
| Test examples | 5,026 |

The model learns and improves over these references on this distribution. The average hides substantial weakness: the test MAE is about 70.57 cp in the high-material diagnostic bucket and 186.15 cp in the low-material bucket. This is one general model; the buckets are analysis, not phase-specific networks.

![Measured CPU training curves](../runs/local-small/curves.png)

The [full test report](../runs/local-small/test.json) and [epoch CSV](../runs/local-small/metrics.csv) contain the underlying measurements. The first epoch's unusually high observed throughput is not a reliable sustained-speed estimate; use the dedicated benchmark on the target machine.

## The move-retention result is not 95%

An explicit bundled **Stockfish 16** binary generated a small workflow benchmark: **20 independent parents, 588 complete legal children, 2,000 requested nodes per nonterminal child**, one teacher thread and 64 MiB hash. Parent/child overlap exclusion against both training and validation ran before labeling.

| Measurement | Result |
|---|---:|
| Strict teacher-best recall@1 | 1/20 = 5% |
| Strict teacher-best recall@5 | **6/20 = 30%** |
| Strict teacher-best recall@7 | **6/20 = 30%** |
| Near-best within 25 cp recall@5 | 14/20 = 70% |
| Strict@5 Wilson 95% interval | 14.5%–51.9% |
| Near-best@5 Wilson 95% interval | 48.1%–85.5% |
| Mean finite top-one teacher regret | 308.45 cp |

There are only 20 observations, the node budget is deliberately low, and the pilot is drawn from a bounded source prefix. This is an end-to-end workflow check. It does **not** establish deployment strength, trustworthy hard pruning, or progress to 95% on a representative final benchmark. Near-best retention is a different claim from retaining an exactly tied teacher-best move.

The [ranking report](../runs/local-small/ranking.json) includes legal-move coverage, separate White/Black results, timings, and each parent outcome. Timings vary by host/run; its CPU parent latency includes Python legal generation, encoding, inference, and sorting. It is not a C++ search-node evaluator benchmark.

## Large model, exports and repeated evaluation

The actual 17,858,049-parameter large model passed a synthetic CPU batch-of-eight forward/backward/AdamW step with finite loss/weights and output shape `[8,1]`. It has **not** completed a large real-data training run here. Its size alone says nothing about its eventual chess quality.

TorchScript export parity passed for ReLU and the custom GELU/SiLU/tanh designs. The small trained checkpoint's serialized export matched eager outputs within the specified tolerance, with zero measured maximum difference in the local check. This is Python/TorchScript parity, not C++ integration.

The full Bash evaluation wrapper ran successfully and was rerun successfully. Checkpoint-specific export names and checksum-verified reuse avoid stale silent overwrites. Python 3.14 emits a TorchScript compatibility/deprecation warning; Python 3.12 is the recommended first server interpreter for this artifact format.

## What remains for the actual GPU session

- Verify the actual NVIDIA device, CUDA kernels, deterministic feature expansion, BF16 and full lab optimizer step using the doctor.
- Measure real batch throughput and peak allocated/reserved/free VRAM for both models.
- Train both GPU pilots and inspect validation curves rather than copying CPU expectations.
- Scale data coverage and training only after checking the pilot.
- Build a stronger, larger, stable teacher benchmark before making recall claims.
- Measure C++ inference and equal-time engine behavior before search integration.

No cloud machine was created, no paid training was launched, and the original C++ source hashes remain the preservation reference. The upload bundle includes only the lab, its explicit pilot/demo artifacts, and guides.
