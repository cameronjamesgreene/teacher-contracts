#!/usr/bin/env python3
"""Audit extractor output for citation integrity, with no answer key required.

This is the check that scales. Accuracy needs a hand-built key and so is limited to a
sample, but three properties can be verified mechanically on every answer of every
document:

  verbatim    the quote appears in the document at all
  contiguous  it is one unbroken span, not fragments stitched across a gap
  on_page     it appears on the page the answer reports

**This is not an accuracy metric and must never be quoted as one.** It cannot tell
whether the answer interprets the quote correctly, whether a better provision was
missed, or whether an absence claim is right. It is also trivially gamed by abstention:
a run that answers `not_discussed` everywhere scores a perfect 1.000. So integrity is
always reported beside `coverage`, the share of questions actually answered, and the two
must be read together.

Use it to catch regressions and to spot documents where the pipeline is quietly failing
— an unusually low coverage or a sudden integrity drop is a signal worth investigating
before any accuracy work is spent there.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from grind_retrieve import load_document, norm
from grind_score import classify
from utils import WORK, read_codebook

_ELLIPSIS = re.compile(r"\.\.\.|…|\[\.\.\.\]")
_PAGE_NUM = re.compile(r"\d+")


def audit_file(path: Path) -> dict | None:
    """Audit one result file, or return None if it is not one.

    The extractors checkpoint to `<name>.prog.jsonl` beside their output, so an
    ordinary `results/*.jsonl` glob picks up progress files that carry no
    document_id. Aborting the whole batch on one of those made the natural command
    unusable; the file is skipped and the caller reports it instead.
    """
    records: list[dict] = []
    document_id = ""
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        batch = json.loads(line)
        document_id = batch.get("document_id") or document_id
        records.extend(batch.get("answers", []))
    if not document_id:
        return None

    document = load_document(document_id)
    pages = [norm(block) for block in document.pages()]
    # Join with a single space: norm() already collapsed the form feeds, so a literal
    # separator here would make any quote spanning a page break look fabricated.
    whole = " ".join(pages)

    total = len(records)
    substantive = verbatim = contiguous = on_page = 0
    flagged_ungrounded = 0
    unsupported: list[str] = []
    for record in records:
        if classify(record.get("answer", "")) != "substantive":
            continue
        substantive += 1
        if "ungrounded" in (record.get("coder_notes") or ""):
            flagged_ungrounded += 1
        quote = norm(record.get("evidence", ""))
        if len(quote) < 15:
            unsupported.append(f"{record['question_id']}: evidence too short")
            continue
        stitched = bool(_ELLIPSIS.search(record.get("evidence", "") or ""))
        found_anywhere = quote in whole
        if found_anywhere:
            verbatim += 1
        else:
            unsupported.append(f"{record['question_id']}: quote not in document")
            continue
        page_hit = next((index for index, block in enumerate(pages, start=1)
                         if quote in block), None)
        if page_hit is not None and not stitched:
            contiguous += 1
        elif stitched:
            unsupported.append(f"{record['question_id']}: quote is stitched")
        reported = {int(value) for value in
                    _PAGE_NUM.findall(record.get("page", "") or "")}
        if page_hit is not None and page_hit in reported:
            on_page += 1
        elif page_hit is not None:
            unsupported.append(
                f"{record['question_id']}: quote on page {page_hit}, reported {sorted(reported)}")

    def rate(numerator: int) -> float:
        return round(numerator / substantive, 4) if substantive else 0.0

    return {
        "document_id": document_id,
        "district": document.district,
        "pdf_pages": document.page_count,
        "questions": total,
        "substantive": substantive,
        "coverage": round(substantive / total, 4) if total else 0.0,
        "self_flagged_ungrounded": flagged_ungrounded,
        "verbatim": rate(verbatim),
        "contiguous": rate(contiguous),
        "on_page": rate(on_page),
        "problems": unsupported[:12],
        "problem_count": len(unsupported),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("jsonl", type=Path, nargs="+")
    parser.add_argument("--out", type=Path, help="write the per-document report as CSV")
    args = parser.parse_args()

    expected = len(read_codebook())
    audited = [(path, audit_file(path)) for path in args.jsonl]
    skipped = [path for path, report in audited if report is None]
    reports = [report for _, report in audited if report is not None]
    for path in skipped:
        print(f"skipping {path.name}: no document_id (a progress/checkpoint file?)")
    if not reports:
        raise SystemExit("no auditable result files given")
    print(f"{'district':30s} {'pp':>5s} {'answered':>9s} {'cover':>6s} "
          f"{'verbatim':>9s} {'contig':>7s} {'on_page':>8s} {'unground':>9s}")
    for report in reports:
        print(f"{report['district'][:30]:30s} {report['pdf_pages']:>5} "
              f"{report['substantive']:>4}/{report['questions']:<4} "
              f"{report['coverage']:>6.3f} {report['verbatim']:>9.3f} "
              f"{report['contiguous']:>7.3f} {report['on_page']:>8.3f} "
              f"{report['self_flagged_ungrounded']:>9}")
        if report["questions"] != expected:
            print(f"    ! answered {report['questions']} of {expected} codebook questions")
        for problem in report["problems"]:
            print(f"    - {problem}")
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        fields = [key for key in reports[0] if key != "problems"]
        with args.out.open("w", newline="", encoding="utf-8") as target:
            writer = csv.DictWriter(target, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(reports)
        print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
