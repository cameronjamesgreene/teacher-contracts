#!/usr/bin/env python3
"""Run the 15 docs full-pipeline at the MEASURED-OPTIMAL fixed concurrency (default 6),
worker-pool style. Resumes in-progress docs from cache (per-call cache keyed by document
id/chunk), so nothing already computed is redone. Writes logs/v9_ramp_status.tsv."""
import subprocess, time, os, re
REPO="/home/cjg79/contracts/contract_coding_CG"; os.chdir(REPO)
PY=REPO+"/.venv/bin/python"
TARGET=int(os.environ.get("V9_CONC","6"))
def slug(d): return re.sub(r'[^a-z0-9_]','',d.lower().replace(' ','_'))
docs=[tuple(l.rstrip("\n").split("\t")) for l in open("v8p_runlist.tsv") if l.strip()]
def launch(d,f):
    s=slug(d); out=f"output_v9/{s}"; os.makedirs(out,exist_ok=True)
    env=dict(os.environ, CONTRACT_OUT_DIR=out, PYTHONUNBUFFERED="1")
    specs=[("llm",[PY,"scripts/llm_extract.py","--doc",f"{d}|{f}"]),
           ("rights",[PY,"scripts/rights_score.py","--district",d,"--file",f]),
           ("salary",[PY,"scripts/salary_schedule.py","--district",d,"--file",f])]
    return [subprocess.Popen(cmd,stdout=open(f"logs/v9_{s}_{n}.log","a"),
            stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL,env=env) for n,cmd in specs]
queue=list(docs); active={}; done=[]; start=time.monotonic(); last=0
st=open("logs/v9_ramp_status.tsv","w"); st.write("time\telapsed_min\ttarget_C\tactive\tdone\tqueued\n"); st.flush()
while queue or active:
    el=(time.monotonic()-start)/60
    for s in list(active):
        if all(p.poll() is not None for p in active[s]): done.append(s); del active[s]
    while queue and len(active)<TARGET:
        d,f=queue.pop(0); active[slug(d)]=launch(d,f)
    if time.monotonic()-last>=30:
        st.write(f"{time.strftime('%H:%M:%S')}\t{el:.1f}\t{TARGET}\t{len(active)}\t{len(done)}\t{len(queue)}\n"); st.flush(); last=time.monotonic()
    time.sleep(5)
st.write(f"ALL_DONE {len(done)} docs at {time.strftime('%H:%M:%S')}\n"); st.flush()
