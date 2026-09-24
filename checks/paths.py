"""Where the design files live. The Makefile exports these; defaults match it so
`pytest` also works from an activated venv without make."""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PCB_DIR = ROOT / "components/a-tet-001113/components/p-tet-000166"


def _env(name: str, default: Path) -> Path:
    v = os.environ.get(name)
    return (ROOT / v).resolve() if v else default


EAGLE_SCH = _env("EAGLE_SCH", PCB_DIR / "src/Papra TH_eagle.sch")
EAGLE_BRD = _env("EAGLE_BRD", PCB_DIR / "src/Papra TH_eagle.brd")
EAGLE_GERBERS_ZIP = _env("EAGLE_GERBERS_ZIP", PCB_DIR / "dist/Papra TH_eagle_2023-03-08.zip")
KICAD_PRO = _env("KICAD_PRO", PCB_DIR / "src/papra-pcb-th/papra-pcb-th.kicad_pro")
KICAD_PCB = _env("KICAD_PCB", PCB_DIR / "src/papra-pcb-th/papra-pcb-th.kicad_pcb")
KICAD_SCH = _env("KICAD_SCH", PCB_DIR / "src/papra-pcb-th/papra-pcb-th.kicad_sch")
BUILD = _env("BUILD", ROOT / "build/p-tet-000166")


def kicad_cli() -> str:
    """Path to kicad-cli: $KICAD_CLI, else the project-local install, else PATH."""
    env = os.environ.get("KICAD_CLI")
    if env:
        return env
    local = ROOT / "tools/KiCad/KiCad.app/Contents/MacOS/kicad-cli"
    if local.exists():
        return str(local)
    found = shutil.which("kicad-cli")
    if found:
        return found
    raise FileNotFoundError("kicad-cli not found; run `make kicad` or set KICAD_CLI")


def run_kicad_cli(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run([kicad_cli(), *args], text=True, capture_output=True, check=check)
