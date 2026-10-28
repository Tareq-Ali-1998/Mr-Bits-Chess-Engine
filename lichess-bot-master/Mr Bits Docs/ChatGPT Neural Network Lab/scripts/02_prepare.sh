#!/usr/bin/env bash
set -euo pipefail
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/_common.sh"
if (($# < 1)) || [[ "$1" == '-h' || "$1" == '--help' ]]; then
    printf '%s\n' 'Usage: bash scripts/02_prepare.sh INPUT [OUTPUT=data/pilot] [prepare options]'
    printf '%s\n' 'Example: bash scripts/02_prepare.sh "/data/lichess_db_eval.jsonl.zst" data/pilot --sampling reservoir'
    if (($# < 1)); then exit 2; else exit 0; fi
fi
INPUT="$1"; shift
OUTPUT='data/pilot'
if (($#)) && [[ "$1" != --* ]]; then OUTPUT="$1"; shift; fi
lab_status "Preparing accepted positions in $OUTPUT"
"$LAB_PYTHON" -m chesslab.prepare --input "$INPUT" --output "$OUTPUT" \
    --max-positions 100000 --max-records 2000000 --min-depth 20 --max-depth 80 \
    --min-knodes 1000 "$@"
