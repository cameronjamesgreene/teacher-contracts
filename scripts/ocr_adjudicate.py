#!/usr/bin/env python3
"""Adjudicate OCR figure disputes on internal consistency, not on engine reputation.

`ocr_reconcile.py` breaks a figure dispute by preferring whichever engine measured best on a
verified sample. That is a fixed prior: it never looks at the disputed text, so it is only as
good as the sample it was tuned on, and it cannot tell you *why* one reading is right.

Contract prose happens to be unusually self-checking, which makes a better decision possible.
The genre is full of redundant constructions:

* **Word and digit must agree.** "fifteen (15) days". olmOCR-2 produced `eighty (8) hours`
  where the PDF says `eight (8) hours` — internally contradictory on its face.
* **Parenthetical arithmetic must close.** The PDF says `202 days (192 days + 10 additional)`;
  olmOCR-2 produced `132 days (192 days - 10 additional)`. Neither 132 nor a minus sign is
  consistent with 192 and 10.
* **Salary steps are monotonic.** A schedule reading 37,620 / 38,120 / 39,620 / 39,120 has a
  step that goes backwards.

So a disputed reading can often be adjudicated from the text itself. Two tiers, cheapest
first:

1. **Deterministic checks** — word/digit mismatch and parenthetical arithmetic. These need no
   model, are not fallible, and catch a real share of the cases.
2. **Model adjudication** for what is left: both engines' renderings of the same passage are
   shown side by side and the model is asked which is internally coherent as contract
   language, and to say why. It is choosing between two candidate transcriptions, not
   transcribing, which is a far better-posed task than OCR and does not put the model on the
   critical path of reading the page.

A dispute the model cannot resolve stays unresolved and flagged. The aim is to shrink the set
a human must look at, not to manufacture confidence.

## Where this does NOT work: table pages

Measured limitation, not a hypothetical. On a rotated salary schedule the model chose the
*wrong* engine, describing the correct-but-ragged transcription as "garbled and incoherent"
and the transposed one as "a coherent salary schedule table". It preferred fluency over
fidelity — the very bias that makes generative OCR risky in the first place, reappearing in
the adjudicator.

A deterministic monotonicity check was written to cover this and removed again, because any
version of it reads "rows" from line breaks and so measures an engine's text wrapping rather
than the schedule; it also got the known case backwards.

**So table and schedule pages are not adjudicated. They are flagged for human review.** The
two deterministic checks above operate on prose constructions and are reliable there; the
model tier should be trusted for prose and distrusted for tables.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ocr_quality_gate import pages_of
from som_client import MODEL, budgeted_max_tokens, create_with_retries, get_client
from utils import WORK

_WORD_DIGIT = re.compile(
    r"\b(one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|"
    r"fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|"
    r"eighty|ninety|hundred)\s*\(\s*(\d+)\s*\)", re.I)
WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
         "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
         "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
         "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
         "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90, "hundred": 100}
# "202 days (192 days + 10 additional)" — the outer figure must equal the inner arithmetic.
_ARITHMETIC = re.compile(
    r"(\d[\d,]*)\s*days?\s*\(\s*(\d[\d,]*)\s*days?\s*([+\-])\s*(\d[\d,]*)", re.I)


def word_digit_conflicts(text: str) -> list[str]:
    """Spelled numbers that contradict their own parenthetical digits."""
    problems = []
    for word, digits in _WORD_DIGIT.findall(text):
        expected = WORDS.get(word.casefold())
        if expected is not None and expected != int(digits):
            problems.append(f"{word} ({digits}) — the word says {expected}")
    return problems


def arithmetic_conflicts(text: str) -> list[str]:
    """Parenthetical sums that do not close."""
    problems = []
    for total, base, sign, delta in _ARITHMETIC.findall(text):
        total_value = int(total.replace(",", ""))
        computed = int(base.replace(",", "")) + (
            int(delta.replace(",", "")) * (1 if sign == "+" else -1))
        if total_value != computed:
            problems.append(f"{total} days ({base} {sign} {delta}) — that arithmetic gives "
                            f"{computed}")
    return problems


# A salary-schedule monotonicity check was tried here and REMOVED. Steps within a lane do
# increase, so the idea is sound, but any implementation reading "rows" from line breaks
# measures how an engine chose to wrap text rather than the schedule itself. On the one page
# whose contents are known, it fired on the engine with the CORRECT figures — because its
# transcription is ragged — and decided for the engine with transposed ones. A check that
# gets the known case backwards is worse than no check.
#
# Table pages therefore are not adjudicated here at all. See the caveat in the module
# docstring: they are flagged for human review instead.


def deterministic_score(text: str) -> tuple[int, list[str]]:
    problems = word_digit_conflicts(text) + arithmetic_conflicts(text)
    return len(problems), problems


SYSTEM = """You choose between two OCR transcriptions of the same page of a US school-district
teacher contract. You are NOT transcribing; both candidates already exist and one is likely
closer to the page.

