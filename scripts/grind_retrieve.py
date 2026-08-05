#!/usr/bin/env python3
"""Shared retrieval and grounding layer for the extraction variants.

Three lessons from the blinded review are enforced here rather than left to a
prompt, because a prompt cannot be relied on for any of them:

1. **The host owns the page number.** The baseline scored 0.105 on pages purely by
   reporting the number printed on the page, which in this contract runs one behind
   the PDF page in the body and up to seven behind in the appendices. Retrieval
   already knows each passage's true PDF page range, so the model is never asked for
   a page; the page is derived from whichever passage the evidence was found in.
2. **Evidence must be contiguous.** `validate_batch` accepted ellipsis-stitched
   quotes because it checked containment per fragment. Here a quote must appear as
   one unbroken span in one passage.
3. **Retrieval fuses lexical and dense.** FTS5 cannot reach appendix provisions at
   any depth when the wording shares no vocabulary with the question; dense retrieval
   reaches them at depth 8. Embeddings live in the same SQLite file as the passages,
   so retrieval needs no service.
"""

from __future__ import annotations

import csv
import difflib
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from contract_search import Passage, open_database, read_passages, search_passages

BUDGET = 10          # raised from 8; recovers the one fusion regression (P@10 0.944)
FUSION_DEPTH = 20    # pull deeper than the budget so each engine can promote finds
_WS = re.compile(r"\s+")
_ELLIPSIS = re.compile(r"\.\.\.|…|\[\.\.\.\]")

WORK_ROOT = Path(__file__).resolve().parent.parent
MANIFEST = WORK_ROOT / "output" / "extraction" / "corpus_manifest.csv"


@dataclass(frozen=True)
class DocumentContext:
    """Which document a retrieval or grounding call refers to.

    Everything in this module used to assume Manchester. Passing the document
    explicitly is what allows the pipeline to run on the rest of the corpus, and it
    is the value injected as PydanticAI `deps`.
    """
    document_id: str
    text_path: Path
    district: str = ""
    file_name: str = ""
    page_count: int = 0
    text_status: str = "usable"

    def pages(self) -> list[str]:
        """Form-feed delimited pages; index N-1 is PDF page N. Cached per document."""
        cached = _PAGE_CACHE.get(self.document_id)
        if cached is None:
            cached = self.text_path.read_text(encoding="utf-8", errors="ignore").split("\f")
            _PAGE_CACHE[self.document_id] = cached
        return cached


_PAGE_CACHE: dict[str, list[str]] = {}


def corpus() -> list[DocumentContext]:
    """Every document with usable extracted text, from the frozen corpus manifest."""
    documents: list[DocumentContext] = []
    with MANIFEST.open(newline="", encoding="utf-8") as source:
        for row in csv.DictReader(source):
            if row["text_status"] != "usable":
                continue
            # Manifest paths are repo-relative so a fresh checkout works anywhere;
            # an absolute path is still honoured for older manifests.
            text_path = Path(row["text_path"])
            documents.append(DocumentContext(
                document_id=row["document_id"],
                text_path=text_path if text_path.is_absolute() else WORK_ROOT / text_path,
                district=row["district"], file_name=row["file_name"],
                page_count=int(row["pdf_pages"] or 0), text_status=row["text_status"]))
    return documents


def load_document(document_id: str) -> DocumentContext:
    for document in corpus():
        if document.document_id == document_id:
            return document
    raise KeyError(f"{document_id} is absent from {MANIFEST.name} or lacks usable text")


# Retained so the existing variant scripts keep running unchanged.
DOCUMENT_ID = "manchester_school_district__83__de5d62c9"
MANCHESTER = DocumentContext(
    document_id=DOCUMENT_ID,
    text_path=WORK_ROOT / "cache" / "extracted_text" / f"{DOCUMENT_ID}.txt")
TEXT_PATH = MANCHESTER.text_path


def norm(text: str) -> str:
    """Whitespace/quote-normalised text for substring comparison."""
    return _WS.sub(" ", (text or "").replace("’", "'").replace("‘", "'")
                   .replace("“", '"').replace("”", '"').replace("–", "-")
                   .replace("—", "-").casefold()).strip()


@dataclass(frozen=True)
class Grounding:
    """Where an answer's evidence was actually found, according to the host."""
    passage_id: int | None
    page: str
    verbatim: bool
    contiguous: bool
    error: str


