"""Read-only device checks plus an explicit local diagnostics artifact.

No cloud API, credentials, driver changes, or training jobs are involved.
"""
from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import sysconfig
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _command(command: list[str], timeout: int = 30) -> dict[str, Any]:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout,
                                encoding="utf-8", errors="replace", check=False)
        return {"returncode": result.returncode, "stdout": result.stdout.strip(),
                "stderr": result.stderr.strip()}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"returncode": None, "error": str(exc)}


def _smoke_test(torch: Any, device: str, *, bf16: bool = False) -> dict[str, Any]:
    """Actually run matmul, differentiation, and AdamW rather than just detect CUDA."""
    started = time.perf_counter()
    try:
        x = torch.randn(64, 64, device=device, requires_grad=True)
        weight = torch.nn.Parameter(torch.randn(64, 64, device=device) / 8)
        optimizer = torch.optim.AdamW([weight], lr=1e-4)
        if bf16:
            with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
                prediction = x @ weight
                loss = prediction.float().square().mean()
            output_dtype = str(prediction.dtype)
            if prediction.dtype != torch.bfloat16:
                raise RuntimeError("BF16 autocast did not produce a BF16 matmul output")
        else:
            prediction = x @ weight
            loss = prediction.square().mean()
            output_dtype = str(prediction.dtype)
        loss.backward()
        if not torch.isfinite(loss).item() or not torch.isfinite(weight.grad).all().item():
            raise RuntimeError("Non-finite loss or gradient")
        optimizer.step()
        if not torch.isfinite(weight).all().item():
            raise RuntimeError("Non-finite weights after optimizer step")
        if device == "cuda":
            torch.cuda.synchronize()
        return {"passed": True, "device": device, "output_dtype": output_dtype,
                "loss": float(loss.detach().cpu()), "seconds": time.perf_counter() - started}
    except Exception as exc:
        return {"passed": False, "device": device, "error": f"{type(exc).__name__}: {exc}"}


def _lab_step(torch: Any, device: str, bf16: bool = False) -> dict[str, Any]:
    """Exercise our real encoding and model, including deterministic kernels."""
    import numpy as np
    from .features import encode_fen, expand_batch, expand_numpy
    from .models import build_model

    previous = torch.are_deterministic_algorithms_enabled()
    try:
        torch.use_deterministic_algorithms(True)
        fens = ["rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq -",
                "7r/1p3k2/p1bPR3/5p2/2B2P1p/8/PP4P1/3K4 b - -"]
        packed = np.stack([encode_fen(fen) for fen in fens])
        inputs = expand_batch(torch.from_numpy(packed).to(device))
        expected = torch.from_numpy(np.stack([expand_numpy(row) for row in packed])).to(device)
        if not torch.equal(inputs, expected):
            raise RuntimeError("Device feature expansion differs from reference encoding")
        model = build_model("small").to(device).train()
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-4)
        with torch.autocast(device_type=device, dtype=torch.bfloat16 if bf16 else torch.float32, enabled=bf16):
            predictions = model(inputs)
        loss = (predictions.float() - 0.1).square().mean()
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0, error_if_nonfinite=True)
        optimizer.step()
        if not torch.isfinite(loss).item() or not all(torch.isfinite(p).all().item() for p in model.parameters()):
            raise RuntimeError("Non-finite lab training step")
        if device == "cuda":
            torch.cuda.synchronize()
        return {"passed": True, "device": device, "shape": list(predictions.shape),
                "precision": "bfloat16_autocast" if bf16 else "float32", "deterministic": True}
    except Exception as exc:
        return {"passed": False, "error": f"{type(exc).__name__}: {exc}"}
    finally:
        torch.use_deterministic_algorithms(previous)


