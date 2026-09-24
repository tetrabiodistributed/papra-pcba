# PAPRa PCBA: reproducible toolchain + Eagle -> KiCad migration checks.
#
#   make setup     install pinned uv, Python, deps, kistack submodule, KiCad (all project-local)
#   make import    regenerate the KiCad project from the Eagle sources (board, schematic, libs)
#   make check     run every validation (Eagle vs KiCad structure, ERC, DRC, Gerber diff)
#   make outputs   ERC/DRC reports, Gerbers, drill, BOM, PDFs, renders into build/
#
# Nothing here assumes uv, Python, KiCad or Docker on the host. See scripts/versions.env
# for the pins. Override KICAD_CLI=... to point at another KiCad (e.g. in CI's container).

SHELL := /bin/bash
.DEFAULT_GOAL := help
.DELETE_ON_ERROR:

ROOT  := $(abspath .)
TOOLS := $(ROOT)/tools
UV    := $(TOOLS)/bin/uv
VENV  := $(ROOT)/.venv
VENV_STAMP := $(VENV)/.stamp
PYTHON := $(VENV)/bin/python

# Keep everything uv does inside the repo: cache, managed Pythons, the venv.
export UV_CACHE_DIR          := $(TOOLS)/cache/uv
export UV_PYTHON_INSTALL_DIR := $(TOOLS)/python
export UV_PYTHON_PREFERENCE  := only-managed
export UV_PROJECT_ENVIRONMENT := $(VENV)

ifeq ($(shell uname -s),Darwin)
KICAD_APP  := $(TOOLS)/KiCad/KiCad.app
KICAD_CLI  ?= $(KICAD_APP)/Contents/MacOS/kicad-cli
# KiCad's bundled Python carries the pcbnew module (needed for the footprint export).
KICAD_PY   ?= $(KICAD_APP)/Contents/Frameworks/Python.framework/Versions/Current/bin/python3
else
KICAD_CLI  ?= kicad-cli
KICAD_PY   ?= python3
endif
export KICAD_CLI KICAD_PY

# ---- the board under migration ------------------------------------------------
PART      := p-tet-000166
PCB_DIR   := components/a-tet-001113/components/$(PART)
EAGLE_SCH := $(PCB_DIR)/src/Papra TH_eagle.sch
EAGLE_BRD := $(PCB_DIR)/src/Papra TH_eagle.brd
EAGLE_GERBERS_ZIP := $(PCB_DIR)/dist/Papra TH_eagle_2023-03-08.zip
KICAD_DIR := $(PCB_DIR)/src/papra-pcb-th
KICAD_PRO := $(KICAD_DIR)/papra-pcb-th.kicad_pro
KICAD_PCB := $(KICAD_DIR)/papra-pcb-th.kicad_pcb
KICAD_SCH := $(KICAD_DIR)/papra-pcb-th.kicad_sch
LIB_NICK  := papra-pcb-th
BOM_CSV   := components/a-tet-001113/Papra TH v1.0_bom.csv
BUILD     := build/$(PART)
export EAGLE_SCH EAGLE_BRD EAGLE_GERBERS_ZIP KICAD_PRO KICAD_PCB KICAD_SCH BUILD

.PHONY: help setup deps kicad submodules lock import import-pcb import-sch \
        check erc drc outputs lcsc clean distclean

help:
	@sed -n '2,10p' Makefile | sed 's/^# \{0,1\}//'

# ---- toolchain ----------------------------------------------------------------
setup: deps kicad

deps: submodules $(VENV_STAMP)

submodules:
	git submodule update --init --recursive

$(UV): scripts/install-uv.sh scripts/lib.sh scripts/versions.env
	scripts/install-uv.sh

uv.lock: pyproject.toml | $(UV)
	$(UV) lock

lock: | $(UV)
	$(UV) lock --upgrade

$(VENV_STAMP): uv.lock pyproject.toml .python-version | $(UV)
	$(UV) sync --frozen
	touch $@

