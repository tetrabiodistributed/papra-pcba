"""Known, accepted differences between the Eagle sources and the KiCad import.
Every entry here is a deliberate decision; the tests fail on anything not listed."""

# KiCad requires reference designators to end in a number for annotation. Its Eagle
# importer appends "0" to the ones that don't. The Eagle names were net-like test-point
# and connector names, so this is cosmetic, but the BOM (Papra TH v1.0_bom.csv) still
# uses the Eagle spelling. Map KiCad ref -> Eagle ref.
# KiCad treats a reference without a trailing digit as unannotated; kicad-cli's importer
# and checks/sch_convert.py both append "0" to Eagle's few such names. KiCad ref -> Eagle.
REF_RENAMES = {"GND0": "GND", "+5V0": "+5V", "REG0": "REG", "BATT+0": "BATT+", "BATT-0": "BATT-"}

# Bare drill holes in Eagle become nameless placeholder footprints in KiCad.
HOLE_REF_PREFIX = "UNK_HOLE_"

# Geometry tolerance in mm for positions and sizes (Eagle stores 4 decimals).
TOL_MM = 0.001

# Eagle emulated the DC jack's plated slots with several pads per blade; KiCad gets one
# oval plated pad per blade (see checks/parts.py SLOT_PADS). Eagle pad -> KiCad pad.
from .parts import PAD_MERGE  # noqa: E402
MERGED_PADS = {ref: PAD_MERGE["CUI-PJ-066A"] for ref in ("H1",)}


def kicad_pad(ref: str, pad: str) -> str:
    return MERGED_PADS.get(ref, {}).get(pad, pad)
