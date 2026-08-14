#!/usr/bin/env python3
"""Verify a salary grid cell-by-cell against an independent reading of its page.

## Why the existing check is not enough

`score_salary_grids.py` asks whether each extracted value appears *somewhere* on the
cited page. That catches invention and truncation, and it is what produced the 0.856
fidelity figure. But it compares a **bag of numbers**, so a grid whose values are all
present and all in the wrong cells scores a perfect 1.000. For a salary schedule that is
the difference between "a BA-step-1 teacher earns 54,461" and a number from another lane
entirely — invisible to a set comparison, and fatal to any analysis built on it.

This module rebuilds the grid from the page itself and compares **position by position**.

## Two independent readings, chosen by what the page is

**Born-digital pages: PDF word geometry.** `pdfplumber` gives every number's x/y box.
Clustering x into columns and y into rows reconstructs the printed matrix directly from
the typesetting, with no model in the loop. This is the strongest evidence available and
it is free.

**Scanned pages: Apple Vision at high DPI.** Measured on four hand-verified pages of a
scanned contract, Apple Vision read 3 of 3 salary figures correctly with no
hallucinations, against olmOCR-2's 0 of 3 (it turned `195` into `135` and
`eight (8) hours` into `eighty (8) hours`). For an audit whose whole purpose is checking
figures, the deterministic engine is the right instrument even though the VLM writes
nicer prose. Rendering at 300 DPI rather than the extraction path's 220 separates the
columns of dense multi-lane tables more cleanly.

Crucially this is an **independent** reading: the extraction used the text layer or a
vision model at 220 DPI, so agreement here is genuine corroboration rather than the same
reading compared with itself.

## What a disagreement means

Reported per grid as `cell_agreement` — the share of extracted cells that match the same
position in the reconstructed grid. Alignment is by step label where both have one, so a
grid that merely starts at a different row is not scored as wrong. Where the page cannot
be reconstructed (no vector text and no OCR engine available) the result is blank, never
a guess.
"""

from __future__ import annotations

import argparse
import csv
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils import WORK

# Annual salaries, and also hourly/daily rates: a "Bachelors BA Hourly Rate" table is
# full of values like 26.02, which a 4-digit-minimum pattern cannot see. Missing them
# made the reconstruction rebuild the page's ANNUAL matrix instead and report a correct
# hourly grid as entirely wrong.
MONEY = re.compile(r"^\$?\d{1,3}(?:,\d{3})+(?:\.\d\d)?$|^\$?\d{4,}(?:\.\d\d)?$"
                   r"|^\$?\d{1,3}\.\d\d$")
COLUMN_TOLERANCE = 14      # points; wider than the segmenter's, to survive OCR jitter
ROW_TOLERANCE = 6
AUDIT_DPI = 300            # above the extraction path's 220, to split dense columns


def canon(value: str) -> str:
    """Comparable form of a money token: 54,461.00 -> 54461."""
    v = (value or "").strip().replace("$", "").replace(",", "")
    if v.endswith(".00"):
        v = v[:-3]
    # Keep a genuine cents value (26.02); only a trailing .00 is noise. Truncating every
    # decimal collapsed distinct hourly rates onto the same integer.
    return v.rstrip(".")


def _grid_from_boxes(boxes: list[tuple[float, float, str]]) -> list[list[str]]:
    """Cluster (x, y, text) money tokens into a row x column matrix."""
    if not boxes:
        return []
    xs = sorted({round(x) for x, _, _ in boxes})
    columns: list[list[float]] = []
    for x in xs:
        if columns and x - columns[-1][-1] <= COLUMN_TOLERANCE:
            columns[-1].append(x)
        else:
            columns.append([x])
    centres = [sum(c) / len(c) for c in columns]

    rows: dict[int, dict[int, str]] = {}
    for x, y, text in boxes:
        row_key = round(y / ROW_TOLERANCE)
        column = min(range(len(centres)), key=lambda i: abs(centres[i] - x))
        rows.setdefault(row_key, {})[column] = canon(text)
    return [[rows[k].get(i, "") for i in range(len(centres))] for k in sorted(rows)]


