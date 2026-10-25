#!/usr/bin/env bash
set -euo pipefail
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/_common.sh"
if (($# < 2)) || [[ "$1" == '-h' || "$1" == '--help' ]]; then
    printf '%s\n' 'Usage: bash scripts/05_evaluate.sh RUN DATA [TEACHER_BENCHMARK.jsonl]'
    printf '%s\n' 'Writes test metrics, plots, TorchScript export, and optional candidate-ranking metrics.'
    if (($# < 2)) && [[ "${1:-}" != '-h' && "${1:-}" != '--help' ]]; then exit 2; else exit 0; fi
fi
if (($# > 3)); then lab_error 'Expected RUN DATA and optional benchmark'; exit 2; fi
RUN="$1"
DATA="$2"
BENCHMARK="${3:-}"
if [[ ! -f "$RUN/best.pt" ]]; then lab_error "Missing $RUN/best.pt"; exit 2; fi
lab_status "Evaluating and exporting $RUN/best.pt"
"$LAB_PYTHON" -m chesslab.metrics --checkpoint "$RUN/best.pt" --data "$DATA" --split test --output "$RUN/test.json"
"$LAB_PYTHON" -m chesslab.plot --run "$RUN"
CHECKPOINT_DIGEST="$("$LAB_PYTHON" - "$RUN/best.pt" <<'PY'
import sys
from chesslab.data import sha256_file
print(sha256_file(sys.argv[1])[:16])
PY
)"
"$LAB_PYTHON" -m chesslab.export --checkpoint "$RUN/best.pt" --output "$RUN/exports/model-$CHECKPOINT_DIGEST.ts" --reuse-existing
if [[ -n "$BENCHMARK" ]]; then
    "$LAB_PYTHON" -m chesslab.rank --checkpoint "$RUN/best.pt" --benchmark "$BENCHMARK" --output "$RUN/ranking.json"
fi
