#!/usr/bin/env python3
"""Dense passage embeddings stored in the same SQLite file as the passages.

Design notes, since each choice looks like an omission otherwise:

* **No ANN index.** At ~12,000 passages an approximate-nearest-neighbour index earns
  nothing: the float32 matrix for the whole corpus is ~18 MB and a NumPy dot product
  over one document's passages is sub-millisecond. `sqlite-vec` would be the obvious
  extension, but it performs brute-force search itself, so it would add a compiled
  dependency without changing the algorithm.
* **No embedding service.** `fastembed` runs `BAAI/bge-small-en-v1.5` through ONNX
  Runtime with no PyTorch, at ~13 passages/second, so the whole corpus embeds in about
  16 minutes on CPU.
* **Queries get BGE's retrieval prefix and documents do not**, via `query_embed` and
  `embed` respectively. Mixing the two conventions silently degrades retrieval, so both
  sides are computed by the same library here.

The result is that the entire retrieval layer — passages, the FTS5 index and the
vectors — is one reproducible file with no service to run.
"""

from __future__ import annotations

import argparse
import sqlite3
import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils import WORK

DB = WORK / "cache" / "contract_search_structural.sqlite3"
EMBED_MODEL = "BAAI/bge-small-en-v1.5"
DIMENSIONS = 384
BATCH = 256

SCHEMA = """
CREATE TABLE IF NOT EXISTS passage_vectors (
    passage_id INTEGER PRIMARY KEY REFERENCES passages(passage_id) ON DELETE CASCADE,
    model TEXT NOT NULL,
    dimensions INTEGER NOT NULL,
    embedding BLOB NOT NULL
);
"""

_MATRIX_CACHE: dict[str, tuple] = {}


def pack(vector) -> bytes:
    return struct.pack(f"<{len(vector)}f", *(float(value) for value in vector))


def unpack(blob: bytes, dimensions: int = DIMENSIONS):
    import numpy as np
    return np.frombuffer(blob, dtype="<f4", count=dimensions)


def build(db_path: Path = DB, model_name: str = EMBED_MODEL, rebuild: bool = False) -> None:
    """Embed every passage and store the vectors alongside the passages themselves."""
    from fastembed import TextEmbedding
    connection = sqlite3.connect(db_path)
    try:
        connection.executescript(SCHEMA)
        if rebuild:
            connection.execute("DELETE FROM passage_vectors")
            connection.commit()
        done = {row[0] for row in connection.execute("SELECT passage_id FROM passage_vectors")}
        rows = connection.execute(
            "SELECT passage_id, heading, text FROM passages ORDER BY passage_id").fetchall()
        pending = [row for row in rows if row[0] not in done]
        print(f"{len(rows)} passages, {len(pending)} to embed", flush=True)
        if not pending:
            return
        embedder = TextEmbedding(model_name)
        started = time.monotonic()
        for offset in range(0, len(pending), BATCH):
            chunk = pending[offset:offset + BATCH]
            # Heading carries the article or appendix name, which is often the only place
            # a topic word appears. This mirrors the documentTemplate used before.
            texts = [f"{heading}\n{text}" for _, heading, text in chunk]
            vectors = list(embedder.embed(texts))
            connection.executemany(
                "INSERT OR REPLACE INTO passage_vectors "
                "(passage_id, model, dimensions, embedding) VALUES (?, ?, ?, ?)",
                [(chunk[index][0], model_name, DIMENSIONS, pack(vector))
                 for index, vector in enumerate(vectors)])
            connection.commit()
            done_count = min(offset + BATCH, len(pending))
            rate = done_count / max(1e-6, time.monotonic() - started)
            print(f"  {done_count}/{len(pending)} ({rate:.0f}/s)", flush=True)
    finally:
        connection.close()


def _matrix(db_path: Path, document_id: str):
    """Per-document (ids, L2-normalised matrix), cached so a run pays for it once."""
    import numpy as np
    key = f"{db_path}::{document_id}"
    if key in _MATRIX_CACHE:
        return _MATRIX_CACHE[key]
    connection = sqlite3.connect(db_path)
    try:
        rows = connection.execute(
            "SELECT v.passage_id, v.embedding FROM passage_vectors v "
            "JOIN passages p ON p.passage_id = v.passage_id "
            "WHERE p.document_id = ? ORDER BY v.passage_id", (document_id,)).fetchall()
    finally:
        connection.close()
    if not rows:
        empty = ([], np.zeros((0, DIMENSIONS), dtype="float32"))
        _MATRIX_CACHE[key] = empty
        return empty
    ids = [row[0] for row in rows]
    matrix = np.vstack([unpack(row[1]) for row in rows]).astype("float32")
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    matrix = matrix / np.clip(norms, 1e-9, None)
    _MATRIX_CACHE[key] = (ids, matrix)
    return ids, matrix


_QUERY_EMBEDDER = None


def embed_query(query: str, model_name: str = EMBED_MODEL):
    """Embed a search query, with the retrieval prefix BGE expects on the query side."""
    import numpy as np
    global _QUERY_EMBEDDER
    if _QUERY_EMBEDDER is None:
        from fastembed import TextEmbedding
        _QUERY_EMBEDDER = TextEmbedding(model_name)
    vector = next(iter(_QUERY_EMBEDDER.query_embed([query])))
    vector = np.asarray(vector, dtype="float32")
    return vector / max(1e-9, float(np.linalg.norm(vector)))


def search(query: str, document_id: str, limit: int = 10,
           db_path: Path = DB) -> list[tuple[int, float]]:
    """Brute-force cosine search within one document. Returns (passage_id, score)."""
    import numpy as np
    ids, matrix = _matrix(db_path, document_id)
    if not ids:
        return []
    scores = matrix @ embed_query(query)
    top = np.argsort(-scores)[:limit]
    return [(ids[index], float(scores[index])) for index in top]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DB)
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--query", help="smoke-test a query instead of building")
    parser.add_argument("--document-id", default="manchester_school_district__83__de5d62c9")
    args = parser.parse_args()
    if args.query:
        started = time.monotonic()
        hits = search(args.query, args.document_id, db_path=args.db)
        print(f"{len(hits)} hits in {(time.monotonic() - started) * 1000:.0f}ms")
        for passage_id, score in hits:
            print(f"  {passage_id} {score:.4f}")
        return
    build(args.db, rebuild=args.rebuild)


if __name__ == "__main__":
    main()