def dense_ids(query: str, doc: DocumentContext, limit: int) -> list[int]:
    """Dense passage ids for one document, from the embeddings stored in SQLite.

    A missing vectors table raises rather than returning nothing. Silently returning no
    dense hits would degrade retrieval to lexical-only, which measurably loses appendix
    provisions (appendix recall 0.375 lexical against 0.750 dense) while still producing
    plausible output — the worst kind of failure.
    """
    from sqlite_vectors import search as vector_search
    hits = vector_search(query, doc.document_id, limit=limit)
    if not hits and not _has_vectors(doc):
        raise RuntimeError(
            f"no embeddings for {doc.document_id}. Build them with:\n"
            f"  .venv/bin/python scripts/sqlite_vectors.py")
    return [passage_id for passage_id, _ in hits]


def _has_vectors(doc: DocumentContext) -> bool:
    import sqlite3
    from sqlite_vectors import DB as VECTOR_DB
    connection = sqlite3.connect(VECTOR_DB)
    try:
        row = connection.execute(
            "SELECT 1 FROM passage_vectors v JOIN passages p ON p.passage_id = v.passage_id "
            "WHERE p.document_id = ? LIMIT 1", (doc.document_id,)).fetchone()
    except sqlite3.Error:
        return False
    finally:
        connection.close()
    return row is not None


def fused_passages(connection, query: str, budget: int = BUDGET,
                   doc: DocumentContext = MANCHESTER) -> list[Passage]:
    """Interleave FTS5 and dense retrieval, then hydrate full passage text.

    Interleaving rather than score fusion: the two retrievers fail on different
    questions, and reciprocal-rank fusion rewards passages both engines found, which is
    the opposite of what makes the pair valuable. Interleaving guarantees each engine
    half the budget and so preserves its unique finds.
    """
    lexical = [hit.passage_id for hit in
               search_passages(connection, doc.document_id, query, limit=FUSION_DEPTH)]
    dense = dense_ids(query, doc, FUSION_DEPTH)
    ordered: list[int] = []
    seen: set[int] = set()
    for index in range(max(len(lexical), len(dense))):
        for source in (lexical, dense):
            if index < len(source) and source[index] not in seen:
                seen.add(source[index])
                ordered.append(source[index])
                if len(ordered) >= budget:
                    break
        if len(ordered) >= budget:
            break
    passages = {p.passage_id: p for p in read_passages(connection, doc.document_id, ordered)}
    return [passages[pid] for pid in ordered if pid in passages]


def page_label(passage: Passage) -> str:
    if passage.page_start == passage.page_end:
        return str(passage.page_start)
    return f"{passage.page_start}-{passage.page_end}"


def ground(evidence: str, passages: list[Passage],
           doc: DocumentContext = MANCHESTER) -> Grounding:
    """Locate a quote in the supplied passages and derive its true PDF page.

    Returns the page from the passage that actually contains the quote, ignoring
    whatever the model may have claimed.
    """
    quote = norm(evidence)
    if len(quote) < 15:
        return Grounding(None, "not_applicable", False, False, "evidence too short to verify")
    if _ELLIPSIS.search(evidence or ""):
        # An ellipsis means omitted governing words; the span is not one clause.
        for passage in passages:
            fragments = [norm(f) for f in _ELLIPSIS.split(evidence) if len(norm(f)) >= 15]
            if fragments and all(f in norm(passage.text) for f in fragments):
                return Grounding(passage.passage_id, page_label(passage), True, False,
                                 "evidence is stitched from non-contiguous fragments")
        return Grounding(None, "not_applicable", False, False,
                         "evidence is stitched and not found in one passage")
    for passage in passages:
        if quote in norm(passage.text):
            # A passage can straddle a page break, so its range is not the clause's
            # page. Prefer the single page that actually holds the quote and fall
            # back to the passage range only when the span crosses a break.
            return Grounding(passage.passage_id,
                             exact_page(evidence, doc) or page_label(passage), True, True, "")
    return Grounding(None, "not_applicable", False, False,
                     "evidence is not a verbatim span of any supplied passage")


def exact_page(evidence: str, doc: DocumentContext = MANCHESTER) -> str:
    """The single PDF page wholly containing this quote, or "" if it spans a break."""
    quote = norm(evidence)
    if len(quote) < 15:
        return ""
    for index, block in enumerate(doc.pages(), start=1):
        if quote in norm(block):
            return str(index)
    return ""


_NORM_REPL = {"’": "'", "‘": "'", "“": '"', "”": '"', "–": "-", "—": "-"}
_CLAUSE_END = ".;:!?"
MIN_ANCHOR_CHARS = 60      # exact-match run long enough to identify a clause
MAX_REPAIRED_CHARS = 1400  # a repaired quote is a clause, not a whole passage


