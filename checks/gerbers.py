"""Compare the Gerbers Eagle produced for fabrication (committed in dist/) against the
Gerbers kicad-cli produces from the imported board. Raster XOR per layer, plus an exact
hole-list comparison for the drill file. Writes overlay PNGs to build/ for eyeballing.
"""
from __future__ import annotations

import shutil
import subprocess
import zipfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops
from pygerber.gerberx3.api.v2 import GerberFile

from . import excellon
from .paths import BUILD, EAGLE_GERBERS_ZIP, KICAD_PCB, run_kicad_cli

DPMM = 20  # 50 um per pixel

# Regions (Gerber/Eagle coordinates, mm: x0, y0, x1, y1) excluded from every layer diff.
# The DC jack's blade slots are plated oval pads in KiCad (checks/parts.py SLOT_PADS)
# where Eagle emulated them with SMD pads, end holes and milling; the copper, mask and
# outline there differ by design.
EXCLUDE_MM = {"H1 plated slots": (-7.5, 5.0, 3.5, 16.5)}


def _qr_exclusion() -> dict:
    """The bottom-silk QR code is new artwork (checks/qr.py); Eagle's Gerbers have none."""
    from . import sexpr
    root = sexpr.load(KICAD_PCB)
    xs, ys = [], []
    for g in sexpr.children(root, "gr_poly"):
        u = sexpr.child(g, "uuid")
        if u and u[1].startswith("qr-"):
            for pt in sexpr.child(g, "pts")[1:]:
                xs.append(float(pt[1])); ys.append(float(pt[2]))
    if not xs:
        return {}
    return {"bottom silk QR": (min(xs) - 1, -max(ys) - 1, max(xs) + 1, -min(ys) + 1)}  # file y-down -> gerber y-up

# Eagle CAM extension -> KiCad layer name
LAYERS = {
    "GTL": "F.Cu", "GBL": "B.Cu",
    "GTS": "F.Mask", "GBS": "B.Mask",
    "GTO": "F.SilkS", "GBO": "B.SilkS",
    "GTP": "F.Paste", "GBP": "B.Paste",
    "GML": "Edge.Cuts",
}
KICAD_SUFFIX = {  # kicad-cli names files <board>-<layer>.<protel ext>; match on the layer part
    "F.Cu": "F_Cu", "B.Cu": "B_Cu", "F.Mask": "F_Mask", "B.Mask": "B_Mask",
    "F.SilkS": "F_Silkscreen", "B.SilkS": "B_Silkscreen",
    "F.Paste": "F_Paste", "B.Paste": "B_Paste", "Edge.Cuts": "Edge_Cuts",
}


def eagle_gerbers() -> dict[str, Path]:
    out = BUILD / "gerbers-eagle"
    out.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(EAGLE_GERBERS_ZIP) as z:
        z.extractall(out)
    files = {}
    for p in out.iterdir():
        ext = p.suffix.lstrip(".").upper()
        if ext in LAYERS:
            files[LAYERS[ext]] = p
        elif ext == "TXT":
            files["drill"] = p
    return files


def filled_board() -> Path:
    """A copy of the board with zones filled, so plots include the pours.
    (kicad-cli's plotters do not refill; DRC with --save-board does.)"""
    out = BUILD / "filled" / KICAD_PCB.name
    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(KICAD_PCB, out)
    run_kicad_cli("pcb", "drc", "--refill-zones", "--save-board", "--output",
                  str(out.with_suffix(".drc.rpt")), str(out), check=False)
    return out


def kicad_gerbers() -> dict[str, Path]:
    out = BUILD / "gerbers-kicad"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    board = filled_board()
    run_kicad_cli("pcb", "export", "gerbers", "--output", str(out) + "/",
                  "--layers", ",".join(KICAD_SUFFIX), "--no-x2", "--no-netlist",
                  "--precision", "6", str(board))
    run_kicad_cli("pcb", "export", "drill", "--output", str(out) + "/", "--format", "excellon",
                  "--drill-origin", "absolute", "--excellon-units", "mm",
                  "--excellon-zeros-format", "decimal", "--excellon-separate-th", str(board))
    files = {}
    for layer, suffix in KICAD_SUFFIX.items():
        files[layer] = next(out.glob(f"*-{suffix}.*"))
    drills = sorted(out.glob("*.drl"))
    files["drill"] = drills
    return files


@dataclass
class LayerDiff:
    layer: str
    bbox_a: tuple[float, float, float, float]
    bbox_b: tuple[float, float, float, float]
    area_a_mm2: float
    area_b_mm2: float
    mismatch_mm2: float  # pixels set in exactly one image, after 1px tolerance
    overlay: Path

    @property
    def mismatch_ratio(self) -> float:
        union = max(self.area_a_mm2, self.area_b_mm2, 1e-9)
        return self.mismatch_mm2 / union


def _render(path: Path) -> tuple[np.ndarray, tuple[float, float, float, float]]:
    parsed = GerberFile.from_file(path).parse()
    info = parsed.get_info()
    png = BUILD / "render" / (path.name + ".png")
    png.parent.mkdir(parents=True, exist_ok=True)
    parsed.render_raster(png, dpmm=DPMM)
    img = np.asarray(Image.open(png).convert("L"))
    # pygerber draws "solid" in a mid green and background black: threshold
    mask = img > 20
    bbox = (float(info.min_x_mm), float(info.min_y_mm), float(info.max_x_mm), float(info.max_y_mm))
    return mask, bbox


