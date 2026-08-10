#!/usr/bin/env python3
"""Full-pipeline (llm_extract + rights_score + salary_schedule) on the NEW 15-doc sample,
worker-pool style at a HARD-CODED concurrency of 5 documents at a time. Each doc gets its own
CONTRACT_OUT_DIR (output_new15/<slug>) so shared CSVs never race; caches are keyed by
document_id so resuming is safe. Writes logs/new15_status.tsv every 30s."""
import subprocess, time, os, re

REPO = "/home/cjg79/contracts/contract_coding_CG"
os.chdir(REPO)
PY = REPO + "/.venv/bin/python"

# ── HARD-CODED: run exactly 5 documents at a time (not an env var, not overridable). ──
CONCURRENCY = 5

RUNLIST = "runlist15.tsv"
OUTBASE = "output_new15"

def slug(d):
    return re.sub(r'[^a-z0-9_]', '', d.lower().replace(' ', '_'))

docs = [tuple(l.rstrip("\n").split("\t")) for l in open(RUNLIST) if l.strip()]

def launch(d, f):
    s = slug(d)
    out = f"{OUTBASE}/{s}"
    os.makedirs(out, exist_ok=True)
    env = dict(os.environ, CONTRACT_OUT_DIR=out, PYTHONUNBUFFERED="1")
    specs = [
        ("llm",    [PY, "scripts/llm_extract.py",    "--doc", f"{d}|{f}"]),
        ("rights", [PY, "scripts/rights_score.py",   "--district", d, "--file", f]),
        ("salary", [PY, "scripts/salary_schedule.py","--district", d, "--file", f]),
    ]
    return [subprocess.Popen(cmd, stdout=open(f"logs/new15_{s}_{n}.log", "a"),
            stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, env=env)
            for n, cmd in specs]

os.makedirs("logs", exist_ok=True)
os.makedirs(OUTBASE, exist_ok=True)
queue = list(docs)
active = {}
done = []
start = time.monotonic()
last = 0
st = open("logs/new15_status.tsv", "w")
st.write("time\telapsed_min\tconcurrency\tactive\tdone\tqueued\n"); st.flush()

while queue or active:
    el = (time.monotonic() - start) / 60
    for s in list(active):
        if all(p.poll() is not None for p in active[s]):
            done.append(s); del active[s]
    while queue and len(active) < CONCURRENCY:   # never more than 5 docs in flight
        d, f = queue.pop(0)
        active[slug(d)] = launch(d, f)
    if time.monotonic() - last >= 30:
        st.write(f"{time.strftime('%H:%M:%S')}\t{el:.1f}\t{CONCURRENCY}\t"
                 f"{len(active)}\t{len(done)}\t{len(queue)}\n"); st.flush()
        last = time.monotonic()
    time.sleep(5)

st.write(f"ALL_DONE {len(done)} docs at {time.strftime('%H:%M:%S')} "
         f"(elapsed {int((time.monotonic()-start)/60)} min)\n"); st.flush()
st.close()
