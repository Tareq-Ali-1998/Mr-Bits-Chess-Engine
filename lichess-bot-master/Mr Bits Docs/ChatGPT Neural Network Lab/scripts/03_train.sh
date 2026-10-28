#!/usr/bin/env bash
set -euo pipefail
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/_common.sh"
if (($# < 1)) || [[ "$1" == '-h' || "$1" == '--help' ]]; then
    printf '%s\n' 'Usage: bash scripts/03_train.sh small|large [DATA=data/pilot] [RUN=runs/pilot-MODEL] [train options]'
    printf '%s\n' 'Examples: --device cuda --benchmark-steps 100; --resume runs/pilot-small/last.pt --epochs 10'
    if (($# < 1)); then exit 2; else exit 0; fi
fi
MODEL="$1"; shift
case "$MODEL" in
    small|large) ;;
    *) lab_error 'Choose small or large'; exit 2 ;;
esac
DATA='data/pilot'
RUN="runs/pilot-$MODEL"
if (($#)) && [[ "$1" != --* ]]; then DATA="$1"; shift; fi
if (($#)) && [[ "$1" != --* ]]; then RUN="$1"; shift; fi
lab_status "Training $MODEL; data=$DATA; run=$RUN"
"$LAB_PYTHON" -m chesslab.train --data "$DATA" --config "configs/pilot_$MODEL.json" --run "$RUN" "$@"