def _place(mask: np.ndarray, bbox, canvas_bbox) -> np.ndarray:
    gx0, gy0, gx1, gy1 = canvas_bbox
    W = int(round((gx1 - gx0) * DPMM)) + 2
    H = int(round((gy1 - gy0) * DPMM)) + 2
    canvas = np.zeros((H, W), dtype=bool)
    ox = int(round((bbox[0] - gx0) * DPMM))
    oy = int(round((gy1 - bbox[3]) * DPMM))  # image row 0 is max y
    h, w = mask.shape
    h = min(h, H - oy)
    w = min(w, W - ox)
    canvas[oy:oy + h, ox:ox + w] = mask[:h, :w]
    return canvas


def _dilate(m: np.ndarray, r: int = 1) -> np.ndarray:
    out = m.copy()
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            out |= np.roll(np.roll(m, dy, 0), dx, 1)
    return out


# Morphological closing radius (mm) per layer before comparing. Eagle and KiCad draw the
# hatched GND pour with a different grid phase and different thermal spokes, so the
# bottom copper is compared as the *area the hatch covers*; the fine grid itself is not
# design intent. Thin outline/silk strokes get a small closing so line-width differences
# (Eagle 0.254 mm vs KiCad 0.05 mm outline) do not count.
CLOSE_MM = {"B.Cu": 0.6, "Edge.Cuts": 0.3, "F.SilkS": 0.15, "B.SilkS": 0.15}
# Positional tolerance (mm) when deciding a pixel is "only in one file". Copper and mask
# are compared at one pixel; silkscreen text is drawn with different stroke fonts by the
# two tools, so it gets a looser tolerance that still catches missing or shifted items.
TOL_MM = {"F.SilkS": 0.4, "B.SilkS": 0.4, "Edge.Cuts": 0.3}


def _close(m: np.ndarray, r_px: int) -> np.ndarray:
    if r_px <= 0:
        return m
    d = _dilate(m, r_px)
    return ~_dilate(~d, r_px)


def diff_layer(layer: str, a: Path, b: Path) -> LayerDiff:
    ma, ba = _render(a)
    mb, bb = _render(b)
    canvas = (min(ba[0], bb[0]), min(ba[1], bb[1]), max(ba[2], bb[2]), max(ba[3], bb[3]))
    r = int(round(CLOSE_MM.get(layer, 0) * DPMM))
    A = _close(_place(ma, ba, canvas), r)
    B = _close(_place(mb, bb, canvas), r)
    for x0, y0, x1, y1 in {**EXCLUDE_MM, **_qr_exclusion()}.values():
        c0 = int((x0 - canvas[0]) * DPMM); c1 = int((x1 - canvas[0]) * DPMM)
        r0 = int((canvas[3] - y1) * DPMM); r1 = int((canvas[3] - y0) * DPMM)
        A[max(r0, 0):r1, max(c0, 0):c1] = False
        B[max(r0, 0):r1, max(c0, 0):c1] = False
    tol = max(1, int(round(TOL_MM.get(layer, 0.05) * DPMM)))
    only_a = A & ~_dilate(B, tol)
    only_b = B & ~_dilate(A, tol)
    px_mm2 = 1.0 / (DPMM * DPMM)
    overlay = BUILD / "render" / f"diff-{layer}.png"
    rgb = np.zeros(A.shape + (3,), dtype=np.uint8)
    rgb[A & B] = (90, 90, 90)
    rgb[only_a] = (255, 40, 40)   # red: Eagle only
    rgb[only_b] = (40, 120, 255)  # blue: KiCad only
    Image.fromarray(rgb).save(overlay)
    return LayerDiff(layer, ba, bb, A.sum() * px_mm2, B.sum() * px_mm2,
                     (only_a.sum() + only_b.sum()) * px_mm2, overlay)


def drill_holes(paths: Path | list[Path]) -> list[excellon.Hole]:
    if isinstance(paths, Path):
        paths = [paths]
    holes: list[excellon.Hole] = []
    for p in paths:
        holes.extend(excellon.load(p))
    return sorted(holes)


def compare_all() -> tuple[list[LayerDiff], list[excellon.Hole], list[excellon.Hole]]:
    e = eagle_gerbers()
    k = kicad_gerbers()
    diffs = [diff_layer(layer, e[layer], k[layer]) for layer in KICAD_SUFFIX if layer in e]
    return diffs, drill_holes(e["drill"]), drill_holes(k["drill"])


if __name__ == "__main__":
    diffs, eh, kh = compare_all()
    print(f"{'layer':10} {'eagle mm2':>10} {'kicad mm2':>10} {'mismatch':>10} {'ratio':>7}")
    for d in diffs:
        print(f"{d.layer:10} {d.area_a_mm2:10.2f} {d.area_b_mm2:10.2f} {d.mismatch_mm2:10.3f} {d.mismatch_ratio:7.3%}  {d.overlay}")
    print("drill: eagle", len(eh), "kicad", len(kh), "equal:", eh == kh)
