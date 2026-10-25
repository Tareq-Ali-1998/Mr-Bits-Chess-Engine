"""Export a checked dense FP32 TorchScript evaluator and its input contract."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import tempfile

import torch

from .features import FEATURE_VERSION
from .data import sha256_file
from .models import load_checkpoint


def export_checkpoint(checkpoint_path: str | Path, output: str | Path, *, samples: int = 128,
                      atol: float = 1e-5, rtol: float = 1e-5, reuse_existing: bool = False) -> dict:
    if samples < 1 or min(atol, rtol) < 0:
        raise ValueError("Positive sample count and nonnegative tolerances required")
    output = Path(output)
    sidecar = output.with_suffix(output.suffix + ".json")
    checkpoint_digest = sha256_file(checkpoint_path)
    if output.exists() or sidecar.exists():
        if reuse_existing and output.is_file() and sidecar.is_file():
            previous = json.loads(sidecar.read_text(encoding="utf-8"))
            if (previous.get("schema") == "chesslab.torchscript-export.v1"
                    and previous.get("checkpoint_sha256") == checkpoint_digest
                    and previous.get("sha256") == sha256_file(output)
                    and previous.get("feature_version") == FEATURE_VERSION):
                return previous
        raise FileExistsError("Refusing to overwrite an existing export or sidecar")
    model, checkpoint = load_checkpoint(checkpoint_path, "cpu")
    model = model.float().eval()
    # Model inference is dense: feature expansion is deliberately an external,
    # independently specified part of this deployment interface.
    generator = torch.Generator().manual_seed(20261022)
    examples = torch.randint(0, 2, (samples, 782), generator=generator).float()
    cases = [torch.zeros(1, 782), torch.ones(1, 782), examples[:1], examples]
    with torch.inference_mode():
        traced = torch.jit.trace(model, examples[:1], check_trace=True).eval()
        max_abs = 0.0
        for inputs in cases:
            expected = model(inputs)
            actual = traced(inputs)
            if expected.shape != (len(inputs), 1) or not torch.isfinite(expected).all().item():
                raise ValueError("Checkpoint does not produce finite [B,1] scores")
            if actual.shape != expected.shape or not torch.isfinite(actual).all().item():
                raise ValueError("Export output shape or finiteness differs")
            torch.testing.assert_close(actual, expected, atol=atol, rtol=rtol)
            max_abs = max(max_abs, float((actual - expected).abs().max()))
    metadata = {"schema": "chesslab.torchscript-export.v1", "feature_version": FEATURE_VERSION,
                "format": "TorchScript", "model_spec": checkpoint["model_spec"],
                "checkpoint_sha256": checkpoint_digest,
                "input": {"dtype": "float32", "shape": ["batch", 782],
                          "order": "12 piece planes P,N,B,R,Q,K,p,n,b,r,q,k, each a8..h1; turn; K,Q,k,q; EP none,a..h",
                          "turn": "1 White, 0 Black", "castling": "retained rights, not immediate castling legality",
                          "en_passant": "raw FEN target file; none is its own one-hot entry",
                          "omitted": ["halfmove clock", "fullmove number", "repetition history"]},
                "output": {"dtype": "float32", "shape": ["batch", 1],
                           "perspective": "white", "units": "pawns", "activation": "linear, unbounded",
                           "target": checkpoint["target"],
                           "terminal_policy": "caller handles exact terminals before model scoring"},
                "data_fingerprint": checkpoint.get("data_fingerprint"),
                "validation": {"seed": 20261022, "random_binary_examples": samples,
                               "extra_cases": "zero and all-one features; batch-one and multi-batch",
                               "legal_chess_guarantee": False, "max_abs_error": max_abs,
                               "atol": atol, "rtol": rtol},
                "torch_version": str(torch.__version__)}
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(prefix=output.name + ".", suffix=".tmp", dir=output.parent, delete=False) as handle:
        temporary = Path(handle.name)
    try:
        torch.jit.save(traced, str(temporary))
        # Reload the actual serialized bytes before committing the artifact.
        reloaded = torch.jit.load(str(temporary), map_location="cpu").eval()
        with torch.inference_mode():
            torch.testing.assert_close(reloaded(examples), model(examples), atol=atol, rtol=rtol)
        metadata["sha256"] = hashlib.sha256(temporary.read_bytes()).hexdigest()
        temporary.replace(output)
        sidecar.write_text(json.dumps(metadata, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    finally:
        temporary.unlink(missing_ok=True)
    return metadata


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--output", required=True, help="New .pt artifact; contract written alongside as .pt.json")
    parser.add_argument("--samples", type=int, default=128)
    parser.add_argument("--reuse-existing", action="store_true", help="Reuse only an intact artifact from this exact checkpoint; never overwrite")
    args = parser.parse_args(argv)
    print(json.dumps(export_checkpoint(args.checkpoint, args.output, samples=args.samples, reuse_existing=args.reuse_existing), indent=2))


if __name__ == "__main__":
    main()
