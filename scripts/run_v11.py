#!/usr/bin/env python3
"""Four-step pipeline driver: OCR (if needed) -> llm_extract -> salary_schedule -> rights_score.

    python3 run_v11.py --docs-file /tmp/subset10.json --out output_v11 --concurrency 3
    python3 run_v11.py --doc "Polk County Public Schools|Polk_Teacher_CBA_2019-2022.pdf"

Each document gets its own CONTRACT_OUT_DIR (`<out>/<slug>`), because llm_extract and
rights_score open their CSVs in "w" mode and would otherwise clobber each other when run
concurrently. `merge_parallel_outputs.py` unions them afterwards.

CONCURRENCY, and why it is not simply "more"
────────────────────────────────────────────
som_client's governor is per-PROCESS. Each coder is a separate process, so N concurrent
documents x 1 running coder = N independent permit pools. The driver therefore divides the
global budget: each child gets SOM_MAX_INFLIGHT = max(2, 14 // concurrency), so the total
in-flight across the run stays inside the shared endpoint's fair share regardless of how
many documents are running. The governor's own back-off on x-som-global-in-flight is a
second line of defence, not the first.

Steps 2-4 run SEQUENTIALLY within a document rather than in parallel. They are not
independent: salary_schedule reads llm_main_dataset.csv to decide which documents have a
salary schedule at all, so running it before llm_extract finishes would silently process
nothing. The parallelism that matters is across documents, and inside each coder.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import utils                                                    # noqa: E402

SCRIPTS = Path(__file__).resolve().parent
WORK = SCRIPTS.parent
PDF_ROOT = utils.PDF_ROOT
PY = sys.executable


def resolve(document_id: str) -> tuple:
    """document_id -> (district folder, file name). The id encodes slugs, not paths, so
    match back against the real tree rather than trying to invert the slugify."""
    import hashlib
    for p in PDF_ROOT.rglob("*.pdf"):
        if p.name.startswith("._"):
            continue
        h = hashlib.sha1(str(p.relative_to(utils.ROOT)).encode()).hexdigest()[:8]
        did = (f"{utils.slugify(p.parent.name, 45)}__"
               f"{utils.slugify(p.stem, 55)}__{h}")
        if did == document_id:
            return p.parent.name, p.name
    return None, None


def run_step(name: str, cmd: list, env: dict, log: Path, timeout: int) -> dict:
    t = time.time()
    with open(log, "a", encoding="utf-8") as fh:
        fh.write(f"\n{'='*70}\n### {name}\n{' '.join(cmd)}\n{'='*70}\n")
        fh.flush()
        try:
            r = subprocess.run(cmd, stdout=fh, stderr=subprocess.STDOUT,
                               env=env, timeout=timeout, cwd=str(SCRIPTS))
            ok, code = r.returncode == 0, r.returncode
        except subprocess.TimeoutExpired:
            ok, code = False, "timeout"
    return {"step": name, "ok": ok, "code": code, "seconds": round(time.time() - t, 1)}


def process(district: str, file_name: str, out_root: Path, inflight: int,
            do_ocr: bool, timeout: int) -> dict:
    slug = utils.slugify(f"{district}_{Path(file_name).stem}", 80)
    out_dir = out_root / slug
    out_dir.mkdir(parents=True, exist_ok=True)
    log = out_dir / "run.log"
    env = dict(os.environ)
    env["CONTRACT_OUT_DIR"] = str(out_dir.relative_to(WORK)) \
        if str(out_dir).startswith(str(WORK)) else str(out_dir)
    env["SOM_MAX_INFLIGHT"] = str(inflight)
    env["PYTHONUNBUFFERED"] = "1"

    steps = []
    pdf = PDF_ROOT / district / file_name

    # ── STEP 1: OCR, only if the text layer is inadequate ────────────────────────────
    if do_ocr:
        t = time.time()
        try:
            import ocr_remote
            from som_client import get_client
            document_id = utils.document_id_for(district, file_name) \
                if hasattr(utils, "document_id_for") else None
            if document_id is None:
                import hashlib
                h = hashlib.sha1(str(pdf.relative_to(utils.ROOT)).encode()).hexdigest()[:8]
                document_id = (f"{utils.slugify(district, 45)}__"
                               f"{utils.slugify(Path(file_name).stem, 55)}__{h}")
            override = WORK / "cache" / "ocr_text" / f"{document_id}.txt"
            if override.exists() and override.stat().st_size:
                steps.append({"step": "1_ocr", "ok": True, "code": "cached",
                              "seconds": 0.0})
            else:
                res = ocr_remote.build_override(get_client(), pdf, document_id)
                steps.append({"step": "1_ocr", "ok": True,
                              "code": res.get("status"),
                              "pages_ocred": res.get("pages_ocred", 0),
                              "seconds": round(time.time() - t, 1)})
        except Exception as exc:
            steps.append({"step": "1_ocr", "ok": False,
                          "code": f"{type(exc).__name__}: {exc}"[:120],
                          "seconds": round(time.time() - t, 1)})

    doc_arg = f"{district}|{file_name}"
    steps.append(run_step("2_llm_extract",
                          [PY, "llm_extract.py", "--doc", doc_arg], env, log, timeout))
    steps.append(run_step("3_salary_schedule",
                          [PY, "salary_schedule.py", "--district", district,
                           "--file", file_name], env, log, timeout))
    steps.append(run_step("4_rights_score",
                          [PY, "rights_score.py", "--district", district,
                           "--file", file_name], env, log, timeout))

    produced = {p.name: p.stat().st_size for p in sorted(out_dir.glob("*.csv"))}
    grids = len(list((out_dir / "salary_schedule_wide").rglob("*.csv"))) \
        if (out_dir / "salary_schedule_wide").exists() else 0
    return {"district": district, "file": file_name, "slug": slug,
            "steps": steps, "csvs": produced, "salary_grids": grids,
            "total_seconds": round(sum(s["seconds"] for s in steps), 1)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--doc", action="append", metavar="DISTRICT|FILE.pdf")
    ap.add_argument("--docs-file", help="JSON list of document_ids")
    ap.add_argument("--out", default="output_v11")
    ap.add_argument("--concurrency", type=int, default=3)
    ap.add_argument("--global-inflight", type=int, default=14)
    ap.add_argument("--no-ocr", action="store_true")
    ap.add_argument("--timeout", type=int, default=7200)
    args = ap.parse_args()

    targets = []
    for d in (args.doc or []):
        district, _, file_name = d.partition("|")
        targets.append((district, file_name))
    if args.docs_file:
        ids = json.loads(Path(args.docs_file).read_text())
        print(f"resolving {len(ids)} document_id(s) against {PDF_ROOT} …", flush=True)
        for did in ids:
            district, file_name = resolve(did)
            if district:
                targets.append((district, file_name))
            else:
                print(f"  !! could not resolve {did}", flush=True)
    if not targets:
        print("nothing to do", file=sys.stderr)
        return 2

    out_root = WORK / args.out
    out_root.mkdir(parents=True, exist_ok=True)
    inflight = max(2, args.global_inflight // max(1, args.concurrency))
    print(f"\n{len(targets)} document(s) | concurrency={args.concurrency} | "
          f"SOM_MAX_INFLIGHT={inflight} per child "
          f"(<= {inflight * args.concurrency} in flight total)\n", flush=True)

    t0 = time.time()
    results = []
    with ThreadPoolExecutor(max_workers=args.concurrency) as ex:
        futs = [ex.submit(process, d, f, out_root, inflight, not args.no_ocr, args.timeout)
                for d, f in targets]
        for fu in futs:
            r = fu.result()
            results.append(r)
            marks = " ".join(("OK " if s["ok"] else "FAIL") + ":" + s["step"][2:]
                             for s in r["steps"])
            print(f"  {r['district'][:34]:36s} {r['total_seconds']:7.1f}s  {marks}",
                  flush=True)

    elapsed = time.time() - t0
    (out_root / "run_summary.json").write_text(json.dumps(results, indent=2))
    ok = sum(1 for r in results if all(s["ok"] for s in r["steps"]))
    print(f"\n{'='*72}")
    print(f"{ok}/{len(results)} document(s) completed all steps in {elapsed/60:.1f} min "
          f"({elapsed/max(1,len(results))/60:.1f} min/doc)")
    for step in ("1_ocr", "2_llm_extract", "3_salary_schedule", "4_rights_score"):
        got = [s for r in results for s in r["steps"] if s["step"] == step]
        if got:
            print(f"  {step:20s} {sum(1 for s in got if s['ok'])}/{len(got)} ok, "
                  f"median {sorted(s['seconds'] for s in got)[len(got)//2]:.1f}s")
    print(f"  salary grids emitted: {sum(r['salary_grids'] for r in results)}")
    print(f"  summary: {out_root / 'run_summary.json'}")
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
