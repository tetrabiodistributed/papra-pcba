"""3D models sit where the parts sit, computed with KiCad's own model transform.

checks/model_geom.py places each model's geometry exactly as the 3D viewer does. Parts
with datasheet rules (checks/parts.py PLACEMENT) are held to them; every other model must
be on its own side of the board with only leads through it, landing on its pads.
"""
from __future__ import annotations

import numpy as np
import pytest

from . import model_geom as g
from .parts import PLACEMENT

PINS_MAX_MM = 10.0     # library models carry full leads (KiCad's TO-220 has 9.75 mm)
PIN_TOL_MM = 2.0       # a pin's material lies within this of the centre of one of the pads
BASE_MM = 1.3          # the slab just above the seating surface: a module's own PCB, a body's base


def measure(entry: dict) -> dict:
    v = g.placed(entry)
    z = v[:, 2]
    back = entry["back"]
    seat = -g.BOARD_T if back else 0.0
    height = (seat - z.min()) if back else (z.max() - seat)
    pins = (z.max() - seat) if back else (seat - z.min())
    pin_pts = v[z > seat + 0.25] if back else v[z < seat - 0.25]          # past the seating surface
    base = v[(z < seat) & (z > seat - BASE_MM)] if back else v[(z > seat) & (z < seat + BASE_MM)]
    end = v[z < z.min() + 1.0] if back else v[z > z.max() - 1.0]         # furthest from the board
    top = v[z < seat - 3.5] if back else v[z > seat + 3.5]
    pads = np.array(entry["pads"])
    if len(pin_pts):
        d = np.sqrt(((pin_pts[:, None, :2] - pads[None, :, :]) ** 2).sum(-1)).min(1)
        pin_miss = float(d.max())
    else:
        pin_miss = 0.0
    return {
        "height": float(height), "pins": float(pins),
        "end_width": float(max(np.ptp(end[:, 0]), np.ptp(end[:, 1]))),
        "base": (float(np.ptp(base[:, 0])), float(np.ptp(base[:, 1]))) if len(base) else (0.0, 0.0),
        "top_y": float(top[:, 1].mean()) if len(top) else None,
        "x": (float(v[:, 0].min()), float(v[:, 0].max())),
        "y": (float(v[:, 1].min()), float(v[:, 1].max())),
        "pin_miss": pin_miss,
    }


def violations(entry: dict, rule: dict | None) -> list[str]:
    m = measure(entry)
    bad = []
    if rule:
        for key in ("height", "pins", "end_width"):
            if key in rule and not rule[key][0] <= m[key] <= rule[key][1]:
                bad.append(f"{key} {m[key]:.2f} not in {rule[key]}")
        if "reach_y" in rule and not rule["reach_y"][0] <= m["y"][1] <= rule["reach_y"][1]:
            bad.append(f"far y extreme {m['y'][1]:.1f} not in {rule['reach_y']}")
        for key in ("x", "y"):
            if key in rule and not (rule[key][0] <= m[key][0] and m[key][1] <= rule[key][1]):
                bad.append(f"{key} {m[key][0]:.1f}..{m[key][1]:.1f} not within {rule[key]}")
        if "top_y" in rule and (m["top_y"] is None or not rule["top_y"][0] <= m["top_y"] <= rule["top_y"][1]):
            bad.append(f"tallest material centred at y {m['top_y']}: not in {rule['top_y']}")
        if "base" in rule and not (m["base"][0] >= rule["base"][0] and m["base"][1] >= rule["base"][1]):
            bad.append(f"base slab {m['base'][0]:.1f} x {m['base'][1]:.1f} smaller than {rule['base']}: not sitting on its own base")
    else:
        if m["pins"] > PINS_MAX_MM:
            bad.append(f"{m['pins']:.1f} mm past the seating surface: body on the wrong side")
        if m["pins"] < -0.5:
            bad.append(f"floating {-m['pins']:.1f} mm off the board")
    if m["pin_miss"] > (rule or {}).get("pin_tol", PIN_TOL_MM):
        bad.append(f"pin material {m['pin_miss']:.1f} mm from the nearest pad centre")
    return bad


ENTRIES = {e["ref"]: e for e in g.board_models()}


@pytest.mark.parametrize("ref", sorted(ENTRIES))
def test_model_seated_on_its_pads(ref):
    entry = ENTRIES[ref]
    bad = violations(entry, PLACEMENT.get(ref))
    assert not bad, f"{ref}: " + "; ".join(bad)


def test_every_ruled_part_has_a_model():
    assert set(PLACEMENT) <= set(ENTRIES), sorted(set(PLACEMENT) - set(ENTRIES))


def test_model_geometry_extraction_matches_the_step_file():
    """The cloud KiCad hands back for a plain single-solid STEP is the STEP's own points."""
    path = g.resolve(g.CALIBRATION_STEP)
    raw, cloud = g.step_points(path), g.canonical_cloud(g.CALIBRATION_STEP)
    assert np.allclose(raw.min(0), cloud.min(0), atol=0.1) and np.allclose(raw.max(0), cloud.max(0), atol=0.1), (raw.min(0), cloud.min(0), raw.max(0), cloud.max(0))
