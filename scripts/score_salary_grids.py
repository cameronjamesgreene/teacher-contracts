#!/usr/bin/env python3
"""Score extracted salary grids against their source pages. No answer key required.

Salary extraction had no measurement instrument at all. Accuracy was judged only by
the independent audit workbooks, where an agent re-read each grid against the PDF and
recorded `Cells Checked` / `Cells Wrong` — thorough, but manual, so it ran on a sample
of a sample and could not gate a change. Every improvement to `salary_schedule.py` was
therefore made blind.

This is the cheap instrument. Four properties are checkable mechanically on every grid
of every document, because the source page's text is right there:

  fidelity     every value in the grid appears as a figure on the page it cites
  capture      the page's figures appear in the grid — the under-extraction defect
  monotonic    within a lane, pay rises with step, as a salary schedule almost always does
  distinct     no two grids are the same numbers under different labels

**This is not accuracy.** It cannot tell whether a column is labelled with the right
lane, whether the schedule covers the right employee group, or whether a whole table
was missed. It is the salary equivalent of `audit_citations.py`: it proves the numbers
are real and complete relative to the page, which is exactly the class of defect
`salary_schedule.py` is known to have (under-extraction, truncation, duplicated grids).

Like the citation audit, it is **gameable by abstention** — a grid with two cells
scores 1.000 on fidelity. So `capture` is always reported next to `fidelity`, and a
grid that captures little of its page is the interesting failure, not a clean one.

Usage:
    python3 scripts/score_salary_grids.py --out output/output_v12/salary_grid_score.csv
"""

from __future__ import annotations

import argparse
import csv
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils import OUT_DIR, TEXT_DIR, WORK

# A salary figure. Four digits or more, or anything comma-grouped: below that the page
# is full of step numbers, article numbers and years that are not pay.
_FIGURE = re.compile(r"\b\d{1,3}(?:,\d{3})+(?:\.\d+)?\b|\b\d{4,}(?:\.\d+)?\b")
_PAGES_HEADER = re.compile(r"^#\s*pages:\s*(\d+)\s*-\s*(\d+)", re.I)
_PDF_HEADER = re.compile(r"^#\s*(.+?)\s+—")
_FILENAME_PAGES = re.compile(r"__p(\d+)-(\d+)\.csv$")
# Below this share of a page's figures, the grid is not plausibly the whole table.
LOW_CAPTURE = 0.60


def figures(text: str) -> set[str]:
    """Comparable figures: commas and trailing decimals dropped, so 54,461 == 54461.

    A bare four-digit number in 1900-2099 is dropped as a year. Salary pages are dense
    with them — "2021-22 Salary Schedule", "effective July 1, 2023", article and section
    numbers — and counting them as pay inflates the page's figure set, which silently
    depresses `capture` on grids that are in fact complete. A comma-grouped or
    dollar-marked value in that range is kept, since "$2,021" is written like money.
    The cost is a genuine bare 2021-dollar cell, which in a teacher salary grid is rare
    enough to be worth the trade.
    """
    out = set()
    for raw in _FIGURE.findall(text or ""):
        looks_like_money = "," in raw or "." in raw
        value = raw.replace(",", "")
        value = value[:-3] if value.endswith(".00") else value
        value = value.rstrip(".").split(".")[0]
        if not looks_like_money and len(value) == 4 and 1900 <= int(value) <= 2099:
            continue
        out.add(value)
    return out


def parse_grid(path: Path) -> dict | None:
    """Header provenance plus the numeric body of one grid CSV."""
    rows = list(csv.reader(path.open(encoding="utf-8", errors="ignore")))
    if not rows:
        return None
    pdf, page_start, page_end = "", 0, 0
    body_start = 0
    for index, row in enumerate(rows):
        first = row[0] if row else ""
        if not first.startswith("#"):
            body_start = index
            break
        match = _PDF_HEADER.match(first)
        if match and not pdf:
            pdf = match.group(1).strip()
        match = _PAGES_HEADER.match(first)
        if match:
            page_start, page_end = int(match.group(1)), int(match.group(2))
    if not page_start:                      # older grids: pages only in the filename
        match = _FILENAME_PAGES.search(path.name)
        if match:
            page_start, page_end = int(match.group(1)), int(match.group(2))

    header = rows[body_start] if body_start < len(rows) else []
    values: list[str] = []
    for row in rows[body_start + 1:]:
        for cell in row[1:]:                # column 0 is the step label, not a wage
            cleaned = (cell or "").strip().replace("$", "").replace(",", "")
            if cleaned and re.fullmatch(r"\d+(?:\.\d+)?", cleaned):
                values.append(cleaned.rstrip(".").split(".")[0])
    steps = [(row[0] or "").strip() for row in rows[body_start + 1:] if row]
    return {"path": path, "pdf": pdf, "page_start": page_start, "page_end": page_end,
            "lanes": max(0, len(header) - 1), "rows": max(0, len(rows) - body_start - 1),
            "values": values, "steps": steps}


