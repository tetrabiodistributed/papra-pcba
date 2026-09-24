"""Fabrication-output parity: what Eagle sent to the fab in 2023 vs what KiCad plots now.

Thresholds are per layer. Copper and mask are what get manufactured, so they are tight.
Silkscreen is loose: Eagle and KiCad render stroke fonts differently and the bottom silk
carries a bitmap logo, so only gross differences (a missing outline, a shifted layer)
would show. Overlay PNGs land in build/<part>/render/diff-<layer>.png: grey = both,
red = Eagle only, blue = KiCad only.
"""
from __future__ import annotations

import pytest

from . import gerbers

THRESHOLDS = {  # max mismatch as a fraction of the layer's drawn area (after closing)
    "F.Cu": 0.01,
    # Eagle let the hatched pour run ~0.3 mm closer to the outline than KiCad's 0.2 mm
    # edge clearance (from Eagle's own mdCopperDimension) allows; a perimeter strip.
    "B.Cu": 0.05,
    "F.Mask": 0.02, "B.Mask": 0.02,
    "F.SilkS": 0.20, "B.SilkS": 0.20,
    "Edge.Cuts": 0.30,
}
BBOX_TOL_MM = 0.2   # Eagle strokes the outline 0.254 mm wide, KiCad 0.05 mm


@pytest.fixture(scope="module")
def result():
    return gerbers.compare_all()


def test_board_outline_extents_match(result):
    diffs, _, _ = result
    edge = next(d for d in diffs if d.layer == "Edge.Cuts")
    assert edge.bbox_a == pytest.approx(edge.bbox_b, abs=BBOX_TOL_MM)


@pytest.mark.parametrize("layer", list(THRESHOLDS))
def test_layer_matches(result, layer):
    diffs, _, _ = result
    d = next((d for d in diffs if d.layer == layer), None)
    if d is None:
        pytest.skip(f"{layer} not in the Eagle Gerber set")
    assert d.bbox_a == pytest.approx(d.bbox_b, abs=1.0), "layer is offset"
    assert d.mismatch_ratio <= THRESHOLDS[layer], (
        f"{layer}: {d.mismatch_mm2:.2f} mm2 differs ({d.mismatch_ratio:.1%}), see {d.overlay}")


def test_drill_holes_identical(result):
    """Every hole: same position and diameter. Eagle rounds to um, so compare at 1 um.
    Eagle's slot-end holes on the DC jack are now part of plated slots and are skipped."""
    _, eagle_holes, kicad_holes = result
    x0, y0, x1, y1 = gerbers.EXCLUDE_MM["H1 plated slots"]
    eagle_holes = [h for h in eagle_holes if not (x0 <= h[0] <= x1 and y0 <= h[1] <= y1)]
    kicad_holes = [h for h in kicad_holes if not (x0 <= h[0] <= x1 and y0 <= h[1] <= y1)]
    assert len(eagle_holes) == len(kicad_holes)
    for a, b in zip(eagle_holes, kicad_holes):
        assert a == pytest.approx(b, abs=0.0015), (a, b)
