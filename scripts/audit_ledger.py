#!/usr/bin/env python3
"""The audit ledger: every row to be judged, with the source text needed to judge it.

Grading is the expensive step and it is done in batches across several sittings, so it
needs three properties that an ad-hoc pass does not have:

**Resumable.** Verdicts accumulate in one file. A batch that was graded is never graded
again, and the accuracy estimate improves monotonically as batches land.

**Self-contained.** Each row carries the source passage the judgement needs — the cited
page's text around the quote, the grid's page text, the clause's surrounding sentence.
Judging then means reading the row, not re-opening a 700-page PDF per item.

**Honest about method.** Every row records how it was checked:

    computed         mechanical only — the quote is verbatim on the cited page, the
                     grid's values are on that page, the cell count matches geometry.
                     Says nothing about whether the answer is RIGHT.
    claude_verified  a judgement was made by reading the source passage.

Only `claude_verified` rows enter the accuracy estimate. Mixing the two would quietly
report "the quote is real" as if it were "the answer is correct", which is the exact
conflation the citation-integrity work exists to prevent.

Usage:
    python3 scripts/audit_ledger.py build            # create/refresh the ledger
    python3 scripts/audit_ledger.py next --n 300     # emit the next ungraded batch
    python3 scripts/audit_ledger.py record --verdicts verdicts.json
    python3 scripts/audit_ledger.py status
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils import OUT_DIR, TEXT_DIR, WORK

RESULTS = WORK / "output" / "extraction" / "results"
MANIFEST = WORK / "output" / "extraction" / "corpus_manifest.csv"
LEDGER = OUT_DIR / "audit_ledger.jsonl"
SEED = 20260811
CONTEXT_CHARS = 700

ABSENT = {"not_discussed", "discussed_unclear", "not_applicable"}
_WS = re.compile(r"\s+")


def norm(text: str) -> str:
    return _WS.sub(" ", (text or "")).strip().casefold()


def pages_of(document_id: str) -> list[str]:
    path = TEXT_DIR / f"{document_id}.txt"
    if not path.exists():
        return []
    return path.read_text(encoding="utf-8", errors="ignore").split("\f")


_CODEBOOK: dict[str, object] | None = None


def absence_context(document_id: str, question_id: str, limit: int = 4) -> str:
    """What a grader needs to judge a `not_discussed`: the best matches in the document.

    An absence claim cites no page, so there is nothing to "read at the citation" — and
    falling back to page one means grading the answer against the title page, which is
    no check at all. The question is always *is this provision really absent*, and the
    only way to answer it is to search. Retrieval is already built for exactly this, so
    the ledger runs the same fused lexical+dense search the extractor uses and shows the
    top passages. If the provision is there, it will almost always be in these.

    Returns "" when the index is unavailable, so a grader sees an honest blank rather
    than a misleading page-one excerpt.
    """
    global _CODEBOOK
    try:
        from contract_search import open_database
        from grind_retrieve import fused_passages, load_document
        from utils import read_codebook
        if _CODEBOOK is None:
            _CODEBOOK = {q.qid: q for q in read_codebook()}
        question = _CODEBOOK.get(question_id)
        if question is None:
            return ""
        doc = load_document(document_id)
        connection = open_database(WORK / "cache" / "contract_search_structural.sqlite3")
        query = f"{question.question} {question.keywords}"
        passages = fused_passages(connection, query, budget=limit, doc=doc)
    except Exception:
        return ""
    return "\n---\n".join(
        f"[p{p.page_start}] {p.heading or ''}\n{p.text[:420]}" for p in passages[:limit])


def context_for(pages: list[str], page_spec: str, needle: str) -> str:
    """The passage a grader needs: around the quote if findable, else the cited page."""
    numbers = [int(n) for n in re.findall(r"\d+", page_spec or "") if 0 < int(n) <= len(pages)]
    window = "\n".join(pages[n - 1] for n in numbers[:3]) if numbers else "\n".join(pages[:1])
    if needle:
        target, hay = norm(needle)[:80], norm(window)
        index = hay.find(target)
        if index >= 0:
            raw = window[max(0, index - CONTEXT_CHARS // 2):index + CONTEXT_CHARS]
            return raw.strip()
    return window[:CONTEXT_CHARS * 2].strip()


def manifest() -> dict[str, dict[str, str]]:
    with MANIFEST.open(newline="", encoding="utf-8") as source:
        return {row["document_id"]: row for row in csv.DictReader(source)}


def ocr_documents() -> set[str]:
    return {Path(p).stem for p in glob.glob(
        str(WORK / "output" / "extraction" / "ocr_provenance" / "*.csv"))}


# ── row builders, one per program ────────────────────────────────────────────────

def llm_extract_rows() -> list[dict]:
    scans = ocr_documents()
    rows: list[dict] = []
    for path in glob.glob(str(RESULTS / "*" / "ensemble.jsonl")):
        document_id = os.path.basename(os.path.dirname(path))
        pages = pages_of(document_id)
        for line in open(path, encoding="utf-8"):
            if not line.strip():
                continue
            for answer in json.loads(line).get("answers", []):
                text = str(answer.get("answer", "")).strip()
                is_absent = text.lower() in ABSENT or not text
                page_spec = str(answer.get("page", ""))
                evidence = str(answer.get("evidence", ""))
                stratum = ("absence" if is_absent
                           else "scanned" if document_id in scans
                           else "multi_page_cite" if ";" in page_spec
                           else "substantive")
                rows.append({
                    "sheet": "2_llm_extract", "document_id": document_id,
                    "key": f"{document_id}|{answer.get('question_id','')}",
                    "question_id": answer.get("question_id", ""),
                    "answer": text[:500], "evidence": evidence[:500],
                    "page": page_spec, "stratum": stratum,
                    "source_context": (absence_context(document_id, answer.get("question_id",""))
                                       or context_for(pages, page_spec, evidence))
                                      if is_absent else
                                      context_for(pages, page_spec, evidence),
                    "quote_verbatim": bool(evidence) and norm(evidence)[:60] in norm(
                        "\n".join(pages)) if evidence else "",
                })
    return rows


def salary_rows() -> list[dict]:
    path = OUT_DIR / "salary_grid_score.csv"
    if not path.exists():
        return []
    by_file = {m["file_name"]: (did, m) for did, m in manifest().items()}
    scans = ocr_documents()
    rows: list[dict] = []
    with path.open(newline="", encoding="utf-8") as source:
        for index, row in enumerate(csv.DictReader(source)):
            document_id = (by_file.get(row["pdf"]) or ("", {}))[0]
            fidelity = float(row["fidelity"]) if row["fidelity"] else None
            stratum = ("low_fidelity" if fidelity is not None and fidelity < 0.95
                       else "duplicate" if "identical values" in row["note"]
                       else "scanned" if document_id in scans else "clean")
            rows.append({
                "sheet": "3_salary_schedule", "document_id": document_id,
                # The grid filename is NOT unique: 46 of 431 grids share a basename with
                # another (a schedule reprinted per contract year lands in a different
                # year folder under the same name). Keying on it made one verdict apply
                # to every grid with that name - 148 recorded verdicts marked all 431
                # rows. The key must identify the row, not merely describe it.
                # Row position, because nothing else is unique: one page can carry
                # several grids that share a truncated basename (Boston p63 has four).
                # A key that does not identify exactly one row lets a verdict leak.
                "key": f"salary#{index}|{row['grid'][:40]}",
                "grid": row["grid"], "pdf": row["pdf"],
                "pages": row["pages"], "cells": row["cells"],
                "fidelity": row["fidelity"], "capture": row["capture"],
                "page_capture": row.get("page_capture", ""),
                "expected_cells": row.get("expected_cells", ""),
                "note": row["note"][:200], "stratum": stratum,
                "source_context": context_for(pages_of(document_id), row["pages"], ""),
            })
    return rows


def rights_rows() -> list[dict]:
    path = OUT_DIR / "rights_score_long.csv"
    if not path.exists():
        return []
    rows: list[dict] = []
    cache: dict[str, list[str]] = {}
    with path.open(newline="", encoding="utf-8") as source:
        for index, row in enumerate(csv.DictReader(source)):
            document_id = row.get("document_id", "")
            if document_id not in cache:
                cache[document_id] = pages_of(document_id)
            rule = (row.get("statement_type") or "").strip().lower()
            model = (row.get("llm_judgment") or "").strip().lower()
            verified = str(row.get("quote_verified", "")).strip().lower()
            stratum = ("quote_unverified" if verified in ("false", "0", "no")
                       else "rule_vs_model" if rule and model and rule != model
                       else "agreed")
            quote = (row.get("quote") or "")[:500]
            rows.append({
                "sheet": "4_rights_score", "document_id": document_id,
                "key": f"{document_id}|{index}", "quote": quote,
                "statement_type": rule, "llm_judgment": model,
                "acting_party": row.get("acting_party", ""),
                "protected_party": row.get("protected_party", ""),
                "modal": row.get("modal", ""), "negation": row.get("negation", ""),
                "quote_verified": verified, "stratum": stratum,
                "source_context": context_for(cache[document_id], "", quote),
            })
    return rows


# ── ledger management ────────────────────────────────────────────────────────────

def draw(rows: list[dict], target: int, weights: dict[str, float],
         rng: random.Random) -> list[dict]:
    """Stratified draw that records each row's inclusion weight for the estimator."""
    if not rows:
        return []
    if len(rows) <= target:                      # population, not a sample
        return [{**r, "stratum_size": sum(1 for x in rows if x["stratum"] == r["stratum"]),
                 "sampling_weight": 1.0, "is_population": True} for r in rows]
    strata: dict[str, list[dict]] = {}
    for row in rows:
        strata.setdefault(row["stratum"], []).append(row)
    share = {name: weights.get(name, 1.0) * len(items) for name, items in strata.items()}
    total = sum(share.values()) or 1.0
    drawn: list[dict] = []
    for name, items in sorted(strata.items()):
        take = min(len(items), max(1, round(target * share[name] / total)))
        for row in rng.sample(items, take):
            drawn.append({**row, "stratum_size": len(items),
                          "sampling_weight": round(len(items) / take, 3),
                          "is_population": False})
    return drawn


