#!/usr/bin/env bash
set -euo pipefail
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/_common.sh"
exec "$LAB_PYTHON" -u - "$@" <<'PY'
"""Unattended, fail-fast large-data experiment. Linux server only."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import subprocess
import sys
import time
import traceback

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--input', type=Path, default=Path('../raw/lichess_db_eval.jsonl.zst'))
parser.add_argument('--tag', default='big-10m-v1')
parser.add_argument('--positions', type=int, default=10_000_000)
parser.add_argument('--scan-records', type=int, default=20_000_000)
parser.add_argument('--epochs', type=int, default=20)
parser.add_argument('--batch-size', type=int, default=2048)
parser.add_argument('--prep-workers', type=int, default=min(16, max(1, (os.cpu_count() or 2) - 2)))
parser.add_argument('--download', action='store_true', help='Explicitly download the official archive if input is missing')
args = parser.parse_args()
if not sys.platform.startswith('linux'):
    parser.error('Run this launcher on the Linux GPU server. --help is available locally.')
import fcntl
if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', args.tag):
    parser.error('Use a safe experiment tag, e.g. big-10m-v1')
if min(args.positions, args.scan_records, args.epochs, args.batch_size, args.prep_workers) < 1:
    parser.error('Counts and worker settings must be positive')
if args.scan_records < args.positions:
    parser.error('Scan at least as many raw records as requested accepted positions')

root = Path.cwd().resolve()
source = args.input.resolve()
data = root / 'data' / args.tag
runs = root / 'runs' / args.tag
logs = root / 'logs'
runs.mkdir(parents=True, exist_ok=True)
logs.mkdir(parents=True, exist_ok=True)
status_path = logs / (args.tag + '.status.json')
started = time.monotonic()
child = None
stage = 'starting'
EXPECTED_BYTES = 22423777007
EXPECTED_SHA256 = 'b2856cafa4d323b2641a43e2d25b716313febeef2fbed9b1472f7a036a368215'


def atomic_json(path, value):
    temporary = path.with_name(path.name + '.tmp')
    with temporary.open('w', encoding='utf-8', newline='\n') as handle:
        json.dump(value, handle, indent=2, allow_nan=False)
        handle.write('\n')
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def status(state, message=''):
    value = {'state': state, 'stage': stage, 'message': message, 'pid': os.getpid(),
             'updated_utc': datetime.now(timezone.utc).isoformat(),
             'elapsed_seconds': round(time.monotonic() - started, 2),
             'data': str(data), 'runs': str(runs)}
    atomic_json(status_path, value)
    print(f"\n[{value['updated_utc']}] {state.upper()} | {stage} | {message}", flush=True)


def stop_child():
    global child
    if child is not None and child.poll() is None:
        try:
            os.killpg(child.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            child.wait(timeout=15)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.wait()


def interrupted(signum, frame):
    stop_child()
    raise KeyboardInterrupt


def run(command):
    global child
    command = [str(part) for part in command]
    print('$ ' + shlex.join(command), flush=True)
    env = dict(os.environ, PYTHONUNBUFFERED='1')
    child = subprocess.Popen(command, cwd=root, env=env, start_new_session=True)
    try:
        result = child.wait()
        if result:
            raise subprocess.CalledProcessError(result, command)
    finally:
        stop_child()
        child = None


lock = (runs / '.pipeline.lock').open('a+b')
try:
    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
except BlockingIOError:
    raise SystemExit('This experiment already has an active pipeline. Do not launch it twice.')

signal.signal(signal.SIGTERM, interrupted)
signal.signal(signal.SIGINT, interrupted)

try:
    from chesslab.data import sha256_file, verify_dataset
    plan = {'input': str(source), 'source_bytes': EXPECTED_BYTES,
            'source_sha256': EXPECTED_SHA256, 'positions': args.positions,
            'scan_records': args.scan_records, 'epochs': args.epochs,
            'batch_size': args.batch_size, 'prep_workers': args.prep_workers,
            'feature_version': 'board782_v1', 'models': ['small', 'large'],
            'quality': {'min_depth': 20, 'max_depth': 80, 'min_knodes': 1000,
                        'max_abs_cp': 1500, 'pv_validation': 'full'},
            'sampling': 'reservoir', 'seed': 20261023}
    plan_path = runs / 'plan.json'
    if plan_path.exists():
        if json.loads(plan_path.read_text(encoding='utf-8')) != plan:
            raise ValueError('This tag already belongs to a different plan. Choose a new --tag.')
    else:
        atomic_json(plan_path, plan)

    stage = 'source verification'
    free = shutil.disk_usage(root).free
    required = 20 * 2**30 + (0 if source.exists() else EXPECTED_BYTES)
    if free < required:
        raise RuntimeError(f'Need at least {required/2**30:.1f} GiB free here; found {free/2**30:.1f}. Extra scratch is needed for deduplication.')
    if not source.exists():
        if not args.download:
            raise FileNotFoundError(f'Full archive is missing: {source}. Finish the upload, or rerun with --download to fetch the official source.')
        status('running', 'Downloading the full archive before preparation')
        run(['bash', 'scripts/download_data.sh', '--download', source])
    before = source.stat()
    if before.st_size != EXPECTED_BYTES:
        raise ValueError(f'Archive is incomplete or a different version: expected {EXPECTED_BYTES:,} bytes; got {before.st_size:,}. Wait for upload completion.')
    status('running', 'Checking the full 22 GB source checksum; this is a complete disk read')
    digest = sha256_file(source)
    after = source.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError('Archive changed while hashing; let the upload finish before retrying.')
    if digest != EXPECTED_SHA256:
        raise ValueError('Full archive checksum differs from the original local source. Do not train on an incomplete/different transfer.')
    atomic_json(runs / 'source.json', {'path': str(source), 'bytes': after.st_size,
                'sha256': digest, 'verified_utc': datetime.now(timezone.utc).isoformat()})

    stage = 'GPU and large-model preflight'
    status('running', 'Checking CUDA/BF16, then disposable steps on the actual large architecture')
    run([sys.executable, '-m', 'chesslab.doctor', '--require-cuda', '--strict-deps',
         '--output', runs / 'environment.json'])
    run([sys.executable, '-m', 'chesslab.benchmark', '--data', 'data/local-100k',
         '--model', 'large', '--batches', args.batch_size, '--steps', 10,
         '--workers', 0, '--device', 'cuda', '--output', runs / 'large-preflight.json'])

    stage = 'large data preparation'
    if (data / 'manifest.json').exists():
        status('running', 'Checking a previously completed dataset before reuse')
    else:
        if data.exists() and any(data.iterdir()):
            raise ValueError(f'Partial preparation exists at {data}; it cannot resume. Preserve it and choose a new --tag.')
        status('running', f'Scan up to {args.scan_records:,} raw records; select up to {args.positions:,} clean positions. CPU stage; GPU may be idle.')
        run([sys.executable, '-m', 'chesslab.prepare', '--input', source,
             '--output', data, '--max-positions', args.positions,
             '--max-records', args.scan_records, '--sampling', 'reservoir',
             '--workers', args.prep_workers, '--min-depth', 20, '--max-depth', 80,
             '--min-knodes', 1000, '--max-abs-cp', 1500, '--pv-validation', 'full',
             '--seed', 20261023])
    manifest = verify_dataset(data)
    if sum(manifest['counts'].values()) < min(args.positions, 1_000_000):
        raise ValueError('Too few accepted positions for the requested substantial run; inspect the quality audit instead of relaxing filters silently.')
    if (manifest['quality'] != plan['quality']
            or manifest['sampling']['method'] != plan['sampling']
            or manifest['sampling']['max_records'] != args.scan_records
            or manifest['sampling']['max_positions'] != args.positions
            or manifest['split']['seed'] != plan['seed']
            or manifest['source']['filename'] != source.name
            or manifest['source']['bytes'] != EXPECTED_BYTES):
        raise ValueError('Existing prepared dataset differs from this experiment plan.')
    binding_path = runs / 'data-binding.json'
    binding = {'source_sha256': digest, 'prepared_fingerprint': manifest['fingerprint']}
    if binding_path.exists() and json.loads(binding_path.read_text(encoding='utf-8')) != binding:
        raise ValueError('Prepared release differs from this run plan\'s recorded source/data binding.')
    atomic_json(binding_path, binding)
    status('running', f"Prepared split counts: {manifest['counts']}")

    for model in ('small', 'large'):
        config = json.loads((root / 'configs' / (model + '.json')).read_text(encoding='utf-8'))
        config.update(epochs=args.epochs, batch_size=args.batch_size,
                      workers=0, cpu_threads=8, tensorboard=True)
        config_path = runs / (model + '.json')
        if config_path.exists() and json.loads(config_path.read_text(encoding='utf-8')) != config:
            raise ValueError('Saved experiment settings changed; use a new tag.')
        atomic_json(config_path, config)
        run_dir = runs / model
        command = [sys.executable, '-m', 'chesslab.train', '--data', data,
                   '--config', config_path, '--run', run_dir, '--device', 'cuda']
        last = run_dir / 'last.pt'
        if last.exists():
            command += ['--resume', last]
        elif run_dir.exists() and any(p.name != '.training.lock' for p in run_dir.iterdir()):
            raise ValueError(f'Existing run lacks a resumable checkpoint: {run_dir}. Preserve and inspect it.')
        stage = model + ' training'
        status('running', f'Up to {args.epochs} epochs; validation early stopping remains enabled')
        run(command)
        stage = model + ' evaluation/export'
        status('running', 'Saving test metrics, plots, and a checked inference artifact')
        run(['bash', 'scripts/05_evaluate.sh', run_dir, data])

    stage = 'comparison'
    run([sys.executable, '-m', 'chesslab.experiments', 'compare', '--runs',
         runs / 'small', runs / 'large', '--output', runs / 'comparison.json', '--include-test'])
    stage = 'finished'
    status('complete', 'Both experiments finished. Save the results before stopping the VM. These are regression results, not a 95% move-retention claim.')
except KeyboardInterrupt:
    status('interrupted', 'Completed training epochs can resume with this same command. Incomplete data preparation needs a fresh tag.')
    raise SystemExit(130)
except BaseException as exc:
    status('failed', str(exc))
    traceback.print_exc()
    raise SystemExit(1)
finally:
    stop_child()
    lock.close()
PY