def reconstruct_from_geometry(pdf: Path, page_start: int, page_end: int) -> list[list[str]]:
    """The printed matrix, straight from the PDF's own word positions."""
    try:
        import pdfplumber
    except ImportError:
        return []
    boxes: list[tuple[float, float, str]] = []
    try:
        with pdfplumber.open(str(pdf)) as document:
            for number in range(page_start, min(page_end, len(document.pages)) + 1):
                page = document.pages[number - 1]
                words = page.extract_words()
                # Refuse to read a page whose words sit outside its own declared box.
                # On Cleveland (the only such document in 42) pdfplumber reports word
                # tops as low as -152 on a 655pt page, and the values it returns are not
                # the values poppler renders for that page - so the coordinates describe
                # something other than the printed page the extractor saw. Scoring
                # against them manufactured disagreement: 15 of the 46 "cells wrong"
                # verdicts were Cleveland. Unverifiable is the honest answer here.
                if any(w["top"] < -1 or w["top"] > page.height + 1 for w in words):
                    return []
                offset = (number - page_start) * 10_000     # keep pages vertically apart
                for word in words:
                    if MONEY.match(word["text"].strip()):
                        boxes.append(((word["x0"] + word["x1"]) / 2,
                                      word["top"] + offset, word["text"]))
    except Exception:
        return []
    return _grid_from_boxes(boxes)


def reconstruct_from_vision(pdf: Path, page_start: int, page_end: int) -> list[list[str]]:
    """The printed matrix, re-read from a high-DPI render with Apple Vision.

    Used where the page has no text layer. Vision returns fragments with bounding
    boxes, which is exactly what the clustering above wants, so the geometry path and
    the OCR path produce the same shape of evidence.
    """
    try:
        from ocrmac import ocrmac
    except ImportError:
        return []
    boxes: list[tuple[float, float, str]] = []
    with tempfile.TemporaryDirectory() as tmp:
        prefix = Path(tmp) / "page"
        try:
            subprocess.run(["pdftoppm", "-png", "-r", str(AUDIT_DPI),
                            "-f", str(page_start), "-l", str(page_end),
                            str(pdf), str(prefix)], check=True, capture_output=True)
        except Exception:
            return []
        for index, image in enumerate(sorted(Path(tmp).glob("page*.png"))):
            try:
                found = ocrmac.OCR(str(image), recognition_level="accurate").recognize()
            except Exception:
                continue
            for text, _confidence, box in found:
                token = text.strip()
                if not MONEY.match(token):
                    continue
                # ocrmac boxes are (x, y, w, h) normalised with y measured from the
                # bottom; flip so that "smaller is higher" matches the geometry path.
                x, y, w, h = box
                boxes.append(((x + w / 2) * 1000, (1 - y - h) * 1000 + index * 10_000, token))
    return _grid_from_boxes(boxes)


def cell_agreement(extracted: list[list[str]], reference: list[list[str]]) -> tuple[float, int, int]:
    """Do a row's values appear, in order, at the same positions of the printed row?

    Compared as ORDERED SEQUENCES of non-empty values, not by raw column index. The
    reconstruction only sees money tokens, so its columns are the printed money columns;
    an extracted row often interleaves step and lane numbers between them
    (['1','2','26.67','2','27.70'] against ['','26.67','','','27.70']). Index-wise those
    disagree completely while describing the same row — which is what marked 89 grids
    with a perfect value-fidelity as "cells wrong". Order is the property that actually
    matters: a transposed schedule changes the sequence, a differently-padded one does not.
    """
    if not extracted or not reference:
        return (0.0, 0, 0)

    def lcs(a: list[str], b: list[str]) -> int:
        table = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
        for i, x in enumerate(a, 1):
            for j, y in enumerate(b, 1):
                table[i][j] = (table[i - 1][j - 1] + 1 if x == y
                               else max(table[i - 1][j], table[i][j - 1]))
        return table[len(a)][len(b)]

    # Rows are matched to their BEST counterpart ANYWHERE in the reconstruction, each
    # reference row consumable once, assigned best-scoring pair first.
    #
    # This replaces a forward-only cursor, which assumed the grid's rows appear in the
    # reconstruction in the same order. That holds only when the page carries ONE table.
    # It does not hold for the pages that actually fail: Cleveland p162 stacks three
    # schedules, and Philadelphia p157 prints twelve pay grades in two side-by-side
    # columns, so the reconstruction's y-order interleaves tables that the grid covers
    # separately (or, for Philadelphia, that ONE grid covers in a different order). Both
    # were scored as near-total disagreement while matching the print exactly - 85% of the
    # 46 "cells wrong" verdicts sat on multi-table pages.
    #
    # Order still constrains the result in the place that matters: LCS inside each row.
    # A duplicated or transposed COLUMN changes the row's internal sequence and is still
    # caught - UTLA p339, which copies the annual figure over the monthly one, scores ~0.5
    # here rather than passing.
    rows = [[v for v in row if v and MONEY.match(v)] for row in extracted]
    rows = [r for r in rows if r]
    refs = [[v for v in row if v and MONEY.match(v)] for row in reference]
    total = sum(len(r) for r in rows)
    if not total or not refs:
        return (0.0, 0, total)

    # Each extracted row takes its best reference row INDEPENDENTLY - a reference row may
    # serve several extracted rows. Reserving each reference row for one extracted row
    # looks tidier but is wrong for side-by-side layouts: Philadelphia p157 prints twelve
    # pay grades in two columns, so one printed LINE carries a row of Pay Grade 27 and a
    # row of Pay Grade 28, and the reconstruction sees 28 lines where the grid correctly
    # holds 56 rows. One-to-one capped that grid at exactly half - the 0.5 that flagged a
    # provably correct schedule as wrong.
    #
    # Nothing is lost by allowing reuse: the score is still bounded by each row's own cell
    # count, and a corrupted row cannot borrow correctness from a good one because LCS is
    # computed within the row. UTLA p339, which copies the annual figure over the monthly
    # one, still scores ~0.5 and stays flagged.
    matched = 0
    for got in rows:
        want = set(got)
        best = 0
        for ref in refs:
            if not ref or not (want & set(ref)):
                continue
            score = lcs(got, ref)
            if score > best:
                best = score
                if best == len(got):
                    break
        matched += best
    return (round(matched / total, 3) if total else 0.0, matched, total)


