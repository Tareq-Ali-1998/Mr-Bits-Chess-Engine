#!/usr/bin/env bash
set -euo pipefail
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/_common.sh"

usage() {
    cat <<'USAGE'
Usage: bash scripts/00_setup.sh [--cpu] [--python python3.12] [--isolated]
Default: reuse a working CUDA Torch through a local system-site-packages venv.
--cpu explicitly selects a CPU-only development environment.
--isolated creates a new venv without image-provided packages.
An existing .venv is reused; its isolation setting is not changed.
No drivers, sudo operations, cloud instances, or training jobs are created.
USAGE
}

CPU_ONLY=0
ISOLATED=0
BASE_PYTHON="${CHESSLAB_BOOTSTRAP_PYTHON:-python3}"
while (($#)); do
    case "$1" in
        --cpu) CPU_ONLY=1; shift ;;
        --isolated) ISOLATED=1; shift ;;
        --python)
            if (($# < 2)); then lab_error '--python needs an interpreter'; exit 2; fi
            BASE_PYTHON="$2"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) usage; lab_error "Unknown option: $1"; exit 2 ;;
    esac
done

"$BASE_PYTHON" - <<'PY'
import sys
import sysconfig
if not (3, 11) <= sys.version_info[:2] < (3, 15):
    raise SystemExit('Use standard CPython 3.11–3.14 (3.12 is a good starting choice).')
if sys.implementation.name != 'cpython' or sysconfig.get_config_var('Py_GIL_DISABLED'):
    raise SystemExit('Use standard CPython, not PyPy or a free-threaded build, for the reference Torch wheels.')
PY

if [[ ! -f "$LAB_ROOT/.venv/pyvenv.cfg" ]]; then
    lab_status '[1/5] Creating local Python environment'
    if ((ISOLATED)); then
        "$BASE_PYTHON" -m venv "$LAB_ROOT/.venv"
    else
        "$BASE_PYTHON" -m venv --system-site-packages "$LAB_ROOT/.venv"
    fi
else
    lab_status '[1/5] Reusing existing .venv'
    if ((ISOLATED)); then
        printf '%s\n' 'Note: --isolated applies only to a newly created environment; the existing .venv is unchanged.' >&2
    fi
fi
if [[ -x "$LAB_ROOT/.venv/bin/python" ]]; then
    LAB_PYTHON="$LAB_ROOT/.venv/bin/python"
elif [[ "${OSTYPE:-}" == msys* || "${OSTYPE:-}" == cygwin* ]] && [[ -x "$LAB_ROOT/.venv/Scripts/python.exe" ]]; then
    LAB_PYTHON="$LAB_ROOT/.venv/Scripts/python.exe"
else
    lab_error 'The existing .venv has no native interpreter. Upload source/data without a Windows venv and use a fresh extraction directory.'
    exit 1
fi
"$LAB_PYTHON" - <<'PY'
import sys
import sysconfig
if not (3, 11) <= sys.version_info[:2] < (3, 15):
    raise SystemExit('The existing .venv uses an unsupported Python; use a fresh extraction with CPython 3.11–3.14.')
if sys.implementation.name != 'cpython' or sysconfig.get_config_var('Py_GIL_DISABLED'):
    raise SystemExit('The reference environment needs standard CPython, not PyPy or a free-threaded build.')
PY

lab_status '[2/5] Checking the existing Torch build with real computation'
if "$LAB_PYTHON" - "$CPU_ONLY" <<'PY'
import re
import sys
try:
    import torch
    version = re.match(r'(\d+)\.(\d+)', torch.__version__)
    if version is None or tuple(map(int, version.groups())) < (2, 7):
        raise RuntimeError('Torch >=2.7 is required')
    device = 'cpu' if sys.argv[1] == '1' else 'cuda'
    if device == 'cuda' and not torch.cuda.is_available():
        raise RuntimeError('CUDA is unavailable to this Torch build')
    x = torch.randn(32, 32, device=device, requires_grad=True)
    w = torch.randn(32, 32, device=device, requires_grad=True)
    loss = (x @ w).square().mean()
    loss.backward()
    if not torch.isfinite(loss).item() or not torch.isfinite(w.grad).all().item():
        raise RuntimeError('Non-finite CUDA/CPU smoke test')
    if device == 'cuda':
        torch.cuda.synchronize()
    print(f'Keeping Torch {torch.__version__}: {device} forward/backward passed.')
except Exception as exc:
    print(f'Existing Torch cannot be reused: {exc}', file=sys.stderr)
    raise SystemExit(1)
PY
then
    :
else
    if ((CPU_ONLY)); then
        lab_status 'Installing the reference Torch 2.10.0 CPU wheel'
        "$LAB_PYTHON" -m pip install --force-reinstall 'torch==2.10.0' --index-url https://download.pytorch.org/whl/cpu
    else
        if ! command -v nvidia-smi >/dev/null 2>&1 || ! nvidia-smi --list-gpus >/dev/null 2>&1; then
            lab_error 'No usable NVIDIA host driver/device was detected. Use a GPU image, or rerun with --cpu for CPU development.'
            exit 1
        fi
        lab_status 'Installing the reference Torch 2.10.0 CUDA 12.8 wheel'
        "$LAB_PYTHON" -m pip install --force-reinstall 'torch==2.10.0' --index-url https://download.pytorch.org/whl/cu128
    fi
fi

lab_status '[3/5] Installing lab dependencies without upgrading a validated Torch'
"$LAB_PYTHON" -m pip install -r "$LAB_ROOT/requirements.txt"
"$LAB_PYTHON" -m pip install --no-deps -e "$LAB_ROOT"

lab_status '[4/5] Recording environment and checking the actual device'
if ((CPU_ONLY)); then
    "$LAB_PYTHON" -m chesslab.doctor --device cpu --strict-deps --output "$LAB_ROOT/diagnostics/environment.json"
else
    "$LAB_PYTHON" -m chesslab.doctor --require-cuda --strict-deps --output "$LAB_ROOT/diagnostics/environment.json"
fi
lab_status '[5/5] Setup finished. Run bash scripts/01_check.sh --require-cuda --strict-deps on the GPU host.'
printf 'Interpreter: %s\n' "$LAB_PYTHON"
printf 'Environment report: %s\n' "$LAB_ROOT/diagnostics/environment.json"
