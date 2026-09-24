"""Convert an Eagle 9 schematic to a KiCad 9/10 schematic plus a project symbol library.

Why this exists: kicad-cli can import Eagle boards but not schematics; that path is
GUI-only. This converter is deterministic, so `make import` reproduces the schematic
from the committed Eagle source and the checks in test_schematic.py prove it carries
the same connectivity as the Eagle schematic and the Eagle/KiCad boards.

Coordinate conventions:
  * Eagle sheets and symbols are Y-up, in mm.
  * KiCad library symbols are Y-up; KiCad sheets are Y-down. Sheet coordinates map as
    (x, y) -> (x, PAGE_H - y) so the drawing keeps Eagle's picture.
  * Rotation angles are counter-clockwise on screen in both tools, so they carry over.
    Eagle's mirror ("MR90") flips X before rotating; KiCad's (mirror y) is the same flip.
  * Eagle's gate x/y offsets are library-editor defaults only and are not applied on sheets.

Presentation rules (the picture is for people):
  * Pin names/numbers follow Eagle's per-symbol visibility; "PIN@1" style names lose the
    "@n" suffix, as Eagle displays them.
  * Text anchoring follows Eagle's bottom-left anchor under each rotation, so rotated
    reference/value fields land where Eagle drew them.
  * Nets Eagle named without a label get one small label on the longest wire of each
    segment, placed where it does not collide with symbols or other text.
  * BOM fields (Manufacturer, MPN, Digi-Key_PN, LCSC) are added as hidden symbol fields
    from the repository BOM so `kicad-cli sch export bom` can produce it.

Usage: python -m checks.sch_convert <eagle.sch> <out.kicad_sch> <symbol lib> <fp lib> [bom.csv]
"""
from __future__ import annotations

import csv
import math
import re
import sys
import urllib.parse
import uuid as uuidlib
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from .parts import DATASHEETS, PAD_MERGE, PIN_TYPES

PAGE = "A3"            # Eagle's ANSI-A frame content sits inside an A3 sheet with room for the title block
PAGE_W, PAGE_H = 420.0, 297.0
FRAME_H = 215.9        # Eagle FRAME_A_L height (Y-up origin at its bottom-left)
OFF_X, OFF_Y = 25.4, 25.4
PIN_LEN = {"point": 0.0, "short": 2.54, "middle": 5.08, "long": 7.62}
# Eagle's default direction is "io", which its libraries rarely set on purpose; it is
# mapped to passive so ERC does not flag every supply pin against the PWR_FLAGs.
PIN_TYPE = {"pas": "passive", "in": "input", "out": "output", "io": "passive",
            "oc": "open_collector", "pwr": "power_in", "sup": "power_in", "nc": "no_connect",
            "hiz": "tri_state"}
SUPPLY_NET_FLAGS = True  # add a PWR_FLAG on each supply net so ERC sees a driver
SKIP_LIBS = {"frames"}   # Eagle title-block frames; KiCad has its own drawing sheet
AUTO_LABEL_SIZE = 1.27
FIELD_SIZE_MAX = 1.27    # reference/value fields and net labels; Eagle used 1.778
CHAR_W = 0.9             # KiCad stroke font: average glyph advance as a fraction of size
NUDGE_MAX = 6.35         # how far (mm) a field may move from where Eagle put it
TITLE = {"title": "PAPRa M12 Controller PCB, Through-Hole (P-TET-000166)", "rev": "1.0",
         "company": "Tetra Bio Distributed", "comment": "Converted from Papra TH_eagle.sch; see checks/sch_convert.py"}

MANUFACTURERS = {  # Digi-Key URL slug -> display name
    "te-connectivity-amp-connectors": "TE Connectivity", "tdk-corporation": "TDK", "kemet": "KEMET",
    "kingbright": "Kingbright", "onsemi": "onsemi", "comchip-technology": "Comchip Technology",
    "würth-elektronik": "Würth Elektronik", "cui-devices": "CUI Devices", "tt-electronics-bi": "TT Electronics/BI",
    "goford-semiconductor": "Goford Semiconductor", "infineon-technologies": "Infineon Technologies",
    "texas-instruments": "Texas Instruments", "adafruit-industries-llc": "Adafruit Industries",
    "yageo": "Yageo", "sparkfun-electronics": "SparkFun Electronics",
}
BOM_OVERRIDES = {  # designator -> (Manufacturer, MPN) where the BOM's link cannot be parsed
    "SG1": ("CUI Devices", "CMI-1210-92T"),
}


def stable_uuid(*parts: str) -> str:
    """Deterministic UUIDs so re-running the converter yields a byte-identical file."""
    return str(uuidlib.uuid5(uuidlib.NAMESPACE_URL, "papra-pcba/" + "/".join(parts)))


def parse_rot(rot: str | None) -> tuple[float, bool]:
    if not rot:
        return 0.0, False
    digits = "".join(ch for ch in rot if ch.isdigit() or ch == ".")
    return (float(digits) if digits else 0.0), rot.startswith("M")


def fnum(v: float) -> str:
    s = f"{v:.4f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def q(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def effects(size: float, rot: float = 0, mirror: bool = False, hide: bool = False) -> tuple[float, str]:
    """KiCad text angle + effects reproducing an Eagle bottom-left-anchored text at `rot`."""
    r = int(rot) % 360
    if mirror:
        r = (180 - r) % 360
    angle, justify = {0: (0, "left bottom"), 90: (90, "left bottom"),
                      180: (0, "right top"), 270: (90, "right top")}[r]
    return angle, f"(effects (font (size {fnum(size)} {fnum(size)})) (justify {justify}){' (hide yes)' if hide else ''})"


def label_angle(rot: float, mirror: bool) -> int:
    """KiCad labels take 0/90/180/270 and stay readable; Eagle's mirror flips the side."""
    r = int(rot) % 360
    return (180 - r) % 360 if mirror else r


