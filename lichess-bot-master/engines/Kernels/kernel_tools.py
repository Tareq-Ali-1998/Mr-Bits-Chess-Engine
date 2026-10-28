"""Local build/selection helpers. No bot, credentials or network access here."""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

ENGINES = Path(__file__).resolve().parents[1]


def version_name(value: str) -> bool:
    return value == "original" or re.fullmatch(r"v[1-9][0-9]*", value) is not None


def versions(engines: Path = ENGINES) -> list[str]:
    found = [p.name for p in (engines / "Kernels").iterdir() if p.is_dir()
             and version_name(p.name) and p.name != "original" and (p / f"Kernel-{p.name}.cpp").is_file()]
    return ["original", *sorted(found, key=lambda item: int(item[1:]))]


def paths(version: str, engines: Path = ENGINES) -> tuple[Path, Path]:
    if not version_name(version):
        raise ValueError("Choose original or a version folder named v1, v2, ...")
    if version == "original":
        return engines / "Kernel.cpp", engines / "Kernel.exe"
    folder = engines / "Kernels" / version
    return folder / f"Kernel-{version}.cpp", folder / f"Kernel-{version}.exe"


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def inputs(source: Path, engines: Path) -> dict[str, str]:
    headers = [*engines.glob("*.hpp"), *(engines / "Neural Networks").rglob("*.hpp")]
    return {p.relative_to(engines).as_posix(): digest(p) for p in sorted({source, *headers})}


def compiler_environment() -> tuple[str, dict[str, str]]:
    compiler = shutil.which("g++")
    if not compiler:
        raise RuntimeError("g++ was not found on PATH. Use the same MinGW installation as Build Engines.bat.")
    env = dict(os.environ)
    env["PATH"] = str(Path(compiler).parent) + os.pathsep + env.get("PATH", "")
    return compiler, env


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                     prefix=path.name + ".", suffix=".tmp", delete=False) as handle:
        staging = Path(handle.name)
        json.dump(value, handle, indent=2); handle.write("\n")
    try:
        os.replace(staging, path)
    finally:
        staging.unlink(missing_ok=True)


def build(source: Path, executable: Path, label: str, *, engines: Path = ENGINES,
          controller: bool = False, force: bool = False) -> Path:
    if not source.is_file():
        raise FileNotFoundError(f"Missing source: {source}")
    if not executable.resolve().is_relative_to(engines.resolve()):
        raise ValueError("Build target must stay inside engines")
    expected = inputs(source, engines)
    if controller:
        for name in ("sqlite/sqlite3.c", "sqlite/sqlite3.h"):
            expected[name] = digest(engines / name)
    builder_sha256 = digest(Path(__file__))
    metadata_path = executable.with_suffix(".build.json")
    if not force and executable.is_file() and metadata_path.is_file():
        try:
            previous = json.loads(metadata_path.read_text(encoding="utf-8"))
            if (previous.get("schema") == "mrbits.local-build.v1" and previous.get("inputs") == expected
                    and previous.get("builder_sha256") == builder_sha256
                    and previous.get("executable_sha256") == digest(executable)):
                print(f"{label}: existing build matches its source and shared headers.", flush=True)
                return executable
        except (OSError, ValueError):
            pass
    compiler, env = compiler_environment()
    stamp = f"{label}-{digest(source)[:12]}-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}"
    temporary = executable.with_name(executable.stem + ".building.exe")
    executable.parent.mkdir(parents=True, exist_ok=True)
    command = [compiler, "-std=c++17", "-O2", f'-DMRBITS_BUILD_STAMP="{stamp}"',
               "-I", str(engines), str(source)]
    if controller:
        sqlite_source, sqlite_object = engines / "sqlite/sqlite3.c", engines / "sqlite/sqlite3.o"
        if not sqlite_object.is_file() or sqlite_object.stat().st_mtime < sqlite_source.stat().st_mtime:
            c_compiler = shutil.which("gcc")
            if not c_compiler:
                raise RuntimeError("gcc is required to compile SQLite")
            subprocess.run([c_compiler, "-O2", "-DSQLITE_DQS=0", "-DSQLITE_DEFAULT_FOREIGN_KEYS=1",
                            "-DSQLITE_OMIT_LOAD_EXTENSION", "-c", str(sqlite_source), "-o", str(sqlite_object)],
                           env=env, check=True)
        command.append(str(sqlite_object))
    command += ["-o", str(temporary)]
    print(f"Building {label} ({stamp}) ...", flush=True)
    try:
        subprocess.run(command, cwd=engines, env=env, check=True)
        after_inputs = inputs(source, engines)
        if controller:
            for name in ("sqlite/sqlite3.c", "sqlite/sqlite3.h"):
                after_inputs[name] = digest(engines / name)
        if after_inputs != expected:
            raise RuntimeError("Source changed during compilation. Build again before selecting it.")
        os.replace(temporary, executable)
        write_json(metadata_path, {"schema": "mrbits.local-build.v1", "label": label, "stamp": stamp,
                                   "inputs": expected, "builder_sha256": builder_sha256,
                                   "executable_sha256": digest(executable), "command": command})
    except PermissionError as error:
        raise RuntimeError("The executable is in use. Stop the bot/engine before rebuilding.") from error
    finally:
        temporary.unlink(missing_ok=True)
    return executable


def build_kernel(version: str, *, engines: Path = ENGINES, force: bool = False) -> Path:
    source, executable = paths(version, engines)
    return build(source, executable, version, engines=engines, force=force)


def build_controller(*, engines: Path = ENGINES, force: bool = False) -> Path:
    return build(engines / "Engine UCI.cpp", engines / "Engine UCI.exe", "uci", engines=engines,
                 controller=True, force=force)


def select(version: str, *, engines: Path = ENGINES) -> None:
    _, executable = paths(version, engines)
    if not executable.is_file():
        raise FileNotFoundError(f"Build the selected Kernel first: {executable}")
    write_json(engines / "kernel-selection.json", {"version": version})


def require_weights(version: str, engines: Path = ENGINES) -> None:
    models = () if version == "original" else (("Small",) if version == "v4" else ("Small", "Large"))
    model_root = Path(os.environ.get("MRBITS_NEURAL_WEIGHTS_DIR") or engines / "Neural Networks")
    for model in models:
        if not (model_root / model / "weights.bin").is_file():
            raise FileNotFoundError(f"Missing {model} weights: {model_root / model / 'weights.bin'}")
