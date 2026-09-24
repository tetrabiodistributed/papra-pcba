"""Export the imported board's footprints into a project library and point the board at it.

Runs under KiCad's bundled Python (it needs the pcbnew module):
    <KiCad.app>/Contents/Frameworks/Python.framework/Versions/Current/bin/python3 -m checks.fp_export <board> <lib nickname>

kicad-cli's Eagle importer embeds each footprint in the board with a bare name and no
library. This writes every distinct footprint once to <project dir>/<nickname>.pretty,
normalised to the front side at the origin, then re-links each board footprint to
"<nickname>:<name>" so the schematic's Footprint fields and the board agree (DRC
schematic parity checks exactly that) and the project's library tables resolve.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pcbnew  # type: ignore

from .models import MODELS
from .eagle import load_schematic
from .paths import EAGLE_SCH
from .parts import DATASHEETS
from .sch_convert import load_bom, load_eagle
from .stable_ids import stabilise, stabilise_board


def unconnected_net_names() -> dict[tuple[str, str], str]:
    """KiCad names a no-connect pin's pad net 'unconnected-(REF-PIN-PadN)'; reproduce it so
    the schematic-parity check sees the board agree."""
    symbols, devicesets, parts, instances, nets, _plain = load_eagle(EAGLE_SCH)
    used = {(pr.get("part"), pr.get("gate"), pr.get("pin")) for net in nets for pr in net.iter("pinref")}
    names: dict[tuple[str, str], str] = {}
    for inst in instances:
        part = parts[inst.part]
        if part.lib in devicesets and False:
            pass
        ds = devicesets.get((part.lib, part.deviceset))
        if ds is None:
            continue
        package, conns = ds.devices[part.device]
        if not package:
            continue
        sym = symbols[(ds.lib, next(g[1] for g in ds.gates if g[0] == inst.gate))]
        for pin in sym.pins:
            if (part.name, inst.gate, pin.name) in used:
                continue
            pads = conns.get((inst.gate, pin.name), [pin.name])
            for pad in pads:
                names[(part.name, pad)] = f"unconnected-({part.name}-{pin.name.replace('/', '{slash}')}-Pad{pad})"
    return names
from .parts import SLOT_COPPER, SLOT_DRILL, SLOT_PADS


def plated_slots(fp) -> int:
    """Replace Eagle's SMD+PTH+milling emulation of a slot with one plated oval pad."""
    name = fp.GetFPID().GetLibItemName().wx_str()
    spec = SLOT_PADS.get(name)
    if not spec:
        return 0
    pads = {p.GetNumber(): p for p in fp.Pads()}
    for keep, (fold, (cx, cy), axis) in spec.items():
        pad = pads[keep]
        pth_layers = next(pads[o].GetLayerSet() for o in fold if pads[o].GetAttribute() == pcbnew.PAD_ATTRIB_PTH)
        for old in fold:
            pads[old].DeleteStructure()
        pad.SetAttribute(pcbnew.PAD_ATTRIB_PTH)
        pad.SetShape(pcbnew.PAD_SHAPE_OVAL)
        pad.SetDrillShape(pcbnew.PAD_DRILL_SHAPE_OBLONG)
        L, W = SLOT_DRILL
        CL, CW = SLOT_COPPER
        if axis == "x":
            pad.SetDrillSize(pcbnew.VECTOR2I(pcbnew.FromMM(L), pcbnew.FromMM(W)))
            pad.SetSize(pcbnew.VECTOR2I(pcbnew.FromMM(CL), pcbnew.FromMM(CW)))
        else:
            pad.SetDrillSize(pcbnew.VECTOR2I(pcbnew.FromMM(W), pcbnew.FromMM(L)))
            pad.SetSize(pcbnew.VECTOR2I(pcbnew.FromMM(CW), pcbnew.FromMM(CL)))
        pad.SetFPRelativePosition(pcbnew.VECTOR2I(pcbnew.FromMM(cx), pcbnew.FromMM(cy)))
        pad.SetLayerSet(pth_layers)
    return len(spec)


def attach_model(fp) -> bool:
    name = fp.GetFPID().GetLibItemName().wx_str()
    entry = MODELS.get(name)
    fp.Models().clear()
    if not entry:
        return False
    path, (ox, oy, oz), (rx, ry, rz) = entry
    m = pcbnew.FP_3DMODEL()
    m.m_Filename = path
    m.m_Offset = pcbnew.VECTOR3D(ox, oy, oz)
    m.m_Rotation = pcbnew.VECTOR3D(rx, ry, rz)
    m.m_Scale = pcbnew.VECTOR3D(1, 1, 1)
    fp.Models().push_back(m)
    return True


