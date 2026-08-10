#!/usr/bin/env python3
"""Per-question extraction with a mandatory absence-verification second pass.

The dominant error in this pipeline is a confident `not_discussed` for a provision
that is present, usually in an appendix or attached to a special employee group
(job sharers, part-time staff, per-diem specialists). Human reviewers avoided that
error by refusing to accept an absence until they had tried several different
wordings. This variant makes that refusal a stage of the program rather than an
instruction in a prompt:

1. **Evidence before answer.** Every call is asked to copy the contiguous verbatim
   clause that governs the provision *first*, and only then to state the answer
   derived from those words. One question per call, so nothing is answered in the
   shadow of a neighbouring question.
2. **No absence is accepted on the first pass.** Any absence (`not_discussed`,
   `no`, `discussed_unclear`, or an empty answer) triggers a second search. The
   model is asked for the words the contract itself would use -- headings,
   operative phrasing, special-employee-group vocabulary, appendix/schedule
   vocabulary -- rather than for a rewrite of the question, because generic
   rewrites are what failed before. Deterministic expansions are added, retrieval
   runs again (dense-weighted, since dense is what reaches appendix material), and
   the model must either produce a grounded substantive answer or explicitly
   confirm the absence.
3. **The host owns the page.** No page the model reports is ever used; the page is
   derived from `grind_retrieve.ground()`, i.e. from whichever passage actually
   contains the quote. The printed page number in this contract runs one behind the
   PDF page in the body and up to seven behind in the appendices, which is why the
   baseline scored 0.105 on pages.
4. **Stitched evidence is rejected.** `contiguous=False` costs the model one
   re-ask for a single unbroken clause. A quote that is merely mistranscribed is
   realigned by the host instead: the longest exact run the model got right locates
   the clause, and the host then emits the passage's own characters, so the recorded
   quote is verbatim and contiguous by construction rather than by promise.
5. **`no` is audited.** `no` means the document explicitly denies or prohibits the
   provision. A clause that merely describes or conditions the provision is a
   substantive answer, so a `no` whose quote carries no denial language is sent
   back once for correction.
6. **A grounded answer gets one completeness sweep.** A provision is usually split
   across clauses -- a rate here, a cap there, elementary in one sentence and
   secondary in the next -- and a half-answer is a wrong answer. The sweep may add
   only detail that arrives with verbatim words the host can locate, and it revises
   the answer text only: letting it re-cite moved the page off the governing clause
   (paired on identical extractions, page 0.895 against 0.947).

Checkpointed per question; `--resume` picks up where a run stopped.
"""

from __future__ import annotations

import argparse
import csv
import difflib
import json
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from contract_search import Passage, read_passages
from grind_retrieve import (DEFAULT_DOCUMENT_ID, DocumentContext, load_document,
                            document_pages, fused_passages, ground,
                            open_database, passage_payload)
# Dense retrieval goes through the shared layer, which reads embeddings from the
# same SQLite file as the passages.
from grind_retrieve import dense_ids as _dense_ids
from grind_retrieve import realign_by_claim, sentence_menu
from som_client import MODEL, budgeted_max_tokens, create_with_retries, get_client
from utils import WORK, Question, read_codebook

DB_PATH = WORK / "cache" / "contract_search_structural.sqlite3"
OUT_PATH = WORK / "output" / "extraction" / "results" / "verify.jsonl"
PROGRESS_PATH = WORK / "output" / "extraction" / "results" / "verify_progress.jsonl"
GOLD_PATH = WORK / "output" / "extraction" / "answer_gold.csv"

# One process codes one document. Set from --document-id before any coding begins, so
# retrieval, page derivation and the emitted document_id cannot disagree.
DOC: DocumentContext | None = None
ANSWERS_PER_LINE = 10

PASS1_BUDGET = 10          # measured best-performing depth for the fused retriever
PASS2_BUDGET = 12          # second pass sees more, since it is the last chance
MAX_EXPANSION_QUERIES = 12

# An absence is anything that asserts the provision is not codeable from the
# document. Every one of these must survive verification before it is written out.
ABSENCE_STATUSES = {"not_discussed", "discussed_unclear", "not_applicable", "no", "empty"}

_WS = re.compile(r"\s+")
_SENTENCE = re.compile(r"(?<=[.;:!?])\s+")
# Words a contract uses when it actually denies or forbids something. Used only to
# decide whether a `no` needs auditing, never to write an answer.
_DENIAL = re.compile(
    r"\b(shall\s+not|may\s+not|will\s+not|does\s+not|do\s+not|is\s+not|are\s+not|"
    r"no\s+\w+\s+(?:shall|will|is|are|may)|not\s+be\s+(?:granted|paid|provided|"
    r"allowed|permitted|entitled|eligible)|prohibited|ineligible|not\s+eligible|"
    r"without\s+pay|nothing\s+herein)\b", re.I)

# Vocabulary the second pass adds regardless of what the model proposes. These are
# the two places the reviewers found provisions that the first pass had missed:
# attached schedules, and provisions written for a non-standard employee group.
APPENDIX_TERMS = ("appendix", "addendum", "exhibit", "schedule", "attachment",
                  "memorandum of agreement", "letter of agreement", "side letter")
SUBSET_TERMS = ("job sharing", "shared contract", "part-time", "less than full time",
                "per diem", "itinerant", "specialists", "long-term substitute",
                "hourly", "extended year")