Judge by internal consistency, because this genre is redundant in checkable ways:
- A spelled number must match its parenthetical digits: "fifteen (15) days" is consistent,
  "eighty (8) hours" is not.
- Parenthetical arithmetic must close: "202 days (192 days + 10 additional)" is consistent,
  "132 days (192 days - 10 additional)" is not.
- Salary steps and year columns normally increase monotonically.
- Contract prose does not contain image tags, URLs, or the same row repeated many times.

Reply with JSON only:
{"choice": "A" | "B" | "unresolved",
 "reason": "<one sentence naming the specific inconsistency that decided it>",
 "confidence": "high" | "medium" | "low"}

Answer "unresolved" when neither candidate shows a checkable inconsistency, or when both do.
That is a useful answer; do not guess."""


def adjudicate(client, question_context: str, a_text: str, b_text: str) -> dict:
    budget = 1_800
    body = (f"CONTEXT: {question_context}\n\n"
            f"--- CANDIDATE A ---\n{a_text[:budget]}\n\n"
            f"--- CANDIDATE B ---\n{b_text[:budget]}")
    return create_with_retries(
        client, model=MODEL, temperature=0,
        max_tokens=budgeted_max_tokens(SYSTEM, body, max_output=1_500),
        messages=[{"role": "system", "content": SYSTEM},
                  {"role": "user", "content": body}])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--a", type=Path, required=True, metavar="PATH")
    parser.add_argument("--b", type=Path, required=True, metavar="PATH")
    parser.add_argument("--a-label", default="A")
    parser.add_argument("--b-label", default="B")
    parser.add_argument("--pages", help="comma-separated page numbers; default all disputed")
    parser.add_argument("--no-model", action="store_true",
                        help="deterministic checks only, no API calls")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    a_pages, b_pages = pages_of(args.a), pages_of(args.b)
    wanted = ({int(value) for value in args.pages.split(",")} if args.pages
              else set(range(1, min(len(a_pages), len(b_pages)) + 1)))
    client = None if args.no_model else get_client()

    rows = []
    for number in sorted(wanted):
        if number > min(len(a_pages), len(b_pages)):
            continue
        a_text, b_text = a_pages[number - 1], b_pages[number - 1]
        if not a_text.strip() or not b_text.strip():
            continue
        a_bad, a_problems = deterministic_score(a_text)
        b_bad, b_problems = deterministic_score(b_text)
        row = {"page": number, "a_inconsistencies": a_bad, "b_inconsistencies": b_bad,
               "a_detail": "; ".join(a_problems[:3]), "b_detail": "; ".join(b_problems[:3]),
               "winner": "", "how": "", "reason": ""}
        if a_bad != b_bad:
            # Decided without a model call: one reading contradicts itself more than the other.
            row["winner"] = args.a_label if a_bad < b_bad else args.b_label
            row["how"] = "deterministic"
            row["reason"] = ("fewer internal contradictions: "
                             + (row["b_detail"] if a_bad < b_bad else row["a_detail"]))
        elif client is not None:
            try:
                verdict = adjudicate(client, f"page {number} of a teacher contract",
                                     a_text, b_text)
                choice = str(verdict.get("choice", "")).strip().upper()
                row["winner"] = {"A": args.a_label, "B": args.b_label}.get(choice, "")
                row["how"] = "model" if row["winner"] else "unresolved"
                row["reason"] = str(verdict.get("reason", ""))[:200]
            except Exception as exc:
                row["how"] = f"error {type(exc).__name__}"
        else:
            row["how"] = "tie, no model"
        rows.append(row)
        print(f"  page {number:>4}  {args.a_label}:{a_bad} {args.b_label}:{b_bad}  "
              f"-> {row['winner'] or '(unresolved)':14s} [{row['how']}] {row['reason'][:70]}",
              flush=True)

    decided = [row for row in rows if row["winner"]]
    by_determinism = [row for row in decided if row["how"] == "deterministic"]
    print(f"\n{len(decided)}/{len(rows)} disputes decided "
          f"({len(by_determinism)} without a model call)")
    if args.out and rows:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("w", newline="", encoding="utf-8") as target:
            writer = csv.DictWriter(target, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
