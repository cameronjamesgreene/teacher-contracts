#!/usr/bin/env python3
"""Re-check absence claims by showing the model the provision from another contract.

Two similarity-based approaches to absence have now been measured and both failed: the
best dense match over every passage of a document, and a probe built from another
document's evidence for the same question. Neither separates verified-present from
verified-absent, because similarity measures topical proximity while these absences are
propositional — a contract discusses special education at length and never states a
special-education differential.

The conclusion is that retrieval cannot settle absence; only judgement can. But the
exemplar is still valuable, just in a different slot: instead of *searching* with it, show
it to the model as a concrete comparison target.

"Does this contract provide X?" is an open-ended question against an unbounded space, and
the model answers it badly — it over-claims, and given plausible topical material it will
paraphrase its way to a citation. "Here is what X looks like in another contract of the
same kind. Is anything in these passages the same kind of provision, or is it genuinely
absent here?" is a comparison, which is a far better-posed task.

Two safeguards carried over from earlier findings:

* The model selects **sentence numbers** rather than writing out a quote, so any evidence
  it returns is verbatim and contiguous by construction. Asking it to transcribe is what
  produced 19 unciteable quotes on a handbook.
* An explicit "genuinely absent" verdict is a **first-class outcome**, stated as such in
  the prompt. The failure mode being targeted is a model that would rather invent support
  than decline, so declining has to be an obviously acceptable answer.

Only absence claims worth spending a call on are re-checked: those where most other
documents answer the question substantively, which is the one absence signal that is not
similarity-based and therefore survives the results above.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from absence_triage import base_rates, exemplar_bank, load_runs
from grind_retrieve import (fused_passages, ground, load_document,
                            open_database, sentence_menu)
from grind_score import classify
from som_client import MODEL, budgeted_max_tokens, create_with_retries, get_client
from utils import WORK, read_codebook

DB = WORK / "cache" / "contract_search_structural.sqlite3"

SYSTEM = """You judge whether a contract contains a particular kind of provision.

You will be shown: the question, an example of the provision as written in a DIFFERENT
contract, and numbered sentences from THIS contract.

Decide whether any sentence in THIS contract states the same kind of provision.

- If yes, return the sentence numbers that state it. One number, or two or three
  CONSECUTIVE numbers. Do not write out the text; the host copies it for you.
- If no, return an empty list and say so. **A genuine absence is a correct and useful
  answer.** Contracts differ, and this one may simply not address it. Do not stretch a
  loosely related sentence to fit.

Judge the provision, not the topic. The example is only there to show you what the
provision looks like when a contract does have it. This contract discussing the same
subject area is NOT enough — it must state this kind of rule.

Reply with JSON only:
{"sentence_ids": [numbers or empty], "answer": "<the answer those sentences support, or
 \\"not_discussed\\">", "reasoning": "<one sentence>", "confidence": "high|medium|low"}"""


def recheck(client, question, doc, menu, exemplar: str, source: str) -> dict:
    body = (f"QUESTION: {question.question}\n"
            f"Answer type: {question.answer_type}\n"
            f"Keywords: {question.keywords}\n\n"
            f"THE PROVISION AS WRITTEN IN ANOTHER CONTRACT ({source}):\n"
            f"{exemplar[:900]}\n\n"
            f"NUMBERED SENTENCES FROM THIS CONTRACT:\n{menu.render()}")
    return create_with_retries(
        client, model=MODEL, temperature=0,
        max_tokens=budgeted_max_tokens(SYSTEM, body, max_output=3_000),
        messages=[{"role": "system", "content": SYSTEM},
                  {"role": "user", "content": body}])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True)
    parser.add_argument("--runs", type=Path, nargs="+", required=True,
                        help="extraction outputs; other documents supply the exemplars")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--min-base-rate", type=float, default=0.5,
                        help="only recheck absences most other documents answer")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    runs = load_runs(args.runs)
    if args.target not in runs:
        raise SystemExit(f"no run for {args.target}")
    bank = exemplar_bank(runs)
    rates = base_rates(runs)
    questions = {question.qid: question for question in read_codebook()}
    doc = load_document(args.target)

    candidates = []
    for qid, answer in runs[args.target].items():
        if classify(answer.get("answer", "")) == "substantive":
            continue
        exemplars = [(source, quote) for source, quote in bank.get(qid, [])
                     if source != args.target]
        if exemplars and rates.get(qid, 0.0) >= args.min_base_rate and qid in questions:
            candidates.append((qid, exemplars[0]))
    candidates.sort(key=lambda item: -rates.get(item[0], 0.0))
    if args.limit:
        candidates = candidates[:args.limit]
    print(f"{len(runs[args.target])} answers; {len(candidates)} absence claims to recheck "
          f"(base rate >= {args.min_base_rate})", flush=True)

    client = get_client()
    revised, confirmed, failed = 0, 0, 0
    records: list[dict] = []
    started = time.monotonic()
    with open_database(DB) as connection:
        for index, (qid, (source, exemplar)) in enumerate(candidates, start=1):
            question = questions[qid]
            original = dict(runs[args.target][qid])
            try:
                passages = fused_passages(
                    connection, f"{question.question} {question.keywords}", doc=doc)
                menu = sentence_menu(passages)
                if not menu.sentences:
                    raise RuntimeError("no sentences retrieved")
                reply = recheck(client, question, doc, menu, exemplar, source)
                sids = [int(value) for value in (reply.get("sentence_ids") or [])
                        if str(value).strip().lstrip("-").isdigit()]
                span = menu.span(sids) if sids else ""
                answer = str(reply.get("answer") or "").strip()
                grounding = ground(span, passages, doc=doc) if span else None
                if span and grounding and grounding.contiguous and classify(answer) == "substantive":
                    original.update(
                        answer=answer, evidence=span, page=grounding.page,
                        confidence=str(reply.get("confidence") or "medium"),
                        coder_notes=(original.get("coder_notes", "") +
                                     f" [absence overturned by contrast with {source[:24]}: "
                                     f"{str(reply.get('reasoning'))[:120]}]").strip())
                    revised += 1
                    mark = "OVERTURNED"
                else:
                    original["coder_notes"] = (
                        original.get("coder_notes", "") +
                        f" [absence confirmed against an exemplar from {source[:24]}]").strip()
                    confirmed += 1
                    mark = "confirmed"
            except Exception as exc:
                original["coder_notes"] = (original.get("coder_notes", "") +
                                           f" [contrast failed: {type(exc).__name__}]").strip()
                failed += 1
                mark = f"error {type(exc).__name__}"
            records.append(original)
            print(f"  [{index}/{len(candidates)}] {qid:42s} {mark}", flush=True)

    # Emit the whole answer set so the output is a drop-in replacement, not a fragment.
    merged = dict(runs[args.target])
    for record in records:
        merged[record["question_id"]] = record
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as output:
        for index, qid in enumerate(sorted(merged), start=1):
            output.write(json.dumps({"document_id": args.target, "batch": index,
                                     "answers": [merged[qid]]}, ensure_ascii=False) + "\n")
    print(f"\n{revised} overturned, {confirmed} confirmed absent, {failed} failed "
          f"in {time.monotonic() - started:.0f}s -> {args.out}")


if __name__ == "__main__":
    main()
