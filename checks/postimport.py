"""Deterministic fix-ups applied right after `kicad-cli pcb import`.

kicad-cli has no layer-mapping dialog, so Eagle layers without a default KiCad
equivalent land on a layer literally named UNDEFINED and the board refuses to load.
This board uses two such layers inside footprints:

  * Eagle 46 "Milling" (DCJACK-PJ-066A-SLOT): the slot outlines for the DC jack's
    blade pins. Eagle's CAM job plots Milling together with Dimension into the
    mechanical Gerber, so the KiCad equivalent is Edge.Cuts.
  * Eagle 37 "tTest" (P1-17 test pads): a text marker. Documentation only -> F.Fab.

It also drops footprint text that only holds an Eagle attribute placeholder the board
never filled in (TP_SIGNAL_NAME on the test pads is "" with display off), which KiCad
would otherwise report as an unresolved ${variable}.

The bottom silkscreen carries two bitmap logos that Eagle stored as ~8000 hairline
rectangles. kicad-cli turns them into zones, which never fill (they are thinner than any
zone minimum width) and so vanish from plots. They become plain filled polygons here.

Usage: python -m checks.postimport <board.kicad_pcb>
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from .stable_ids import stabilise

GRAPHIC_TARGET = None         # Eagle Milling graphics are dropped: fp_export makes plated slot pads
TEXT_TARGET = "F.Fab"          # fp_text / property


DROP_TEXT = ("${TP_SIGNAL_NAME}",)


def _drop_blocks(lines: list[str], counts: dict[str, int]) -> list[str]:
    """Remove pretty-printed (fp_text ...) blocks whose text is in DROP_TEXT."""
    out, i = [], 0
    while i < len(lines):
        line = lines[i]
        stripped = line.lstrip("\t ")
        if stripped.startswith("(fp_text") and any(f'"{t}"' in line or f'"{t}"' in lines[i + 1] for t in DROP_TEXT):
            indent = len(line) - len(stripped)
            j = i + 1
            while not (lines[j].startswith("\t" * (indent // 1) + ")") and len(lines[j]) - len(lines[j].lstrip("\t ")) == indent):
                j += 1
            counts["dropped fp_text"] = counts.get("dropped fp_text", 0) + 1
            i = j + 1
            continue
        out.append(line)
        i += 1
    return out


ZONE_RE = re.compile(r"\t\(zone\n(.*?)\n\t\)\n", re.S)


def _zones_to_polys(text: str, counts: dict[str, int]) -> str:
    def repl(m: re.Match) -> str:
        body = m.group(1)
        layer = re.search(r'\(layer "([^"]+)"\)', body).group(1)
        if layer.endswith(".Cu"):
            return m.group(0)
        pts = re.search(r"\(pts\n\s*(.*?)\n", body).group(1).strip()
        counts[f"{layer} zone->gr_poly"] = counts.get(f"{layer} zone->gr_poly", 0) + 1
        uuid = re.search(r'\(uuid "([^"]+)"\)', body).group(1)
        return (f"\t(gr_poly\n\t\t(pts\n\t\t\t{pts}\n\t\t)\n\t\t(stroke\n\t\t\t(width 0)\n\t\t\t(type solid)\n\t\t)\n"
                f"\t\t(fill yes)\n\t\t(layer \"{layer}\")\n\t\t(uuid \"{uuid}\")\n\t)\n")
    return ZONE_RE.sub(repl, text)


BLOCK_RE = re.compile(r"\t\t\((fp_line|fp_arc|fp_poly|fp_circle)\n(.*?)\n\t\t\)\n", re.S)


def _drop_undefined_graphics(text: str, counts: dict[str, int]) -> str:
    def repl(m: re.Match) -> str:
        if '(layer "UNDEFINED")' in m.group(2):
            counts[f"dropped {m.group(1)} (Eagle Milling)"] = counts.get(f"dropped {m.group(1)} (Eagle Milling)", 0) + 1
            return ""
        return m.group(0)
    return BLOCK_RE.sub(repl, text)


def fix(text: str) -> tuple[str, dict[str, int]]:
    counts: dict[str, int] = {}
    text = _zones_to_polys(text, counts)
    if GRAPHIC_TARGET is None:
        text = _drop_undefined_graphics(text, counts)
    out = []
    current = None  # head of the enclosing item, e.g. "fp_line"
    for line in _drop_blocks(text.splitlines(keepends=True), counts):
        m = re.match(r"\s*\((fp_line|fp_arc|fp_poly|fp_circle|fp_rect|fp_text|gr_line|gr_arc|gr_text|property)\b", line)
        if m:
            current = m.group(1)
        if '(layer "UNDEFINED")' in line:
            target = TEXT_TARGET if current in ("fp_text", "gr_text", "property") else (GRAPHIC_TARGET or "Cmts.User")
            line = line.replace('(layer "UNDEFINED")', f'(layer "{target}")')
            counts[f"{current}->{target}"] = counts.get(f"{current}->{target}", 0) + 1
        out.append(line)
    return "".join(out), counts


POWER_NETS = {"GND", "+12V", "+5V", "+3V3"}  # driven by power symbols in the schematic


def _local_net_names(text: str, counts: dict[str, int]) -> str:
    """KiCad names a net from a local label "/NAME"; Eagle's board carries bare names."""
    def repl(m: re.Match) -> str:
        name = m.group(2)
        if name in POWER_NETS or name.startswith("/") or not name:
            return m.group(0)
        counts["nets prefixed '/'"] = counts.get("nets prefixed '/'", 0) + 1
        return f'{m.group(1)}"/{name}")'
    return re.sub(r'(\(net(?:_name)?(?: \d+)? )"([^"]*)"\)', repl, text)


def main(path: Path) -> None:
    fixed, counts = fix(path.read_text())
    fixed = _local_net_names(fixed, counts)
    from .qr import polys
    qr_text, info = polys(fixed)
    fixed = fixed.rstrip()
    assert fixed.endswith(")")
    fixed = fixed[:-1] + qr_text + ")\n"
    counts[f"QR {info['modules']}x{info['modules']} ({info['side_mm']} mm) at {info['at']} -> {info['text']}"] = 1
    path.write_text(fixed)
    counts['uuids_stabilised'] = stabilise(path)
    for k, v in sorted(counts.items()):
        print(f"postimport: {v:3d} x {k}")
    if "UNDEFINED" in fixed:
        sys.exit("postimport: UNDEFINED layers remain")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
