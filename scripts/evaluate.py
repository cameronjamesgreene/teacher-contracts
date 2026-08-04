"""Score a run against the gold table, and compare two runs.

The headline metric is RECALL ON SUBSTANTIVE PROVISIONS, not accuracy. On the full-census
audit, 69 of 73 errors were `not_discussed` on a provision that was present and none were
fabricated values, so overall accuracy is dominated by the easy true-negatives and moves
very little when the actual defect is fixed. `recall_substantive` moves.

`precision_substantive` is reported alongside it because it is the guard the union decision
rule in two_view.py needs: an OR over views can only ever increase the number of substantive
answers, so it trades false negatives for false positives. If recall climbs while precision
falls, the union is being paid for with wrong answers and needs its quote gate tightened.

Confidence intervals are bootstrapped over DOCUMENTS, not cells. The gold set is 4 documents
x 106 questions; cells within a document are strongly correlated (whole sub-batches fail
together), so a cell-level binomial interval is roughly 2-3x too narrow and would "confirm"
improvements that are one document's idiosyncrasy. Comparisons between runs use McNemar on
the discordant pairs, which is far more powerful than comparing two independent rates.
"""

from __future__ import annotations

import argparse
import json
import random
import re
from typing import Optional

import store

MISSING = {"not_discussed", "discussed_unclear", "", "none", "null", "no_answer", "ocr_needed"}


def _norm(a) -> str:
    s = re.sub(r"\s+", " ", str(a or "")).strip().lower()
    return s.strip(" .;:'\"")


def _substantive(a) -> bool:
    return _norm(a) not in MISSING


def _match(pred, gold) -> bool:
    """Answer agreement, tolerant of formatting but not of meaning.

    Year values in particular are written every way imaginable ("2005-2006", "2005 - 2006",
    "FY2006", "SY 2005/06"), so those compare on their digit runs.
    """
    p, g = _norm(pred), _norm(gold)
    if not g:
        return False
    if p == g:
        return True
    if p in ("yes", "no") or g in ("yes", "no"):
        return p == g
    pn = re.findall(r"\d{4}", p)
    gn = re.findall(r"\d{4}", g)
    if gn and pn:
        return set(gn) == set(pn) or (len(gn) == 1 and gn[0] in pn)
    return g in p or p in g


def score_run(run_id: str, st: Optional[store.Store] = None,
              include_needs_review: bool = False) -> dict:
    st = st or store.get_store()
    tiers = ("from_answer", "from_note") if not include_needs_review else \
            ("from_answer", "from_note", "needs_review")
    rows = st._con.execute(
        "SELECT a.document_id, a.qid, a.answer, a.quote_verified, g.gold_answer, g.tier"
        " FROM answer a JOIN gold g ON g.document_id=a.document_id AND g.qid=a.qid"
        " WHERE a.run_id=? AND g.tier IN (%s)" % ",".join("?" * len(tiers)),
        (run_id,) + tiers).fetchall()
    cells = [dict(r) for r in rows]
    if not cells:
        return {"n": 0, "error": "no gold-matched answers for this run"}

    tp = sum(1 for c in cells if _substantive(c["gold_answer"]) and _substantive(c["answer"]))
    fn = sum(1 for c in cells if _substantive(c["gold_answer"]) and not _substantive(c["answer"]))
    fp = sum(1 for c in cells if not _substantive(c["gold_answer"]) and _substantive(c["answer"]))
    exact = sum(1 for c in cells if _match(c["answer"], c["gold_answer"]))

    def _boot(fn_metric, iters: int = 2000) -> tuple:
        by_doc: dict = {}
        for c in cells:
            by_doc.setdefault(c["document_id"], []).append(c)
        docs = list(by_doc)
        rng = random.Random(12345)
        vals = []
        for _ in range(iters):
            sample = []
            for _ in docs:
                sample.extend(by_doc[rng.choice(docs)])
            v = fn_metric(sample)
            if v is not None:
                vals.append(v)
        if not vals:
            return (None, None)
        vals.sort()
        return (round(vals[int(0.025 * len(vals))], 3), round(vals[int(0.975 * len(vals))], 3))

    def _recall(cs):
        d = sum(1 for c in cs if _substantive(c["gold_answer"]))
        return (sum(1 for c in cs if _substantive(c["gold_answer"])
                    and _substantive(c["answer"])) / d) if d else None

    def _acc(cs):
        return sum(1 for c in cs if _match(c["answer"], c["gold_answer"])) / len(cs) if cs else None

    return {
        "run_id": run_id,
        "n_cells": len(cells),
        "n_documents": len({c["document_id"] for c in cells}),
        "recall_substantive": round(tp / (tp + fn), 3) if (tp + fn) else None,
        "recall_ci95_doc_bootstrap": _boot(_recall),
        "precision_substantive": round(tp / (tp + fp), 3) if (tp + fp) else None,
        "answer_accuracy": round(exact / len(cells), 3),
        "answer_accuracy_ci95": _boot(_acc),
        "false_negatives": fn,
        "false_positives": fp,
        # Denominator and numerator must both be restricted to substantive answers, or a
        # not_discussed record that carried a stray quote inflates the rate above 1.0.
        "quote_verified_rate": round(
            sum(1 for c in cells if c["quote_verified"] and _substantive(c["answer"])) /
            max(1, sum(1 for c in cells if _substantive(c["answer"]))), 3),
    }


