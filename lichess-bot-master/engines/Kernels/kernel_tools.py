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
import sys
import tempfile
from windows_build import build_lock, check_replace_access, lock_detail, replace_executable
from build_cache import (CPP_FLAGS, SQLITE_FLAGS, SCHEMA, dependency_inputs, recipe,
                         upgraded_receipt, validate_receipt)

ENGINES = Path(__file__).resolve().parents[1]
LEGACY_TO_FAMILY = {
    "v1": "v1.0", "v2": "v1.1", "v3": "v1.2",
    "v4": "v2.0", "v5": "v2.1", "v6": "v2.2",
    "v7": "v3.0", "v8": "v3.1", "v9": "v3.6",
    "v10": "v3.7", "v11": "v3.8", "v12": "v3.9",
}


def version_name(value: str) -> bool:
    # Retain integer-label syntax for historical compatibility; current families use
    # an explicit minor component. Neither component admits leading zeroes.
    return isinstance(value, str) and (value == "original" or
        re.fullmatch(r"v[1-9][0-9]*(?:\.(?:0|[1-9][0-9]*))?", value) is not None)


def version_key(value: str) -> tuple[int, int]:
    major, separator, minor = value[1:].partition(".")
    return int(major), int(minor) if separator else -1


def versions(engines: Path = ENGINES) -> list[str]:
    found = [p.name for p in (engines / "Kernels").iterdir() if p.is_dir()
             and version_name(p.name) and p.name != "original" and (p / f"Kernel-{p.name}.cpp").is_file()]
    return ["original", *sorted(found, key=version_key)]


def paths(version: str, engines: Path = ENGINES) -> tuple[Path, Path]:
    if not version_name(version):
        raise ValueError("Choose original or a version folder such as v1.0 or v3.2")
    if version == "original":
        return engines / "Kernel.cpp", engines / "Kernel.exe"
    folder = engines / "Kernels" / version
    return folder / f"Kernel-{version}.cpp", folder / f"Kernel-{version}.exe"


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def inputs(source: Path, engines: Path) -> dict[str, str]:
    return dependency_inputs(source, engines)


def compiler_environment() -> tuple[str, dict[str, str]]:
    compiler = shutil.which("g++")
    if not compiler:
        raise RuntimeError("g++ was not found on PATH. Use the same MinGW installation as Build Engines.bat.")
    env = dict(os.environ)
    env["PATH"] = str(Path(compiler).parent) + os.pathsep + env.get("PATH", "")
    return compiler, env


def _cleanup_temporary(path: Path, primary_error: BaseException | None) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError as error:
        message = f"Could not remove temporary file '{path}': {error}"
        if primary_error is None:
            raise RuntimeError(message) from error
        print(f"Warning: {message}", file=sys.stderr)


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                     prefix=path.name + ".", suffix=".tmp", delete=False) as handle:
        staging = Path(handle.name)
        json.dump(value, handle, indent=2); handle.write("\n")
    try:
        os.replace(staging, path)
    finally:
        _cleanup_temporary(staging, sys.exception())


def build(source: Path, executable: Path, label: str, *, engines: Path = ENGINES,
          controller: bool = False, force: bool = False) -> Path:
    if not executable.resolve().is_relative_to(engines.resolve()):
        raise ValueError("Build target must stay inside engines")
    with build_lock(executable):
        return _build(source, executable, label, engines=engines, controller=controller, force=force)


