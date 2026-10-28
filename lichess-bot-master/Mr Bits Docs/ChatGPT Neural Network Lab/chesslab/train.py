"""Reproducible single-device training, bounded benchmarks, and epoch-boundary resume."""
from __future__ import annotations

import argparse
import csv
import gc
import json
import math
import os
from pathlib import Path
import random
import time

import numpy as np
import torch
from torch.nn import functional as F
from torch.utils.data import DataLoader

from .data import PositionDataset
from .features import FEATURE_VERSION, expand_batch
from .metrics import evaluate_model
from .models import CHECKPOINT_VERSION, build_model, canonical_spec, load_checkpoint, model_statistics

DEFAULTS = {
    "model": {"name": "small"}, "seed": 20261023, "epochs": 20, "batch_size": 4096,
    "workers": 4, "cpu_threads": min(8, os.cpu_count() or 1), "learning_rate": 3e-4,
    "weight_decay": 1e-4, "huber_delta": 1.0, "clip_pawns": 15.0,
    "gradient_clip_norm": 1.0, "patience": 5, "min_delta": 1e-4,
    "amp": "bfloat16", "compile": False, "deterministic": True,
    "log_every_steps": 20, "tensorboard": True,
}
OPERATIONAL_KEYS = {"epochs", "workers", "cpu_threads", "tensorboard", "compile", "log_every_steps"}


def normalize_config(config: dict) -> dict:
    unknown = set(config) - set(DEFAULTS)
    if unknown:
        raise ValueError(f"Unknown configuration keys: {sorted(unknown)}")
    result = {**DEFAULTS, **config}
    result["model"] = canonical_spec(result["model"])
    for key in ("epochs", "batch_size", "cpu_threads", "patience", "log_every_steps"):
        if not isinstance(result[key], int) or isinstance(result[key], bool) or result[key] < 1:
            raise ValueError(f"{key} must be a positive integer")
    for key in ("workers", "seed"):
        if not isinstance(result[key], int) or isinstance(result[key], bool) or result[key] < 0:
            raise ValueError(f"{key} must be a nonnegative integer")
    for key in ("learning_rate", "huber_delta", "clip_pawns", "gradient_clip_norm"):
        if not isinstance(result[key], (int, float)) or not math.isfinite(result[key]) or result[key] <= 0:
            raise ValueError(f"{key} must be finite and positive")
    for key in ("weight_decay", "min_delta"):
        if not isinstance(result[key], (int, float)) or not math.isfinite(result[key]) or result[key] < 0:
            raise ValueError(f"{key} must be finite and nonnegative")
    for key in ("compile", "deterministic", "tensorboard"):
        if not isinstance(result[key], bool):
            raise ValueError(f"{key} must be true or false")
    if result["amp"] not in ("bfloat16", "float32"):
        raise ValueError("amp must be bfloat16 or float32")
    return result


def resolve_device(choice: str) -> torch.device:
    if choice == "auto":
        choice = "cuda" if torch.cuda.is_available() else "cpu"
    if choice not in ("cuda", "cpu"):
        raise ValueError("device must be auto, cpu, or cuda")
    if choice == "cuda" and not torch.cuda.is_available():
        raise ValueError("CUDA requested but this PyTorch environment has no available CUDA GPU")
    return torch.device(choice)


def seed_everything(seed: int, deterministic: bool = True) -> None:
    os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
    random.seed(seed)
    np.random.seed(seed % (2**32))
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    torch.use_deterministic_algorithms(deterministic)
    if hasattr(torch.backends, "cudnn"):
        torch.backends.cudnn.benchmark = False
        torch.backends.cudnn.deterministic = deterministic
    if hasattr(torch.backends, "cuda"):
        torch.backends.cuda.matmul.allow_tf32 = False
    if hasattr(torch.backends, "cudnn"):
        torch.backends.cudnn.allow_tf32 = False


def _worker_seed(worker_id: int) -> None:
    seed = torch.initial_seed() % (2**32)
    random.seed(seed)
    np.random.seed(seed)


def _rng_state() -> dict:
    numpy_state = np.random.get_state()
    return {"python": random.getstate(), "numpy": {"name": numpy_state[0],
            "keys": numpy_state[1].tolist(), "position": numpy_state[2],
            "has_gauss": numpy_state[3], "cached_gaussian": numpy_state[4]},
            "torch": torch.get_rng_state(),
            "cuda": torch.cuda.get_rng_state_all() if torch.cuda.is_available() else []}