def text_box(x: float, y: float, text: str, size: float, angle: int, justify: str) -> tuple[float, float, float, float]:
    """Approximate sheet bounding box of a text (KiCad stroke font), y-down."""
    w = CHAR_W * size * max(1, len(text)) + 0.5
    h = size + 0.5
    hj, vj = justify.split()
    if angle in (0, 180):
        x0 = x - w if hj == "right" else x
        y0 = y if vj == "top" else y - h
        return x0, y0, x0 + w, y0 + h
    y0 = y - w if hj == "left" else y      # angle 90 reads upward (towards -y)
    x0 = x if vj == "top" else x - h
    return x0, y0, x0 + h, y0 + w


def overlaps(a, b, margin: float = 0.3) -> bool:
    return not (a[2] + margin <= b[0] or b[2] + margin <= a[0] or a[3] + margin <= b[1] or b[3] + margin <= a[1])


# ---------------------------------------------------------------- Eagle model
@dataclass
class EPin:
    name: str
    x: float
    y: float
    length: float
    rot: float
    direction: str
    visible: str
    dot: bool


@dataclass
class ESymbol:
    name: str
    graphics: list[str] = field(default_factory=list)  # already-rendered KiCad s-exprs (lib coords)
    pins: list[EPin] = field(default_factory=list)
    name_text: tuple[float, float, float, float] | None = None   # x y rot size of >NAME
    value_text: tuple[float, float, float, float] | None = None
    extent: list[float] = field(default_factory=lambda: [0, 0, 0, 0])  # minx miny maxx maxy


@dataclass
class EDeviceset:
    lib: str
    name: str
    prefix: str
    gates: list[tuple[str, str, float, float]]  # (gate, symbol, x, y)
    devices: dict[str, tuple[str | None, dict[tuple[str, str], list[str]]]]  # dev -> (package, connects)


@dataclass
class EPart:
    name: str
    lib: str
    deviceset: str
    device: str
    value: str


@dataclass
class EInstance:
    part: str
    gate: str
    x: float
    y: float
    rot: float
    mirror: bool
    smashed: bool
    attrs: dict[str, tuple[float, float, float, float, bool]]  # NAME/VALUE -> x y rot size mirror


def arc_mid(x1, y1, x2, y2, curve_deg):
    """Midpoint of an Eagle curved wire (curve = signed sweep angle, CCW positive)."""
    dx, dy = x2 - x1, y2 - y1
    c = math.hypot(dx, dy)
    if c == 0:
        return x1, y1
    theta = math.radians(curve_deg)
    r = c / (2 * math.sin(abs(theta) / 2))
    s = r * (1 - math.cos(abs(theta) / 2))  # sagitta
    mx, my = (x1 + x2) / 2, (y1 + y2) / 2
    nx, ny = dy / c, -dx / c  # right-hand normal of p1->p2
    sign = 1 if curve_deg > 0 else -1
    return mx + sign * nx * s, my + sign * ny * s


def render_graphic(el: ET.Element, extent: list[float]) -> str | None:
    t = el.tag
    w = float(el.get("width", "0.254"))
    stroke = f"(stroke (width {fnum(w)}) (type default))"

    def grow(*pts):
        for x, y in pts:
            extent[0], extent[1] = min(extent[0], x), min(extent[1], y)
            extent[2], extent[3] = max(extent[2], x), max(extent[3], y)

    if t == "wire":
        x1, y1, x2, y2 = (float(el.get(k)) for k in ("x1", "y1", "x2", "y2"))
        grow((x1, y1), (x2, y2))
        if el.get("curve"):
            mx, my = arc_mid(x1, y1, x2, y2, float(el.get("curve")))
            return f"(arc (start {fnum(x1)} {fnum(y1)}) (mid {fnum(mx)} {fnum(my)}) (end {fnum(x2)} {fnum(y2)}) {stroke} (fill (type none)))"
        return f"(polyline (pts (xy {fnum(x1)} {fnum(y1)}) (xy {fnum(x2)} {fnum(y2)})) {stroke} (fill (type none)))"
    if t == "rectangle":
        x1, y1, x2, y2 = (float(el.get(k)) for k in ("x1", "y1", "x2", "y2"))
        grow((x1, y1), (x2, y2))
        return f"(rectangle (start {fnum(x1)} {fnum(y1)}) (end {fnum(x2)} {fnum(y2)}) (stroke (width 0) (type default)) (fill (type outline)))"
    if t == "circle":
        x, y, r = float(el.get("x")), float(el.get("y")), float(el.get("radius"))
        grow((x - r, y - r), (x + r, y + r))
        return f"(circle (center {fnum(x)} {fnum(y)}) (radius {fnum(r)}) {stroke} (fill (type none)))"
    if t == "polygon":
        vs = [(float(v.get("x")), float(v.get("y"))) for v in el.findall("vertex")]
        grow(*vs)
        pts = " ".join(f"(xy {fnum(x)} {fnum(y)})" for x, y in vs + vs[:1])
        return f"(polyline (pts {pts}) (stroke (width 0) (type default)) (fill (type outline)))"
    if t == "text":
        txt = el.text or ""
        if txt.startswith(">"):
            return None  # Eagle attribute placeholders (>NAME, >VALUE, >TP_SIGNAL_NAME ...)
        x, y, size = float(el.get("x")), float(el.get("y")), float(el.get("size", "1.778"))
        rot, mirror = parse_rot(el.get("rot"))
        angle, eff = effects(size, rot, mirror)
        return f"(text {q(txt)} (at {fnum(x)} {fnum(y)} {fnum(angle)}) {eff})"
    return None


