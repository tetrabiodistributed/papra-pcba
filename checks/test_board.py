"""Eagle .brd vs imported .kicad_pcb: same parts, same connectivity, same copper geometry."""
from __future__ import annotations

import pytest

from . import config, eagle, kicad, paths


@pytest.fixture(scope="module")
def eb() -> eagle.Board:
    return eagle.load_board(paths.EAGLE_BRD)


@pytest.fixture(scope="module")
def kb() -> kicad.KBoard:
    if not paths.KICAD_PCB.exists():
        pytest.fail(f"{paths.KICAD_PCB} missing; run `make import-pcb`")
    return kicad.load_board(paths.KICAD_PCB)


def eagle_ref(ref: str) -> str:
    return config.REF_RENAMES.get(ref, ref)


def real_footprints(kb: kicad.KBoard) -> dict[str, kicad.Footprint]:
    return {eagle_ref(r): f for r, f in kb.footprints.items() if not r.startswith(config.HOLE_REF_PREFIX)}


def test_every_eagle_element_has_exactly_one_footprint(eb, kb):
    fps = real_footprints(kb)
    assert set(fps) == set(eb.elements)
    assert len(fps) == len(kb.footprints) - len(eb.holes)


def test_footprint_values_match(eb, kb):
    """Board values follow the schematic symbol (Eagle's board and schematic disagree on the
    three test pads; KiCad's parity check wants them equal)."""
    es = eagle.load_schematic(paths.EAGLE_SCH)
    want = {r: (es.parts[r].value or es.parts[r].deviceset) if r in es.parts else e.value for r, e in eb.elements.items()}
    mismatched = {r: (want[r], real_footprints(kb)[r].value) for r in eb.elements if want[r] != real_footprints(kb)[r].value}
    assert mismatched == {}


def test_footprint_placement_and_side(eb, kb):
    """KiCad keeps Eagle's origin and mirrors Y (Y-down file frame)."""
    bad = {}
    for r, e in eb.elements.items():
        f = real_footprints(kb)[r]
        side_ok = f.layer == ("B.Cu" if e.mirror else "F.Cu")
        if abs(f.x - e.x) > config.TOL_MM or abs(f.y + e.y) > config.TOL_MM or not side_ok:
            bad[r] = (e.x, e.y, e.mirror, f.x, f.y, f.layer)
    assert bad == {}


def test_bare_holes_preserved(eb, kb):
    holes = {r: f for r, f in kb.footprints.items() if r.startswith(config.HOLE_REF_PREFIX)}
    got = sorted((round(f.x, 3), round(-f.y, 3)) for f in holes.values())
    want = sorted((round(x, 3), round(y, 3)) for x, y, _ in eb.holes)
    assert got == want


def test_pad_connectivity_matches_eagle_signals(eb, kb):
    """The whole point: every pad on every net, identical on both sides."""
    knets = {n: {(eagle_ref(r), p) for r, p in m} for n, m in kb.nets.items()}
    enets = {n: {(r, config.kicad_pad(r, p)) for r, p in m} for n, m in eb.signals.items()}
    assert set(knets) == set(enets), "net names differ"
    diffs = {n: sorted(knets[n] ^ enets[n]) for n in enets if knets[n] != enets[n]}
    assert diffs == {}


def test_pad_geometry(eb, kb):
    """Each pad: same position (to 1 um), same drill, same copper size."""
    kp = {(eagle_ref(p.ref), p.name): p for p in kb.pads if not p.ref.startswith(config.HOLE_REF_PREFIX)}
    ep = {(p.ref, p.name): p for p in eb.pads if config.kicad_pad(p.ref, p.name) == p.name}
    assert set(kp) == set(ep)
    bad = {}
    for key, e in ep.items():
        k = kp[key]
        if key[1] in config.MERGED_PADS.get(key[0], {}).values():
            continue  # plated slot pads replace Eagle's emulation; geometry differs by design
        pos_ok = abs(k.x - e.x) <= config.TOL_MM and abs(k.y + e.y) <= config.TOL_MM
        drill_ok = (k.drill or 0) == pytest.approx(e.drill or 0, abs=config.TOL_MM)
        size_ok = sorted(k.size) == pytest.approx(sorted(e.size), abs=config.TOL_MM)
        if not (pos_ok and drill_ok and size_ok):
            bad[key] = dict(eagle=(e.x, e.y, e.drill, e.size), kicad=(k.x, k.y, k.drill, k.size))
    assert bad == {}


def test_copper_zones_preserved(eb, kb):
    """Eagle signal polygons on copper must come through as zones on the same net."""
    layer = {1: "F.Cu", 16: "B.Cu"}
    want = sorted((net, layer[l]) for net, l, _ in eb.copper_polygons)
    got = sorted(z for z in kb.zones if z[1].endswith(".Cu"))
    assert got == want


def test_no_vias_or_tracks_lost(eb, kb):
    assert kb.vias == 0  # the Eagle board has none
    assert kb.edge_items == len(eb.outline)
