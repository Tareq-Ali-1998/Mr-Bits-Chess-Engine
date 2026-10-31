"""Run the shared legal-search oracle against V8, including neural-only value checks."""
from __future__ import annotations

import sys

from run_kernel_v7_tests import main


if __name__ == "__main__":
    raise SystemExit(main(["--version", "v8", *sys.argv[1:]]))
