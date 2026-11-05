"""Resolve historical diagnostic keys to the current family-named sources.

Diagnostic filenames, macros and schemas retain their original names so old
reports remain interpretable. Source paths and new report metadata use the
same version mapping as the launcher.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Kernels"))
from kernel_tools import LEGACY_TO_FAMILY

FAMILY_TO_LEGACY = {family: legacy for legacy, family in LEGACY_TO_FAMILY.items()}


def canonical_version(value: str) -> str:
    return LEGACY_TO_FAMILY.get(value, value)


def legacy_version(value: str) -> str:
    return FAMILY_TO_LEGACY.get(value, value)


def kernel_source(engines: Path, value: str) -> Path:
    version = canonical_version(value)
    return engines / "Kernels" / version / f"Kernel-{version}.cpp"
