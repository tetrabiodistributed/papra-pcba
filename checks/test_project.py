"""What the KiCad GUI checks beyond ERC/DRC: annotation and library resolution.
kicad-cli's ERC skips both, so they are asserted here from the files themselves."""
from __future__ import annotations

import re

import pytest

from . import paths, sexpr


def _sch():
    return sexpr.load(paths.KICAD_SCH)


def test_every_symbol_is_annotated():
    """KiCad flags any reference that does not end in a digit or ends in '?'."""
    bad = []
    for s in sexpr.children(_sch(), "symbol"):
        ref = sexpr.prop(s, "Reference")
        if ref.endswith("?") or not ref[-1:].isdigit():
            bad.append(ref)
    assert bad == []


def _lib_table(path, kind):
    root = sexpr.load(path)
    libs = {}
    for lib in sexpr.children(root, "lib"):
        name = sexpr.child(lib, "name")[1]
        uri = sexpr.child(lib, "uri")[1].replace("${KIPRJMOD}", str(path.parent))
        libs[name] = paths.ROOT.joinpath(uri) if not uri.startswith("/") else type(path)(uri)
    return libs


def test_symbol_libraries_resolve():
    """Every placed symbol's lib_id names a library in sym-lib-table whose file holds it."""
    tables = _lib_table(paths.KICAD_SCH.parent / "sym-lib-table", "sym")
    missing = []
    for s in sexpr.children(_sch(), "symbol"):
        lib_id = sexpr.child(s, "lib_id")[1]
        nick, name = lib_id.split(":", 1)
        lib = tables.get(nick)
        if lib is None or not lib.exists():
            missing.append(f"{lib_id}: library {nick} not in sym-lib-table"); continue
        if f'(symbol "{name}"' not in lib.read_text():
            missing.append(f"{lib_id}: not in {lib.name}")
    assert missing == []


def test_footprint_libraries_resolve():
    """Every Footprint field and every board footprint names a library in fp-lib-table
    with that .kicad_mod present."""
    tables = _lib_table(paths.KICAD_PCB.parent / "fp-lib-table", "fp")
    ids = {sexpr.prop(s, "Footprint") for s in sexpr.children(_sch(), "symbol")} - {""}
    ids |= {fp[1] for fp in sexpr.children(sexpr.load(paths.KICAD_PCB), "footprint")}
    missing = []
    for fid in sorted(ids):
        nick, name = fid.split(":", 1)
        lib = tables.get(nick)
        if lib is None or not (lib / f"{name}.kicad_mod").exists():
            missing.append(fid)
    assert missing == []


def test_generated_board_and_footprints_are_deterministic():
    """A re-import of unchanged sources must not churn: UUIDs are derived (version 5) and
    the board's footprints are in reference order (checks/stable_ids.py)."""
    from .stable_ids import REF_RE, UUID_RE, BLOCK_RE
    files = [paths.KICAD_PCB, *sorted(paths.KICAD_PCB.parent.glob("*.pretty/*.kicad_mod"))]
    for f in files:
        for u in UUID_RE.findall(f.read_text()):
            assert u[14] == "5", f"{f.name}: random UUID {u}"
    refs = [REF_RE.search(m.group(0)).group(1) for m in BLOCK_RE.finditer(paths.KICAD_PCB.read_text()) if m.group(1) == "footprint"]
    assert refs == sorted(refs), "board footprints are not in reference order"
