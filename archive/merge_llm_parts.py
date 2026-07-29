#!/usr/bin/env python3
"""Merge and validate LLM-coded part files for the sampled contracts."""

from __future__ import annotations

import csv
from pathlib import Path

from utils import OUT_DIR, Question, read_codebook


PART_DIR = OUT_DIR / "llm_parts"
MAIN_OUT = OUT_DIR / "llm_main_dataset.csv"
LOG_OUT = OUT_DIR / "llm_coding_log.csv"
REPORT_OUT = OUT_DIR / "llm_validation_report.txt"

METADATA_FIELDS = [
    "document_id",
    "file_name",
    "district_name",
    "state",
    "document_type",
    "bargaining_unit",
    "start_year",
    "end_year",
    "effective_dates",
    "school_years_covered",
    "union_name",
    "source_document_notes",
]

LOG_FIELDS = [
    "document_id",
    "file_name",
    "Question ID",
    "topic category",
    "question",
    "answer",
    "evidence",
    "page number",
    "confidence",
    "coder notes",
]


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return list(reader.fieldnames or []), list(reader)


def expected_main_fields(questions: list[Question]) -> list[str]:
    fields = METADATA_FIELDS[:]
    for q in questions:
        fields.extend(
            [
                f"{q.qid}_answer",
                f"{q.qid}_evidence",
                f"{q.qid}_page",
                f"{q.qid}_confidence",
            ]
        )
    return fields


def main() -> None:
    questions = read_codebook()
    question_ids = [q.qid for q in questions]
    expected_fields = expected_main_fields(questions)

    main_paths = sorted(PART_DIR.glob("worker_*_main.csv"))
    log_paths = sorted(PART_DIR.glob("worker_*_log.csv"))
    report: list[str] = []

    if not main_paths or not log_paths:
        raise SystemExit(f"No LLM part files found under {PART_DIR}")

    main_rows: list[dict[str, str]] = []
    log_rows: list[dict[str, str]] = []
    seen_documents: set[str] = set()

    for path in main_paths:
        header, rows = read_csv(path)
        missing = [field for field in expected_fields if field not in header]
        extras = [field for field in header if field not in expected_fields]
        report.append(f"{path}: {len(rows)} main rows")
        if missing:
            report.append(f"  missing main fields: {len(missing)}")
            report.extend(f"    {field}" for field in missing[:20])
        if extras:
            report.append(f"  extra main fields: {len(extras)}")
            report.extend(f"    {field}" for field in extras[:20])
        for row in rows:
            document_id = row.get("document_id", "")
            if document_id in seen_documents:
                report.append(f"  duplicate document_id in main files: {document_id}")
            seen_documents.add(document_id)
            normalized = {field: row.get(field, "") for field in expected_fields}
            main_rows.append(normalized)

    for path in log_paths:
        header, rows = read_csv(path)
        missing = [field for field in LOG_FIELDS if field not in header]
        report.append(f"{path}: {len(rows)} log rows")
        if missing:
            report.append(f"  missing log fields: {len(missing)}")
            report.extend(f"    {field}" for field in missing)
        for row in rows:
            normalized = {field: row.get(field, "") for field in LOG_FIELDS}
            log_rows.append(normalized)

    expected_log_rows = len(main_rows) * len(question_ids)
    report.append(f"merged main rows: {len(main_rows)}")
    report.append(f"merged log rows: {len(log_rows)}")
    report.append(f"question IDs: {len(question_ids)}")
    report.append(f"expected log rows: {expected_log_rows}")

    if len(log_rows) != expected_log_rows:
        report.append("WARNING: log row count does not equal documents times questions.")

    blank_answers = 0
    invalid_confidence = 0
    for row in main_rows:
        for qid in question_ids:
            if not row.get(f"{qid}_answer", "").strip():
                blank_answers += 1
            conf = row.get(f"{qid}_confidence", "").strip()
            if conf and conf not in {"high", "medium", "low"}:
                invalid_confidence += 1
    report.append(f"blank main answer cells: {blank_answers}")
    report.append(f"invalid confidence values: {invalid_confidence}")

    with MAIN_OUT.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=expected_fields)
        writer.writeheader()
        writer.writerows(main_rows)

    with LOG_OUT.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=LOG_FIELDS)
        writer.writeheader()
        writer.writerows(log_rows)

    REPORT_OUT.write_text("\n".join(report) + "\n", encoding="utf-8")
    print("\n".join(report))
    print(f"wrote {MAIN_OUT}")
    print(f"wrote {LOG_OUT}")
    print(f"wrote {REPORT_OUT}")


if __name__ == "__main__":
    main()