open: kicad  ## open the project in the pinned KiCad
	open -a $(KICAD_APP) "$(KICAD_PRO)"

kicad: $(KICAD_CLI)

ifeq ($(shell uname -s),Darwin)
$(KICAD_CLI): scripts/install-kicad.sh scripts/lib.sh scripts/versions.env
	scripts/install-kicad.sh
else
$(KICAD_CLI):
	@command -v $(KICAD_CLI) >/dev/null || { echo "kicad-cli not found; on Linux run inside $$(grep KICAD_IMAGE scripts/versions.env | cut -d= -f2)"; exit 1; }
endif

# ---- migration ----------------------------------------------------------------
# Everything under $(KICAD_DIR) is generated from the two Eagle files by these steps.
# Re-run `make import` after touching the Eagle sources or any checks/*.py converter.
import: import-pcb import-sch

# 1. kicad-cli converts the board.  2. postimport maps the Eagle layers kicad-cli
# leaves undefined.  3. project writes .kicad_pro/.kicad_dru from Eagle's design rules.
# 4. fp_export moves the embedded footprints into $(LIB_NICK).pretty and relinks them.
import-pcb: kicad $(VENV_STAMP)
	mkdir -p "$(KICAD_DIR)" "$(BUILD)"
	$(KICAD_CLI) pcb import --format eagle \
	    --report-format text --report-file "$(BUILD)/import-pcb.txt" \
	    -o "$(KICAD_PCB)" "$(EAGLE_BRD)"
	$(PYTHON) -m checks.postimport "$(KICAD_PCB)"
	$(PYTHON) -m checks.project "$(EAGLE_BRD)" "$(KICAD_PRO)"
	$(KICAD_PY) -m checks.fp_export "$(KICAD_PCB)" $(LIB_NICK) "$(BOM_CSV)"
	@cat "$(BUILD)/import-pcb.txt"

# kicad-cli has no schematic importer, so checks/sch_convert.py does the conversion and
# also writes $(LIB_NICK).kicad_sym next to the schematic.
import-sch: $(VENV_STAMP) kicad
	mkdir -p "$(KICAD_DIR)"
	$(PYTHON) -m checks.sch_convert "$(EAGLE_SCH)" "$(KICAD_SCH)" $(LIB_NICK) $(LIB_NICK) "$(BOM_CSV)"
	$(KICAD_CLI) sym upgrade --force "$(KICAD_DIR)/$(LIB_NICK).kicad_sym"
	$(KICAD_CLI) sch upgrade --force "$(KICAD_SCH)"

# ---- validation ---------------------------------------------------------------
check: deps kicad
	$(PYTHON) -m pytest

erc: kicad
	mkdir -p "$(BUILD)"
	$(KICAD_CLI) sch erc --output "$(BUILD)/erc.rpt" --format report --units mm \
	    --severity-warning --severity-error --exit-code-violations "$(KICAD_SCH)"

# Full report with warnings for humans; the gate fails on errors only (Eagle never
# checked silkscreen, so those stay warnings).
drc: kicad
	mkdir -p "$(BUILD)"
	$(KICAD_CLI) pcb drc --output "$(BUILD)/drc-full.rpt" --format report --units mm \
	    --severity-warning --severity-error --refill-zones --schematic-parity "$(KICAD_PCB)"
	$(KICAD_CLI) pcb drc --output "$(BUILD)/drc.rpt" --format json --units mm \
	    --severity-error --refill-zones --schematic-parity \
	    --exit-code-violations "$(KICAD_PCB)"

outputs: deps kicad
	$(PYTHON) -m checks.outputs

# Refresh LCSC part numbers for the BOM (network access; result is committed).
lcsc: deps
	$(PYTHON) -m checks.lcsc_lookup "components/a-tet-001113/Papra TH v1.0_bom.csv" components/a-tet-001113/lcsc-parts.csv

# ---- housekeeping -------------------------------------------------------------
clean:
	rm -rf build

distclean: clean
	rm -rf "$(TOOLS)" "$(VENV)"
