"""Render learning curves without opening a graphical window."""
from __future__ import annotations

import argparse
import csv
import html
import os
from pathlib import Path


def _svg(rows, output: Path) -> Path:
    """Small dependency-free SVG fallback; a real standalone vector artifact."""
    panels = (("Clipped-target Huber", ("train_huber", "val_huber")),
              ("Validation MAE (cp)", ("val_mae_cp",)),
              ("Training examples / second", ("examples_per_second",)))
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" width="1440" height="440" viewBox="0 0 1440 440">',
             '<rect width="1440" height="440" fill="#f8fafc"/>',
             '<g font-family="Arial,sans-serif" font-size="13" fill="#0f172a">']
    epochs = [int(row["epoch"]) for row in rows]
    colors = ("#2563eb", "#e11d48")
    for panel, (title, keys) in enumerate(panels):
        x0, y0, width, height = 65 + panel * 480, 60, 370, 300
        values = [float(row[key]) for key in keys for row in rows]
        low, high = min(values), max(values)
        padding = max((high - low) * 0.08, abs(high) * 0.01, 1e-6)
        low, high = max(0.0, low - padding), high + padding
        parts.append(f'<text x="{x0}" y="28" font-size="17">{html.escape(title)}</text>')
        for index in range(5):
            y = y0 + index * height / 4
            value = high - index * (high - low) / 4
            parts.append(f'<line x1="{x0}" y1="{y}" x2="{x0+width}" y2="{y}" stroke="#cbd5e1"/>')
            parts.append(f'<text x="{x0-7}" y="{y+4}" text-anchor="end">{value:.3g}</text>')
        for index, key in enumerate(keys):
            points = []
            for epoch, row in zip(epochs, rows):
                x = x0 + ((epoch - epochs[0]) / max(1, epochs[-1] - epochs[0])) * width
                y = y0 + (high - float(row[key])) / (high - low) * height
                points.append(f"{x:.2f},{y:.2f}")
                parts.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="3" fill="{colors[index]}"/>')
            parts.append(f'<polyline points="{" ".join(points)}" fill="none" stroke="{colors[index]}" stroke-width="2"/>')
            parts.append(f'<text x="{x0}" y="{400+index*17}" fill="{colors[index]}">{html.escape(key)}</text>')
        parts.append(f'<text x="{x0}" y="382">Epoch {epochs[0]}</text>')
        parts.append(f'<text x="{x0+width}" y="382" text-anchor="end">{epochs[-1]}</text>')
    parts.append("</g></svg>")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(parts), encoding="utf-8")
    return output


def render(run: str | Path, output: str | Path | None = None) -> Path:
    run = Path(run)
    with (run / "metrics.csv").open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    if not rows:
        raise ValueError("No completed epochs in metrics.csv yet")
    output = Path(output) if output else run / "curves.png"
    if output.suffix.lower() == ".svg":
        return _svg(rows, output)
    try:
        cache = Path(os.environ.get("MPLCONFIGDIR", Path.cwd() / ".cache" / "matplotlib"))
        cache.mkdir(parents=True, exist_ok=True)
        os.environ.setdefault("MPLCONFIGDIR", str(cache))
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return _svg(rows, output.with_suffix(".svg"))
    epochs = [int(row["epoch"]) for row in rows]
    figure, axes = plt.subplots(1, 3, figsize=(15, 4.5))
    axes[0].plot(epochs, [float(row["train_huber"]) for row in rows], label="Training")
    axes[0].plot(epochs, [float(row["val_huber"]) for row in rows], label="Validation")
    axes[0].set(title="Clipped-target Huber", xlabel="Completed epoch", ylabel="Loss")
    axes[0].legend()
    axes[1].plot(epochs, [float(row["val_mae_cp"]) for row in rows], color="#2563eb")
    axes[1].set(title="Raw teacher-score error", xlabel="Completed epoch", ylabel="Validation MAE (cp)")
    axes[2].plot(epochs, [float(row["examples_per_second"]) for row in rows], color="#15803d")
    axes[2].set(title="Training throughput", xlabel="Completed epoch", ylabel="Examples / second")
    for axis in axes:
        axis.grid(alpha=0.25)
    figure.tight_layout()
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=160)
    plt.close(figure)
    return output


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    print(render(args.run, args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
