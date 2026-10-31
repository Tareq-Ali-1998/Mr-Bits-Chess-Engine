"""Build and run isolated v5/v6 policy diagnostics; never launch a bot or game.

From engines: python tests/run_kernel_v56_tests.py
Reports include real compiler/run results, source hashes, model hash, and counters.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile
import time

ENGINES = Path(__file__).resolve().parents[1]
REPORTS = ENGINES.parent / "Mr Bits Docs" / "ChatGPT Neural Network Lab" / "diagnostics" / "kernel-v5-v6-20261029"


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def save(path: Path, value) -> None:
    # Keep exact successful evidence when a later attempt cannot run.
    if path.is_file():
        previous = path.read_bytes()
        try:
            successful = json.loads(previous).get("status") == "passed"
        except (ValueError, AttributeError):
            successful = False
        if successful:
            history = path.parent / "history"
            history.mkdir(exist_ok=True)
            archived = history / f"{path.stem}-{hashlib.sha256(previous).hexdigest()[:12]}.json"
            if not archived.exists():
                archived.write_bytes(previous)
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def failure_status(error: Exception) -> str:
    """An explicit Windows policy block is an external block, not a test failure."""
    return "blocked" if isinstance(error, OSError) and getattr(error, "winerror", None) == 4551 else "failed"


def aggregate_status(reports: list[dict]) -> str:
    statuses = {report["status"] for report in reports}
    if not statuses or "failed" in statuses:
        return "failed"
    return "blocked" if "blocked" in statuses else "passed"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", choices=("v5", "v6", "both"), default="both")
    parser.add_argument("--cxx", default=shutil.which("g++"))
    parser.add_argument("--weights-dir", type=Path, default=ENGINES / "Neural Networks")
    parser.add_argument("--report-dir", type=Path, default=REPORTS)
    parser.add_argument("--timeout", type=int, default=120, help="Seconds allowed for each compilation and run")
    args = parser.parse_args(argv)
    if not args.cxx:
        parser.error("g++ was not found; supply --cxx PATH_TO_G++")
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    weights = args.weights_dir.resolve() / "Small" / "weights.bin"
    if not weights.is_file():
        parser.error(f"Missing Small weights: {weights}")
    compiler = shutil.which(args.cxx) or str(Path(args.cxx).resolve())
    env = dict(os.environ)
    env["PATH"] = str(Path(compiler).resolve().parent) + os.pathsep + env.get("PATH", "")
    compiler_version = subprocess.run([compiler, "--version"], capture_output=True, text=True,
                                      check=True, timeout=15).stdout.strip()
    args.report_dir.mkdir(parents=True, exist_ok=True)
    reports = []
    for variant in (("v5", "v6") if args.only == "both" else (args.only,)):
        started = time.perf_counter()
        sources = [Path(__file__), ENGINES / "tests/kernel_v56_policy_test.cpp",
                   ENGINES / f"Kernels/{variant}/Kernel-{variant}.cpp",
                   ENGINES / "Kernels/Neural Search.hpp", ENGINES / "Chess State.hpp",
                   ENGINES / "Neural Networks/Move Ordering.hpp", ENGINES / "Neural Networks/common.hpp",
                   ENGINES / "Neural Networks/Small/Small.hpp", ENGINES / "Neural Networks/Large/Large.hpp"]
        receipt = {"schema": "mrbits.v56-policy-diagnostics.v1", "variant": variant,
                   "started_utc": datetime.now(timezone.utc).isoformat(), "status": "failed",
                   "python": platform.python_version(), "compiler": compiler, "compiler_version": compiler_version,
                   "source_sha256": {str(path.relative_to(ENGINES)): sha256(path) for path in sources},
                   "small_weights_sha256": sha256(weights),
                   "scope": "Offline renamed-main harness; no bot/worker main/Stockfish/cloud/network execution",
                   "reference_contract": "Exhaustive minimax shares inherited move generation and leaf evaluation; it is not a proof of FIDE legality."}
        try:
            with tempfile.TemporaryDirectory(prefix=f"Mr Bits {variant} policy ") as temporary:
                binary = Path(temporary) / f"kernel_{variant}_policy_test.exe"
                command = [compiler, "-std=c++17", "-O2", "-I", str(ENGINES)]
                if variant == "v6":
                    command.append("-DMRBITS_TEST_V6")
                command += [str(ENGINES / "tests/kernel_v56_policy_test.cpp"), "-o", str(binary)]
                compiled = subprocess.run(command, cwd=ENGINES, env=env, capture_output=True,
                                          text=True, timeout=args.timeout)
                receipt["compile"] = {"command": command, "exit_code": compiled.returncode,
                                      "stdout": compiled.stdout, "stderr": compiled.stderr}
                if compiled.returncode:
                    raise RuntimeError("Diagnostic compilation failed")
                command = [str(binary), str(args.weights_dir.resolve())]
                run_started = time.perf_counter()
                receipt["run"] = {"command": command, "started": False}
                executed = subprocess.run(command, cwd=ENGINES, env=env, capture_output=True,
                                          text=True, timeout=args.timeout)
                receipt["run"] = {"command": command, "started": True, "exit_code": executed.returncode,
                                  "seconds": time.perf_counter() - run_started,
                                  "stdout": executed.stdout, "stderr": executed.stderr}
                try:
                    result = json.loads(executed.stdout)
                except json.JSONDecodeError as error:
                    raise RuntimeError("Diagnostic did not produce its JSON report") from error
                receipt["result"] = result
                if executed.returncode or not result.get("passed"):
                    raise RuntimeError(result.get("error", "Diagnostic execution failed"))
                receipt["status"] = "passed"
        except Exception as error:
            receipt["status"] = failure_status(error)
            receipt["error"] = f"{type(error).__name__}: {error}"
            if isinstance(error, OSError):
                receipt["os_error"] = {"errno": error.errno, "winerror": getattr(error, "winerror", None),
                                       "filename": error.filename, "message": str(error)}
        receipt["seconds"] = time.perf_counter() - started
        receipt["completed_utc"] = datetime.now(timezone.utc).isoformat()
        save(args.report_dir / f"kernel_{variant}_policy_test.json", receipt)
        reports.append(receipt)
        check_count = receipt.get("result", {}).get("checks")
        checks_text = (f"{check_count} checks" if check_count is not None else
                       "check results unavailable" if receipt.get("run", {}).get("started") else "checks not executed")
        print(f"{variant}: {receipt['status']} ({checks_text}; {receipt['seconds']:.2f}s)", flush=True)
    summary = {"schema": "mrbits.v56-policy-summary.v1", "completed_utc": datetime.now(timezone.utc).isoformat(),
               "status": aggregate_status(reports),
               "reports": [{"variant": r["variant"], "status": r["status"],
                            "checks": r.get("result", {}).get("checks"),
                            "file": f"kernel_{r['variant']}_policy_test.json"} for r in reports]}
    save(args.report_dir / "v56-policy-tests-summary.json", summary)
    return 0 if summary["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
