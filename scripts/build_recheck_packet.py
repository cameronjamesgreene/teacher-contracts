#!/usr/bin/env python3
"""Rebuild review sheets for tables whose earlier sheet was rendered lossily.

The first two packets rendered each table by pivoting into `dict[(step_raw, lane_raw)]`.
UTLA-style schedules print an annual and a monthly line per pay level and label only the
annual one, so every unlabelled row collapsed onto a single key - UTLA p328 holds 504 cells
and the reviewer saw 192. Eleven of twenty-seven sheets were affected, and the reviewer
reported them as truncated. The extraction was complete; the renderer was not.

This regenerates only the affected sheets, as CSV matrices built by
`salary_tables.matrix_from_rows` (which keys on `row_index` and is asserted lossless), and
KEEPS THEIR ORIGINAL IDs so the verdicts already recorded for the other sheets still line up.

Sheets that lost nothing are not reissued: those verdicts stand.
"""

from __future__ import annotations

import argparse
import csv
import shutil
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from salary_tables import matrix_from_rows, table_key
from utils import OUT_DIR, PDF_ROOT, WORK

REVIEW = WORK / "review"
RENDER_DPI = 130


def load_long() -> dict[tuple, list[dict]]:
    grouped: dict[tuple, list[dict]] = defaultdict(list)
    for row in csv.DictReader((OUT_DIR / "salary_long.csv").open(newline="", encoding="utf-8")):
        grouped[table_key(row)].append(row)
    return grouped


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=REVIEW / "recheck")
    args = parser.parse_args()

    manifest = {r["id"]: r for r in
                csv.DictReader((REVIEW / "review_manifest.csv").open(newline="", encoding="utf-8"))}
    grouped = load_long()
    pdfs = {p.name: p for p in PDF_ROOT.rglob("*.pdf")}

    args.out.mkdir(parents=True, exist_ok=True)
    for stale in args.out.glob("*"):
        stale.unlink()

    reissued = []
    for ident, entry in sorted(manifest.items()):
        candidates = [k for k in grouped
                      if k[0] == entry["pdf"] and k[1] == entry["page"]]
        members = next((grouped[k] for k in candidates
                        if len(grouped[k]) == int(entry["cells"])), None)
        if members is None:
            continue
        # Was this sheet lossy? A label-keyed pivot keeps only distinct (step, lane) pairs.
        shown = len({(m["step_raw"], m["lane_raw"]) for m in members})
        if shown >= len(members):
            continue                       # nothing was hidden; the verdict stands

        header, body = matrix_from_rows(members)
        first = members[0]
        stem = f"{ident}_p{entry['page']}"
        with (args.out / f"{stem}.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow([f"# {ident} | {entry['pdf']} | page {entry['page']}"])
            writer.writerow([f"# title: {(first.get('schedule_title') or '(none)')[:150]}"])
            writer.writerow([f"# cells: {len(members)} | previously shown: {shown} "
                             f"| vision_agreement: {first.get('cell_agreement') or 'n/a'}"])
            writer.writerow(header)
            writer.writerows(body)
        if entry["pdf"] in pdfs:
            subprocess.run(["pdftoppm", "-png", "-r", str(RENDER_DPI),
                            "-f", entry["page"], "-l", entry["page"],
                            str(pdfs[entry["pdf"]]), str(args.out / stem)],
                           capture_output=True)
        reissued.append({"id": ident, "pdf": entry["pdf"], "page": entry["page"],
                         "cells": len(members), "previously_shown": shown,
                         "hidden": len(members) - shown})

    with (args.out / "RECHECK_VERDICTS.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["id", "pdf", "page", "verdict", "wrong_cells_approx", "notes"])
        for row in reissued:
            writer.writerow([row["id"], row["pdf"], row["page"], "", "", ""])

    print(f"  reissued {len(reissued)} sheets (of {len(manifest)}); the rest stand")
    for row in reissued:
        print(f"    {row['id']} {row['pdf'][:34]:34s} p{row['page']:<5s} "
              f"cells={row['cells']:4d}  you were shown {row['previously_shown']:4d} "
              f"(hidden {row['hidden']})")
    print(f"  -> {args.out}")
    print("RECHECK_DONE")


if __name__ == "__main__":
    main()
