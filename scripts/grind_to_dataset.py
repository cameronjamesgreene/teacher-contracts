#!/usr/bin/env python3
"""Turn the grind pipeline's JSONL into the CSV pair the rest of the project reads.

This is the seam between the two programs. `llm_extract.py` writes two files and
everything downstream is built on them:

    <OUT_DIR>/llm_main_dataset.csv   wide: 12 metadata columns, then
                                     <qid>_answer/_evidence/_page/_confidence x 106
    <OUT_DIR>/llm_coding_log.csv     long: one row per document-question pair

`salary_schedule.py` reads the wide file and runs only where
`pay_salary_schedule_001_answer` is yes; the audit workbooks read both. None of that
knows or cares which extractor produced the CSVs, so emitting the same two files from
the grind pipeline makes it a drop-in replacement rather than a parallel universe.

The field mapping is one-to-one, which is why this is an adapter and not a rewrite:

    question_id -> Question ID       answer     -> answer
    evidence    -> evidence          page       -> page number
    confidence  -> confidence        coder_notes-> coder notes

What the JSONL does not carry is the document metadata (district, state, document
type, effective years, union). That is derived, not extracted, so it comes from
`utils.build_metadata()` — the same function `llm_extract.py` calls, so the two
backends produce identical metadata for the same PDF.

Answers are normalised through `llm_extract._normalize_answer`, deliberately importing
the incumbent's own function rather than reimplementing it: if `ND` maps to
`not_discussed` on one backend it must map identically on the other, or the two are
not comparable and every downstream count silently depends on which one ran.

Usage:
    python3 scripts/grind_to_dataset.py output/extraction/results/*.jsonl
    CONTRACT_OUT_DIR=output_v12 python3 scripts/grind_to_dataset.py final.jsonl
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from llm_extract import _normalize_answer
from utils import OUT_DIR, WORK, Question, build_metadata, load_documents, read_codebook

MANIFEST = WORK / "output" / "extraction" / "corpus_manifest.csv"

# What a question gets when no variant answered it at all. Matches llm_extract's own
# fallback: an unanswered question is not_discussed with empty support, never blank.
FALLBACK = {"answer": "not_discussed", "evidence": "", "page": "",
            "confidence": "low", "coder_notes": ""}


def load_answers(paths: list[Path]) -> dict[str, dict[str, dict]]:
    """document_id -> question_id -> answer record.

    Later files and later lines win, so passing sweep then ensemble then a subset
    polish layers them in the order given, which is the same precedence the pipeline
    applies when it writes them.
    """
    documents: dict[str, dict[str, dict]] = {}
    for path in paths:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            document_id = record.get("document_id")
            if not document_id:
                continue
            answers = documents.setdefault(document_id, {})
            for answer in record.get("answers", []):
                if answer.get("question_id"):
                    answers[answer["question_id"]] = answer
    return documents


def manifest_rows() -> dict[str, dict[str, str]]:
    with MANIFEST.open(newline="", encoding="utf-8") as source:
        return {row["document_id"]: row for row in csv.DictReader(source)}


def metadata_for(document_id: str, rows: dict[str, dict[str, str]]) -> dict[str, str]:
    """The 12 derived metadata columns, from the same code path as llm_extract."""
    row = rows.get(document_id)
    if row is None:
        raise SystemExit(f"{document_id} is not in {MANIFEST.name}; cannot derive its "
                         f"metadata. Re-freeze the manifest first.")
    documents = load_documents([(row["district"], row["file_name"])])
    document = documents[0]
    if document.document_id != document_id:
        # The id is a hash of the PDF's path relative to ROOT. A mismatch means the
        # manifest and utils disagree about where the corpus lives, which would pair
        # one document's answers with another's metadata.
        raise SystemExit(f"manifest says {document_id} but utils derives "
                         f"{document.document_id} for the same district/file. "
                         f"Check PDF_ROOT in utils.py.")
    return build_metadata(document)


def write_outputs(questions: list[Question], documents: dict[str, dict[str, dict]],
                  out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    meta_fields = ["document_id", "file_name", "district_name", "state",
                   "document_type", "bargaining_unit", "start_year", "end_year",
                   "effective_dates", "school_years_covered", "union_name",
                   "source_document_notes"]
    wide_fields = meta_fields + [f"{question.qid}_{suffix}"
                                 for question in questions
                                 for suffix in ("answer", "evidence", "page", "confidence")]
    log_fields = ["document_id", "file_name", "Question ID", "topic category",
                  "question", "answer", "evidence", "page number", "confidence",
                  "coder notes"]

    rows = manifest_rows()
    wide_rows: list[dict] = []
    log_rows: list[dict] = []
    for document_id in sorted(documents):
        metadata = metadata_for(document_id, rows)
        coded = documents[document_id]
        wide = dict(metadata)
        for question in questions:
            cell = {**FALLBACK, **coded.get(question.qid, {})}
            cell["answer"] = _normalize_answer(cell["answer"]) or "not_discussed"
            wide[f"{question.qid}_answer"] = cell["answer"]
            wide[f"{question.qid}_evidence"] = cell["evidence"]
            wide[f"{question.qid}_page"] = cell["page"]
            wide[f"{question.qid}_confidence"] = cell["confidence"]
            log_rows.append({
                "document_id": metadata["document_id"],
                "file_name": metadata["file_name"],
                "Question ID": question.qid,
                "topic category": question.topic,
                "question": question.question,
                "answer": cell["answer"],
                "evidence": cell["evidence"],
                "page number": cell["page"],
                "confidence": cell["confidence"],
                "coder notes": cell.get("coder_notes", ""),
            })
        wide_rows.append(wide)

    main_path = out_dir / "llm_main_dataset.csv"
    log_path = out_dir / "llm_coding_log.csv"
    with main_path.open("w", newline="", encoding="utf-8") as target:
        writer = csv.DictWriter(target, fieldnames=wide_fields)
        writer.writeheader()
        writer.writerows(wide_rows)
    with log_path.open("w", newline="", encoding="utf-8") as target:
        writer = csv.DictWriter(target, fieldnames=log_fields)
        writer.writeheader()
        writer.writerows(log_rows)
    return main_path, log_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("jsonl", type=Path, nargs="+",
                        help="extractor output, in increasing order of precedence")
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR,
                        help="default: utils.OUT_DIR (set CONTRACT_OUT_DIR to change it)")
    args = parser.parse_args()

    missing = [path for path in args.jsonl if not path.exists()]
    if missing:
        raise SystemExit("no such file: " + ", ".join(str(path) for path in missing))

    questions = read_codebook()
    documents = load_answers(args.jsonl)
    if not documents:
        raise SystemExit("no records with a document_id in the given files")

    main_path, log_path = write_outputs(questions, documents, args.out_dir)

    answered = sum(1 for answers in documents.values() for answer in answers.values()
                   if _normalize_answer(answer.get("answer")) not in
                   ("", "not_discussed", "discussed_unclear", "not_applicable"))
    total = len(documents) * len(questions)
    print(f"{len(documents)} document(s) x {len(questions)} questions")
    print(f"  {answered}/{total} substantive answers ({answered / max(1, total):.1%})")
    print(f"  wide -> {main_path}")
    print(f"  long -> {log_path}")


if __name__ == "__main__":
    main()
