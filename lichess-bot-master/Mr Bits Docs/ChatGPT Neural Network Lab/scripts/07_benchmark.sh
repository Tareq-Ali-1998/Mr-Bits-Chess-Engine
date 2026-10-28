#!/usr/bin/env bash
set -euo pipefail
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/_common.sh"
if (($# < 1)) || [[ "$1" == '-h' || "$1" == '--help' ]]; then
    printf '%s\n' 'Usage: bash scripts/07_benchmark.sh small|large [DATA=data/local-100k] [OUTPUT=benchmarks/MODEL-throughput.json] [benchmark options]'
    printf '%s\n' 'Example options: --device cuda --batches 1024 4096 16384 --steps 30'
    if (($# < 1)); then exit 2; else exit 0; fi
fi
MODEL="$1"; shift
case "$MODEL" in
    small|large) ;;
    *) lab_error 'Choose small or large'; exit 2 ;;
esac
DATA='data/local-100k'
OUTPUT="benchmarks/$MODEL-throughput.json"
if (($#)) && [[ "$1" != --* ]]; then DATA="$1"; shift; fi
if (($#)) && [[ "$1" != --* ]]; then OUTPUT="$1"; shift; fi
lab_status "Benchmarking $MODEL with real data from $DATA"
"$LAB_PYTHON" -m chesslab.benchmark --data "$DATA" --model "$MODEL" --output "$OUTPUT" "$@"