def _dependency_checks(torch: Any) -> dict[str, dict[str, Any]]:
    """Check working imports/integration, including headless plots and event writing."""
    import io

    def numpy_bridge() -> None:
        import numpy as np
        array = np.array([1.0, 2.0], dtype=np.float32)
        np.testing.assert_array_equal(torch.from_numpy(array).numpy(), array)

    def chess_rules() -> None:
        import chess
        board = chess.Board()
        if not board.is_valid() or board.legal_moves.count() != 20:
            raise RuntimeError("Unexpected starting-position legal-move check")

    def zstandard_roundtrip() -> None:
        import zstandard
        payload = b"Mr. Bits compression smoke test"
        encoded = zstandard.ZstdCompressor().compress(payload)
        if zstandard.ZstdDecompressor().decompress(encoded) != payload:
            raise RuntimeError("Zstandard round trip failed")

    def rich_output() -> None:
        from rich.console import Console
        output = io.StringIO()
        Console(file=output, force_terminal=False).print("Mr. Bits")
        if "Mr. Bits" not in output.getvalue():
            raise RuntimeError("Rich output failed")

    def headless_plot() -> None:
        cache = Path(os.environ.get("MPLCONFIGDIR", Path.cwd() / ".cache" / "matplotlib"))
        cache.mkdir(parents=True, exist_ok=True)
        os.environ.setdefault("MPLCONFIGDIR", str(cache))
        import matplotlib
        matplotlib.use("Agg", force=True)
        import matplotlib.pyplot as plt
        buffer = io.BytesIO()
        figure, axes = plt.subplots()
        try:
            axes.plot([0, 1], [1, 0])
            figure.savefig(buffer, format="png")
            if not buffer.getvalue().startswith(b"\x89PNG"):
                raise RuntimeError("Matplotlib did not produce a PNG")
        finally:
            plt.close(figure)

    def tensorboard_event() -> None:
        from torch.utils.tensorboard import SummaryWriter
        with tempfile.TemporaryDirectory(prefix="chesslab-doctor-") as directory:
            writer = SummaryWriter(directory)
            try:
                writer.add_scalar("doctor/smoke", 1.0, 0)
                writer.flush()
            finally:
                writer.close()
            if not list(Path(directory).glob("events.out.tfevents.*")):
                raise RuntimeError("TensorBoard did not create an event file")

    checks = {}
    for name, function in (("numpy_torch_bridge", numpy_bridge), ("chess_rules", chess_rules),
                           ("zstandard_roundtrip", zstandard_roundtrip), ("rich_output", rich_output),
                           ("headless_plot_png", headless_plot), ("tensorboard_event", tensorboard_event)):
        try:
            function()
            checks[name] = {"passed": True}
        except Exception as exc:
            checks[name] = {"passed": False, "error": f"{type(exc).__name__}: {exc}"}
    return checks


