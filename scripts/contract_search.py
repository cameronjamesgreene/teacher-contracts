#!/usr/bin/env python3
"""Build and query a page-aware SQLite FTS5 index of contract text.

The index is deliberately local and deterministic. It supplies candidate passages
for the experimental PydanticAI extractor; it does not make network calls.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sqlite3
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable

from utils import PDF_ROOT, WORK, Document, load_documents

DEFAULT_DB_PATH = WORK / "cache" / "contract_search.sqlite3"
# Shorter passages improve clause-level BM25 precision while retaining enough
# surrounding context to establish the clause's subject and conditions.
_PASSAGE_TARGET_CHARS = 1_800
_MIN_PASSAGE_CHARS = 450
_INDEX_VERSION = "structural-passages-v4"
_WORD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9'/-]*")
_STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "does", "for", "from",
    "how", "if", "in", "is", "it", "of", "on", "or", "the", "this", "to", "what",
    "when", "which", "with",
}


@dataclass(frozen=True)
class SearchHit:
    passage_id: int
    document_id: str
    page_start: int
    page_end: int
    heading: str
    snippet: str
    rank: float


@dataclass(frozen=True)
class Passage:
    passage_id: int
    document_id: str
    page_start: int
    page_end: int
    heading: str
    text: str


_SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS documents (
    document_id TEXT PRIMARY KEY,
    district TEXT NOT NULL,
    file_name TEXT NOT NULL,
    source_path TEXT NOT NULL,
    source_sha256 TEXT NOT NULL,
    page_count INTEGER,
    text_status TEXT NOT NULL,
    indexed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS passages (
    passage_id INTEGER PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    page_start INTEGER NOT NULL,
    page_end INTEGER NOT NULL,
    heading TEXT NOT NULL DEFAULT '',
    text TEXT NOT NULL,
    text_sha256 TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS passages_document_pages
    ON passages(document_id, page_start, page_end);
CREATE VIRTUAL TABLE IF NOT EXISTS passages_fts USING fts5(
    heading,
    text,
    content='passages',
    content_rowid='passage_id',
    tokenize='porter unicode61'
);
CREATE TRIGGER IF NOT EXISTS passages_ai AFTER INSERT ON passages BEGIN
    INSERT INTO passages_fts(rowid, heading, text)
    VALUES (new.passage_id, new.heading, new.text);
END;
CREATE TRIGGER IF NOT EXISTS passages_ad AFTER DELETE ON passages BEGIN
    INSERT INTO passages_fts(passages_fts, rowid, heading, text)
    VALUES ('delete', old.passage_id, old.heading, old.text);
END;
CREATE TRIGGER IF NOT EXISTS passages_au AFTER UPDATE ON passages BEGIN
    INSERT INTO passages_fts(passages_fts, rowid, heading, text)
    VALUES ('delete', old.passage_id, old.heading, old.text);
    INSERT INTO passages_fts(rowid, heading, text)
    VALUES (new.passage_id, new.heading, new.text);
END;
"""


