"""Measure real disposable training steps across batches; never tune accuracy by VRAM fill."""
from __future__ import annotations

import argparse
import gc
import json
from pathlib import Path

import torch

from .train import _atomic_json, benchmark_production, normalize_config, resolve_device


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", required=True, type=Path)
    architecture = parser.add_mutually_exclusive_group(required=True)
    architecture.add_argument("--model", choices=("small", "large"))
    architecture.add_argument("--config", type=Path, help="Any lab training config, including a custom model specification")
    parser.add_argument("--batches", nargs="+", type=int)
    parser.add_argument("--steps", type=int, default=30)
    parser.add_argument("--warmup", type=int, default=2)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    parser.add_argument("--workers", type=int)
    parser.add_argument("--cpu-threads", type=int)
    args = parser.parse_args(argv)
    base_config = json.loads(args.config.read_text(encoding="utf-8")) if args.config else {"model": {"name": args.model}}
    if args.workers is not None:
        base_config["workers"] = args.workers
    if args.cpu_threads is not None:
        base_config["cpu_threads"] = args.cpu_threads
    base_config["tensorboard"] = False
    base_config = normalize_config(base_config)
    batches = args.batches or [1024, 4096, 16384]
    if args.steps < 1 or args.warmup < 0 or any(batch < 1 for batch in batches):
        parser.error("steps/batch sizes must be positive and warmup nonnegative")
    device = resolve_device(args.device)
    trials = []
    for batch in batches:
        config = {**base_config, "batch_size": batch}
        print(f"Benchmark {base_config['model']['name']}, requested batch {batch:,}, {args.steps} measured steps...")
        try:
            measurement = benchmark_production(args.data, config, device, args.steps, args.warmup)
            if device.type == "cuda":
                measurement["headroom_fraction"] = min(
                    1 - measurement["peak_reserved_mib"] / measurement["total_vram_mib"],
                    measurement["free_vram_mib"] / measurement["total_vram_mib"])
            trials.append(measurement)
        except torch.cuda.OutOfMemoryError:
            trials.append({"status": "out_of_memory", "requested_batch_size": batch})
        finally:
            gc.collect()
            if device.type == "cuda":
                torch.cuda.empty_cache()
    eligible = [trial for trial in trials if trial["status"] == "ok" and trial.get("headroom_fraction", 1.0) >= 0.10
                and trial["actual_batch_size_max"] == trial["requested_batch_size"]]
    winner = max(eligible, key=lambda trial: trial["examples_per_second"]) if eligible else None
    report = {"model": base_config["model"]["name"], "model_spec": base_config["model"], "trials": trials,
              "recommended_throughput_batch": winner["requested_batch_size"] if winner else None,
              "recommendation_policy": "Highest observed end-to-end throughput among trials that include the requested full batch and have >=10% headroom by both peak-reserved-memory and observed free CUDA memory. Partial epoch-ending batches are counted by their actual examples. This is not an accuracy recommendation, a future-memory guarantee, or a VRAM-utilization target.",
              "notes": "Fresh model/optimizer per trial; only benchmark measurements are persisted. No trained weights or production-run history changed. Repeat to assess timing noise; retain final smaller training batches in real training."}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    _atomic_json(args.output, report)
    print(json.dumps(report, indent=2, allow_nan=False))
    return 0 if any(trial["status"] == "ok" for trial in trials) else 2


if __name__ == "__main__":
    raise SystemExit(main())
