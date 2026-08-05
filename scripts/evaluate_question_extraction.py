#!/usr/bin/env python3
"""Create and score reproducible A/B evaluations of contract-question extractors.

This tool intentionally does not declare an LLM winner from agreement alone. It
creates a human-reviewable, blinded packet from a frozen corpus manifest and two
extractor outputs, then scores the completed packet with its private key.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable

sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils import PDF_ROOT, WORK, load_documents, read_codebook

ANSWER_FIELDS = ("answer", "evidence", "page", "confidence", "coder_notes")
REVIEW_FIELDS = ("status", "value", "evidence", "page", "overall")
VALID_REVIEW_VALUES = {"yes", "no", "na", ""}
_PAGE_NUMBER_RE = re.compile(r"\d+")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _all_documents() -> list[tuple[str, str]]:
    return [
        (district.name, pdf.name)
        for district in sorted(PDF_ROOT.iterdir())
        if district.is_dir()
        for pdf in sorted(district.glob("*.pdf"))
    ]


def write_manifest(path: Path) -> None:
    """Write source and extracted-text checksums for every locally available PDF."""
    docs = load_documents(_all_documents())
    rows = []
    for doc in docs:
        rows.append({
            "document_id": doc.document_id,
            "district": doc.district,
            "file_name": doc.file_name,
            "source_path": str(doc.path),
            "pdf_sha256": _sha256_file(doc.path),
            "text_path": str(doc.text_path),
            "text_sha256": hashlib.sha256(doc.text.encode("utf-8")).hexdigest(),
            "pdf_pages": doc.page_count or 0,
            "text_characters": len(doc.text),
            "text_status": doc.text_status,
        })
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=list(rows[0]) if rows else [])
        writer.writeheader()
        writer.writerows(rows)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as source:
        return list(csv.DictReader(source))


def _size_bucket(row: dict[str, str]) -> str:
    pages = int(row["pdf_pages"] or 0)
    if pages <= 10:
        return "short"
    if pages <= 100:
        return "medium"
    return "long"


def select_documents(manifest: Path, count: int, seed: int) -> list[dict[str, str]]:
    """Select a deterministic spread of text status and document length buckets."""
    rows = _read_csv(manifest)
    usable = [row for row in rows if row["text_status"] == "usable"]
    if count > len(usable):
        raise ValueError(f"Requested {count} usable documents; manifest contains {len(usable)}")
    buckets: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in usable:
        buckets[(row["text_status"], _size_bucket(row))].append(row)
    rng = random.Random(seed)
    for values in buckets.values():
        rng.shuffle(values)
    ordered_buckets = [bucket for bucket in sorted(buckets) if buckets[bucket]]
    selected: list[dict[str, str]] = []
    while len(selected) < count:
        progressed = False
        for bucket in ordered_buckets:
            if buckets[bucket] and len(selected) < count:
                selected.append(buckets[bucket].pop())
                progressed = True
        if not progressed:
            break
    return selected


def write_question_template(manifest: Path, output: Path, count: int, seed: int) -> None:
    """Create one human-adjudication row per selected document/question pair."""
    selected = select_documents(manifest, count, seed)
    questions = read_codebook()
    rows = []
    for doc in selected:
        for question in questions:
            rows.append({
                "document_id": doc["document_id"],
                "district": doc["district"],
                "file_name": doc["file_name"],
                "text_status": doc["text_status"],
                "question_id": question.qid,
                "question": question.question,
                "answer_type": question.answer_type,
                "keywords": question.keywords,
                "expected_answer": "",
                "expected_evidence": "",
                "expected_page": "",
                "adjudicator_notes": "",
            })
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as target:
        writer = csv.DictWriter(target, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _load_baseline(path: Path) -> dict[tuple[str, str], dict[str, str]]:
    """Load the existing long CSV shape emitted by llm_extract.py."""
    rows = _read_csv(path)
    answers = {}
    for row in rows:
        key = (row["document_id"], row["Question ID"])
        answers[key] = {
            "answer": row.get("answer", ""),
            "evidence": row.get("evidence", ""),
            "page": row.get("page number", ""),
            "confidence": row.get("confidence", ""),
            "coder_notes": row.get("coder notes", ""),
        }
    return answers


def _load_candidate(path: Path) -> dict[tuple[str, str], dict[str, str]]:
    """Load the JSONL shape emitted by llm_extract_fts.py."""
    answers = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        batch = json.loads(line)
        for answer in batch["answers"]:
            key = (batch["document_id"], answer["question_id"])
            answers[key] = {
                "answer": answer.get("answer", ""),
                "evidence": answer.get("evidence", ""),
                "page": answer.get("page", ""),
                "confidence": answer.get("confidence", ""),
                "coder_notes": answer.get("coder_notes", ""),
            }
    return answers


def _review_id(document_id: str, question_id: str) -> str:
    return hashlib.sha256(f"{document_id}\0{question_id}".encode()).hexdigest()[:16]


def make_blinded_packet(template: Path, baseline: Path, candidate: Path, packet: Path, key_path: Path, seed: int) -> None:
    """Randomly assign baseline/candidate outputs to A/B without exposing mapping."""
    base = _load_baseline(baseline)
    alt = _load_candidate(candidate)
    rng = random.Random(seed)
    packet_rows: list[dict[str, str]] = []
    key_rows: list[dict[str, str]] = []
    for row in _read_csv(template):
        pair = (row["document_id"], row["question_id"])
        if pair not in base or pair not in alt:
            continue
        a_is_baseline = bool(rng.randrange(2))
        first, second = (base[pair], alt[pair]) if a_is_baseline else (alt[pair], base[pair])
        review = {
            "review_id": _review_id(*pair),
            "document_id": row["document_id"],
            "district": row["district"],
            "file_name": row["file_name"],
            "question_id": row["question_id"],
            "question": row["question"],
        }
        for label, answer in (("a", first), ("b", second)):
            for field in ANSWER_FIELDS:
                review[f"{label}_{field}"] = answer[field]
            for field in REVIEW_FIELDS:
                review[f"{label}_{field}_correct"] = ""
        review["reviewer_notes"] = ""
        packet_rows.append(review)
        key_rows.append({"review_id": review["review_id"], "a_system": "baseline" if a_is_baseline else "candidate"})
    if not packet_rows:
        raise ValueError("No overlapping document/question pairs between template and both outputs")
    packet.parent.mkdir(parents=True, exist_ok=True)
    with packet.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=list(packet_rows[0]))
        writer.writeheader()
        writer.writerows(packet_rows)
    with key_path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=["review_id", "a_system"])
        writer.writeheader()
        writer.writerows(key_rows)


def _source_excerpt(text_path: Path, page_fields: Iterable[str], radius: int = 1) -> str:
    """Return cited PDF pages and immediate neighbors from form-feed text."""
    text = text_path.read_text(encoding="utf-8", errors="ignore")
    pages = text.split("\f")
    cited = {int(value) for field in page_fields for value in _PAGE_NUMBER_RE.findall(field)}
    selected = {page for cited_page in cited for page in range(cited_page - radius, cited_page + radius + 1)}
    excerpts = []
    for page_number in sorted(page for page in selected if 1 <= page <= len(pages)):
        page = pages[page_number - 1].strip()
        if page:
            excerpts.append(f"### PDF page {page_number}\n{page[:8000]}")
    return "\n\n".join(excerpts) or "No cited page was supplied. Search the document before deciding."


def write_review_tasks(packet: Path, manifest: Path, db_path: Path, task_dir: Path) -> int:
    """Write source-grounded, anonymized reviewer tasks and return task count.

    The task gives reviewers cited-page text for fast verification and explicit
    document-scoped FTS commands for investigating absence claims. It never exposes
    the A/B-to-system mapping.
    """
    by_document = {row["document_id"]: row for row in _read_csv(manifest)}
    task_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    for row in _read_csv(packet):
        source = by_document.get(row["document_id"])
        if source is None:
            raise ValueError(f"Document {row['document_id']} is absent from manifest")
        response_path = task_dir / f"{row['review_id']}.response.json"
        task_path = task_dir / f"{row['review_id']}.task.md"
        excerpt = _source_excerpt(Path(source["text_path"]), (row["a_page"], row["b_page"]))
        lines = [
            f"# Blinded contract-answer review: {row['review_id']}",
            "",
            "## Source of truth",
            f"- PDF: `{source['source_path']}`",
            f"- Extracted page-delimited text: `{source['text_path']}`",
            f"- Text status: `{source['text_status']}`",
            "",
            "The PDF and document text are authoritative. A and B are anonymized; do not infer which system produced either.",
            "",
            "## Question",
            f"- ID: `{row['question_id']}`",
            row["question"],
            "",
            "## Candidate A",
            f"- Answer: {row['a_answer']}",
            f"- Evidence: {row['a_evidence']}",
            f"- Page: {row['a_page']}",
            "",
            "## Candidate B",
            f"- Answer: {row['b_answer']}",
            f"- Evidence: {row['b_evidence']}",
            f"- Page: {row['b_page']}",
            "",
            "## Cited-page excerpts",
            excerpt,
            "",
            "## Required review procedure",
            "1. Check each substantive quote against the PDF/text and its reported PDF page.",
            "2. Check that the clause applies to the requested teacher/certificated unit and supports the answer, not merely a related topic.",
            "3. For a `not_discussed` or `no` answer, search the full document before accepting absence. Use:",
            f"   `python3 scripts/contract_search.py --db {db_path} search --document-id {row['document_id']} \"<terms>\" --limit 10`",
            "4. Mark yes/no/na independently for status, value, evidence, page, and overall correctness.",
            "",
            "## Response JSON",
            "Write only this JSON shape to:",
            f"`{response_path}`",
            "```json",
            json.dumps({
                "review_id": row["review_id"],
                "a": {field: "yes|no|na" for field in REVIEW_FIELDS},
                "b": {field: "yes|no|na" for field in REVIEW_FIELDS},
                "reviewer_notes": "short source-grounded explanation",
            }, indent=2),
            "```",
        ]
        task_path.write_text("\n".join(lines), encoding="utf-8")
        count += 1
    return count


def apply_review_responses(packet: Path, task_dir: Path, output: Path) -> int:
    """Copy completed independent-agent decisions into a scoring packet."""
    rows = _read_csv(packet)
    completed = 0
    for row in rows:
        response_path = task_dir / f"{row['review_id']}.response.json"
        if not response_path.exists():
            continue
        response = json.loads(response_path.read_text(encoding="utf-8"))
        if response.get("review_id") != row["review_id"]:
            raise ValueError(f"Response ID mismatch in {response_path}")
        for label in ("a", "b"):
            verdict = response.get(label, {})
            for field in REVIEW_FIELDS:
                value = verdict.get(field, "")
                if value not in VALID_REVIEW_VALUES - {""}:
                    raise ValueError(f"Invalid {label}.{field}={value!r} in {response_path}")
                row[f"{label}_{field}_correct"] = value
        row["reviewer_notes"] = str(response.get("reviewer_notes", ""))
        completed += 1
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as target:
        writer = csv.DictWriter(target, fieldnames=list(rows[0]) if rows else [])
        writer.writeheader()
        writer.writerows(rows)
    return completed


def score_packet(packet: Path, key_path: Path, output: Path) -> None:
    """Aggregate blinded human review; blank/NA labels are excluded per metric."""
    key = {row["review_id"]: row["a_system"] for row in _read_csv(key_path)}
    totals: dict[str, Counter[str]] = {field: Counter() for field in REVIEW_FIELDS}
    comparisons = Counter()
    for row in _read_csv(packet):
        a_system = key[row["review_id"]]
        b_system = "candidate" if a_system == "baseline" else "baseline"
        for field in REVIEW_FIELDS:
            values = {a_system: row[f"a_{field}_correct"], b_system: row[f"b_{field}_correct"]}
            for system, value in values.items():
                if value not in VALID_REVIEW_VALUES:
                    raise ValueError(f"Invalid {field} value {value!r} for {row['review_id']}")
                if value in {"yes", "no"}:
                    totals[field][f"{system}_{value}"] += 1
            if field == "overall" and values["baseline"] in {"yes", "no"} and values["candidate"] in {"yes", "no"}:
                comparisons[f"baseline_{values['baseline']}_candidate_{values['candidate']}"] += 1
    report = {
        "metrics": {
            field: {
                system: {
                    "correct": totals[field][f"{system}_yes"],
                    "incorrect": totals[field][f"{system}_no"],
                    "accuracy": totals[field][f"{system}_yes"] /
                    max(1, totals[field][f"{system}_yes"] + totals[field][f"{system}_no"]),
                }
                for system in ("baseline", "candidate")
            }
            for field in REVIEW_FIELDS
        },
        "paired_overall": dict(comparisons),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    manifest = sub.add_parser("manifest")
    manifest.add_argument("--out", type=Path, required=True)
    template = sub.add_parser("template")
    template.add_argument("--manifest", type=Path, required=True)
    template.add_argument("--out", type=Path, required=True)
    template.add_argument("--documents", type=int, default=12)
    template.add_argument("--seed", type=int, default=20260323)
    packet = sub.add_parser("packet")
    packet.add_argument("--template", type=Path, required=True)
    packet.add_argument("--baseline", type=Path, required=True)
    packet.add_argument("--candidate", type=Path, required=True)
    packet.add_argument("--out", type=Path, required=True)
    packet.add_argument("--key", type=Path, required=True)
    packet.add_argument("--seed", type=int, default=20260323)
    tasks = sub.add_parser("tasks", help="write source-grounded blinded review tasks")
    tasks.add_argument("--packet", type=Path, required=True)
    tasks.add_argument("--manifest", type=Path, required=True)
    tasks.add_argument("--db", type=Path, required=True)
    tasks.add_argument("--task-dir", type=Path, required=True)
    collect = sub.add_parser("collect", help="apply completed task response JSON files")
    collect.add_argument("--packet", type=Path, required=True)
    collect.add_argument("--task-dir", type=Path, required=True)
    collect.add_argument("--out", type=Path, required=True)
    score = sub.add_parser("score")
    score.add_argument("--packet", type=Path, required=True)
    score.add_argument("--key", type=Path, required=True)
    score.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "manifest":
        write_manifest(args.out)
    elif args.command == "template":
        write_question_template(args.manifest, args.out, args.documents, args.seed)
    elif args.command == "packet":
        make_blinded_packet(args.template, args.baseline, args.candidate, args.out, args.key, args.seed)
    elif args.command == "tasks":
        print(f"Wrote {write_review_tasks(args.packet, args.manifest, args.db, args.task_dir)} review tasks")
    elif args.command == "collect":
        print(f"Collected {apply_review_responses(args.packet, args.task_dir, args.out)} completed reviews")
    else:
        score_packet(args.packet, args.key, args.out)


if __name__ == "__main__":
    main()