def _manifest_by_file_name() -> dict[str, str]:
    """file_name -> document_id, from the frozen manifest."""
    path = WORK / "output" / "extraction" / "corpus_manifest.csv"
    if not path.exists():
        return {}
    with path.open(newline="", encoding="utf-8") as source:
        return {row["file_name"]: row["document_id"] for row in csv.DictReader(source)}


_BY_FILE_NAME: dict[str, str] | None = None


def document_text(pdf_name: str, texts: dict[str, list[str]]) -> list[str] | None:
    """Form-feed pages for the PDF a grid names, resolved through the manifest.

    Not by substring on the file stem, which is how this first went wrong: Manchester's
    grids are written from `83.pdf`, and `"83" in document_id` matched
    `pinellas_county_schools__..._983a400c` — a different district whose *hash* contains
    those digits. Every Manchester grid then scored 0.000 fidelity against the wrong
    contract, which reads as catastrophic extraction rather than as a lookup bug.
    """
    global _BY_FILE_NAME
    if _BY_FILE_NAME is None:
        _BY_FILE_NAME = _manifest_by_file_name()
    document_id = _BY_FILE_NAME.get(pdf_name) or _BY_FILE_NAME.get(Path(pdf_name).name)
    if document_id and document_id in texts:
        return texts[document_id]
    # Fall back to an exact stem match on the slugged file name, never a substring.
    stem = re.sub(r"[^a-z0-9]+", "_", Path(pdf_name).stem.lower()).strip("_")
    for candidate, pages in texts.items():
        parts = candidate.split("__")
        if len(parts) >= 2 and parts[1] == stem:
            return pages
    return None


def load_texts() -> dict[str, list[str]]:
    texts = {}
    for path in TEXT_DIR.glob("*.txt"):
        texts[path.stem] = path.read_text(encoding="utf-8", errors="ignore").split("\f")
    return texts


def score_grid(grid: dict, pages: list[str] | None) -> dict:
    result = {
        "grid": grid["path"].name, "pdf": grid["pdf"],
        "pages": f"{grid['page_start']}-{grid['page_end']}" if grid["page_start"] else "",
        "lanes": grid["lanes"], "steps": grid["rows"], "cells": len(grid["values"]),
        "fidelity": "", "capture": "", "monotonic": "", "completeness": "",
        "expected_cells": "", "note": "",
    }
    if not grid["values"]:
        result["note"] = "no numeric cells"
        return result
    if pages is None:
        result["note"] = "source text not found; cannot verify"
        return result
    if not grid["page_start"]:
        result["note"] = "no page provenance; rerun salary_schedule to record it"
        return result

    window = "\n".join(pages[grid["page_start"] - 1:grid["page_end"]])
    if not window.strip():
        result["note"] = "cited page is empty in the text layer (image-only?)"
        return result
    on_page = figures(window)
    in_grid = set(grid["values"])

    found = sum(1 for value in grid["values"] if value in on_page)
    result["fidelity"] = round(found / len(grid["values"]), 3)
    result["capture"] = round(len(in_grid & on_page) / len(on_page), 3) if on_page else ""

    notes = []
    if result["fidelity"] < 0.95:
        notes.append(f"{len(grid['values']) - found} cell(s) not on the cited page")
    if result["capture"] != "" and result["capture"] < LOW_CAPTURE:
        notes.append(f"page has {len(on_page)} figures, grid uses {len(in_grid & on_page)}"
                     " — possible truncation or a missed table")

    # Expected-cell check. `salary_segment` measures rows x columns from the PDF's own
    # geometry, so under-extraction stops being an inference from figure counts and
    # becomes a comparison against a number derived independently of the model. A grid
    # that is short by whole rows is the truncation defect, stated exactly.
    expected = grid.get("expected_cells") or 0
    if expected:
        result["expected_cells"] = expected
        result["completeness"] = round(min(1.0, len(grid["values"]) / expected), 3)
        if result["completeness"] < 0.9:
            notes.append(f"geometry expects {expected} cells, grid has "
                         f"{len(grid['values'])}")
    result["note"] = "; ".join(notes)
    return result


def _has_step_ladder(grid: dict) -> bool:
    """True when the row labels are an ascending run of numbers, i.e. a real step axis."""
    numbers = [int(s) for s in grid.get("steps", []) if s.isdigit()]
    if len(numbers) < 3:
        return False
    return all(b > a for a, b in zip(numbers, numbers[1:]))


def monotonic_share(grid: dict) -> str:
    """Share of columns whose values rise with the step, where 'step' means something.

    Reported only for grids whose row labels are an ascending run of numbers — a real
    step ladder. A credential-differential or stipend table has no step axis and no
    reason to rise, so scoring it 0.000 flags a defect that does not exist; measured on
    Albuquerque that produced false alarms on every small table while the four genuine
    matrices scored 1.000.
    """
    if grid["lanes"] < 1 or grid["rows"] < 3 or not _has_step_ladder(grid):
        return ""
    columns = defaultdict(list)
    for index, value in enumerate(grid["values"]):
        columns[index % max(1, grid["lanes"])].append(int(value))
    rising = sum(1 for series in columns.values()
                 if len(series) >= 3 and all(b >= a for a, b in zip(series, series[1:])))
    return round(rising / max(1, len(columns)), 3)


