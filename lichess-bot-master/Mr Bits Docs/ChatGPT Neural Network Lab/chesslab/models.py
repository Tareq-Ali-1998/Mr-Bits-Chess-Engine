"""The two lab models and a versioned, weights-only checkpoint reader."""
from __future__ import annotations

import copy
from pathlib import Path
import re
from typing import Any

import torch
from torch import nn

INPUT_DIM = 782
CHECKPOINT_VERSION = 1


def model_spec(name: str) -> dict[str, Any]:
    if name == "small":
        return {"name": "small", "kind": "mlp", "input_dim": INPUT_DIM,
                "hidden": [256, 64], "activation": "relu"}
    if name == "large":
        return {"name": "large", "kind": "residual", "input_dim": INPUT_DIM,
                "width": 1024, "blocks": 8, "head": 256, "activation": "relu"}
    raise ValueError("Model name must be 'small' or 'large'.")


def canonical_spec(spec: dict[str, Any] | str) -> dict[str, Any]:
    if isinstance(spec, str):
        spec = model_spec(spec)
    if not isinstance(spec, dict):
        raise ValueError("model must be a preset name or a model specification object")
    name = spec.get("name", "custom" if "kind" in spec else "small")
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", name):
        raise ValueError("Model name must be a safe 1-64 character experiment label (letters, digits, dot, underscore, hyphen)")
    if name in ("small", "large"):
        result = model_spec(name)
    else:
        if "kind" not in spec:
            raise ValueError("A custom model name requires an explicit kind and architecture fields")
        result = {"name": name, "input_dim": INPUT_DIM, "activation": "relu"}
    result.update(copy.deepcopy(spec))
    if result.get("input_dim") != INPUT_DIM:
        raise ValueError(f"This feature version requires {INPUT_DIM} inputs.")
    if result.get("kind") == "mlp":
        allowed = {"name", "kind", "input_dim", "hidden", "activation"}
        hidden = result.get("hidden")
        if not isinstance(hidden, list) or not hidden or not all(
            isinstance(x, int) and not isinstance(x, bool) and 1 <= x <= 4096 for x in hidden
        ):
            raise ValueError("hidden must be a nonempty list of positive widths <=4096")
    elif result.get("kind") == "residual":
        allowed = {"name", "kind", "input_dim", "width", "blocks", "head", "activation"}
        for key, upper in (("width", 4096), ("head", 4096), ("blocks", 64)):
            value = result.get(key)
            if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= upper:
                raise ValueError(f"{key} must be an integer between 1 and {upper}")
    else:
        raise ValueError("kind must be 'mlp' or 'residual'")
    if set(result) - allowed:
        raise ValueError(f"Unknown model keys: {sorted(set(result) - allowed)}")
    if result["activation"] not in ("relu", "gelu", "silu", "tanh"):
        raise ValueError("activation must be relu, gelu, silu, or tanh")
    return result


def activation_builder(name: str) -> nn.Module:
    """Stateless hidden activations; the score output always remains linear."""
    factories = {"relu": nn.ReLU, "gelu": nn.GELU, "silu": nn.SiLU, "tanh": nn.Tanh}
    if name not in factories:
        raise ValueError("activation must be relu, gelu, silu, or tanh")
    return factories[name]()


class ResidualBlock(nn.Module):
    def __init__(self, width: int, activation: str = "relu") -> None:
        super().__init__()
        self.first = nn.Linear(width, width)
        self.second = nn.Linear(width, width)
        self.activation = activation_builder(activation)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.activation(x + self.second(self.activation(self.first(x))))


class ResidualValueNet(nn.Module):
    def __init__(self, spec: dict[str, Any]) -> None:
        super().__init__()
        width = spec["width"]
        self.projection = nn.Linear(INPUT_DIM, width)
        self.blocks = nn.ModuleList(ResidualBlock(width, spec["activation"]) for _ in range(spec["blocks"]))
        self.head = nn.Linear(width, spec["head"])
        self.output = nn.Linear(spec["head"], 1)
        self.activation = activation_builder(spec["activation"])

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = self.activation(self.projection(x))
        for block in self.blocks:
            x = block(x)
        return self.output(self.activation(self.head(x)))


