#!/usr/bin/env bash
set -euo pipefail
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/_common.sh"
if [[ "${1:-}" != '--download' ]]; then
    printf '%s\n' 'Usage: bash scripts/download_data.sh --download [DESTINATION=downloads/lichess_db_eval.jsonl.zst]'
    printf '%s\n' 'Opt-in only: downloads the current official Lichess evaluated-position archive.'
    printf '%s\n' 'The file is large, changes over time, and may incur storage/network charges. Existing completed files are not replaced.'
    if [[ "${1:-}" == '-h' || "${1:-}" == '--help' ]]; then exit 0; else exit 2; fi
fi
shift
if (($# > 1)); then lab_error 'Expected only the destination'; exit 2; fi
DESTINATION="${1:-downloads/lichess_db_eval.jsonl.zst}"
URL='https://database.lichess.org/lichess_db_eval.jsonl.zst'
if [[ -e "$DESTINATION" ]]; then lab_error "Destination exists: $DESTINATION"; exit 2; fi
if ! command -v curl >/dev/null 2>&1; then lab_error 'curl is required'; exit 1; fi
mkdir -p -- "$(dirname -- "$DESTINATION")"
LOCK_DIRECTORY="$DESTINATION.download.lock"
if ! mkdir -- "$LOCK_DIRECTORY" 2>/dev/null; then
    lab_error "Another download may own $LOCK_DIRECTORY. Check its pid file before recovering a stale lock."
    exit 1
fi
printf '%s\n' "$$" > "$LOCK_DIRECTORY/pid"
HEADER_FILE=''
cleanup_download() {
    if [[ -n "$HEADER_FILE" ]]; then rm -f -- "$HEADER_FILE"; fi
    rm -f -- "$LOCK_DIRECTORY/pid"
    rmdir -- "$LOCK_DIRECTORY" 2>/dev/null || true
}
trap cleanup_download EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
HEADER_FILE="$(mktemp)"
curl --fail --silent --show-error --location --retry 3 --proto '=https' --proto-redir '=https' --head "$URL" > "$HEADER_FILE"
VALIDATOR="$("$LAB_PYTHON" - "$HEADER_FILE" "$DESTINATION" "$URL" <<'PY'
import json
import re
import sys
from email.parser import Parser
from pathlib import Path
header_file, destination, url = sys.argv[1:]
blocks = re.split(r'\r?\n\r?\n', Path(header_file).read_text(encoding='utf-8').strip())
block = next((part for part in reversed(blocks)
              if re.match(r'HTTP/\S+\s+2\d\d', part)), None)
if block is None:
    raise SystemExit('Cannot establish the source version from the final HTTP response.')
headers = Parser().parsestr(block.split('\n', 1)[1])
etag = headers.get('ETag', '').strip()
modified = headers.get('Last-Modified', '').strip()
if any(character in etag + modified for character in '\r\n'):
    raise SystemExit('Unexpected multiline HTTP validator.')
strong_etag = etag if etag and not etag.lower().startswith('w/') else ''
range_validator = strong_etag or modified
length_header = headers.get('Content-Length', '').strip()
length = int(length_header) if length_header.isdecimal() else None
current = {'url': url, 'etag': etag, 'last_modified': modified,
           'range_validator': range_validator, 'content_length': length}
partial = Path(destination + '.partial')
record = Path(destination + '.partial.source.json')
if partial.exists() and partial.stat().st_size:
    if not record.exists():
        raise SystemExit('Existing partial file has no source-version record. Move it aside or choose a new destination.')
    old = json.loads(record.read_text(encoding='utf-8'))
    old_etag = old.get('etag', '')
    old_strong_etag = old_etag if old_etag and not old_etag.lower().startswith('w/') else ''
    old_validator = old_strong_etag or old.get('last_modified', '')
    same = (old.get('url') == url and old_etag == etag and range_validator
            and old_validator == range_validator)
    if length is not None and partial.stat().st_size > length:
        same = False
    if not same:
        raise SystemExit('The source changed or cannot be verified. Preserve the old partial file and choose a new destination.')
record.write_text(json.dumps(current, indent=2) + '\n', encoding='utf-8')
print(range_validator)
PY
)"
lab_status "Downloading official data to $DESTINATION.partial (resumes an interrupted transfer)"
CURL_ARGUMENTS=(--fail --location --retry 5 --retry-delay 3 --proto '=https' --proto-redir '=https' --continue-at - --output "$DESTINATION.partial")
if [[ -n "$VALIDATOR" ]]; then CURL_ARGUMENTS+=(--header "If-Range: $VALIDATOR"); fi
curl "${CURL_ARGUMENTS[@]}" "$URL"
mv -- "$DESTINATION.partial" "$DESTINATION"
"$LAB_PYTHON" - "$DESTINATION" "$URL" <<'PY'
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
path = Path(sys.argv[1])
digest = hashlib.sha256()
with path.open('rb') as handle:
    for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b''):
        digest.update(chunk)
manifest = {'url': sys.argv[2], 'file': path.name, 'bytes': path.stat().st_size,
            'sha256': digest.hexdigest(), 'downloaded_at_utc': datetime.now(timezone.utc).isoformat()}
manifest_path = path.with_name(path.name + '.download.json')
manifest_path.write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
print(f'Saved provenance: {manifest_path}')
print('This checksum records what was downloaded; it is not an independently verified publisher checksum.')
PY
