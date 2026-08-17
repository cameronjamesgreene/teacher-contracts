#!/usr/bin/env python3
"""Draw a stratified sample of salary tables and build a hand-review packet.

## Why a sample rather than a sweep

Salary extraction has no human-verified ground truth. Five pages have been checked by eye;
everything else rests on an Apple Vision cross-read whose usefulness is itself unproven -
on pages known to be byte-perfect it scores between 0.705 and 0.955, so no threshold
separates right from wrong.

So the first question is not "what is the accuracy" but **"is the Vision agreement score
informative?"** If low-agreement tables really are the wrong ones, the score becomes a free
corpus-wide proxy and hand-checking is only ever needed for a small confirmatory sample. If
it is not, we know to stop reporting it. That question is answerable with ~24 tables instead
of hundreds, which is why the sample is stratified BY AGREEMENT BAND rather than drawn at
random.

## The bands

    A_high          agreement >= 0.90    Vision says these are fine
    B_mid           0.70 - 0.90          the ambiguous middle
    C_low           < 0.70               Vision says these are wrong
    D_unverifiable  no usable Vision read, or extracted by the legacy image path

D matters most in the long run: those tables (Pittsburgh, Cleveland, Fresno) cannot be
verified mechanically at all, because their pages are printed sideways or their coordinates
are untrustworthy. Hand review is the only instrument that reaches them.

Larger tables are preferred within each band - a 500-cell table costs the same glance as a
30-cell one and settles far more. No more than two tables per document per band, so one
contract cannot dominate a stratum.

Two tables already verified by eye are included unlabelled, as a consistency check on the
reviewer against the earlier verdicts.
"""

from __future__ import annotations

import argparse
import csv
import random
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils import OUT_DIR, PDF_ROOT, WORK

REVIEW = WORK / "review"
PER_BAND = 6
MIN_CELLS = 20
MAX_PER_DOC_PER_BAND = 2
RENDER_DPI = 130
# Verified by eye earlier in the rebuild; included blind as reviewer controls.
CONTROLS = {("ATF-Negotiated-Agreement_2018-19.pdf", "72"),
            ("SD_of_Philadelphia_2021-2024.pdf", "157")}


def band_of(table: dict) -> str:
    if table["agreement"] is None or table["method"].startswith("legacy"):
        return "D_unverifiable"
    if table["agreement"] >= 0.90:
        return "A_high"
    return "B_mid" if table["agreement"] >= 0.70 else "C_low"


def load_tables(path: Path) -> list[dict]:
    rows = list(csv.DictReader(path.open(newline="", encoding="utf-8")))
    grouped: dict[tuple, list[dict]] = defaultdict(list)
    for row in rows:
        grouped[(row["source_pdf"], row["page_start"], row["grid_id"])].append(row)
    out = []
    for (source, page, grid), members in grouped.items():
        score = members[0]["cell_agreement"]
        out.append({"pdf": source, "page": page, "grid": grid, "members": members,
                    "cells": sum(1 for m in members if m["amount"]),
                    "agreement": float(score) if score else None,
                    "method": members[0]["extraction_method"],
                    "title": members[0]["schedule_title"],
                    "group": members[0]["employee_group"]})
    return out


