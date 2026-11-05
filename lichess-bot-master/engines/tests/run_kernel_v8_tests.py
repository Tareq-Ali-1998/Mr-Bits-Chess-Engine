"""Run the shared legal-search oracle against v3.1 (historically V8)."""
from __future__ import annotations

import sys

from run_kernel_v7_tests import main


if __name__ == "__main__":
    raise SystemExit(main(["--version", "v3.1", *sys.argv[1:]]))
