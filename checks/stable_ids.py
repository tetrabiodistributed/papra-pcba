"""Deterministic UUIDs for generated KiCad files.

kicad-cli's importer and pcbnew's footprint writer mint random UUIDs on every run, which
turns a re-import of unchanged sources into thousands of spurious diffs. Every UUID in a
generated file is renamed to a UUID5 of its ordinal of first appearance, so identical
input gives an identical file, and references between elements (groups, net ties) stay
consistent because the mapping is by value.

Standard library only: this also runs under KiCad's bundled Python.
"""
from __future__ import annotations

import re
import uuid
from pathlib import Path

NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "https://github.com/tetrabiodistributed/papra-pcba")
UUID_RE = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")


def stabilise_text(text: str, scope: str) -> str:
    mapping: dict[str, str] = {}

    def replace(m: re.Match) -> str:
        old = m.group(0)
        if old not in mapping:
            mapping[old] = str(uuid.uuid5(NAMESPACE, f"{scope}:{len(mapping)}"))
        return mapping[old]

    return UUID_RE.sub(replace, text)


def stabilise(path: Path, scope: str | None = None) -> int:
    """Rewrite the file in place; returns the number of distinct UUIDs renamed."""
    text = path.read_text()
    new = stabilise_text(text, scope or path.name)
    if new != text:
        path.write_text(new)
    return len(set(UUID_RE.findall(text)))


if __name__ == "__main__":
    import sys
    for arg in sys.argv[1:]:
        print(arg, stabilise(Path(arg)))


BLOCK_RE = re.compile(r"^\t\((\w+)\b.*?^\t\)\n", re.M | re.S)
REF_RE = re.compile(r'\(property "Reference" "([^"]*)"')


def sort_blocks(text: str) -> str:
    """pcbnew writes footprints, tracks and vias in memory order; sort each run of
    same-kind top-level blocks by content (UUIDs blanked, footprints by reference first)."""
    out, pos = [], 0
    run: list[tuple[str, str]] = []

    def flush():
        if run:
            out.extend(b for _, b in sorted(run, key=lambda kb: (REF_RE.search(kb[1]).group(1) if REF_RE.search(kb[1]) else "",
                                                                 UUID_RE.sub("", kb[1]))))
            run.clear()

    for m in BLOCK_RE.finditer(text):
        if m.start() != pos:
            flush()
            out.append(text[pos:m.start()])
        if run and run[-1][0] != m.group(1):
            flush()
        run.append((m.group(1), m.group(0)))
        pos = m.end()
    flush()
    out.append(text[pos:])
    return "".join(out)


def stabilise_board(path: Path) -> int:
    text = path.read_text()
    new = stabilise_text(sort_blocks(text), path.name)
    if new != text:
        path.write_text(new)
    return len(set(UUID_RE.findall(text)))
