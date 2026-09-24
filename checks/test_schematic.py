"""Eagle .sch vs converted .kicad_sch: same parts, same connectivity, and the KiCad
schematic agrees with the KiCad board (which test_board.py ties back to Eagle)."""
from __future__ import annotations

import json

import pytest

from . import config, eagle, kicad, paths


@pytest.fixture(scope="module")
def es() -> eagle.Schematic:
    return eagle.load_schematic(paths.EAGLE_SCH)


@pytest.fixture(scope="module")
def ks() -> kicad.KSchematic:
    if not paths.KICAD_SCH.exists():
        pytest.fail(f"{paths.KICAD_SCH} missing; run `make import-sch`")
    return kicad.load_schematic(paths.KICAD_SCH)


def real_nets(nets: eagle.Net) -> eagle.Net:
    """KiCad prefixes local-label nets with '/' and invents names for unconnected pins."""
    return {n.lstrip("/"): m for n, m in nets.items() if m and not n.startswith("unconnected-")}


def test_every_eagle_part_with_a_package_is_a_symbol(es, ks):
    want = {p.ref for p in es.parts.values() if p.package is not None}
    got = {config.REF_RENAMES.get(r, r) for r in ks.symbols}
    assert got == want


def test_values_and_footprints_match(es, ks):
    bad = {}
    for ref, sym in ks.symbols.items():
        p = es.parts[config.REF_RENAMES.get(ref, ref)]
        want_fp = f"papra-pcb-th:{p.package.replace('/', '_')}"
        want_val = p.value or p.deviceset
        if sym.value != want_val or sym.footprint != want_fp:
            bad[ref] = dict(value=(want_val, sym.value), footprint=(want_fp, sym.footprint))
    assert bad == {}


def test_schematic_connectivity_matches_eagle(es, ks):
    """KiCad's own netlister must produce Eagle's nets, pad for pad."""
    got = {n: {(config.REF_RENAMES.get(r, r), p) for r, p in m} for n, m in real_nets(ks.nets).items()}
    want = {n: {(r, config.kicad_pad(r, p)) for r, p in m} for n, m in es.nets.items()}
    assert set(got) == set(want), "net names differ"
    diffs = {n: sorted(got[n] ^ want[n]) for n in want if got[n] != want[n]}
    assert diffs == {}


def test_erc_has_no_errors():
    """Warnings are reported in build/erc.json; only errors fail (kistack export rule)."""
    out = paths.BUILD / "erc.json"
    paths.BUILD.mkdir(parents=True, exist_ok=True)
    paths.run_kicad_cli("sch", "erc", "-o", str(out), "--format", "json", "--severity-error",
                        "--severity-warning", str(paths.KICAD_SCH))
    report = json.loads(out.read_text())
    errors = [v for s in report["sheets"] for v in s["violations"] if v["severity"] == "error"]
    assert errors == [], [e["description"] + ": " + "; ".join(i["description"] for i in e["items"]) for e in errors]


def test_board_matches_schematic_and_passes_drc():
    """KiCad's schematic-parity DRC: every footprint, pad and net agrees with the schematic,
    and the board passes the design rules translated from Eagle (errors only)."""
    out = paths.BUILD / "drc.json"
    paths.BUILD.mkdir(parents=True, exist_ok=True)
    paths.run_kicad_cli("pcb", "drc", "-o", str(out), "--format", "json", "--units", "mm",
                        "--severity-error", "--refill-zones", "--schematic-parity", str(paths.KICAD_PCB))
    report = json.loads(out.read_text())
    problems = {k: [v["description"] + ": " + "; ".join(i["description"] for i in v["items"]) for v in report.get(k, [])]
                for k in ("violations", "unconnected_items", "schematic_parity")}
    assert {k: v for k, v in problems.items() if v} == {}
