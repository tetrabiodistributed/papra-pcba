"""Look up LCSC part numbers for the BOM's manufacturer part numbers through JLCPCB's
public parts search, and write them to a small CSV the schematic converter reads.

Usage: python -m checks.lcsc_lookup <bom.csv> <lcsc-parts.csv>

Only exact MPN matches are recorded; anything else is left blank for a human to pick.
Network access is needed; the output CSV is committed so `make import` stays offline.
"""
from __future__ import annotations

import csv
import json
import sys
import time
import urllib.request
from pathlib import Path

from .sch_convert import load_bom

URL = "https://jlcpcb.com/api/overseas-pcb-order/v1/shoppingCart/smtGood/selectSmtComponentList"


def search(keyword: str) -> list[dict]:
    body = json.dumps({"currentPage": 1, "pageSize": 10, "keyword": keyword, "searchSource": "search",
                       "firstSortName": "", "secondSortName": "", "componentBrand": "",
                       "componentSpecification": "", "componentAttributes": [], "stockFlag": False,
                       "stockSort": None, "componentLibraryType": "", "preferredComponentFlag": False}).encode()
    req = urllib.request.Request(URL, data=body, headers={"Content-Type": "application/json",
                                                          "User-Agent": "Mozilla/5.0 (papra-pcba lcsc_lookup)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.load(r)
    return data.get("data", {}).get("componentPageInfo", {}).get("list", []) or []


def lcsc_code(item: dict) -> str:
    code = item.get("componentCode") or ""
    return code if code.startswith("C") else ""


def main(bom: Path, out: Path) -> None:
    fields = load_bom(bom)
    rows = []
    seen: dict[str, tuple[str, str]] = {}
    for desig, f in sorted(fields.items()):
        mpn = f["MPN"]
        if not mpn:
            rows.append((desig, "", "", "no MPN in BOM")); continue
        if mpn not in seen:
            hits = search(mpn)
            exact = [h for h in hits if (h.get("componentModelEn") or "").upper() == mpn.upper()]
            if exact:
                h = exact[0]
                seen[mpn] = (lcsc_code(h), f"{h.get('componentBrandEn','')}; {h.get('componentLibraryType','')} part, stock {h.get('stockCount')}")
            else:
                seen[mpn] = ("", f"no exact match ({len(hits)} hits)")
            time.sleep(0.5)
        rows.append((desig, mpn, *seen[mpn]))
        print(f"{desig:8} {mpn:28} {seen[mpn][0]:12} {seen[mpn][1]}")
    with out.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["Designator", "MPN", "LCSC", "Note"])
        w.writerows(rows)


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
