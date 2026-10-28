#!/usr/bin/env bash
set -euo pipefail
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/_common.sh"
if [[ "${1:-}" == '-h' || "${1:-}" == '--help' ]]; then
    printf '%s\n' 'Usage: bash scripts/06_monitor.sh [RUN_OR_RUNROOT=runs]'
    printf '%s\n' 'TensorBoard listens only on 127.0.0.1:6006. Use an SSH tunnel from your own computer.'
    exit 0
fi
if (($# > 1)); then lab_error 'Expected only the run directory'; exit 2; fi
RUN="${1:-runs}"
lab_status 'TensorBoard: http://127.0.0.1:6006 (host-local access only)'
printf '%s\n' 'On your computer: ssh -N -L 6006:127.0.0.1:6006 USER@GPU_HOST'
exec "$LAB_PYTHON" -m tensorboard.main --logdir "$RUN" --host 127.0.0.1 --port 6006
