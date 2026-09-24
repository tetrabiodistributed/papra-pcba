"""Minimal Excellon reader: enough for Eagle 9 and kicad-cli output (metric, decimal or
trailing-zero formats, tool table in the header, absolute coordinates)."""
from __future__ import annotations

import re
from pathlib import Path

Hole = tuple[float, float, float]  # x, y, diameter in mm


def load(path: Path) -> list[Hole]:
    text = path.read_text(errors="replace")
    tools: dict[str, float] = {}
    scale = 1.0  # multiplier applied to integer coordinates when the format has no decimal point
    decimals = 3
    inch = False
    in_header = True
    holes: list[Hole] = []
    tool = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(";"):
            continue
        if line in ("%", "M95"):
            in_header = False
            continue
        if line.startswith("METRIC") or line.startswith("INCH"):
            inch = line.startswith("INCH")
            m = re.search(r"(\d+)\.(\d+)", line)
            if m:
                decimals = len(m.group(2))
            continue
        m = re.match(r"T(\d+)C([\d.]+)", line)
        if m and in_header:
            tools[m.group(1)] = float(m.group(2)) * (25.4 if inch else 1)
            continue
        if line.startswith("T"):
            tool = re.match(r"T(\d+)", line).group(1)
            continue
        m = re.match(r"X(-?[\d.]+)Y(-?[\d.]+)", line)
        if "G85" in line:
            continue  # routed slot, not a drilled hole
        if m and tool is not None:
            xs, ys = m.group(1), m.group(2)
            def val(s: str) -> float:
                v = float(s) if "." in s else float(s) / (10 ** decimals)
                return v * (25.4 if inch else 1)
            holes.append((round(val(xs), 3), round(val(ys), 3), round(tools[tool], 3)))
    return holes
