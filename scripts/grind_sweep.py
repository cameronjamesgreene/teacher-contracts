#!/usr/bin/env python3
"""Full-document, question-batched sweep: read every page, ask what it answers.

Retrieval-first extraction is O(questions) model calls and can only code what the
retriever surfaced. Its documented failure on this contract is appendix blindness:
lexical search never reaches the Appendix B line that carries the Title I stipend at
any depth, because the appendix shares almost no vocabulary with the question. The
sweep inverts the loop. It slides overlapping windows across the WHOLE document and
asks, per window, *which of the codebook questions does this text answer*. Every page
including every appendix is read by construction, and the cost is O(windows) instead
of O(questions).

Four things are host-owned rather than prompt-owned, because a prompt cannot be
trusted with any of them:

1. **Pages.** The model is never shown a page number and never asked for one. Every
   page is derived by locating the evidence in the document text (`locate_in_document`,
   plus a cross-page resolver for clauses that straddle a form feed). The printed
   footer in this contract runs behind the PDF page by one in the body and by up to
   seven in the appendices, so any number a model copies out of the text is wrong.
2. **Evidence.** A quote must appear as ONE unbroken whitespace-equivalent span of the
   document. A near-miss quote is repaired rather than believed - trimmed back at the
   edges, or replaced by the real document span running between its first and last
   grounded words - and a grounded span is widened to its clause so the governing verb
   travels with it. Whatever survives is re-verified before it is written out.
3. **Question ids.** Anything not in the codebook is dropped silently. A prior
   full-document attempt failed by returning more answers than questions asked.
4. **Merging.** Provisions in this corpus routinely vary by employee group, school
   level, plan, or contract year, so the same question is answered differently in
   several windows and often several times within one window. Every distinct variant is
   joined into one answer and all contributing pages recorded; incomplete
   single-variant values were a known failure mode.

The sweep then re-reads the whole document with only the questions nothing answered
yet, and keeps doing so until a lap adds nothing. Recall is where this design wins or
loses - a question missed by every window is silently coded `not_discussed` - and a
leftovers-only list is short enough to carry the codebook's keyword hints too.

Output is `output/grind/sweep.jsonl`: one checkpoint line per window as it finishes,
then one merged line carrying all 106 questions. The merged line is last because the
scorer lets later lines win, and each window line is a resumable checkpoint.

Usage:
    .venv/bin/python scripts/grind_sweep.py                    # full sweep
    .venv/bin/python scripts/grind_sweep.py --max-windows 2 --question-limit 20
    .venv/bin/python scripts/grind_sweep.py --resume           # keep finished windows
    .venv/bin/python scripts/grind_sweep.py --dry-run          # geometry and budgets
"""

from __future__ import annotations

import argparse
import bisect
import json
import re
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from grind_retrieve import (DOCUMENT_ID, MANCHESTER, DocumentContext, load_document,
                            document_pages, locate_in_document)
from som_client import MODEL, budgeted_max_tokens, create_with_retries, get_client
from utils import WORK, read_codebook

OUT_PATH = WORK / "output" / "extraction" / "results" / "sweep.jsonl"

# One process sweeps one document; set from --document-id before windowing.
DOC: DocumentContext = MANCHESTER

# ── window geometry ───────────────────────────────────────────────────────────────
# Sized against the 32k window that prompt and output share. A window of ~20k chars
# of contract text plus the 106-question list (~22k chars with its extraction hints)
# plus the instructions leaves ~15k output tokens, which a reasoning model needs to
# think through 106 questions and still finish its JSON. Overlapping by two pages
# means no clause is only ever seen cut in half at a boundary.
WINDOW_CHARS = 20_000
OVERLAP_PAGES = 2
MAX_EVIDENCE_CHARS = 400     # clause expansion stops here; long enough for a full clause
MIN_EVIDENCE_CHARS = 25      # below this a "quote" cannot identify a clause
MIN_TRIM_KEPT = 0.6          # a trimmed quote must still be most of what was returned
MAX_ANSWER_CHARS = 1500      # merged answers stay readable for a human reviewer

_WS = re.compile(r"\s+")
_RUN_OF_SPACES = re.compile(r"[ \t]{4,}")
_ELLIPSIS = re.compile(r"\.\.\.|…|\[\.\.\.\]")
# Length-preserving character folding: unicode punctuation the extractor and the
# model disagree about. Every entry is 1 char -> 1 char so offsets stay valid.
_FOLD = str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"',
                       "–": "-", "—": "-", "′": "'", " ": " "})
_ABSENT = {"", "not_discussed", "not discussed", "none", "n/a", "na", "null",
           "not applicable", "not_applicable", "not found", "not stated"}


# ── document text: whitespace-collapsed view with a map back to raw offsets ───────