def build(per_sheet: int) -> list[dict]:
    rng = random.Random(SEED)
    ledger = []
    ledger += draw(llm_extract_rows(), per_sheet,
                   {"absence": 3.0, "scanned": 2.0, "multi_page_cite": 1.5,
                    "substantive": 1.0}, rng)
    ledger += draw(salary_rows(), per_sheet,
                   {"low_fidelity": 3.0, "duplicate": 2.5, "scanned": 2.0, "clean": 1.0}, rng)
    ledger += draw(rights_rows(), per_sheet,
                   {"quote_unverified": 3.0, "rule_vs_model": 3.0, "agreed": 1.0}, rng)
    for row in ledger:
        # "pending" until a verdict is actually recorded. Defaulting to "computed"
        # counted un-checked rows as checked, which inflates the audit's coverage.
        row.setdefault("check_method", "pending")
        row.setdefault("verdict", "")
        row.setdefault("audit_note", "")
    return ledger


def load() -> list[dict]:
    if not LEDGER.exists():
        return []
    return [json.loads(line) for line in LEDGER.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def save(rows: list[dict]) -> None:
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    LEDGER.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
                      encoding="utf-8")


def status(rows: list[dict]) -> None:
    for sheet in sorted({r["sheet"] for r in rows}):
        group = [r for r in rows if r["sheet"] == sheet]
        read = [r for r in group if r["check_method"] == "claude_verified"]
        computed = [r for r in group if r["check_method"] == "computed"]
        graded = read + computed
        pop = "population" if group and group[0].get("is_population") else "sample"
        print(f"  {sheet:20s} {len(group):>5} rows ({pop:>10})  read {len(read):>4}"
              f"  computed {len(computed):>4}  remaining {len(group) - len(graded):>4}")
    total = len(rows)
    done = sum(1 for r in rows if r["check_method"] in ("claude_verified", "computed"))
    read_n = sum(1 for r in rows if r["check_method"] == "claude_verified")
    print(f"  {'TOTAL':20s} {total:>5} rows{'':>13}  read {read_n:>4}"
          f"  computed {done - read_n:>4}  remaining {total - done:>4}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build"); b.add_argument("--per-sheet", type=int, default=520)
    n = sub.add_parser("next"); n.add_argument("--n", type=int, default=300)
    n.add_argument("--sheet"); n.add_argument("--out", type=Path)
    r = sub.add_parser("record"); r.add_argument("--verdicts", type=Path, required=True)
    r.add_argument("--method", default="claude_verified",
                   choices=("claude_verified", "computed"),
                   help="how these verdicts were reached. 'computed' means a mechanical "
                        "check settled it (every value present on the cited page); "
                        "'claude_verified' means the source passage was read and judged. "
                        "They are reported separately because they answer different "
                        "questions and must not be pooled into one accuracy figure.")
    sub.add_parser("status")
    args = parser.parse_args()

    if args.command == "build":
        rows = build(args.per_sheet)
        existing = {r["key"]: r for r in load()}
        for row in rows:                       # preserve verdicts across a rebuild
            prior = existing.get(row["key"])
            # Preserve ANY recorded verdict, not just hand-read ones. Keeping only
            # claude_verified would have silently discarded 431 computed salary verdicts
            # on the next rebuild - hours of verification, gone to a rebuild nobody
            # thought was destructive.
            if prior and prior.get("check_method") in ("claude_verified", "computed"):
                row.update({k: prior[k] for k in ("check_method", "verdict", "audit_note")})
        save(rows)
        status(rows)
        return

    rows = load()
    if args.command == "status":
        status(rows)
    elif args.command == "next":
        pending = [r for r in rows if r["check_method"] != "claude_verified"
                   and (not args.sheet or r["sheet"] == args.sheet)][:args.n]
        out = args.out or (OUT_DIR / "audit_batch.json")
        out.write_text(json.dumps(pending, indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"  {len(pending)} rows -> {out}")
    elif args.command == "record":
        verdicts = json.loads(args.verdicts.read_text(encoding="utf-8"))
        by_key = {v["key"]: v for v in verdicts}
        applied = 0
        for row in rows:
            v = by_key.get(row["key"])
            if v:
                row["check_method"] = args.method
                row["verdict"] = v.get("verdict", "")
                row["audit_note"] = v.get("audit_note", "")[:300]
                applied += 1
        save(rows)
        print(f"  recorded {applied} verdict(s)")
        status(rows)


if __name__ == "__main__":
    main()
