"""SQLite-backed call cache, telemetry, results and evaluation store.

Replaces the flat one-JSON-file-per-call cache directories. Two motivations:

1. **Correctness.** The old cache key was (document, category, sub-batch, section index).
   It encoded no prompt version, no model, and no sampling config, so editing a prompt
   silently reused answers produced by the previous one. That is why cache files written on
   Jul 1 and an accuracy audit written on Jun 29 describe two different systems under
   identical filenames. The key here is a sha256 over the FULL request (som_client.
   request_cache_key), so any change to prompt/model/temperature/seed is a natural miss.

2. **Operability.** cache/llm_cache/ held 11,642 files in one flat directory on GPFS, polled
   by `ls | wc -l` on a 45-second timer. Per-call Path.exists() at that fan-out is a real
   cost, and there was no way to ask "how many calls did this document take?" or "what was
   p90 latency?" at all.

Legacy JSON is importable for forensics but is NEVER served as a cache hit -- its provenance
(which prompt, which config) is unrecoverable, and serving it would poison every future
measurement. At the throughput this overhaul targets, a full re-run costs about an hour;
being able to throw the cache away is the point.

Two database files, deliberately: corpus.sqlite is read-mostly (the FTS5 index, see
corpus.py) and runs.sqlite is write-heavy, so telemetry writes never contend with index
reads under WAL.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Optional

CACHE_DIR = Path(os.environ.get(
    "CONTRACT_CACHE_DIR",
    str(Path(__file__).resolve().parents[1] / "cache"),
))
RUNS_DB = Path(os.environ.get("CONTRACT_RUNS_DB", str(CACHE_DIR / "runs.sqlite")))

_SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

CREATE TABLE IF NOT EXISTS run(
  run_id TEXT PRIMARY KEY,
  started_at TEXT, ended_at TEXT,
  git_rev TEXT, config_json TEXT, prompt_version TEXT, model TEXT, notes TEXT);

CREATE TABLE IF NOT EXISTS call(
  call_id INTEGER PRIMARY KEY,
  cache_key TEXT,
  run_id TEXT, ts REAL, stage TEXT,
  document_id TEXT, qids TEXT,
  model TEXT, prompt_version TEXT,
  reasoning INT, temperature REAL, top_p REAL, seed INT, max_tokens INT,
  prompt_chars INT, prompt_tokens INT, cached_tokens INT,
  completion_tokens INT, reasoning_tokens INT,
  latency_ms INT, queue_wait_ms INT, admission_decision TEXT,
  global_in_flight INT, estimated_cost REAL, policy_tier TEXT, permits INT,
  http_status INT, attempt INT, finish_reason TEXT, error TEXT,
  response_json TEXT,
  legacy INT DEFAULT 0);

-- Only clean, non-legacy rows are servable as cache hits.
CREATE INDEX IF NOT EXISTS call_cache_idx
  ON call(cache_key) WHERE legacy = 0 AND error IS NULL;
CREATE INDEX IF NOT EXISTS call_doc_idx ON call(document_id, stage);
CREATE INDEX IF NOT EXISTS call_run_idx ON call(run_id);

CREATE TABLE IF NOT EXISTS answer(
  run_id TEXT, document_id TEXT, qid TEXT,
  answer TEXT, evidence TEXT, page INT, confidence TEXT, coder_notes TEXT,
  quote_verified INT, adopted_from TEXT, view_agreement TEXT,
  PRIMARY KEY(run_id, document_id, qid));

CREATE TABLE IF NOT EXISTS gold(
  document_id TEXT, qid TEXT,
  gold_answer TEXT, gold_page INT, gold_quote TEXT,
  source TEXT, tier TEXT, labeled_at TEXT, rationale TEXT,
  PRIMARY KEY(document_id, qid));

CREATE TABLE IF NOT EXISTS eval(
  run_id TEXT, document_id TEXT, qid TEXT, verdict TEXT, metric_json TEXT,
  PRIMARY KEY(run_id, document_id, qid));
"""


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path), timeout=60.0, check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con


