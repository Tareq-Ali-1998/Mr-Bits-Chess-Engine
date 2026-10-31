"""Choose/build a Kernel before launching the existing lichess-bot application."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from kernel_tools import ENGINES, build_controller, build_kernel, require_weights, select, versions

DESCRIPTIONS = {"original": "original search", "v1": "your Large/top-four experiment",
                "v2": "ordering only; retain every candidate", "v3": "eight quiet root moves plus captures/promotions",
                "v4": "Small-only leaf evaluation; sort from depth six",
                "v5": "Small + handcrafted blend; retain every candidate",
                "v6": "v5 foundation + guarded late quiet move reductions",
                "v7": "legal search + check-aware quiescence + Small blend",
                "v8": "v7 legal/tactical search + 100% Small position evaluation",
                "v9": "Large top-three beam + handcrafted static evaluation",
                "v10": "Large top-three beam + 50/50 handcrafted/Small value",
                "v11": "Small-only value + PVS re-search + exact-position value cache"}


def choose(available: list[str]) -> str:
    default = "original"
    try:
        configured = json.loads((ENGINES / "kernel-selection.json").read_text(encoding="utf-8"))["version"]
        if configured in available: default = configured
    except (OSError, ValueError, KeyError, TypeError):
        pass
    print("\nMr. Bits - choose a Kernel for this application run\n")
    for index, version in enumerate(available):
        print(f"  {index}. {version:8} {DESCRIPTIONS.get(version, 'experimental version folder')}")
    while True:
        value = input(f"\nVersion name or number [Enter = {default}]: ").strip().lower()
        if not value: return default
        if value in available: return value
        if value.isdecimal() and int(value) < len(available): return available[int(value)]
        print("Choose one of the versions listed above.")


def probe_kernel_startup(kernel_path: Path, env: dict[str, str]) -> None:
    """Check one offline hello/quit exchange before saving or starting a bot."""
    try:
        result = subprocess.run(
            [str(kernel_path)], input='{"type":"hello"}\n{"type":"quit"}\n',
            capture_output=True, text=True, timeout=15, env=env, cwd=ENGINES,
        )
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(
            f"Kernel startup check timed out after 15 seconds: '{kernel_path}'. "
            "The bot was not started."
        ) from error
    except OSError as error:
        if getattr(error, "winerror", None) == 4551:
            raise RuntimeError(
                f"Windows App Control blocked Kernel startup (WinError 4551): '{kernel_path}'. "
                "The bot was not started. Review the Windows policy event before trying again."
            ) from error
        raise RuntimeError(f"Could not start Kernel startup check '{kernel_path}': {error}") from error
    if result.returncode != 0:
        detail = (result.stderr or "").strip()[:400]
        raise RuntimeError(
            f"Kernel startup check failed for '{kernel_path}' with exit code {result.returncode}"
            + (f": {detail}" if detail else ".")
        )
    lines = [line for line in (result.stdout or "").splitlines() if line.strip()]
    try:
        if len(lines) != 1:
            raise ValueError("expected one ready JSON response")
        ready = json.loads(lines[0])
        if (not isinstance(ready, dict) or ready.get("type") != "ready"
                or type(ready.get("protocol")) is not int or ready["protocol"] != 1):
            raise ValueError("expected type=ready and integer protocol=1")
    except (ValueError, TypeError) as error:
        raise RuntimeError(f"Invalid Kernel startup response from '{kernel_path}': {error}") from error


def main() -> int:
    available = versions()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", choices=available)
    parser.add_argument("--list", action="store_true", help="List folders without building or launching")
    parser.add_argument("--prepare-only", action="store_true", help="Build/select without starting lichess-bot")
    parser.add_argument("--rebuild", action="store_true")
    args = parser.parse_args()
    if args.list:
        for version in available: print(f"{version}: {DESCRIPTIONS.get(version, 'experimental version folder')}")
        return 0
    version = args.version or choose(available)
    require_weights(version)
    kernel_path = build_kernel(version, force=args.rebuild)
    build_controller(force=args.rebuild)
    env = dict(os.environ)
    compiler = shutil.which("g++")
    if compiler: env["PATH"] = str(Path(compiler).parent) + os.pathsep + env.get("PATH", "")
    if not args.prepare_only:
        probe_kernel_startup(kernel_path, env)
    select(version)
    print(f"\nSelected Kernel: {version}. Selection applies to newly started engine processes.")
    print("Dashboard: open Launch Dashboard.bat (http://127.0.0.1:8765/).\n")
    if args.prepare_only: return 0
    return subprocess.call([sys.executable, "lichess-bot.py"], cwd=ENGINES.parent, env=env)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError, EOFError) as error:
        print(f"Could not start Mr. Bits: {error}", file=sys.stderr)
        raise SystemExit(1)
    except KeyboardInterrupt:
        raise SystemExit(130)
