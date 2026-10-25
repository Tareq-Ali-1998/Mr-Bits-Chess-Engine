# Continue from here

**Updated: 23 October 2026. Status: upload-ready lab completed and locally verified; first Nebius GPU session is next.**

This file preserves the working state if the session ends. A future “continue” means resume the authorized lab work below, not restart the project or change the original engine.

## Scope and boundaries

- Build a runnable, upload-ready Linux/Nebius training lab in this folder.
- Keep the original C++ engine and earlier documents unchanged. Never read `Claude Docs`.
- Train one general evaluator per run; compare the small model and the larger experiment.
- Measure move ranking with complete legal-child teacher labels; 95% recall@5/@7 is a research target, not a promise.
- No cloud instance has been provisioned. Do not spend money or launch paid jobs without the user's actual machine/access being ready.

## Current artifacts

- Runnable Python package, two model configurations, Bash workflow scripts, and detailed README/data/Nebius/ranking guides are present.
- `data/local-100k/`: 100,000 real prepared positions, selected from the first 160,000 archive records; splits 89,995 / 4,979 / 5,026. Source is a bounded prefix, not a representative full-archive sample.
- Dataset fingerprint: `744decab4d485b8415e617ad1fa09adf49cc4209cbe1d53bf163eadc8205e511`.
- `runs/local-small/`: real five-epoch CPU training, batch512, workers0, CPUthreads4. Completed 880 updates; best validation MAE103.7708cp, Huber0.72268. This validates learning, not playing strength or final ranking recall.
- Model sizes: small216,961 parameters; large17,858,049 parameters. The larger executable design supersedes the earlier notebook's3.6M proposal.
- Local Python 3.14.2 and PyTorch 2.10.0+cpu. The project-local `.venv` now includes the pinned NumPy/chess/Rich/Zstandard/matplotlib/TensorBoard dependencies. Plotting works in PNG and SVG. Actual CUDA training remains untested here.

Configurable MLP/residual families and ReLU/GELU/SiLU/tanh variants are implemented, with `chesslab.experiments` list/new/compare and generic `08_experiment.sh`. The complete suite has **43 passing tests**, including final export reuse/integrity checks. Full CPU setup succeeded, real event readback and a localhost TensorBoard HTTP endpoint passed, and PNG plotting passed. Project-local matplotlib cache avoids protected-home writes.

The demo benchmark has 20 parents / 588 legal children, Stockfish 16, and 2,000 requested nodes per nonterminal child. Strict recall@5/@7 is 6/20 = 30%; near-best within 25 cp @5 is 14/20 = 70%. This is workflow validation, not a strength/final 95% result. Artifacts are `benchmarks/local-teacher-test.jsonl` and `runs/local-small/ranking.json`.

`05_evaluate.sh` writes checkpoint-specific `exports/model-<hash>.ts`; export `--reuse-existing` checks both checkpoint and artifact checksums and never overwrites. The wrapper passed both initial execution and repeat execution. The full 17,858,049-parameter large network also passed a finite synthetic CPU forward/backward/AdamW step; it has not completed a real-data training run here.

The bundle is **`../Mr_Bits_Neural_Lab_Upload.zip`** with its sibling `.zip.sha256`. It contains source, configurations, docs, tests, the 100k pilot and the small demo run. It excludes the raw archive, engine, account files, `.venv`, caches and unrelated runs. The packager uses an explicit allowlist and LF-normalizes text for Linux. Bundle extraction, all file checksums, data checksums, the extracted-copy test suite, tamper detection, Markdown rendering, and local links passed. Eleven Bash files pass syntax; ten public help routes pass.

## User's next action

Follow `START_HERE.md`: upload the ZIP/checksum, extract into a fresh Linux directory, verify, run `00_setup.sh`, then `01_check.sh --require-cuda --strict-deps`. Prefer ordinary Python 3.12 on the GPU host. Keep the working directory on persistent storage. No raw-archive transfer is necessary for the pilot.

## Next actions when continuing

1. Read this file and the latest user steering; inspect any newly supplied GPU output or changed files.
2. If the user supplies their device-check results, resolve them before running benchmarks/training. Do not claim a server has been tested without actual evidence.
3. Run measured batch benchmarks for each chosen architecture, then the two fresh CUDA pilots. Use explicit `--device cuda` to avoid an accidental CPU run.
4. Review validation curves, GPU throughput/memory, and runtime/cost. Current GPU pilots use batch 2,048 / seed 20261023; the local five-epoch demonstration used batch 512 / seed 42.
5. Keep variants independent and reuse the prepared data. Select settings with validation; reserve a stronger, larger final benchmark for frozen claims.
6. Scale data coverage, training, and teacher-label budgets based on evidence. The 95% move-retention target has not been reached; do not enable hard top-k pruning.
7. Later verify C++ numerical agreement, inference cost and equal-time engine results before integration.

For code changes, run only the relevant checks and then rebuild with `python package_upload.py --force`. The current source/data are already locally verified; do not redo the research or rescan the raw archive without a reason. Detailed results are in `docs/LOCAL_VERIFICATION.md`.

## Source preservation reference

SHA-256 values before lab work:

| Original file under `lichess-bot-master/engines/` | SHA-256 |
|---|---|
| `Engine UCI.cpp` | `05ED557F763AAB92BBE06E4B9AAD3DCDDDAC70BFCDE24ADA91D3CFB05F768EF8` |
| `Kernel.cpp` | `A7B5A4AC412BAF5FD97FA59750368E1A277685B57B46C5A237D08953CB3263A9` |
| `Stockfish Handler.hpp` | `BF0844FCF4D22BCA8636E908C1F98513D8AB3C0DE7D726B3E76368DE7BDE7A57` |

## How to assess readiness

Local CPU tests, Bash checks, and export parity can be completed here. Actual NVIDIA kernels, GPU throughput/memory, final teacher quality, strong recall, and equal-time engine strength require later measured runs. Never report those as completed based on CPU wiring checks.