def grid_sheet(table: dict, ident: str) -> str:
    """The extracted table as an aligned grid, for eyeball comparison with the page."""
    lanes, steps, cells = [], [], {}
    for row in table["members"]:
        if row["lane_raw"] not in lanes:
            lanes.append(row["lane_raw"])
        if row["step_raw"] not in steps:
            steps.append(row["step_raw"])
        if row["amount"]:
            cells[(row["step_raw"], row["lane_raw"])] = row["amount"]
    width = max([10] + [len(str(l)) for l in lanes])
    head = [f"{ident}   {table['pdf']}   page {table['page']}",
            f"title          : {(table['title'] or '(none)')[:100]}",
            f"employee_group : {table['group'] or '(not labelled - SOM endpoint was down)'}",
            f"cells          : {table['cells']}",
            f"Vision agree   : {table['agreement'] if table['agreement'] is not None else 'could not read this page'}",
            "",
            "step".ljust(22) + "".join(str(l)[:width].rjust(width + 2) for l in lanes),
            "-" * (22 + (width + 2) * len(lanes))]
    for step in steps:
        line = str(step)[:20].ljust(22)
        for lane in lanes:
            value = cells.get((step, lane), "")
            try:
                number = float(value)
                value = f"{number:,.0f}" if number.is_integer() else f"{number:,.2f}"
            except (TypeError, ValueError):
                pass
            line += str(value).rjust(width + 2)
        head.append(line)
    return "\n".join(head)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--long", type=Path, default=OUT_DIR / "salary_long.csv")
    parser.add_argument("--seed", type=int, default=20260817)
    args = parser.parse_args()

    tables = load_tables(args.long)
    banded: dict[str, list[dict]] = defaultdict(list)
    for table in tables:
        banded[band_of(table)].append(table)

    rng = random.Random(args.seed)
    picked: list[tuple[str, dict]] = []
    for band in ("A_high", "B_mid", "C_low", "D_unverifiable"):
        pool = [t for t in banded[band]
                if t["cells"] >= MIN_CELLS and (t["pdf"], t["page"]) not in CONTROLS]
        rng.shuffle(pool)
        per_doc: dict[str, int] = defaultdict(int)
        take: list[dict] = []
        for table in sorted(pool, key=lambda t: -t["cells"]):
            if per_doc[table["pdf"]] >= MAX_PER_DOC_PER_BAND:
                continue
            take.append(table)
            per_doc[table["pdf"]] += 1
            if len(take) == PER_BAND:
                break
        picked += [(band, t) for t in take]
    # Cap the controls. They are keyed on (pdf, page), and Philadelphia p157 now yields ten
    # tables rather than one, so taking every match spent 11 of 35 review slots on two
    # pages. Three is enough to check the reviewer against the earlier verdicts.
    controls = [t for t in tables if (t["pdf"], t["page"]) in CONTROLS]
    controls.sort(key=lambda t: -t["cells"])
    picked += [("CONTROL", t) for t in controls[:3]]
    rng.shuffle(picked)

    pages = REVIEW / "pages"
    pages.mkdir(parents=True, exist_ok=True)
    for old in pages.glob("*"):
        old.unlink()
    pdfs = {p.name: p for p in PDF_ROOT.rglob("*.pdf")}

    manifest = []
    for index, (band, table) in enumerate(picked, start=1):
        ident = f"P{index:02d}"
        stem = f"{ident}_p{table['page']}"
        # Render for EVERY ident, not once per page. A page now yields several tables, and
        # the earlier once-per-page guard left later sheets with no image beside them.
        if table["pdf"] in pdfs:
            subprocess.run(["pdftoppm", "-png", "-r", str(RENDER_DPI),
                            "-f", table["page"], "-l", table["page"],
                            str(pdfs[table["pdf"]]), str(pages / stem)],
                           capture_output=True)
        (pages / f"{stem}_extracted.txt").write_text(grid_sheet(table, ident),
                                                    encoding="utf-8")
        manifest.append({"id": ident, "band": band, "pdf": table["pdf"],
                         "page": table["page"], "cells": table["cells"],
                         "agreement": table["agreement"] if table["agreement"] is not None else "",
                         "method": table["method"], "title": (table["title"] or "")[:70]})

    with (REVIEW / "review_manifest.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(manifest[0].keys()))
        writer.writeheader()
        writer.writerows(manifest)
    with (REVIEW / "VERDICTS.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["id", "pdf", "page", "verdict", "wrong_cells_approx", "notes"])
        for entry in manifest:
            writer.writerow([entry["id"], entry["pdf"], entry["page"], "", "", ""])

    print(f"  sampled {len(manifest)} tables across "
          f"{len({m['pdf'] for m in manifest})} documents")
    for band in ("A_high", "B_mid", "C_low", "D_unverifiable", "CONTROL"):
        count = sum(1 for m in manifest if m["band"] == band)
        print(f"    {band:16s} {count}")
    print(f"  -> {REVIEW}/VERDICTS.csv  and  {pages}/")
    print("REVIEW_PACKET_DONE")


if __name__ == "__main__":
    main()
