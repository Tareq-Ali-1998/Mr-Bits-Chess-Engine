"""Build a self-contained, checked Linux upload ZIP without raw data or secrets."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import zipfile

from chesslab.data import sha256_file, verify_dataset

ROOT = Path(__file__).resolve().parent
TOP = "ChatGPT Neural Network Lab"
TEXT_EXTENSIONS = {".py", ".sh", ".md", ".json", ".toml", ".txt", ".csv", ".jsonl", ".svg"}
TOP_FILES = {"README.md", "START_HERE.md", "HANDOFF.md", "requirements.txt", "pyproject.toml",
             "package_upload.py", "verify_upload.py", ".gitignore", ".gitattributes"}


def selected_files(root: Path, include_demo: bool = True):
    paths = [root / name for name in TOP_FILES if (root / name).is_file()]
    for folder in ("chesslab", "scripts", "configs", "docs", "tests"):
        paths.extend(p for p in (root / folder).rglob("*") if p.is_file()
                     and p.suffix in TEXT_EXTENSIONS and "__pycache__" not in p.parts)
    data = root / "data" / "local-100k"
    for name in ("manifest.json", "preparation_progress.json", "train.npy", "validation.npy", "test.npy"):
        paths.append(data / name)
    if include_demo:
        run = root / "runs" / "local-small"
        for name in ("best.pt", "last.pt", "config.json", "environment.json", "data_manifest.json",
                     "metrics.csv", "metrics.jsonl", "result.json", "test.json", "ranking.json",
                     "curves.svg", "curves.png"):
            if (run / name).is_file():
                paths.append(run / name)
        if (run / "best.pt").is_file():
            digest = sha256_file(run / "best.pt")[:16]
            for name in (f"model-{digest}.ts", f"model-{digest}.ts.json"):
                path = run / "exports" / name
                if path.is_file():
                    paths.append(path)
        benchmark = root / "benchmarks" / "local-teacher-test.jsonl"
        if benchmark.is_file():
            paths.append(benchmark)
    for path in sorted(set(paths)):
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError(f"Unsupported/missing upload source: {path}")
        yield path


def build(output: Path, include_demo: bool = True, force: bool = False):
    output = output.resolve()
    if output.exists() and not force:
        raise FileExistsError(f"Already exists; use --force to replace this generated bundle: {output}")
    if output.suffix.lower() != ".zip":
        raise ValueError("Output filename must end in .zip")
    verify_dataset(ROOT / "data" / "local-100k")
    files = list(selected_files(ROOT, include_demo))
    entries = []
    payloads = []
    for path in files:
        raw = path.read_bytes()
        # Linux Bash cannot interpret CRLF reliably; the bundle is LF-normalized.
        if path.suffix in TEXT_EXTENSIONS or path.name.startswith(".git"):
            raw = raw.replace(b"\r\n", b"\n")
        rel = path.relative_to(ROOT).as_posix()
        entries.append({"path": rel, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})
        payloads.append((rel, raw))
    manifest = {"schema": "chesslab.upload.v1", "top_directory": TOP,
                "includes_demo_run": include_demo, "files": entries,
                "excluded": ["raw archive", "original engine", "credentials", "virtual environments", "Python caches", "unlisted local runs"]}
    payloads.append(("UPLOAD_MANIFEST.json", (json.dumps(manifest, indent=2) + "\n").encode()))
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".zip.tmp")
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for name, raw in payloads:
                info = zipfile.ZipInfo(f"{TOP}/{name}", date_time=(2026, 10, 23, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.create_system = 3
                info.external_attr = (0o100755 if name.endswith(".sh") else 0o100644) << 16
                archive.writestr(info, raw)
        with zipfile.ZipFile(temporary) as archive:
            if archive.testzip() is not None:
                raise ValueError("Upload ZIP CRC validation failed")
        temporary.replace(output)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix(".zip.sha256").write_text(f"{digest}  {output.name}\n", encoding="utf-8", newline="\n")
    return {"zip": str(output), "bytes": output.stat().st_size, "files": len(payloads), "sha256": digest}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT.parent / "Mr_Bits_Neural_Lab_Upload.zip")
    parser.add_argument("--no-demo", action="store_true", help="Keep the prepared pilot but omit example trained artifacts")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    print(json.dumps(build(args.output, not args.no_demo, args.force), indent=2))


if __name__ == "__main__":
    main()