def compare(run_a: str, run_b: str, st: Optional[store.Store] = None) -> dict:
    """Paired McNemar on cells both runs coded. Blocked by construction: identical cells."""
    st = st or store.get_store()
    rows = st._con.execute(
        "SELECT a.document_id, a.qid, a.answer aa, b.answer ba, g.gold_answer"
        " FROM answer a JOIN answer b ON a.document_id=b.document_id AND a.qid=b.qid"
        " JOIN gold g ON g.document_id=a.document_id AND g.qid=a.qid"
        " WHERE a.run_id=? AND b.run_id=? AND g.tier IN ('from_answer','from_note')",
        (run_a, run_b)).fetchall()
    if not rows:
        return {"error": "no shared gold-matched cells"}
    a_only = b_only = both = neither = 0
    for r in rows:
        ok_a = _match(r["aa"], r["gold_answer"])
        ok_b = _match(r["ba"], r["gold_answer"])
        if ok_a and ok_b:
            both += 1
        elif ok_a:
            a_only += 1
        elif ok_b:
            b_only += 1
        else:
            neither += 1
    n_disc = a_only + b_only
    # McNemar chi-square with continuity correction; exact binomial when discordants are few.
    chi2 = ((abs(a_only - b_only) - 1) ** 2 / n_disc) if n_disc else 0.0
    if n_disc == 0:
        p = 1.0
    elif n_disc < 25:
        from math import comb
        k = min(a_only, b_only)
        p = min(1.0, 2 * sum(comb(n_disc, i) for i in range(k + 1)) / (2 ** n_disc))
    else:
        from math import erfc, sqrt
        p = erfc(sqrt(chi2 / 2))
    return {"n_paired": len(rows), "both_correct": both, "neither": neither,
            f"only_{run_a}": a_only, f"only_{run_b}": b_only,
            "mcnemar_chi2": round(chi2, 3), "p_value": round(p, 4),
            "verdict": ("B better" if b_only > a_only else
                        "A better" if a_only > b_only else "tie") +
                       (" (significant at .05)" if p < 0.05 else " (NOT significant)")}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Score runs against gold.")
    ap.add_argument("--run", help="run_id to score")
    ap.add_argument("--compare", nargs=2, metavar=("RUN_A", "RUN_B"))
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()
    st = store.get_store()
    if args.list:
        for r in st._con.execute(
                "SELECT run_id, started_at, notes, (SELECT COUNT(*) FROM answer a"
                " WHERE a.run_id=run.run_id) n FROM run ORDER BY started_at DESC LIMIT 20"):
            print(dict(r))
    if args.run:
        print(json.dumps(score_run(args.run, st), indent=2))
    if args.compare:
        print(json.dumps(compare(args.compare[0], args.compare[1], st), indent=2))
