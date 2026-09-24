"""Analytic 3D placement: where KiCad's viewer puts a model, computed, not rendered.

The vertex chain is the one in KiCad's 3D renderer (render_3d_opengl.cpp, renderFootprint):

    world = T(fp.x, -fp.y, z_seat) . Rz(fp_angle) . [Ry(pi) . Rz(pi) if back side]
            . T(offset) . Rz(-rz) . Ry(-ry) . Rx(-rx) . S(scale) . vertex

with model units in mm and z_seat the top (front) or bottom (back) surface of the board.

The model's own vertices come from KiCad's STEP loader, exported once per model file via
`kicad-cli pcb export glb` of a one-footprint scratch board with an identity transform,
so nested placements inside the STEP file are resolved by the same code the viewer uses.
Those canonical clouds are cached in build/.

The exporter seats a front model a little above the board's top surface (board thickness
plus its tech-layer allowance). That shift is measured, not assumed: the TE 63952-1 STEP
is a single solid with no placements, so its raw CARTESIAN_POINTs are the truth, and the
difference between them and its exported cloud calibrates every other model.
"""
from __future__ import annotations

import json
import math
import struct
from pathlib import Path

import numpy as np

from . import sexpr
from .paths import BUILD, KICAD_PCB, run_kicad_cli

BOARD_T = 1.6
CALIBRATION_STEP = "${KIPRJMOD}/3d/TE_63952-1.step"   # single solid, no placements
KICAD_3D = Path(__file__).resolve().parent.parent / "tools/KiCad/KiCad.app/Contents/SharedSupport/3dmodels"


def resolve(path: str) -> Path:
    import os
    p = path.replace("${KICAD10_3DMODEL_DIR}", os.environ.get("KICAD10_3DMODEL_DIR", str(KICAD_3D)))
    return Path(p.replace("${KIPRJMOD}", str(KICAD_PCB.parent)))