class Store:
    """Thread-safe cache + telemetry sink. One instance per process.

    All writes go through a single lock and a single connection. At the volumes involved
    (a few thousand calls per document-batch) that is far cheaper than the GPFS directory
    scans it replaces, and it keeps WAL contention to one writer.
    """

    def __init__(self, db_path: Path = RUNS_DB, run_id: Optional[str] = None):
        self.db_path = Path(db_path)
        self._lock = threading.Lock()
        self._con = _connect(self.db_path)
        with self._lock:
            self._con.executescript(_SCHEMA)
            self._con.commit()
        self.run_id = run_id or uuid.uuid4().hex[:12]
        self._mem: dict = {}          # in-process hit cache, avoids repeat SELECTs

    # ── run bookkeeping ───────────────────────────────────────────────────────────────
    def start_run(self, config: Optional[dict] = None, notes: str = "") -> str:
        import subprocess
        try:
            git_rev = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=str(Path(__file__).resolve().parents[1]),
                capture_output=True, text=True, timeout=10,
            ).stdout.strip() or None
        except Exception:
            git_rev = None
        import som_client
        with self._lock:
            self._con.execute(
                "INSERT OR REPLACE INTO run(run_id, started_at, git_rev, config_json,"
                " prompt_version, model, notes) VALUES (?,?,?,?,?,?,?)",
                (self.run_id, time.strftime("%Y-%m-%dT%H:%M:%S"), git_rev,
                 json.dumps(config or {}, default=str),
                 som_client.PROMPT_VERSION, som_client.MODEL, notes),
            )
            self._con.commit()
        return self.run_id

    def end_run(self) -> None:
        with self._lock:
            self._con.execute("UPDATE run SET ended_at=? WHERE run_id=?",
                              (time.strftime("%Y-%m-%dT%H:%M:%S"), self.run_id))
            self._con.commit()

    # ── cache interface (som_client sink protocol) ────────────────────────────────────
    def lookup(self, cache_key: str) -> Optional[dict]:
        if cache_key in self._mem:
            return self._mem[cache_key]
        with self._lock:
            row = self._con.execute(
                "SELECT response_json FROM call WHERE cache_key=? AND legacy=0"
                " AND error IS NULL AND response_json IS NOT NULL LIMIT 1",
                (cache_key,),
            ).fetchone()
        if not row:
            return None
        try:
            value = json.loads(row["response_json"])
        except (ValueError, TypeError):
            return None
        self._mem[cache_key] = value
        return value

    def put(self, cache_key: str, value: dict) -> None:
        self._mem[cache_key] = value

    def record(self, **f: Any) -> None:
        """One row per API call -- cache entry and telemetry in the same place."""
        resp = f.get("response_json")
        with self._lock:
            self._con.execute(
                "INSERT INTO call(cache_key, run_id, ts, stage, document_id, qids, model,"
                " prompt_version, reasoning, temperature, top_p, seed, max_tokens,"
                " prompt_chars, prompt_tokens, cached_tokens, completion_tokens,"
                " reasoning_tokens, latency_ms, queue_wait_ms, admission_decision,"
                " global_in_flight, estimated_cost, policy_tier, permits, http_status,"
                " attempt, finish_reason, error, response_json, legacy)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0)",
                (f.get("cache_key"), self.run_id, time.time(), f.get("stage"),
                 f.get("document_id"), f.get("qids"), f.get("model"),
                 f.get("prompt_version"), f.get("reasoning"), f.get("temperature"),
                 f.get("top_p"), f.get("seed"), f.get("max_tokens"),
                 f.get("prompt_chars"), f.get("prompt_tokens"), f.get("cached_tokens"),
                 f.get("completion_tokens"), f.get("reasoning_tokens"),
                 f.get("latency_ms"), f.get("queue_wait_ms"), f.get("admission_decision"),
                 f.get("global_in_flight"), f.get("estimated_cost"), f.get("policy_tier"),
                 f.get("permits"), f.get("http_status"), f.get("attempt"),
                 f.get("finish_reason"), f.get("error"),
                 json.dumps(resp, ensure_ascii=False) if resp is not None else None),
            )
            self._con.commit()

    # ── results ───────────────────────────────────────────────────────────────────────
    def save_answer(self, document_id: str, qid: str, rec: dict,
                    adopted_from: str = "", view_agreement: str = "") -> None:
        with self._lock:
            self._con.execute(
                "INSERT OR REPLACE INTO answer(run_id, document_id, qid, answer, evidence,"
                " page, confidence, coder_notes, quote_verified, adopted_from,"
                " view_agreement) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (self.run_id, document_id, qid, rec.get("answer"), rec.get("evidence"),
                 rec.get("page"), rec.get("confidence"), rec.get("coder_notes"),
                 int(bool(rec.get("quote_verified"))), adopted_from, view_agreement),
            )
            self._con.commit()

    # ── reporting ─────────────────────────────────────────────────────────────────────
    def run_summary(self, run_id: Optional[str] = None) -> dict:
        rid = run_id or self.run_id
        with self._lock:
            row = self._con.execute(
                "SELECT COUNT(*) n, SUM(error IS NOT NULL) errs,"
                " SUM(prompt_tokens) ptok, SUM(completion_tokens) ctok,"
                " SUM(cached_tokens) cached, AVG(latency_ms) avg_ms,"
                " MAX(latency_ms) max_ms, AVG(permits) avg_permits,"
                " SUM(http_status=429) rate_limited,"
                " MIN(ts) t0, MAX(ts) t1 FROM call WHERE run_id=?", (rid,),
            ).fetchone()
        d = dict(row) if row else {}
        if d.get("t0") and d.get("t1"):
            d["wall_s"] = round(d["t1"] - d["t0"], 1)
            if d["wall_s"] > 0:
                d["calls_per_min"] = round(60.0 * (d.get("n") or 0) / d["wall_s"], 1)
        return d

    def close(self) -> None:
        with self._lock:
            self._con.close()


