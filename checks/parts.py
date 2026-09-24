"""Per-part facts that are not in the Eagle files: datasheet links and pin electrical
types from the datasheets. Keyed by Eagle deviceset name (pins) and by designator or
MPN (datasheets). Anything not listed keeps Eagle's pin direction and gets the BOM's
Digi-Key product page as its datasheet link.
"""

# Eagle deviceset -> {pin name: KiCad electrical type}; "*" is the default for the rest.
PIN_TYPES: dict[str, dict[str, str]] = {
    # TI UA78L05: pin 1 output, 2 common, 3 input (TO-92 LP package)
    "78*": {"VI": "power_in", "GND": "power_in", "VO": "power_out"},
    # Seeed XIAO ESP32S3 / Adafruit QT Py ESP32-S3: 3V3 is the on-board regulator output,
    # 5V is the USB/VIN rail (fed by REG on this board), GND return, D0-D10 GPIO.
    "MOUDLE-SEEEDUINO-XIAO": {"3V3": "power_out", "5V": "power_in", "GND": "power_in", "*": "bidirectional"},
    # MOSFETs (Infineon IPP040N06NF2S, Goford G75P04FI): gate is an input, D/S passive.
    "NMOSFET": {"G": "input"},
    "PMOSFET": {"G": "input"},
}

# Datasheet links, verified reachable when added. Keyed by MPN, fallback by designator.
DATASHEETS: dict[str, str] = {
    "UA78L05ACLPME3": "https://www.ti.com/lit/ds/symlink/ua78l.pdf",
    "696108003002": "https://www.we-online.com/components/products/datasheet/696108003002.pdf",
    "CMI-1210-92T": "https://www.sameskydevices.com/product/resource/cmi-1210-92t.pdf",
    "PJ-066A": "https://www.sameskydevices.com/product/resource/pj-066x.pdf",
    "P091S-FC20BR10K": "https://www.ttelectronics.com/TTElectronics/media/ProductFiles/Datasheet/P09x.pdf",
    "5325": "https://learn.adafruit.com/adafruit-qt-py-esp32-s3",
    "G75P04FI": "https://www.gofordsemi.com/Upload/2024/05/d3e2d4ae7c5049f79f3567f858d60867.pdf",
    "IPP040N06NF2SAKMA1": "https://www.infineon.com/dgdl/Infineon-IPP040N06NF2S-DataSheet-v02_02-EN.pdf?fileId=8ac78c8c80f4d3290180fd60c2843c86",
    "1N5240BTR": "https://www.onsemi.com/pdf/datasheet/1n5221b-d.pdf",
    "63952-1": "https://www.te.com/commerce/DocumentDelivery/DDEController?Action=srchrtrv&DocNm=63952&DocType=Customer%20Drawing&DocLang=English&DocFormat=pdf&PartCntxt=63952-1",
    "5227161-9": "https://www.te.com/commerce/DocumentDelivery/DDEController?Action=srchrtrv&DocNm=5175473&DocType=Customer%20Drawing&DocLang=English&DocFormat=pdf&PartCntxt=5227161-9",
}

# The CUI PJ-066A footprint from Eagle emulates plated slots with SMD pads on both sides,
# through-hole pads at the slot ends and milled slots on the Milling layer. KiCad models the
# same thing as one plated oval pad per blade (the CUI drawing calls for 0.8 x 3.0 mm slots),
# which is what the fab makes anyway and lets DRC reason about it.
#   pad kept -> (pads folded into it, slot centre (footprint x, y), slot length axis)
SLOT_PADS: dict[str, dict[str, tuple[list[str], tuple[float, float], str]]] = {
    "DCJACK-PJ-066A-SLOT": {
        "GND": (["GND$1", "GND$2", "GND$3"], (0.0, -8.1), "x"),
        "GNDBREAK": (["GNDBREAK$1", "GNDBREAK$2", "GNDBREAK$3"], (4.8, -11.2), "y"),
        "PWR": (["PWR$1", "PWR$2", "PWR$3"], (0.0, -14.2), "x"),
    },
}
SLOT_DRILL = (3.2, 1.1)   # slot length x width, mm (0.8 x 3.0 blade + clearance)
SLOT_COPPER = (4.0, 1.9)  # copper around the slot
# Eagle deviceset -> {folded pad: kept pad}, derived from SLOT_PADS for the schematic side.
PAD_MERGE: dict[str, dict[str, str]] = {
    "CUI-PJ-066A": {old: new for new, (olds, _c, _a) in SLOT_PADS["DCJACK-PJ-066A-SLOT"].items() for old in olds},
}