# ---------------------------------------------------------------- canonical clouds
def _glb_vertices(glb: Path) -> np.ndarray:
    data = glb.read_bytes()
    assert data[:4] == b"glTF"
    length = struct.unpack_from("<I", data, 8)[0]
    off, chunks = 12, {}
    while off < length:
        clen, ctype = struct.unpack_from("<II", data, off)
        chunks[ctype] = data[off + 8:off + 8 + clen]
        off += 8 + clen
    g = json.loads(chunks[0x4E4F534A]); binary = chunks[0x004E4942]

    def accessor(i):
        a = g["accessors"][i]; bv = g["bufferViews"][a["bufferView"]]
        start = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
        return np.frombuffer(binary, dtype="<f4", count=a["count"] * 3, offset=start).reshape(-1, 3).astype(float)

    def local(node):
        if "matrix" in node:
            return np.array(node["matrix"], dtype=float).reshape(4, 4).T
        m = np.eye(4)
        if "scale" in node:
            m = m @ np.diag([*node["scale"], 1.0])
        if "rotation" in node:
            x, y, z, w = node["rotation"]
            r = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                          [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                          [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
            rm = np.eye(4); rm[:3, :3] = r; m = rm @ m
        if "translation" in node:
            tm = np.eye(4); tm[:3, 3] = node["translation"]; m = tm @ m
        return m

    verts = []

    def walk(idx, parent):
        node = g["nodes"][idx]; m = parent @ local(node)
        if "mesh" in node:
            for prim in g["meshes"][node["mesh"]]["primitives"]:
                v = accessor(prim["attributes"]["POSITION"])
                verts.append((np.hstack([v, np.ones((len(v), 1))]) @ m.T)[:, :3])
        for c in node.get("children", []):
            walk(c, m)

    for root in g["scenes"][g.get("scene", 0)]["nodes"]:
        walk(root, np.eye(4))
    v = np.vstack(verts) if verts else np.zeros((0, 3))
    # glTF is Y-up in metres; KiCad's exporter maps board Z-up to it: board (x, y, z) = (x, -z, y)
    return np.stack([v[:, 0], -v[:, 2], v[:, 1]], axis=1) * 1000.0


def step_points(path: Path) -> np.ndarray:
    """Raw CARTESIAN_POINTs of a STEP file: exact only for a single solid with no placements."""
    import re
    text = path.read_text(errors="ignore")
    return np.array([[float(v) for v in m.split(",")]
                     for m in re.findall(r"CARTESIAN_POINT\s*\(\s*'[^']*'\s*,\s*\(([^)]*)\)", text)])


def _export_cloud(path: Path) -> np.ndarray:
    """Export one model through kicad-cli on a scratch board, uncorrected."""
    (BUILD / "clouds").mkdir(parents=True, exist_ok=True)
    scratch = KICAD_PCB.with_name("cloud-lab.kicad_pcb")
    scratch.write_text(f'''(kicad_pcb (version 20241229) (generator "pcbnew") (generator_version "9.0")
  (general (thickness {BOARD_T}) (legacy_teardrops no))
  (paper "A4")
  (layers (0 "F.Cu" signal) (2 "B.Cu" signal) (25 "Edge.Cuts" user) (5 "F.SilkS" user "F.Silkscreen"))
  (setup (pad_to_mask_clearance 0))
  (footprint "cloud" (layer "F.Cu") (uuid "00000000-0000-0000-0000-000000000001") (at 0 0)
    (property "Reference" "X1" (at 0 0 0) (layer "F.SilkS") (uuid "00000000-0000-0000-0000-000000000002") (effects (font (size 1 1) (thickness 0.15))))
    (property "Value" "cloud" (at 0 0 0) (layer "F.Fab") (uuid "00000000-0000-0000-0000-000000000003") (effects (font (size 1 1) (thickness 0.15))))
    (attr through_hole)
    (model "{path}" (offset (xyz 0 0 0)) (scale (xyz 1 1 1)) (rotate (xyz 0 0 0)))
  )
)
''')
    out = BUILD / "clouds" / (path.name + ".glb")
    try:
        run_kicad_cli("pcb", "export", "glb", "--output", str(out), "--force", "--subst-models",
                      "--no-board-body", str(scratch))
    finally:
        scratch.unlink(missing_ok=True)
    return _glb_vertices(out)


def export_shift() -> np.ndarray:
    """Where the exporter puts a model's origin, measured on the calibration STEP."""
    cache = BUILD / "clouds" / "shift.npy"
    if cache.exists():
        return np.load(cache)
    path = resolve(CALIBRATION_STEP)
    shift = _export_cloud(path).max(0) - step_points(path).max(0)
    np.save(cache, shift)
    return shift


def canonical_cloud(model: str) -> np.ndarray:
    """Model vertices in the model's own frame (mm), as KiCad loads them."""
    path = resolve(model)
    cache = BUILD / "clouds" / (path.name + ".npy")
    if cache.exists() and cache.stat().st_mtime >= path.stat().st_mtime:
        return np.load(cache)
    v = _export_cloud(path) - export_shift()
    np.save(cache, v)
    return v


# ---------------------------------------------------------------- the viewer's transform
def _R(axis: str, deg: float) -> np.ndarray:
    a = math.radians(deg); c, s = math.cos(a), math.sin(a)
    if axis == "x":
        return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])
    if axis == "y":
        return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])


def place(cloud: np.ndarray, offset, rotate, scale, fp_x: float, fp_y_file: float, fp_deg: float, back: bool) -> np.ndarray:
    """Model cloud -> board frame (x right, y up, z up; z=0 at the top surface), mm."""
    rx, ry, rz = rotate
    m = _R("z", -rz) @ _R("y", -ry) @ _R("x", -rx) @ np.diag(scale)
    v = cloud @ m.T + np.array(offset, dtype=float)
    if back:
        v = v @ (_R("y", 180) @ _R("z", 180)).T
    v = v @ _R("z", fp_deg).T
    return v + np.array([fp_x, -fp_y_file, -BOARD_T if back else 0.0])