def open_database(path: Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Open an initialized local FTS database."""
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(_SCHEMA)
    return connection


def _normalize_text(text: str) -> str:
    return re.sub(r"[ \t]+", " ", text).strip()


def _is_heading(paragraph: str) -> bool:
    compact = _normalize_text(paragraph)
    if not compact or len(compact) > 160:
        return False
    upper_letters = sum(char.isupper() for char in compact)
    letters = sum(char.isalpha() for char in compact)
    starts_article = bool(re.match(r"^(ARTICLE|APPENDIX|SECTION)\b", compact, re.I))
    return starts_article or (letters >= 5 and upper_letters / letters >= 0.8)


def _split_long_paragraph(paragraph: str) -> list[str]:
    """Split only oversized paragraphs, preferring sentence boundaries."""
    if len(paragraph) <= _PASSAGE_TARGET_CHARS:
        return [paragraph]
    sentences = re.split(r"(?<=[.!?;:])\s+", paragraph)
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        if current and len(current) + len(sentence) + 1 > _PASSAGE_TARGET_CHARS:
            chunks.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        chunks.append(current)
    return chunks


def build_passages(text: str) -> list[tuple[int, int, str, str]]:
    """Return structural passages as (PDF page range, section heading, text).

    Contract headings define the primary boundaries. Character limits are only a
    fallback for unusually long sections and split at paragraph/sentence boundaries;
    adjacent articles are never packed together merely because they fit.
    """
    sections: list[tuple[str, list[tuple[int, str]]]] = []
    current_heading = "DOCUMENT PREAMBLE"
    current_heading_page = 1
    current_units: list[tuple[int, str]] = []

    def finish_section() -> None:
        nonlocal current_units
        if current_units:
            sections.append((current_heading, current_units))
        elif current_heading != "DOCUMENT PREAMBLE" and not sections:
            # Preserve the document title for metadata retrieval. Later empty
            # headings are structural markers, not independently useful clauses.
            sections.append((current_heading, [(current_heading_page, current_heading)]))
        current_units = []

    for page_number, raw_page in enumerate(text.split("\f"), start=1):
        page = raw_page.strip()
        if not page:
            continue
        paragraphs = [_normalize_text(p) for p in re.split(r"\n\s*\n", page) if _normalize_text(p)]
        for paragraph in paragraphs:
            if _is_heading(paragraph):
                finish_section()
                current_heading = paragraph
                current_heading_page = page_number
                continue
            for unit in _split_long_paragraph(paragraph):
                current_units.append((page_number, unit))
    finish_section()

    passages: list[tuple[int, int, str, str]] = []
    for heading, units in sections:
        current: list[tuple[int, str]] = []
        current_chars = 0
        for page_number, unit in units:
            added_chars = len(unit) + (2 if current else 0)
            if current and current_chars + added_chars > _PASSAGE_TARGET_CHARS:
                passages.append((
                    current[0][0], current[-1][0], heading,
                    "\n\n".join(part for _, part in current),
                ))
                current = []
                current_chars = 0
            current.append((page_number, unit))
            current_chars += len(unit) + (2 if len(current) > 1 else 0)
        if current:
            passages.append((
                current[0][0], current[-1][0], heading,
                "\n\n".join(part for _, part in current),
            ))
    return passages


def index_document(connection: sqlite3.Connection, document: Document) -> int:
    """Replace one document's indexed passages when its extracted text changed."""
    source_hash = hashlib.sha256(f"{_INDEX_VERSION}\\0{document.text}".encode("utf-8")).hexdigest()
    existing = connection.execute(
        "SELECT source_sha256 FROM documents WHERE document_id = ?", (document.document_id,)
    ).fetchone()
    if existing and existing["source_sha256"] == source_hash:
        return connection.execute(
            "SELECT COUNT(*) FROM passages WHERE document_id = ?", (document.document_id,)
        ).fetchone()[0]

    passage_rows = build_passages(document.text)
    with connection:
        connection.execute("DELETE FROM passages WHERE document_id = ?", (document.document_id,))
        connection.execute("DELETE FROM documents WHERE document_id = ?", (document.document_id,))
        connection.execute(
            """INSERT INTO documents
            (document_id, district, file_name, source_path, source_sha256, page_count, text_status, indexed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                document.document_id, document.district, document.file_name, str(document.path), source_hash,
                document.page_count, document.text_status, datetime.now(UTC).isoformat(),
            ),
        )
        connection.executemany(
            """INSERT INTO passages (document_id, page_start, page_end, heading, text, text_sha256)
            VALUES (?, ?, ?, ?, ?, ?)""",
            [
                (document.document_id, start, end, heading, passage, hashlib.sha256(passage.encode("utf-8")).hexdigest())
                for start, end, heading, passage in passage_rows
            ],
        )
    return len(passage_rows)


def index_documents(path: Path, documents: Iterable[Document]) -> dict[str, int]:
    """Index documents and return passage counts keyed by document ID."""
    with open_database(path) as connection:
        return {document.document_id: index_document(connection, document) for document in documents}


def query_terms(query: str, limit: int = 24) -> list[str]:
    """Reduce plain-language query text to distinct searchable terms.

    Public because any alternative retrieval engine benchmarked against this one
    must receive the same terms; comparing a stopword-stripped query against a raw
    natural-language sentence measures preprocessing, not retrieval.
    """
    terms: list[str] = []
    for raw in _WORD_RE.findall(query.casefold()):
        term = raw.strip("'-/")
        if len(term) >= 3 and term not in _STOP_WORDS and term not in terms:
            terms.append(term)
    return terms[:limit]


def _fts_query(query: str) -> str:
    terms = query_terms(query)
    if not terms:
        raise ValueError("Query contains no searchable terms")
    # OR gives codebook synonym queries recall; BM25 still ranks passages that
    # contain multiple useful terms above single-term incidental matches.
    return " OR ".join(f'"{term.replace(chr(34), "")}"' for term in terms)


def search_passages(
    connection: sqlite3.Connection,
    document_id: str,
    query: str,
    limit: int = 8,
) -> list[SearchHit]:
    """Return document-scoped BM25-ranked passages for plain-language query text."""
    if limit < 1 or limit > 30:
        raise ValueError("limit must be between 1 and 30")
    fts_query = _fts_query(query)
    rows = connection.execute(
        """SELECT p.passage_id, p.document_id, p.page_start, p.page_end, p.heading,
                  snippet(passages_fts, 1, '[', ']', '…', 32) AS snippet,
                  bm25(passages_fts, 2.0, 1.0) AS rank
           FROM passages_fts
           JOIN passages p ON p.passage_id = passages_fts.rowid
           WHERE passages_fts MATCH ? AND p.document_id = ?
           ORDER BY bm25(passages_fts, 2.0, 1.0)
           LIMIT ?""",
        (fts_query, document_id, limit),
    ).fetchall()
    return [SearchHit(**dict(row)) for row in rows]


def read_passages(
    connection: sqlite3.Connection,
    document_id: str,
    passage_ids: list[int],
) -> list[Passage]:
    """Read passages only when they belong to the requested document."""
    if not passage_ids or len(passage_ids) > 20:
        raise ValueError("passage_ids must contain 1 to 20 IDs")
    placeholders = ",".join("?" for _ in passage_ids)
    rows = connection.execute(
        f"""SELECT passage_id, document_id, page_start, page_end, heading, text
             FROM passages WHERE document_id = ? AND passage_id IN ({placeholders})
             ORDER BY page_start, passage_id""",
        [document_id, *passage_ids],
    ).fetchall()
    return [Passage(**dict(row)) for row in rows]


def available_documents() -> list[tuple[str, str]]:
    """Return every locally available district/PDF pair in deterministic order."""
    return [
        (district.name, pdf.name)
        for district in sorted(PDF_ROOT.iterdir())
        if district.is_dir()
        for pdf in sorted(district.glob("*.pdf"))
    ]


def _parse_doc(value: str) -> tuple[str, str]:
    if "|" not in value:
        raise argparse.ArgumentTypeError("document must be DISTRICT|FILE.pdf")
    return tuple(value.split("|", 1))  # type: ignore[return-value]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    sub = parser.add_subparsers(dest="command", required=True)
    index_parser = sub.add_parser("index", help="index one or more PDF documents")
    index_source = index_parser.add_mutually_exclusive_group(required=True)
    index_source.add_argument("--doc", action="append", type=_parse_doc)
    index_source.add_argument("--all", action="store_true", help="index every locally available PDF")
    search_parser = sub.add_parser("search", help="search an indexed document")
    search_parser.add_argument("--document-id", required=True)
    search_parser.add_argument("query")
    search_parser.add_argument("--limit", type=int, default=8)
    args = parser.parse_args()

    if args.command == "index":
        docs = load_documents(available_documents() if args.all else args.doc)
        counts = index_documents(args.db, docs)
        for document in docs:
            print(f"{document.document_id}: {counts[document.document_id]} passages")
        return
    with open_database(args.db) as connection:
        for hit in search_passages(connection, args.document_id, args.query, args.limit):
            print(f"[{hit.passage_id}] pp. {hit.page_start}-{hit.page_end} {hit.heading}")
            print(f"  {hit.snippet}\n")


if __name__ == "__main__":
    main()
