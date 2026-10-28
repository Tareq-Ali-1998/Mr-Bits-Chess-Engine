#!/usr/bin/env bash
set -euo pipefail
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/_common.sh"
if (($# < 3)) || [[ "${1:-}" == '-h' || "${1:-}" == '--help' ]]; then
    printf '%s\n' 'Usage: bash scripts/08_experiment.sh CONFIG DATA RUN [train options]'
    printf '%s\n' 'Uses any supported model/activation configuration; each experiment needs its own run directory.'
    printf '%s\n' 'Example: bash scripts/08_experiment.sh configs/my-gelu.json data/local-100k runs/my-gelu --device cuda'
    if [[ "${1:-}" == '-h' || "${1:-}" == '--help' ]]; then exit 0; else exit 2; fi
fi
CONFIG="$1"
DATA="$2"
RUN="$3"
shift 3
if [[ ! -f "$CONFIG" ]]; then lab_error "Configuration file does not exist: $CONFIG"; exit 2; fi
lab_status "Experiment config=$CONFIG; data=$DATA; run=$RUN"
"$LAB_PYTHON" -m chesslab.train --data "$DATA" --config "$CONFIG" --run "$RUN" "$@"