def inspect_environment(device: str = "auto", require_cuda: bool = False,
                        check_dependencies: bool = False) -> dict[str, Any]:
    os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
    report: dict[str, Any] = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "python": sys.version, "python_executable": sys.executable,
        "platform": platform.platform(), "machine": platform.machine(),
        "prefix": sys.prefix, "base_prefix": sys.base_prefix,
        "inside_venv": sys.prefix != sys.base_prefix,
        "requested_device": device, "require_cuda": require_cuda,
        "check_dependencies": check_dependencies,
        "checks": {}, "warnings": [], "errors": [], "packages": {},
    }
    if not (3, 11) <= sys.version_info[:2] < (3, 15):
        report["errors"].append("This package supports standard CPython 3.11–3.14.")
    if sys.implementation.name != "cpython" or sysconfig.get_config_var("Py_GIL_DISABLED"):
        report["errors"].append("The reference wheels require standard CPython, not PyPy or a free-threaded build.")
    for package in ("torch", "numpy", "chess", "zstandard", "rich", "matplotlib", "tensorboard"):
        try:
            report["packages"][package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            report["packages"][package] = None
            report["warnings"].append(f"Package not installed: {package}")
    driver_tool = shutil.which("nvidia-smi")
    report["nvidia_smi"] = _command([driver_tool, "--query-gpu=index,name,driver_version,memory.total",
                                     "--format=csv,noheader"]) if driver_tool else {"available": False}
    try:
        import torch
    except Exception as exc:
        report["errors"].append(f"Cannot import torch: {type(exc).__name__}: {exc}")
        report["passed"] = False
        return report
    report["torch"] = {"version": torch.__version__, "cuda_build": torch.version.cuda,
                        "module_file": torch.__file__}
    version = re.match(r"(\d+)\.(\d+)", torch.__version__)
    if version is None or tuple(map(int, version.groups())) < (2, 7):
        report["errors"].append("Torch >=2.7 is required.")
    cpu_check = _smoke_test(torch, "cpu")
    report["checks"]["cpu_fp32"] = cpu_check
    if not cpu_check["passed"]:
        report["errors"].append("CPU forward/backward/optimizer test failed.")
    report["checks"]["cpu_lab_training_step"] = _lab_step(torch, "cpu")
    if not report["checks"]["cpu_lab_training_step"]["passed"]:
        report["errors"].append("Actual lab CPU feature/evaluator step failed.")
    cuda_available = torch.cuda.is_available()
    report["torch"]["cuda_available"] = cuda_available
    use_cuda = device == "cuda" or (device == "auto" and cuda_available) or require_cuda
    if use_cuda and not cuda_available:
        report["errors"].append("CUDA was requested but is unavailable. Use a GPU-compatible image/build.")
    elif use_cuda:
        try:
            properties = torch.cuda.get_device_properties(0)
            report["torch"].update({
                "device_count": torch.cuda.device_count(), "device_name": properties.name,
                "compute_capability": list(torch.cuda.get_device_capability(0)),
                "device_memory_bytes": properties.total_memory,
                "compiled_architectures": torch.cuda.get_arch_list(),
            })
            cuda_check = _smoke_test(torch, "cuda")
            report["checks"]["cuda_fp32"] = cuda_check
            if not cuda_check["passed"]:
                report["errors"].append("CUDA forward/backward/optimizer test failed.")
            if torch.cuda.is_bf16_supported():
                bf16_check = _smoke_test(torch, "cuda", bf16=True)
                report["checks"]["cuda_bf16"] = bf16_check
                if not bf16_check["passed"]:
                    report["errors"].append("CUDA BF16 autocast test failed.")
            else:
                report["checks"]["cuda_bf16"] = {"passed": None, "skipped": "BF16 not supported by this device/build"}
                report["warnings"].append("BF16 is unavailable; use FP32 or a supported precision.")
            report["torch"]["peak_allocated_bytes"] = torch.cuda.max_memory_allocated()
            report["torch"]["peak_reserved_bytes"] = torch.cuda.max_memory_reserved()
            report["checks"]["cuda_lab_training_step"] = _lab_step(torch, "cuda", bf16=torch.cuda.is_bf16_supported())
            if not report["checks"]["cuda_lab_training_step"]["passed"]:
                report["errors"].append("Actual deterministic lab CUDA feature/evaluator step failed.")
        except Exception as exc:
            report["errors"].append(f"Cannot inspect/run CUDA: {type(exc).__name__}: {exc}")
    elif device == "auto":
        report["warnings"].append("CPU-only check. This does not validate a future GPU host.")
    if check_dependencies:
        requirements_path = Path(__file__).resolve().parent.parent / "requirements.txt"
        if requirements_path.exists():
            pins = dict(re.findall(r"^([A-Za-z0-9_-]+)==([0-9.]+)\s*$",
                                   requirements_path.read_text(encoding="utf-8"), re.MULTILINE))
            report["reference_dependency_pins"] = pins
            for package, expected in pins.items():
                actual = report["packages"].get(package)
                if actual != expected:
                    report["errors"].append(f"Dependency version mismatch: {package}=={expected} required; found {actual!r}.")
        dependency_checks = _dependency_checks(torch)
        report["checks"].update(dependency_checks)
        for name, result in dependency_checks.items():
            if not result["passed"]:
                report["errors"].append(f"Dependency/integration check failed: {name}.")
    else:
        report["warnings"].append("Full dependency integration was not checked; use --check-dependencies for release/setup validation.")
    report["passed"] = not report["errors"]
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check real CPU/CUDA operations and record the environment.")
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    parser.add_argument("--require-cuda", action="store_true", help="Fail if a real CUDA step cannot run")
    parser.add_argument("--strict-deps", "--check-dependencies", dest="check_dependencies", action="store_true",
                        help="Check pinned versions, NumPy/Torch bridge, compression, plotting and TensorBoard")
    parser.add_argument("--output", type=Path, default=Path("diagnostics/environment.json"))
    args = parser.parse_args(argv)
    if args.require_cuda and args.device == "cpu":
        parser.error("--device cpu and --require-cuda are mutually exclusive")
    report = inspect_environment(args.device, args.require_cuda, args.check_dependencies)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    freeze = _command([sys.executable, "-m", "pip", "freeze"], timeout=60)
    freeze_path = args.output.with_name(args.output.stem + "-pip-freeze.txt")
    if freeze.get("returncode") == 0:
        freeze_path.write_text(freeze["stdout"] + "\n", encoding="utf-8")
        report["pip_freeze_file"] = freeze_path.name
    else:
        report["warnings"].append("pip freeze failed; inspect the environment manually.")
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    for name, check in report["checks"].items():
        state = "PASS" if check["passed"] else "SKIP" if check["passed"] is None else "FAIL"
        print(f"[{state}] {name}: {check.get('output_dtype', check.get('error', check.get('skipped', '')))}")
    for warning in report["warnings"]:
        print(f"[NOTE] {warning}")
    for error in report["errors"]:
        print(f"[FAIL] {error}", file=sys.stderr)
    print(f"Environment report: {args.output}")
    print("Doctor smoke-test latency is not a training-throughput benchmark.")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
