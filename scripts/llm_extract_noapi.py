#!/usr/bin/env python3
"""LLM contract extraction — agent-run variant, no OpenAI API key required.

Same goal and outputs as llm_extract.py, but instead of this script calling the
OpenAI API itself, it delegates the actual reading-and-coding step to whatever
coding agent (Claude Code, Codex, etc.) is running it. For each document and
stage it writes the full instructions and document text to a task file, then
stops. The agent reads the task, produces the JSON answer itself, writes it to
the response path named in the task file, and re-runs this script to continue.

llm_extract.py batches each document into 11 small category-batch API calls per
stage (22 calls/document) to keep individual prompts small for the API. That is
impractical as a manual agent loop, so this variant asks one stage-1 task and
one stage-2 (audit) task per document, covering the full question bank each
time — 2 tasks/document instead of 22. A capable agent reading a whole document
once and answering every question together is a reasonable fit for this; it
also means each task's prompt is large (the full codebook), so the agent needs
enough context budget to read it.

Outputs (identical shape to llm_extract.py):
  output/llm_main_dataset.csv
  output/llm_coding_log.csv

Usage (run repeatedly; each run does as much as it can, then stops at the next
task that needs the agent's own answer):
    python3 llm_extract_noapi.py
    python3 llm_extract_noapi.py --max-docs 3      # limit for a quick test
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils import OUT_DIR, WORK, Document, Question, build_metadata, load_documents, read_codebook, read_sample
from agent_task import AgentTaskPending, run_task

TASK_DIR = WORK / "cache" / "llm_extract_tasks"
CACHE_DIR = WORK / "cache" / "llm_cache_noapi"

# Set to an integer to limit a run from the CLI default; None processes all documents.
MAX_DOCS_DEFAULT = 40
MAX_TEXT_CHARS = 180_000

STAGE1_INSTRUCTIONS = """\
You are an expert researcher extracting structured data from a U.S. public school \
district employment document — a collective bargaining agreement, employee handbook, \
salary schedule, policy manual, tentative agreement, or settlement summary.

You will be given the full text of one document and the full question bank (every \
Question ID). For each question:

STEP 1 — RETRIEVE: Search the document for every passage plausibly relevant to \
this question. Note the page or section reference.

STEP 2 — CODE: Answer the question using ONLY the passages you retrieved in \
Step 1. Do not draw on outside knowledge of this district or document. If no \
relevant passage was found, code not_discussed.

Return a JSON object where each key is a Question ID and each value has exactly:
  "answer"     — extracted value, or one of:
                 not_discussed | discussed_unclear | not_applicable | ocr_needed
  "evidence"   — short verbatim quote supporting the answer; empty string if not_discussed
  "page"       — page number as a string; "not_applicable" if not discussed
  "confidence" — preliminary rating: high | medium | low

Coding rules:
  • not_discussed: topic is genuinely absent from this document.
  • discussed_unclear: topic appears but cannot be coded specifically.
  • not_applicable: question does not apply to this document type or unit.
  • For yes/no questions answer "yes" or "no" based on document text only.
  • Quote evidence verbatim. Note when a provision appears to restate statute
    rather than a district-negotiated benefit.
  • If a provision varies by year, employee type, step, lane, or classification,
    extract the variation compactly.

