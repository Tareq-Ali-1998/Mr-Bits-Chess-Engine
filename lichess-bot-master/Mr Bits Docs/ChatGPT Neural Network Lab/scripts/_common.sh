#!/usr/bin/env bash
set -euo pipefail

LAB_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd -- "$LAB_ROOT"

if [[ -n "${CHESSLAB_PYTHON:-}" ]]; then
    LAB_PYTHON="$CHESSLAB_PYTHON"
elif [[ -x "$LAB_ROOT/.venv/bin/python" ]]; then
    LAB_PYTHON="$LAB_ROOT/.venv/bin/python"
elif [[ -x "$LAB_ROOT/.venv/Scripts/python.exe" ]]; then
    LAB_PYTHON="$LAB_ROOT/.venv/Scripts/python.exe"
else
    LAB_PYTHON="python3"
fi

lab_status() {
    if [[ -t 1 && -z "${NO_COLOR:-}" ]]; then
        printf '\033[1;36m%s\033[0m\n' "$*"
    else
        printf '%s\n' "$*"
    fi
}

lab_error() {
    printf 'Error: %s\n' "$*" >&2
}