def load_eagle(path: Path):
    root = ET.parse(path).getroot()
    sch = root.find("drawing").find("schematic")
    symbols: dict[tuple[str, str], ESymbol] = {}
    devicesets: dict[tuple[str, str], EDeviceset] = {}
    for lib in sch.find("libraries").findall("library"):
        lname = lib.get("name")
        for s in lib.find("symbols").findall("symbol") if lib.find("symbols") is not None else []:
            sym = ESymbol(s.get("name"))
            for el in s:
                if el.tag == "pin":
                    rot, _ = parse_rot(el.get("rot"))
                    p = EPin(el.get("name"), float(el.get("x")), float(el.get("y")),
                             PIN_LEN[el.get("length", "long")], rot, el.get("direction", "pas"),
                             el.get("visible", "both"), el.get("function") == "dot")
                    sym.pins.append(p)
                    ex = p.x + p.length * math.cos(math.radians(p.rot))
                    ey = p.y + p.length * math.sin(math.radians(p.rot))
                    sym.extent[0], sym.extent[1] = min(sym.extent[0], p.x, ex), min(sym.extent[1], p.y, ey)
                    sym.extent[2], sym.extent[3] = max(sym.extent[2], p.x, ex), max(sym.extent[3], p.y, ey)
                elif el.tag == "text" and (el.text or "").upper() in (">NAME", ">VALUE", ">PART"):
                    rot, _ = parse_rot(el.get("rot"))
                    tup = (float(el.get("x")), float(el.get("y")), rot, float(el.get("size", "1.778")))
                    if (el.text or "").upper() == ">VALUE":
                        sym.value_text = tup
                    else:
                        sym.name_text = tup
                else:
                    g = render_graphic(el, sym.extent)
                    if g:
                        sym.graphics.append(g)
            symbols[(lname, sym.name)] = sym
        for ds in lib.find("devicesets").findall("deviceset"):
            gates = [(g.get("name"), g.get("symbol"), float(g.get("x", "0")), float(g.get("y", "0")))
                     for g in ds.find("gates").findall("gate")]
            devices = {}
            for dev in ds.find("devices").findall("device"):
                conns: dict[tuple[str, str], list[str]] = {}
                if dev.find("connects") is not None:
                    merge = PAD_MERGE.get(ds.get("name"), {})
                    for c in dev.find("connects").findall("connect"):
                        pads = list(dict.fromkeys(merge.get(pd, pd) for pd in c.get("pad").split()))
                        conns[(c.get("gate"), c.get("pin"))] = pads
                devices[dev.get("name", "")] = (dev.get("package"), conns)
            devicesets[(lname, ds.get("name"))] = EDeviceset(lname, ds.get("name"), ds.get("prefix", "U"), gates, devices)

    parts = {p.get("name"): EPart(p.get("name"), p.get("library"), p.get("deviceset"), p.get("device", ""),
                                  p.get("value", "")) for p in sch.find("parts").findall("part")}
    sheet = sch.find("sheets").findall("sheet")[0]
    instances = []
    for i in sheet.find("instances").findall("instance"):
        rot, mirror = parse_rot(i.get("rot"))
        attrs = {}
        for a in i.findall("attribute"):
            arot, amirror = parse_rot(a.get("rot"))
            attrs[a.get("name")] = (float(a.get("x")), float(a.get("y")), arot, float(a.get("size", "1.778")), amirror)
        instances.append(EInstance(i.get("part"), i.get("gate"), float(i.get("x")), float(i.get("y")), rot, mirror,
                                   i.get("smashed") == "yes", attrs))
    nets = sheet.find("nets").findall("net")
    plain = sheet.find("plain")
    return symbols, devicesets, parts, instances, nets, plain


def load_bom(path: Path | None) -> dict[str, dict[str, str]]:
    """Designator -> {Manufacturer, MPN, Digi-Key_PN, LCSC} from the repository BOM CSV.
    Manufacturer and MPN come from the Digi-Key product URL, which encodes both."""
    if not path or not path.exists():
        return {}
    fields: dict[str, dict[str, str]] = {}
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            desigs = row.get("Designator", "").split()
            link = row.get("Digikey Link", "")
            m = re.search(r"/products/detail/([^/]+)/([^/]+)/\d+", link)
            manu, mpn = "", ""
            if m:
                slug = urllib.parse.unquote(m.group(1)).lower()
                manu = MANUFACTURERS.get(slug, slug.replace("-", " ").title())
                mpn = urllib.parse.unquote(m.group(2))
            for d in desigs:
                if d in BOM_OVERRIDES:
                    manu, mpn = BOM_OVERRIDES[d]
                if not re.fullmatch(r"[A-Z+\-]+[0-9+\-]*", d):
                    continue  # "See Below" and similar notes
                fields[d] = {"Manufacturer": manu, "MPN": mpn, "Digi-Key_PN": row.get("DigiKey Part Number", ""),
                             "LCSC": "", "_footprint": row.get("Footprint", ""), "_link": link}
    # LCSC numbers live in a sibling file written by checks/lcsc_lookup.py (the BOM itself
    # is never edited by tooling).
    lcsc = path.with_name("lcsc-parts.csv")
    if lcsc.exists():
        with lcsc.open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row.get("Designator") in fields and row.get("LCSC"):
                    fields[row["Designator"]]["LCSC"] = row["LCSC"]
    return fields


# ---------------------------------------------------------------- KiCad output
def kicad_symbol_name(ds: EDeviceset, device: str) -> str:
    base = ds.name if not device else f"{ds.name}_{device}"
    return re.sub(r"[^A-Za-z0-9_.+-]", "_", base)


def fp_name(package: str | None) -> str:
    """kicad-cli's Eagle importer names footprints after the package with '/' -> '_'."""
    return (package or "").replace("/", "_")


def kicad_ref(name: str) -> str:
    """KiCad treats a reference without a trailing digit as unannotated; kicad-cli's
    Eagle importer appends "0" to those, and so does this converter."""
    return name if name[-1:].isdigit() else name + "0"


def display_pin_name(name: str) -> str:
    return re.sub(r"@\d+$", "", name)  # Eagle shows PIN@1 as PIN


def is_supply(ds: EDeviceset, symbols) -> bool:
    if len(ds.gates) != 1 or any(pkg for pkg, _ in ds.devices.values()):
        return False
    sym = symbols[(ds.lib, ds.gates[0][1])]
    return len(sym.pins) == 1 and sym.pins[0].direction == "sup"