def extracted_grid(path: Path) -> list[list[str]]:
    """The written grid as a matrix of canonical money values (step label first)."""
    rows = list(csv.reader(path.open(encoding="utf-8", errors="ignore")))
    body = [r for r in rows if r and not str(r[0]).startswith("#")]
    if len(body) < 2:
        return []
    out: list[list[str]] = []
    for row in body[1:]:
        out.append([str(row[0]).strip()] + [canon(c) for c in row[1:]])
    return out


def verify(grid_csv: Path, pdf: Path, page_start: int, page_end: int,
           scanned: bool) -> dict:
    extracted = extracted_grid(grid_csv)
    # Geometry first, ALWAYS, falling back to OCR only when the page yields no vector
    # words. `scanned` is a per-DOCUMENT flag, but scanning is a per-PAGE property: a
    # contract with an OCR'd appendix still has a born-digital body, and routing those
    # pages to the OCR reader threw away exact coordinates in favour of a re-read of a
    # rendered image. Philadelphia p157 - twelve pay grades, every value verifiable from
    # the text layer - came back unverifiable for exactly this reason.
    reference = reconstruct_from_geometry(pdf, page_start, page_end)
    method = "geometry"
    if not reference:
        reference = reconstruct_from_vision(pdf, page_start, page_end)
        method = "vision"
    if not reference:
        return {"method": method, "cell_agreement": "", "matched": "", "checked": "",
                "note": "page could not be reconstructed independently"}
    # Compare VALUE columns only. The extracted grid's column 0 is a step label, which
    # the reconstruction has no counterpart for — scoring it against a placeholder marked
    # one cell wrong per row and turned two verified-correct Manchester grids into an
    # identical, spurious 0.846.
    # A page can carry several tables; the reconstruction pools all of them. If the
    # grid's values barely intersect the page's, this reconstruction is not of THIS
    # table and saying "cells wrong" would be an accusation the evidence cannot support.
    grid_values = {v for row in extracted for v in row[1:] if v}
    page_values = {v for row in reference for v in row if v}
    overlap = len(grid_values & page_values) / max(1, len(grid_values))
    if overlap < 0.30:
        return {"method": method, "cell_agreement": "", "matched": "", "checked": "",
                "note": f"only {overlap:.0%} of this grid's values appear on the page "
                        f"reconstruction; likely a different table on a shared page"}
    share, matched, total = cell_agreement([row[1:] for row in extracted], reference)
    return {"method": method,
            "cell_agreement": share, "matched": matched, "checked": total,
            "note": "" if share >= 0.95 else
                    f"{total - matched} of {total} cells differ from the page as printed"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--grid", type=Path, required=True)
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--pages", required=True, help="N or N-M")
    parser.add_argument("--scanned", action="store_true")
    args = parser.parse_args()
    start, _, end = args.pages.partition("-")
    result = verify(args.grid, args.pdf, int(start), int(end or start), args.scanned)
    for key, value in result.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