def pad_signature(fp) -> tuple:
    """Footprint-local pad geometry, independent of placement, rotation and side."""
    return tuple(sorted((p.GetNumber(), abs(p.GetFPRelativePosition().x), abs(p.GetFPRelativePosition().y),
                         p.GetSizeX(), p.GetSizeY(), p.GetDrillSizeX()) for p in fp.Pads()))


def eagle_ref(ref: str) -> str:
    """kicad-cli appends '0' to references without a trailing digit; Eagle's names stay."""
    return ref[:-1] if ref.endswith("0") and not ref[:-1][-1:].isdigit() and ref[:-1] else ref


def main(board_path: Path, nickname: str, bom: Path | None = None) -> None:
    board = pcbnew.LoadBoard(str(board_path))
    sch = load_schematic(EAGLE_SCH)
    nc_names = unconnected_net_names()
    bom_fields = load_bom(bom) if bom else {}
    by_fp = {f["_footprint"]: f for f in bom_fields.values()}
    lib_dir = board_path.parent / f"{nickname}.pretty"
    lib_dir.mkdir(exist_ok=True)
    io = pcbnew.PCB_IO_KICAD_SEXPR()
    seen: dict[str, tuple] = {}
    written = 0
    for fp in sorted(board.Footprints(), key=lambda f: f.GetReference()):
        plated_slots(fp)
        name = fp.GetFPID().GetLibItemName().wx_str()
        sig = pad_signature(fp)
        if name in seen:
            if seen[name] != sig and not fp.IsFlipped():
                raise SystemExit(f"fp_export: two different footprints both named {name}")
        else:
            seen[name] = sig
            copy = pcbnew.FOOTPRINT(fp)  # copy constructor keeps the FOOTPRINT type
            if copy.IsFlipped():
                copy.Flip(copy.GetPosition(), False)
            copy.SetOrientationDegrees(0)
            copy.SetPosition(pcbnew.VECTOR2I(0, 0))
            copy.Reference().SetText("REF**")
            copy.Value().SetText(name)
            for pad in copy.Pads():
                pad.SetNetCode(0)
            copy.SetFPID(pcbnew.LIB_ID(nickname, name))
            attach_model(copy)
            io.FootprintSave(str(lib_dir), copy)
            written += 1
        fp.SetFPID(pcbnew.LIB_ID(nickname, name))
        attach_model(fp)
        ref = eagle_ref(fp.GetReference())
        if fp.GetReference().startswith("UNK_HOLE_"):
            # bare Eagle holes: board-only, nothing in the schematic or BOM corresponds
            fp.SetAttributes(fp.GetAttributes() | pcbnew.FP_BOARD_ONLY | pcbnew.FP_EXCLUDE_FROM_BOM | pcbnew.FP_EXCLUDE_FROM_POS_FILES)
        if ref in sch.parts:
            part = sch.parts[ref]
            fp.SetValue(part.value or part.deviceset)  # what the schematic symbol shows
            for pad in fp.Pads():
                nc = nc_names.get((ref, pad.GetNumber()))
                if nc and not pad.GetNetname():
                    net = board.FindNet(nc)
                    if net is None:
                        net = pcbnew.NETINFO_ITEM(board, nc)
                        board.Add(net)
                    pad.SetNet(net)
            fields = bom_fields.get(ref) or by_fp.get(name)
            if fields:
                for k in ("Manufacturer", "MPN", "Digi-Key_PN", "LCSC"):
                    fp.SetField(k, fields.get(k, ""))
                fp.SetField("Datasheet", DATASHEETS.get(fields.get("MPN", ""), fields.get("_link", "")))
                for fld in fp.GetFields():
                    if fld.GetName() not in ("Reference", "Value"):
                        fld.SetVisible(False)
    pcbnew.SaveBoard(str(board_path), board)
    stabilised = stabilise_board(board_path) + sum(stabilise(f) for f in sorted(lib_dir.glob('*.kicad_mod')))
    print(f'fp_export: stabilised uuids in the board and {len(list(lib_dir.glob("*.kicad_mod")))} footprints')
    proj = board_path.parent
    (proj / "fp-lib-table").write_text(
        "(fp_lib_table\n  (version 7)\n"
        f'  (lib (name "{nickname}")(type "KiCad")(uri "${{KIPRJMOD}}/{nickname}.pretty")(options "")(descr "Footprints imported from the Eagle board"))\n)\n')
    (proj / "sym-lib-table").write_text(
        "(sym_lib_table\n  (version 7)\n"
        f'  (lib (name "{nickname}")(type "KiCad")(uri "${{KIPRJMOD}}/{nickname}.kicad_sym")(options "")(descr "Symbols converted from the Eagle schematic"))\n)\n')
    print(f"fp_export: {written} footprints -> {lib_dir.name}; {len(list(board.Footprints()))} board footprints relinked to {nickname}:")


if __name__ == "__main__":
    main(Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3]) if len(sys.argv) > 3 else None)