def render_lib_symbol(name: str, ds: EDeviceset, device: str, symbols, fp_lib: str, power: bool) -> str:
    package, conns = ds.devices[device]
    all_pins = [p for g in ds.gates for p in symbols[(ds.lib, g[1])].pins]
    hide_names = power or all(p.visible in ("off", "pad") for p in all_pins)
    hide_numbers = power or all(p.visible in ("off", "pin") for p in all_pins)
    units: list[str] = []
    for u, (gate, symname, _gx, _gy) in enumerate(ds.gates, start=1):
        sym = symbols[(ds.lib, symname)]
        body = [f"    (symbol \"{name}_{u}_1\""]
        for g in sym.graphics:
            body.append("      " + g)
        override = PIN_TYPES.get(ds.name, {})
        for p in sym.pins:
            pads = conns.get((gate, p.name), [p.name])
            ptype = "power_in" if power else override.get(p.name, override.get("*", PIN_TYPE.get(p.direction, "passive")))
            style = "inverted" if p.dot else "line"
            for k, pad in enumerate(pads):
                # extra pads for one pin become their own pins, 2.54 mm apart
                dx, dy = pad_offset(p, k)
                body.append(
                    f"      (pin {ptype} {style} (at {fnum(p.x + dx)} {fnum(p.y + dy)} {fnum(p.rot)}) (length {fnum(p.length)})"
                    + f" (name {q(display_pin_name(p.name))} (effects (font (size 1.27 1.27))))"
                    + f" (number {q(pad)} (effects (font (size 1.27 1.27)))))")
        body.append("    )")
        units.append("\n".join(body))
    sym0 = symbols[(ds.lib, ds.gates[0][1])]
    nx, ny, nrot, nsize = sym0.name_text or (0, 2.54, 0, 1.27)
    vx, vy, vrot, vsize = sym0.value_text or (0, -2.54, 0, 1.27)
    na, neff = effects(nsize, nrot, hide=power)
    va, veff = effects(vsize, vrot)
    props = [
        f"    (property \"Reference\" {q('#PWR' if power else ds.prefix)} (at {fnum(nx)} {fnum(ny)} {fnum(na)}) {neff})",
        f"    (property \"Value\" {q(ds.name)} (at {fnum(vx)} {fnum(vy)} {fnum(va)}) {veff})",
        f"    (property \"Footprint\" {q(f'{fp_lib}:{fp_name(package)}' if package else '')} (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))",
        "    (property \"Datasheet\" \"\" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))",
    ]
    head = (f"  (symbol {q(name)}" + (" (power)" if power else "")
            + (" (pin_numbers (hide yes))" if hide_numbers else "")
            + f" (pin_names (offset 1.016){' (hide yes)' if hide_names else ''})"
            + f" (exclude_from_sim no) (in_bom {'no' if power else 'yes'}) (on_board {'no' if power else 'yes'})")
    return "\n".join([head, *props, *units, "  )"])


PWR_FLAG = """  (symbol "PWR_FLAG" (power) (pin_numbers (hide yes)) (pin_names (offset 0) (hide yes)) (exclude_from_sim no) (in_bom no) (on_board no)
    (property "Reference" "#FLG" (at 0 1.905 0) (effects (font (size 1.27 1.27)) (hide yes)))
    (property "Value" "PWR_FLAG" (at 0 3.81 0) (effects (font (size 1.27 1.27)) (hide yes)))
    (property "Footprint" "" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))
    (property "Datasheet" "" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))
    (symbol "PWR_FLAG_0_1"
      (polyline (pts (xy 0 0) (xy 0 1.27) (xy -1.016 1.905) (xy 0 2.54) (xy 1.016 1.905) (xy 0 1.27)) (stroke (width 0) (type default)) (fill (type none)))
    )
    (symbol "PWR_FLAG_1_1"
      (pin power_out line (at 0 0 90) (length 0) (name "pwr" (effects (font (size 1.27 1.27)))) (number "1" (effects (font (size 1.27 1.27)))))
    )
  )"""


def pad_offset(pin: EPin, k: int) -> tuple[float, float]:
    """Symbol-local offset of the k-th pad of a multi-pad pin: 2.54 mm steps sideways."""
    a = math.radians(pin.rot + 90)
    return round(k * 2.54 * math.cos(a), 4), round(k * 2.54 * math.sin(a), 4)


def eagle_to_sheet(x: float, y: float) -> tuple[float, float]:
    return OFF_X + x, OFF_Y + FRAME_H - y


def instance_point(inst: EInstance, px: float, py: float) -> tuple[float, float]:
    """Sheet position of a symbol-local point under an Eagle instance transform."""
    if inst.mirror:
        px = -px
    a = math.radians(inst.rot)
    rx = px * math.cos(a) - py * math.sin(a)
    ry = px * math.sin(a) + py * math.cos(a)
    return eagle_to_sheet(inst.x + rx, inst.y + ry)


def instance_box(inst: EInstance, sym: ESymbol) -> tuple[float, float, float, float]:
    x0, y0, x1, y1 = sym.extent
    pts = [instance_point(inst, x, y) for x, y in ((x0, y0), (x1, y0), (x0, y1), (x1, y1))]
    return min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts)


def on_segment(p, a, b, tol: float = 0.001) -> bool:
    (px, py), (ax, ay), (bx, by) = p, a, b
    cross = (bx - ax) * (py - ay) - (by - ay) * (px - ax)
    if abs(cross) > tol * max(1.0, math.hypot(bx - ax, by - ay)):
        return False
    return min(ax, bx) - tol <= px <= max(ax, bx) + tol and min(ay, by) - tol <= py <= max(ay, by) + tol


def place_auto_label(name: str, wires: list[tuple[tuple[float, float], tuple[float, float]]], occupied: list,
                     size: float = AUTO_LABEL_SIZE) -> tuple[float, float, int, str, float]:
    """Pick a spot for a net label along the segment's wires that collides with nothing.
    Returns (x, y, angle, justify, size). Tries a smaller font before giving up and
    falling back to the longest wire's midpoint."""
    w = CHAR_W * size * len(name) + 0.5
    cands = []
    for (x1, y1), (x2, y2) in sorted(wires, key=lambda s: -math.hypot(s[1][0] - s[0][0], s[1][1] - s[0][1])):
        length = math.hypot(x2 - x1, y2 - y1)
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        # The anchor must stay on the wire for KiCad to connect the label to it.
        if abs(y1 - y2) < 1e-6:  # horizontal: text above the wire, centred
            lo, hi = min(x1, x2), max(x1, x2)
            for dx in (0, -0.25 * length, 0.25 * length):
                cands.append((min(max(mx - w / 2 + dx, lo), hi), my, 0, "left bottom"))
            for dx in (0, -0.25 * length, 0.25 * length):  # text rising from the wire
                cands.append((min(max(mx + dx, lo), hi), my, 90, "left bottom"))
        elif abs(x1 - x2) < 1e-6:  # vertical: text left of the wire, reading upward
            lo, hi = min(y1, y2), max(y1, y2)
            for dy in (0, 0.25 * length, -0.25 * length):
                cands.append((mx, min(max(my + w / 2 + dy, lo), hi), 90, "left bottom"))
        else:
            cands.append((mx, my, 0, "left bottom"))
    for x, y, angle, justify in cands:
        box = text_box(x, y, name, size, angle, justify)
        if not any(overlaps(box, o) for o in occupied):
            occupied.append(box)
            return x, y, angle, justify, size
    if size > 1.0:
        return place_auto_label(name, wires, occupied, size=1.0)
    x, y, angle, justify = cands[0]
    occupied.append(text_box(x, y, name, size, angle, justify))
    return x, y, angle, justify, size


