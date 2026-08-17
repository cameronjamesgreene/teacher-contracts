#!/usr/bin/env python3
"""Stamp `cell_verified` on salary_long.csv against an INDEPENDENT reading of each page.

## Why the reference must be the other engine

`verify()` in scripts/verify_salary_grids.py reconstructs a page from pdfplumber word
coordinates. That is the right reference for a grid the *model* transcribed — but the
current pipeline EXTRACTS from those same coordinates, so checking geometry against
geometry is circular and would report 1.000 everywhere while proving nothing.

Apple Vision at 300 DPI is independent of both extraction paths:

| rows | extracted by | Vision is independent because |
|---|---|---|
| `geometry_vector` | pdfplumber word boxes | rasterise + OCR never touches the text layer |
| `legacy_vision` | Qwen reading a page image | a deterministic OCR engine, not a VLM |
| `legacy_structured` | pdfplumber -> Qwen retype | independent of both halves |

**This is a local verification harness, not a pipeline stage.** `ocrmac` is macOS-only and
the pipeline must run on the Yale HPC, so nothing here is imported by the extraction path.

## What the number means

`cell_agreement` is the share of a table's money cells that appear, in row order, in the
Vision reconstruction. Agreement with an OCR reference is bounded by that OCR's own
accuracy — on a dense Cleveland table Vision differs on ~5 of 51 cells that are provably
correct — so the bar is 0.90 rather than the 0.95 used against vector geometry. A table
Vision cannot read at all is left unverified, never guessed.
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from verify_salary_grids import cell_agreement, canon, reconstruct_from_vision
from utils import OUT_DIR, PDF_ROOT

GOOD = 0.90          # bounded by Apple Vision's own cell accuracy, not the extractor's
WORKERS = 6


def matrix_of(rows: list[dict]) -> list[list[str]]:
    """Rebuild the printed matrix from long rows, preserving EMISSION ORDER.

    Keying on (step_raw, lane_raw) loses cells whenever either label repeats, and both do:
    UTLA p339 prints its sub-columns with no header at all, so five of six `lane_raw` are
    empty strings, and its row labels ("B basis", "C basis") repeat once per pay-scale
    group. Pivoting on labels dropped 236 of that table's 320 cells and then reported the
    survivors as a disagreement.

    The rows are written row-by-row and column-by-column, so the file order IS the printed
    order, and a new matrix row starts when the step label changes — every printed row
    carries exactly one. Breaking on a repeated COLUMN label instead looks equivalent and
    is not: UTLA's empty sub-column headers repeat every other cell, which chopped its
    32 x 10 table into 160 x 3.
    """
    matrix: list[list[str]] = []
    current: list[str] = []
    last_step = None
    for row in rows:
        amount = row["amount"]
        if not amount:
            continue
        step = row["step_raw"]
        if current and step != last_step:
            matrix.append(current)
            current = []
        value = float(amount)
        current.append(canon(str(int(value)) if value.is_integer() else str(value)))
        last_step = step
    if current:
        matrix.append(current)
    return matrix


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--long", type=Path, default=OUT_DIR / "salary_long.csv")
    parser.add_argument("--out", type=Path, default=OUT_DIR / "salary_long.csv")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()

    rows = list(csv.DictReader(args.long.open(newline="", encoding="utf-8")))
    fields = list(rows[0].keys())
    tables: dict[tuple, list[dict]] = defaultdict(list)
    for row in rows:
        tables[(row["source_pdf"], row["page_start"], row["page_end"],
                row["grid_id"])].append(row)
    keys = list(tables)
    if args.limit:
        keys = keys[: args.limit]

    pdfs = {p.name: p for p in PDF_ROOT.rglob("*.pdf")}
    # One Vision read per PAGE, shared by every table on it — a page carrying three
    # schedules costs one 3.9s reconstruction, not three.
    pages = sorted({(k[0], k[1], k[2]) for k in keys})
    print(f"  tables: {len(keys)}   distinct pages to read with Vision: {len(pages)}")

    def read(page_key):
        source, start, end = page_key
        pdf = pdfs.get(source)
        if pdf is None or not str(start).isdigit():
            return (page_key, [])
        finish = int(end) if str(end).isdigit() else int(start)
        try:
            return (page_key, reconstruct_from_vision(pdf, int(start), finish))
        except Exception:
            return (page_key, [])

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        reconstructions = dict(pool.map(read, pages))
    print(f"  pages Vision could read: {sum(1 for v in reconstructions.values() if v)}")

    verdicts = Counter()
    for key in keys:
        reference = reconstructions.get((key[0], key[1], key[2]), [])
        members = tables[key]
        if not reference:
            verdicts["unverifiable_no_reference"] += 1
            continue
        share, matched, total = cell_agreement(matrix_of(members), reference)
        if not total:
            verdicts["unverifiable_no_cells"] += 1
            continue
        ok = share >= GOOD
        verdicts["verified" if ok else "disagrees"] += 1
        for row in members:
            row["cell_verified"] = str(ok)
            row["cell_agreement"] = f"{share:.3f}"

    with args.out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    stamped = sum(1 for r in rows if r["cell_agreement"])
    print(f"  tables: {dict(verdicts)}")
    print(f"  cells carrying an agreement score: {stamped:,} of {len(rows):,}")
    print(f"  cells verified: {sum(1 for r in rows if r['cell_verified'] == 'True'):,}")
    print(f"  -> {args.out}")
    print("VERIFY_LONG_DONE")


if __name__ == "__main__":
    main()
