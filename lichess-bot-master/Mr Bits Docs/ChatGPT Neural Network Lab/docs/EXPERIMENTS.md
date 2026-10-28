# 🧪 Many networks, one reusable dataset

The lab is an experiment workspace. `small` and `large` are two convenient starting configurations, not a limit on how many networks we can create.

```text
                    ONE PREPARED DATA RELEASE
                    train / validation / test
                              │
          ┌───────────────────┼─────────────────────┐
          ▼                   ▼                     ▼
     small ReLU          large ReLU           another experiment
     batch 2,048          batch 2,048           MLP / residual
     up to 5 epochs        up to 5 epochs         GELU / SiLU / tanh
          │                   │                     │
          ▼                   ▼                     ▼
   runs/pilot-small    runs/pilot-large       runs/my-next-idea

Each run: own config + weights + optimizer + metrics + data fingerprint.
No dataset copying and no mixing checkpoints between experiments.
```

## Batches, epochs and chunks are different

| Term | What it means | What happens if we increase it? |
|---|---|---|
| Batch size | Positions used for one optimizer update | More work per update, generally fewer updates per epoch; throughput and learning can change |
| Epochs | Repeated passes over the fixed training split | More weight updates, more compute, and potentially more overfitting |
| Data chunk/shard | A storage/loading subdivision | Can improve memory/I/O handling; does not improve accuracy by itself |
| Architecture | Layers, widths, shortcuts, activations | Changes capacity, optimization, memory, and inference cost |
| Seed | Initialization and shuffling randomness | Lets us estimate variability by repeating a configuration |

This version memory-maps a compact file per split. It loads batches without placing the full dataset on the GPU. The preprocessing `--chunk-size` controls CPU parsing work, **not training epochs**. We can introduce physical data shards later without changing what the network learns from each accepted sample.

## Inspect the configurations

```bash
.venv/bin/python -m chesslab.experiments list --configs configs
```

The output includes architecture, activation, parameters, batch, epochs, and seed. All JSON configurations are independently runnable.

## Create a new variant safely

Clone the current small pilot and change its activation and widths:

```bash
.venv/bin/python -m chesslab.experiments new \
  --base configs/pilot_small.json \
  --output configs/experiments/my-gelu.json \
  --activation gelu --hidden 512 128 --batch-size 2048 --epochs 15

bash scripts/08_experiment.sh configs/experiments/my-gelu.json \
  data/local-100k runs/my-gelu --device cuda
```

The tool refuses to overwrite another configuration. A new filename/run directory keeps experiments separate. The JSON model `name` is a label; the complete architecture specification is saved, so two variants that share a family are still distinguishable.

Or write a custom model object in a configuration:

```json
{
  "model": {
    "name": "wide-gelu-v1",
    "kind": "mlp",
    "input_dim": 782,
    "hidden": [1024, 512, 128],
    "activation": "gelu"
  },
  "seed": 20261023,
  "epochs": 20,
  "batch_size": 2048,
  "workers": 4,
  "learning_rate": 0.0003,
  "amp": "bfloat16"
}
```

Other omitted training settings receive explicit defaults, which are written into the run's `config.json`. Read that file when comparing experiments.

Supported families are **MLP** (`hidden` width list) and **residual** (`width`, `blocks`, `head`). Supported hidden activations are **ReLU, GELU, SiLU, and tanh**. The output stays signed and linear. A fundamentally new family, such as a convolutional network or king-conditioned incremental evaluator, needs a new implementation, specification validation, tests, and export checks; it cannot be invented by changing a string.

For non-ReLU residual variants, the post-addition activation also changes. A zero residual branch is an exact identity on nonnegative inputs for ReLU, but not generally for GELU/SiLU/tanh. Treat these as different model designs and measure them.

## Benchmark a custom configuration

The direct benchmark CLI accepts a configuration as an alternative to a preset:

```bash
.venv/bin/python -m chesslab.benchmark \
  --data data/local-100k --config configs/experiments/my-gelu.json \
  --batches 1024 4096 16384 --steps 30 --device cuda \
  --output benchmarks/my-gelu-batches.json
```

This measures throughput, not accuracy. It constructs disposable models and saves no learned production weights.

## Compare like with like

```bash
.venv/bin/python -m chesslab.experiments compare \
  --runs runs/pilot-small runs/pilot-large runs/my-gelu \
  --output reports/variant-comparison.json
```

Runs are grouped by dataset fingerprint and target/loss contract. Different groups cannot support a direct score comparison. Within a group the report orders validation Huber, and shows MAE from the **same best epoch**, update counts, seed, and training time.

That ordering is not a complete winner decision. One model may train longer, use more arithmetic, or be slower in the CPU engine. Compare quality at a common data budget, then at a common time/compute budget. Repeat promising variants with multiple seeds, and report the spread.

`--include-test` includes already-created test reports explicitly. Keep test results for reporting after choices are frozen; use validation when tuning.

## Resume versus a new experiment

Resume means continue the same learning process: same architecture, activation, batch size, learning rate, target contract, and data release. The trainer enforces those boundaries. Increasing the total epoch cap is allowed. Reusing the same dataset for a new activation or width means **fresh weights and a new run directory**.

Learning-rate schedules, pairwise ranking objectives, phase specialists, distillation, and incremental NNUE models are future experiments, not features silently active in today's recipe. Add each with its own configuration/contract, metrics, and tests so the lab remains understandable.
