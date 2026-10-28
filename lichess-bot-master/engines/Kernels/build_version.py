"""Compile one local Kernel version; never starts an engine or game."""
import argparse
from kernel_tools import build_kernel, versions

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version", choices=versions())
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    build_kernel(args.version, force=args.force)
