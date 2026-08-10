#!/usr/bin/env python3
"""v9 full pipeline on 10 documents at a concurrency of 10 (previously 5).

IN-FLIGHT ARITHMETIC -- the reason RIGHTS_CONCURRENCY is set here.
run_new15.py launches all three coders SIMULTANEOUSLY per document, so aggregate in-flight
API calls are N_docs x (llm 1 + rights RIGHTS_CONCURRENCY + salary 1).

  v9 baseline:  5 docs x (1 + 8 + 1) = 50 in flight   (rights default is 8)
  naive 10:    10 docs x (1 + 8 + 1) = 100 in flight

The SOM endpoint admits ~44 concurrent and returns 429s beyond that (measured), and v9's
only response to a 429 is a flat 60-second sleep. At 100 in-flight the run would spend most
of its time asleep and could easily be SLOWER than concurrency 5.

So rights fan-out is set to 3:  10 x (1 + 3 + 1) = 50 in flight -- identical aggregate load
to the v9 baseline, but spread over twice as many documents. That isolates the variable the
test is actually about (document parallelism) instead of confounding it with endpoint
overload. Override with RIGHTS_CONCURRENCY if you want the naive version.
"""
import subprocess, time, os, re

REPO = "/home/cjg79/contracts/contract_coding_CG"
os.chdir(REPO)
PY = REPO + "/.venv/bin/python"

CONCURRENCY = int(os.environ.get("DOC_CONCURRENCY", "10"))
os.environ.setdefault("RIGHTS_CONCURRENCY", "3")
RUNLIST = "runlist_v9_10.tsv"
OUTBASE = "output_v9_c10"

def slug(d): return re.sub(r'[^a-z0-9_]', '', d.lower().replace(' ', '_'))
docs = [tuple(l.rstrip("\n").split("\t")) for l in open(RUNLIST) if l.strip()]

def launch(d, f):
    out = f"{OUTBASE}/{slug(d)}"
    os.makedirs(out, exist_ok=True)
    env = dict(os.environ, CONTRACT_OUT_DIR=out, PYTHONUNBUFFERED="1")
    specs = [("llm",    [PY, "scripts/llm_extract.py",  "--doc", f"{d}|{f}"]),
             ("rights", [PY, "scripts/rights_score.py", "--district", d, "--file", f]),
             ("salary", [PY, "scripts/salary_schedule.py", "--district", d, "--file", f])]
    procs = []
    for name, cmd in specs:
        lg = open(f"{out}/{name}.log", "w")
        procs.append(subprocess.Popen(cmd, stdout=lg, stderr=subprocess.STDOUT, env=env))
    return procs

os.makedirs(OUTBASE, exist_ok=True); os.makedirs("logs", exist_ok=True)
queue, active, done = list(docs), {}, []
start = time.monotonic(); last = 0
st = open("logs/v9_c10_status.tsv", "w")
st.write("time\telapsed_min\tconcurrency\tactive\tdone\tqueued\n"); st.flush()
print(f"v9 pipeline | {len(docs)} docs | CONCURRENCY={CONCURRENCY} | "
      f"RIGHTS_CONCURRENCY={os.environ['RIGHTS_CONCURRENCY']} | "
      f"~{CONCURRENCY*(1+int(os.environ['RIGHTS_CONCURRENCY'])+1)} in flight", flush=True)
while queue or active:
    el = (time.monotonic() - start) / 60
    for s in list(active):
        if all(p.poll() is not None for p in active[s]):
            done.append(s); del active[s]
            print(f"  [{el:6.1f}m] done: {s}  ({len(done)}/{len(docs)})", flush=True)
    while queue and len(active) < CONCURRENCY:
        d, f = queue.pop(0); active[slug(d)] = launch(d, f)
    if time.monotonic() - last >= 30:
        st.write(f"{time.strftime('%H:%M:%S')}\t{el:.1f}\t{CONCURRENCY}\t{len(active)}\t{len(done)}\t{len(queue)}\n"); st.flush()
        last = time.monotonic()
    time.sleep(5)
el = (time.monotonic()-start)/60
print(f"\nALL DONE {len(done)} docs in {el:.1f} min ({el/max(len(done),1):.1f} min/doc amortized)", flush=True)
st.write(f"ALL_DONE\t{el:.1f}\t{CONCURRENCY}\t0\t{len(done)}\t0\n"); st.close()