@dataclass
class DocumentIndex:
    """The document in three parallel forms, so a quote can be matched loosely and
    then extracted verbatim.

    `flat` is the raw text with every whitespace run collapsed to one space; `fold`
    is `flat` lowercased with unicode punctuation folded, used only for searching;
    `raw_offset[i]` is the offset in `raw` of `flat[i]`. Matching happens in `fold`
    (so the model's straight apostrophe finds the document's curly one) but the
    evidence handed back is sliced out of `raw`, which is what keeps it a literal
    substring of the document for every downstream verifier.
    """
    raw: str
    flat: str
    fold: str
    raw_offset: list[int]
    page_raw_bounds: list[tuple[int, int]]      # (start, end) in raw, per PDF page
    page_flat_bounds: list[tuple[int, int]]     # (start, end) in flat, per PDF page
    pages: list[str]


def build_index(pages: list[str]) -> DocumentIndex:
    raw = "\n".join(pages)
    flat_chars: list[str] = []
    raw_offset: list[int] = []
    in_space = False
    for position, char in enumerate(raw):
        if char.isspace():
            if not in_space:
                flat_chars.append(" ")
                raw_offset.append(position)
                in_space = True
            continue
        in_space = False
        flat_chars.append(char)
        raw_offset.append(position)
    flat = "".join(flat_chars)
    fold = flat.translate(_FOLD).lower()
    if len(fold) != len(flat):                     # pragma: no cover - defensive
        raise RuntimeError("character folding changed length; offsets invalid")

    page_raw_bounds: list[tuple[int, int]] = []
    cursor = 0
    for page in pages:
        page_raw_bounds.append((cursor, cursor + len(page)))
        cursor += len(page) + 1                    # +1 for the joining newline
    # Translate the raw page bounds into flat space by bisecting raw_offset.
    page_flat_bounds = [(bisect.bisect_left(raw_offset, start),
                         bisect.bisect_left(raw_offset, end))
                        for start, end in page_raw_bounds]
    return DocumentIndex(raw, flat, fold, raw_offset, page_raw_bounds,
                         page_flat_bounds, pages)


def _pages_for_flat_span(index: DocumentIndex, start: int, end: int) -> list[int]:
    """PDF page numbers (1-based) a flat-space span touches."""
    return [number for number, (low, high) in enumerate(index.page_flat_bounds, start=1)
            if start < high and end > low]