def norm_with_map(text: str) -> tuple[str, list[int]]:
    """`norm` plus, for each output character, its index in the source text.

    The map is what lets the host emit a slice of the PASSAGE's own characters after
    locating a span by normalised comparison, so the emitted quote is verbatim by
    construction rather than by the model's promise.
    """
    out: list[str] = []
    index: list[int] = []
    previous_space = False
    for position, character in enumerate(text):
        character = _NORM_REPL.get(character, character)
        if character.isspace():
            if not previous_space and out:
                out.append(" ")
                index.append(position)
            previous_space = True
            continue
        previous_space = False
        for folded in character.casefold():
            out.append(folded)
            index.append(position)
    while out and out[-1] == " ":
        out.pop()
        index.pop()
    return "".join(out), index


def realign(evidence: str, passages: list[Passage]) -> str:
    """Replace a near-miss quote with the real clause it points at, without a model call.

    The model reliably identifies the right clause and unreliably transcribes it: it
    drops a word, normalises a stray space ("Blue Cross -Blue Shield"), or elides across
    a paragraph break. Find the longest exact run it did get right, expand to clause
    boundaries within that passage, and emit the passage's own characters. Verbatim and
    contiguous by construction. The 60-character anchor floor is what stops an invented
    quote from being "repaired" onto an unrelated real clause.
    """
    target, _ = norm_with_map(evidence)
    if len(target) < MIN_ANCHOR_CHARS:
        return ""
    best: tuple[int, Passage, str, list[int], int, int] | None = None
    for passage in passages:
        text, offsets = norm_with_map(passage.text)
        match = difflib.SequenceMatcher(None, target, text, autojunk=False) \
            .find_longest_match(0, len(target), 0, len(text))
        if match.size >= MIN_ANCHOR_CHARS and (best is None or match.size > best[0]):
            best = (match.size, passage, text, offsets, match.b, match.b + match.size)
    if best is None:
        return ""
    _, passage, text, offsets, start, end = best
    while start > 0 and text[start - 1] not in _CLAUSE_END:
        start -= 1
    while end < len(text) and text[end - 1] not in _CLAUSE_END:
        end += 1
    if end - start > MAX_REPAIRED_CHARS:
        return ""
    return passage.text[offsets[start]:offsets[min(end, len(offsets)) - 1] + 1].strip()


_DISTINCTIVE = re.compile(r"\d+(?:\.\d+)?%?|\b[A-Z][A-Za-z'&-]{3,}(?:\s+[A-Z][A-Za-z'&-]{3,})*")
_SENTENCE_SPLIT = re.compile(r"(?<=[.;:!?])\s+")


def realign_by_claim(answer: str, passages: list[Passage]) -> str:
    """Find the clause that supports an answer, anchored on the answer's own facts.

    `realign` needs a 60-character exact run and so cannot repair a quote the model
    *paraphrased* rather than mistyped. A handbook run produced 19 such answers out of 58:
    the substance was right and present in the document — the figure "14.27" really is
    there — but no long character run matched, so the quote was unverifiable and had to be
    discarded along with a correct finding.

    This anchors on what the answer asserts instead. Distinctive tokens (figures, proper
    nouns) are looked up in the passages, and the sentence containing the rarest one is
    returned as the quote. Verbatim by construction, because it is sliced out of the
    passage. Requires at least one numeric token so that a vague answer cannot pull an
    arbitrary sentence.
    """
    tokens = [t for t in _DISTINCTIVE.findall(answer or "") if len(t) >= 3]
    numeric = [t for t in tokens if any(character.isdigit() for character in t)]
    if not numeric:
        return ""
    best = ""
    for token in numeric + [t for t in tokens if t not in numeric]:
        needle = norm(token)
        for passage in passages:
            for sentence in _SENTENCE_SPLIT.split(passage.text):
                if needle in norm(sentence) and 40 <= len(sentence.strip()) <= 700:
                    candidate = sentence.strip()
                    if not best or len(candidate) < len(best):
                        best = candidate
        if best:
            return best
    return best


