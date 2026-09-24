# 3D model sources

Manufacturer STEP models for parts KiCad's own library does not cover. Mapped to
footprints in `checks/models.py`; offsets and rotations there were set by rendering the
board (`kicad-cli pcb render`) and checking against the silkscreen.

| File | Part | Source |
|---|---|---|
| `TE_63952-1.step` | TE Connectivity 63952-1 FASTON 6.35 mm PCB tab (BATT+, BATT-) | https://www.te.com/en/product-63952-1.html ("Customer View Model", STEP) |
| `TE_5227161-9.step` | TE Connectivity 5227161-9 right-angle PCB BNC jack (H2) | https://www.te.com/en/product-5227161-9.html ("Customer View Model", STEP) |
| `TT_P091S-FC20BR10K.step` | TT Electronics/BI P091S-FC20BR10K potentiometer with switch (POT1) | https://www.ttelectronics.com/products/passive-components/potentiometers/p091s/ |
| `Seeed_XIAO-ESP32S3.step` | Seeed Studio XIAO ESP32S3 (U1; Adafruit QT Py shares the footprint) | https://files.seeedstudio.com/wiki/SeeedStudio-XIAO-ESP32S3/res/seeed-studio-xiao-esp32s3-3d_model.zip |

Not available: Same Sky (CUI) no longer publishes a 3D model for the PJ-066A DC jack
(H1); their model page reports it does not exist. KiCad's bundled PJ-063AH model, the
same family and envelope, stands in for mechanical checks. Replace it in
`checks/models.py` if a PJ-066A model turns up.

All other parts use models shipped with KiCad 10 (`${KICAD10_3DMODEL_DIR}`).
