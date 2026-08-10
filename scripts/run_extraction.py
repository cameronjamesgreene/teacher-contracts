#!/usr/bin/env python3
"""Run the grind pipeline over many documents: sweep -> verify -> reconcile -> audit.

The stages were designed to be run one document at a time, by hand, and that is how
the measured results were produced. This is the driver that makes the corpus a single
command, in the role `run_parallel_v6.sh` plays for the v9 programs.

## Per-document output, not per-stage

Every stage writes into `output/extraction/results/<document_id>/`, so two documents
can never overwrite each other's `sweep.jsonl`. This is the same reasoning that gave
the v9 driver a per-document `CONTRACT_OUT_DIR`.

## Resume is the default

Each stage is skipped when its output already exists, so an interrupted corpus run is
resumed by re-running the same command. `--force` re-runs everything. Model calls are
the expensive resource here and they are all upstream of a file on disk.

## Concurrency is bounded on purpose

The SOM endpoint has a measured ceiling around 24-32 in-flight requests. In-flight
calls are `documents-in-flight x (sweep-workers or verify-workers)`, so the default of
3 documents x 6 workers stays under it with room for retries. Raising
`--documents-in-flight` without lowering the per-stage workers is how a corpus run
starts failing halfway through on rate limits.

## The cost driver is absence, not length

Measured: per-question extraction is roughly flat at 210-290 calls per document
regardless of size, and a 4-page tentative agreement took 18.5 minutes because 92 of
106 questions hit the expensive absence-verification path. Do not schedule by page
count.

Usage:
    python3 scripts/run_extraction.py --all
    python3 scripts/run_extraction.py --document-id manchester_school_district__83__de5d62c9
    python3 scripts/run_extraction.py --all --stage sweep --stage verify   # extract only
"""

from __future__ import annotations

import argparse
import csv
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils import WORK

SCRIPTS = Path(__file__).resolve().parent
MANIFEST = WORK / "output" / "extraction" / "corpus_manifest.csv"
RESULTS = WORK / "output" / "extraction" / "results"
LOGS = WORK / "logs"

STAGES = ("sweep", "verify", "reconcile", "subset", "audit")
# subset is off by default: measured +0.023 on the ensemble and 0.000 on verify alone,
# well inside the +/-0.05 run-to-run noise, at the cost of another model pass.
DEFAULT_STAGES = ("sweep", "verify", "reconcile", "audit")

_print_lock = threading.Lock()


def say(message: str) -> None:
    with _print_lock:
        print(message, flush=True)


def documents() -> list[dict[str, str]]:
    with MANIFEST.open(newline="", encoding="utf-8") as source:
        return list(csv.DictReader(source))


def run_stage(name: str, command: list[str], log: Path) -> bool:
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as sink:
        sink.write(f"\n$ {' '.join(str(part) for part in command)}\n")
        sink.flush()
        result = subprocess.run(command, stdout=sink, stderr=subprocess.STDOUT)
    return result.returncode == 0


# A sweep batch that dies on a network error reports "0 hits", which is indistinguishable
# downstream from a window that was read and genuinely contained nothing. So a document
# can finish, look complete, and be missing a fifth of its content with nothing to say so
# — measured: one VPN drop voided 41.6% of one document's windows and 19.3% of another's,
# and both were only caught by reading logs by hand. Above this share the sweep is not
# trusted and is re-run.
MAX_ERRORED_BATCH_SHARE = 0.05


def sweep_damage(log: Path, from_line: int) -> tuple[int, int]:
    """(errored, total) sweep batches recorded in the log after `from_line`."""
    if not log.exists():
        return (0, 0)
    lines = log.read_text(encoding="utf-8", errors="ignore").splitlines()[from_line:]
    batches = [line for line in lines if line.lstrip().startswith("batch ")]
    errored = [line for line in batches if "ERROR API" in line]
    return (len(errored), len(batches))


def log_lines(log: Path) -> int:
    if not log.exists():
        return 0
    return len(log.read_text(encoding="utf-8", errors="ignore").splitlines())