Return ONLY a valid JSON object — no markdown fences, no explanation. Cover every \
Question ID given to you; do not skip any.\
"""

STAGE2_INSTRUCTIONS = """\
You are auditing your own (or another coder's) Stage 1 coded answers for accuracy \
and consistency, for every Question ID in the document's question bank.

For each answer:
1. Re-read the quoted evidence.
2. Ask: "Does this evidence EXPLICITLY support the coded answer, or is it
   indirect, ambiguous, or only weakly relevant?"
3. Revise if needed:
   — If the evidence is weak, ambiguous, or only tangentially related, change
     the answer to discussed_unclear.
   — If no actual supporting evidence was quoted, change to not_discussed.
   — If the answer overstates what the evidence says (e.g., codes "yes" when
     the passage only implies it), revise to discussed_unclear.
   — Preserve "no" answers when the document explicitly states a provision does
     not exist or is not provided.
4. Assign or revise the confidence rating:
   — high: evidence directly and unambiguously states the answer.
   — medium: evidence strongly suggests the answer but requires minor inference.
   — low: evidence is indirect, partially readable, or required significant
     inference.
5. Record any corrections or reasoning in "coder_notes". Leave empty if no
   change was made.

Return a JSON object where each key is a Question ID and each value has:
  "answer", "evidence", "page", "confidence", "coder_notes"

Return ONLY a valid JSON object — no markdown fences, no explanation. Cover every \
Question ID given to you; do not skip any.\
"""

_FALLBACK: dict[str, str] = {
    "answer": "not_discussed",
    "evidence": "",
    "page": "not_applicable",
    "confidence": "low",
    "coder_notes": "",
}


# ── prompt builders ──────────────────────────────────────────────────────────────

def build_stage1_input(doc: Document, questions: list[Question], doc_text: str) -> str:
    q_list = [
        {
            "id": q.qid,
            "topic": q.topic,
            "question": q.question,
            "answer_type": q.answer_type,
            "extract_if_discussed": q.extract,
            "keywords": q.keywords,
            "notes": q.notes,
        }
        for q in questions
    ]
    return (
        f"Document: {doc.file_name}\n"
        f"District: {doc.district}\n\n"
        f"QUESTIONS:\n{json.dumps(q_list, indent=2)}\n\n"
        "---BEGIN DOCUMENT---\n"
        + doc_text
        + "\n---END DOCUMENT---\n\n"
        "Answer every question above using only passages retrieved from the document. "
        "Return only the JSON object."
    )


def build_stage2_input(questions: list[Question], stage1: dict[str, dict]) -> str:
    audit_input = {
        q.qid: {
            "question": q.question,
            **{k: stage1.get(q.qid, _FALLBACK).get(k, v) for k, v in _FALLBACK.items() if k != "coder_notes"},
        }
        for q in questions
    }
    return f"STAGE 1 RESULTS:\n{json.dumps(audit_input, indent=2)}\n\nAudit every answer. Return only the JSON object."


# ── per-document pipeline ────────────────────────────────────────────────────────

def process_document(doc: Document, questions: list[Question], cache_path: Path) -> dict[str, dict]:
    if cache_path.exists():
        return json.loads(cache_path.read_text(encoding="utf-8"))

    doc_text = doc.text[:MAX_TEXT_CHARS]
    if len(doc.text) > MAX_TEXT_CHARS:
        doc_text += "\n\n[Document truncated at character limit — questions about content beyond this point may return not_discussed]"

    s1 = run_task(
        f"{doc.document_id}__stage1",
        STAGE1_INSTRUCTIONS,
        build_stage1_input(doc, questions, doc_text),
        TASK_DIR,
    )
    s2 = run_task(
        f"{doc.document_id}__stage2",
        STAGE2_INSTRUCTIONS,
        build_stage2_input(questions, s1),
        TASK_DIR,
    )

    merged: dict[str, dict] = {}
    for q in questions:
        result = dict(_FALLBACK)
        for src in (s1.get(q.qid, {}), s2.get(q.qid, {})):
            result.update({k: v for k, v in src.items() if v is not None and (v != "" or k == "coder_notes")})
        if not result.get("answer"):
            result["answer"] = "not_discussed"
        merged[q.qid] = result

    CACHE_DIR.mkdir(exist_ok=True)
    cache_path.write_text(json.dumps(merged, indent=2, ensure_ascii=False), encoding="utf-8")
    return merged


# ── output writers (same shape as llm_extract.py) ────────────────────────────────

def write_outputs(questions: list[Question], results: list[tuple[Document, dict, dict[str, dict]]]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    meta_fields = [
        "document_id", "file_name", "district_name", "state",
        "document_type", "bargaining_unit", "start_year", "end_year",
        "effective_dates", "school_years_covered", "union_name",
        "source_document_notes",
    ]
    wide_fields = meta_fields + [
        f"{q.qid}_{suffix}" for q in questions for suffix in ("answer", "evidence", "page", "confidence")
    ]
    log_fields = [
        "document_id", "file_name", "Question ID", "topic category",
        "question", "answer", "evidence", "page number", "confidence", "coder notes",
    ]

    wide_rows: list[dict] = []
    log_rows: list[dict] = []

    for doc, metadata, coded in results:
        wide = dict(metadata)
        for q in questions:
            cell = {**_FALLBACK, **coded.get(q.qid, {})}
            wide[f"{q.qid}_answer"] = cell["answer"]
            wide[f"{q.qid}_evidence"] = cell["evidence"]
            wide[f"{q.qid}_page"] = cell["page"]
            wide[f"{q.qid}_confidence"] = cell["confidence"]
            log_rows.append({
                "document_id":    metadata["document_id"],
                "file_name":      metadata["file_name"],
                "Question ID":    q.qid,
                "topic category": q.topic,
                "question":       q.question,
                "answer":         cell["answer"],
                "evidence":       cell["evidence"],
                "page number":    cell["page"],
                "confidence":     cell["confidence"],
                "coder notes":    cell.get("coder_notes", ""),
            })
        wide_rows.append(wide)

    main_path = OUT_DIR / "llm_main_dataset.csv"
    log_path = OUT_DIR / "llm_coding_log.csv"

    with main_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=wide_fields)
        w.writeheader()
        w.writerows(wide_rows)

    with log_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=log_fields)
        w.writeheader()
        w.writerows(log_rows)

    print(f"  {len(wide_rows)} document rows  -> {main_path}")
    print(f"  {len(log_rows)} log rows        -> {log_path}")


# ── entry point ───────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-docs", type=int, default=MAX_DOCS_DEFAULT)
    parser.add_argument(
        "--doc", action="append", metavar="DISTRICT|FILE.pdf",
        help="Process specific document(s) instead of the default 40-doc sample. "
             "May be repeated. Example: --doc \"Davis School District|Davis_2019-2020.pdf\"",
    )
    args = parser.parse_args()

    print("Reading codebook ...")
    questions = read_codebook()
    if args.doc:
        sample = [tuple(d.split("|", 1)) for d in args.doc]
    else:
        sample = read_sample()
    docs = load_documents(sample[:args.max_docs] if args.max_docs else sample)
    print(f"  {len(questions)} questions | {len(docs)} document(s) (max_docs={args.max_docs})")

    CACHE_DIR.mkdir(exist_ok=True)

    results: list[tuple[Document, dict, dict[str, dict]]] = []

    for i, doc in enumerate(docs, start=1):
        cache_path = CACHE_DIR / f"{doc.document_id}.json"
        metadata = build_metadata(doc)
        from_cache = cache_path.exists()
        print(f"[{i:>2}/{len(docs)}] {doc.file_name}  {'(cache)' if from_cache else '...'}")

        try:
            coded = process_document(doc, questions, cache_path)
        except AgentTaskPending as pending:
            print(f"\nStopped — agent action required.")
            print(f"Task:     {pending.task_id}")
            print(f"Read:     {pending.task_path}")
            print(f"Write to: {pending.response_path}")
            print("Then re-run this script to continue with the next task.")
            sys.exit(0)

        results.append((doc, metadata, coded))

    print("\nAll documents complete. Writing outputs ...")
    write_outputs(questions, results)


if __name__ == "__main__":
    main()