_STORE: Optional[Store] = None


def get_store(run_id: Optional[str] = None) -> Store:
    """Process-wide singleton, registered with som_client as its cache/telemetry sink."""
    global _STORE
    if _STORE is None:
        _STORE = Store(run_id=run_id)
        import som_client
        som_client.register_sink(_STORE)
    return _STORE


def import_legacy_cache(cache_root: Path = CACHE_DIR, limit: int = 0) -> int:
    """Import old flat-JSON cache files as legacy=1 rows (forensics only, never served).

    Kept so the historical answers remain queryable -- e.g. to show that a cache file
    written after an audit already contained the fix the audit reported as missing.
    """
    store = get_store()
    n = 0
    for sub in ("llm_cache", "rights_score_cache", "salary_schedule_cache"):
        d = Path(cache_root) / sub
        if not d.is_dir():
            continue
        for p in sorted(d.glob("*.json")):
            try:
                payload = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            with store._lock:
                store._con.execute(
                    "INSERT INTO call(cache_key, run_id, ts, stage, document_id,"
                    " response_json, legacy) VALUES (?,?,?,?,?,?,1)",
                    (None, "legacy", p.stat().st_mtime, sub,
                     "__".join(p.stem.split("__")[:3]),
                     json.dumps(payload, ensure_ascii=False)),
                )
            n += 1
            if limit and n >= limit:
                break
    with store._lock:
        store._con.commit()
    return n


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Inspect or migrate the pipeline store.")
    ap.add_argument("--import-legacy", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--summary", metavar="RUN_ID", nargs="?", const="")
    args = ap.parse_args()
    s = get_store()
    if args.import_legacy:
        print(f"imported {import_legacy_cache(limit=args.limit)} legacy cache files")
    if args.summary is not None:
        rid = args.summary or None
        if rid is None:
            rows = s._con.execute(
                "SELECT run_id, started_at, git_rev, notes FROM run"
                " ORDER BY started_at DESC LIMIT 10").fetchall()
            for r in rows:
                print(dict(r))
        else:
            print(json.dumps(s.run_summary(rid), indent=2))