@dataclass(frozen=True)
class SentenceMenu:
    """Numbered sentences from the retrieved passages, for selection instead of copying.

    Transcription is the one thing the model is measurably bad at: it identifies the right
    clause and then drops a word or paraphrases it, which on a handbook made 19 of 58
    quotes unverifiable. Repair tiers (character realignment, claim anchoring, re-asking)
    each recover a fraction and none is reliable.

    Selecting sentence numbers removes the failure mode rather than mitigating it. The
    model never emits document text, so the quote cannot be wrong: the host slices it out
    of the passage. Verbatim and contiguous by construction, on any document.
    """
    sentences: dict[int, tuple[int, int, int]]      # sid -> (passage_id, start, end)
    passages: dict[int, Passage]

    def render(self) -> str:
        lines: list[str] = []
        current = None
        for sid, (pid, start, end) in self.sentences.items():
            if pid != current:
                current = pid
                lines.append(f"--- passage {pid}: {self.passages[pid].heading}")
            lines.append(f"[{sid}] {self.passages[pid].text[start:end].strip()}")
        return "\n".join(lines)

    def span(self, sids: list[int]) -> str:
        """Verbatim text spanning consecutive selected sentences within one passage."""
        chosen = [sid for sid in sids if sid in self.sentences]
        if not chosen:
            return ""
        chosen.sort()
        pid = self.sentences[chosen[0]][0]
        # Consecutive and same-passage only, so the result is one unbroken span.
        run = [chosen[0]]
        for sid in chosen[1:]:
            if sid == run[-1] + 1 and self.sentences[sid][0] == pid:
                run.append(sid)
            else:
                break
        start = self.sentences[run[0]][1]
        end = self.sentences[run[-1]][2]
        return self.passages[pid].text[start:end].strip()


def sentence_menu(passages: list[Passage], max_sentences: int = 120) -> SentenceMenu:
    """Split passages into numbered sentences, recording each one's character span."""
    sentences: dict[int, tuple[int, int, int]] = {}
    index = 1
    for passage in passages:
        position = 0
        for piece in re.split(r"(?<=[.;:!?])\s+", passage.text):
            if not piece.strip():
                position += len(piece) + 1
                continue
            start = passage.text.find(piece, position)
            if start < 0:
                start = position
            end = start + len(piece)
            position = end
            if len(piece.strip()) >= 25:
                sentences[index] = (passage.passage_id, start, end)
                index += 1
                if index > max_sentences:
                    break
        if index > max_sentences:
            break
    return SentenceMenu(sentences, {p.passage_id: p for p in passages})


def passage_payload(passages: list[Passage]) -> list[dict]:
    """Passages as the model sees them: labelled, with no page numbers exposed.

    Pages are withheld deliberately. The model has no way to distinguish a printed
    footer from a PDF page, and any number it copies out of the body text is likely
    to be the footer. The host attaches the page afterwards.
    """
    return [{"passage_id": passage.passage_id,
             "heading": passage.heading,
             "text": passage.text} for passage in passages]


def document_pages(doc: DocumentContext = MANCHESTER) -> list[str]:
    """Form-feed delimited pages; index N-1 is PDF page N. Cached per document."""
    return doc.pages()


def locate_in_document(evidence: str, pages: list[str] | None = None,
                       doc: DocumentContext = MANCHESTER) -> Grounding:
    """Find a quote anywhere in the document and derive its true PDF page.

    Used by the full-document sweep, which reads raw page text rather than indexed
    passages and so has no passage_id to attach.
    """
    pages = pages if pages is not None else doc.pages()
    quote = norm(evidence)
    if len(quote) < 15:
        return Grounding(None, "not_applicable", False, False, "evidence too short to verify")
    stitched = bool(_ELLIPSIS.search(evidence or ""))
    if stitched:
        fragments = [norm(f) for f in _ELLIPSIS.split(evidence) if len(norm(f)) >= 15]
        for index, block in enumerate(pages, start=1):
            if fragments and all(f in norm(block) for f in fragments):
                return Grounding(None, str(index), True, False,
                                 "evidence is stitched from non-contiguous fragments")
        return Grounding(None, "not_applicable", False, False,
                         "evidence is stitched and not found on one page")
    for index, block in enumerate(pages, start=1):
        if quote in norm(block):
            return Grounding(None, str(index), True, True, "")
    return Grounding(None, "not_applicable", False, False,
                     "evidence is not a verbatim span of the document")


__all__ = ["DOCUMENT_ID", "MANCHESTER", "BUDGET", "DocumentContext", "corpus",
           "load_document", "Grounding", "exact_page", "fused_passages", "ground",
           "realign", "realign_by_claim", "norm_with_map", "dense_ids",
           "SentenceMenu", "sentence_menu",
           "norm", "page_label", "passage_payload", "open_database",
           "document_pages", "locate_in_document"]
