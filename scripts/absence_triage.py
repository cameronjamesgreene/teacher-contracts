#!/usr/bin/env python3
"""Triage absence claims using evidence from other documents. No model calls.

Absence is the hardest answer in this project: on some documents it is the majority
answer, it is the largest error class, and it is the most expensive thing to verify.

An earlier attempt measured, for each question, the best dense similarity over *every*
passage of a document — an exhaustive search rather than a sampled one — and it **failed
to separate present from absent** (verified-absent scored 0.679–0.732 inside a
verified-present range of 0.591–0.836). The reason is that absence here is almost never
topical: a contract discusses special education at length and simply never states a
special-education pay differential. Topic-level similarity cannot see that.

The obvious next idea was to probe with the *provision* instead of the topic: when another
document answers the same question substantively, its evidence quote is a concrete example
of what the provision looks like in contract language, so searching for text like that
should be a proposition-level question rather than a topical one.

**That also fails, and the failure is the useful finding here.** Calibrated on the answer
key with exemplars held out to other documents, verified-absent provisions score 0.767–0.780
against a verified-present range of 0.674–0.906 — the absent cases land on the present
median. The reason is the same one that sank the topical probe: an exemplar clause about
special-education pay is *topically* about special education, so it matches this contract's
special-education text whether or not the differential exists.

**Conclusion: similarity-based retrieval cannot detect fine-grained absence at all.** Not
by topic, not by exemplar. Similarity measures topical proximity and these absences are
propositional. An exemplar's value is therefore as a *comparison target for judgement*, fed
to the model alongside the retrieved passages, not as a search query — see
`grind_contrast.py`.

What this module still provides, and it is worth keeping:

  base_rate            share of other documents answering this question substantively.
                       Not a similarity signal, so it survives the above. An absence on the
                       one document in thirty that lacks a common provision is worth a
                       second look; an absence of something no document carries is not.
  exemplar_similarity  retained and reported, but do NOT threshold on it alone. It is
                       useful only as a tie-breaker within a base-rate stratum, and the
                       calibration above is the evidence for that caution.

This module ranks; it does not decide.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from grind_score import classify
from utils import WORK, read_codebook

RESULTS = WORK / "output" / "extraction" / "results"
MIN_EXEMPLAR_CHARS = 60


def load_runs(paths: list[Path]) -> dict[str, dict[str, dict]]:
    """document_id -> question_id -> answer record."""
    runs: dict[str, dict[str, dict]] = defaultdict(dict)
    for path in paths:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            batch = json.loads(line)
            document = batch.get("document_id", "")
            for answer in batch.get("answers", []):
                runs[document][answer["question_id"]] = answer
    return runs


def exemplar_bank(runs: dict[str, dict[str, dict]]) -> dict[str, list[tuple[str, str]]]:
    """question_id -> [(source document, evidence quote)] from substantive answers."""
    bank: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for document, answers in runs.items():
        for qid, answer in answers.items():
            evidence = (answer.get("evidence") or "").strip()
            if (classify(answer.get("answer", "")) == "substantive"
                    and len(evidence) >= MIN_EXEMPLAR_CHARS):
                bank[qid].append((document, evidence))
    return bank


def base_rates(runs: dict[str, dict[str, dict]], minimum: int = 3) -> dict[str, float]:
    """Share of documents answering each question substantively, excluding partial runs."""
    full = {doc: answers for doc, answers in runs.items() if len(answers) >= 100}
    present: dict[str, int] = defaultdict(int)
    total: dict[str, int] = defaultdict(int)
    for answers in full.values():
        for qid, answer in answers.items():
            total[qid] += 1
            if classify(answer.get("answer", "")) == "substantive":
                present[qid] += 1
    return {qid: present[qid] / total[qid] for qid in total if total[qid] >= minimum}


def probe(document_id: str, quotes: list[str]) -> float:
    """Best dense similarity between this document and any exemplar quote."""
    from sqlite_vectors import search as vector_search
    best = 0.0
    for quote in quotes:
        hits = vector_search(quote[:1200], document_id, limit=1)
        if hits:
            best = max(best, hits[0][1])
    return best


def triage(target: str, runs: dict[str, dict[str, dict]], threshold: float) -> list[dict]:
    bank = exemplar_bank(runs)
    rates = base_rates(runs)
    questions = {question.qid: question for question in read_codebook()}
    rows: list[dict] = []
    for qid, answer in runs.get(target, {}).items():
        if classify(answer.get("answer", "")) == "substantive":
            continue
        # Exemplars must come from OTHER documents, or a document would vouch for itself.
        quotes = [quote for source, quote in bank.get(qid, []) if source != target]
        if not quotes:
            continue
        similarity = probe(target, quotes)
        rows.append({
            "question_id": qid,
            "answer_type": questions[qid].answer_type if qid in questions else "",
            "claimed": answer.get("answer", "")[:24],
            "exemplar_similarity": round(similarity, 4),
            "exemplars": len(quotes),
            "base_rate": round(rates.get(qid, 0.0), 3),
            "suspect": int(similarity >= threshold and rates.get(qid, 0.0) >= 0.5),
        })
    rows.sort(key=lambda row: -row["exemplar_similarity"])
    return rows


def calibrate(target: str, runs: dict[str, dict[str, dict]], gold_path: Path) -> None:
    """Does the exemplar probe separate verified-present from verified-absent?

    Held out honestly: exemplars for the target document are excluded, so the probe never
    sees the target's own evidence.
    """
    bank = exemplar_bank(runs)
    with gold_path.open(newline="", encoding="utf-8") as source:
        gold = list(csv.DictReader(source))
    present: list[float] = []
    absent: list[float] = []
    for row in gold:
        quotes = [quote for document, quote in bank.get(row["question_id"], [])
                  if document != target]
        if not quotes:
            continue
        score = probe(target, quotes)
        (absent if row["gold_status"] == "not_discussed" else present).append(score)

    def show(label: str, values: list[float]) -> None:
        if not values:
            print(f"  {label}: none")
            return
        values.sort()
        print(f"  {label:20s} n={len(values):>3}  min {values[0]:.3f}  "
              f"median {values[len(values) // 2]:.3f}  max {values[-1]:.3f}")

    print(f"exemplar-probe separation on {target} (exemplars from other documents only):")
    show("provision present", present)
    show("provision absent", absent)
    if present and absent:
        overlap = sum(1 for value in absent if value >= min(present))
        print(f"  absent at or above the lowest present score: {overlap}/{len(absent)}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True, help="document_id to triage")
    parser.add_argument("--runs", type=Path, nargs="+", required=True,
                        help="extraction outputs, including other documents")
    parser.add_argument("--threshold", type=float, default=0.72)
    parser.add_argument("--calibrate", type=Path,
                        help="answer key for the target, to test separation")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    runs = load_runs(args.runs)
    if args.calibrate:
        calibrate(args.target, runs, args.calibrate)
        return
    rows = triage(args.target, runs, args.threshold)
    suspect = [row for row in rows if row["suspect"]]
    print(f"{len(rows)} absence claims with exemplars from other documents; "
          f"{len(suspect)} suspect")
    print(f"{'question':40s} {'sim':>6s} {'rate':>5s} {'ex':>3s}")
    for row in rows[:15]:
        mark = " <-- recheck" if row["suspect"] else ""
        print(f"{row['question_id']:40s} {row['exemplar_similarity']:>6.3f} "
              f"{row['base_rate']:>5.2f} {row['exemplars']:>3}{mark}")
    if args.out and rows:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("w", newline="", encoding="utf-8") as target:
            writer = csv.DictWriter(target, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