# QR code on the bottom silkscreen, placed by checks/postimport.py in the largest area
# with no holes, pads or other silkscreen. Mirrored so it scans from the bottom side.
QR_TEXT = "https://tetrab.io"
QR_MODULE_MM = 0.30        # silkscreen module size; 21 modules + quiet zone need a 7.5 mm clear square
QR_QUIET_MODULES = 2       # quiet zone kept clear around the code

# 3D placement rules from the datasheets (checks/test_models.py; solved by checks/model_solve.py).
# Board frame: x right, y up, z out of the front; z=0 is the top surface, the board is 1.6 mm.
# "height": body reach from the seating surface on the part's own side; "pins": reach past
# the seating surface into/through the board; "end_width": width of the material at the end
# furthest from the board (tells the tab's tip from its legs); "base": minimum x/y span of the
# material within 1.3 mm of the seat (a module sits on its own PCB); "top_y": where the
# material more than 3.5 mm up sits (a module's USB connector); "x"/"y": allowed extent;
# "reach_y": where the part's far y extreme must land (a blade projecting past an edge).
PLACEMENT: dict[str, dict] = {
    # TT P091S side-adjust: body 11.35 tall, 9.5 wide over the pin row, pins 3.5, shaft parallel
    # to the board pointing off the bottom edge.
    "POT1": {"height": (10.8, 11.9), "pins": (3.0, 4.0), "x": (-23.5, -11.5), "y": (-70, -29)},
    # TE 5227161-9 right-angle BNC: 13.18 tall, 14.76 across, pins 4.11, barrel off the bottom edge.
    "H2": {"height": (12.6, 13.8), "pins": (3.6, 4.6), "x": (6.0, 24.0), "y": (-70, -28)},
    # TE 63952-1 FASTON tab on the back (drawing C-63952): a flat 25.4 x 6.35 x 0.8 strip whose
    # two 3.81 legs come off its long edge, 5.08 apart, in the same plane. Seated, the blade
    # stands on edge along the pad row (y), 7.62 below the bottom face (the leg-end base is
    # 1.27 wider), and projects past the board's top edge for the battery lead to slide on.
    "BATT+0": {"height": (7.3, 7.9), "pins": (3.5, 4.1), "x": (-7.2, -6.0), "y": (10.0, 40.0), "reach_y": (30.0, 40.0)},
    "BATT-0": {"height": (7.3, 7.9), "pins": (3.5, 4.1), "x": (6.0, 7.2), "y": (10.0, 40.0), "reach_y": (30.0, 40.0)},
    # Same Sky PJ-066A DC jack, drawn with KiCad's PJ-063AH model as a stand-in (3d/SOURCES.md):
    # same family and envelope, but its two plastic mounting pegs have no holes in the PJ-066A
    # footprint, so its pin material is allowed to miss the pads by that much.
    "H1": {"height": (8.5, 9.5), "pins": (2.5, 3.5), "x": (-5.5, 5.5), "y": (5.5, 20.0), "pin_tol": 5.5},
    # Seeed XIAO ESP32S3 soldered flat: 17.8 x 21 module, parts up, castellations on the pad rows,
    # USB-C (the tallest part, 3.2 over the module) at the board-edge end as the Eagle silk outline shows.
    "U1": {"height": (2.5, 6.5), "pins": (-0.1, 0.5), "base": (17.0, 20.0), "top_y": (-46.0, -36.0),
           "x": (-12.5, 7.5), "y": (-47.5, -22.0)},
}
