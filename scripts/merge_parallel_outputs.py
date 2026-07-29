#!/usr/bin/env python3
"""Merge the per-document output dirs produced by run_parallel_v6.sh into one combined
output dir.

When documents are processed concurrently, each runs with its own
CONTRACT_OUT_DIR=<base>/<slug> so the three writers never clobber each other's CSVs
(llm_extract and rights_score each open their CSVs in "w" and write once at the end,
containing only that run's docs). This script unions those per-slug dirs back into
<base>/:

  * the long/wide CSVs (llm_main_dataset, llm_coding_log, rights_score_long,
    rights_score_summary) are concatenated with a single shared header;
  * salary_schedule_wide/ is a copy-merge (its files are already partitioned by
    district/year/label/pdf-stem, so distinct documents never collide).

Usage:
    python3 merge_parallel_outputs.py <base_dir> <slug1> <slug2> [<slug3> ...]
e.g. python3 merge_parallel_outputs.py .../contract_coding_CG/output_v6 denver_... baltimore_... broward_...
"""
from __future__ import annotations

import csv
import shutil
import sys
from pathlib import Path

CSV_FILES = (
    "llm_main_dataset.csv",
    "llm_coding_log.csv",
    "rights_score_long.csv",
    "rights_score_summary.csv",
)
WIDE_DIR = "salary_schedule_wide"


def merge_csv(name: str, base: Path, slug_dirs: list[Path]) -> None:
    header: list[str] | None = None
    rows: list[list[str]] = []
    seen_sources = 0
    for d in slug_dirs:
        p = d / name
        if not p.exists():
            continue
        seen_sources += 1
        with p.open(encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            these = list(reader)
        if not these:
            continue
        if header is None:
            header = these[0]
        elif these[0] != header:
            print(f"  WARNING: {name} header mismatch in {d.name} — using first header")
        rows.extend(these[1:])
    if header is None:
        print(f"  {name}: no per-slug files found — skipped")
        return
    out = base / name
    with out.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    print(f"  {name}: {len(rows)} rows from {seen_sources} doc dir(s) -> {out}")


def merge_wide(base: Path, slug_dirs: list[Path]) -> None:
    dest_root = base / WIDE_DIR
    copied = 0
    collisions = 0
    for d in slug_dirs:
        src_root = d / WIDE_DIR
        if not src_root.exists():
            continue
        for src in src_root.rglob("*.csv"):
            rel = src.relative_to(src_root)
            dest = dest_root / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.exists():
                # Distinct documents shouldn't collide (filenames embed the pdf stem);
                # if they do, keep both by suffixing the source slug.
                collisions += 1
                dest = dest.with_name(f"{dest.stem}__{d.name[:20]}{dest.suffix}")
            shutil.copy2(src, dest)
            copied += 1
    print(f"  {WIDE_DIR}: copied {copied} grid file(s)"
          + (f" ({collisions} name collision(s) disambiguated)" if collisions else "")
          + f" -> {dest_root}")


def main() -> None:
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    base = Path(sys.argv[1]).resolve()
    slug_dirs = [base / s for s in sys.argv[2:]]
    missing = [str(d) for d in slug_dirs if not d.exists()]
    if missing:
        sys.exit(f"Error: per-doc output dir(s) not found: {missing}")
    base.mkdir(parents=True, exist_ok=True)
    print(f"Merging {len(slug_dirs)} doc dir(s) into {base}")
    for name in CSV_FILES:
        merge_csv(name, base, slug_dirs)
    merge_wide(base, slug_dirs)
    print("Merge complete.")


if __name__ == "__main__":
    main()
