"""Read KiCad 8+/9/10 boards and schematics into the same shapes as checks.eagle."""
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

from . import sexpr
from .eagle import Net, Pad
from .paths import BUILD, run_kicad_cli


@dataclass
class Footprint:
    ref: str
    value: str
    name: str  # "lib:footprint"
    x: float
    y: float
    rot: float
    layer: str


@dataclass
class KBoard:
    footprints: dict[str, Footprint]
    pads: list[Pad]
    nets: Net  # from pad net assignments
    net_names: set[str]  # declared nets (may include unused ones)
    zones: list[tuple[str, str]]  # (net_name, layer)
    edge_items: int
    vias: int
    segments: int


def _net_name(node: list) -> str:
    """(net 3 "GND") in KiCad <=9, (net "GND") in KiCad 10, (net 0) for unconnected."""
    net = sexpr.child(node, "net")
    if net is None:
        return ""
    if len(net) >= 3:
        return net[2]
    return net[1] if not net[1].isdigit() else ""


def _at(node: list) -> tuple[float, float, float]:
    a = sexpr.child(node, "at")
    x, y = float(a[1]), float(a[2])
    r = float(a[3]) if len(a) > 3 else 0.0
    return x, y, r


def load_board(path: Path) -> KBoard:
    root = sexpr.load(path)
    net_names = {n[2] for n in sexpr.children(root, "net") if len(n) >= 3}
    footprints: dict[str, Footprint] = {}
    pads: list[Pad] = []
    nets: Net = {}
    for fp in sexpr.children(root, "footprint"):
        fx, fy, frot = _at(fp)
        layer = sexpr.child(fp, "layer")[1]
        ref = sexpr.prop(fp, "Reference")
        footprints[ref] = Footprint(ref, sexpr.prop(fp, "Value"), fp[1], fx, fy, frot, layer)
        for pad in sexpr.children(fp, "pad"):
            name = pad[1]
            px, py, _ = _at(pad)
            # Pad (at x y) is footprint-local. The file frame is Y-down, and a positive
            # footprint angle is counter-clockwise on screen, so rotate by -angle here.
            # Back-side footprints are mirrored about the Y axis before rotation.
            if layer.startswith("B."):
                px = -px
            a = math.radians(-frot)
            x = fx + px * math.cos(a) - py * math.sin(a)
            y = fy + px * math.sin(a) + py * math.cos(a)
            size = sexpr.child(pad, "size")
            drill = sexpr.child(pad, "drill")
            d = None
            if drill is not None:
                nums = [float(t) for t in drill[1:] if isinstance(t, str) and t.replace(".", "", 1).isdigit()]
                d = nums[0] if nums else None
            pads.append(Pad(ref, name, round(x, 4), round(y, 4), d,
                            (float(size[1]), float(size[2]))))
            net_name = _net_name(pad).lstrip("/")  # KiCad local-label nets are "/NAME"
            if net_name and not net_name.startswith("unconnected-"):
                nets.setdefault(net_name, set()).add((ref, name))
    zones = [(sexpr.child(z, "net_name", [None, _net_name(z)])[1], sexpr.child(z, "layer", ["", ""])[1])
             for z in sexpr.children(root, "zone")]
    edge = sum(1 for tag in ("gr_line", "gr_arc", "gr_circle", "gr_rect", "gr_poly")
               for g in sexpr.children(root, tag) if sexpr.child(g, "layer", ["", ""])[1] == "Edge.Cuts")
    return KBoard(footprints, pads, nets, net_names, zones, edge,
                  sum(1 for _ in sexpr.children(root, "via")),
                  sum(1 for _ in sexpr.children(root, "segment")))


@dataclass
class KSymbol:
    ref: str
    value: str
    lib_id: str
    footprint: str


@dataclass
class KSchematic:
    symbols: dict[str, KSymbol]  # placed, non-power symbols
    power_symbols: int
    nets: Net  # from kicad-cli netlist export: (ref, pin number)


def _netlist(sch_path: Path) -> Net:
    """Connectivity as KiCad itself computes it, via the kicadsexpr netlist export."""
    BUILD.mkdir(parents=True, exist_ok=True)
    out = BUILD / "netlist.kicadsexpr"
    run_kicad_cli("sch", "export", "netlist", "--format", "kicadsexpr", "-o", str(out), str(sch_path))
    root = sexpr.load(out)
    nets: Net = {}
    for net in sexpr.children(sexpr.child(root, "nets"), "net"):
        name = sexpr.child(net, "name")[1]
        members = {(sexpr.child(n, "ref")[1], sexpr.child(n, "pin")[1]) for n in sexpr.children(net, "node")}
        nets[name] = members
    return nets


def load_schematic(path: Path) -> KSchematic:
    root = sexpr.load(path)
    symbols: dict[str, KSymbol] = {}
    power = 0
    for s in sexpr.children(root, "symbol"):
        ref = sexpr.prop(s, "Reference")
        lib_id = sexpr.child(s, "lib_id", ["", ""])[1]
        if ref.startswith("#"):
            power += 1
            continue
        symbols[ref] = KSymbol(ref, sexpr.prop(s, "Value"), lib_id, sexpr.prop(s, "Footprint"))
    return KSchematic(symbols, power, _netlist(path))