def _clause_bounds(index: DocumentIndex, start: int, end: int,
                   limit_low: int, limit_high: int) -> tuple[int, int]:
    """Widen a grounded span to its clause, staying inside one page.

    The codebook wants the clause containing the governing verb; a model asked for a
    quote often hands back only the fragment carrying the number. Widening is safe
    because it stays contiguous by construction, and it is generic: it uses sentence
    punctuation, not knowledge of any particular question.
    """
    room = MAX_EVIDENCE_CHARS - (end - start)
    if room <= 0:
        return start, end
    left_room = min(room // 2, start - limit_low)
    right_room = min(room - left_room, limit_high - end)
    new_start, new_end = start, end
    # Only ever complete the sentence the quote sits in. If no sentence boundary is
    # within reach on a side, that side is left alone rather than padded out, so the
    # span never grows into neighbouring provisions.
    for match in re.finditer(r"[.;:!?]\s+|•\s*", index.flat[start - left_room:start]):
        new_start = start - left_room + match.end()      # last boundary before the quote
    if index.flat[end - 1] not in ".;:!?":               # already ends a sentence
        ahead = index.flat[end:end + right_room]
        for match in re.finditer(r"[.;!?](?=\s|$)", ahead):
            # An outline enumerator ("... hereof. A. All teachers ...") is a period too;
            # stopping after it would append the next section's label to the quote.
            if re.search(r"(^|\s)\w\.$", ahead[:match.end()]):
                continue
            new_end = end + match.end()
            break
    while new_start < new_end and index.flat[new_start] == " ":
        new_start += 1
    while new_end > new_start and index.flat[new_end - 1] == " ":
        new_end -= 1
    return new_start, new_end


def _raw_slice(index: DocumentIndex, start: int, end: int) -> str:
    """The verbatim document text underlying a flat-space span."""
    raw_start = index.raw_offset[start]
    raw_end = index.raw_offset[end - 1] + 1
    return index.raw[raw_start:raw_end].strip()


@dataclass
class Anchor:
    """A model quote resolved against the document by the host."""
    evidence: str
    pages: list[int]
    mode: str            # exact | cross_page | trimmed
    note: str

    @property
    def page(self) -> str:
        return "; ".join(str(number) for number in self.pages)


def _find(index: DocumentIndex, quote: str) -> tuple[int, int] | None:
    needle = _WS.sub(" ", quote.translate(_FOLD).lower()).strip()
    if len(needle) < MIN_EVIDENCE_CHARS:
        return None
    position = index.fold.find(needle)
    if position < 0:
        return None
    return position, position + len(needle)


def _all_occurrences(index: DocumentIndex, flat_span: tuple[int, int],
                     limit: int = 3) -> list[int]:
    """Every page carrying this exact text.

    Appendix tables in this contract are reprinted verbatim for a second contract year,
    so a quote can be a true citation for more than one page and there is no way to tell
    from the text which printing a coder meant. Text repeated more than `limit` times is
    boilerplate (running headers), so only the first occurrence is credited then.
    """
    needle = index.fold[flat_span[0]:flat_span[1]]
    found: list[int] = []
    position = index.fold.find(needle)
    while position >= 0 and len(found) <= limit:
        found.extend(_pages_for_flat_span(index, position, position + len(needle)))
        position = index.fold.find(needle, position + 1)
    unique = sorted(dict.fromkeys(found))
    return unique if len(unique) <= limit else unique[:1]


def _trim_to_longest_grounded(index: DocumentIndex, quote: str) -> tuple[int, int] | None:
    """Recover the longest contiguous run of the model's words that IS in the document.

    A quote fails to ground for two reasons: the model drifted into paraphrase, or it
    ran a label/heading onto the front or a summarising tail onto the back. Trimming
    word by word from each end rescues the second case without inventing anything.
    The MIN_TRIM_KEPT floor is what stops it rescuing the first case: a paraphrase
    usually still opens with real contract words ("Teachers shall be given a ..."), so
    without the floor a trimmed fragment would ground on an unrelated clause and drag a
    wrong page along with it. A quote that cannot keep most of itself is dropped.
    """
    flat_quote = _WS.sub(" ", quote).strip()
    words = flat_quote.split(" ")
    if len(words) < 5:
        return None
    floor = max(MIN_EVIDENCE_CHARS * 2, int(len(flat_quote) * MIN_TRIM_KEPT))
    best: tuple[int, int] | None = None
    best_length = floor
    for start in range(0, min(len(words) - 4, 12)):
        for end in range(len(words), start + 4, -1):
            candidate = " ".join(words[start:end])
            if len(candidate) <= best_length:
                break                       # shorter than what we already have
            span = _find(index, candidate)
            if span:
                best, best_length = span, len(candidate)
                break
    return best


def _longest_grounded_edge(index: DocumentIndex, words: list[str],
                           from_start: bool) -> tuple[int, int] | None:
    """The longest grounded prefix (or suffix) of a word list, at least 40 chars."""
    best: tuple[int, int] | None = None
    for count in range(len(words), 3, -1):
        piece = " ".join(words[:count] if from_start else words[-count:])
        if len(piece) < 40:
            break
        span = _find(index, piece)
        if span:
            best = span
            break
    return best


def _bridge_fragments(index: DocumentIndex, quote: str) -> tuple[int, int] | None:
    """Rescue a quote whose MIDDLE is wrong by spanning from its start to its end.

    Trimming only fixes bad edges. The other common defect is an internal omission -
    the model silently drops a parenthetical or an ellipsis stands in for a phrase - and
    no amount of edge trimming grounds that. If the quote's opening and closing both
    ground on the same page in the right order, the document text BETWEEN them is what
    the model meant to quote, so the host returns that full contiguous span. Note what
    this is not: it never reports the model's stitched string, only a real unbroken span
    of the page, and the length cap stops it bridging two unrelated provisions.
    """
    words = _WS.sub(" ", _ELLIPSIS.sub(" ", quote)).strip().split(" ")
    if len(words) < 10:
        return None
    head = _longest_grounded_edge(index, words, from_start=True)
    tail = _longest_grounded_edge(index, words, from_start=False)
    if not head or not tail or tail[0] <= head[0] or tail[1] <= head[1]:
        return None
    if tail[1] - head[0] > 2 * MAX_EVIDENCE_CHARS:
        return None
    if _pages_for_flat_span(index, head[0], head[1]) != \
            _pages_for_flat_span(index, tail[0], tail[1]):
        return None
    return head[0], tail[1]


def resolve(index: DocumentIndex, quote: str) -> Anchor | None:
    """Ground a quote and derive its page. Returns None when it does not ground.

    `locate_in_document` has the final word on both the page and the quote: whatever the
    flat index proposes is only accepted once that helper confirms it is a verbatim,
    contiguous span of one page. The flat index adds the two things the helper cannot
    do on its own - salvage a clause that straddles a form feed (which lies on no single
    page and so grounds nowhere), and widen a fragment out to its clause.
    """
    quote = (quote or "").strip()
    stitched = bool(_ELLIPSIS.search(quote))
    span = None if stitched else _find(index, quote)
    mode, note = "exact", ""
    if span is None:
        span = None if stitched else _trim_to_longest_grounded(index, quote)
        if span is not None:
            mode, note = "trimmed", "quote trimmed to the longest span found in the document"
        else:
            span = _bridge_fragments(index, quote)
            if span is None:
                return None
            mode = "bridged"
            note = ("quote did not appear as written; evidence replaced by the contiguous "
                    "document span running from its first grounded words to its last")
    touched = _pages_for_flat_span(index, *span)
    if not touched:
        return None
    # A quote that straddles a page break is on no single page, so it cannot be
    # verified or scored as one. Keep the side of the break that holds most of it as
    # the evidence, and record both pages, since the clause really does span them.
    home = max(touched, key=lambda number: (
        min(span[1], index.page_flat_bounds[number - 1][1])
        - max(span[0], index.page_flat_bounds[number - 1][0])))
    low, high = index.page_flat_bounds[home - 1]
    clipped = [max(span[0], low), min(span[1], high)]
    for edge, step in ((0, 1), (1, -1)):        # never start or end mid-word
        if clipped[edge] != span[edge]:
            boundary = (index.flat.find(" ", clipped[0], clipped[1]) if step == 1
                        else index.flat.rfind(" ", clipped[0], clipped[1]))
            if boundary > 0:
                clipped[edge] = boundary + (1 if step == 1 else 0)
    clipped = (clipped[0], clipped[1])
    pages = _all_occurrences(index, span)
    if home not in pages:
        pages = [home] + pages
    if len(touched) > 1:
        mode = "cross_page" if mode == "exact" else mode
        note = "; ".join(filter(None, [note, "clause straddles a page break; evidence "
                                             "clipped to the page holding most of it"]))
        # Only credit the neighbouring page when a real piece of the clause is there,
        # not when the quote merely brushed a running header.
        pages = sorted(number for number in touched
                       if number == home or
                       min(span[1], index.page_flat_bounds[number - 1][1])
                       - max(span[0], index.page_flat_bounds[number - 1][0]) >= 20)
    for start, end in (_clause_bounds(index, *clipped, low, high), clipped):
        evidence = _raw_slice(index, start, end)
        if len(_WS.sub(" ", evidence).strip()) < MIN_EVIDENCE_CHARS:
            continue
        check = locate_in_document(evidence, index.pages)
        if check.verbatim and check.contiguous:
            page = int(check.page)
            ordered = [page] + [number for number in pages if number != page]
            return Anchor(evidence, ordered, mode, note)
    return None


# ── windowing ─────────────────────────────────────────────────────────────────────

def compress(page: str) -> str:
    """Squeeze layout padding out of a page. Whitespace-only, so every quote copied
    from the compressed view still grounds against the raw document."""
    lines: list[str] = []
    blanks = 0
    for line in page.split("\n"):
        line = _RUN_OF_SPACES.sub("   ", line.rstrip())
        if not line.strip():
            blanks += 1
            if blanks > 1:
                continue
        else:
            blanks = 0
        lines.append(line)
    return "\n".join(lines).strip("\n")


@dataclass
class Window:
    index: int
    first_page: int
    last_page: int
    text: str


def build_windows(pages: list[str], max_chars: int = WINDOW_CHARS,
                  overlap: int = OVERLAP_PAGES) -> list[Window]:
    compressed = [compress(page) for page in pages]
    total = len(pages)
    windows: list[Window] = []
    start = 1
    while start <= total:
        end = start
        size = len(compressed[start - 1])
        while end < total and size + len(compressed[end]) + 2 <= max_chars:
            size += len(compressed[end]) + 2
            end += 1
        text = "\n\n".join(compressed[start - 1:end])
        windows.append(Window(len(windows), start, end, text))
        if end >= total:
            break
        start = max(start + 1, end - overlap + 1)
    return windows


# ── prompt ────────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are coding one public-school teacher collective bargaining document against a fixed
codebook. You are shown ONE WINDOW of consecutive pages, not the whole document, and the
full question list.

Report ONLY the questions that THIS WINDOW actually answers. Expect a short, sparse list:
most questions are answered somewhere else in the document, and the correct behaviour is to
leave them out. Never pad the list, never guess, and never report a question just because
the window mentions its topic word - the window must contain text that supplies the answer.

EVIDENCE is the part that is checked mechanically:
- Copy ONE CONTIGUOUS span of the window, character for character, including the words that
  govern the provision (shall, must, may, shall not, is entitled to, will be paid).
- No ellipsis, no "...", no joining two separate sentences, no paraphrase, no summarising,
  no square brackets, no added labels, no question ids, no page numbers.
- If you cannot copy an unbroken span that supports your answer, do not report the question.

ANSWER content:
- Put the substance in the answer: dollar amounts, day and hour counts, percentages,
  deadlines, step/lane/degree labels, named leave types, and the conditions that qualify
  someone, using the document's own wording and labels.
- A provision that exists only for a NAMED SUBSET (part-time teachers, job sharers, nurses,
  one school level, a single contract year, one insurance plan, teachers hired before a
  date) is STILL a discussed provision. Report it and name the subset in the answer.
- If the window answers one question in SEVERAL DISTINCT WAYS - a different rate per
  activity, per plan, per school level, per contract year, per employee group, or a separate
  cap, deadline or exception - return one hit per variant, each with its own quote, rather
  than one hit for whichever variant you saw first. An incomplete value is a wrong value.
- Answer "no" ONLY where the window explicitly states the provision does not exist or is not
  provided. Text that describes a provision is never "no".
- Never answer "not_discussed" or "unknown" - simply omit the question instead. Absence is
  determined by the host after all windows are read.
- If the window says the value is set by an outside source (a salary schedule, board policy,
  state law, an appendix, or an MOU), state in the answer that it is referenced externally
  and quote the referring clause.

BARGAINING UNIT: code the teacher / certificated instructional unit. A clause whose subject
is principals, administrators, supervisors, managers, or another excluded classification does
NOT answer a teacher-focused question; skip it rather than reporting it.

Return ONLY a JSON object, no markdown fences:
{"hits": [{"question_id": "<exact id from the list>", "answer": "...",
           "evidence": "<contiguous verbatim span of the window>",
           "confidence": "high|medium|low", "notes": "<optional, one short clause>"}]}
Return {"hits": []} if this window answers none of the listed questions.\
"""


def question_block(questions, keywords: bool = False) -> str:
    """The codebook as the model sees it.

    `keywords` is off for the first read, where the full 106-question list has to fit
    beside 20k chars of contract text, and on for the short leftover list of a second
    read, where the budget is free and the reason a question was missed is usually that
    the document names the provision in words the question never uses.
    """
    lines = []
    for question in questions:
        line = f"- {question.qid} [{question.answer_type}] {question.question}"
        if question.extract:
            line += f" WANTED: {question.extract}"
        if keywords and question.keywords:
            line += f" MAY APPEAR AS: {question.keywords}"
        lines.append(line)
    return "\n".join(lines)


SECOND_READ_NOTE = """\
This is a SECOND READ of the same document. The questions below are only the ones that no
window answered on the first read, so they are the hard leftovers: an answer, if it exists at
all, is likely to be buried in a list, a table, an appendix, a definitions clause, or a
sentence that never uses the question's own vocabulary. Each question below carries a
MAY APPEAR AS list of the wording documents of this kind tend to use - treat it as a hint
about what the provision looks like, not as a term to match: the window can answer a question
without containing any of those words, and containing one of them does not make it an answer.
Most of these questions really are absent from this document, so an empty list is a normal and
correct answer - do not force a hit, and still omit anything this window does not answer.
"""


def build_user_prompt(window: Window, questions, second_read: bool = False) -> str:
    return (
        "---WINDOW TEXT START---\n"
        f"{window.text}\n"
        "---WINDOW TEXT END---\n\n"
        + (SECOND_READ_NOTE + "\n" if second_read else "")
        + f"CODEBOOK QUESTIONS ({len(questions)}):\n"
        f"{question_block(questions, keywords=second_read)}\n\n"
        "Which of the questions above does the window text answer? Return the sparse JSON "
        "list of hits, each with a contiguous verbatim span copied from the window text."
    )


# ── one batch = one (window, question group) call ─────────────────────────────────

@dataclass
class BatchResult:
    batch: int
    window: int
    group: int
    first_page: int
    last_page: int
    answers: list[dict]
    raw_hits: int = 0
    dropped_unknown: int = 0
    dropped_ungrounded: int = 0
    error: str = ""
    seconds: float = 0.0


def run_batch(client, window: Window, questions, group: int, batch: int,
              index: DocumentIndex, valid_ids: set[str],
              second_read: bool = False) -> BatchResult:
    user_prompt = build_user_prompt(window, questions, second_read)
    started = time.time()
    result = BatchResult(batch, window.index, group, window.first_page, window.last_page, [])
    try:
        payload = create_with_retries(
            client,
            model=MODEL,
            max_tokens=budgeted_max_tokens(SYSTEM_PROMPT, user_prompt),
            temperature=0,
            response_format={"type": "json_object"},
            messages=[{"role": "system", "content": SYSTEM_PROMPT},
                      {"role": "user", "content": user_prompt}],
        )
    except Exception as exc:
        result.error = f"{type(exc).__name__}: {exc}"[:300]
        result.seconds = round(time.time() - started, 1)
        return result

    hits = payload.get("hits") if isinstance(payload, dict) else None
    if not isinstance(hits, list):
        hits = payload if isinstance(payload, list) else []
    result.raw_hits = len(hits)
    # A window may answer the same question several times over - a stipend table lists a
    # rate per activity, an insurance article lists a share per plan. Those are variants
    # of one provision, not duplicates, so several hits per question are kept and only an
    # identical repeat of the same quote is discarded.
    seen: set[tuple[str, str]] = set()
    for hit in hits:
        if not isinstance(hit, dict):
            continue
        qid = str(hit.get("question_id", "")).strip()
        if qid not in valid_ids:
            result.dropped_unknown += 1     # a prior attempt invented ids; drop silently
            continue
        answer = str(hit.get("answer", "") or "").strip()
        if not answer or _WS.sub(" ", answer.lower()).strip(" .") in _ABSENT:
            continue
        anchor = resolve(index, str(hit.get("evidence", "") or ""))
        if anchor is None:
            result.dropped_ungrounded += 1
            continue
        signature = (qid, _WS.sub(" ", anchor.evidence.lower()).strip())
        if signature in seen:
            continue
        seen.add(signature)
        confidence = str(hit.get("confidence", "") or "medium").strip().lower()
        if confidence not in {"high", "medium", "low"}:
            confidence = "medium"
        notes = str(hit.get("notes", "") or "").strip()
        result.answers.append({
            "question_id": qid, "answer": answer, "evidence": anchor.evidence,
            "page": anchor.page, "confidence": confidence, "coder_notes": notes,
            "_grounding": anchor.mode, "_grounding_note": anchor.note,
            "_pages": anchor.pages, "_window": window.index,
            "_window_pages": f"{window.first_page}-{window.last_page}",
        })
    result.seconds = round(time.time() - started, 1)
    return result


# ── merge ─────────────────────────────────────────────────────────────────────────

_GROUNDING_RANK = {"exact": 0, "cross_page": 1, "trimmed": 2, "bridged": 3}


def _answer_key(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _same_answer(first: str, second: str, threshold: float = 0.75) -> bool:
    """Do two window answers say the same thing?

    Overlapping windows see the same clause twice, and the model rarely words it
    identically ("Yes, covers extracurricular activities..." vs "Yes, covers
    extracurriculars, detention..."). Substring containment alone misses those and the
    merged answer reads as a stutter, so near-duplicates are folded on word overlap.
    The threshold is deliberately high: genuinely different variants (a different
    employee group, a different plan year) share far less vocabulary than this.
    """
    left, right = set(first.split()), set(second.split())
    if not left or not right:
        return False
    if first in right or second in left or first in second or second in first:
        return True
    return len(left & right) / min(len(left), len(right)) >= threshold


def _join_variants(texts: list[str]) -> str:
    """Distinct answers, readably joined, with duplicates folded away.

    Windows overlap and provisions vary by employee group, school level, plan, or
    contract year, so the same question is genuinely answered several different ways.
    Dropping all but one variant is how single-pass coding loses the second half of a
    provision, so every distinct variant is kept; the longer wording wins whenever two
    of them are really the same statement.
    """
    kept: list[str] = []
    for text in texts:
        key = _answer_key(text)
        if not key:
            continue
        for position, existing in enumerate(kept):
            if _same_answer(key, _answer_key(existing)):
                if len(key) > len(_answer_key(existing)):
                    kept[position] = text            # new wording says more
                break
        else:
            kept.append(text)
    joined = "; ".join(part.strip().rstrip(" .;") for part in kept)
    if len(joined) <= MAX_ANSWER_CHARS:
        return joined
    # Runaway joins are a sign of a very fragmented provision, e.g. a stipend table. Keep
    # as many whole variants as fit rather than truncating one mid-figure.
    trimmed: list[str] = []
    for part in (part.strip().rstrip(" .;") for part in kept):
        if sum(len(item) + 2 for item in trimmed) + len(part) > MAX_ANSWER_CHARS:
            break
        trimmed.append(part)
    return "; ".join(trimmed) + f" [+{len(kept) - len(trimmed)} further variant(s)]"


def merge(batches: list[dict], questions) -> tuple[list[dict], dict]:
    by_question: dict[str, list[dict]] = {}
    for batch in batches:
        for answer in batch.get("answers", []):
            answer.setdefault("_window", int(batch.get("window", 0)))
            answer.setdefault("_grounding", "exact")
            answer.setdefault("_grounding_note", "")
            answer.setdefault("_pages", [int(value) for value
                                        in re.findall(r"\d+", answer.get("page", ""))] or [0])
            by_question.setdefault(answer["question_id"], []).append(answer)

    merged: list[dict] = []
    stats = {"answered": 0, "not_discussed": 0, "multi_window": 0}
    for question in questions:
        hits = by_question.get(question.qid, [])
        if not hits:
            merged.append({
                "question_id": question.qid, "answer": "not_discussed", "evidence": "",
                "page": "not_applicable", "confidence": "medium",
                "coder_notes": "no window of the document answered this question",
            })
            stats["not_discussed"] += 1
            continue
        hits = sorted(hits, key=lambda hit: (hit["_pages"][0], hit["_window"]))
        windows = sorted({hit["_window"] for hit in hits})
        answer = _join_variants([hit["answer"] for hit in hits])
        # Best-grounded evidence: prefer an exact single-page match, then the longest
        # span, which is the one most likely to carry the governing verb.
        best = sorted(hits, key=lambda hit: (_GROUNDING_RANK.get(hit["_grounding"], 3),
                                             -len(hit["evidence"])))[0]
        # The quoted clause's own page leads; the rest are the other places this
        # provision is stated, which a reviewer checking a merged answer needs.
        pages = best["_pages"][:1] + sorted({page for hit in hits for page in hit["_pages"]}
                                            - set(best["_pages"][:1]))
        confidences = {hit["confidence"] for hit in hits}
        if len(windows) > 1:
            stats["multi_window"] += 1
            confidence = "high" if "high" in confidences else "medium"
        else:
            confidence = best["confidence"]
        notes = [note for note in (hit.get("coder_notes", "") for hit in hits) if note]
        detail = [f"{len(hits)} window hit(s) on page(s) {', '.join(str(p) for p in pages)}"]
        if len(hits) > 1:
            detail.append("variations joined across windows")
        if best["_grounding"] != "exact":
            detail.append(best["_grounding_note"])
        detail.extend(dict.fromkeys(notes))
        merged.append({
            "question_id": question.qid, "answer": answer,
            "evidence": best["evidence"],
            "page": "; ".join(str(page) for page in pages),
            "confidence": confidence, "coder_notes": "; ".join(detail)[:600],
        })
        stats["answered"] += 1
    return merged, stats


# ── checkpointing ─────────────────────────────────────────────────────────────────

def load_checkpoints(path: Path) -> dict[int, dict]:
    if not path.exists():
        return {}
    done: dict[int, dict] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if record.get("kind") == "window" and not record.get("error"):
            done[int(record["batch"])] = record
    return done


def write_output(path: Path, windows: dict[int, dict], merged: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(windows[key], ensure_ascii=False) for key in sorted(windows)]
    # The merged line goes last on purpose: the scorer reads every line and lets later
    # lines win, so the merged record is the one that is graded.
    lines.append(json.dumps({"document_id": DOC.document_id, "batch": 9999, "kind": "merged",
                             "answers": public(merged)}, ensure_ascii=False))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def public(answers: list[dict]) -> list[dict]:
    """Strip host-internal bookkeeping fields (`_window`, `_grounding`, ...).

    Applied to the merged line only. The per-window checkpoint lines keep the
    bookkeeping, because `--resume` re-merges from them and the merge needs to know
    which window and which grounding mode each hit came from.
    """
    return [{key: value for key, value in answer.items() if not key.startswith("_")}
            for answer in answers]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--document-id", default=MANCHESTER.document_id)
    parser.add_argument("--out", type=Path, default=OUT_PATH)
    parser.add_argument("--window-chars", type=int, default=WINDOW_CHARS)
    parser.add_argument("--overlap-pages", type=int, default=OVERLAP_PAGES)
    parser.add_argument("--question-groups", type=int, default=1,
                        help="split the codebook into N groups per window (more calls, "
                             "shorter question list per call)")
    parser.add_argument("--passes", type=int, default=3,
                        help="re-read every window with only the questions still "
                             "unanswered (a question missed once is missed for good)")
    parser.add_argument("--question-limit", type=int, help="smoke test: first N questions")
    parser.add_argument("--max-windows", type=int, help="smoke test: first N windows")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--dry-run", action="store_true",
                        help="report window geometry and token budgets, make no calls")
    args = parser.parse_args()
    global DOC
    DOC = (MANCHESTER if args.document_id == MANCHESTER.document_id
           else load_document(args.document_id))

    questions = read_codebook()
    if args.question_limit:
        questions = questions[:args.question_limit]
    pages = DOC.pages()
    index = build_index(pages)
    windows = build_windows(pages, args.window_chars, args.overlap_pages)
    if args.max_windows:
        windows = windows[:args.max_windows]

    print(f"{len(windows)} windows x {max(1, args.question_groups)} question group(s); "
          f"{len(questions)} questions; pages 1-{len(pages)}; {args.passes} pass(es)")
    for window in windows:
        sample = build_user_prompt(window, questions[:-(-len(questions) //
                                                        max(1, args.question_groups))])
        print(f"  window {window.index}: pages {window.first_page}-{window.last_page} "
              f"{len(window.text):>6} chars  max_tokens="
              f"{budgeted_max_tokens(SYSTEM_PROMPT, sample)}")
    if args.dry_run:
        return

    done = load_checkpoints(args.out) if args.resume else {}
    if done:
        print(f"resuming: {len(done)} batches already complete")

    client = get_client()
    lock = threading.Lock()
    results: dict[int, dict] = dict(done)
    tally = {"raw": 0, "unknown": 0, "ungrounded": 0, "kept": 0, "errors": 0, "calls": 0}
    started = time.time()

    def work(job) -> None:
        window, group_index, group, batch, valid_ids, second_read = job
        if batch in done:
            return
        result = run_batch(client, window, group, group_index, batch, index, valid_ids,
                           second_read)
        record = {
            "document_id": DOC.document_id, "batch": batch, "kind": "window",
            "window": result.window, "question_group": group_index,
            "pages": f"{result.first_page}-{result.last_page}",
            "dropped_ungrounded": result.dropped_ungrounded,
            "dropped_unknown_id": result.dropped_unknown,
            "answers": result.answers,
        }
        if result.error:
            record["error"] = result.error
        with lock:
            if not result.error:
                results[batch] = record
            tally["calls"] += 1
            tally["raw"] += result.raw_hits
            tally["unknown"] += result.dropped_unknown
            tally["ungrounded"] += result.dropped_ungrounded
            tally["kept"] += len(result.answers)
            tally["errors"] += int(bool(result.error))
            # Rewrite the whole file after every window: cheap at this size, and it
            # keeps the merged line last and consistent with the checkpoints above it.
            merged, _ = merge(list(results.values()), questions)
            write_output(args.out, results, merged)
            flag = f" ERROR {result.error}" if result.error else ""
            print(f"  batch {batch:>3} pages "
                  f"{result.first_page}-{result.last_page} group {group_index}: "
                  f"{result.raw_hits:>3} hits -> {len(result.answers):>3} kept "
                  f"({result.dropped_ungrounded} ungrounded, {result.dropped_unknown} "
                  f"unknown id) {result.seconds:>6.1f}s{flag}", flush=True)

    from concurrent.futures import ThreadPoolExecutor
    stats: dict = {}
    previous_pending = -1
    pass_calls = 1
    for pass_index in range(max(1, args.passes)):
        merged, stats = merge(list(results.values()), questions)
        answered = {answer["question_id"] for answer in merged
                    if answer["answer"] != "not_discussed"}
        pending = [question for question in questions if question.qid not in answered]
        # Stop once a re-read stops finding anything: the remaining questions are absent
        # from the document and another lap only spends calls. A pass that made no calls
        # at all (everything was resumed from the checkpoint file) proves nothing, so it
        # must not be read as convergence.
        if pass_index and (not pending or (len(pending) == previous_pending and pass_calls)):
            print(f"\nconverged after pass {pass_index - 1}: "
                  f"{len(pending)} question(s) unanswered anywhere")
            break
        previous_pending = len(pending)
        if pass_index == 0:
            pending = questions
        # Pass 0 splits the codebook so no single call carries too long a list; later
        # passes already have a short list, so they go in one group.
        count = max(1, args.question_groups) if pass_index == 0 else 1
        size = -(-len(pending) // count)
        question_groups = [group for group in
                           (pending[i * size:(i + 1) * size] for i in range(count)) if group]
        valid_ids = {question.qid for question in pending}
        jobs = [(window, group_index, group,
                 1000 * pass_index + window.index * len(question_groups) + group_index,
                 valid_ids, pass_index > 0)
                for window in windows
                for group_index, group in enumerate(question_groups)]
        print(f"\npass {pass_index}: {len(pending)} question(s) in "
              f"{len(question_groups)} group(s) x {len(windows)} windows "
              f"= {len(jobs)} calls", flush=True)
        before = tally["calls"]
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            list(pool.map(work, jobs))
        pass_calls = tally["calls"] - before

    merged, stats = merge(list(results.values()), questions)
    write_output(args.out, results, merged)
    elapsed = time.time() - started
    print(f"\ncalls={tally['calls']}, {len(done)} resumed, "
          f"errors={tally['errors']}  wall={elapsed / 60:.1f} min")
    print(f"hits: {tally['raw']} returned, {tally['kept']} kept, "
          f"{tally['ungrounded']} failed grounding, {tally['unknown']} unknown ids")
    print(f"merged: {stats['answered']} answered "
          f"({stats['multi_window']} from >1 window), "
          f"{stats['not_discussed']} not_discussed -> {args.out}")


if __name__ == "__main__":
    main()
