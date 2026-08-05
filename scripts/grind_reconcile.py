#!/usr/bin/env python3
"""Reconcile several extraction variants into one answer set.

The variants fail on different questions, which is the same complementarity that
made fused retrieval beat either engine alone. Two mechanisms, both deterministic:

**Absence yields to evidence.** Wrongly answering `not_discussed` is the dominant
error class, and every variant nulls out ungrounded answers before writing them. So
a grounded substantive answer from any variant outranks an absence claim from all
the others. The asymmetry is deliberate and is the whole point.

**Augmentation on grounded facts.** A variant that found a figure the chosen answer
lacks contributes it, provided its quote still verifies against the document. This
targets completeness, where both incumbent systems score about 0.5 because they
state a general rule and omit the variation that applies to job sharers, part-time
staff, one school level, one plan, or one contract year.

No model calls. Reconciliation that needed a model to arbitrate would be another
thing to validate; arithmetic on grounded quotes does not.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from grind_retrieve import DOCUMENT_ID, document_pages, locate_in_document, norm
from grind_score import classify
from utils import WORK, read_codebook

_NUMERIC = re.compile(r"\d+(?:\.\d+)?%?")
_PAGE_NUM = re.compile(r"\d+")


def load(path: Path) -> dict[str, dict]:
    answers: dict[str, dict] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        for answer in json.loads(line).get("answers", []):
            answers[answer["question_id"]] = answer
    return answers


def numeric_tokens(text: str) -> set[str]:
    """Figures a coded answer turns on: days, dollars, minutes, percentages, years."""
    return {token.rstrip("%") for token in _NUMERIC.findall(text or "")}


_CONTENT = re.compile(r"[a-z][a-z'/-]{3,}")
_COMMON = {
    "shall", "will", "must", "that", "this", "with", "from", "have", "been", "which",
    "teacher", "teachers", "board", "district", "agreement", "article", "section",
    "document", "provision", "provisions", "stated", "states", "under", "such",
    "also", "than", "when", "each", "any", "other", "their", "they", "there",
    "school", "schools", "year", "years", "shall_not", "does", "discussed",
}


def support_tokens(text: str) -> set[str]:
    """Figures plus distinctive content words, for testing whether a quote supports an answer.

    Numbers alone cannot discriminate on questions whose answer is a list of names or
    rights rather than an amount, which is where evidence/answer mismatch was observed.
    """
    lowered = norm(text)
    words = {word for word in _CONTENT.findall(lowered) if word not in _COMMON}
    return numeric_tokens(text) | words


def pages_of(record: dict) -> list[int]:
    return [int(value) for value in _PAGE_NUM.findall(record.get("page", "") or "")]


def merge_pages(primary: dict, extras: list[dict]) -> str:
    pages = sorted({*pages_of(primary), *(p for extra in extras for p in pages_of(extra))})
    return ";".join(str(page) for page in pages) if pages else "not_applicable"


def reconcile(sources: list[tuple[str, dict[str, dict]]], question_ids: list[str],
              pages: list[str]) -> list[dict]:
    records: list[dict] = []
    for qid in question_ids:
        candidates = [(label, source[qid]) for label, source in sources if qid in source]
        substantive = [(label, record) for label, record in candidates
                       if classify(record.get("answer", "")) == "substantive"
                       and (record.get("evidence") or "").strip()]

        if not substantive:
            # Every variant reports absence. Prefer an explicit `no` over
            # not_discussed only when a variant actually asserted it.
            explicit = [record for _, record in candidates
                        if classify(record.get("answer", "")) == "no"]
            chosen = explicit[0] if explicit else (candidates[0][1] if candidates else None)
            records.append({
                "question_id": qid,
                "answer": (chosen or {}).get("answer", "not_discussed") or "not_discussed",
                "evidence": "", "page": "not_applicable", "confidence": "low",
                "coder_notes": "[reconcile: all variants report absence]",
            })
            continue

        # Source order is the caller's stated precedence; the first grounded
        # substantive answer leads and the rest may only add to it.
        primary_label, primary = substantive[0]
        answer = str(primary.get("answer", "")).strip()
        have = numeric_tokens(answer)
        added: list[dict] = []
        notes: list[str] = []
        for label, record in substantive[1:]:
            extra_answer = str(record.get("answer", "")).strip()
            new_figures = numeric_tokens(extra_answer) - have
            if not new_figures:
                continue
            grounding = locate_in_document(record.get("evidence", ""), pages)
            if not grounding.contiguous:
                continue          # an unverified "variation" is worse than an omission
            answer = f"{answer}; also ({label}): {extra_answer}"
            have |= new_figures
            added.append(record)
            notes.append(f"+{label} figures {','.join(sorted(new_figures))}")

        # The quote must support the answer that is actually being reported. A variant
        # can be right about the provision and cite the wrong clause for it, and once
        # augmentation has changed the answer text the primary's quote may no longer
        # be its best support. Choose, among grounded candidates, the quote sharing
        # the most of the answer's figures; fall back to the primary on a tie.
        answer_support = support_tokens(answer)
        best_label, best_evidence, best_support = primary_label, primary.get("evidence", ""), -1
        for label, record in substantive:
            candidate = record.get("evidence", "") or ""
            if not locate_in_document(candidate, pages).contiguous:
                continue
            support = len(answer_support & support_tokens(candidate))
            if label == primary_label:
                support += 1        # tie goes to the precedence winner
            if support > best_support:
                best_label, best_evidence, best_support = label, candidate, support
        if best_label != primary_label:
            notes.append(f"evidence from {best_label}")

        chosen_pages = merge_pages(primary, added)
        if best_label != primary_label:
            source = next(record for label, record in substantive if label == best_label)
            chosen_pages = merge_pages(source, added + [primary])

        records.append({
            "question_id": qid,
            "answer": answer,
            "evidence": best_evidence,
            "page": chosen_pages,
            "confidence": primary.get("confidence", "medium"),
            "coder_notes": (f"[reconcile: base={primary_label}"
                            + (f"; {'; '.join(notes)}" if notes else "") + "]"),
        })
    return records


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", action="append", required=True,
                        metavar="LABEL=PATH", help="in precedence order, best first")
    parser.add_argument("--out", type=Path,
                        default=WORK / "output" / "extraction" / "results" / "reconciled.jsonl")
    args = parser.parse_args()

    sources: list[tuple[str, dict[str, dict]]] = []
    for item in args.input:
        label, _, raw_path = item.partition("=")
        path = Path(raw_path)
        if not path.exists():
            print(f"skipping missing input {label}={path}")
            continue
        sources.append((label, load(path)))
    if not sources:
        raise SystemExit("no usable inputs")

    question_ids = [question.qid for question in read_codebook()]
    records = reconcile(sources, question_ids, document_pages())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as output:
        for index, record in enumerate(records, start=1):
            output.write(json.dumps({"document_id": DOCUMENT_ID, "batch": index,
                                     "answers": [record]}, ensure_ascii=False) + "\n")
    augmented = sum(1 for record in records if "+" in record["coder_notes"])
    substantive = sum(1 for record in records
                      if classify(record["answer"]) == "substantive")
    print(f"reconciled {len(records)} questions from {len(sources)} sources: "
          f"{substantive} substantive, {augmented} augmented -> {args.out}")


if __name__ == "__main__":
    main()