SYSTEM_RULES = """\
You are an expert labor-contract coder building a research dataset from one U.S.
public school district document (a teachers' collective bargaining agreement). You
are shown selected passages of that document, never the whole document.

ORDER OF WORK -- always in this order:
  1. Find the clause that governs the provision the question asks about.
  2. Copy that clause verbatim into "evidence".
  3. Only then write "answer", derived strictly from the words you copied.
Never assert anything you cannot point to in the words you copied.

EVIDENCE RULES
- "evidence" is one contiguous, unbroken span copied character-for-character out of
  ONE passage. Never join two places. Never use "...", "[...]" or any elision.
  Never correct spelling, spacing, capitalisation or numbers.
- Stay inside a single paragraph of a single passage. If the language you want is
  spread over two paragraphs, pick the one paragraph that governs the provision.
- Include the whole clause containing the governing verb (shall, must, will, may,
  shall not, is entitled to) plus the numbers and terms your answer relies on.
- Never report a page number and never quote one; the host assigns pages. Passage
  labels are internal identifiers, not pages.

BARGAINING-UNIT RULE
- Code only the teacher / certificated instructional unit. A clause whose subject
  is principals, administrators, supervisors, managers, or non-certificated staff
  does not answer a teacher question even when the wording looks right.

STATUS RULES
- A substantive answer (a value, or "yes" with the specifics) is required whenever
  the passages state that the provision exists or give the requested value.
- "no" is ONLY for a document that explicitly states the provision does not exist,
  is not provided, or is prohibited. A passage that DESCRIBES the provision is a
  substantive answer, never "no".
- "not_discussed" is ONLY for a topic that is absent from the passages shown.
- Language that protects teachers -- "shall not be involuntarily transferred
  without written notice and a conference" -- means the topic IS addressed. That is
  a substantive "yes", not "no" and not "not_discussed".
- A provision that exists only for a named subset -- job sharers, part-time or
  less-than-full-time teachers, specialists, per-diem or itinerant staff, one
  school level, one contract year, one salary lane, one appendix table -- is STILL
  discussed. Answer substantively and name the subset in the answer.
- Do not infer a specific component (for example student-growth or standardised
  test measures) from a general article that does not name it.

ANSWER-WRITING RULES
- Write the answer so a reader could use it without the contract in hand. The
  answer is the only field a reader sees, so nothing important may live only in
  "coder_notes".
- Even when the answer type is a number, a date or a short value, do not stop at
  the bare value. Put the value first, then, in the same "answer" string, the
  qualifying detail: who it applies to, how it is earned or triggered, any cap,
  minimum, maximum, waiting period or deadline, and any condition.
- State every number, dollar amount, percentage, day or minute count, step, lane,
  deadline, eligibility condition, named group and time limit the passages give,
  and every variation they show (by school level, employee group, contract year,
  or seniority). A missing variation is an incomplete answer.
- "evidence" must be a single clause, but the ANSWER may draw on every passage
  shown. When two passages give two parts of the provision -- elementary and
  secondary, or a rate and a cap -- state both in the answer and quote the one
  clause that governs it most directly.
- Add nothing the passages do not state.

Reply with a single JSON object and nothing else. No prose before or after it."""


@dataclass
class Attempt:
    """One model verdict, after the host has checked it against the passages."""
    answer: str = "not_discussed"
    evidence: str = ""
    page: str = "not_applicable"
    confidence: str = "low"
    coder_notes: str = ""
    grounded: bool = False
    grounding_error: str = ""
    # Citation carried by the primary pass, kept when the completeness sweep re-cites
    # so the two citation policies can be compared on identical extractions.
    alt_evidence: str = ""
    alt_page: str = ""


@dataclass
class Stats:
    calls: int = 0
    pass1_absences: int = 0
    verified_absences: int = 0
    overturned: int = 0
    stitched_reasks: int = 0
    stitch_recovered: int = 0
    realigned: int = 0
    enrich_calls: int = 0
    enriched: int = 0
    no_audits: int = 0
    no_downgrades: int = 0
    page_trims: int = 0
    claim_anchored_recoveries: int = 0
    sentence_selection_recoveries: int = 0
    selection_declined: int = 0
    failures: list[str] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def bump(self, name: str, amount: int = 1) -> None:
        with self.lock:
            setattr(self, name, getattr(self, name) + amount)


# ── host-side verification helpers ────────────────────────────────────────────────

def scorer_norm(text: str) -> str:
    """Whitespace/quote normalisation used for single-page containment checks."""
    return _WS.sub(" ", (text or "").replace("’", "'").replace("“", '"')
                   .replace("”", '"').casefold()).strip()


_CONFIDENCE_ORDER = {"low": 0, "medium": 1, "high": 2}


def cap_confidence(value: str, ceiling: str) -> str:
    """Never let a reported confidence exceed what the host could establish."""
    if _CONFIDENCE_ORDER.get(value, 0) > _CONFIDENCE_ORDER[ceiling]:
        return ceiling
    return value


def classify(answer: str) -> str:
    """Map a free-text answer onto a discussion status."""
    raw = (answer or "").strip()
    if not raw:
        return "empty"
    collapsed = _WS.sub("_", raw.casefold()).strip("._")
    if collapsed.startswith("not_discussed"):
        return "not_discussed"
    if collapsed.startswith("discussed_unclear"):
        return "discussed_unclear"
    if collapsed.startswith("not_applicable"):
        return "not_applicable"
    if collapsed in {"no", "none", "none_specifically_cited", "no_provision"}:
        return "no"
    return "substantive"


def fit_single_page(evidence: str, page_blocks: list[str]) -> str:
    """Shrink a quote to the longest contiguous run of it that sits on ONE page.

    A passage may span a page break, so a legitimately contiguous quote can still
    straddle two pages. Downstream verification is page-scoped, so such a quote
    reads as unverifiable. Trimming at sentence boundaries keeps the quote verbatim
    and contiguous while making it checkable. Returns the original text when the
    quote is already on one page or when no run of it can be located.
    """
    if not evidence:
        return evidence
    target = scorer_norm(evidence)
    if any(target in block for block in page_blocks):
        return evidence
    parts = [part for part in _SENTENCE.split(evidence) if part.strip()]
    best = ""
    for start in range(len(parts)):
        for end in range(len(parts), start, -1):
            candidate = " ".join(parts[start:end]).strip()
            if len(candidate) <= len(best):
                break
            if any(scorer_norm(candidate) in block for block in page_blocks):
                best = candidate
                break
    return best or evidence


