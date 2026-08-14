#!/usr/bin/env python3
"""Draw the audit sample: the items a human (or Claude) then checks against the source.

An audit is only worth its sample. Drawing uniformly would spend most of the budget on
the easy majority — a full CBA answering a question it plainly answers, a six-lane matrix
on a clean page — and learn almost nothing. So this oversamples deliberately where the
recorded evidence says errors concentrate, and records the sampling weight so the reader
knows the sample is not representative and must not be read as a corpus rate.

Where errors concentrate, from this project's own measurements:

  llm_extract   absence claims (the largest error class in every version), citations into
                appendices and OCR'd scans, and answers on short documents where coverage
                is legitimately low and a wrong absence is hard to spot
  salary        grids below 0.95 fidelity, grids sharing values with another grid, and
                anything from a scanned document — where the scorer compares a vision
                reading against an OCR reading and cannot say which is wrong
  rights        clauses whose deterministic rule and the model's own holistic judgement
                disagree, plus any clause whose quote did not verify against the document

Deterministic: a fixed seed, so the same sample is redrawn on re-run and a grader cannot
quietly reshuffle until the numbers look better.

Usage:
    python3 scripts/sample_for_audit.py --out output/output_v12/audit_sample.json
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils import OUT_DIR, WORK

RESULTS = WORK / "output" / "extraction" / "results"
MANIFEST = WORK / "output" / "extraction" / "corpus_manifest.csv"
SEED = 20260811

ABSENT = {"not_discussed", "discussed_unclear", "not_applicable"}


def manifest() -> dict[str, dict[str, str]]:
    with MANIFEST.open(newline="", encoding="utf-8") as source:
        return {row["document_id"]: row for row in csv.DictReader(source)}


def ocr_documents() -> set[str]:
    return {Path(p).stem for p in glob.glob(
        str(WORK / "output" / "extraction" / "ocr_provenance" / "*.csv"))}


def sample_llm_extract(n: int, rng: random.Random) -> list[dict]:
    """Answers to re-read, oversampling absence claims and hard provenance."""
    scans = ocr_documents()
    pool: list[dict] = []
    for path in glob.glob(str(RESULTS / "*" / "ensemble.jsonl")):
        document_id = os.path.basename(os.path.dirname(path))
        for line in open(path, encoding="utf-8"):
            if not line.strip():
                continue
            for answer in json.loads(line).get("answers", []):
                text = str(answer.get("answer", "")).strip().lower()
                is_absent = text in ABSENT or not text
                pages = str(answer.get("page", ""))
                stratum = ("absence" if is_absent else
                           "scanned" if document_id in scans else
                           "multi_page_cite" if ";" in pages else "substantive")
                pool.append({"program": "llm_extract", "document_id": document_id,
                             "question_id": answer.get("question_id", ""),
                             "answer": str(answer.get("answer", ""))[:400],
                             "evidence": str(answer.get("evidence", ""))[:600],
                             "page": pages, "stratum": stratum})
    return _stratified(pool, n, rng, weights={"absence": 3.0, "scanned": 2.0,
                                              "multi_page_cite": 1.5, "substantive": 1.0})


def sample_salary(n: int, rng: random.Random) -> list[dict]:
    """Grids to re-read, oversampling low fidelity, duplicates and scans."""
    score_path = OUT_DIR / "salary_grid_score.csv"
    if not score_path.exists():
        return []
    scans = {m["file_name"] for did, m in manifest().items() if did in ocr_documents()}
    pool: list[dict] = []
    with score_path.open(newline="", encoding="utf-8") as source:
        for row in csv.DictReader(source):
            fidelity = float(row["fidelity"]) if row["fidelity"] else 1.0
            stratum = ("low_fidelity" if fidelity < 0.95 else
                       "duplicate" if "identical values" in row["note"] else
                       "scanned" if row["pdf"] in scans else "clean")
            pool.append({"program": "salary_schedule", "grid": row["grid"],
                         "pdf": row["pdf"], "pages": row["pages"],
                         "cells": row["cells"], "fidelity": row["fidelity"],
                         "capture": row["capture"], "page_capture": row.get("page_capture", ""),
                         "note": row["note"][:200], "stratum": stratum})
    return _stratified(pool, n, rng, weights={"low_fidelity": 3.0, "duplicate": 2.5,
                                              "scanned": 2.0, "clean": 1.0})


def sample_rights(n: int, rng: random.Random) -> list[dict]:
    """Clauses to re-read, oversampling rule-vs-model disagreement and unverified quotes."""
    long_path = OUT_DIR / "rights_score_long.csv"
    if not long_path.exists():
        return []
    pool: list[dict] = []
    with long_path.open(newline="", encoding="utf-8") as source:
        for row in csv.DictReader(source):
            rule = (row.get("statement_type") or "").strip().lower()
            model = (row.get("llm_judgment") or "").strip().lower()
            verified = str(row.get("quote_verified", "")).strip().lower()
            stratum = ("quote_unverified" if verified in ("false", "0", "no") else
                       "rule_vs_model" if rule and model and rule != model else "agreed")
            pool.append({"program": "rights_score",
                         "document_id": row.get("document_id", ""),
                         "quote": (row.get("quote") or "")[:500],
                         "statement_type": rule, "llm_judgment": model,
                         "acting_party": row.get("acting_party", ""),
                         "modal": row.get("modal", ""), "stratum": stratum})
    return _stratified(pool, n, rng, weights={"quote_unverified": 3.0,
                                              "rule_vs_model": 3.0, "agreed": 1.0})


def _stratified(pool: list[dict], n: int, rng: random.Random,
                weights: dict[str, float]) -> list[dict]:
    """Draw n items, allocating the budget by stratum weight x stratum size.

    Each item carries its inclusion weight so a reader can see how far the sample is
    from representative. Do NOT average the graded results directly — that is the
    oversampled rate, not the corpus rate.
    """
    if not pool:
        return []
    strata: dict[str, list[dict]] = {}
    for item in pool:
        strata.setdefault(item["stratum"], []).append(item)
    share = {name: weights.get(name, 1.0) * len(items) for name, items in strata.items()}
    total = sum(share.values()) or 1.0
    drawn: list[dict] = []
    for name, items in sorted(strata.items()):
        take = min(len(items), max(1, round(n * share[name] / total)))
        for item in rng.sample(items, take):
            drawn.append({**item,
                          "stratum_size": len(items),
                          "sampling_weight": round(len(items) / take, 2)})
    rng.shuffle(drawn)
    return drawn[:n]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=OUT_DIR / "audit_sample.json")
    parser.add_argument("--llm", type=int, default=30)
    parser.add_argument("--salary", type=int, default=24)
    parser.add_argument("--rights", type=int, default=24)
    args = parser.parse_args()

    rng = random.Random(SEED)
    sample = {"seed": SEED,
              "llm_extract": sample_llm_extract(args.llm, rng),
              "salary_schedule": sample_salary(args.salary, rng),
              "rights_score": sample_rights(args.rights, rng)}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(sample, indent=1, ensure_ascii=False), encoding="utf-8")
    for program, items in sample.items():
        if program == "seed":
            continue
        counts: dict[str, int] = {}
        for item in items:
            counts[item["stratum"]] = counts.get(item["stratum"], 0) + 1
        print(f"  {program:16s} {len(items):>3} items  {counts}")
    print(f"  -> {args.out}")


if __name__ == "__main__":
    main()
