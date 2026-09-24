"""Bottom-silkscreen QR code: content from checks/parts.py, placed automatically."""
from __future__ import annotations

import math

import segno

from . import sexpr
from .parts import QR_MODULE_MM, QR_QUIET_MODULES, QR_TEXT


def matrix() -> list[list[int]]:
    return [list(row) for row in segno.make(QR_TEXT, error="l").matrix]


def text_box(g) -> list[tuple[float, float]]:
    """Corners of a gr_text's extent from its anchor, rotation, size and justification."""
    at = sexpr.child(g, "at"); ax, ay = float(at[1]), float(at[2]); rot = float(at[3]) if len(at) > 3 else 0.0
    text = g[1]
    size = 1.5
    eff = sexpr.child(g, "effects")
    font = sexpr.child(eff, "font") if eff else None
    fs = sexpr.child(font, "size") if font else None
    if fs:
        size = float(fs[1])
    just = sexpr.child(eff, "justify") if eff else None
    hj = "left" if just and "left" in just else ("right" if just and "right" in just else "center")
    vj = "bottom" if just and "bottom" in just else ("top" if just and "top" in just else "center")
    length = 0.8 * size * max(1, len(text)) + 0.5
    # extent along the reading direction and across it, before rotation (text reads +x)
    a0 = {"left": 0.0, "center": -length / 2, "right": -length}[hj]
    b0 = {"bottom": -size, "center": -size / 2, "top": 0.0}[vj]
    corners = [(a0, b0), (a0 + length, b0), (a0, b0 + size), (a0 + length, b0 + size)]
    r = math.radians(-rot)  # file frame is y-down; a positive angle reads counter-clockwise on screen
    out = []
    for u, v in corners:
        out.append((ax + u * math.cos(r) - v * math.sin(r), ay + u * math.sin(r) + v * math.cos(r)))
    return out


def obstacles(root) -> tuple[list[tuple[float, float, float, float]], tuple[float, float, float, float]]:
    """Bottom-side keep-out boxes (file frame, y down) and the board bbox."""
    boxes = []
    edge = []

    def pts(node):
        out = []
        for k in ("start", "end", "mid", "center"):
            c = sexpr.child(node, k)
            if c:
                out.append((float(c[1]), float(c[2])))
        p = sexpr.child(node, "pts")
        if p:
            out += [(float(q[1]), float(q[2])) for q in p[1:]]
        return out

    for tag in ("gr_line", "gr_arc", "gr_circle", "gr_rect", "gr_poly", "gr_text"):
        for g in sexpr.children(root, tag):
            layer = sexpr.child(g, "layer")[1]
            if tag == "gr_text":
                p = text_box(g)
            else:
                p = pts(g)
            if not p:
                continue
            xs = [q[0] for q in p]; ys = [q[1] for q in p]
            if layer == "Edge.Cuts":
                edge += p
            elif layer == "B.SilkS":
                boxes.append((min(xs) - 0.6, min(ys) - 0.6, max(xs) + 0.6, max(ys) + 0.6))
    for fp in sexpr.children(root, "footprint"):
        at = sexpr.child(fp, "at"); fx, fy = float(at[1]), float(at[2]); rot = float(at[3]) if len(at) > 3 else 0.0
        back = sexpr.child(fp, "layer")[1].startswith("B.")
        a = math.radians(-rot)

        def place(px, py):
            if back:
                px = -px
            return fx + px * math.cos(a) - py * math.sin(a), fy + px * math.sin(a) + py * math.cos(a)

        for pad in sexpr.children(fp, "pad"):
            pa = sexpr.child(pad, "at"); size = sexpr.child(pad, "size")
            if pad[2] == "smd" and not back:
                continue  # front-side SMD pad: nothing on the bottom
            x, y = place(float(pa[1]), float(pa[2]))
            r = max(float(size[1]), float(size[2])) / 2 + 0.4
            boxes.append((x - r, y - r, x + r, y + r))
        if back:
            for tag in ("fp_line", "fp_arc", "fp_circle", "fp_text", "fp_poly"):
                for g in sexpr.children(fp, tag):
                    p = [place(px, py) for px, py in pts(g)] or None
                    if tag == "fp_text" or (tag == "fp_line" and not p):
                        p = [place(0, 0)]
                    if p:
                        xs = [q[0] for q in p]; ys = [q[1] for q in p]
                        boxes.append((min(xs) - 1.5, min(ys) - 1.5, max(xs) + 1.5, max(ys) + 1.5))
    xs = [q[0] for q in edge]; ys = [q[1] for q in edge]
    return boxes, (min(xs), min(ys), max(xs), max(ys))


def find_spot(root, side_mm: float, margin: float = 1.5, step: float = 0.5) -> tuple[float, float]:
    """Top-left corner (file frame) of a side_mm square clear of every obstacle, nearest the
    board's bottom-left corner as seen from the back (so it sits with the other markings)."""
    boxes, (bx0, by0, bx1, by1) = obstacles(root)
    best = None
    y = by0 + margin
    while y + side_mm <= by1 - margin:
        x = bx0 + margin
        while x + side_mm <= bx1 - margin:
            sq = (x, y, x + side_mm, y + side_mm)
            if not any(not (sq[2] <= b[0] or b[2] <= sq[0] or sq[3] <= b[1] or b[3] <= sq[1]) for b in boxes):
                d = (x - bx0) ** 2 + (by1 - (y + side_mm)) ** 2  # prefer bottom-left of the board
                if best is None or d < best[0]:
                    best = (d, x, y)
            x += step
        y += step
    if best is None:
        raise SystemExit(f"qr: no clear {side_mm:.1f} mm square on the bottom silkscreen")
    return best[1], best[2]


def polys(text: str) -> tuple[str, dict]:
    """KiCad gr_poly blocks for the QR on B.SilkS (mirrored for the bottom view)."""
    root = sexpr.parse(text)
    m = matrix()
    n = len(m)
    side = (n + 2 * QR_QUIET_MODULES) * QR_MODULE_MM
    x0, y0 = find_spot(root, side)
    ox, oy = x0 + QR_QUIET_MODULES * QR_MODULE_MM, y0 + QR_QUIET_MODULES * QR_MODULE_MM
    out = []
    for r, row in enumerate(m):
        for c, bit in enumerate(row):
            if not bit:
                continue
            # mirror left-right: seen from the bottom, the code reads normally
            cx = ox + (n - 1 - c) * QR_MODULE_MM
            cy = oy + r * QR_MODULE_MM
            pts = f"(xy {cx:.3f} {cy:.3f}) (xy {cx + QR_MODULE_MM:.3f} {cy:.3f}) (xy {cx + QR_MODULE_MM:.3f} {cy + QR_MODULE_MM:.3f}) (xy {cx:.3f} {cy + QR_MODULE_MM:.3f})"
            out.append(f"\t(gr_poly\n\t\t(pts\n\t\t\t{pts}\n\t\t)\n\t\t(stroke\n\t\t\t(width 0)\n\t\t\t(type solid)\n\t\t)\n\t\t(fill yes)\n\t\t(layer \"B.SilkS\")\n\t\t(uuid \"qr-{r:02d}-{c:02d}-0000-0000-000000000000\")\n\t)\n")
    info = {"modules": n, "side_mm": round(side, 2), "at": (round(x0, 2), round(y0, 2)), "text": QR_TEXT}
    return "".join(out), info
