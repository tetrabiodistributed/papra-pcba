"""3D models for the Eagle-derived footprints.

Each entry: footprint name -> (model path, offset xyz in mm, rotation xyz in degrees), in
KiCad's footprint 3D frame (X right, Y *up*, Z out of the board; the file's pad Y is
negated). Standard parts use the models shipped with KiCad; parts KiCad has no model for
use manufacturer STEP files committed under 3d/ (sources in 3d/SOURCES.md).
"""
from __future__ import annotations

K = "${KICAD10_3DMODEL_DIR}"
P = "${KIPRJMOD}/3d"

MODELS: dict[str, tuple[str, tuple[float, float, float], tuple[float, float, float]]] = {
    # Eagle pads at x=+-5.08; KiCad model origin at pad 1 (x=0), pad 2 at +10.16.
    "0207_10": (f"{K}/Resistor_THT.3dshapes/R_Axial_DIN0207_L6.3mm_D2.5mm_P10.16mm_Horizontal.step", (-5.08, 0, 0), (0, 0, 0)),
    # Eagle A at -1.27, K at +1.27; KiCad pad 1 = K at origin, A at +2.54 -> rotate 180.
    "LED_3MM": (f"{K}/LED_THT.3dshapes/LED_D3.0mm.step", (1.27, 0, 0), (0, 0, 180)),
    # Eagle G/D/S at x=-2.54/0/+2.54, y=+2.54 (file frame); KiCad pins 1/2/3 at 0/2.54/5.08.
    "TO220BV": (f"{K}/Package_TO_SOT_THT.3dshapes/TO-220-3_Vertical.step", (-2.54, -2.54, 0), (0, 0, 0)),
    # Eagle TO92 triangle: 1(-1.27,0) 2(0,-1.905) 3(1.27,0); KiCad TO-92: 1(-1.27,0) 2(0,1.27) 3(1.27,0)
    # in the file frame, so pin 2 sits on the other side -> rotate 180 about the pin-1/3 axis.
    "TO92": (f"{K}/Package_TO_SOT_THT.3dshapes/TO-92.step", (0, 0, 0), (0, 0, 180)),
    # Eagle C at -5.08, A at +5.08; KiCad pad 1 = K at origin, A at +10.16.
    "DO41-10": (f"{K}/Diode_THT.3dshapes/D_DO-41_SOD81_P10.16mm_Horizontal.step", (-5.08, 0, 0), (0, 0, 0)),
    # Zener D2 (Tinkercad DIODE-AXIAL): pad 1 = A at -5.08, pad 2 = C at +5.08 -> rotate 180.
    "DIODE-AXIAL": (f"{K}/Diode_THT.3dshapes/D_DO-41_SOD81_P10.16mm_Horizontal.step", (5.08, 0, 0), (0, 0, 180)),
    # SparkFun kit footprint, pads at +-1.397 (2.79 pitch); 5 mm disc model on a 2.5 pitch.
    "CAP-PTH-SMALL-KIT": (f"{K}/Capacitor_THT.3dshapes/C_Disc_D5.0mm_W2.5mm_P2.50mm.step", (-1.25, 0, 0), (0, 0, 0)),
    # Eagle pad 1 (+) at +1.25; KiCad pad 1 (+) at origin, pad 2 at +2.5 -> rotate 180.
    "CPOL-RADIAL-2.5MM-6.5MM": (f"{K}/Capacitor_THT.3dshapes/CP_Radial_D6.3mm_P2.50mm.step", (1.25, 0, 0), (0, 0, 180)),
    # Eagle + at +3.81, - at -3.81 (7.62 pitch); KiCad pad 1 (+) at origin, pad 2 at +7.6.
    "F_TMB": (f"{K}/Buzzer_Beeper.3dshapes/Buzzer_12x9.5RM7.6.step", (3.81, 0, 0), (0, 0, 180)),
    # Wurth 696108003002 open 5x20 holder, pads at +-11.43; closest shipped model is 22.5 pitch.
    "FUSE": (f"{K}/Fuse.3dshapes/Fuseholder_Cylinder-5x20mm_Schurter_0031_8201_Horizontal_Open.step", (-11.43, 0, 0), (0, 0, 0)),
    # Manufacturer STEP files (see 3d/SOURCES.md). Rotation and offset solved by
    # checks/model_solve.py from the model geometry and the datasheet rules in
    # checks/parts.py PLACEMENT, with KiCad's own model transform (checks/model_geom.py);
    # checks/test_models.py holds every model to those rules.
    # TE tab (drawing C-63952): a flat strip, 25.4 along Z, 6.35 wide along Y, 0.8 thick along X,
    # legs off its long edge towards -Y. Seated on the back it stands on edge along the pad
    # row with the blade projecting past the board's top edge. Matches the placement set by
    # hand in the KiCad viewer to 0.05 mm.
    "TE63952-1": (f"{P}/TE_63952-1.step", (21.24, 0.4, 4.46), (90, 180, 90)),
    # TE BNC: height along Y (pins at -Y), mating axis along Z; barrel off the bottom edge.
    "TE-BNC": (f"{P}/TE_5227161-9.step", (21.0, 0.0, 6.92), (90, 180, 90)),
    # TT pot: height along X (pins at +X), shaft along +Y; shaft off the bottom edge.
    "P091S-FC20BR": (f"{P}/TT_P091S-FC20BR10K.step", (-1.33, -0.19, 6.69), (0, 270, 90)),
    # XIAO: long axis along X, height along Y; USB-C end towards the bottom edge.
    "MODULE14P-TH+PAD": (f"{P}/Seeed_XIAO-ESP32S3.step", (6.11, -2.57, 0.05), (90, 180, 90)),
    # Same Sky no longer publishes a PJ-066A model; the PJ-063AH is the same family and
    # envelope, so it stands in for mechanical checks. Flagged in 3d/SOURCES.md.
    # PJ-063AH pins run +Y from pin 1; ours run towards the board edge at y=0 (file frame).
    "DCJACK-PJ-066A-SLOT": (f"{K}/Connector_BarrelJack.3dshapes/BarrelJack_CUI_PJ-063AH_Horizontal.step", (0, 14.2, 0), (0, 0, 0)),
}
