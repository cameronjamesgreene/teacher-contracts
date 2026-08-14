#!/usr/bin/env python3
"""Stages 0-2 of the salary pipeline: PDFs -> salary_long.csv, no API calls.

Geometry finds the tables (scripts/salary_geometry.py), the deterministic parsers in
scripts/salary_schema.py turn headers and labels into economics, and every numeric cell is
written straight from the PDF's own coordinates. Nothing here calls the model.

The five fields that genuinely need judgement — employee_group, lane_type where geometry
cannot infer it, pay_basis, step_kind and days_per_year where the page states it in prose —
are left empty for stage 3, one short call per page-range. Running this alone shows what
coverage costs nothing.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from salary_geometry import MONEY, Table, is_year, money_in, page_words, tables_on_page
from salary_schema import (PayCell, classify_value, days_from_prose, infer_lane_type,
                           parse_effective_date, parse_lane, parse_step)
from utils import OUT_DIR, PDF_ROOT

FIELDS = [f for f in PayCell.__dataclass_fields__]


def money_value(cell: str) -> float | None:
    """The amount in a cell, tolerating stray glyphs that share its column.

    Rochester p146 assembles cells as `"$ 37,410 !"` because it prints a rule glyph and a
    detached currency sign; an anchored match on the whole cell drops all 178 of that
    page's values. `money_in` matches per token instead.
    """
    token = money_in(cell)
    if token is None:
        return None
    try:
        return float(token.replace("$", "").replace(",", ""))
    except ValueError:
        return None


def district_of(pdf: Path) -> str:
    return pdf.parent.name if pdf.parent != PDF_ROOT else pdf.stem


def rows_from_table(table: Table, pdf: Path, page_text: str) -> list[dict]:
    days = days_from_prose(page_text, " ".join(table.groups[:1]) if table.groups else "")
    out: list[dict] = []
    for index, row in enumerate(table.rows):
        step_raw = row[0]
        group = table.groups[index] if index < len(table.groups) else ""
        # Classify the step from the STEP LABEL ALONE. Folding the sub-heading in first
        # ("Pay Grade 29" + "01") sent 55% of the corpus to `class_code`, because the
        # heading's words dominate the pattern match. The heading is identity, not step -
        # it belongs in schedule_title, where a consumer can still group on it.
        kind, number = parse_step(step_raw)
        composite = f"{group} {step_raw}".strip() if group else step_raw
        for column, cell in enumerate(row[1:], start=1):
            amount = money_value(cell)
            if amount is None:
                continue
            lane = table.header[column] if column < len(table.header) else ""
            kind_of_value, basis_hint = classify_value(lane, composite)
            # A bare year in a data cell is a stray header token, not pay. 429 such cells
            # were previously emitted as `value_kind="salary"`, so a wage regression that
            # filtered on salary would have ingested them as $2,006 salaries.
            if is_year(money_in(cell) or ""):
                kind_of_value = "unknown"
            degree, credits = parse_lane(lane)
            out.append(PayCell(
                document_id="", district=district_of(pdf), state="",
                source_pdf=pdf.name, page_start=table.page_start, page_end=table.page_end,
                grid_id=f"{pdf.stem[:24]}_p{table.page_start}_{table.note or 'main'}",
                extraction_method=table.method, cell_verified=False, cell_agreement=None,
                schedule_title=group, employee_group="", is_teacher=False,
                contract_year_start=None, contract_year_end=None,
                effective_date=parse_effective_date(lane),
                lane_raw=lane, lane_type=infer_lane_type(lane), degree=degree,
                education_credits=credits, step_raw=composite, step_kind=kind,
                step_number=number, amount=amount,
                pay_basis=basis_hint or "", value_kind=kind_of_value,
                days_per_year=days, notes=table.note).as_row())
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=OUT_DIR / "salary_long.csv")
    parser.add_argument("--limit", type=int, help="first N documents only")
    args = parser.parse_args()

    try:
        import pdfplumber
    except ImportError:
        sys.exit("pdfplumber is required")

    pdfs = sorted(PDF_ROOT.rglob("*.pdf"))[: args.limit]
    rows: list[dict] = []
    stats = Counter()
    for number, pdf in enumerate(pdfs, start=1):
        found = 0
        try:
            with pdfplumber.open(str(pdf)) as document:
                for page_number, page in enumerate(document.pages, start=1):
                    if not page_words(page):
                        stats["pages_no_usable_geometry"] += 1
                        continue
                    tables = tables_on_page(page, page_number)
                    if not tables:
                        continue
                    text = page.extract_text() or ""
                    for table in tables:
                        rows.extend(rows_from_table(table, pdf, text))
                        found += 1
        except Exception as error:
            stats[f"document_error_{type(error).__name__}"] += 1
        stats["tables"] += found
        if found:
            stats["documents_with_tables"] += 1
        print(f"  [{number}/{len(pdfs)}] {pdf.name[:52]:52s} tables={found}", flush=True)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\n  documents            : {len(pdfs)}")
    print(f"  documents with tables: {stats['documents_with_tables']}")
    print(f"  tables               : {stats['tables']}")
    print(f"  pay cells            : {len(rows):,}")
    print(f"  -> {args.out}")
    for key, value in sorted(stats.items()):
        if key.startswith(("document_error", "pages_no")):
            print(f"    {key}: {value}")
    print("SALARY_LONG_DONE")


if __name__ == "__main__":
    main()
