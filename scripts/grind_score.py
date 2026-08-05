#!/usr/bin/env python3
"""Score extractor output against the hand-transcribed Manchester answer key.

No model calls and no human review, so a pipeline change can be evaluated in
seconds. The key (`output/grind/answer_gold.csv`) is transcribed from the 38
completed blinded reviews, where independent reviewers verified each provision
against the PDF.

Five deterministic checks per question:
  status    predicted discussion status matches the verified one
  required  every token a correct answer must contain is present
  complete  fraction of the material variations a complete answer would include
  page      reported page is one of the verified PDF pages for the clause
  evidence  quote appears contiguously in the document text

`overall` requires status, required, page and evidence together. Contiguity is
checked deliberately: the blinded review found ellipsis-stitched quotes that
`validate_batch` accepted because it tested per-fragment containment.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils import WORK

GOLD = WORK / "output" / "extraction" / "answer_gold.csv"
# Manchester remains the only document with a hand-verified key; --document-id points
# the scorer at another one once a key exists for it.
DOCUMENT_ID = "manchester_school_district__83__de5d62c9"
TEXT = WORK / "cache" / "extracted_text" / f"{DOCUMENT_ID}.txt"

MISSING = {"not_discussed", "not discussed", "discussed_unclear", "discussed unclear",
           "not_applicable", "not applicable", "no", "none", ""}
_NUMBER_WORDS = {
    "1": "one", "2": "two", "3": "three", "4": "four", "5": "five", "6": "six",
    "7": "seven", "8": "eight", "9": "nine", "10": "ten", "12": "twelve",
    "15": "fifteen", "20": "twenty", "30": "thirty", "45": "forty-five",
    "50": "fifty", "85": "eighty-five", "90": "ninety", "95": "ninety-five",
    "120": "one hundred and twenty",
}
_WS = re.compile(r"\s+")
_PAGE_NUM = re.compile(r"\d+")


def _norm(text: str) -> str:
    return _WS.sub(" ", text.replace("’", "'").replace("“", '"')
                   .replace("”", '"').casefold()).strip()


def classify(answer: str) -> str:
    """Map a free-text answer onto a discussion-status class."""
    normalized = _WS.sub("_", answer.strip().casefold())
    if normalized in {"not_discussed", "not_discussed."}:
        return "not_discussed"
    if normalized.startswith("discussed_unclear"):
        return "discussed_unclear"
    if normalized.startswith("not_applicable"):
        return "not_applicable"
    if normalized in {"no", "no.", "none", "none_specifically_cited"}:
        return "no"
    # "No, the document grants unpaid leave only" is a `no` verdict with its reasoning
    # attached, which is a better answer than a bare "no", not a substantive one. Requiring
    # punctuation after the word keeps value answers like "No more than 26 students" out.
    if re.match(r"^no\s*[,.;:—-]", answer.strip(), flags=re.I):
        return "no"
    if _WS.sub(" ", answer.strip().casefold()) in MISSING:
        return "not_discussed"
    return "substantive"


def token_present(token: str, haystack: str) -> bool:
    """Match a required token, allowing digit/spelled-number equivalence."""
    token = token.strip().casefold()
    if not token:
        return True
    if re.fullmatch(r"\d+(\.\d+)?", token):
        if re.search(rf"(?<![\d.]){re.escape(token)}(?![\d])", haystack):
            return True
        word = _NUMBER_WORDS.get(token)
        return bool(word and word in haystack)
    return token in haystack


def _pages(field: str) -> set[int]:
    return {int(value) for value in field.split(";") if value.strip()}


def _tokens(field: str) -> list[str]:
    return [value.strip() for value in field.split(";") if value.strip()]


def _document_text(document_id: str) -> str:
    """Page-delimited text for the document being scored."""
    if document_id == DOCUMENT_ID:
        return TEXT.read_text(encoding="utf-8", errors="ignore")
    from grind_retrieve import load_document
    return load_document(document_id).text_path.read_text(encoding="utf-8", errors="ignore")


def load_gold(path: Path = GOLD) -> dict[str, dict]:
    gold = {}
    for row in csv.DictReader(path.open(newline="", encoding="utf-8")):
        gold[row["question_id"]] = {
            "status": row["gold_status"],
            "required": _tokens(row["required"]),
            "optional": _tokens(row["optional"]),
            "pages": _pages(row["gold_pages"]),
            "provision": row["provision"],
        }
    return gold


def load_jsonl(path: Path) -> dict[str, dict]:
    answers = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        batch = json.loads(line)
        for answer in batch.get("answers", []):
            answers[answer["question_id"]] = answer
    return answers


def load_baseline_csv(path: Path) -> dict[str, dict]:
    answers = {}
    with path.open(newline="", encoding="utf-8") as source:
        for row in csv.DictReader(source):
            if row.get("document_id") not in (None, "", DOCUMENT_ID):
                continue
            answers[row["Question ID"]] = {
                "question_id": row["Question ID"],
                "answer": row.get("answer", ""),
                "evidence": row.get("evidence", ""),
                "page": row.get("page number", ""),
            }
    return answers


def score(answers: dict[str, dict], gold: dict[str, dict],
          document_text: str) -> tuple[dict, list[dict]]:
    pages = document_text.split("\f")
    page_text = {index: _norm(block) for index, block in enumerate(pages, start=1)}
    rows: list[dict] = []
    for qid, expected in gold.items():
        record = answers.get(qid)
        answer_text = _norm(record.get("answer", "")) if record else ""
        evidence = (record.get("evidence", "") or "") if record else ""
        haystack = f"{answer_text} {_norm(evidence)}"
        predicted = classify(record.get("answer", "")) if record else "not_discussed"

        if expected["status"] in {"yes", "value"}:
            status_ok = predicted == "substantive"
        else:
            status_ok = predicted == expected["status"]

        # Required tokens only bind a substantive answer; a wrong absence claim is
        # already penalised by status, and double-counting would exaggerate the gap.
        if status_ok and predicted == "substantive":
            required_ok = all(token_present(token, haystack) for token in expected["required"])
            optional_hits = sum(1 for token in expected["optional"]
                                if token_present(token, haystack))
        else:
            required_ok = not expected["required"] and status_ok
            optional_hits = 0
        complete = (optional_hits / len(expected["optional"])) if expected["optional"] else 1.0

        # Reported pages arrive in many shapes: "34", "pp. 12-13", "not_applicable".
        reported = ({int(value) for value in _PAGE_NUM.findall(record.get("page", "") or "")}
                    if record else set())
        if expected["status"] in {"not_discussed"}:
            page_ok = True
        else:
            page_ok = bool(reported & expected["pages"])

        normalized_evidence = _norm(evidence)
        if predicted != "substantive":
            evidence_ok = True
        elif len(normalized_evidence) < 15:
            evidence_ok = False
        else:
            evidence_ok = any(normalized_evidence in block for block in page_text.values())

        overall = bool(status_ok and required_ok and page_ok and evidence_ok)
        rows.append({
            "question_id": qid, "gold_status": expected["status"],
            "predicted": predicted, "status_ok": int(status_ok),
            "required_ok": int(bool(required_ok)), "complete": round(complete, 3),
            "page_ok": int(page_ok), "evidence_ok": int(evidence_ok),
            "overall": int(overall),
            "answer": (record.get("answer", "")[:120] if record else "<missing>"),
        })
    total = len(rows) or 1
    summary = {
        "questions": len(rows),
        "status": round(sum(r["status_ok"] for r in rows) / total, 4),
        "required": round(sum(r["required_ok"] for r in rows) / total, 4),
        "completeness": round(sum(r["complete"] for r in rows) / total, 4),
        "page": round(sum(r["page_ok"] for r in rows) / total, 4),
        "evidence": round(sum(r["evidence_ok"] for r in rows) / total, 4),
        "overall": round(sum(r["overall"] for r in rows) / total, 4),
    }
    return summary, rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jsonl", type=Path, action="append", default=[])
    parser.add_argument("--baseline-csv", type=Path)
    parser.add_argument("--label", action="append", default=[])
    parser.add_argument("--out", type=Path)
    parser.add_argument("--detail", type=Path, help="write per-question rows for one input")
    parser.add_argument("--gold", type=Path, default=GOLD, help="answer key to score against")
    parser.add_argument("--document-id", default=DOCUMENT_ID)
    args = parser.parse_args()

    gold = load_gold(args.gold)
    document_text = _document_text(args.document_id)
    inputs: list[tuple[str, dict]] = []
    for index, path in enumerate(args.jsonl):
        label = args.label[index] if index < len(args.label) else path.stem
        inputs.append((label, load_jsonl(path)))
    if args.baseline_csv:
        inputs.append(("baseline", load_baseline_csv(args.baseline_csv)))

    report = {}
    detail_rows: list[dict] = []
    for label, answers in inputs:
        summary, rows = score(answers, gold, document_text)
        report[label] = summary
        detail_rows = rows
        print(f"{label:34s} overall={summary['overall']:.3f} status={summary['status']:.3f} "
              f"req={summary['required']:.3f} cov={summary['completeness']:.3f} "
              f"page={summary['page']:.3f} ev={summary['evidence']:.3f}")
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if args.detail and detail_rows:
        args.detail.parent.mkdir(parents=True, exist_ok=True)
        with args.detail.open("w", newline="", encoding="utf-8") as target:
            writer = csv.DictWriter(target, fieldnames=list(detail_rows[0]))
            writer.writeheader()
            writer.writerows(detail_rows)


if __name__ == "__main__":
    main()
