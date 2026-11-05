"""Conservative project dependencies and reproducible local build-cache contracts.

This module never starts a compiler, executable, bot, or network connection.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import re
import shutil

SCHEMA = "mrbits.local-build.v2"
CPP_FLAGS = ["-std=c++17", "-O2"]
SQLITE_FLAGS = ["-O2", "-DSQLITE_DQS=0", "-DSQLITE_DEFAULT_FOREIGN_KEYS=1",
                "-DSQLITE_OMIT_LOAD_EXTENSION"]
# This historical helper used exactly SQLITE_FLAGS. V1 receipts only recorded
# the linker command, so unknown helpers cannot establish the C build recipe.
_LEGACY_SQLITE_BUILDERS = {"c7b812971230d48ae02767688e45ce267c38bee10c851cdbd2d96b0c42424900"}
_TOKENS = re.compile(
    r'R"(?P<delimiter>[^\s()\\]{0,16})\([\s\S]*?\)(?P=delimiter)"'
    r'|"(?:\\[\s\S]|[^"\\])*"|\'(?:\\[\s\S]|[^\'\\])*\''
    r'|//[^\n]*|/\*[\s\S]*?\*/'
)
_INCLUDE = re.compile(r"^\s*#\s*(include(?:_next)?)\b(.*)$", re.MULTILINE)


def _digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _project_path(path: Path, root: Path) -> Path:
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(f"Build dependency escapes engines: {path}")
    return resolved


def _directives(path: Path):
    # Join preprocessing line continuations before removing comments. Preserve
    # newlines to distinguish directives; ignore directive-looking raw strings.
    source = re.sub(r"\\\r?\n", "", path.read_text(encoding="utf-8-sig"))
    def clean(match):
        token = match.group()
        return ("\n" * token.count("\n") if token.startswith(("//", "/*", 'R"'))
                else token)
    return _INCLUDE.finditer(_TOKENS.sub(clean, source))


def dependency_inputs(source: Path, engines: Path, *, controller: bool = False) -> dict[str, str]:
    """Hash the literal project include closure, including inactive branches.

    Standard/system angle includes are supplied by the recorded toolchain.
    SQLite's vendored amalgamation is an explicit opaque C translation unit:
    its platform/custom includes are governed by our fixed SQLite build flags.
    """
    root = engines.resolve()
    pending = [_project_path(source, root)]
    found: dict[str, str] = {}
    while pending:
        path = pending.pop()
        name = path.relative_to(root).as_posix()
        if name in found:
            continue
        found[name] = _digest(path)
        for include in _directives(path):
            kind, value = include.groups()
            value = value.strip()
            literal = re.fullmatch(r'"([^"\n]+)"|<([^>\n]+)>', value)
            if kind != "include" or literal is None:
                raise ValueError(f"Unsupported dynamic include in {path}: #{kind} {value}")
            quoted, angled = literal.groups()
            include_name = quoted if quoted is not None else angled
            candidates = ([path.parent / include_name, root / include_name]
                          if quoted is not None else [root / include_name])
            local = next((candidate for candidate in candidates if candidate.is_file()), None)
            if local is None:
                if quoted is not None:
                    # Check escape even when the target does not currently exist.
                    for candidate in candidates:
                        _project_path(candidate, root)
                    raise FileNotFoundError(f"Missing quoted build dependency in {path}: {include_name}")
                continue
            pending.append(_project_path(local, root))
    if controller:
        for name in ("sqlite/sqlite3.c", "sqlite/sqlite3.h"):
            found[name] = _digest(_project_path(root / name, root))
    return dict(sorted(found.items()))


def _compiler_identity(value: str | None, name: str) -> dict[str, str]:
    selected = value or shutil.which(name)
    if not selected:
        raise RuntimeError(f"{name} was not found on PATH; cannot validate the local build toolchain.")
    path = Path(selected).resolve()
    return {"path": str(path), "sha256": _digest(path)}


def recipe(source: Path, engines: Path, *, controller: bool = False,
           compiler: str | None = None, c_compiler: str | None = None) -> dict:
    """Explicit compile/link contract; helper-script bytes are audit metadata only."""
    root = engines.resolve()
    value = {
        "contract": "mrbits.build-recipe.v1",
        "source": _project_path(source, root).relative_to(root).as_posix(),
        "include_directory": str(root),
        "cpp_compiler": _compiler_identity(compiler, "g++"),
        "cpp_flags": list(CPP_FLAGS),
        "build_stamp_define": "MRBITS_BUILD_STAMP",
    }
    if controller:
        value["sqlite"] = {"compiler": _compiler_identity(c_compiler, "gcc"),
                           "flags": list(SQLITE_FLAGS), "source": "sqlite/sqlite3.c",
                           "object": "sqlite/sqlite3.o"}
    return value


def _same_path(value, expected: Path) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return os.path.normcase(str(Path(value).resolve())) == os.path.normcase(str(expected.resolve()))
    except (OSError, ValueError):
        return False


def _legacy_command_matches(previous: dict, expected_recipe: dict, executable: Path,
                            source: Path, engines: Path, controller: bool) -> bool:
    recovered = previous.get("origin") == "verified_git_artifact_recovery"
    recovery = previous.get("recovery", {})
    if recovered and not isinstance(recovery, dict):
        return False
    command = (recovery.get("comparison_command") if recovered
               else previous.get("command"))
    if not isinstance(command, list) or len(command) != (10 if controller else 9):
        return False
    if not all(isinstance(item, str) for item in command):
        return False
    compiler_path = Path(expected_recipe["cpp_compiler"]["path"])
    if (not _same_path(command[0], compiler_path)
            or command[1:3] != CPP_FLAGS
            or command[4] != "-I" or not _same_path(command[5], engines)
            or not _same_path(command[6], source)
            or command[-2] != "-o"
            or not _same_path(command[-1], executable.with_name(executable.stem + ".building.exe"))):
        return False
    stamp_match = re.fullmatch(r'-DMRBITS_BUILD_STAMP="([A-Za-z0-9-]+)"', command[3])
    if stamp_match is None:
        return False
    if recovered:
        prefix = f'{previous.get("label")}-{_digest(source)[:12]}-'
        if re.fullmatch(re.escape(prefix) + r"\d{8}T\d{6}Z", stamp_match[1]) is None:
            return False
        if not all(isinstance(recovery.get(key), str) and recovery[key] for key in
                   ("git_blob", "comparison_executable_sha256", "equivalence_proof", "inputs_validation")):
            return False
    elif stamp_match[1] != previous.get("stamp"):
        return False
    if controller and not _same_path(command[7], engines / "sqlite/sqlite3.o"):
        return False
    if controller and previous.get("builder_sha256") not in _LEGACY_SQLITE_BUILDERS:
        return False
    # The known legacy helper establishes C flags; v2 records C identity too.
    return True


def validate_receipt(previous: dict, expected_inputs: dict, expected_recipe: dict,
                     executable: Path, *, source: Path, engines: Path,
                     controller: bool = False) -> bool:
    """Validate v2 receipts or strictly compatible v1 compilation provenance."""
    if not isinstance(previous, dict) or not executable.is_file():
        return False
    if previous.get("executable_sha256") != _digest(executable):
        return False
    validation = previous.get("cache_validation", {})
    if previous.get("schema") == SCHEMA:
        return (isinstance(validation, dict)
                and validation.get("inputs") == expected_inputs
                and validation.get("recipe") == expected_recipe)
    if previous.get("schema") != "mrbits.local-build.v1":
        return False
    old_inputs = previous.get("inputs")
    if not isinstance(old_inputs, dict) or any(old_inputs.get(k) != v for k, v in expected_inputs.items()):
        return False
    return _legacy_command_matches(previous, expected_recipe, executable, source, engines, controller)


def upgraded_receipt(previous: dict, inputs: dict, build_recipe: dict) -> dict:
    """Attach validation without inventing a compilation or rewriting its origin."""
    value = deepcopy(previous)
    prior_schema = value.get("schema")
    value["schema"] = SCHEMA
    value["cache_validation"] = {
        "inputs": deepcopy(inputs), "recipe": deepcopy(build_recipe),
        "validated_utc": datetime.now(timezone.utc).isoformat(),
        "method": "existing_artifact_dependency_and_recipe_validation",
    }
    if prior_schema != SCHEMA:
        value["cache_validation"]["previous_schema"] = prior_schema
    return value
