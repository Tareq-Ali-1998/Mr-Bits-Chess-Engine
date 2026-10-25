"""Create, inspect and compare independent experiments on reusable data."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from .models import model_statistics
from .train import normalize_config


def read_config(path: Path) -> dict:
    return normalize_config(json.loads(path.read_text(encoding="utf-8")))


def config_summary(path: Path) -> dict:
    config = read_config(path)
    spec = config["model"]
    return {"config": str(path), "model": spec["name"], "kind": spec["kind"],
            "activation": spec.get("activation", "relu"), **model_statistics(spec),
            "batch_size": config["batch_size"], "epochs": config["epochs"], "seed": config["seed"]}


def compare_runs(paths: list[Path], include_test: bool = False) -> dict:
    rows = []
    for run in paths:
        config = read_config(run / "config.json")
        manifest = json.loads((run / "data_manifest.json").read_text(encoding="utf-8"))
        with (run / "metrics.csv").open(encoding="utf-8", newline="") as stream:
            history = list(csv.DictReader(stream))
        if not history:
            raise ValueError(f"No completed epoch metrics in {run}")
        # best.pt selection uses the actual minimum; min_delta is a separate
        # patience condition. Compare the same checkpoint's MAE, not each metric's
        # independently most flattering epoch.
        best = min(history, key=lambda row: float(row["val_huber"]))
        target_contract = {"clip_pawns": config["clip_pawns"], "huber_delta": config["huber_delta"],
                           "perspective": "white", "units": "pawns"}
        row = {"run": str(run), "model": config["model"],
               "parameters": model_statistics(config["model"])["parameters"],
               "data_fingerprint": manifest["fingerprint"], "target_contract": target_contract,
               "batch_size": config["batch_size"], "seed": config["seed"],
               "epochs_completed": int(history[-1]["epoch"]), "steps": int(history[-1]["step"]),
               "best_epoch": int(best["epoch"]), "best_val_huber": float(best["val_huber"]),
               "mae_cp_at_best_epoch": float(best["val_mae_cp"]),
               "training_seconds": sum(float(item["train_seconds"]) for item in history)}
        if include_test:
            path = run / "test.json"
            if path.exists():
                test = json.loads(path.read_text(encoding="utf-8"))
                if test.get("data_fingerprint") != manifest["fingerprint"]:
                    raise ValueError(f"Stale or incompatible test report: {path}")
                row["test_metrics"] = test["metrics"]
        rows.append(row)
    groups = {}
    for row in rows:
        key = json.dumps([row["data_fingerprint"], row["target_contract"]], sort_keys=True)
        groups.setdefault(key, []).append(row)
    return {"schema": "chesslab.experiment-comparison.v1",
            "comparable_groups": [sorted(group, key=lambda row: row["best_val_huber"]) for group in groups.values()],
            "notes": "Grouped by identical prepared release and target/loss contract; ordered by validation Huber within a group. MAE is from that checkpoint's epoch. Different seeds, update counts and training budgets remain explicit. This does not select an engine-strength winner. Use validation for decisions; test inclusion is explicit."}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    listing = sub.add_parser("list", help="Inspect all JSON configurations without training")
    listing.add_argument("--configs", type=Path, default=Path("configs"))
    clone = sub.add_parser("new", help="Clone a configuration into a NEW independent experiment")
    clone.add_argument("--base", type=Path, required=True)
    clone.add_argument("--output", type=Path, required=True)
    clone.add_argument("--activation", choices=("relu", "gelu", "silu", "tanh"))
    clone.add_argument("--hidden", type=int, nargs="+", help="MLP widths only")
    clone.add_argument("--batch-size", type=int)
    clone.add_argument("--epochs", type=int)
    clone.add_argument("--seed", type=int)
    compare = sub.add_parser("compare", help="Compare completed runs; does not train or touch checkpoints")
    compare.add_argument("--runs", nargs="+", type=Path, required=True)
    compare.add_argument("--output", type=Path, required=True)
    compare.add_argument("--include-test", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "list":
            paths = sorted(args.configs.rglob("*.json"))
            if not paths:
                raise ValueError("No experiment configurations found")
            result = [config_summary(path) for path in paths]
        elif args.command == "new":
            if args.output.exists():
                raise FileExistsError(f"Refusing to overwrite an experiment: {args.output}")
            config = read_config(args.base)
            if args.activation:
                config["model"]["activation"] = args.activation
            if args.hidden is not None:
                if config["model"]["kind"] != "mlp":
                    raise ValueError("--hidden applies only to an MLP; edit width/blocks/head for a residual model")
                config["model"]["hidden"] = args.hidden
            for name in ("batch_size", "epochs", "seed"):
                if getattr(args, name) is not None:
                    config[name] = getattr(args, name)
            config = normalize_config(config)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("x", encoding="utf-8") as stream:
                json.dump(config, stream, indent=2)
                stream.write("\n")
            result = config_summary(args.output)
        else:
            result = compare_runs(args.runs, args.include_test)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        print(json.dumps(result, indent=2, allow_nan=False))
        return 0
    except (ValueError, OSError) as exc:
        parser.exit(2, f"Error: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
