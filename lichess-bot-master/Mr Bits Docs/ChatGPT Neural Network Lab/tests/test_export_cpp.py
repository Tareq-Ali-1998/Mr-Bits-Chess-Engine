"""Deployment boundaries: frozen architectures, byte order, and reuse integrity."""
from __future__ import annotations

import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import zlib

import torch

from chesslab.export_cpp import HEADER, MAGIC, export_checkpoint, serialize_weights
from chesslab.models import build_model, model_spec


class CppExportTests(unittest.TestCase):
    def setUp(self):
        self.model = build_model("small")
        self.spec = model_spec("small")

    def test_sparse_projection_layout_and_portable_header(self):
        # A known feature-column must survive transpose without losing a bit.
        with torch.no_grad():
            self.model[0].weight[19, 777] = -1.234567
        raw, layout = serialize_weights(self.model, self.spec)
        fields = HEADER.unpack_from(raw)
        self.assertEqual(HEADER.size, 64)
        self.assertEqual(fields[:8], (MAGIC, 1, 782, 216961, 3, 256, 0, 64))
        self.assertEqual(fields[8], zlib.crc32(raw[64:]) & 0xFFFFFFFF)
        self.assertEqual(fields[9], bytes(24))
        actual = struct.unpack_from("<f", raw, 64 + (777 * 256 + 19) * 4)[0]
        self.assertEqual(actual, self.model[0].weight[19, 777].item())
        self.assertEqual(len(raw), 64 + 216961 * 4)
        self.assertEqual(layout["layers"][0]["weight_layout"], "input_output")
        self.assertEqual(layout["layers"][1]["weight_layout"], "output_input")

    def test_changed_architecture_or_activation_cannot_silently_export(self):
        for changed in ({**self.spec, "activation": "silu"}, {**self.spec, "hidden": [256, 65]},
                        {**self.spec, "name": "other"}):
            with self.assertRaises(ValueError):
                serialize_weights(self.model, changed)

    def test_nonfinite_parameters_are_rejected(self):
        with torch.no_grad():
            self.model[2].bias[3] = float("inf")
        with self.assertRaisesRegex(ValueError, "Nonfinite"):
            serialize_weights(self.model, self.spec)

    def test_reuse_requires_same_checkpoint_and_unchanged_binary(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            checkpoint = directory / "best.pt"
            checkpoint.write_bytes(b"mocked trusted checkpoint")
            output = directory / "weights.bin"
            contract = {"model_spec": self.spec, "target": {"perspective": "white", "units": "pawns", "clip_pawns": 15},
                        "epoch": 20, "step": 87920, "data_fingerprint": "fixture"}
            with patch("chesslab.export_cpp.load_checkpoint", return_value=(self.model, contract)):
                first = export_checkpoint(checkpoint, output)
            self.assertEqual(json.loads((directory / "model.json").read_text())["sha256"], first["sha256"])
            self.assertEqual(export_checkpoint(checkpoint, output, reuse_existing=True), first)
            with self.assertRaises(FileExistsError):
                export_checkpoint(checkpoint, output)
            damaged = bytearray(output.read_bytes()); damaged[-1] ^= 1
            output.write_bytes(damaged)
            with self.assertRaises(FileExistsError):
                export_checkpoint(checkpoint, output, reuse_existing=True)
            checkpoint.write_bytes(b"different checkpoint")
            with self.assertRaises(FileExistsError):
                export_checkpoint(checkpoint, output, reuse_existing=True)


if __name__ == "__main__":
    unittest.main()