def _restore_rng(state: dict) -> None:
    random.setstate(state["python"])
    saved = state["numpy"]
    np.random.set_state((saved["name"], np.asarray(saved["keys"], dtype=np.uint32),
                         saved["position"], saved["has_gauss"], saved["cached_gaussian"]))
    torch.set_rng_state(state["torch"])
    if state.get("cuda") and torch.cuda.is_available():
        torch.cuda.set_rng_state_all(state["cuda"])


def _atomic_json(path: Path, value) -> None:
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        stream.write(json.dumps(value, indent=2, allow_nan=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)
    _sync_directory(path.parent)


def _atomic_checkpoint(path: Path, checkpoint: dict) -> None:
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("wb") as stream:
        torch.save(checkpoint, stream)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)
    _sync_directory(path.parent)


def _sync_directory(directory: Path) -> None:
    # Windows does not expose POSIX directory fsync. Rename is still atomic;
    # durability ultimately also depends on the storage/volume guarantees.
    if os.name != "nt":
        descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _write_history(run: Path, history: list[dict]) -> None:
    if not history:
        return
    path = run / "metrics.csv"
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(history[0]["summary"]))
        writer.writeheader()
        writer.writerows(record["summary"] for record in history)
    temporary.replace(path)
    path = run / "metrics.jsonl"
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text("".join(json.dumps(record, allow_nan=False) + "\n" for record in history), encoding="utf-8")
    temporary.replace(path)


