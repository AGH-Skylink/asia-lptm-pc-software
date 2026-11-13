"""Combined BER and signal plots with bit-1 labels on individual samples."""

from __future__ import annotations

import csv
import os
from pathlib import Path
from tempfile import gettempdir


def _labels(axis, figure, points):
    """Place short labels in free screen-space lanes around the samples."""
    figure.canvas.draw()
    occupied = []
    bounds = axis.bbox
    dpi_scale = 72 / figure.dpi
    offsets = [(x, y) for y in (13, 27, -13, -27, 41, -41, 55, -55)
               for x in (7, -7, 24, -24, 42, -42)]
    for speed, value, label, color in sorted(points, key=lambda point: (point[1], point[0])):
        px, py = axis.transData.transform((speed, value))
        width = 9 * len(label) + 6
        height = 18
        candidates = []
        for dx, dy in offsets:
            left = px + dx if dx > 0 else px + dx - width
            bottom = py + dy - height / 2
            box = (left, bottom, left + width, bottom + height)
            outside = max(0, bounds.x0 + 3 - box[0]) + max(0, box[2] - bounds.x1 + 18)
            outside += max(0, bounds.y0 + 3 - box[1]) + max(0, box[3] - bounds.y1 - 15)
            overlap = sum(max(0, min(box[2], old[2]) - max(box[0], old[0]))
                          * max(0, min(box[3], old[3]) - max(box[1], old[1]))
                          for old in occupied)
            candidates.append((outside * 100 + overlap + abs(dx) + abs(dy) * 0.25,
                               dx, dy, box))
        _, dx, dy, box = min(candidates)
        occupied.append(box)
        axis.annotate(label, (speed, value), xytext=(dx * dpi_scale, dy * dpi_scale),
                      textcoords="offset points", ha="left" if dx > 0 else "right",
                      va="center", color=color, fontsize=7.5,
                      arrowprops={"arrowstyle": "-", "color": "#888888", "lw": 0.4}
                      if abs(dx) + abs(dy) > 35 else None)


def _frequency_label(hz: str) -> str:
    value = int(hz)
    return f"{value / 1000:g}k" if value >= 1000 else str(value)


def make_combined_plots(csv_path: Path, description: str = "") -> tuple[Path, Path]:
    cache = Path(gettempdir()) / "sound_matplotlib_cache"
    cache.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR", str(cache))
    os.environ.setdefault("XDG_CACHE_HOME", str(cache))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import LogNorm

    with csv_path.open(newline="", encoding="utf-8") as source:
        rows = list(csv.DictReader(source))
    if not rows:
        raise ValueError("Tabela pomiarów jest pusta.")
    zero_values = [int(row["bit_0_hz"]) for row in rows]
    norm = LogNorm(vmin=min(zero_values), vmax=max(zero_values) + 1)
    outputs = []
    for column, ylabel, suffix in (
        ("ber_percent", "BER [%]", "ber_vs_bps.png"),
        ("signal_rms_dbfs", "Siła sygnału, RMS [dBFS]", "signal_vs_bps.png"),
    ):
        figure, axis = plt.subplots(figsize=(17, 9), layout="constrained")
        positions = {}
        for row in rows:
            if row[column] == "":
                continue
            key = (float(row["speed_bps"]), float(row[column]))
            positions.setdefault(key, []).append(row)
        labels = []
        for (speed, value), samples in sorted(positions.items()):
            no_frame = any(sample["ber_percent"] != "" and float(sample["ber_percent"]) == 100
                           for sample in samples)
            color = "#b22222" if no_frame else plt.cm.viridis(norm(int(samples[0]["bit_0_hz"])))
            axis.scatter(speed, value, color=color, marker="x" if no_frame else "o",
                         s=48 + 20 * (len(samples) - 1), zorder=3)
            label = "/".join(_frequency_label(sample["bit_1_hz"]) for sample in samples)
            labels.append((speed, value, label, "#9a1a1a" if no_frame else "#243344"))
        axis.set_xscale("log")
        axis.set_xlim(min(float(row["speed_bps"]) for row in rows) * 0.7,
                      max(float(row["speed_bps"]) for row in rows) * 1.42)
        if column == "ber_percent":
            axis.set_ylim(-9, 114)
        axis.grid(True, which="both", alpha=0.25)
        axis.set_xlabel("Szybkość transmisji [bit/s]")
        axis.set_ylabel(ylabel)
        note = "Etykieta punktu = bit 1 [Hz], k = 1000"
        if any(row["ber_percent"] != "" and float(row["ber_percent"]) == 100 for row in rows):
            note += "; czerwony × = brak ramki, umowny BER 100%"
        figure.suptitle(f"{ylabel} od szybkości transmisji — {description}\n{note}", fontsize=14)
        colorbar = figure.colorbar(plt.cm.ScalarMappable(norm=norm, cmap="viridis"), ax=axis,
                                   fraction=0.028, pad=0.015)
        colorbar.set_label("bit 0 [Hz]")
        _labels(axis, figure, labels)
        target = csv_path.with_name(f"{csv_path.stem}_{suffix}")
        figure.savefig(target, dpi=170)
        plt.close(figure)
        outputs.append(target)
    return tuple(outputs)
