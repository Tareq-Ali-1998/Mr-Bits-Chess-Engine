#!/usr/bin/env bash
set -euo pipefail
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/_common.sh"
lab_status 'Checking software, real tensor operations, and device information'
"$LAB_PYTHON" -m chesslab.doctor "$@"
