"""Verify the extracted bundle using only Python's standard library."""

import hashlib
import json
from pathlib import Path


def verify(root: Path):
    manifest = json.loads((root / "UPLOAD_MANIFEST.json").read_text(encoding="utf-8"))
    if manifest.get("schema") != "chesslab.upload.v1":
        raise ValueError("Unknown upload manifest")
    seen = set()
    for record in manifest["files"]:
        relative = Path(record["path"])
        path = (root / relative).resolve()
        if relative.is_absolute() or not path.is_relative_to(root.resolve()) or record["path"] in seen:
            raise ValueError("Unsafe/duplicate upload manifest path")
        seen.add(record["path"])
        raw = path.read_bytes()
        if len(raw) != record["bytes"] or hashlib.sha256(raw).hexdigest() != record["sha256"]:
            raise ValueError(f"Upload integrity failed: {relative}")
    return len(seen)


if __name__ == "__main__":
    count = verify(Path(__file__).resolve().parent)
    print(f"PASS: {count} extracted upload files match their checksums.")