def _build(source: Path, executable: Path, label: str, *, engines: Path,
           controller: bool, force: bool) -> Path:
    if not source.is_file():
        raise FileNotFoundError(f"Missing source: {source}")
    if not executable.resolve().is_relative_to(engines.resolve()):
        raise ValueError("Build target must stay inside engines")
    expected = dependency_inputs(source, engines, controller=controller)
    expected_recipe = recipe(source, engines, controller=controller)
    builder_sha256 = digest(Path(__file__))
    metadata_path = executable.with_suffix(".build.json")
    if not force and executable.is_file() and metadata_path.is_file():
        try:
            previous = json.loads(metadata_path.read_text(encoding="utf-8"))
            if validate_receipt(previous, expected, expected_recipe, executable,
                                source=source, engines=engines, controller=controller):
                if previous.get("schema") != SCHEMA:
                    write_json(metadata_path, upgraded_receipt(previous, expected, expected_recipe))
                print(f"{label}: existing build matches its dependencies and build recipe.", flush=True)
                return executable
        except (OSError, ValueError, TypeError, AttributeError):
            pass
    check_replace_access(executable)
    compiler, env = compiler_environment()
    stamp = f"{label}-{digest(source)[:12]}-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}"
    temporary = executable.with_name(executable.stem + ".building.exe")
    executable.parent.mkdir(parents=True, exist_ok=True)
    command = [compiler, *CPP_FLAGS, f'-DMRBITS_BUILD_STAMP="{stamp}"',
               "-I", str(engines), str(source)]
    if controller:
        sqlite_source, sqlite_object = engines / "sqlite/sqlite3.c", engines / "sqlite/sqlite3.o"
        object_receipt = sqlite_object.with_suffix(".o.build.json")
        object_inputs = {name: expected[name] for name in ("sqlite/sqlite3.c", "sqlite/sqlite3.h")}
        object_recipe = expected_recipe["sqlite"]
        object_current = False
        if sqlite_object.is_file() and object_receipt.is_file():
            try:
                old_object = json.loads(object_receipt.read_text(encoding="utf-8"))
                object_current = (old_object.get("schema") == "mrbits.sqlite-object.v1"
                                  and old_object.get("inputs") == object_inputs
                                  and old_object.get("recipe") == object_recipe
                                  and old_object.get("object_sha256") == digest(sqlite_object))
            except (OSError, ValueError, TypeError, AttributeError):
                pass
        if not object_current:
            c_compiler = shutil.which("gcc")
            if not c_compiler:
                raise RuntimeError("gcc is required to compile SQLite")
            object_staging = sqlite_object.with_name("sqlite3.building.o")
            print("Building SQLite object (source/header/toolchain validation) ...", flush=True)
            try:
                subprocess.run([c_compiler, *SQLITE_FLAGS, "-c", str(sqlite_source), "-o", str(object_staging)],
                               env=env, check=True)
                os.replace(object_staging, sqlite_object)
                write_json(object_receipt, {"schema": "mrbits.sqlite-object.v1", "inputs": object_inputs,
                                           "recipe": object_recipe, "object_sha256": digest(sqlite_object)})
            finally:
                _cleanup_temporary(object_staging, sys.exception())
        command.append(str(sqlite_object))
    command += ["-o", str(temporary)]
    print(f"Building {label} ({stamp}) ...", flush=True)
    try:
        try:
            subprocess.run(command, cwd=engines, env=env, check=True)
        except OSError as error:
            raise RuntimeError(f"Could not start compiler '{compiler}' while building '{executable}': {error}") from error
        after_inputs = dependency_inputs(source, engines, controller=controller)
        if after_inputs != expected:
            raise RuntimeError("Source changed during compilation. Build again before selecting it.")
        try:
            replace_executable(temporary, executable)
        except OSError as error:
            raise RuntimeError(
                f"Could not install executable '{executable}' from '{temporary}': {error}. "
                + lock_detail(executable) + " If this engine is running, stop it before rebuilding; otherwise check the file's permissions "
                "and Windows protection history."
            ) from error
        try:
            receipt = {"label": label, "stamp": stamp, "inputs": expected,
                       "builder_sha256": builder_sha256, "executable_sha256": digest(executable),
                       "command": command, "origin": "local_compilation"}
            write_json(metadata_path, upgraded_receipt(receipt, expected, expected_recipe))
        except OSError as error:
            raise RuntimeError(
                f"Executable '{executable}' was installed, but could not write build receipt '{metadata_path}': {error}"
            ) from error
    finally:
        _cleanup_temporary(temporary, sys.exception())
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
    requirements = {
        "original": (),
        "v1": ("Small", "Large"), "v2": ("Small", "Large"), "v3": ("Small", "Large"),
        "v4": ("Small",), "v5": ("Small",), "v6": ("Small",),
        "v7": ("Small",), "v8": ("Small",), "v9": ("Large",),
        "v10": ("Small", "Large"),
        "v11": ("Small",), "v12": ("Small",),
    }
    requirements.update({family: requirements[legacy] for legacy, family in LEGACY_TO_FAMILY.items()})
    # Purely classical leaf scoring still uses the unchanged Small move ordering.
    requirements.update({version: ("Small",) for version in ("v3.2", "v3.3", "v3.4")})
    models = requirements.get(version, ("Small", "Large"))
    model_root = Path(os.environ.get("MRBITS_NEURAL_WEIGHTS_DIR") or engines / "Neural Networks")
    for model in models:
        if not (model_root / model / "weights.bin").is_file():
            raise FileNotFoundError(f"Missing {model} weights: {model_root / model / 'weights.bin'}")
