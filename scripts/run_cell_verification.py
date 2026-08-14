#!/usr/bin/env python3
"""Cell-level verification across every pending salary grid in the audit ledger.

Upgrades each grid from "its values appear somewhere on the cited page" to "its values
sit in the right cells", by rebuilding the page independently — PDF word geometry for
born-digital pages, Apple Vision at 300 DPI for scans — and comparing position by
position. See scripts/verify_salary_grids.py for why a bag-of-values comparison is not
enough.

Writes verdicts in the shape scripts/audit_ledger.py record expects.
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils import OUT_DIR, PDF_ROOT, WORK
from verify_salary_grids import verify

LEDGER = OUT_DIR / "audit_ledger.jsonl"
# Agreement bands. 0.95 allows the header row the reconstruction reads as data plus the
# odd hyphenation artifact; below 0.70 the grid is not describing this page.
GOOD, PARTIAL = 0.95, 0.70


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()

    manifest = {r["file_name"]: r["document_id"] for r in
                csv.DictReader(open(WORK / "output" / "extraction" / "corpus_manifest.csv",
                                    newline="", encoding="utf-8"))}
    scans = {Path(p).stem for p in
             glob.glob(str(WORK / "output" / "extraction" / "ocr_provenance" / "*.csv"))}
    # Key on (basename, pages), not basename alone. 46 basenames are reused across the
    # year-folders of one document and 85 grids resolve to a file describing a DIFFERENT
    # page - Philadelphia writes `professional_technical_salaries__...csv` for both p157
    # and p159. Taking paths[0] then compared a grid against someone else's page and
    # scored it as fabricated. Pages come from the file's own header stamp.
    by_key: dict[tuple[str, str], str] = {}
    by_name: dict[str, list[str]] = {}
    for path in glob.glob(str(OUT_DIR / "salary_schedule_wide" / "*" / "*" / "*.csv")):
        head = Path(path).read_text(encoding="utf-8", errors="ignore")[:400]
        stamp = re.search(r"pages:\s*([\d\-]+)", head)
        if stamp:
            by_key[(Path(path).name, stamp.group(1))] = path
        by_name.setdefault(Path(path).name, []).append(path)
    pdf_by_name = {p.name: p for p in PDF_ROOT.rglob("*.pdf")}

    rows = [json.loads(line) for line in LEDGER.read_text(encoding="utf-8").splitlines()
            if line.strip()]
    todo = [r for r in rows if r["sheet"] == "3_salary_schedule"
            and r["check_method"] == "pending"]
    if args.limit:
        todo = todo[:args.limit]

    out = []
    for index, row in enumerate(todo, 1):
        pages = str(row.get("pages") or "")
        exact = by_key.get((str(row["grid"]), pages))
        paths = [exact] if exact else by_name.get(row["grid"], [])
        pdf = pdf_by_name.get(row["pdf"])
        if not paths or pdf is None or "-" not in pages:
            out.append({"key": row["key"], "verdict": "unverifiable",
                        "audit_note": "grid file or source PDF could not be resolved"})
            continue
        start, _, end = pages.partition("-")
        try:
            result = verify(Path(paths[0]), pdf, int(start), int(end or start),
                            manifest.get(row["pdf"], "") in scans)
        except Exception as error:
            out.append({"key": row["key"], "verdict": "unverifiable",
                        "audit_note": f"verification failed: {type(error).__name__}"})
            continue

        share = result["cell_agreement"]
        if share == "":
            verdict, note = "unverifiable", result["note"]
        else:
            detail = (f"cell agreement {share} ({result['matched']}/{result['checked']}) "
                      f"against a {result['method']} reconstruction of the page")
            if share >= GOOD:
                verdict, note = "cells_correct", detail
            elif share >= PARTIAL:
                verdict, note = "partial", detail + " - some cells differ from the print"
            else:
                verdict, note = "cells_wrong", detail
        out.append({"key": row["key"], "verdict": verdict, "audit_note": note})
        if index % 25 == 0:
            print(f"  {index}/{len(todo)}", flush=True)

    args.out.write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print("  verdicts:", dict(Counter(o["verdict"] for o in out)))
    print(f"  -> {args.out}")
    print("CELLVERIFY_DONE")


if __name__ == "__main__":
    main()
