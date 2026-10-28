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
                "v4": "Small-only leaf evaluation; sort from depth six"}


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
    build_kernel(version, force=args.rebuild)
    build_controller(force=args.rebuild)
    select(version)
    print(f"\nSelected Kernel: {version}. Selection applies to newly started engine processes.")
    print("Dashboard: open Launch Dashboard.bat (http://127.0.0.1:8765/).\n")
    if args.prepare_only: return 0
    env = dict(os.environ)
    compiler = shutil.which("g++")
    if compiler: env["PATH"] = str(Path(compiler).parent) + os.pathsep + env.get("PATH", "")
    return subprocess.call([sys.executable, "lichess-bot.py"], cwd=ENGINES.parent, env=env)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError, EOFError) as error:
        print(f"Could not start Mr. Bits: {error}", file=sys.stderr)
        raise SystemExit(1)
    except KeyboardInterrupt:
        raise SystemExit(130)
