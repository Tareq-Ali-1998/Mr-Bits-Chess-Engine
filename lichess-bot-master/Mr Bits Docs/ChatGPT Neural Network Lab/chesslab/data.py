"""Memory-mapped prepared records; no full float feature matrix in RAM."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

from .features import FEATURE_VERSION, PACKED_SIZE

RECORD_DTYPE = np.dtype([
    ("position", "u1", (PACKED_SIZE,)),
    ("cp", "<i4"),
    ("depth", "<u2"),
    ("knodes", "<u8"),
    ("key", "u1", (16,)),
])
SPLITS = ("train", "validation", "test")


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def compute_manifest_fingerprint(manifest: dict) -> str:
    stable = {key: value for key, value in manifest.items()
              if key not in ("created_utc", "preparation_seconds", "fingerprint")}
    encoded = json.dumps(stable, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def load_manifest(directory: str | Path) -> dict:
    path = Path(directory) / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("feature_version") != FEATURE_VERSION:
        raise ValueError("Dataset feature version does not match board782_v1")
    if manifest.get("schema") != "chesslab.prepared.v1":
        raise ValueError("Unsupported prepared dataset schema")
    if manifest.get("fingerprint") != compute_manifest_fingerprint(manifest):
        raise ValueError("Dataset manifest fingerprint mismatch: metadata changed or release is incomplete")
    return manifest


def manifest_fingerprint(directory: str | Path) -> str:
    return load_manifest(directory)["fingerprint"]


class PositionDataset:
    """Dataset protocol for torch DataLoader; returns compact board and raw cp."""

    def __init__(self, directory: str | Path, split: str = "train"):
        if split not in SPLITS:
            raise ValueError(f"split must be one of {SPLITS}")
        self.directory = Path(directory)
        self.split = split
        self.manifest = load_manifest(self.directory)
        self._records = None
        self._length = int(self.manifest["counts"][split])
        records = self.records
        if records.dtype != RECORD_DTYPE or len(records) != self._length:
            raise ValueError("Dataset record layout/count differs from the manifest")

    @property
    def records(self) -> np.ndarray:
        if self._records is None:
            self._records = np.load(self.directory / f"{self.split}.npy", mmap_mode="r", allow_pickle=False)
        return self._records

    @property
    def data(self) -> np.ndarray:
        return self.records

    def __len__(self):
        return self._length

    def __getitem__(self, index):
        import torch

        row = self.records[index]
        return (
            torch.from_numpy(np.array(row["position"], copy=True)),
            torch.tensor([float(row["cp"])], dtype=torch.float32),
        )

    def __getstate__(self):
        result = dict(self.__dict__)
        result["_records"] = None  # Workers open their own small mmap descriptors.
        return result

    def close(self):
        """Release this process's mmap when no outstanding record views are used."""
        if self._records is not None:
            self._records._mmap.close()
            self._records = None


def verify_dataset(directory: str | Path) -> dict:
    """Opt-in full file integrity check; ordinary loading checks shapes only."""
    directory = Path(directory)
    manifest = load_manifest(directory)
    for split in SPLITS:
        dataset = PositionDataset(directory, split)
        dataset.close()
        actual = sha256_file(directory / f"{split}.npy")
        if actual != manifest["files"][f"{split}.npy"]["sha256"]:
            raise ValueError(f"Checksum mismatch: {split}.npy")
    return manifest