class RunLock:
    """OS lock is automatically released even when a process is killed."""
    def __init__(self, run: Path):
        self.path = run / ".training.lock"
        self.stream = None

    def __enter__(self):
        self.stream = self.path.open("a+b")
        self.stream.seek(0, 2)
        if self.stream.tell() == 0:
            self.stream.write(b"0")
            self.stream.flush()
        self.stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.stream.close()
            raise ValueError("Another trainer is already using this run directory") from exc
        return self

    def __exit__(self, *args):
        self.stream.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(self.stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(self.stream.fileno(), fcntl.LOCK_UN)
        self.stream.close()


class Display:
    def __init__(self):
        self.progress = None
        self.console = None
        try:
            from rich.console import Console
            from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn, TimeRemainingColumn
            self.console = Console()
            self.progress = Progress(SpinnerColumn(), TextColumn("{task.description}"), BarColumn(),
                                     TaskProgressColumn(), TextColumn("{task.fields[metric]}"),
                                     TimeRemainingColumn(), TextColumn("{task.fields[memory]}"),
                                     console=self.console, transient=True)
        except ImportError:
            pass

    def __enter__(self):
        if self.progress:
            self.progress.start()
        return self

    def __exit__(self, *args):
        if self.progress:
            self.progress.stop()

    def print(self, value):
        self.console.print(value) if self.console else print(value)

    def add(self, description, total):
        return self.progress.add_task(description, total=total, metric="", memory="") if self.progress else None

    def advance(self, task, count, metric="", memory=""):
        if self.progress and task is not None:
            self.progress.update(task, advance=count, metric=metric, memory=memory)

    def remove(self, task):
        if self.progress and task is not None:
            self.progress.remove_task(task)


def _amp_dtype(config: dict, device: torch.device):
    if device.type == "cuda" and config["amp"] == "bfloat16":
        if not torch.cuda.is_bf16_supported():
            raise ValueError("bfloat16 requested on CUDA, but GPU/runtime does not support it; select amp=float32")
        return torch.bfloat16
    return None


def _loader(dataset, config, device, generator, shuffle):
    return DataLoader(dataset, batch_size=config["batch_size"], shuffle=shuffle,
                      num_workers=config["workers"], pin_memory=device.type == "cuda",
                      persistent_workers=False, generator=generator, worker_init_fn=_worker_seed,
                      drop_last=False)


def _optimizer(model, config):
    return torch.optim.AdamW(model.parameters(), lr=config["learning_rate"],
                             weight_decay=config["weight_decay"], betas=(0.9, 0.999), eps=1e-8)


def train_step(model, optimizer, batch, config, device, amp_dtype=None):
    compressed, raw_cp = batch
    features = expand_batch(compressed.to(device, non_blocking=True))
    raw_cp = raw_cp.to(device, non_blocking=True)
    targets = (raw_cp.float() / 100).clamp(-config["clip_pawns"], config["clip_pawns"])
    optimizer.zero_grad(set_to_none=True)
    with torch.autocast(device_type=device.type, dtype=amp_dtype or torch.float32, enabled=amp_dtype is not None):
        prediction = model(features)
    if prediction.shape != targets.shape or prediction.ndim != 2 or prediction.shape[1] != 1:
        raise ValueError("Model predictions and labels must both have shape [batch,1]")
    loss = F.huber_loss(prediction.float(), targets, delta=config["huber_delta"], reduction="mean")
    if not torch.isfinite(loss).item():
        raise FloatingPointError("Non-finite loss; the last completed epoch checkpoint is still available")
    loss.backward()
    norm = torch.nn.utils.clip_grad_norm_(model.parameters(), config["gradient_clip_norm"], error_if_nonfinite=True)
    optimizer.step()
    return float(loss.detach().item()), len(raw_cp), float(norm.item())


def _synchronize(device):
    if device.type == "cuda":
        torch.cuda.synchronize(device)


def benchmark_production(data_dir, config, device, steps=30, warmup=2) -> dict:
    """A fresh disposable model: no checkpoints, history, or live trainer state changed."""
    config = normalize_config(config)
    device = torch.device(device)
    if steps < 1 or warmup < 0:
        raise ValueError("benchmark steps must be positive and warmup nonnegative")
    torch.set_num_threads(config["cpu_threads"])
    seed_everything(config["seed"], config["deterministic"])
    dataset = PositionDataset(data_dir, split="train")
    model = optimizer = forward_model = loader = iterator = None
    try:
        if not len(dataset):
            raise ValueError("Training split is empty")
        generator = torch.Generator().manual_seed(config["seed"])
        loader = _loader(dataset, config, device, generator, True)
        iterator = iter(loader)
        def next_batch():
            nonlocal iterator
            try:
                return next(iterator)
            except StopIteration:
                iterator = iter(loader)
                return next(iterator)
        model = build_model(config["model"]).to(device).train()
        optimizer = _optimizer(model, config)
        forward_model = torch.compile(model) if config["compile"] else model
        amp_dtype = _amp_dtype(config, device)
        for _ in range(warmup):
            train_step(forward_model, optimizer, next_batch(), config, device, amp_dtype)
        _synchronize(device)
        if device.type == "cuda":
            torch.cuda.reset_peak_memory_stats(device)
        started = time.perf_counter()
        examples = 0
        losses = []
        batch_sizes = []
        for _ in range(steps):
            loss, count, _ = train_step(forward_model, optimizer, next_batch(), config, device, amp_dtype)
            examples += count
            losses.append(loss)
            batch_sizes.append(count)
        _synchronize(device)
        seconds = time.perf_counter() - started
        free, total = torch.cuda.mem_get_info(device) if device.type == "cuda" else (None, None)
        return {"status": "ok", "device": str(device), "gpu_name": torch.cuda.get_device_name(device) if device.type == "cuda" else None,
                "torch_version": str(torch.__version__), "precision": "bfloat16_autocast" if amp_dtype else "float32",
                "model_spec": config["model"], "model_statistics": model_statistics(config["model"]),
                "data_fingerprint": dataset.manifest["fingerprint"], "requested_batch_size": config["batch_size"],
                "workers": config["workers"], "cpu_threads": config["cpu_threads"], "steps": steps, "warmup_steps": warmup,
                "examples": examples, "actual_batch_size_min": min(batch_sizes), "actual_batch_size_max": max(batch_sizes),
                "seconds": seconds, "seconds_per_step": seconds / steps, "examples_per_second": examples / seconds,
                "peak_allocated_mib": torch.cuda.max_memory_allocated(device) / 2**20 if device.type == "cuda" else None,
                "peak_reserved_mib": torch.cuda.max_memory_reserved(device) / 2**20 if device.type == "cuda" else None,
                "free_vram_mib": free / 2**20 if free is not None else None,
                "total_vram_mib": total / 2**20 if total is not None else None,
                "last_loss": losses[-1], "notes": "Includes loader, transfers, feature expansion, forward/backward, clipping, optimizer and finite checks. Warmup excluded. No validation/logging/checkpoint overhead; no accuracy conclusion."}
    finally:
        # Drop worker iterator and all model/optimizer references even on OOM.
        # The CLI also collects after handling the exception, when its traceback
        # no longer holds intermediate CUDA tensors.
        iterator = loader = forward_model = optimizer = model = None
        dataset.close()
        gc.collect()


def _training_contract(config):
    result = {key: value for key, value in config.items() if key not in OPERATIONAL_KEYS}
    # Older ReLU checkpoints omitted this newly explicit architecture field.
    result["model"] = canonical_spec(result["model"])
    return result


def run_training(data_dir, config, run_dir, device, resume=None) -> dict:
    config = normalize_config(config)
    device = torch.device(device)
    run = Path(run_dir)
    run.mkdir(parents=True, exist_ok=True)
    with RunLock(run):
        train_data = validation_data = None
        try:
            train_data = PositionDataset(data_dir, split="train")
            validation_data = PositionDataset(data_dir, split="validation")
            return _run_training(data_dir, config, run, device, resume, train_data, validation_data)
        finally:
            if train_data is not None:
                train_data.close()
            if validation_data is not None:
                validation_data.close()


def _run_training(data_dir, config, run, device, resume, train_data, validation_data):
    torch.set_num_threads(config["cpu_threads"])
    seed_everything(config["seed"], config["deterministic"])
    manifest = train_data.manifest
    if manifest.get("feature_version") != FEATURE_VERSION:
        raise ValueError("Dataset feature version is incompatible")
    if not manifest.get("fingerprint") or validation_data.manifest.get("fingerprint") != manifest["fingerprint"]:
        raise ValueError("Training and validation must have the same fixed release fingerprint")
    if not len(train_data) or not len(validation_data):
        raise ValueError("Training and validation splits must both be nonempty")
    generator = torch.Generator().manual_seed(config["seed"])
    val_generator = torch.Generator().manual_seed(config["seed"] + 1)
    loader = _loader(train_data, config, device, generator, True)
    validation_loader = _loader(validation_data, config, device, val_generator, False)
    model = build_model(config["model"]).to(device)
    optimizer = _optimizer(model, config)
    amp_dtype = _amp_dtype(config, device)
    runtime = {"device": str(device), "precision": "bfloat16_autocast" if amp_dtype else "float32",
               "torch_version": str(torch.__version__), "gpu_name": torch.cuda.get_device_name(device) if device.type == "cuda" else None}
    completed_epoch, step, best_metric, best_epoch, bad_epochs = 0, 0, float("inf"), 0, 0
    patience_metric = float("inf")
    history = []
    if resume:
        resume = Path(resume)
        if resume.resolve().parent != run.resolve():
            raise ValueError("Resume into the checkpoint's own run directory to preserve its history/best model")
        model, saved = load_checkpoint(resume, device)
        if saved.get("data_fingerprint") != manifest["fingerprint"]:
            raise ValueError("Refusing resume: dataset fingerprint changed")
        if _training_contract(saved["config"]) != _training_contract(config):
            raise ValueError("Refusing resume: training configuration changed; use a new run for a new experiment")
        if saved.get("runtime", {}).get("precision") != runtime["precision"]:
            raise ValueError("Refusing resume: numerical precision changed")
        optimizer = _optimizer(model, config)
        optimizer.load_state_dict(saved["optimizer"])
        completed_epoch, step = saved["epoch"], saved["step"]
        best_metric, best_epoch = saved["best_metric"], saved.get("best_epoch", 0)
        patience_metric = saved.get("patience_metric", best_metric)
        bad_epochs, history = saved.get("bad_epochs", 0), saved.get("history", [])
        generator.set_state(saved["loader_rng_state"]["train"])
        val_generator.set_state(saved["loader_rng_state"]["validation"])
        _restore_rng(saved["rng_state"])
        _write_history(run, history)
        if completed_epoch and best_epoch == completed_epoch:
            _atomic_checkpoint(run / "best.pt", saved)
    elif (run / "last.pt").exists() or (run / "metrics.csv").exists():
        raise ValueError("Run already contains training results; use --resume or a new run directory")
    if config["epochs"] < completed_epoch:
        raise ValueError("Requested total epochs cannot be lower than completed epochs in the checkpoint")
    if resume and (config["epochs"] == completed_epoch or bad_epochs >= config["patience"]):
        status = "early_stopped" if bad_epochs >= config["patience"] else "already_completed"
        result = {"status": status, "epochs_completed": completed_epoch, "steps": step,
                  "best_epoch": best_epoch, "best_validation_huber": best_metric,
                  "best_checkpoint": str(run / "best.pt"), "last_checkpoint": str(run / "last.pt")}
        _atomic_json(run / "result.json", result)
        print(f"Resume recovered completed artifacts; no extra epoch needed ({status}).")
        return result
    _atomic_json(run / "config.json", config)
    _atomic_json(run / "environment.json", runtime)
    _atomic_json(run / "data_manifest.json", manifest)
    def checkpoint():
        return {"checkpoint_version": CHECKPOINT_VERSION, "model_spec": config["model"], "feature_version": FEATURE_VERSION,
                "target": {"perspective": "white", "units": "pawns", "clip_pawns": config["clip_pawns"]},
                "state_dict": model.state_dict(), "optimizer": optimizer.state_dict(), "config": config,
                "runtime": runtime, "data_fingerprint": manifest["fingerprint"], "epoch": completed_epoch, "step": step,
                "best_metric": best_metric, "best_epoch": best_epoch, "patience_metric": patience_metric,
                "bad_epochs": bad_epochs, "history": history,
                "rng_state": _rng_state(), "loader_rng_state": {"train": generator.get_state(), "validation": val_generator.get_state()},
                "resume_semantics": "Complete-epoch boundary; interrupted partial epoch is discarded."}
    if not resume:
        _atomic_checkpoint(run / "last.pt", checkpoint())
    forward_model = torch.compile(model) if config["compile"] else model
    writer = None
    if config["tensorboard"]:
        try:
            from torch.utils.tensorboard import SummaryWriter
            writer = SummaryWriter(str(run / "tensorboard"), purge_step=step if resume else None)
        except ImportError:
            print("TensorBoard is unavailable; CSV and JSONL metrics remain enabled.")
    start_wall = time.perf_counter()
    previous_wall = history[-1]["summary"]["total_seconds"] if history else 0.0
    interrupted_epoch = completed_epoch + 1
    stopped = "completed"
    try:
        with Display() as display:
            display.print(f"[bold cyan]{config['model']['name']}[/bold cyan] | {model_statistics(config['model'])['parameters']:,} parameters | {runtime['device']} {runtime['precision']}")
            display.print(f"Train {len(train_data):,}; validation {len(validation_data):,}; batch {config['batch_size']:,}; resume at completed epoch {completed_epoch}.")
            for epoch in range(completed_epoch + 1, config["epochs"] + 1):
                interrupted_epoch = epoch
                forward_model.train()
                if device.type == "cuda":
                    torch.cuda.reset_peak_memory_stats(device)
                train_task = display.add(f"Epoch {epoch}/{config['epochs']} train", len(train_data))
                _synchronize(device)
                started = time.perf_counter()
                loss_sum, examples = 0.0, 0
                for batch in loader:
                    loss, count, norm = train_step(forward_model, optimizer, batch, config, device, amp_dtype)
                    step += 1
                    loss_sum += loss * count
                    examples += count
                    memory = f"GPU {torch.cuda.memory_allocated(device) / 2**20:.0f} MiB" if device.type == "cuda" else "CPU FP32"
                    display.advance(train_task, count, f"loss {loss_sum / examples:.4f}", memory)
                    if writer and step % config["log_every_steps"] == 0:
                        writer.add_scalar("step/train_huber", loss, step)
                        writer.add_scalar("step/gradient_norm_before_clip", norm, step)
                _synchronize(device)
                train_seconds = time.perf_counter() - started
                display.remove(train_task)
                val_task = display.add(f"Epoch {epoch}/{config['epochs']} validation", len(validation_data))
                val_started = time.perf_counter()
                validation = evaluate_model(forward_model, validation_loader, device, config["clip_pawns"], config["huber_delta"], amp_dtype,
                                            lambda count, mae: display.advance(val_task, count, f"MAE {mae:.1f} cp"))
                _synchronize(device)
                validation_seconds = time.perf_counter() - val_started
                display.remove(val_task)
                completed_epoch = epoch
                improved = validation["huber"] < best_metric
                if improved:
                    best_metric, best_epoch = validation["huber"], epoch
                if validation["huber"] < patience_metric - config["min_delta"]:
                    patience_metric, bad_epochs = validation["huber"], 0
                else:
                    bad_epochs += 1
                row = {"epoch": epoch, "step": step, "train_huber": loss_sum / examples,
                       "val_huber": validation["huber"], "val_mae_cp": validation["mae_cp"],
                       "val_rmse_cp": validation["rmse_cp"], "val_within_50_cp": validation["within_50_cp"],
                       "train_seconds": train_seconds, "validation_seconds": validation_seconds,
                       "examples_per_second": examples / train_seconds,
                       "peak_allocated_mib": torch.cuda.max_memory_allocated(device) / 2**20 if device.type == "cuda" else 0.0,
                       "total_seconds": previous_wall + time.perf_counter() - start_wall,
                       "learning_rate": optimizer.param_groups[0]["lr"]}
                history.append({"summary": row, "validation": validation})
                saved = checkpoint()
                _atomic_checkpoint(run / "last.pt", saved)
                if improved:
                    _atomic_checkpoint(run / "best.pt", saved)
                _write_history(run, history)
                if writer:
                    writer.add_scalar("epoch/train_huber", row["train_huber"], epoch)
                    for key in ("huber", "mae_cp", "rmse_cp", "within_25_cp", "within_50_cp", "within_100_cp"):
                        writer.add_scalar(f"validation/{key}", validation[key], epoch)
                    writer.flush()
                remaining = (config["epochs"] - epoch) * (train_seconds + validation_seconds)
                display.print(f"[green]Epoch {epoch}[/green]: train {row['train_huber']:.4f} | val {validation['huber']:.4f} | MAE {validation['mae_cp']:.1f} cp | {row['examples_per_second']:,.0f} pos/s | approx remaining {remaining / 60:.1f} min" + (" [bold]BEST[/bold]" if improved else ""))
                if bad_epochs >= config["patience"]:
                    stopped = "early_stopped"
                    display.print(f"Early stop after {bad_epochs} epochs without the required validation-Huber improvement.")
                    break
    except KeyboardInterrupt:
        _atomic_json(run / "interrupted.json", {"resume_from": str(run / "last.pt"),
                      "interrupted_epoch": interrupted_epoch,
                      "policy": "Resume the last atomically saved completed epoch; partial work is discarded."})
        print(f"Interrupted. Resume {run / 'last.pt'}; unfinished epoch work is discarded.")
        raise
    finally:
        if writer:
            writer.close()
    result = {"status": stopped, "epochs_completed": completed_epoch, "steps": step,
              "best_epoch": best_epoch, "best_validation_huber": best_metric,
              "best_checkpoint": str(run / "best.pt"), "last_checkpoint": str(run / "last.pt")}
    _atomic_json(run / "result.json", result)
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", required=True, type=Path)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--run", required=True, type=Path)
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    parser.add_argument("--resume", type=Path)
    parser.add_argument("--epochs", type=int)
    parser.add_argument("--batch-size", type=int)
    parser.add_argument("--workers", type=int)
    parser.add_argument("--cpu-threads", type=int)
    parser.add_argument("--benchmark-steps", type=int, default=0)
    parser.add_argument("--compile", action="store_true", default=None)
    parser.add_argument("--no-tensorboard", action="store_true")
    args = parser.parse_args(argv)
    try:
        config = json.loads(args.config.read_text(encoding="utf-8"))
        for name in ("epochs", "batch_size", "workers", "cpu_threads", "compile"):
            if getattr(args, name) is not None:
                config[name] = getattr(args, name)
        if args.no_tensorboard:
            config["tensorboard"] = False
        config = normalize_config(config)
        device = resolve_device(args.device)
        if args.benchmark_steps:
            if args.resume:
                raise ValueError("Benchmark uses a fresh disposable model; do not combine --resume with --benchmark-steps")
            result = benchmark_production(args.data, config, device, args.benchmark_steps)
            args.run.mkdir(parents=True, exist_ok=True)
            _atomic_json(args.run / "benchmark.json", result)
        else:
            result = run_training(args.data, config, args.run, device, args.resume)
        print(json.dumps(result, indent=2, allow_nan=False))
        return 0
    except KeyboardInterrupt:
        return 130
    except (ValueError, FloatingPointError) as exc:
        parser.exit(2, f"Error: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
