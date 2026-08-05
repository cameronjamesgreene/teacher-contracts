#!/usr/bin/env python3
"""Evidence for and against an absence claim, computed without a model call.

The problem this addresses. On many documents absence is the *majority* answer — a
4-page tentative agreement legitimately answers 14 of 106 questions — while wrong
absence is simultaneously the largest error class and the most expensive thing to check,
because the current pipeline re-queries and re-adjudicates every single absence with the
model. Absence is thus the most common answer, the most error-prone, and the most costly.

The reframing. "I did not find it in the top 10 passages" is a *sampled* search and is
weak evidence. But every passage embedding for the corpus already sits in SQLite, so the
maximum similarity over **all** passages of a document is computable in microseconds.
That is an *exhaustive* search, and it turns absence into a measurable quantity: not
"retrieval missed it" but "the closest thing anywhere in this document is this passage,
at this similarity."

Two signals per (document, question):

* `max_similarity` — best dense match over every passage in the document.
* `lexical_hits` — how many of the question's codebook keywords appear anywhere in the
  document text at all. A keyword that never occurs is strong support for absence; a
  keyword that occurs while dense similarity is low means the topic is present but
  phrased unlike the question, which is exactly the appendix failure mode.

Use: triage. Spend model calls verifying absences whose signals say the provision is
probably there, and accept the rest cheaply. Symmetrically, a *substantive* answer with
low support is the profile of a paraphrased or invented quote, which is what a handbook
run produced, so the same numbers flag over-claiming as well as under-claiming.

This module only measures. Choosing thresholds is a calibration exercise; run
`--calibrate` to see the separation on the questions where the answer is known.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from grind_retrieve import DocumentContext, load_document, norm
from grind_score import classify
from utils import WORK, Question, read_codebook

GOLD = WORK / "output" / "extraction" / "answer_gold.csv"
_WORD = re.compile(r"[a-z][a-z'/-]{3,}")
_STOP = {"does", "document", "the", "and", "for", "with", "that", "this", "any",
         "other", "state", "provide", "provides", "stated", "teacher", "teachers"}


@dataclass(frozen=True)
class Support:
    question_id: str
    max_similarity: float
    mean_top5: float
    keyword_hits: int
    keyword_total: int

    @property
    def keyword_rate(self) -> float:
        return self.keyword_hits / self.keyword_total if self.keyword_total else 0.0


def keywords_of(question: Question) -> list[str]:
    """Distinctive keyword terms from the codebook row, for a lexical presence check."""
    terms: list[str] = []
    for chunk in re.split(r"[;,]", question.keywords or ""):
        chunk = chunk.strip().casefold()
        if not chunk:
            continue
        words = [w for w in _WORD.findall(chunk) if w not in _STOP]
        if words:
            phrase = " ".join(words)
            if phrase not in terms:
                terms.append(phrase)
    return terms[:8]


def support(question: Question, doc: DocumentContext, document_text: str) -> Support:
    """Exhaustive dense similarity plus a lexical presence count. No model call."""
    import numpy as np
    from sqlite_vectors import _matrix, DB, embed_query

    ids, matrix = _matrix(DB, doc.document_id)
    if not ids:
        return Support(question.qid, 0.0, 0.0, 0, len(keywords_of(question)))
    scores = matrix @ embed_query(f"{question.question} {question.keywords}")
    top = np.sort(scores)[::-1][:5]
    terms = keywords_of(question)
    hits = sum(1 for term in terms if term in document_text)
    return Support(question.qid, float(top[0]), float(top.mean()), hits, len(terms))


def calibrate(document_id: str) -> None:
    """Do the signals separate known-present from known-absent provisions?

    Uses the answer key, so it only works where one exists. The point is to see whether a
    threshold exists at all before any of this is wired into the pipeline.
    """
    doc = load_document(document_id)
    document_text = norm(" ".join(doc.pages()))
    questions = {q.qid: q for q in read_codebook()}
    present: list[Support] = []
    absent: list[Support] = []
    with GOLD.open(newline="", encoding="utf-8") as source:
        for row in csv.DictReader(source):
            question = questions.get(row["question_id"])
            if question is None:
                continue
            value = support(question, doc, document_text)
            (absent if row["gold_status"] == "not_discussed" else present).append(value)

    def summarise(label: str, rows: list[Support]) -> None:
        if not rows:
            print(f"  {label}: none")
            return
        sims = sorted(r.max_similarity for r in rows)
        rates = sorted(r.keyword_rate for r in rows)
        print(f"  {label:22s} n={len(rows):>3}  max_sim min/median/max "
              f"{sims[0]:.3f}/{sims[len(sims)//2]:.3f}/{sims[-1]:.3f}   "
              f"keyword_rate median {rates[len(rates)//2]:.2f}")

    print(f"{doc.district} — separation on the answer key:")
    summarise("provision present", present)
    summarise("provision absent", absent)
    if present and absent:
        overlap = sum(1 for a in absent
                      if a.max_similarity >= min(p.max_similarity for p in present))
        print(f"  absent rows at or above the lowest present similarity: {overlap}/{len(absent)}")


def report(document_id: str, answers_path: Path | None) -> None:
    doc = load_document(document_id)
    document_text = norm(" ".join(doc.pages()))
    questions = read_codebook()
    given: dict[str, dict] = {}
    if answers_path:
        for line in answers_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                for answer in json.loads(line).get("answers", []):
                    given[answer["question_id"]] = answer

    rows = []
    for question in questions:
        value = support(question, doc, document_text)
        answer = given.get(question.qid)
        status = classify(answer.get("answer", "")) if answer else ""
        rows.append((value, status))

    print(f"{doc.district}  ({doc.page_count}pp)")
    print(f"{'question':44s} {'status':>12s} {'max_sim':>8s} {'kw':>7s}")
    # Surface the two profiles that matter: an absence with high support, which is
    # probably wrong, and a substantive answer with low support, which is probably
    # over-claimed.
    suspect_absence = [(v, s) for v, s in rows
                       if s in {"not_discussed", "no"} and v.max_similarity >= 0.62]
    weak_presence = [(v, s) for v, s in rows
                     if s == "substantive" and v.max_similarity < 0.55]
    for label, group in (("absence with strong support against it", suspect_absence),
                         ("substantive answer with weak support", weak_presence)):
        print(f"\n  {label}: {len(group)}")
        for value, status in sorted(group, key=lambda item: -item[0].max_similarity)[:10]:
            print(f"  {value.question_id:44s} {status:>12s} "
                  f"{value.max_similarity:>8.3f} {value.keyword_hits}/{value.keyword_total:<5}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--document-id", required=True)
    parser.add_argument("--answers", type=Path, help="extractor output to triage")
    parser.add_argument("--calibrate", action="store_true",
                        help="check signal separation against the answer key")
    args = parser.parse_args()
    if args.calibrate:
        calibrate(args.document_id)
    else:
        report(args.document_id, args.answers)


if __name__ == "__main__":
    main()
