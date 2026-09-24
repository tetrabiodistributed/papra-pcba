"""Solve a model's rotation and offset from its geometry and the datasheet rules.

    .venv/bin/python -m checks.model_solve POT1 H2 BATT+0 U1

For each of the 24 axis-aligned rotations, the model is placed with KiCad's own transform
(checks/model_geom.py), the offset that seats it on the board over its pads is computed
directly, and the result is scored against checks/parts.py PLACEMENT. Rotations that pass
are printed as ready-to-paste entries for checks/models.py.
"""
from __future__ import annotations

import itertools
import sys

import numpy as np

from . import model_geom as g
from .parts import PLACEMENT
from .test_models import violations

ANGLES = (0.0, 90.0, 180.0, 270.0)


def _offset_for(entry: dict, rot, rule: dict) -> tuple[float, float, float]:
    """Offset (model frame, after rotation) that puts the leads through the pads and the
    body seated: solved from the zero-offset placement by inverting the post-offset chain."""
    cloud = g.canonical_cloud(entry["model"])
    v = g.place(cloud, (0, 0, 0), rot, entry["scale"], entry["fp_x"], entry["fp_y"], entry["fp_deg"], entry["back"])
    back = entry["back"]
    z = v[:, 2]
    # seat: pin reach past the seating surface equals the datasheet value
    pins = sum(rule["pins"]) / 2
    dz = (-g.BOARD_T + pins - z.max()) if back else (-pins - z.min())
    # centre the pins on the pads, or a pinless module's base slab on the pad centre
    zz = z + dz
    seat = -g.BOARD_T if back else 0.0
    part = v[zz > seat + 0.25] if back else v[zz < seat - 0.25]
    if len(part) == 0:
        part = v[(zz < seat) & (zz > seat - 1.3)] if back else v[(zz > seat) & (zz < seat + 1.3)]
    px = np.array([p[0] for p in entry["pads"]]); py = np.array([p[1] for p in entry["pads"]])
    dx = (px.min() + px.max()) / 2 - (part[:, 0].min() + part[:, 0].max()) / 2
    dy = (py.min() + py.max()) / 2 - (part[:, 1].min() + part[:, 1].max()) / 2
    d = np.array([dx, dy, dz])
    # world delta -> model offset: undo Rz(fp) then the back-side flip
    d = g._R("z", -entry["fp_deg"]) @ d
    if back:
        d = (g._R("y", 180) @ g._R("z", 180)).T @ d
    return tuple(round(float(x), 2) for x in d)


def solve(ref: str):
    entry = next(e for e in g.board_models() if e["ref"] == ref)
    rule = PLACEMENT[ref]
    hits = []
    for rot in itertools.product(ANGLES, repeat=3):
        off = _offset_for(entry, rot, rule)
        e = dict(entry, rotate=rot, offset=off)
        bad = violations(e, rule)
        if not bad:
            hits.append((rot, off))
    return entry, hits


if __name__ == "__main__":
    for ref in sys.argv[1:] or sorted(PLACEMENT):
        entry, hits = solve(ref)
        print(f"{ref}: {len(hits)} of 64 rotation triples pass")
        seen = set()
        for rot, off in hits:
            v = g.placed(dict(entry, rotate=rot, offset=off))
            key = tuple(np.round(v.mean(0), 1))
            tag = "" if key not in seen else "  (same placement)"
            seen.add(key)
            print(f"   rotate {rot} offset {off}{tag}")