def build_model(spec: dict[str, Any] | str) -> nn.Module:
    """Build a float32 model; signed output is deliberately unconstrained."""
    spec = canonical_spec(spec)
    if spec["kind"] == "mlp":
        layers: list[nn.Module] = []
        previous = INPUT_DIM
        for width in spec["hidden"]:
            layers.extend((nn.Linear(previous, width), activation_builder(spec["activation"])))
            previous = width
        layers.append(nn.Linear(previous, 1))
        model: nn.Module = nn.Sequential(*layers)
    else:
        model = ResidualValueNet(spec)
    # Explicit initialization is part of this lab's reproducibility contract.
    for layer in model.modules():
        if isinstance(layer, nn.Linear):
            if spec["activation"] == "relu":
                nn.init.kaiming_uniform_(layer.weight, nonlinearity="relu")
            elif spec["activation"] == "tanh":
                nn.init.xavier_uniform_(layer.weight, gain=nn.init.calculate_gain("tanh"))
            else:
                # No built-in gain is specified for GELU/SiLU; gain=1 is an
                # explicit conservative starting experiment, not an optimality claim.
                nn.init.xavier_uniform_(layer.weight, gain=1.0)
            nn.init.zeros_(layer.bias)
    output = model[-1] if isinstance(model, nn.Sequential) else model.output
    nn.init.normal_(output.weight, mean=0.0, std=0.001)
    if isinstance(model, ResidualValueNet):
        # Zero residual contribution. With non-ReLU postactivations a block
        # initially computes activation(h), which is not an exact identity.
        for block in model.blocks:
            nn.init.zeros_(block.second.weight)
            nn.init.zeros_(block.second.bias)
    model.model_spec = spec
    return model


def model_statistics(spec: dict[str, Any] | str) -> dict[str, int]:
    """Dense Linear MACs only; different activations have different extra costs."""
    spec = canonical_spec(spec)
    if spec["kind"] == "mlp":
        dimensions = [INPUT_DIM, *spec["hidden"], 1]
        pairs = list(zip(dimensions[:-1], dimensions[1:]))
    else:
        pairs = [(INPUT_DIM, spec["width"])]
        pairs += [(spec["width"], spec["width"])] * (2 * spec["blocks"])
        pairs += [(spec["width"], spec["head"]), (spec["head"], 1)]
    parameters = sum(a * b + b for a, b in pairs)
    return {"parameters": parameters, "linear_layers": len(pairs),
            "dense_macs": sum(a * b for a, b in pairs), "float32_weight_bytes": 4 * parameters}


def load_checkpoint(path: str | Path, device: str | torch.device = "cpu") -> tuple[nn.Module, dict]:
    """Load lab state dictionaries, never unrestricted pickle objects.

    Only load checkpoints from a trusted source. weights_only limits deserialization
    to tensors/primitives; it is not a general hostile-file sandbox.
    """
    checkpoint = torch.load(Path(path), map_location="cpu", weights_only=True)
    if not isinstance(checkpoint, dict) or checkpoint.get("checkpoint_version") != CHECKPOINT_VERSION:
        raise ValueError("Unsupported or missing lab checkpoint version")
    from .features import FEATURE_VERSION
    if checkpoint.get("feature_version") != FEATURE_VERSION:
        raise ValueError("Checkpoint feature version is incompatible")
    target = checkpoint.get("target", {})
    if target.get("perspective") != "white" or target.get("units") != "pawns":
        raise ValueError("Checkpoint output must be White-perspective pawns")
    if not isinstance(target.get("clip_pawns"), (int, float)) or not 0 < target["clip_pawns"] < 1000:
        raise ValueError("Invalid checkpoint target clipping policy")
    model = build_model(checkpoint["model_spec"])
    model.load_state_dict(checkpoint["state_dict"], strict=True)
    if not all(torch.isfinite(parameter).all().item() for parameter in model.parameters()):
        raise ValueError("Checkpoint contains non-finite model weights")
    model.to(device).eval()
    return model, checkpoint
