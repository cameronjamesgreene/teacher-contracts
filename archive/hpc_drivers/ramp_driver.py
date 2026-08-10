#!/usr/bin/env python3
"""Worker-pool concurrency ramp for the full pipeline on the 15 docs. Holds a target
number of DOCS running (each doc = llm_extract + rights_score + salary_schedule into its
own output_v9/<slug>), stepping the target up over time so throughput can be measured vs
concurrency. Writes logs/v9_ramp_status.tsv (time, elapsed, target_C, active, done, queued)."""
import subprocess, time, os, re
REPO="/home/cjg79/contracts/contract_coding_CG"; os.chdir(REPO)
PY=REPO+"/.venv/bin/python"
def slug(d): return re.sub(r'[^a-z0-9_]','',d.lower().replace(' ','_'))
docs=[tuple(l.rstrip("\n").split("\t")) for l in open("v8p_runlist.tsv") if l.strip()]
RAMP=[(0,2),(5,4),(11,6),(17,8),(24,10),(31,12),(39,15)]   # (elapsed_min, target docs)
def target(el):
    t=RAMP[0][1]
    for thr,c in RAMP:
        if el>=thr: t=c
    return t
def launch(d,f):
    s=slug(d); out=f"output_v9/{s}"; os.makedirs(out,exist_ok=True)
    env=dict(os.environ, CONTRACT_OUT_DIR=out, PYTHONUNBUFFERED="1")
    specs=[("llm",[PY,"scripts/llm_extract.py","--doc",f"{d}|{f}"]),
           ("rights",[PY,"scripts/rights_score.py","--district",d,"--file",f]),
           ("salary",[PY,"scripts/salary_schedule.py","--district",d,"--file",f])]
    procs=[]
    for name,cmd in specs:
        lg=open(f"logs/v9_{s}_{name}.log","w")
        procs.append(subprocess.Popen(cmd,stdout=lg,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL,env=env))
    return procs
queue=list(docs); active={}; done=[]; start=time.monotonic(); last=0
st=open("logs/v9_ramp_status.tsv","w"); st.write("time\telapsed_min\ttarget_C\tactive\tdone\tqueued\n"); st.flush()
while queue or active:
    el=(time.monotonic()-start)/60
    for s in list(active):
        if all(p.poll() is not None for p in active[s]): done.append(s); del active[s]
    tC=target(el)
    while queue and len(active)<tC:
        d,f=queue.pop(0); active[slug(d)]=launch(d,f)
    if time.monotonic()-last>=30:
        st.write(f"{time.strftime('%H:%M:%S')}\t{el:.1f}\t{tC}\t{len(active)}\t{len(done)}\t{len(queue)}\n"); st.flush(); last=time.monotonic()
    time.sleep(5)
st.write(f"ALL_DONE {len(done)} docs at {time.strftime('%H:%M:%S')}\n"); st.flush()
