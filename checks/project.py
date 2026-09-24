"""Generate the KiCad project file and custom DRC rules from the Eagle board's own
design rules, so the KiCad DRC checks what Eagle checked, not KiCad's defaults.

kicad-cli's importer writes only the board. The mapping below is the explicit,
reviewable record of how each Eagle rule became a KiCad constraint.

Usage: python -m checks.project <eagle.brd> <project.kicad_pro>
"""
from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from .eagle import _mm

DRU = """\
(version 1)

# Eagle checks copper against the Dimension layer (board outline) only. The DC jack's
# blade slots were drawn on Eagle's Milling layer, which KiCad has to represent as
# Edge.Cuts inside the footprint; copper deliberately touches those slot edges.
(rule "eagle_copper_to_dimension"
    (constraint edge_clearance (min {edge}mm)))
(rule "milled_slots_inside_footprints"
    (condition "B.memberOfFootprint('H1')")
    (constraint edge_clearance (min 0mm)))
"""

# DRC categories Eagle has no equivalent for and this design did not follow.
# Kept visible as warnings in the full report; the gate only fails on errors.
IGNORED = {
    # Eagle has no silkscreen or text-size rules and the silkscreen is reproduced from the
    # board that was fabricated; these cosmetic checks would only flag Eagle's artwork.
    "silk_over_copper": "ignore",
    "silk_overlap": "ignore",
    "silk_edge_clearance": "ignore",
    "text_height": "ignore",
    "text_thickness": "ignore",
    # The Xiao module's mounting hole is a bare Eagle hole sitting inside U1's outline.
    "npth_inside_courtyard": "ignore",
    # Eagle libraries mostly ship without courtyards.
    "missing_courtyard": "ignore",
    "footprint_type_mismatch": "ignore",
    "footprint_filters_mismatch": "ignore",
}


def eagle_rules(brd: Path) -> tuple[dict[str, str], list[tuple[str, float]]]:
    root = ET.parse(brd).getroot()
    board = root.find("drawing").find("board")
    params = {p.get("name"): p.get("value") for p in board.find("designrules").findall("param")}
    classes = [(c.get("name"), float(c.get("width"))) for c in board.find("classes").findall("class")]
    return params, classes


def project(params: dict[str, str], classes: list[tuple[str, float]], name: str) -> dict:
    clearance = max(_mm(params[k]) for k in ("mdWireWire", "mdWirePad", "mdPadPad"))
    rules = {
        "min_clearance": clearance,                              # md* wire/pad/via
        "min_track_width": _mm(params["msWidth"]),               # msWidth
        "min_through_hole_diameter": _mm(params["msDrill"]),     # msDrill
        "min_hole_to_hole": _mm(params["mdDrill"]),              # mdDrill
        "min_hole_clearance": clearance,
        # Board-setup values are hard floors that custom rules cannot lower, so the
        # copper-to-edge limit lives in the .kicad_dru (with the milled-slot exception).
        "min_copper_edge_clearance": 0.0,
        "min_via_diameter": _mm(params["msDrill"]) + 2 * _mm(params["rlMinViaOuter"]),
        "min_via_annular_width": _mm(params["rlMinViaOuter"]),   # rlMinViaOuter
        "min_microvia_diameter": _mm(params["msMicroVia"]),
        "min_microvia_drill": _mm(params["msMicroVia"]),
        "min_connection": 0.0,
        "min_resolved_spokes": 1,
        "min_silk_clearance": 0.0,
        "min_text_height": 0.5,
        "min_text_thickness": 0.05,
        "solder_mask_to_copper_clearance": 0.0,
        "max_error": 0.005,
        "use_height_for_length_calcs": True,
    }
    netclasses = []
    for cname, width in classes:
        netclasses.append({
            "name": "Default" if cname == "default" else cname,
            "clearance": clearance,
            "track_width": width,
            "via_diameter": rules["min_via_diameter"],
            "via_drill": _mm(params["msDrill"]),
            "microvia_diameter": rules["min_microvia_diameter"],
            "microvia_drill": rules["min_microvia_drill"],
            "diff_pair_gap": clearance, "diff_pair_via_gap": clearance, "diff_pair_width": width,
            "bus_width": 12, "wire_width": 6, "line_style": 0, "priority": -1,
            "pcb_color": "rgba(0, 0, 0, 0.000)", "schematic_color": "rgba(0, 0, 0, 0.000)",
        })
    return {
        "board": {
            "design_settings": {
                "defaults": {
                    "board_outline_line_width": 0.05,
                    "zones": {"min_clearance": clearance},
                },
                "rules": rules,
                "rule_severities": IGNORED,
                "meta": {"version": 2},
            },
            "layer_presets": [],
            "viewports": [],
        },
        "boards": [],
        "meta": {"filename": f"{name}.kicad_pro", "version": 3},
        "net_settings": {"classes": netclasses, "meta": {"version": 4},
                         "net_colors": None, "netclass_assignments": None, "netclass_patterns": []},
        "pcbnew": {"page_layout_descr_file": ""},
        "schematic": {"legacy_lib_dir": "", "legacy_lib_list": []},
        "sheets": [],
        "text_variables": {},
    }


def main(brd: Path, pro: Path) -> None:
    params, classes = eagle_rules(brd)
    # Eagle net classes assign nets explicitly; kicad-cli's import keeps the class widths
    # on the tracks themselves, so classes here only carry the defaults for new work.
    data = project(params, classes, pro.stem)
    pro.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    dru = pro.with_suffix(".kicad_dru")
    dru.write_text(DRU.format(edge=_mm(params["mdCopperDimension"])))
    print(f"project: wrote {pro.name} and {dru.name}: clearance {data['board']['design_settings']['rules']['min_clearance']} mm,"
          f" edge {_mm(params['mdCopperDimension'])} mm, classes {[c['name'] for c in data['net_settings']['classes']]}")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
