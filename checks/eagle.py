"""Parse Eagle 9 XML schematics and boards into plain, comparable structures.

Everything is reduced to the same vocabulary the KiCad side uses:
  * a *part* has a reference (Eagle "name"), a value, a package name
  * a *net* is a set of (reference, pad) pairs
  * a *pad* has an absolute (x, y) in mm, Eagle coordinates (Y up), a drill and a size
Parts without a package (frames, supply symbols) carry no pads and appear in no net.
"""
from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

Net = dict[str, set[tuple[str, str]]]  # net name -> {(ref, pad)}


@dataclass(frozen=True)
class Pad:
    ref: str
    name: str
    x: float
    y: float
    drill: float | None  # None for SMD
    size: tuple[float, float]  # (w, h) of the copper


@dataclass
class Part:
    ref: str
    value: str
    library: str
    package: str | None  # None when the device has no package (supply, frame)
    deviceset: str = ""
    device: str = ""


@dataclass
class Element:
    """A placed package on the board."""
    ref: str
    value: str
    library: str
    package: str
    x: float
    y: float
    rot: float  # degrees, counter-clockwise
    mirror: bool  # on the bottom side


@dataclass
class Board:
    elements: dict[str, Element]
    signals: Net
    pads: list[Pad]
    holes: list[tuple[float, float, float]]  # (x, y, drill)
    outline: list[tuple[float, float, float, float]]  # layer-20 wires (x1,y1,x2,y2)
    rules: dict[str, str]
    copper_polygons: list[tuple[str, int, int]]  # (signal, layer, vertex count)


@dataclass
class Schematic:
    parts: dict[str, Part]
    nets: Net  # expressed in package pads (via device <connect>), not symbol pins
    sheets: int = 1
    unresolved: list[str] = field(default_factory=list)  # pinrefs we couldn't map to a pad


def parse_rot(rot: str | None) -> tuple[float, bool]:
    """Eagle rot strings: 'R90', 'MR90' (mirrored), 'SR45' (spin). Returns (deg, mirrored)."""
    if not rot:
        return 0.0, False
    mirror = "M" in rot
    digits = "".join(ch for ch in rot if ch.isdigit() or ch == ".")
    return (float(digits) if digits else 0.0), mirror


def transform(px: float, py: float, el: Element) -> tuple[float, float]:
    """Package-local pad coordinates -> board coordinates (Eagle convention).

    Eagle applies mirror (about the Y axis) first, then rotation, then translation.
    """
    if el.mirror:
        px = -px
    a = math.radians(el.rot)
    x = px * math.cos(a) - py * math.sin(a)
    y = px * math.sin(a) + py * math.cos(a)
    return round(el.x + x, 4), round(el.y + y, 4)


def _packages(drawing: ET.Element) -> dict[tuple[str, str], ET.Element]:
    out = {}
    for lib in drawing.iter("library"):
        lname = lib.get("name", "")
        for pkg in lib.iter("package"):
            out[(lname, pkg.get("name", ""))] = pkg
    return out


def _mm(v: str) -> float:
    if v.endswith("mil"):
        return float(v[:-3]) * 0.0254
    if v.endswith("mm"):
        return float(v[:-2])
    return float(v)


def auto_diameter(drill: float, rules: dict[str, str]) -> float:
    """Eagle's pad diameter when the package leaves it at 'auto': drill plus two
    annular rings, each drill*rvPadTop clamped to [rlMinPadTop, rlMaxPadTop]."""
    ring = drill * float(rules.get("rvPadTop", "0.25"))
    ring = min(max(ring, _mm(rules.get("rlMinPadTop", "10mil"))), _mm(rules.get("rlMaxPadTop", "80mil")))
    return round(drill + 2 * ring, 4)


