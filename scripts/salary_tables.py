#!/usr/bin/env python3
"""Write one matrix CSV per salary table, derived from salary_long.csv.

## Why derived, not re-extracted

`salary_long.csv` is the analysis panel - one row per pay cell - and it is the only thing
the pipeline produces. A matrix is what a person wants to look at, so this rebuilds the
printed shape FROM the panel rather than extracting it a second time. One source of truth,
no second path to drift.

## Why the previous renderer lost rows

The review packet built its matrix by pivoting into `dict[(step_raw, lane_raw)]`. UTLA-style
schedules print an annual line and a monthly line for each pay level and label only the
annual one, so 24 unlabelled rows collapsed onto one key: UTLA p328 holds 504 cells and the
sheet showed 192. Reviewers correctly reported "roughly every other row is missing" - of the
extraction, which was in fact complete.

`row_index` exists precisely so emission order survives, and this module keys on it. Cell
count in equals cell count out, asserted by `write_tables`.
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils import OUT_DIR


def matrix_from_rows(rows: list[dict]) -> tuple[list[str], list[list[str]]]:
    """(header, body) for one table. Body row 0 is the step label, then the amounts.

    Rows come back in printed order and keep every cell, including rows whose step label is
    blank and rows that repeat a label - both of which a label-keyed pivot silently merges.
    """
    by_row: dict[int, list[dict]] = defaultdict(list)
    for row in rows:
        try:
            by_row[int(row["row_index"])].append(row)
        except (KeyError, TypeError, ValueError):
            by_row[len(by_row) + 1].append(row)

    ordered = [by_row[key] for key in sorted(by_row)]
    # Columns are positional. The widest printed row defines the header, because a table
    # whose first row is short would otherwise truncate every row below it.
    widest = max(ordered, key=len) if ordered else []
    header = ["step"] + [str(cell.get("lane_raw") or "") for cell in widest]

    body: list[list[str]] = []
    for group in ordered:
        label = str(group[0].get("step_raw") or "")
        body.append([label] + [str(cell.get("amount") or "") for cell in group])
    return (header, body)


def table_key(row: dict) -> tuple:
    return (row["source_pdf"], row["page_start"], row["grid_id"])


def write_tables(long_csv: Path, out_dir: Path) -> tuple[int, int, int]:
    """Emit one CSV per table. Returns (tables, cells_in, cells_out)."""
    rows = list(csv.DictReader(long_csv.open(newline="", encoding="utf-8")))
    grouped: dict[tuple, list[dict]] = defaultdict(list)
    for row in rows:
        grouped[table_key(row)].append(row)

    out_dir.mkdir(parents=True, exist_ok=True)
    for stale in out_dir.glob("*.csv"):
        stale.unlink()

    cells_in = cells_out = 0
    for (source, page, grid), members in grouped.items():
        header, body = matrix_from_rows(members)
        cells_in += sum(1 for m in members if m.get("amount"))
        cells_out += sum(1 for line in body for value in line[1:] if value)
        first = members[0]
        path = out_dir / f"{grid}.csv"
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            # Provenance travels with the matrix, so a file on its own is still traceable.
            writer.writerow([f"# {source} | page {page} | table "
                             f"{first.get('table_index')} of {first.get('tables_on_page')}"])
            writer.writerow([f"# title: {first.get('schedule_title', '')[:160]}"])
            writer.writerow([f"# employee_group: {first.get('employee_group') or '(unlabelled)'}"
                             f" | pay_basis: {first.get('pay_basis') or '(unlabelled)'}"
                             f" | method: {first.get('extraction_method')}"
                             f" | low_density: {first.get('low_density')}"
                             f" | vision_agreement: {first.get('cell_agreement') or 'n/a'}"])
            writer.writerow(header)
            writer.writerows(body)
    return (len(grouped), cells_in, cells_out)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--long", type=Path, default=OUT_DIR / "salary_long.csv")
    parser.add_argument("--out", type=Path, default=OUT_DIR / "salary_tables")
    args = parser.parse_args()
    tables, cells_in, cells_out = write_tables(args.long, args.out)
    print(f"  tables written : {tables}")
    print(f"  cells in panel : {cells_in:,}")
    print(f"  cells in matrices: {cells_out:,}")
    if cells_in != cells_out:
        print(f"  ** LOSS {cells_in - cells_out} ** the matrix writer is dropping cells")
    else:
        print("  lossless")
    print(f"  -> {args.out}")
    print("TABLES_DONE")


if __name__ == "__main__":
    main()
