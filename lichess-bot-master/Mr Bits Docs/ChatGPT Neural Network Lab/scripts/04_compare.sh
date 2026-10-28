#!/usr/bin/env bash
set -euo pipefail
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/_common.sh"
if [[ "${1:-}" == '-h' || "${1:-}" == '--help' ]]; then
    printf '%s\n' 'Usage: bash scripts/04_compare.sh [DATA=data/pilot] [RUNROOT=runs]'
    printf '%s\n' 'Evaluates existing pilot-small and pilot-large best checkpoints. Never starts training.'
    exit 0
fi
if (($# > 2)); then lab_error 'Expected at most DATA and RUNROOT'; exit 2; fi
DATA="${1:-data/pilot}"
RUNROOT="${2:-runs}"
for MODEL in small large; do
    RUN="$RUNROOT/pilot-$MODEL"
    if [[ ! -f "$RUN/best.pt" ]]; then
        lab_error "Missing $RUN/best.pt. Train both models explicitly before comparing."
        printf 'Run: bash scripts/03_train.sh %q %q %q --device cuda\n' "$MODEL" "$DATA" "$RUN" >&2
        exit 2
    fi
done
for MODEL in small large; do
    RUN="$RUNROOT/pilot-$MODEL"
    lab_status "Evaluating $MODEL on the frozen test split"
    "$LAB_PYTHON" -m chesslab.metrics --checkpoint "$RUN/best.pt" --data "$DATA" --split test --output "$RUN/test.json"
    "$LAB_PYTHON" -m chesslab.plot --run "$RUN"
done
printf 'Compare the two test.json reports and training curves under: %s\n' "$RUNROOT"