def board_models():
    """Every (ref, model, offset, rotate, scale, fp_x, fp_y, fp_deg, back, pads) on the board."""
    root = sexpr.load(KICAD_PCB)
    out = []
    for fp in sexpr.children(root, "footprint"):
        ref = sexpr.prop(fp, "Reference")
        at = sexpr.child(fp, "at"); fx, fy = float(at[1]), float(at[2]); deg = float(at[3]) if len(at) > 3 else 0.0
        back = sexpr.child(fp, "layer")[1].startswith("B.")
        pads = []
        for pad in sexpr.children(fp, "pad"):
            pa = sexpr.child(pad, "at"); px, py = float(pa[1]), float(pa[2])
            if back:
                px = -px
            a = math.radians(-deg)
            pads.append((fx + px * math.cos(a) - py * math.sin(a), -(fy + px * math.sin(a) + py * math.cos(a))))
        for m in sexpr.children(fp, "model"):
            off = tuple(float(v) for v in sexpr.child(m, "offset")[1][1:])
            rot = tuple(float(v) for v in sexpr.child(m, "rotate")[1][1:]) if sexpr.child(m, "rotate") else (0.0, 0.0, 0.0)
            sc = tuple(float(v) for v in sexpr.child(m, "scale")[1][1:]) if sexpr.child(m, "scale") else (1.0, 1.0, 1.0)
            out.append(dict(ref=ref, model=m[1], offset=off, rotate=rot, scale=sc, fp_x=fx, fp_y=fy, fp_deg=deg, back=back, pads=pads))
    return out


def placed(entry: dict) -> np.ndarray:
    return place(canonical_cloud(entry["model"]), entry["offset"], entry["rotate"], entry["scale"],
                 entry["fp_x"], entry["fp_y"], entry["fp_deg"], entry["back"])


def metrics(v: np.ndarray, back: bool) -> dict:
    """What matters physically, from the placed cloud (mm, board frame)."""
    z = v[:, 2]
    top, bottom = 0.0, -BOARD_T
    crossing = v[(z > bottom - 0.8) & (z < top + 0.8)]      # material passing through the board
    far = v[z > top + 0.3] if back else v[z < bottom - 0.3]  # material on the far side (leads)
    return {
        "z_min": float(z.min()), "z_max": float(z.max()),
        "above": float(max(z.max() - top, 0.0)), "below": float(max(bottom - z.min(), 0.0)),
        "x": (float(v[:, 0].min()), float(v[:, 0].max())), "y": (float(v[:, 1].min()), float(v[:, 1].max())),
        "waist": float(max(np.ptp(crossing[:, 0]), np.ptp(crossing[:, 1]))) if len(crossing) > 1 else 0.0,
        "far": (float(far[:, 0].mean()), float(far[:, 1].mean()), float(np.ptp(far[:, 0])), float(np.ptp(far[:, 1]))) if len(far) else None,
    }


if __name__ == "__main__":
    import sys
    want = set(sys.argv[1:])
    for e in board_models():
        if want and e["ref"] not in want:
            continue
        m = metrics(placed(e), e["back"])
        px = [p[0] for p in e["pads"]]; py = [p[1] for p in e["pads"]]
        print(f"{e['ref']:7} {'back ' if e['back'] else 'front'} above {m['above']:5.1f} below {m['below']:5.1f} waist {m['waist']:5.1f} "
              f"x {m['x'][0]:6.1f}..{m['x'][1]:6.1f} y {m['y'][0]:6.1f}..{m['y'][1]:6.1f} | pads x {min(px):6.1f}..{max(px):6.1f} y {min(py):6.1f}..{max(py):6.1f}"
              + (f" far@({m['far'][0]:.1f},{m['far'][1]:.1f})" if m['far'] else ""))