def page_level_capture(results: list[dict], grids: dict[str, dict],
                       texts: dict[str, list[str]]) -> dict[tuple[str, str], float]:
    """Capture measured per PAGE, pooling every grid that cites that page.

    Per-grid capture is misleading wherever a page holds more than one table, which is
    92 of 215 pages in this corpus: three correctly-extracted schedules on one page each
    match about a third of its figures, so each grid scores ~0.33 and the page reads as
    badly under-extracted when it is fully captured. Measured both ways on v12, per-grid
    capture is 0.467 and page-level is 0.805 — the difference is entirely the artifact.

    Reported alongside, never instead: per-grid capture still finds the single grid that
    truncated on a page it does not share.
    """
    pooled: dict[tuple[str, str], set[str]] = defaultdict(set)
    for row in results:
        grid = grids.get(row["grid"])
        if grid and row["pages"]:
            pooled[(row["pdf"], row["pages"])] |= set(grid["values"])
    out: dict[tuple[str, str], float] = {}
    for (pdf, pages), values in pooled.items():
        source = document_text(pdf, texts)
        if not source or "-" not in pages:
            continue
        start, end = (int(part) for part in pages.split("-"))
        on_page = figures("\n".join(source[start - 1:end]))
        if on_page:
            out[(pdf, pages)] = round(len(values & on_page) / len(on_page), 3)
    return out


def expected_cells_by_page(pdf_path: Path) -> dict[tuple[int, int], int]:
    """rows x columns per region, from the PDF geometry, keyed by page range."""
    try:
        from salary_segment import fingerprint_document, segment
    except ImportError:
        return {}
    regions = segment(fingerprint_document(pdf_path))
    return {(r.start, r.end): r.expected_cells for r in regions}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--wide-dir", type=Path,
                        default=OUT_DIR / "salary_schedule_wide",
                        help="default: <OUT_DIR>/salary_schedule_wide")
    parser.add_argument("--out", type=Path, help="write the per-grid report as CSV")
    args = parser.parse_args()

    grid_paths = sorted(args.wide_dir.rglob("*.csv"))
    if not grid_paths:
        raise SystemExit(f"no grids under {args.wide_dir} — run salary_schedule.py first")

    texts = load_texts()
    results, signatures, parsed = [], defaultdict(list), {}
    for path in grid_paths:
        grid = parse_grid(path)
        if grid is None:
            continue
        parsed[path.name] = grid
        row = score_grid(grid, document_text(grid["pdf"], texts))
        row["monotonic"] = monotonic_share(grid)
        results.append(row)
        if grid["values"]:
            signatures["|".join(grid["values"])].append(path.name)

    duplicates = {name: names for names in signatures.values() if len(names) > 1
                  for name in names}
    for row in results:
        if row["grid"] in duplicates:
            others = [n for n in duplicates[row["grid"]] if n != row["grid"]]
            row["note"] = "; ".join(filter(None, [
                row["note"], f"identical values to {len(others)} other grid(s)"]))

    by_page = page_level_capture(results, parsed, texts)
    for row in results:
        row["page_capture"] = by_page.get((row["pdf"], row["pages"]), "")

    print(f"{len(results)} grids from {args.wide_dir}")
    scored = [r for r in results if r["fidelity"] != ""]
    if scored:
        print(f"  fidelity  mean {statistics.mean(r['fidelity'] for r in scored):.3f}"
              f"  (grids below 0.95: {sum(1 for r in scored if r['fidelity'] < 0.95)})")
        captures = [r["capture"] for r in scored if r["capture"] != ""]
        if captures:
            print(f"  capture   mean {statistics.mean(captures):.3f} per grid"
                  f"  (grids below {LOW_CAPTURE}: {sum(1 for c in captures if c < LOW_CAPTURE)})")
        pooled = sorted(set(by_page.values()))
        if pooled:
            print(f"  capture   mean {statistics.mean(by_page.values()):.3f} PER PAGE"
                  f"  ({sum(1 for c in by_page.values() if c >= 0.9)}/{len(by_page)} pages "
                  f">=0.90) <- the honest figure where a page holds several tables")
        mono = [r["monotonic"] for r in results if r["monotonic"] != ""]
        if mono:
            print(f"  monotonic mean {statistics.mean(mono):.3f}")
    unscored = [r for r in results if r["fidelity"] == ""]
    if unscored:
        print(f"  {len(unscored)} not verifiable:")
        for note, count in sorted(
                {r["note"]: sum(1 for x in unscored if x["note"] == r["note"])
                 for r in unscored}.items(), key=lambda kv: -kv[1]):
            print(f"    {count:>4}  {note}")
    if duplicates:
        print(f"  {len(duplicates)} grid(s) share values with another grid")

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        fields = ["grid", "pdf", "pages", "lanes", "steps", "cells", "expected_cells",
                  "fidelity", "capture", "page_capture", "monotonic", "completeness", "note"]
        with args.out.open("w", newline="", encoding="utf-8") as sink:
            writer = csv.DictWriter(sink, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(results)
        print(f"  report -> {args.out}")


if __name__ == "__main__":
    main()