def _package_pads(pkg: ET.Element, rules: dict[str, str]) -> list[tuple[str, float, float, float | None, tuple[float, float]]]:
    pads = []
    for p in pkg.findall("pad"):
        drill = float(p.get("drill", "0"))
        dia = float(p.get("diameter", "0")) or auto_diameter(drill, rules)
        shape = p.get("shape", "round")
        size = (dia * 2, dia) if shape in ("long", "offset") else (dia, dia)
        pads.append((p.get("name", ""), float(p.get("x")), float(p.get("y")), drill, size))
    for s in pkg.findall("smd"):
        pads.append((s.get("name", ""), float(s.get("x")), float(s.get("y")), None,
                     (float(s.get("dx")), float(s.get("dy")))))
    return pads


def load_board(path: Path) -> Board:
    root = ET.parse(path).getroot()
    drawing = root.find("drawing")
    board = drawing.find("board")
    pkgs = _packages(drawing)
    rules = {p.get("name"): p.get("value") for p in board.find("designrules").findall("param")}

    elements: dict[str, Element] = {}
    pads: list[Pad] = []
    for e in board.find("elements").findall("element"):
        rot, mirror = parse_rot(e.get("rot"))
        el = Element(e.get("name"), e.get("value", ""), e.get("library"), e.get("package"),
                     float(e.get("x")), float(e.get("y")), rot, mirror)
        elements[el.ref] = el
        pkg = pkgs[(el.library, el.package)]
        for name, px, py, drill, size in _package_pads(pkg, rules):
            x, y = transform(px, py, el)
            pads.append(Pad(el.ref, name, x, y, drill, size))

    signals: Net = {}
    copper_polygons = []
    for s in board.find("signals").findall("signal"):
        name = s.get("name")
        signals[name] = {(c.get("element"), c.get("pad")) for c in s.findall("contactref")}
        for poly in s.findall("polygon"):
            copper_polygons.append((name, int(poly.get("layer")), len(poly.findall("vertex"))))

    plain = board.find("plain")
    holes = [(float(h.get("x")), float(h.get("y")), float(h.get("drill"))) for h in plain.findall("hole")]
    outline = [(float(w.get("x1")), float(w.get("y1")), float(w.get("x2")), float(w.get("y2")))
               for w in plain.findall("wire") if w.get("layer") == "20"]

    return Board(elements, signals, pads, holes, outline, rules, copper_polygons)


def load_schematic(path: Path) -> Schematic:
    root = ET.parse(path).getroot()
    drawing = root.find("drawing")
    sch = drawing.find("schematic")

    # (library, deviceset, device) -> {(gate, pin): pad}, and whether it has a package
    connects: dict[tuple[str, str, str], dict[tuple[str, str], list[str]]] = {}
    packages: dict[tuple[str, str, str], str | None] = {}
    for lib in sch.find("libraries").findall("library"):
        lname = lib.get("name")
        for ds in lib.find("devicesets").findall("deviceset"):
            for dev in ds.find("devices").findall("device"):
                key = (lname, ds.get("name"), dev.get("name", ""))
                packages[key] = dev.get("package")
                conns = dev.find("connects")
                connects[key] = {}
                if conns is not None:
                    for c in conns.findall("connect"):
                        # a pin may map to several pads: pad="PWR$1 PWR$2 PWR$3"
                        connects[key][(c.get("gate"), c.get("pin"))] = c.get("pad").split()

    parts: dict[str, Part] = {}
    for p in sch.find("parts").findall("part"):
        key = (p.get("library"), p.get("deviceset"), p.get("device", ""))
        parts[p.get("name")] = Part(p.get("name"), p.get("value", ""), key[0], packages.get(key),
                                    key[1], key[2])

    nets: Net = {}
    unresolved: list[str] = []
    sheets = sch.find("sheets").findall("sheet")
    for sheet in sheets:
        for net in sheet.find("nets").findall("net"):
            members = nets.setdefault(net.get("name"), set())
            for pr in net.iter("pinref"):
                part = parts[pr.get("part")]
                if part.package is None:
                    continue  # supply / frame symbols: net name is the connection
                key = (part.library, part.deviceset, part.device)
                pads = connects[key].get((pr.get("gate"), pr.get("pin")))
                if not pads:
                    unresolved.append(f"{part.ref}.{pr.get('gate')}.{pr.get('pin')}")
                    continue
                members.update((part.ref, pd) for pd in pads)
    return Schematic(parts, nets, len(sheets), unresolved)
