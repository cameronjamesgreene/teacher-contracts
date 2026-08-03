"""SQLite FTS5 page index over contract text: the retrieval half of the two-view coder.

WHY THIS EXISTS (and where it does NOT help)
────────────────────────────────────────────
95% of this pipeline's coding errors are `not_discussed` on a provision that IS in the
document, with zero fabricated values. That is a recall problem, and a controlled test on
four known false negatives showed the two obvious fixes are complementary rather than
competing:

    whole-document single call, reasoning on : 3/4
    FTS5 BM25 top-k passages                 : 2/4  -- but a DIFFERENT subset

The clearest case: Houston's contract is 1.06M chars (113k tokens). Asked what year its
salary schedule covers, the whole-document view returned `not_discussed`; BM25 returned
`"Appendix A-1 - Teacher Salary Schedule - 2005 - 2006"` verbatim, from a 15k-token
retrieval. That is lost-in-the-middle, and no amount of extra context fixes it. Conversely,
on Palm Beach the whole-document view found step increments that BM25's top-k missed
entirely, because the answer needed synthesis across distant sections.

So this index is a SECOND VIEW and a negative-check, never a replacement for reading the
document. Union the two views and gate on quote verification (see llm_extract).

Retrieval is useless or harmful for:
  * whole-document judgments with no lexicon (meta_doc_type_001) -- BM25 is pure noise
  * absence questions -- proving a provision is NOT present is not a retrieval task
  * number-only table pages -- a salary grid page is almost entirely digits and carries
    nearly no lexical signal. BM25 finds such pages only via a nearby heading; when the
    heading is an image or absent it will never rank them. That is what n_dollar and
    n_numeric are for, and why salary page location uses density OR text match.
  * OCR'd text -- token garble degrades BM25 exactly where recall is already worst.

Chose SQLite FTS5 over Meilisearch: FTS5 is in the standard library (verified present on
the HPC's Python 3.9 venv, SQLite 3.34.1), needs no daemon on a shared login node, and the
index is a single file that moves with scp like everything else in this project.
"""

from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import threading
from pathlib import Path
from typing import Iterable, Optional

CACHE_DIR = Path(os.environ.get(
    "CONTRACT_CACHE_DIR",
    str(Path(__file__).resolve().parents[1] / "cache"),
))
CORPUS_DB = Path(os.environ.get("CONTRACT_CORPUS_DB", str(CACHE_DIR / "corpus.sqlite")))

# Pages longer than this are indexed as overlapping parts so BM25 scores a focused span
# rather than diluting a hit across a wall of text. p99 page is ~8,900 chars.
MAX_PAGE_CHARS = int(os.environ.get("FTS_MAX_PAGE_CHARS", "9000"))
PAGE_PART_OVERLAP = 1000

_SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS doc(
  document_id TEXT PRIMARY KEY, district TEXT, file_name TEXT, pdf_path TEXT,
  text_sha256 TEXT NOT NULL, n_chars INT, n_pages INT, text_source TEXT,
  ingested_at TEXT DEFAULT CURRENT_TIMESTAMP);

CREATE TABLE IF NOT EXISTS page(
  page_uid    INTEGER PRIMARY KEY,
  document_id TEXT NOT NULL,
  page_no     INT NOT NULL,
  part_no     INT NOT NULL DEFAULT 0,
  char_start  INT, char_end INT,
  body        TEXT NOT NULL,
  n_dollar    INT DEFAULT 0,
  n_numeric   INT DEFAULT 0,
  is_toc      INT DEFAULT 0,
  head_match  INT DEFAULT 0,
  UNIQUE(document_id, page_no, part_no));

CREATE INDEX IF NOT EXISTS page_doc_idx ON page(document_id, page_no);

-- tokenchars '-+' keeps ET-15, BA+30, MA+45 and duty-free as single tokens; the default
-- unicode61 tokenizer shatters exactly the vocabulary these contracts are indexed on.
CREATE VIRTUAL TABLE IF NOT EXISTS page_fts USING fts5(
  body, content='page', content_rowid='page_uid',
  tokenize="unicode61 remove_diacritics 2 tokenchars '-+'");

