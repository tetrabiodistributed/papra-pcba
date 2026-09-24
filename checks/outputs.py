"""Deterministic fabrication/documentation outputs (kistack export skill), into build/.

Run with `make outputs`. Fails on ERC/DRC errors; warnings are kept in the reports.
"""
from __future__ import annotations

import json
import shutil
import sys

from .gerbers import filled_board
from .paths import BUILD, KICAD_PCB, KICAD_SCH, run_kicad_cli

LAYERS = "F.Cu,B.Cu,F.Mask,B.Mask,F.SilkS,B.SilkS,F.Paste,B.Paste,Edge.Cuts"


def main() -> int:
    out = BUILD / "outputs"
    if out.exists():
        shutil.rmtree(out)
    (out / "gerbers").mkdir(parents=True)
    print("kicad-cli", run_kicad_cli("version").stdout.strip())

    run_kicad_cli("sch", "erc", "--output", str(out / "erc.rpt"), "--format", "report", "--units", "mm",
                  "--severity-warning", "--severity-error", str(KICAD_SCH))
    erc = run_kicad_cli("sch", "erc", "--output", str(out / "erc.json"), "--format", "json",
                        "--severity-error", "--exit-code-violations", str(KICAD_SCH), check=False)
    run_kicad_cli("pcb", "drc", "--output", str(out / "drc.rpt"), "--format", "report", "--units", "mm",
                  "--severity-warning", "--severity-error", "--refill-zones", "--schematic-parity", str(KICAD_PCB))
    drc = run_kicad_cli("pcb", "drc", "--output", str(out / "drc.json"), "--format", "json", "--units", "mm",
                        "--severity-error", "--refill-zones", "--schematic-parity", "--exit-code-violations",
                        str(KICAD_PCB), check=False)

    run_kicad_cli("sch", "export", "pdf", "--output", str(out / "schematic.pdf"), str(KICAD_SCH))
    run_kicad_cli("sch", "export", "svg", "--output", str(out / "schematic-svg"), str(KICAD_SCH))
    run_kicad_cli("sch", "export", "netlist", "--format", "kicadsexpr", "--output", str(out / "netlist.net"), str(KICAD_SCH))
    run_kicad_cli("sch", "export", "bom", "--output", str(out / "bom.csv"),
                  "--fields", "Reference,Value,Footprint,Manufacturer,MPN,Digi-Key_PN,LCSC,${QUANTITY}",
                  "--labels", "Reference,Value,Footprint,Manufacturer,MPN,Digi-Key PN,LCSC,Qty",
                  "--group-by", "Value,Footprint,MPN", "--sort-field", "Reference", str(KICAD_SCH))
    run_kicad_cli("sch", "export", "bom", "--output", str(out / "bom_JLCPCB.csv"),
                  "--fields", "Value,Reference,Footprint,LCSC", "--labels", "Comment,Designator,Footprint,LCSC",
                  "--group-by", "Value,Footprint,LCSC", str(KICAD_SCH))

    board = filled_board()
    run_kicad_cli("pcb", "export", "gerbers", "--output", str(out / "gerbers") + "/", "--layers", LAYERS,
                  "--subtract-soldermask", "--precision", "6", str(board))
    run_kicad_cli("pcb", "export", "drill", "--output", str(out / "gerbers") + "/", "--format", "excellon",
                  "--drill-origin", "absolute", "--excellon-units", "mm", "--excellon-zeros-format", "decimal",
                  "--excellon-separate-th", str(board))
    run_kicad_cli("pcb", "export", "pos", "--output", str(out / "positions.csv"), "--format", "csv", "--units", "mm",
                  "--side", "both", str(board))
    run_kicad_cli("pcb", "export", "pdf", "--output", str(out / "pcb-layers.pdf"), "--layers", LAYERS,
                  "--include-border-title", "--mode-multipage", str(board))
    run_kicad_cli("pcb", "export", "step", "--output", str(out / "board.step"), "--force", "--subst-models", str(board))
    for side in ("top", "bottom"):
        run_kicad_cli("pcb", "render", "--output", str(out / f"render-{side}.png"), "--width", "1600", "--height", "1200",
                      "--background", "opaque", "--quality", "basic", "--side", side, str(board))
    shutil.make_archive(str(out / "gerbers"), "zip", out / "gerbers")

    problems = []
    for name, res in (("ERC", erc), ("DRC", drc)):
        if res.returncode != 0:
            problems.append(f"{name}: errors, see {out}/{name.lower()}.rpt")
    for line in problems:
        print("FAILURE", line)
    print(f"outputs in {out}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