def convert(eagle: Path, out: Path, sym_lib: str, fp_lib: str, bom: Path | None = None) -> dict:
    symbols, devicesets, parts, instances, nets, plain = load_eagle(eagle)
    bom_fields = load_bom(bom)
    project = out.stem
    root_uuid = stable_uuid("sch", project)
    occupied: list[tuple[float, float, float, float]] = []
    stats: dict = {"bom_fields": 0, "bom_missing": []}

    # ---- library symbols, one per (deviceset, device) actually used
    lib_defs: dict[str, str] = {}
    part_symbol: dict[str, tuple[str, bool]] = {}  # part -> (symbol name, is_power)
    for p in parts.values():
        if p.lib in SKIP_LIBS:
            continue
        ds = devicesets[(p.lib, p.deviceset)]
        power = is_supply(ds, symbols)
        name = kicad_symbol_name(ds, p.device)
        if name not in lib_defs:
            lib_defs[name] = render_lib_symbol(name, ds, p.device, symbols, fp_lib, power)
        part_symbol[p.name] = (name, power)
    lib_defs["PWR_FLAG"] = PWR_FLAG

    # ---- placed symbols
    body: list[str] = []
    used_pins: set[tuple[str, str, str]] = set()  # (part, gate, pin) that appear in nets
    for net in nets:
        for pr in net.iter("pinref"):
            used_pins.add((pr.get("part"), pr.get("gate"), pr.get("pin")))

    # Every symbol's footprint on the sheet is known before any text is placed.
    for inst in instances:
        p = parts[inst.part]
        if p.lib in SKIP_LIBS:
            continue
        ds = devicesets[(p.lib, p.deviceset)]
        unit = [g[0] for g in ds.gates].index(inst.gate) + 1
        occupied.append(instance_box(inst, symbols[(ds.lib, ds.gates[unit - 1][1])]))
    symbol_boxes = list(occupied)

    def nudge(x: float, y: float, text: str, size: float, angle: int, justify: str, own_box) -> tuple[float, float, int, str]:
        """Find the closest spot (within NUDGE_MAX) where a text sits on nothing else.
        Its own symbol counts unless the text is fully inside it (IC-style values)."""
        others = [o for o in occupied if o is not own_box]

        def inside(b, o):
            return o[0] <= b[0] and b[2] <= o[2] and o[1] <= b[1] and b[3] <= o[3]

        def clear(b):
            if any(overlaps(b, o, 0.4) for o in others):
                return False
            return inside(b, own_box) or not overlaps(b, own_box, 0.0)

        if clear(text_box(x, y, text, size, angle, justify)):
            return x, y, angle, justify
        best = None
        step = 0.635
        n = int(NUDGE_MAX / step)
        for alt, (a2, j2) in enumerate(((angle, justify), (90 if angle == 0 else 0, "left bottom"))):
            for i in range(-n, n + 1):
                for j in range(-n, n + 1):
                    dx, dy = i * step, j * step
                    cost = math.hypot(dx, dy) + (2.0 if alt else 0.0)
                    if best is not None and cost >= best[0]:
                        continue
                    if clear(text_box(x + dx, y + dy, text, size, a2, j2)):
                        best = (cost, x + dx, y + dy, a2, j2)
        if best:
            return best[1], best[2], best[3], best[4]
        return x, y, angle, justify

    # ---- the drawing-sheet frame (10 mm margins with the row/column strip) is off limits
    for box in ((0, 0, PAGE_W, 12), (0, PAGE_H - 12, PAGE_W, PAGE_H), (0, 0, 12, PAGE_H), (PAGE_W - 12, 0, PAGE_W, PAGE_H)):
        occupied.append(box)

    # ---- free text on the sheet occupies space too
    plain_items: list[str] = []
    if plain is not None:
        for el in plain:
            if el.tag == "text":
                x, y = eagle_to_sheet(float(el.get("x")), float(el.get("y")))
                rot, mirror = parse_rot(el.get("rot"))
                size = float(el.get("size", "1.778"))
                angle, eff = effects(size, rot, mirror)
                occupied.append(text_box(x, y, el.text or "", size, angle, eff.split("(justify ")[1].split(")")[0]))
                plain_items.append(f"  (text {q(el.text or '')} (at {fnum(x)} {fnum(y)} {fnum(angle)}) {eff} (uuid {q(stable_uuid('text', el.get('x'), el.get('y'), el.text or ''))}))")
            elif el.tag == "wire":
                x1, y1 = eagle_to_sheet(float(el.get("x1")), float(el.get("y1")))
                x2, y2 = eagle_to_sheet(float(el.get("x2")), float(el.get("y2")))
                # section dividers: thin obstacles so text does not sit across them
                occupied.append((min(x1, x2) - 0.3, min(y1, y2) - 0.3, max(x1, x2) + 0.3, max(y1, y2) + 0.3))
                plain_items.append(f"  (polyline (pts (xy {fnum(x1)} {fnum(y1)}) (xy {fnum(x2)} {fnum(y2)})) (stroke (width 0) (type default)) (uuid {q(stable_uuid('gline', el.get('x1'), el.get('y1'), el.get('x2'), el.get('y2')))}))")

    # ---- nets: wires, junctions, labels
    stats.update({"wires": 0, "junctions": 0, "labels": 0, "added_labels": 0})
    label_items: list[str] = []
    auto_segments: list[tuple[str, int, list]] = []
    for net in nets:
        name = net.get("name")
        for si, seg in enumerate(net.findall("segment")):
            wires = [(eagle_to_sheet(float(w.get("x1")), float(w.get("y1"))), eagle_to_sheet(float(w.get("x2")), float(w.get("y2"))))
                     for w in seg.findall("wire")]
            # Eagle leaves sub-0.2 mm stubs at some junctions; ERC reports them as dangling.
            wires = [w for w in wires if math.hypot(w[1][0] - w[0][0], w[1][1] - w[0][1]) >= 0.2] or wires
            # ...and sometimes draws a wire on top of a longer collinear one: drop the contained one.
            def contained(a, b):
                (ax1, ay1), (ax2, ay2) = a; (bx1, by1), (bx2, by2) = b
                if abs(ay1 - ay2) < 1e-6 and abs(by1 - by2) < 1e-6 and abs(ay1 - by1) < 1e-6:
                    return min(bx1, bx2) - 1e-6 <= min(ax1, ax2) and max(ax1, ax2) <= max(bx1, bx2) + 1e-6
                if abs(ax1 - ax2) < 1e-6 and abs(bx1 - bx2) < 1e-6 and abs(ax1 - bx1) < 1e-6:
                    return min(by1, by2) - 1e-6 <= min(ay1, ay2) and max(ay1, ay2) <= max(by1, by2) + 1e-6
                return False
            wires = [w for i, w in enumerate(wires) if not any(j != i and w != o and contained(w, o) for j, o in enumerate(wires))]
            for (x1, y1), (x2, y2) in wires:
                body.append(f"  (wire (pts (xy {fnum(x1)} {fnum(y1)}) (xy {fnum(x2)} {fnum(y2)})) (stroke (width 0) (type default)) (uuid {q(stable_uuid('wire', name, str(si), fnum(x1), fnum(y1), fnum(x2), fnum(y2)))}))")
                stats["wires"] += 1
            for j in seg.findall("junction"):
                x, y = eagle_to_sheet(float(j.get("x")), float(j.get("y")))
                body.append(f"  (junction (at {fnum(x)} {fnum(y)}) (diameter 0) (color 0 0 0 0) (uuid {q(stable_uuid('junc', name, j.get('x'), j.get('y')))}))")
                stats["junctions"] += 1
            has_label = False
            for li, lab in enumerate(seg.findall("label")):
                x, y = eagle_to_sheet(float(lab.get("x")), float(lab.get("y")))
                rot, mirror = parse_rot(lab.get("rot"))
                size = min(float(lab.get("size", "1.778")), FIELD_SIZE_MAX)
                # Eagle attaches a label to its segment wherever it sits; KiCad needs the
                # label anchor on the wire. Snap to the nearest wire endpoint if it is off.
                if wires and not any(on_segment((x, y), a, b) for a, b in wires):
                    x, y = min((pt for a, b in wires for pt in (a, b)), key=lambda pt: math.hypot(pt[0] - x, pt[1] - y))
                angle = label_angle(rot, mirror)
                justify = "left bottom" if angle in (0, 90) else "right bottom"
                bjust = justify if angle in (0, 90) else "right top"
                # Slide along the wire the label sits on until it collides with nothing.
                host = next((w for w in wires if on_segment((x, y), *w)), None)
                if host and any(overlaps(text_box(x, y, name, size, angle % 180, bjust), o, 0.15) for o in occupied):
                    (ax, ay), (bx, by) = host
                    far = (bx, by) if math.hypot(bx - x, by - y) > math.hypot(ax - x, ay - y) else (ax, ay)
                    n = max(1, int(math.hypot(far[0] - x, far[1] - y) / 1.27))
                    for k in range(1, n + 1):
                        cx, cy = x + (far[0] - x) * k / n, y + (far[1] - y) * k / n
                        if not any(overlaps(text_box(cx, cy, name, size, angle % 180, bjust), o, 0.15) for o in occupied):
                            x, y = cx, cy
                            break
                occupied.append(text_box(x, y, name, size, angle % 180, bjust))
                label_items.append(f"  (label {q(name)} (at {fnum(x)} {fnum(y)} {angle}) (effects (font (size {fnum(size)} {fnum(size)})) (justify {justify})) (uuid {q(stable_uuid('label', name, str(si), str(li)))}))")
                stats["labels"] += 1
                has_label = True
            if not has_label and wires:
                # Eagle nets are named even without a label; KiCad only names a net from a
                # label, and the board expects Eagle's names, so add one per segment.
                auto_segments.append((name, si, wires))
    for name, si, wires in auto_segments:
        x, y, angle, justify, lsize = place_auto_label(name, wires, occupied)
        label_items.append(f"  (label {q(name)} (at {fnum(x)} {fnum(y)} {angle}) (effects (font (size {fnum(lsize)} {fnum(lsize)})) (justify {justify})) (uuid {q(stable_uuid('autolabel', name, str(si)))}))")
        stats["added_labels"] += 1
    # Place field texts in a deliberate order so short, anchored texts (power-symbol net
    # names, reference designators) claim their spot before long value strings move.
    placed: dict[tuple[str, str, str], tuple[float, float, int, str]] = {}
    pending = []
    for inst in instances:
        p = parts[inst.part]
        if p.lib in SKIP_LIBS:
            continue
        ds = devicesets[(p.lib, p.deviceset)]
        name, power = part_symbol[p.name]
        unit = [g[0] for g in ds.gates].index(inst.gate) + 1
        sym = symbols[(ds.lib, ds.gates[unit - 1][1])]
        own_box = instance_box(inst, sym)
        for key, prio in (("NAME", 1), ("VALUE", 0 if power else 2)):
            if power and key == "NAME":
                continue
            if key in inst.attrs:
                ax, ay, arot, asize, amirror = inst.attrs[key]
                x, y = eagle_to_sheet(ax, ay)
            elif inst.smashed:
                continue  # hidden in Eagle
            else:
                lx, ly, arot, asize = (sym.name_text if key == "NAME" else sym.value_text) or (0, 2.54 if key == "NAME" else -2.54, 0, 1.27)
                amirror = False
                x, y = instance_point(inst, lx, ly)
            asize = min(asize, FIELD_SIZE_MAX)
            val = kicad_ref(p.name) if key == "NAME" else (sym.pins[0].name if power else (p.value or ds.name))
            angle, eff = effects(asize, arot, amirror)
            justify = eff.split("(justify ")[1].split(")")[0]
            pending.append((prio, len(val), inst.part, inst.gate, key, x, y, val, asize, angle, justify, own_box))
    import os
    audit = []
    for prio, _n, part, gate, key, x, y, val, asize, angle, justify, own_box in sorted(pending, key=lambda r: (r[0], r[1])):
        slot = nudge(x, y, val, asize, angle, justify, own_box)
        placed[(part, gate, key)] = slot
        box = text_box(*slot[:2], val, asize, slot[2], slot[3])
        hits = [o for o in occupied if overlaps(box, o, 0.0)
                and not (o == own_box and o[0] <= box[0] and box[2] <= o[2] and o[1] <= box[1] and box[3] <= o[3])]
        if hits:
            audit.append(f"{part}.{key} '{val}' at ({slot[0]:.1f},{slot[1]:.1f}) a{slot[2]} still overlaps {len(hits)}; moved={(slot[0], slot[1]) != (x, y)}")
        occupied.append(box)
    stats["field_overlaps"] = len(audit)
    if os.environ.get("SCH_DEBUG"):
        print("\n".join(audit))

    supply_flag_done: set[str] = set()
    flag_refs: dict[str, str] = {}

    def flag_ref(net_name: str) -> str:
        return flag_refs.setdefault(net_name, f"#FLG{len(flag_refs) + 1}")
    # nets already driven by a power_out pin (per checks/parts.py) need no PWR_FLAG
    for net in nets:
        for pr in net.iter("pinref"):
            pp = parts[pr.get("part")]
            if pp.lib in SKIP_LIBS:
                continue
            if PIN_TYPES.get(pp.deviceset, {}).get(pr.get("pin")) == "power_out":
                supply_flag_done.add(net.get("name"))
    # nets with a power_in pin but no driver get a PWR_FLAG at that pin
    flag_points: dict[str, tuple[float, float]] = {}
    for net in nets:
        nm = net.get("name")
        for pr in net.iter("pinref"):
            pp = parts[pr.get("part")]
            if pp.lib in SKIP_LIBS or nm in supply_flag_done or nm in flag_points:
                continue
            if PIN_TYPES.get(pp.deviceset, {}).get(pr.get("pin")) == "power_in":
                inst = next(i for i in instances if i.part == pp.name and i.gate == pr.get("gate"))
                dsx = devicesets[(pp.lib, pp.deviceset)]
                symx = symbols[(dsx.lib, next(g[1] for g in dsx.gates if g[0] == pr.get("gate")))]
                pin = next(pn for pn in symx.pins if pn.name == pr.get("pin"))
                flag_points[nm] = instance_point(inst, pin.x, pin.y)
    for nm, (fx, fy) in flag_points.items():
        supply_flag_done.add(nm)
        fu = stable_uuid("flag", nm)
        body.append("\n".join([
            f"  (symbol (lib_id {q(f'{sym_lib}:PWR_FLAG')}) (at {fnum(fx)} {fnum(fy)} 0) (unit 1) (exclude_from_sim no) (in_bom no) (on_board no) (dnp no) (uuid {q(fu)})",
            f"    (property \"Reference\" {q(flag_ref(nm))} (at {fnum(fx)} {fnum(fy)} 0) (effects (font (size 1.27 1.27)) (hide yes)))",
            f"    (property \"Value\" \"PWR_FLAG\" (at {fnum(fx)} {fnum(fy)} 0) (effects (font (size 1.27 1.27)) (hide yes)))",
            "    (property \"Footprint\" \"\" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))",
            "    (property \"Datasheet\" \"\" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))",
            f"    (pin \"1\" (uuid {q(stable_uuid('flagpin', nm))}))",
            f"    (instances (project {q(project)} (path {q('/' + root_uuid)} (reference {q(flag_ref(nm))}) (unit 1))))",
            "  )"]))
    no_connects: list[tuple[float, float]] = []
    bom_by_fp: dict[str, dict[str, str]] = {f["_footprint"]: f for f in bom_fields.values()}
    for inst in instances:
        p = parts[inst.part]
        if p.lib in SKIP_LIBS:
            continue
        ds = devicesets[(p.lib, p.deviceset)]
        name, power = part_symbol[p.name]
        unit = [g[0] for g in ds.gates].index(inst.gate) + 1
        sx, sy = eagle_to_sheet(inst.x, inst.y)
        sym = symbols[(ds.lib, ds.gates[unit - 1][1])]
        own_box = instance_box(inst, sym)
        value = p.value or ds.name
        if power:
            value = sym.pins[0].name  # KiCad power symbols take the net name from Value
        ref = ("#" + p.name) if power else kicad_ref(p.name)
        u = stable_uuid("inst", p.name, inst.gate)

        def prop(key: str, val: str, default_xy, hide: bool):
            if key in inst.attrs:
                ax, ay, arot, asize, amirror = inst.attrs[key]
                x, y = eagle_to_sheet(ax, ay)
            else:
                lx, ly, arot, asize = default_xy
                amirror = False
                x, y = instance_point(inst, lx, ly)
                hide = hide or inst.smashed  # smashed instance without the attribute: Eagle hid it
            asize = min(asize, FIELD_SIZE_MAX)
            angle, eff = effects(asize, arot, amirror, hide)
            if not hide:
                justify = eff.split("(justify ")[1].split(")")[0]
                slot = placed.get((inst.part, inst.gate, key))
                if slot is None:
                    slot = nudge(x, y, val, asize, angle, justify, own_box)
                    occupied.append(text_box(*slot[:2], val, asize, slot[2], slot[3]))
                x, y, angle, justify = slot
                bx0, by0, bx1, by1 = text_box(x, y, val, asize, angle, justify)
                x, y = (bx0 + bx1) / 2, (by0 + by1) / 2
                # Field angles are relative to the symbol; KiCad keeps the text readable.
                angle = (angle - int(inst.rot)) % 180
                eff = f"(effects (font (size {fnum(asize)} {fnum(asize)})))"
            kname = {"NAME": "Reference", "VALUE": "Value"}[key]
            return f"    (property {q(kname)} {q(val)} (at {fnum(x)} {fnum(y)} {fnum(angle)}) {eff})"

        props = [
            prop("NAME", ref, sym.name_text or (0, 2.54, 0, 1.27), hide=power),
            prop("VALUE", value, sym.value_text or (0, -2.54, 0, 1.27), hide=False),
            f"    (property \"Footprint\" {q(f'{fp_lib}:{fp_name(ds.devices[p.device][0])}' if ds.devices[p.device][0] else '')} (at {fnum(sx)} {fnum(sy)} 0) (effects (font (size 1.27 1.27)) (hide yes)))",
        ]
        fields = None
        if not power and ds.devices[p.device][0]:
            fields = bom_fields.get(p.name) or bom_by_fp.get(ds.devices[p.device][0])
        datasheet = ""
        if fields:
            datasheet = DATASHEETS.get(fields.get("MPN", ""), fields.get("_link", ""))
        props.append(f"    (property \"Datasheet\" {q(datasheet)} (at {fnum(sx)} {fnum(sy)} 0) (effects (font (size 1.27 1.27)) (hide yes)))")
        if not power and ds.devices[p.device][0]:
            if fields:
                stats["bom_fields"] += 1
                for k in ("Manufacturer", "MPN", "Digi-Key_PN", "LCSC"):
                    props.append(f"    (property {q(k)} {q(fields.get(k, ''))} (at {fnum(sx)} {fnum(sy)} 0) (effects (font (size 1.27 1.27)) (hide yes)))")
            else:
                stats["bom_missing"].append(p.name)
        mirror = " (mirror y)" if inst.mirror else ""
        pins_sexpr = []
        conns = ds.devices[p.device][1]
        for pin in sym.pins:
            for pad in conns.get((inst.gate, pin.name), [pin.name]):
                pins_sexpr.append(f"    (pin {q(pad)} (uuid {q(stable_uuid('pin', p.name, inst.gate, pad))}))")
            if not power and (p.name, inst.gate, pin.name) not in used_pins:
                for k in range(len(conns.get((inst.gate, pin.name), [pin.name]))):
                    dx, dy = pad_offset(pin, k)
                    no_connects.append(instance_point(inst, pin.x + dx, pin.y + dy))
        body.append("\n".join([
            f"  (symbol (lib_id {q(f'{sym_lib}:{name}')}) (at {fnum(sx)} {fnum(sy)} {fnum(inst.rot)}){mirror} (unit {unit})"
            f" (exclude_from_sim no) (in_bom {'no' if power else 'yes'}) (on_board {'no' if power else 'yes'}) (dnp no) (uuid {q(u)})",
            *props, *pins_sexpr,
            f"    (instances (project {q(project)} (path {q('/' + root_uuid)} (reference {q(ref)}) (unit {unit}))))",
            "  )"]))
        if power and SUPPLY_NET_FLAGS and value not in supply_flag_done:
            supply_flag_done.add(value)
            fx, fy = instance_point(inst, sym.pins[0].x, sym.pins[0].y)
            fu = stable_uuid("flag", value)
            body.append("\n".join([
                f"  (symbol (lib_id {q(f'{sym_lib}:PWR_FLAG')}) (at {fnum(fx)} {fnum(fy)} 0) (unit 1) (exclude_from_sim no) (in_bom no) (on_board no) (dnp no) (uuid {q(fu)})",
                f"    (property \"Reference\" {q(flag_ref(value))} (at {fnum(fx)} {fnum(fy)} 0) (effects (font (size 1.27 1.27)) (hide yes)))",
                f"    (property \"Value\" \"PWR_FLAG\" (at {fnum(fx)} {fnum(fy)} 0) (effects (font (size 1.27 1.27)) (hide yes)))",
                "    (property \"Footprint\" \"\" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))",
                "    (property \"Datasheet\" \"\" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))",
                f"    (pin \"1\" (uuid {q(stable_uuid('flagpin', value))}))",
                f"    (instances (project {q(project)} (path {q('/' + root_uuid)} (reference {q(flag_ref(value))}) (unit 1))))",
                "  )"]))

    body.extend(label_items)
    body.extend(plain_items)

    stats["no_connects"] = len(no_connects)
    for x, y in no_connects:
        body.append(f"  (no_connect (at {fnum(x)} {fnum(y)}) (uuid {q(stable_uuid('nc', fnum(x), fnum(y)))}))")

    lib_symbols = "\n".join(lib_defs[k].replace(f'(symbol "{k}"', f'(symbol "{sym_lib}:{k}"', 1) for k in sorted(lib_defs))
    sch = "\n".join([
        f"(kicad_sch (version 20250114) (generator \"eeschema\") (generator_version \"9.0\") (uuid {q(root_uuid)}) (paper {q(PAGE)})",
        f"  (title_block (title {q(TITLE['title'])}) (rev {q(TITLE['rev'])}) (company {q(TITLE['company'])}) (comment 1 {q(TITLE['comment'])}))",
        "  (lib_symbols", lib_symbols, "  )",
        *body,
        f"  (sheet_instances (path \"/\" (page \"1\")))",
        ")", ""])
    out.write_text(sch)

    lib = "\n".join([
        "(kicad_symbol_lib (version 20241209) (generator \"kicad_symbol_editor\") (generator_version \"9.0\")",
        *[lib_defs[k] for k in sorted(lib_defs)],
        ")", ""])
    out.with_name(f"{sym_lib}.kicad_sym").write_text(lib)
    stats["symbols"] = len(lib_defs)
    stats["instances"] = sum(1 for i in instances if parts[i.part].lib not in SKIP_LIBS)
    return stats


if __name__ == "__main__":
    eagle, out, sym_lib, fp_lib = sys.argv[1:5]
    bom = Path(sys.argv[5]) if len(sys.argv) > 5 else None
    print("sch_convert:", convert(Path(eagle), Path(out), sym_lib, fp_lib, bom))
