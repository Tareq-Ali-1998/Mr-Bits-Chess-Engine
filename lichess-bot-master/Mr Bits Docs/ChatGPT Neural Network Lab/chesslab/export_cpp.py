"""Export the two frozen ReLU presets as checked FP32 C++ weight files.

The engine does not need Python, PyTorch, CUDA, or checkpoint optimizer states.
The first matrix is transposed to make sparse binary feature accumulation cheap.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import struct
import tempfile
import zlib

import numpy as np
import torch

from .data import sha256_file
from .features import feature_contract
from .models import load_checkpoint, model_spec, model_statistics

MAGIC = b"MRBNN001"
HEADER = struct.Struct("<8s8I24s")
SCHEMA = "chesslab.cpp-fp32.v1"


def layer_names(name: str) -> list[str]:
    if name == "small":
        return ["0", "2", "4"]
    if name == "large":
        return ["projection", *[f"blocks.{i}.{part}" for i in range(8)
                                for part in ("first", "second")], "head", "output"]
    raise ValueError("The C++ v1 export supports only the frozen small/large ReLU presets")


def serialize_weights(model: torch.nn.Module, spec: dict) -> tuple[bytes, dict]:
    """Return deterministic little-endian bytes and an auditable layer manifest."""
    name = spec.get("name")
    if name not in ("small", "large") or spec != model_spec(name):
        raise ValueError("Architecture differs from the frozen small/large C++ v1 contract")
    state = model.state_dict()
    chunks: list[bytes] = []
    layers = []
    offset = HEADER.size
    for index, prefix in enumerate(layer_names(name)):
        w = state[prefix + ".weight"].detach().cpu().float().numpy()
        b = state[prefix + ".bias"].detach().cpu().float().numpy()
        if w.ndim != 2 or b.shape != (w.shape[0],):
            raise ValueError(f"Unexpected weight/bias shape in {prefix}")
        if not np.isfinite(w).all() or not np.isfinite(b).all():
            raise ValueError(f"Nonfinite parameters in {prefix}")
        matrix = w.T if index == 0 else w
        weight_bytes = np.asarray(matrix, dtype="<f4", order="C").tobytes(order="C")
        bias_bytes = np.asarray(b, dtype="<f4", order="C").tobytes(order="C")
        layers.append({"name": prefix, "input": int(w.shape[1]), "output": int(w.shape[0]),
                       "weight_layout": "input_output" if index == 0 else "output_input",
                       "weight_offset_bytes": offset, "weight_bytes": len(weight_bytes),
                       "bias_offset_bytes": offset + len(weight_bytes), "bias_bytes": len(bias_bytes)})
        chunks.extend((weight_bytes, bias_bytes))
        offset += len(weight_bytes) + len(bias_bytes)
    payload = b"".join(chunks)
    stats = model_statistics(spec)
    if len(payload) != stats["float32_weight_bytes"]:
        raise ValueError("Serialized parameter count differs from model architecture")
    crc = zlib.crc32(payload) & 0xFFFFFFFF
    header = HEADER.pack(MAGIC, 1 if name == "small" else 2, 782, stats["parameters"],
                         len(layers), 256 if name == "small" else 1024,
                         0 if name == "small" else 8, 64 if name == "small" else 256,
                         crc, bytes(24))
    return header + payload, {"header_bytes": HEADER.size, "payload_bytes": len(payload),
                              "payload_crc32": f"{crc:08x}", "layers": layers, **stats}


def export_checkpoint(checkpoint_path: str | Path, output: str | Path, *,
                      reuse_existing: bool = False) -> dict:
    checkpoint_path, output = Path(checkpoint_path), Path(output)
    sidecar = output.with_name("model.json")
    checkpoint_digest = sha256_file(checkpoint_path)
    if output.exists() or sidecar.exists():
        if reuse_existing and output.is_file() and sidecar.is_file():
            metadata = json.loads(sidecar.read_text(encoding="utf-8"))
            if (metadata.get("schema") == SCHEMA
                    and metadata.get("checkpoint_sha256") == checkpoint_digest
                    and metadata.get("sha256") == sha256_file(output)):
                return metadata
        raise FileExistsError("Export already exists; only exact intact --reuse-existing is permitted")
    model, checkpoint = load_checkpoint(checkpoint_path, "cpu")
    binary, layout = serialize_weights(model, checkpoint["model_spec"])
    metadata = {"schema": SCHEMA, "model_spec": checkpoint["model_spec"],
                "format": "64-byte versioned header + little-endian IEEE754 float32 payload",
                "feature_contract": feature_contract(), "output": {
                    "perspective": "white", "units": "pawns", "activation": "linear, unbounded",
                    "terminal_policy": "caller resolves exact terminals and draws before inference"},
                "checkpoint": checkpoint_path.name, "checkpoint_sha256": checkpoint_digest,
                "epoch": checkpoint.get("epoch"), "step": checkpoint.get("step"),
                "data_fingerprint": checkpoint.get("data_fingerprint"),
                "target": checkpoint["target"], "torch_version": str(torch.__version__),
                "quantized": False, "layout": layout,
                "verification": "Run scripts/verify_cpp.py to check actual C++ outputs against this checkpoint"}
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=output.parent, prefix=output.name + ".", suffix=".tmp", delete=False) as f:
        temporary = Path(f.name)
        f.write(binary)
    try:
        metadata["sha256"] = sha256_file(temporary)
        temporary.replace(output)
        sidecar.write_text(json.dumps(metadata, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")
    finally:
        temporary.unlink(missing_ok=True)
    return metadata


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path, help="Model folder/weights.bin; model.json is written alongside")
    parser.add_argument("--reuse-existing", action="store_true", help="Reuse only the exact intact export from this checkpoint")
    args = parser.parse_args(argv)
    torch.set_num_threads(4)
    metadata = export_checkpoint(args.checkpoint, args.output, reuse_existing=args.reuse_existing)
    print(json.dumps({key: metadata[key] for key in ("model_spec", "sha256", "layout")}, indent=2))


if __name__ == "__main__":
    main()
