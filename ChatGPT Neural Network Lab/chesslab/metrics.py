"""Streaming raw-centipawn diagnostics and an explicit held-out evaluation CLI."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import torch
from torch.nn import functional as F

BUCKETS = (("0_50", 0, 50), ("50_200", 50, 200), ("200_600", 200, 600),
           ("600_1500", 600, 1500), ("1500_plus", 1500, float("inf")))
MATERIAL_CP = (0, 100, 320, 330, 500, 900, 0, -100, -320, -330, -500, -900, 0)


class MetricAccumulator:
    def __init__(self, clip_pawns: float = 15.0, huber_delta: float = 1.0) -> None:
        self.clip_pawns, self.huber_delta = float(clip_pawns), float(huber_delta)
        if self.clip_pawns <= 0 or self.huber_delta <= 0:
            raise ValueError("clip_pawns and huber_delta must be positive")
        self.n = 0
        self.absolute = self.squared = self.bias = self.huber = 0.0
        self.within = {25: 0, 50: 0, 100: 0}
        self.clipped = 0
        self.zero_absolute = self.material_absolute = 0.0
        self.material_n = 0
        self.buckets = {name: {"n": 0, "absolute": 0.0} for name, _, _ in BUCKETS}
        self.phases = {name: {"n": 0, "absolute": 0.0} for name in ("low_material", "medium_material", "high_material")}

    def update(self, prediction: torch.Tensor, raw_cp: torch.Tensor,
               compressed: torch.Tensor | None = None) -> None:
        if prediction.shape != raw_cp.shape or prediction.ndim != 2 or prediction.shape[1] != 1:
            raise ValueError("Predictions and raw-cp labels must both have shape [batch,1]")
        predicted = prediction.detach().to(device="cpu", dtype=torch.float64).reshape(-1)
        target = raw_cp.detach().to(device="cpu", dtype=torch.float64).reshape(-1)
        if not torch.isfinite(predicted).all() or not torch.isfinite(target).all():
            raise ValueError("Non-finite predictions or labels in evaluation")
        error = predicted * 100.0 - target
        absolute = error.abs()
        self.n += target.numel()
        self.absolute += absolute.sum().item()
        self.squared += error.square().sum().item()
        self.bias += error.sum().item()
        self.zero_absolute += target.abs().sum().item()
        self.huber += F.huber_loss(predicted, (target / 100).clamp(-self.clip_pawns, self.clip_pawns),
                                   delta=self.huber_delta, reduction="sum").item()
        self.clipped += (target.abs() > self.clip_pawns * 100).sum().item()
        for threshold in self.within:
            self.within[threshold] += (absolute <= threshold).sum().item()
        for name, low, high in BUCKETS:
            mask = (target.abs() >= low) & (target.abs() < high)
            self.buckets[name]["n"] += mask.sum().item()
            self.buckets[name]["absolute"] += absolute[mask].sum().item()
        if compressed is not None:
            pieces = compressed.detach().to(device="cpu", dtype=torch.int64)[:, :64]
            material = torch.tensor(MATERIAL_CP, dtype=torch.float64)[pieces].sum(dim=1)
            self.material_absolute += (material - target).abs().sum().item()
            self.material_n += target.numel()
            phase_weights = torch.tensor((0, 0, 1, 1, 2, 4, 0, 0, 1, 1, 2, 4, 0))
            phase = phase_weights[pieces].sum(dim=1)
            masks = {"low_material": phase <= 8, "medium_material": (phase > 8) & (phase <= 16),
                     "high_material": phase > 16}
            for name, mask in masks.items():
                self.phases[name]["n"] += mask.sum().item()
                self.phases[name]["absolute"] += absolute[mask].sum().item()

    def result(self) -> dict:
        if not self.n:
            raise ValueError("Cannot evaluate an empty split")
        def groups(values):
            return {name: {"n": int(value["n"]), "mae_cp": value["absolute"] / value["n"] if value["n"] else None}
                    for name, value in values.items()}
        return {"n": self.n, "huber": self.huber / self.n, "mae_cp": self.absolute / self.n,
                "rmse_cp": math.sqrt(self.squared / self.n), "bias_cp": self.bias / self.n,
                **{f"within_{threshold}_cp": value / self.n for threshold, value in self.within.items()},
                "target_clip_fraction": self.clipped / self.n, "zero_baseline_mae_cp": self.zero_absolute / self.n,
                "material_baseline_mae_cp": self.material_absolute / self.material_n if self.material_n else None,
                "absolute_target_buckets": groups(self.buckets), "material_phase_buckets": groups(self.phases)}


@torch.inference_mode()
def evaluate_model(model, loader, device, clip_pawns=15.0, huber_delta=1.0, autocast_dtype=None,
                   progress_callback=None) -> dict:
    from .features import expand_batch
    model.eval()
    accumulator = MetricAccumulator(clip_pawns, huber_delta)
    device = torch.device(device)
    for compressed, raw_cp in loader:
        features = expand_batch(compressed.to(device, non_blocking=True))
        with torch.autocast(device_type=device.type, dtype=autocast_dtype or torch.float32,
                            enabled=autocast_dtype is not None):
            prediction = model(features)
        accumulator.update(prediction.float(), raw_cp, compressed)
        if progress_callback:
            progress_callback(len(raw_cp), accumulator.absolute / accumulator.n)
    return accumulator.result()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", required=True, type=Path)
    parser.add_argument("--data", required=True, type=Path)
    parser.add_argument("--split", choices=("validation", "val", "test"), default="test")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    parser.add_argument("--batch-size", type=int, default=1024)
    parser.add_argument("--workers", type=int, default=0)
    args = parser.parse_args(argv)
    from .data import PositionDataset
    from .models import load_checkpoint
    from .train import resolve_device
    device = resolve_device(args.device)
    model, checkpoint = load_checkpoint(args.checkpoint, device)
    split = "validation" if args.split == "val" else args.split
    dataset = PositionDataset(args.data, split=split)
    if checkpoint.get("data_fingerprint") != dataset.manifest.get("fingerprint"):
        parser.error("Data fingerprint differs from the checkpoint's fixed training/validation/test release")
    if args.batch_size < 1 or args.workers < 0:
        parser.error("batch size must be positive and workers nonnegative")
    loader = torch.utils.data.DataLoader(dataset, batch_size=args.batch_size, num_workers=args.workers,
                                         shuffle=False, pin_memory=device.type == "cuda")
    result = evaluate_model(model, loader, device, checkpoint["target"]["clip_pawns"],
                            checkpoint["config"].get("huber_delta", 1.0))
    report = {"checkpoint": str(args.checkpoint), "split": split, "data_fingerprint": dataset.manifest["fingerprint"],
              "evaluation_precision": "float32", "metrics": result,
              "notes": "Raw-cp errors include clipped target tails; Huber uses clipped pawn targets. No recall@K without sibling labels."}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