_NORM_REPL = {"’": "'", "‘": "'", "“": '"', "”": '"', "–": "-", "—": "-"}
_CLAUSE_END = ".;:!?"
MIN_ANCHOR_CHARS = 60      # exact-match run long enough to identify a clause
MAX_REPAIRED_CHARS = 1400  # a repaired quote is a clause, not a whole passage


def norm_with_map(text: str) -> tuple[str, list[int]]:
    """`grind_retrieve.norm` plus, for each output character, its source index.

    The map is what lets the host emit a slice of the PASSAGE's own text after
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
    """Replace a near-miss quote with the real clause it points at.

    The model reliably identifies the right clause and unreliably transcribes it: it
    drops a word, normalises a stray space ("Blue Cross -Blue Shield"), or elides
    across a paragraph break. Rather than spend a call asking again, find the
    longest exact run the model did get right, expand it to clause boundaries inside
    that passage, and emit the passage's own characters. The result is verbatim and
    contiguous by construction. A 60-character exact anchor is required, so an
    invented quote cannot be "repaired" into a real one.
    """
    target, _ = norm_with_map(evidence)
    if len(target) < MIN_ANCHOR_CHARS:
        return ""
    best: tuple[int, Passage, str, list[int], int, int] | None = None
    for passage in passages:
        text, offsets = norm_with_map(passage.text)
        match = difflib.SequenceMatcher(None, target, text, autojunk=False)\
            .find_longest_match(0, len(target), 0, len(text))
        if match.size >= MIN_ANCHOR_CHARS and (best is None or match.size > best[0]):
            best = (match.size, passage, text, offsets, match.b, match.b + match.size)
    if best is None:
        return ""
    _, passage, text, offsets, start, end = best
    # Grow to clause boundaries so the quote carries its governing verb.
    while start > 0 and text[start - 1] not in _CLAUSE_END:
        start -= 1
    while end < len(text) and text[end - 1] not in _CLAUSE_END:
        end += 1
    if end - start > MAX_REPAIRED_CHARS:
        return ""
    return passage.text[offsets[start]:offsets[min(end, len(offsets)) - 1] + 1].strip()


def verify(raw: dict, passages: list[Passage], page_blocks: list[str],
           stats: Stats) -> Attempt:
    """Turn a model reply into an Attempt whose page and evidence the host owns."""
    answer = str(raw.get("answer") or "").strip()
    evidence = str(raw.get("evidence") or "").strip()
    attempt = Attempt(
        answer=answer,
        evidence=evidence,
        confidence=str(raw.get("confidence") or "low").strip().casefold(),
        coder_notes=str(raw.get("coder_notes") or "").strip(),
    )
    if attempt.confidence not in {"high", "medium", "low"}:
        attempt.confidence = "low"
    if classify(answer) in {"not_discussed", "empty", "not_applicable"}:
        attempt.evidence = ""
        attempt.page = "not_applicable"
        return attempt
    if not evidence:
        attempt.grounding_error = "answer carries no evidence"
        return attempt
    grounding = ground(evidence, passages, doc=DOC)
    attempt.grounding_error = grounding.error
    if not (grounding.verbatim and grounding.contiguous):
        return attempt
    # Page comes from the passage the quote was found in, never from the model.
    attempt.page = grounding.page
    attempt.grounded = True
    trimmed = fit_single_page(evidence, page_blocks)
    if trimmed != evidence:
        stats.bump("page_trims")
        attempt.evidence = trimmed
        attempt.coder_notes = (attempt.coder_notes + " [quote trimmed to the portion "
                               "lying on a single page]").strip()
    return attempt


# ── retrieval ─────────────────────────────────────────────────────────────────────

def primary_query(question: Question) -> str:
    return f"{question.question} {question.keywords}"


def deterministic_queries(question: Question) -> list[str]:
    """Expansions that do not depend on the model behaving well.

    The codebook keywords are already provision-specific wording; the two crosses
    add the places the first pass structurally cannot reach -- attached schedules
    and provisions written for a non-standard employee group.
    """
    keywords = [term.strip() for term in question.keywords.split(",") if term.strip()]
    head = " ".join(keywords[:3]) if keywords else question.question
    queries = keywords[:5]
    queries.append(f"{head} {' '.join(APPENDIX_TERMS[:4])}")
    queries.append(f"{head} {' '.join(SUBSET_TERMS[:5])}")
    return queries


def collect(connection, queries: list[str], exclude: set[int],
            budget: int) -> list[Passage]:
    """Round-robin over queries so no single wording monopolises the budget.

    Dense-only for the expansion queries: they are contract vocabulary aimed at
    appendix and special-group language, which is exactly where lexical retrieval
    was measured to fail (appendix recall 0.375 against dense's 0.750).
    """
    ranked: list[list[Passage]] = []
    for query in queries:
        if not query.strip():
            continue
        dense_ids = _dense_ids(query, DOC, 6)
        lexical = fused_passages(connection, query, budget=4, doc=DOC)
        by_id = {passage.passage_id: passage for passage in lexical}
        merged = [by_id[pid] for pid in dense_ids if pid in by_id]
        missing = [pid for pid in dense_ids if pid not in by_id]
        if missing:
            for passage in read_passages(connection, DOC.document_id, missing):
                by_id[passage.passage_id] = passage
            merged = [by_id[pid] for pid in dense_ids if pid in by_id]
        for passage in lexical:
            if passage.passage_id not in {p.passage_id for p in merged}:
                merged.append(passage)
        ranked.append(merged)
    out: list[Passage] = []
    seen = set(exclude)
    for depth in range(max((len(group) for group in ranked), default=0)):
        for group in ranked:
            if depth < len(group) and group[depth].passage_id not in seen:
                seen.add(group[depth].passage_id)
                out.append(group[depth])
                if len(out) >= budget:
                    return out
    return out


# ── prompts ───────────────────────────────────────────────────────────────────────

def question_block(question: Question) -> str:
    return (f"QUESTION ID: {question.qid}\n"
            f"TOPIC: {question.topic}\n"
            f"QUESTION: {question.question}\n"
            f"ANSWER TYPE: {question.answer_type}\n"
            f"WHAT TO EXTRACT IF DISCUSSED: {question.extract}\n"
            f"CODING NOTE: {question.notes}")


def passage_block(passages: list[Passage]) -> str:
    return json.dumps(passage_payload(passages), ensure_ascii=False, indent=1)


def ask(client, system: str, user: str, stats: Stats) -> dict:
    """One model call, with max_tokens sized from the actual prompt.

    The endpoint shares one 32k window between prompt and output, and this is a
    reasoning model that emits a long chain-of-thought before its JSON, so the
    output allowance has to be computed rather than assumed.
    """
    max_tokens = budgeted_max_tokens(system, user)
    stats.bump("calls")
    return create_with_retries(client, model=MODEL, max_tokens=max_tokens,
                               temperature=0,
                               messages=[{"role": "system", "content": system},
                                         {"role": "user", "content": user}])


def pass1_prompt(question: Question, passages: list[Passage]) -> str:
    return f"""\
{question_block(question)}

PASSAGES FROM THE DOCUMENT:
{passage_block(passages)}

Work in this order: locate the governing clause, copy it, then answer from it.

Return exactly this JSON object, with the keys in this order:
{{"evidence": "<one contiguous verbatim span from one passage, or \\"\\" if the topic is absent>",
 "passage_id": <the passage_id you copied from, or null>,
 "answer": "<the answer derived from that span, or \\"not_discussed\\" if the topic is absent from these passages>",
 "confidence": "high" | "medium" | "low",
 "coder_notes": "<section heading, employee group the provision is limited to, and anything a reviewer needs>"}}"""


def expansion_prompt(question: Question) -> str:
    return f"""\
{question_block(question)}

A first search built from the question's own wording returned passages that did not
contain this provision. Before an absence can be recorded, the document has to be
searched again using the words the CONTRACT would use.

Do NOT paraphrase the question and do NOT write generic rewrites of it -- that has
already been tried and it fails. Write the literal language a teachers' collective
bargaining agreement uses for this provision. Cover all of:
  - the article or section HEADING a contract would put this under
  - the operative contract phrasing for the provision itself
  - older or regional synonyms for it
  - the same provision as written for a non-standard employee group: job sharing,
    shared contract, part-time, less than full time, itinerant, specialists, per
    diem, long-term substitutes, hourly, extended year, summer school
  - the wording it would carry if it lives in attached material rather than the
    body: appendix, addendum, exhibit, schedule, attachment, memorandum of
    agreement, letter of agreement, side letter

Each query is 2 to 8 words, contract vocabulary only, no question words.

Return exactly: {{"queries": ["...", "..."]}}  (8 to 12 queries)"""


def pass2_prompt(question: Question, passages: list[Passage],
                 first_answer: str) -> str:
    return f"""\
{question_block(question)}

STATUS: a first pass over differently-retrieved passages produced an absence
("{first_answer}"). An absence is not accepted here until a second search with
contract vocabulary has been read. Below are passages retrieved with alternate
phrasings, including appendix, schedule and special-employee-group wording, so they
are mostly passages the first pass never saw.

PASSAGES FROM THE DOCUMENT:
{passage_block(passages)}

Read every passage before you decide. Then choose one verdict:
  "found"  -- some passage here does address the topic. Copy the governing clause
              verbatim into "evidence" and write the substantive answer. If the
              provision applies only to one employee group, one school level, one
              contract year, or one appendix table, that still counts as found:
              answer substantively and name the limit.
  "absent" -- no passage here addresses the topic at all.

A clause that limits, conditions or protects the provision addresses the topic. A
provision that appears only inside a table, schedule or appendix addresses the
topic. Only choose "absent" if the subject matter genuinely does not appear.

Return exactly this JSON object, with the keys in this order:
{{"evidence": "<one contiguous verbatim span from one passage, or \\"\\" if absent>",
 "passage_id": <the passage_id you copied from, or null>,
 "verdict": "found" | "absent",
 "answer": "<the substantive answer if found, otherwise \\"not_discussed\\">",
 "confidence": "high" | "medium" | "low",
 "coder_notes": "<if found: heading and any employee-group limit. If absent: which wordings you checked.>"}}"""


def restitch_prompt(question: Question, passages: list[Passage], previous: str,
                    reason: str) -> str:
    return f"""\
{question_block(question)}

PASSAGES FROM THE DOCUMENT:
{passage_block(passages)}

Your previous evidence could not be verified: {reason}
It was:
{previous[:1200]}

Choose ONE paragraph inside ONE passage above and copy a contiguous span of it
character-for-character. No elision, no joining of separated sentences, no edits.
The span must contain the governing verb and the facts the answer relies on. Keep
the same answer if that single span still supports it; change the answer if it does
not, and write "not_discussed" if no single span in these passages supports any
answer.

Return exactly this JSON object, with the keys in this order:
{{"evidence": "<one contiguous verbatim span from one passage>",
 "passage_id": <the passage_id you copied from, or null>,
 "answer": "<the answer that span supports, or \\"not_discussed\\">",
 "confidence": "high" | "medium" | "low",
 "coder_notes": "..."}}"""


def select_prompt(question: Question, menu, answer: str) -> str:
    """Ask which numbered sentences support the answer, instead of asking for a quote."""
    return f"""\
{question_block(question)}

NUMBERED SENTENCES FROM THE DOCUMENT:
{menu.render()}

A previous attempt answered: {answer[:600]}
Its quote could not be verified, because it was retyped or paraphrased rather than copied.

Do NOT write out any document text. Instead choose the sentence numbers that state this
provision. Choose one number, or two or three CONSECUTIVE numbers if the provision spans
them. The host will copy the text for you, so it cannot come out wrong.

If no sentence above states the provision, return an empty list and answer
"not_discussed". That is the correct answer when the topic is discussed but this specific
provision is not.

Return exactly this JSON object, with the keys in this order:
{{"sentence_ids": [<numbers, or empty>],
 "answer": "<the answer those sentences support, or \"not_discussed\">",
 "confidence": "high" | "medium" | "low",
 "coder_notes": "..."}}"""


def enrich_prompt(question: Question, passages: list[Passage],
                  attempt: Attempt) -> str:
    return f"""\
{question_block(question)}

A grounded answer already exists for this question:
ANSWER: {attempt.answer}
QUOTE:  {attempt.evidence[:900]}

Your job is only to check that answer for MISSING material detail, using the
passages below (some are new). A provision is usually written in more than one
place: a rate in one clause and a cap in another, elementary in one sentence and
secondary in the next, a base entitlement in the article and an extra amount in an
appendix or for one employee group.

List only detail that the passages STATE and the answer OMITS: another number,
rate, dollar amount, percentage, day or minute count, step or lane, cap, minimum,
maximum, deadline, waiting period, eligibility condition, or a different value for
another school level, employee group, or contract year. Every addition must come
with the verbatim words that state it. Invent nothing, infer nothing, and do not
list detail that is already in the answer. An answer that is already complete gets
an empty list -- that is a normal and acceptable outcome.

PASSAGES FROM THE DOCUMENT:
{passage_block(passages)}

Return exactly this JSON object, with the keys in this order:
{{"additions": [{{"quote": "<contiguous verbatim span stating the missing detail>",
                "detail": "<the missing detail in a few words>"}}],
 "answer": "<the full answer rewritten to include every addition; identical to the existing answer if there are none>",
 "evidence": "<the single clause that most directly governs the provision, contiguous and verbatim>",
 "confidence": "high" | "medium" | "low",
 "coder_notes": "..."}}"""


def no_audit_prompt(question: Question, passages: list[Passage],
                    attempt: Attempt) -> str:
    return f"""\
{question_block(question)}

The provisional code for this question is "no". In this dataset "no" means the
document EXPLICITLY states that the provision does not exist, is not provided, or
is prohibited. The quote recorded for it is:
{attempt.evidence[:1200] or "(none)"}

PASSAGES FROM THE DOCUMENT:
{passage_block(passages)}

Audit that code. Set "explicit_denial" true only if a clause in these passages
denies or forbids the provision in so many words ("shall not", "may not", "is not
provided", "no ... shall be", "is prohibited"). If instead a clause DESCRIBES the
provision, or merely limits, conditions or caps it, the correct code is a
substantive answer, not "no". If the topic simply does not appear in these
passages, the correct code is "not_discussed".

Return exactly this JSON object, with the keys in this order:
{{"evidence": "<one contiguous verbatim span from one passage supporting your code, or \\"\\">",
 "passage_id": <the passage_id you copied from, or null>,
 "explicit_denial": true | false,
 "answer": "<\\"no\\" if explicit denial, else the substantive answer, else \\"not_discussed\\">",
 "confidence": "high" | "medium" | "low",
 "coder_notes": "..."}}"""


# ── per-question pipeline ─────────────────────────────────────────────────────────

def try_realign(attempt: Attempt, passages: list[Passage], page_blocks: list[str],
                stats: Stats) -> Attempt | None:
    """Rebuild an unverifiable quote from the passage text, or give up."""
    repaired = realign(attempt.evidence, passages)
    if not repaired:
        return None
    fixed = verify({"answer": attempt.answer, "evidence": repaired,
                    "confidence": attempt.confidence,
                    "coder_notes": attempt.coder_notes}, passages, page_blocks, stats)
    if not fixed.grounded:
        return None
    stats.bump("realigned")
    fixed.coder_notes = (fixed.coder_notes + " [quote realigned by the host to the "
                         "document's own wording of the same clause]").strip()
    return fixed


def resolve_grounding(client, question: Question, passages: list[Passage],
                      page_blocks: list[str], attempt: Attempt,
                      stats: Stats) -> Attempt:
    """Make a substantive answer's quote verifiable, or record it as ungrounded.

    A stitched quote always costs a re-ask, because `contiguous=False` means the
    model deliberately dropped governing words and its answer may depend on the
    dropped part. A merely mistranscribed quote is realigned first, since the host
    can do that deterministically and correctly.
    """
    if attempt.grounded or classify(attempt.answer) in {"not_discussed", "empty",
                                                        "not_applicable"}:
        return attempt
    reason = attempt.grounding_error or "the quote is not a verbatim span of one passage"
    stitched = "stitched" in reason
    if not stitched:
        fixed = try_realign(attempt, passages, page_blocks, stats)
        if fixed is not None:
            return fixed
    stats.bump("stitched_reasks")
    retry = verify(ask(client, SYSTEM_RULES,
                       restitch_prompt(question, passages, attempt.evidence, reason),
                       stats), passages, page_blocks, stats)
    if retry.grounded:
        stats.bump("stitch_recovered")
        return retry
    for candidate in (retry, attempt):
        fixed = try_realign(candidate, passages, page_blocks, stats)
        if fixed is not None:
            stats.bump("stitch_recovered")
            return fixed
    # Selection instead of transcription. The model has now failed twice to copy text, so
    # stop asking it to: it picks sentence numbers and the host slices the span out of the
    # passage, which is verbatim and contiguous by construction. The prompt also states
    # plainly that an empty selection plus not_discussed is the right answer when the topic
    # is present but the provision is not, which is the case the model otherwise papers
    # over with a paraphrase.
    menu = sentence_menu(passages)
    if menu.sentences:
        try:
            reply = ask(client, SYSTEM_RULES, select_prompt(question, menu, attempt.answer), stats)
            sids = [int(v) for v in (reply.get("sentence_ids") or [])
                    if str(v).strip().lstrip("-").isdigit()]
            span = menu.span(sids) if sids else ""
            selected_answer = str(reply.get("answer") or "").strip()
            if span and classify(selected_answer) not in {"not_discussed", "empty"}:
                picked = verify({"answer": selected_answer or attempt.answer,
                                 "evidence": span,
                                 "confidence": str(reply.get("confidence") or "medium"),
                                 "coder_notes": (str(reply.get("coder_notes") or "") +
                                                 " [evidence selected by sentence number]").strip()},
                                passages, page_blocks, stats)
                if picked.grounded:
                    stats.bump("sentence_selection_recoveries")
                    return picked
            if classify(selected_answer) in {"not_discussed", "empty"}:
                # The model took the licensed exit. That is a real finding, not a failure.
                stats.bump("selection_declined")
                attempt.answer = "not_discussed"
                attempt.evidence = ""
                attempt.page = "not_applicable"
                attempt.confidence = "medium"
                attempt.coder_notes = (attempt.coder_notes +
                                       " [no sentence states this provision; recoded not_discussed]").strip()
                return attempt
        except Exception:
            pass

    # Last resort before dropping: the model may have paraphrased rather than mistyped,
    # in which case no character run matches but the answer's own figures still point at
    # a real clause. Recovers about a quarter of these on a handbook.
    for candidate in (attempt, retry):
        claim_quote = realign_by_claim(candidate.answer, passages)
        if claim_quote:
            probe = verify({"answer": candidate.answer, "evidence": claim_quote,
                            "confidence": "low",
                            "coder_notes": (candidate.coder_notes +
                                            " [quote located from the answer's own figures]").strip()},
                           passages, page_blocks, stats)
            if probe.grounded:
                stats.bump("claim_anchored_recoveries")
                return probe

    # Nothing could be grounded. DROP the quote rather than emit it: a populated
    # evidence field reads as verified support, and on a handbook this path fired for
    # 19 of 58 substantive answers, so the quote would have been the most misleading
    # part of the record. The answer text is kept because the model did read something,
    # but it is marked low confidence and carries an explicit machine-readable flag so
    # it can be filtered and is counted by scripts/audit_citations.py.
    kept = retry if retry.evidence and not attempt.evidence else attempt
    kept.evidence = ""
    kept.page = "not_applicable"
    kept.coder_notes = (kept.coder_notes + f" [ungrounded, quote dropped: {reason}]").strip()
    kept.confidence = "low"
    return kept


def expansion_queries(client, question: Question, stats: Stats) -> list[str]:
    queries = deterministic_queries(question)
    try:
        reply = ask(client, "You write search queries in contract vocabulary. Reply "
                            "with a single JSON object and nothing else.",
                    expansion_prompt(question), stats)
        model_queries = [str(q).strip() for q in (reply.get("queries") or [])
                         if str(q).strip()]
    except Exception as exc:                       # a failed expansion must not
        model_queries = []                         # abort the absence check
        stats.failures.append(f"{question.qid}: expansion failed ({exc})")
    ordered = model_queries + queries
    seen: set[str] = set()
    unique = []
    for query in ordered:
        key = query.casefold()
        if key not in seen:
            seen.add(key)
            unique.append(query)
    return unique[:MAX_EXPANSION_QUERIES]


SIBLING_PROBES = ("elementary junior senior high school level",
                  "maximum minimum cap not to exceed limited to",
                  "per year per day rate amount additional")


def enrich(client, connection, question: Question, passages: list[Passage],
           page_blocks: list[str], attempt: Attempt, stats: Stats,
           keep_citation: bool = True) -> Attempt:
    """Add stated-but-omitted detail to a grounded answer, quote by quote.

    Scored completeness is about variations, not about whether the headline value is
    right: a rate without its cap, or an elementary figure without the secondary
    one, is a half-answer. Retrieval here is conditioned on the answer already
    found, plus generic probes for the shapes a sibling clause takes, so it reaches
    the other half of a split provision. Every proposed addition must arrive with
    verbatim words that the host can locate; one unlocatable addition voids the
    whole revision, which makes the pass unable to launder an invention into the
    answer.
    """
    seen = {passage.passage_id for passage in passages}
    queries = [f"{question.question} {attempt.answer[:200]}"]
    head = " ".join(term.strip() for term in question.keywords.split(",")[:3])
    queries += [f"{head} {probe}" for probe in SIBLING_PROBES]
    extra = collect(connection, queries, seen, 6)
    combined = (passages + extra)[:14]
    stats.bump("enrich_calls")
    reply = ask(client, SYSTEM_RULES, enrich_prompt(question, combined, attempt),
                stats)
    additions = [item for item in (reply.get("additions") or [])
                 if isinstance(item, dict) and str(item.get("quote") or "").strip()]
    if not additions:
        return attempt
    for item in additions:
        quote = str(item["quote"]).strip()
        if not ground(quote, combined, doc=DOC).verbatim and not realign(quote, combined):
            # One unlocatable addition and the whole revision is discarded.
            return attempt
    revised = verify({"answer": reply.get("answer") or attempt.answer,
                      "evidence": reply.get("evidence") or attempt.evidence,
                      "confidence": reply.get("confidence") or attempt.confidence,
                      "coder_notes": reply.get("coder_notes") or ""},
                     combined, page_blocks, stats)
    if classify(revised.answer) != "substantive":
        return attempt
    if not revised.grounded:
        fixed = try_realign(revised, combined, page_blocks, stats)
        revised = fixed if fixed is not None else revised
    if not revised.grounded:
        # Never lose a verified citation to an unverifiable one.
        revised.evidence, revised.page = attempt.evidence, attempt.page
        revised.grounded = attempt.grounded
    if keep_citation and attempt.grounded:
        revised.alt_evidence, revised.alt_page = revised.evidence, revised.page
        revised.evidence, revised.page = attempt.evidence, attempt.page
    else:
        revised.alt_evidence, revised.alt_page = attempt.evidence, attempt.page
    stats.bump("enriched")
    detail = "; ".join(str(item.get("detail") or "")[:80] for item in additions)
    revised.coder_notes = (f"{attempt.coder_notes} {revised.coder_notes} "
                           f"[completeness sweep added: {detail}]").strip()
    return revised


def code_question(client, connection, question: Question, page_blocks: list[str],
                  stats: Stats, do_enrich: bool = True,
                  keep_citation: bool = True) -> dict:
    """One question, end to end, including mandatory absence verification."""
    started = time.time()
    passages = fused_passages(connection, primary_query(question), doc=DOC,
                              budget=PASS1_BUDGET)
    attempt = verify(ask(client, SYSTEM_RULES, pass1_prompt(question, passages),
                         stats), passages, page_blocks, stats)
    attempt = resolve_grounding(client, question, passages, page_blocks, attempt,
                                stats)
    first_status = classify(attempt.answer)
    verification = "not_needed"

    queries: list[str] = []
    if first_status in ABSENCE_STATUSES:
        stats.bump("pass1_absences")
        verification = "confirmed"
        queries = expansion_queries(client, question, stats)
        seen = {passage.passage_id for passage in passages}
        second = collect(connection, queries, seen, PASS2_BUDGET)
        if second:
            reply = ask(client, SYSTEM_RULES,
                        pass2_prompt(question, second,
                                     attempt.answer or "not_discussed"), stats)
            candidate = verify(reply, second, page_blocks, stats)
            found = (str(reply.get("verdict") or "").strip().casefold() == "found"
                     and classify(candidate.answer) == "substantive")
            if found:
                candidate = resolve_grounding(client, question, second, page_blocks,
                                              candidate, stats)
            if found and candidate.grounded:
                stats.bump("overturned")
                verification = "overturned"
                candidate.coder_notes = (
                    candidate.coder_notes + " [found on absence-verification pass; "
                    "first-pass passages did not contain it]").strip()
                attempt = candidate
                passages = second
            else:
                stats.bump("verified_absences")
                if first_status in {"empty", "not_applicable"} or not attempt.grounded:
                    if first_status != "not_applicable":
                        attempt.answer = "not_discussed"
                        attempt.evidence = ""
                        attempt.page = "not_applicable"
                attempt.coder_notes = (
                    attempt.coder_notes + " [absence verified: re-searched with "
                    f"{len(queries)} contract-vocabulary queries covering appendix "
                    "and special-employee-group wording]").strip()
        else:
            stats.bump("verified_absences")

    if classify(attempt.answer) == "no":
        stats.bump("no_audits")
        if not attempt.grounded or not _DENIAL.search(attempt.evidence):
            reply = ask(client, SYSTEM_RULES,
                        no_audit_prompt(question, passages, attempt), stats)
            audited = verify(reply, passages, page_blocks, stats)
            denial = bool(reply.get("explicit_denial"))
            audited_status = classify(audited.answer)
            if audited_status == "substantive" and audited.grounded and not denial:
                stats.bump("no_downgrades")
                audited.coder_notes = (audited.coder_notes + " [recoded from \"no\": "
                                       "the clause describes the provision rather "
                                       "than denying it]").strip()
                attempt = audited
            elif audited_status == "not_discussed":
                stats.bump("no_downgrades")
                attempt.answer = "not_discussed"
                attempt.evidence = ""
                attempt.page = "not_applicable"
                attempt.coder_notes = (attempt.coder_notes + " [recoded from \"no\": "
                                       "no explicit denial in the document]").strip()
            elif denial and audited.grounded:
                attempt = audited

    if do_enrich and classify(attempt.answer) == "substantive" and attempt.grounded:
        attempt = enrich(client, connection, question, passages, page_blocks,
                         attempt, stats, keep_citation=keep_citation)

    # The model returns "high" for almost everything, so confidence is capped by
    # what the host actually established. An absence in particular can never be
    # high: two searches missing a provision is evidence, not proof, because only a
    # few dozen of the document's passages were ever read.
    if verification == "confirmed":
        attempt.confidence = "low" if not queries else "medium"
    elif verification == "overturned":
        attempt.confidence = cap_confidence(attempt.confidence, "medium")
    if "recoded from" in attempt.coder_notes:
        attempt.confidence = cap_confidence(attempt.confidence, "medium")

    final_status = classify(attempt.answer)
    if final_status in {"not_discussed", "empty", "not_applicable"}:
        attempt.evidence = ""
        attempt.page = "not_applicable"
        if final_status == "empty":
            attempt.answer = "not_discussed"
    return {
        "question_id": question.qid,
        "answer": attempt.answer,
        "evidence": attempt.evidence,
        "page": attempt.page,
        "confidence": attempt.confidence,
        "coder_notes": attempt.coder_notes,
        "_verification": verification,
        "_first_status": first_status,
        "_grounded": attempt.grounded,
        "_alt_evidence": attempt.alt_evidence,
        "_alt_page": attempt.alt_page,
        "_seconds": round(time.time() - started, 1),
    }


# ── driver ────────────────────────────────────────────────────────────────────────

def scored_question_ids() -> list[str]:
    """Question IDs the deterministic scorer covers.

    Only the identifier column is read. No expected status, page, token or answer
    field is loaded, so nothing about the key can leak into extraction.
    """
    with GOLD_PATH.open(newline="", encoding="utf-8") as source:
        return [row["question_id"] for row in csv.DictReader(source)]


def load_progress(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    done: dict[str, dict] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            record = json.loads(line)
            done[record["question_id"]] = record
    return done


def write_output(records: list[dict], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    public = [{key: value for key, value in record.items()
               if not key.startswith("_")} for record in records]
    lines = []
    for index in range(0, len(public), ANSWERS_PER_LINE):
        lines.append(json.dumps({"document_id": DOC.document_id,
                                 "batch": index // ANSWERS_PER_LINE + 1,
                                 "answers": public[index:index + ANSWERS_PER_LINE]},
                                ensure_ascii=False))
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--document-id", default=DEFAULT_DOCUMENT_ID)
    parser.add_argument("--out", type=Path, default=OUT_PATH)
    parser.add_argument("--progress", type=Path, default=PROGRESS_PATH)
    parser.add_argument("--resume", action="store_true",
                        help="skip questions already in the progress file")
    parser.add_argument("--question-id", action="append", default=[],
                        help="code only this question (repeatable)")
    parser.add_argument("--scored-only", action="store_true",
                        help="restrict to the question IDs the scorer covers")
    parser.add_argument("--limit", type=int,
                        help="code only the first N questions")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--no-enrich", action="store_true",
                        help="skip the completeness sweep over grounded answers")
    parser.add_argument("--sweep-recites", action="store_true",
                        help="let the completeness sweep replace the quote too "
                             "(measured worse: it drifts the page off the governing clause)")
    args = parser.parse_args()
    global DOC
    DOC = load_document(args.document_id)

    questions = read_codebook()
    if args.scored_only:
        wanted = set(scored_question_ids())
        questions = [q for q in questions if q.qid in wanted]
    if args.question_id:
        wanted = set(args.question_id)
        questions = [q for q in questions if q.qid in wanted]
        missing = wanted - {q.qid for q in questions}
        if missing:
            raise SystemExit(f"unknown question ids: {sorted(missing)}")
    if args.limit is not None:
        questions = questions[:args.limit]
    if not questions:
        raise SystemExit("no questions selected")

    done = load_progress(args.progress) if args.resume else {}
    todo = [q for q in questions if q.qid not in done]
    print(f"{len(questions)} selected, {len(done)} resumed, {len(todo)} to code")

    client = get_client()
    page_blocks = [scorer_norm(block) for block in DOC.pages()]
    stats = Stats()
    write_lock = threading.Lock()
    args.progress.parent.mkdir(parents=True, exist_ok=True)
    if not args.resume and args.progress.exists():
        args.progress.unlink()
    progress_handle = args.progress.open("a", encoding="utf-8")
    started = time.time()

    def run(question: Question) -> dict:
        # One connection per call: sqlite3 connections are not thread-safe.
        connection = open_database(DB_PATH)
        try:
            record = code_question(client, connection, question, page_blocks, stats,
                                   do_enrich=not args.no_enrich,
                                   keep_citation=not args.sweep_recites)
        except Exception as exc:
            stats.failures.append(f"{question.qid}: {exc}")
            record = {"question_id": question.qid, "answer": "not_discussed",
                      "evidence": "", "page": "not_applicable",
                      "confidence": "low",
                      "coder_notes": f"extraction failed: {exc}",
                      "_verification": "failed", "_first_status": "error",
                      "_grounded": False, "_seconds": 0.0}
        finally:
            connection.close()
        with write_lock:
            progress_handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            progress_handle.flush()
            print(f"  {record['question_id']:42s} {record['_verification']:12s} "
                  f"{record['answer'][:52]!r}", flush=True)
        return record

    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        coded = list(pool.map(run, todo))
    progress_handle.close()

    by_qid = {**done, **{record["question_id"]: record for record in coded}}
    order = {q.qid: index for index, q in enumerate(read_codebook())}
    records = sorted(by_qid.values(), key=lambda r: order.get(r["question_id"], 1e9))
    write_output(records, args.out)

    elapsed = time.time() - started
    print(f"\nwrote {args.out} ({len(records)} answers)")
    print(f"model calls        {stats.calls}")
    print(f"wall clock         {elapsed / 60:.1f} min ({elapsed:.0f}s)")
    print(f"pass-1 absences    {stats.pass1_absences}")
    print(f"  overturned       {stats.overturned}")
    print(f"  confirmed        {stats.verified_absences}")
    print(f"stitched re-asks   {stats.stitched_reasks} "
          f"({stats.stitch_recovered} recovered)")
    print(f"host realignments  {stats.realigned}")
    print(f"completeness sweep {stats.enrich_calls} calls "
          f"({stats.enriched} answers revised)")
    print(f"'no' audits        {stats.no_audits} ({stats.no_downgrades} recoded)")
    print(f"page-boundary trims {stats.page_trims}")
    print(f"claim-anchored recov {stats.claim_anchored_recoveries}")
    print(f"sentence selection  {stats.sentence_selection_recoveries} recovered, "
          f"{stats.selection_declined} recoded not_discussed")
    if stats.failures:
        print(f"failures           {len(stats.failures)}")
        for failure in stats.failures[:10]:
            print(f"  {failure}")


if __name__ == "__main__":
    main()
