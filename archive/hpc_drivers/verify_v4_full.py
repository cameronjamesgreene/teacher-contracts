#!/usr/bin/env python3
"""Consolidated output_v4 verification across all three changes. Writes a human summary."""
import csv, re, os
from collections import Counter
from pathlib import Path

W = Path(os.path.expanduser("~/contracts/contract_coding_CG"))
OUT = W / "output_v4"
MISS = {"not_discussed", "discussed_unclear", "not_applicable", "ocr_needed", ""}
ABS = re.compile(r"not provided|no supporting|not found|not in (the )?excerpt|not discussed|"
                 r"no evidence|none found|not mentioned|not applicable|n/?a\b|excerpt", re.I)

def ans(r): return (r.get("answer") or "").strip()

print("=" * 64)
print("output_v4 VERIFICATION SUMMARY")
print("=" * 64)

# ---- Change 2: llm_extract ----
log = OUT / "llm_coding_log.csv"
if log.exists():
    lrows = list(csv.DictReader(log.open(encoding="utf-8")))
    docs = sorted(set(r["document_id"] for r in lrows))
    bug = [r for r in lrows if ans(r).lower() in MISS and (r.get("evidence") or "").strip()
           and not ABS.search(r.get("evidence") or "")]
    leaks = sum(1 for r in lrows if ans(r) in ("ND", "DU", "OCR_NEEDED", "N/A"))
    print("\n[Change 2 - llm_extract]  %d log rows, %d docs" % (len(lrows), len(docs)))
    print("  real-quote-next-to-missing (THE BUG): %d   (want 0)" % len(bug))
    print("  raw ND/DU/OCR_NEEDED leaks:            %d   (want 0)" % leaks)
    for tag, did in [("Chicago", "chicago"), ("Clark", "clark_county_2021"), ("Detroit", "detroit")]:
        rows = [r for r in lrows if did in r["document_id"]]
        sub = sum(1 for r in rows if ans(r).lower() not in MISS)
        print("    %-8s substantive %d / %d" % (tag, sub, len(rows)))
    ev = [r for r in lrows if "chicago" in r["document_id"] and r["Question ID"].startswith("evaluation_")]
    print("    Chicago evaluation_* answers:")
    for r in ev:
        print("      %-34s = %r" % (r["Question ID"], ans(r)[:40]))
else:
    print("\n[Change 2 - llm_extract]  MISSING output")

# ---- Change 1: salary_schedule ----
wide = OUT / "salary_schedule_wide"
grids = list(wide.rglob("*.csv")) if wide.exists() else []
print("\n[Change 1 - salary_schedule]  %d schedule grid CSVs" % len(grids))
byd = Counter()
vis = 0
for g in grids:
    parts = g.relative_to(wide).parts
    byd[parts[0] if parts else "?"] += 1
    try:
        if "MANUAL REVIEW" in g.read_text(errors="ignore")[:300]:
            vis += 1
    except Exception:
        pass
for d, n in sorted(byd.items()):
    print("    %-42s %d grids" % (d[:42], n))
print("    grids via vision/rotation path: %d" % vis)

# ---- Change 3: rights_score ----
rsum = OUT / "rights_score_summary.csv"
rlong = OUT / "rights_score_long.csv"
if rsum.exists():
    srows = list(csv.DictReader(rsum.open(encoding="utf-8")))
    lrows2 = list(csv.DictReader(rlong.open(encoding="utf-8"))) if rlong.exists() else []
    print("\n[Change 3 - rights_score]  %d docs, %d clause rows" % (len(srows), len(lrows2)))
    for r in srows:
        try:
            print("    %-30s clauses=%s scored=%s wr=%.2f mr=%.2f wResp=%.2f mResp=%.2f" % (
                r["file_name"][:30], r.get("total_clauses_extracted"), r.get("total_clauses_scored"),
                float(r.get("worker_rights") or 0), float(r.get("management_rights") or 0),
                float(r.get("worker_responsibilities") or 0), float(r.get("management_responsibilities") or 0)))
        except Exception as e:
            print("    %-30s (row parse error %s)" % (r.get("file_name", "?")[:30], e))
    if lrows2:
        pp = sum(1 for r in lrows2 if (r.get("protected_party") or "").strip())
        tp = sum(1 for r in lrows2 if (r.get("topic") or "").strip())
        lj = sum(1 for r in lrows2 if (r.get("llm_judgment") or "").strip())
        print("    split fields populated -> protected_party %d/%d, topic %d/%d, llm_judgment %d/%d"
              % (pp, len(lrows2), tp, len(lrows2), lj, len(lrows2)))
else:
    print("\n[Change 3 - rights_score]  NOT PRESENT (did not complete)")

print("\n" + "=" * 64)
print("VERIFICATION COMPLETE")
print("=" * 64)