CREATE TABLE IF NOT EXISTS term_df(term TEXT PRIMARY KEY, n_docs INT);
"""

_DOLLAR_RE = re.compile(r"\$\s?[\d,]{3,}")
_NUM_RE = re.compile(r"\b\d[\d,]{2,}(?:\.\d+)?\b")
_TOC_RE = re.compile(r"\.{4,}\s*\d+\s*$", re.M)
_SALARY_HEAD_RE = re.compile(
    r"\b(salary|wage|pay)\s+(schedule|scale|table|matrix|range)s?\b|"
    r"\bschedule\s+[A-Z]\b|\bteacher\s+salar", re.I)
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z\-+']{2,}")


def _connect(path: Path = CORPUS_DB) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path), timeout=60.0, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.executescript(_SCHEMA)
    return con


_LOCK = threading.Lock()
# One connection PER THREAD. A single sqlite3.Connection cannot service concurrent
# execute() calls even with check_same_thread=False -- it raises "bad parameter or other
# API misuse" under the two-view coder's thread pool. Readers don't block each other in WAL
# mode, so per-thread connections are both correct and free; the write path still funnels
# through _LOCK.
_LOCAL = threading.local()


def get_con() -> sqlite3.Connection:
    con = getattr(_LOCAL, "con", None)
    if con is None:
        con = _connect()
        _LOCAL.con = con
    return con


# ── ingestion ─────────────────────────────────────────────────────────────────────────────

def _split_page(text: str) -> list:
    """Yield (part_no, offset, body) for one page, splitting only oversized pages."""
    if len(text) <= MAX_PAGE_CHARS:
        return [(0, 0, text)]
    parts, i, n = [], 0, 0
    step = MAX_PAGE_CHARS - PAGE_PART_OVERLAP
    while i < len(text):
        parts.append((n, i, text[i:i + MAX_PAGE_CHARS]))
        i += step
        n += 1
    return parts


def index_document(document_id: str, text: str, district: str = "", file_name: str = "",
                   pdf_path: str = "", text_source: str = "pdftotext",
                   con: Optional[sqlite3.Connection] = None) -> int:
    """(Re)index one document's text. Idempotent: identical text is a no-op.

    Pages come free from the form-feed delimiters that pdftotext emits natively and that
    splice_ocr/hybrid_ocr normalise olmocr2's `<!-- page N -->` markers into, so page
    numbers here line up with the rest of the pipeline and with the printed document.
    """
    con = con or get_con()
    sha = hashlib.sha256(text.encode("utf-8", "ignore")).hexdigest()
    pages = text.split("\f")
    with _LOCK:
        row = con.execute("SELECT text_sha256 FROM doc WHERE document_id=?",
                          (document_id,)).fetchone()
        if row and row["text_sha256"] == sha:
            return 0                                    # unchanged; nothing to do
        # Rebuild this document's pages. Delete from the FTS shadow first (external-content
        # tables do not cascade), otherwise the index keeps rows pointing at dead rowids.
        uids = [r[0] for r in con.execute(
            "SELECT page_uid FROM page WHERE document_id=?", (document_id,))]
        for uid in uids:
            con.execute("INSERT INTO page_fts(page_fts, rowid, body) VALUES('delete', ?, ?)",
                        (uid, con.execute("SELECT body FROM page WHERE page_uid=?",
                                          (uid,)).fetchone()[0]))
        con.execute("DELETE FROM page WHERE document_id=?", (document_id,))

        n = 0
        for page_no, raw in enumerate(pages, start=1):
            for part_no, offset, body in _split_page(raw):
                if not body.strip():
                    continue
                cur = con.execute(
                    "INSERT INTO page(document_id, page_no, part_no, char_start, char_end,"
                    " body, n_dollar, n_numeric, is_toc, head_match)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (document_id, page_no, part_no, offset, offset + len(body), body,
                     len(_DOLLAR_RE.findall(body)), len(_NUM_RE.findall(body)),
                     1 if len(_TOC_RE.findall(body)) >= 3 else 0,
                     1 if _SALARY_HEAD_RE.search(body) else 0))
                con.execute("INSERT INTO page_fts(rowid, body) VALUES (?,?)",
                            (cur.lastrowid, body))
                n += 1
        con.execute(
            "INSERT OR REPLACE INTO doc(document_id, district, file_name, pdf_path,"
            " text_sha256, n_chars, n_pages, text_source) VALUES (?,?,?,?,?,?,?,?)",
            (document_id, district, file_name, pdf_path, sha, len(text), len(pages),
             text_source))
        con.commit()
    return n


def rebuild_term_df(con: Optional[sqlite3.Connection] = None) -> int:
    """Document frequency per term, used to prune uninformative query terms.

    Without this, a query built from a codebook row's keywords is dominated by words that
    appear in every contract ("teacher", "district", "board"), and BM25 ranks on noise.
    """
    con = con or get_con()
    with _LOCK:
        con.execute("DELETE FROM term_df")
        seen: dict = {}
        for doc_id, body in con.execute("SELECT document_id, body FROM page"):
            for w in set(m.group(0).lower() for m in _WORD_RE.finditer(body)):
                seen.setdefault(w, set()).add(doc_id)
        counts = {term: len(docs) for term, docs in seen.items()}
        con.executemany("INSERT OR REPLACE INTO term_df(term, n_docs) VALUES (?,?)",
                        list(counts.items()))
        con.commit()
    return len(counts)


def n_docs(con: Optional[sqlite3.Connection] = None) -> int:
    con = con or get_con()
    return con.execute("SELECT COUNT(*) FROM doc").fetchone()[0]


# ── retrieval ─────────────────────────────────────────────────────────────────────────────

def _fts_quote(term: str) -> str:
    """FTS5 string literal. Doubling embedded quotes is the only escape it defines."""
    return '"' + term.replace('"', '""') + '"'


def build_query(terms: Iterable[str], max_df_frac: float = 0.5,
                con: Optional[sqlite3.Connection] = None) -> str:
    """OR-query from codebook terms, dropping terms that appear in >max_df_frac of docs.

    Multi-word terms are kept as FTS5 phrases, which is the whole point of not stripping
    them upstream -- "code of ethics" must stay a phrase, not decay into "ethics".
    """
    con = con or get_con()
    total = max(1, n_docs(con))
    kept = []
    for t in terms:
        t = re.sub(r"[^\w\s\-+']", " ", str(t)).strip().lower()
        t = re.sub(r"\s+", " ", t)
        if len(t) < 3:
            continue
        if " " not in t:                       # single words are DF-pruned; phrases are not
            row = con.execute("SELECT n_docs FROM term_df WHERE term=?", (t,)).fetchone()
            if row and total > 4 and row["n_docs"] / total > max_df_frac:
                continue
        kept.append(_fts_quote(t))
    seen, uniq = set(), []
    for k in kept:
        if k not in seen:
            seen.add(k)
            uniq.append(k)
    return " OR ".join(uniq[:24])


def search_pages(document_id: str, terms: Iterable[str], k: int = 12,
                 neighbours: int = 1, con: Optional[sqlite3.Connection] = None) -> list:
    """Top-k pages of one document by BM25, expanded by +/-`neighbours` pages.

    NOTE bm25() returns NEGATIVE scores where more-negative is better, so the ordering is
    ASCENDING. Getting this backwards silently returns the least relevant pages, which is
    the single easiest way to make retrieval look useless.
    """
    con = con or get_con()
    query = build_query(terms, con=con)
    if not query:
        return []
    try:
        rows = con.execute(
            "SELECT p.page_no, p.part_no, bm25(page_fts) AS score"
            " FROM page_fts JOIN page p ON p.page_uid = page_fts.rowid"
            " WHERE page_fts MATCH ? AND p.document_id = ?"
            " ORDER BY score ASC LIMIT ?", (query, document_id, k)).fetchall()
    except sqlite3.OperationalError:
        return []                                        # malformed query -> no view B
    if not rows:
        return []
    wanted = set()
    for r in rows:
        for d in range(-neighbours, neighbours + 1):
            wanted.add(r["page_no"] + d)
    out = con.execute(
        "SELECT page_no, part_no, body FROM page WHERE document_id=? AND page_no IN (%s)"
        " ORDER BY page_no, part_no" % ",".join("?" * len(wanted)),
        [document_id] + sorted(wanted)).fetchall()
    return [(r["page_no"], r["part_no"], r["body"]) for r in out]


def passages(document_id: str, terms: Iterable[str], k: int = 12, neighbours: int = 1,
             max_chars: int = 120_000, con: Optional[sqlite3.Connection] = None) -> str:
    """Retrieved pages assembled in DOCUMENT ORDER with page markers.

    Document order matters: the model is being asked for a page number alongside its quote,
    and relevance-ordered fragments make that citation unreliable.
    """
    hits = search_pages(document_id, terms, k=k, neighbours=neighbours, con=con)
    if not hits:
        return ""
    chunks, total = [], 0
    for page_no, part_no, body in hits:
        head = f"\n[page {page_no}]\n"
        if total + len(body) + len(head) > max_chars:
            break
        chunks.append(head + body)
        total += len(body) + len(head)
    return "".join(chunks)


def has_any_hit(document_id: str, terms: Iterable[str],
                con: Optional[sqlite3.Connection] = None) -> list:
    """Page numbers matching these terms. Backs the never-silent-false-negative check:
    a `not_discussed` answer on a document whose text DOES contain the topic keywords is
    reported with the page numbers attached, so the residual is a bounded, inspectable
    list instead of a silent zero."""
    hits = search_pages(document_id, terms, k=6, neighbours=0, con=con)
    return sorted({p for p, _, _ in hits})


def salary_candidate_pages(document_id: str, min_dollar: int = 12,
                           con: Optional[sqlite3.Connection] = None) -> list:
    """Pages that look like a salary grid: a salary heading OR high dollar density,
    excluding table-of-contents pages.

    Replaces a case-sensitive Title-Case/ALL-CAPS heading regex that missed lowercase and
    image-headed schedules. Density is the half that matters: a grid page is mostly digits
    and BM25 cannot see it at all.
    """
    con = con or get_con()
    rows = con.execute(
        "SELECT DISTINCT page_no FROM page WHERE document_id=? AND is_toc=0"
        " AND (head_match=1 OR n_dollar>=?) ORDER BY page_no",
        (document_id, min_dollar)).fetchall()
    return [r["page_no"] for r in rows]


def locate_quote(document_id: str, quote: str,
                 con: Optional[sqlite3.Connection] = None) -> Optional[int]:
    """Page number containing this quote, for repairing the `page` output field."""
    con = con or get_con()
    words = _WORD_RE.findall(quote or "")
    if len(words) < 5:
        return None
    probe = " ".join(words[:8])
    try:
        row = con.execute(
            "SELECT p.page_no FROM page_fts JOIN page p ON p.page_uid = page_fts.rowid"
            " WHERE page_fts MATCH ? AND p.document_id=? ORDER BY bm25(page_fts) ASC"
            " LIMIT 1", (_fts_quote(probe), document_id)).fetchone()
    except sqlite3.OperationalError:
        return None
    return row["page_no"] if row else None


# ── CLI ───────────────────────────────────────────────────────────────────────────────────

def index_all_cached(text_dir: Optional[Path] = None) -> tuple:
    """Index every document already extracted into cache/extracted_text (or ocr_text)."""
    import utils
    con = get_con()
    docs = pages = 0
    for d in (text_dir or CACHE_DIR / "extracted_text",):
        for p in sorted(Path(d).glob("*.txt")):
            document_id = p.stem
            ocr = CACHE_DIR / "ocr_text" / f"{document_id}.txt"
            src, label = (ocr, "ocr") if ocr.exists() and ocr.stat().st_size else (p, "pdftotext")
            text = src.read_text(encoding="utf-8", errors="ignore")
            parts = document_id.split("__")
            n = index_document(document_id, text, district=parts[0] if parts else "",
                               file_name=parts[1] if len(parts) > 1 else "",
                               text_source=label, con=con)
            if n:
                docs += 1
                pages += n
    return docs, pages


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Build/query the FTS5 contract index.")
    ap.add_argument("--build", action="store_true", help="index cache/extracted_text")
    ap.add_argument("--search", nargs="+", metavar="TERM")
    ap.add_argument("--doc", default="", help="document_id (prefix match allowed)")
    ap.add_argument("--k", type=int, default=8)
    args = ap.parse_args()
    con = get_con()
    if args.build:
        d, p = index_all_cached()
        print(f"indexed {d} document(s), {p} page-parts")
        print(f"term_df: {rebuild_term_df(con)} terms over {n_docs(con)} documents")
    if args.search:
        doc = args.doc
        if doc:
            row = con.execute("SELECT document_id FROM doc WHERE document_id LIKE ?",
                              (doc + "%",)).fetchone()
            doc = row["document_id"] if row else doc
        for page_no, part_no, body in search_pages(doc, args.search, k=args.k):
            print(f"--- page {page_no}.{part_no} ---\n{body[:300]}\n")