def process(row: dict[str, str], stages: tuple[str, ...], force: bool,
            sweep_workers: int, verify_workers: int) -> dict[str, object]:
    document_id = row["document_id"]
    out = RESULTS / document_id
    out.mkdir(parents=True, exist_ok=True)
    log = LOGS / f"extract_{document_id}.log"
    started = time.monotonic()

    sweep = out / "sweep.jsonl"
    verify = out / "verify.jsonl"
    ensemble = out / "ensemble.jsonl"
    final = out / "final.jsonl"
    audit = out / "citation_audit.csv"

    done: list[str] = []
    skipped: list[str] = []
    degraded = ""          # set when a sweep could not be completed cleanly

    def needed(stage: str, target: Path) -> bool:
        if stage not in stages:
            return False
        if target.exists() and not force:
            skipped.append(stage)
            return False
        return True

    say(f"  start   {row['district'][:38]:40s} {row['pdf_pages']:>4}pp")

    if needed("sweep", sweep):
        command = [sys.executable, str(SCRIPTS / "grind_sweep.py"),
                   "--document-id", document_id, "--out", str(sweep),
                   "--workers", str(sweep_workers), "--resume"]
        damage = ""
        # One retry: a transient outage that voided windows is worth another pass,
        # a persistent one is worth reporting rather than looping on.
        for sweep_attempt in (1, 2):
            mark = log_lines(log)
            ok = run_stage("sweep", command, log)
            if not ok:
                return {"document_id": document_id, "status": "failed", "stage": "sweep",
                        "log": str(log), "seconds": round(time.monotonic() - started, 1)}
            errored, total = sweep_damage(log, mark)
            share = errored / total if total else 0.0
            if share <= MAX_ERRORED_BATCH_SHARE:
                damage = ""
                break
            damage = f"{errored}/{total} windows lost to network errors ({share:.0%})"
            say(f"  ! {row['district'][:34]:36s} sweep {damage}"
                + ("; re-running" if sweep_attempt == 1 else "; STILL DEGRADED"))
            if sweep_attempt == 1:
                sweep.unlink(missing_ok=True)   # force a genuine re-run, not a resume
        done.append("sweep")
        if damage:
            # Recorded, not swallowed: the document continues so the run completes, but
            # its coverage is not comparable with the rest and the report says so.
            degraded = damage

    if needed("verify", verify):
        ok = run_stage("verify", [
            sys.executable, str(SCRIPTS / "grind_verify.py"),
            "--document-id", document_id, "--out", str(verify),
            "--progress", str(out / "verify_progress.jsonl"),
            "--workers", str(verify_workers), "--resume"], log)
        if not ok:
            return {"document_id": document_id, "status": "failed", "stage": "verify",
                    "log": str(log), "seconds": round(time.monotonic() - started, 1)}
        done.append("verify")

    if needed("reconcile", ensemble):
        # B first: absence-verified retrieval is the stronger single extractor (0.842
        # against the sweep's 0.684), so it takes precedence where both answered.
        inputs = []
        if verify.exists():
            inputs += ["--input", f"B={verify}"]
        if sweep.exists():
            inputs += ["--input", f"A={sweep}"]
        if not inputs:
            return {"document_id": document_id, "status": "failed", "stage": "reconcile",
                    "log": str(log), "seconds": round(time.monotonic() - started, 1)}
        ok = run_stage("reconcile", [
            sys.executable, str(SCRIPTS / "grind_reconcile.py"),
            *inputs, "--out", str(ensemble), "--document-id", document_id], log)
        if not ok:
            return {"document_id": document_id, "status": "failed", "stage": "reconcile",
                    "log": str(log), "seconds": round(time.monotonic() - started, 1)}
        done.append("reconcile")

    if needed("subset", final):
        ok = run_stage("subset", [
            sys.executable, str(SCRIPTS / "grind_subset.py"),
            "--input", str(ensemble), "--out", str(final),
            "--document-id", document_id, "--resume"], log)
        if not ok:
            return {"document_id": document_id, "status": "failed", "stage": "subset",
                    "log": str(log), "seconds": round(time.monotonic() - started, 1)}
        done.append("subset")

    # Whatever the last stage produced is this document's answer set.
    best = final if final.exists() else (ensemble if ensemble.exists() else verify)

    if needed("audit", audit) and best.exists():
        run_stage("audit", [
            sys.executable, str(SCRIPTS / "audit_citations.py"),
            str(best), "--out", str(audit)], log)
        done.append("audit")

    elapsed = round(time.monotonic() - started, 1)
    say(f"  done    {row['district'][:38]:40s} {elapsed:>7.1f}s  "
        f"ran={','.join(done) or '-'}  reused={','.join(skipped) or '-'}")
    return {"document_id": document_id, "status": "degraded" if degraded else "ok",
            "output": str(best), "ran": ",".join(done), "reused": ",".join(skipped),
            "seconds": elapsed, "degraded": degraded}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--all", action="store_true", help="every usable document")
    target.add_argument("--document-id", action="append", dest="document_ids")
    parser.add_argument("--stage", action="append", dest="stages", choices=STAGES,
                        help=f"repeatable; default {', '.join(DEFAULT_STAGES)}")
    parser.add_argument("--documents-in-flight", type=int, default=3,
                        help="documents processed concurrently (default 3)")
    parser.add_argument("--sweep-workers", type=int, default=6)
    parser.add_argument("--verify-workers", type=int, default=4)
    parser.add_argument("--force", action="store_true",
                        help="re-run stages whose output already exists")
    parser.add_argument("--report", type=Path,
                        default=RESULTS / "run_report.csv")
    args = parser.parse_args()

    rows = documents()
    if args.document_ids:
        wanted = set(args.document_ids)
        rows = [row for row in rows if row["document_id"] in wanted]
        unknown = wanted - {row["document_id"] for row in rows}
        if unknown:
            raise SystemExit(f"not in the manifest: {', '.join(sorted(unknown))}")
    else:
        rows = [row for row in rows if row["text_status"] == "usable"]
    if not rows:
        raise SystemExit("no documents to run")

    stages = tuple(args.stages) if args.stages else DEFAULT_STAGES
    in_flight = max(1, args.documents_in_flight)
    say(f"{len(rows)} document(s), stages: {', '.join(stages)}, "
        f"{in_flight} in flight x up to {max(args.sweep_workers, args.verify_workers)} workers")
    started = time.monotonic()

    results: list[dict[str, object]] = []
    with ThreadPoolExecutor(max_workers=in_flight) as pool:
        futures = {pool.submit(process, row, stages, args.force,
                               args.sweep_workers, args.verify_workers): row
                   for row in rows}
        for future in as_completed(futures):
            row = futures[future]
            try:
                results.append(future.result())
            except Exception as error:              # one dead document, not a dead run
                say(f"  FAILED  {row['district'][:38]:40s} {error}")
                results.append({"document_id": row["document_id"], "status": "error",
                                "stage": str(error), "seconds": 0})

    failed = [r for r in results if r.get("status") not in ("ok", "degraded")]
    degraded = [r for r in results if r.get("status") == "degraded"]
    say(f"\n{len(results) - len(failed) - len(degraded)}/{len(results)} documents "
        f"completed cleanly in {(time.monotonic() - started) / 60:.1f} min")
    for result in failed:
        say(f"  FAILED {result['document_id']} at {result.get('stage')} "
            f"— see {result.get('log', LOGS)}")
    if degraded:
        # Loud, and separate from failure: these produced output, which is exactly why
        # they are dangerous. Their coverage is not comparable with the rest.
        say(f"\n  {len(degraded)} document(s) DEGRADED — output exists but is incomplete:")
        for result in degraded:
            say(f"    {result['document_id']}: {result['degraded']}")
        say("  Re-run these once the endpoint is healthy:")
        say("    " + " ".join(f"--document-id {r['document_id']}" for r in degraded))

    args.report.parent.mkdir(parents=True, exist_ok=True)
    fields = ["document_id", "status", "stage", "output", "ran", "reused", "seconds",
              "degraded", "log"]
    with args.report.open("w", newline="", encoding="utf-8") as sink:
        writer = csv.DictWriter(sink, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(sorted(results, key=lambda r: str(r["document_id"])))
    say(f"report -> {args.report}")
    say("\nBuild the wide/long CSVs with:\n"
        f"  python3 scripts/grind_to_dataset.py {RESULTS}/*/final.jsonl "
        f"{RESULTS}/*/ensemble.jsonl")
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
