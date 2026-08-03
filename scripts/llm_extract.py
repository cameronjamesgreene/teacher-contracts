#!/usr/bin/env python3
"""LLM contract extraction — two-stage, category-batched pipeline.

For each document and each category sub-batch (meta, pay, benefits, …, safety):
  Stage 1: the document is split into overlapping sections (DOC_CHUNK_SIZE chars
           each); each section is sent to the LLM separately to retrieve relevant
           passages and code answers. Results from all sections are merged by
           taking the highest-confidence non-missing answer per question.
  Stage 2: audit the merged Stage 1 answers — the auditor receives both the Stage
           1 coded results AND the original document text, so it can catch passages
           Stage 1 missed; revise to discussed_unclear / not_discussed if weak;
           finalize confidence; record audit notes in coder_notes.

Each codebook category is further split into sub-batches of at most
MAX_QUESTIONS_PER_BATCH questions per call — SOM's model (see som_client.py) is
a much smaller reasoning model than what this pipeline originally targeted, and
asking it to retrieve+code+audit a large category (e.g. "pay" has 17 questions)
in one call risks the same truncated/malformed-JSON failures seen with
rights_score.py before its chunk size was reduced. Each sub-batch result is
cached separately in cache/llm_cache/ as JSON so an interrupted run resumes at
the next uncached sub-batch rather than re-querying everything for a document.

Outputs:
  output/llm_main_dataset.csv   — wide format, one row per document
  output/llm_coding_log.csv     — long format, one row per document-question pair

Calls the SOM API (an OpenAI-compatible chat completions endpoint), the same as
salary_schedule.py and rights_score.py. See som_client.py for the key/model
setup (SOM_API_KEY env var or scripts/som_api_key.txt).

Usage:
    python3 llm_extract.py                          # run the full 40-document sample
    python3 llm_extract.py --max-docs 2              # limit for a quick test
    python3 llm_extract.py --doc "Granite School District|professional_agreement_with_gea_2020_2023.pdf"
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
from collections import OrderedDict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils import (
    OUT_DIR,
    WORK,
    Document,
    Question,
    build_metadata,
    load_documents,
    norm_ws,
    quote_present,
    read_codebook,
    read_sample,
    terms_from_question,
)
from som_client import (
    MAX_TOKENS, MODEL, budgeted_max_tokens, cap_text, create_with_retries, get_client,
)

CACHE_DIR = WORK / "cache" / "llm_cache"

# Set to an integer to limit the run; None processes all documents in the sample.
MAX_DOCS = 40

MAX_TEXT_CHARS = 180_000

# At most this many questions per API call, after grouping by category — see
# module docstring for why (SOM's model is weaker than this pipeline originally
# targeted, so smaller calls are more reliable than one big category-sized call).
MAX_QUESTIONS_PER_BATCH = 6

# Document-chunking parameters for Stage 1. Long documents are split into
# overlapping sections so the AI reads every part of the document (appendices,
# later articles, MOUs) rather than searching one 180 K-char blob that may
# cause it to miss content near the end. Each section is sent in a separate
# Stage 1 call; results are merged by taking the best answer per question.
DOC_CHUNK_SIZE = 45_000   # max chars per Stage-1 section
DOC_CHUNK_OVERLAP = 5_000  # overlap so sentences at section boundaries are seen twice
STAGE2_DOC_CHARS = 50_000   # chars of the original document passed to Stage 2 (kept well
                            # under the 32k-token window; cap_text() is a further backstop)
# Keyword-retrieval (opt-in via LLM_RETRIEVAL=1): run each question sub-batch only on the
# document sections whose text contains one of the batch's codebook keywords, instead of on
# EVERY section. Cuts Stage-1 calls from (sub-batches x ALL sections) to (sub-batches x
# RELEVANT sections) — the dominant cost on long docs (LA: 40 sections x 23 batches = 920
# calls). Falls back to all sections for a batch with no keyword hit, so recall is preserved;
# Stage-2 (full-doc verification) and the not_discussed recovery pass are further backstops.
# Default ON (v9): the always-run recovery pass keyword-window re-scans the WHOLE doc for every
# not_discussed answer, so retrieval's section-skipping cannot introduce a silent false negative
# while it cuts Stage-1 calls ~40-77%. Set LLM_RETRIEVAL=0 to force the exhaustive pass.
LLM_RETRIEVAL = os.environ.get("LLM_RETRIEVAL", "1") == "1"
LLM_RETRIEVAL_TOPK = int(os.environ.get("LLM_RETRIEVAL_TOPK", "8"))  # sections/batch to keep

# ── two-view coding (default) ─────────────────────────────────────────────────────────────
# Replaces the chunk x sub-batch x recovery x reconciliation path below with a whole-document
# view plus an FTS5 BM25 retrieval view, unioned and gated on quote verification, then a
# never-silent escalation for anything still coded not_discussed. See two_view.py for the
# measurements that motivate it. Set LLM_TWO_VIEW=0 to run the legacy path for an A/B.
TWO_VIEW = os.environ.get("LLM_TWO_VIEW", "1") == "1"

# Category batch order must match the prefix order in extraction_elements_reduced.md.
BATCH_ORDER = [
    "meta", "pay", "benefits", "leave", "workload",
    "class", "evaluation", "security", "discipline", "conduct", "safety",
]

# ── system prompts ────────────────────────────────────────────────────────────

STAGE1_SYSTEM = """\
You are an expert researcher extracting structured data from U.S. public school \
district employment documents — collective bargaining agreements, employee handbooks, \
salary schedules, policy manuals, tentative agreements, and settlement summaries.

You will receive the text of one document (or a numbered section of a longer document) \
and a batch of questions from one topic category. For each question complete two steps:

STEP 1 — RETRIEVE: Search the provided text for every passage plausibly relevant to \
this question. Include passages in appendices, exhibits, MOUs, and later articles — \
do not stop at the first hit. Note the page or section reference.

STEP 2 — CODE: Answer the question using ONLY the passages you retrieved in \
Step 1. Do not draw on passages retrieved for other questions or on outside \
knowledge. If no relevant passage was found in the provided text, code not_discussed.

IMPORTANT — DOCUMENT SECTIONS: When the user message says "DOCUMENT SECTION N OF M", \
you are reading only one section of a larger document. Code not_discussed only if the \
relevant passage is absent from THIS section — do not conclude it is absent from the \
full document. Another section call will cover the rest.

Return a JSON object where each key is a Question ID and each value has exactly:
  "answer"     — extracted value, or one of:
                 not_discussed | discussed_unclear | not_applicable | ocr_needed
  "evidence"   — short verbatim quote supporting the answer; empty string if not_discussed
  "page"       — page number as a string; "not_applicable" if not discussed
  "confidence" — preliminary rating: high | medium | low

Coding rules:
  • not_discussed: topic is genuinely absent from this document (or this section).
  • discussed_unclear: topic appears but cannot be coded specifically.
  • not_applicable: question does not apply to this document type or unit.
  • Always emit the lowercase long-form status codes not_discussed / discussed_unclear /
    not_applicable / ocr_needed — never ND, DU, or OCR_NEEDED, even if a question's notes
    abbreviate them.
  • For yes/no questions answer "yes" or "no" based on document text only. Answer "no"
    ONLY when the document positively shows the provision does NOT exist / is NOT provided;
    do NOT answer "no" merely because you did not find a passage — in that case answer
    not_discussed. If your evidence quote actually describes the provision, the answer is
    "yes" (or the specific value), never "no".
  • A relevant provision may sit under a DIFFERENT heading than this question's topic
    (e.g. out-of-state salary credit inside a general "Salary Schedule" article, email/
    acceptable-use rules inside a "Technology" or general-conduct section, layoff order
    inside a seniority section). Retrieve by meaning, not by matching the heading.
  • ADOPTION BY REFERENCE COUNTS. A document that names, cites, or incorporates an external
    code, standard, statute, framework, or plan (e.g. "the Code of Ethics of the Education
    Profession of Florida", the "Danielson Framework", a named 403(b)/pension plan) IS
    discussing that topic — code "yes"/the named value with the citation as evidence, never
    not_discussed. Do not require the document to reproduce the referenced text in full.
  • Quote evidence verbatim. Note when a provision appears to restate statute
    rather than a district-negotiated benefit.
  • If a provision varies by year, employee type, step, lane, or classification,
    extract the variation compactly.

Return ONLY a valid JSON object — no markdown fences, no explanation.\
"""

STAGE2_SYSTEM = """\
You are auditing coded contract-document answers for accuracy and consistency.

You will receive Stage 1 coded answers for a batch of questions, plus the original \
document text. For each answer:

1. Re-read the quoted evidence. If the evidence is absent or weak, search the \
   original document text (appended at the end of the user message) for a passage \
   Stage 1 may have missed — particularly in appendices, later articles, and MOUs. \
   If you find a better passage, update the evidence and page fields accordingly.
2. Ask: "Does this evidence EXPLICITLY support the coded answer, or is it
   indirect, ambiguous, or only weakly relevant?"
3. Revise if needed:
   — If the evidence is weak, ambiguous, or only tangentially related, change
     the answer to discussed_unclear.
   — If no actual supporting evidence was quoted and you cannot locate any in
     the document text below, change to not_discussed. BUT if a verbatim evidence
     quote WAS provided and it genuinely supports the answer, keep the answer even if
     the appended document text (which may be truncated) does not contain that passage —
     do not blank a quote-supported answer just because you cannot re-find the quote here.
   — If the answer overstates what the evidence says (e.g., codes "yes" when
     the passage only implies it), revise to discussed_unclear.
   — Preserve "no" answers ONLY when the document explicitly states a provision does
     not exist or is not provided. If the quoted evidence actually DESCRIBES the
     provision, the answer must be "yes"/the specific value — never leave it as "no"
     (a "no" that cites an on-topic provision is self-contradictory; correct it).
   — Do NOT downgrade a specific answer to discussed_unclear simply because the
     evidence uses conditional language, exceptions, or applies to a subset of
     employees. If the evidence clearly and directly states a specific value
     (number, percentage, date, policy name), preserve the specific answer.
   — Adoption by reference counts: a citation to a named external code, standard,
     statute, framework, or plan is a valid provision — keep the "yes"/named value,
     do NOT downgrade it merely because the referenced text is not reproduced in full.
4. Assign or revise the confidence rating:
   — high: evidence directly and unambiguously states the answer.
   — medium: evidence strongly suggests the answer but requires minor inference.
   — low: evidence is indirect, partially readable, or required significant
     inference.
5. Record any corrections or reasoning in "coder_notes". Leave empty if no
   change was made.

Return a JSON object where each key is a Question ID and each value has:
  "answer", "evidence", "page", "confidence", "coder_notes"

Return ONLY a valid JSON object — no markdown fences, no explanation.\
"""


# ── helpers ───────────────────────────────────────────────────────────────────

def group_by_category(questions: list[Question]) -> list[tuple[str, list[Question]]]:
    """Return questions grouped by ID prefix in BATCH_ORDER order."""
    groups: dict[str, list[Question]] = OrderedDict()
    for q in questions:
        cat = q.qid.split("_")[0]
        groups.setdefault(cat, []).append(q)
    ordered = [(cat, groups[cat]) for cat in BATCH_ORDER if cat in groups]
    # Append any future categories not yet in BATCH_ORDER
    known = set(BATCH_ORDER)
    for cat, qs in groups.items():
        if cat not in known:
            ordered.append((cat, qs))
    return ordered


def split_into_subbatches(
    batches: list[tuple[str, list[Question]]],
) -> list[tuple[str, int, list[Question]]]:
    """Split each category's questions into chunks of at most
    MAX_QUESTIONS_PER_BATCH, returning (category, sub-batch index, questions)."""
    sub: list[tuple[str, int, list[Question]]] = []
    for cat, qs in batches:
        for i in range(0, len(qs), MAX_QUESTIONS_PER_BATCH):
            sub.append((cat, i // MAX_QUESTIONS_PER_BATCH + 1, qs[i:i + MAX_QUESTIONS_PER_BATCH]))
    return sub


# ── API calls ─────────────────────────────────────────────────────────────────

def _call_stage1(
    client,
    doc: Document,
    batch_qs: list[Question],
    cat: str,
    doc_text: str,
    chunk_num: int = 1,
    total_chunks: int = 1,
) -> dict[str, dict]:
    q_list = [
        {
            "id": q.qid,
            "topic": q.topic,
            "question": q.question,
            "answer_type": q.answer_type,
            "extract_if_discussed": q.extract,
            "keywords": q.keywords,
            "notes": q.notes,
        }
        for q in batch_qs
    ]
    section_header = (
        f"DOCUMENT SECTION {chunk_num} OF {total_chunks}\n"
        if total_chunks > 1 else ""
    )
    user_str = (
        f"Document: {doc.file_name}\n"
        f"District: {doc.district}\n\n"
        + section_header
        + f"CATEGORY BATCH: {cat}\n"
        f"QUESTIONS:\n{json.dumps(q_list, indent=2)}\n\n"
        "---BEGIN DOCUMENT---\n"
        + cap_text(doc_text)
        + "\n---END DOCUMENT---\n\n"
        "Answer every question in this batch using only passages "
        "retrieved from the document above. Return only the JSON object."
    )
    return create_with_retries(
        client,
        model=MODEL,
        max_tokens=budgeted_max_tokens(STAGE1_SYSTEM, user_str),
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": STAGE1_SYSTEM},
            {"role": "user", "content": user_str},
        ],
    )


def _call_stage2(
    client,
    batch_qs: list[Question],
    stage1: dict[str, dict],
    cat: str,
    doc_text: str = "",
) -> dict[str, dict]:
    _fallback = {"answer": "not_discussed", "evidence": "", "page": "not_applicable",
                 "confidence": "low"}
    audit_input = {
        q.qid: {
            "question": q.question,
            **{k: stage1.get(q.qid, _fallback).get(k, v)
               for k, v in _fallback.items()},
        }
        for q in batch_qs
    }
    # Never show Stage 2 an abbreviated status code (ND/DU/...) — it audits the
    # long forms it is instructed to emit.
    for rec in audit_input.values():
        rec["answer"] = _normalize_answer(rec["answer"])
    user_content = (
        f"CATEGORY BATCH: {cat}\n\n"
        f"STAGE 1 RESULTS:\n{json.dumps(audit_input, indent=2)}\n\n"
        "Audit each answer. Return only the JSON object."
    )
    if doc_text:
        user_content += (
            "\n\n---ORIGINAL DOCUMENT (use to verify or find missed passages)---\n"
            + cap_text(doc_text)
            + "\n---END DOCUMENT---"
        )
    return create_with_retries(
        client,
        model=MODEL,
        max_tokens=budgeted_max_tokens(STAGE2_SYSTEM, user_content),
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": STAGE2_SYSTEM},
            {"role": "user", "content": user_content},
        ],
    )


# ── per-document pipeline ────────────────────────────────────────────────────

_FALLBACK: dict[str, str] = {
    "answer": "not_discussed",
    "evidence": "",
    "page": "not_applicable",
    "confidence": "low",
    "coder_notes": "",
}

_MISSING_ANSWERS = {"not_discussed", "discussed_unclear", "not_applicable", "ocr_needed", ""}
_CONFIDENCE_RANK = {"high": 3, "medium": 2, "low": 1}

# The codebook (and many per-question notes fed to the model) abbreviate the
# status codes; the model sometimes echoes those abbreviations. Map them back to
# the canonical long forms so the missing-answer checks and CSV output agree.
_ANSWER_ALIASES = {
    "nd": "not_discussed",
    "not discussed": "not_discussed",
    "du": "discussed_unclear",
    "discussed unclear": "discussed_unclear",
    "na": "not_applicable",
    "n/a": "not_applicable",
    "not applicable": "not_applicable",
    "ocr needed": "ocr_needed",
    "ocrneeded": "ocr_needed",
}


def _normalize_answer(ans) -> str:
    """Canonicalize an answer: join list answers, strip, and map status-code
    abbreviations (ND/DU/N/A/OCR_NEEDED) to the long forms. Returns "" for an
    empty/None answer (callers substitute the not_discussed fallback)."""
    if isinstance(ans, list):
        ans = "; ".join(str(x) for x in ans if str(x).strip())
    ans = ("" if ans is None else str(ans)).strip()
    return _ANSWER_ALIASES.get(ans.lower(), ans)


# Quote/document matching now lives in utils (shared with rights_score). Keep the
# module-local names as thin aliases so the rest of this file is unchanged.
_norm_ws = norm_ws
_quote_present = quote_present


def _norm_record(entry: dict) -> dict:
    """Fill every _FALLBACK key from `entry`, normalizing the answer and never
    leaving a blank answer. Empty non-note fields keep the fallback value."""
    rec = dict(_FALLBACK)
    for k in _FALLBACK:
        v = entry.get(k)
        if v is None:
            continue
        if k == "answer":
            a = _normalize_answer(v)
            if a:
                rec[k] = a
        elif k == "coder_notes":
            rec[k] = str(v)
        elif v != "":
            rec[k] = v
    return rec


def _coherent_merge(s1_entry: dict, s2_entry: dict, full_text_norm: str) -> dict:
    """Combine one question's Stage-1 and Stage-2 records atomically.

    Stage 2 is the auditor and normally wins as a whole record, so answer,
    evidence, page and confidence always come from one coherent record and can
    never disagree (the old per-field merge could leave a not_discussed answer
    next to a surviving Stage-1 quote — the reported bug). The one exception:
    Stage 2 must not blank a substantive Stage-1 answer to a missing code when
    Stage 1 supplied a verbatim quote that is actually present in the document.
    That guard fixes provisions located past Stage 2's char-capped view of the
    document, which Stage 2 never saw and would otherwise wrongly drop.
    """
    s1r = _norm_record(s1_entry)
    if not s2_entry:
        return s1r
    s2r = _norm_record(s2_entry)

    s2_missing = s2r["answer"].lower() in _MISSING_ANSWERS
    s1_subst = s1r["answer"].lower() not in _MISSING_ANSWERS

    if s2_missing and s1_subst and _quote_present(s1r["evidence"], full_text_norm):
        return s1r

    # Adopt Stage 2 wholesale, but keep a good Stage-1 quote when Stage 2 upheld a
    # substantive answer without re-quoting it.
    if not s2_missing and not s2r["evidence"] and s1r["evidence"]:
        s2r["evidence"] = s1r["evidence"]
        s2r["page"] = s1r["page"]
    return s2r


def _chunk_document(text: str) -> list[str]:
    """Split document text into overlapping sections for Stage 1 processing.

    Short documents (≤ DOC_CHUNK_SIZE) are returned as a single-element list so
    the rest of the pipeline treats them identically to long ones.
    """
    if len(text) <= DOC_CHUNK_SIZE:
        return [text]
    chunks: list[str] = []
    start, n = 0, len(text)
    while start < n:
        end = min(start + DOC_CHUNK_SIZE, n)
        chunks.append(text[start:end])
        if end >= n:
            break
        start = end - DOC_CHUNK_OVERLAP
    return chunks


def _merge_stage1_chunks(
    batch_qs: list[Question],
    chunk_results: list[dict[str, dict]],
) -> dict[str, dict]:
    """Merge Stage-1 results from multiple document sections.

    Per question: prefer a substantive (non-missing) answer with higher
    confidence over a not_discussed or discussed_unclear answer. If all sections
    returned not_discussed, keep that.
    """
    # An empty chunk_results means every Stage-1 section call raised (they are
    # only appended on success). Mark that as ocr_needed rather than a plain
    # not_discussed so a transient failure is distinguishable from real absence.
    all_failed = not chunk_results
    merged: dict[str, dict] = {}
    for q in batch_qs:
        if all_failed:
            merged[q.qid] = {**_FALLBACK, "answer": "ocr_needed",
                             "coder_notes": "stage1 failed for all sections"}
            continue
        best: dict | None = None
        best_rank = -1
        for chunk_result in chunk_results:
            entry = chunk_result.get(q.qid)
            if not entry:
                continue
            answer = _normalize_answer(entry.get("answer"))
            conf = entry.get("confidence") or "low"
            is_substantive = answer not in _MISSING_ANSWERS
            has_evidence = bool((entry.get("evidence") or "").strip())
            # A substantive answer backed by a verbatim quote outranks a bare one: a
            # chunk-level "no"/"not_discussed" with no evidence usually just means
            # "not in THIS section", and must not beat a quoted "yes" from the section
            # that actually contains the provision. The +5 evidence bonus exceeds any
            # confidence delta (max 3), so an evidenced substantive answer always wins.
            rank = (10 if is_substantive else 0) \
                + (5 if is_substantive and has_evidence else 0) \
                + _CONFIDENCE_RANK.get(conf, 0)
            if rank > best_rank:
                best_rank = rank
                best = entry
        merged[q.qid] = best if best else dict(_FALLBACK)
    return merged


# L1 — not_discussed keyword-rescue. Stage 1 sees every chunk for every question, but a
# provision buried in a 45k-char section alongside a whole batch of questions can still be
# missed (the v5 llm residual was 4 Stage-1 recall misses). When a question finalizes to
# not_discussed, locate a focused passage around its codebook keywords and re-run the same
# Stage-1→Stage-2 pass for that ONE question on just that window. A narrow single-question
# prompt materially refocuses attention versus the original batch-on-a-huge-chunk call.
RESCUE_WINDOW_CHARS = 4000  # focused-passage half-width around a hit
MAX_RECONCILE_REASKS = 24   # per-document cap on cross-question reconciliation re-asks


def _keyword_windows(
    full_text: str, terms: list[str], radius: int = RESCUE_WINDOW_CHARS, max_windows: int = 3,
) -> list[str]:
    """Up to `max_windows` focused ~2*radius passages of `full_text`, each centered on a
    DISTINCT occurrence of a meaningful codebook term (>=5 chars). Multiple windows so a
    provision at a later position is reached, not just the first hit."""
    low = full_text.lower()
    out: list[str] = []
    seen: list[int] = []
    for term in terms:
        t = term.strip().lower()
        if len(t) < 5:
            continue
        start = 0
        while len(out) < max_windows:
            pos = low.find(t, start)
            if pos == -1:
                break
            if all(abs(pos - p) > radius for p in seen):
                seen.append(pos)
                out.append(full_text[max(0, pos - radius):min(len(full_text), pos + len(t) + radius)])
            start = pos + len(t)
        if len(out) >= max_windows:
            break
    return out


def _evidence_window(full_text: str, evidence: str, radius: int = RESCUE_WINDOW_CHARS) -> str | None:
    """A focused passage centered on where `evidence` (the model's own quote) occurs in
    the document, or None if it can't be located. Used to re-read the exact region a
    negative answer contradicts, and to ground a sibling's evidence."""
    ev = (evidence or "").strip()
    if len(ev) < 12:
        return None
    low = full_text.lower()
    for n in (60, 40, 24):
        anchor = ev[:n].lower()
        pos = low.find(anchor)
        if pos != -1:
            return full_text[max(0, pos - radius):min(len(full_text), pos + len(anchor) + radius)]
    return None


def _reask_on_window(client, doc: Document, q: Question, cat: str, window: str, full_text_norm: str):
    """Re-run Stage 1 THEN Stage 2 for ONE question on a focused window; return the merged
    record only if it is substantive AND quote-verified against the whole document, else None.

    Stage 2 now runs EVEN WHEN Stage 1 still misses on the window. The v9 false-negative A/B
    showed Stage 1's retrieval prompt skips provisions that Stage 2's audit prompt catches
    (Hillsborough's 'basic salary schedule' sat in the window: Stage 1 = not_discussed, Stage
    2 = discussed), so bailing after a not_discussed Stage 1 — as this did before — threw away
    the exact step that recovers the answer. The narrow window also keeps the Stage-2 input
    small, avoiding the token truncation a full-view Stage-2 hit (Palm Beach step increment).
    _coherent_merge lets a substantive, quote-verified Stage-2 answer win over a Stage-1 miss."""
    try:
        s1 = _call_stage1(client, doc, [q], cat, window, 1, 1)
    except Exception:
        s1 = {}
    s1e = s1.get(q.qid, {}) or dict(_FALLBACK)
    try:
        s2 = _call_stage2(client, [q], {q.qid: s1e}, cat, window)
    except Exception:
        s2 = {}
    merged = _coherent_merge(s1e, s2.get(q.qid, {}), full_text_norm)
    if (_normalize_answer(merged["answer"]) not in _MISSING_ANSWERS
            and _quote_present(merged["evidence"], full_text_norm)):
        return merged
    return None


def _recover_missed_answers(
    client, doc: Document, batch_qs: list[Question], cat: str,
    result: dict[str, dict], full_text: str, full_text_norm: str,
) -> int:
    """Recover false negatives before a fresh subbatch is cached. For each question that
    finalized to not_discussed OR a bare 'no', re-ask on focused windows and adopt a
    CHANGED, substantive, quote-verified answer. Windows come from (1) the model's OWN
    evidence quote when it is actually present in the document — the self-contradiction
    signal behind a 'no' that cites an on-topic passage — and (2) the question's codebook
    keywords (several hits). Adoption requires the focused re-read to return a DIFFERENT,
    document-supported answer, so a genuine not_discussed/no is never overturned.

    2C backstop — never a silent false negative: when recovery LOCATED the topic's keyword
    windows (so the topic's own terms occur in the document) but still could not confirm an
    answer, the surviving not_discussed is marked for a human glance in coder_notes. This is
    the honest way to bound the residual — a small flagged set, not a silent negative."""
    recovered = 0
    for q in batch_qs:
        rec = result.get(q.qid)
        if not rec:
            continue
        orig = _normalize_answer(rec.get("answer"))
        if orig != "not_discussed" and orig != "no":
            continue
        windows: list[str] = []
        ev = rec.get("evidence") or ""
        if orig == "no" and _quote_present(ev, full_text_norm):
            ew = _evidence_window(full_text, ev)
            if ew:
                windows.append(ew)
        kw_windows = _keyword_windows(full_text, terms_from_question(q))
        windows += kw_windows
        adopted = False
        for window in windows:
            got = _reask_on_window(client, doc, q, cat, window, full_text_norm)
            if got and _normalize_answer(got["answer"]) != orig:
                got["coder_notes"] = (str(got.get("coder_notes", "")) + " [recall-recovery]").strip()
                result[q.qid] = got
                recovered += 1
                adopted = True
                break
        # 2C — topic keywords were located in the document but no answer could be confirmed;
        # flag the surviving not_discussed for review rather than shipping a silent negative.
        if not adopted and kw_windows and orig == "not_discussed":
            note = str(rec.get("coder_notes", "") or "")
            if "[review:" not in note:
                rec["coder_notes"] = (
                    note + " [review: topic keywords located in document but no confirmable "
                    "answer — verify this is not a false negative]"
                ).strip()
    return recovered


_DEP_RE = re.compile(r"\b(?:ND|not[_ ]discussed)\b[^.]*?\bif\b\s+([a-z][a-z0-9_]+)", re.I)


def _reconcile_across_questions(
    client, doc: Document, subbatches: list, merged: dict[str, dict],
    full_text: str, full_text_norm: str,
) -> int:
    """Cross-question reconciliation. Sibling questions split across separate Stage-1
    subbatches (batching is by qid-prefix, 6/call) can't see each other, so a provision
    one sibling quoted gets missed by another. For each not_discussed/'no' question,
    gather the evidence windows of its substantively-answered SIBLINGS and re-ask on them;
    adopt a changed, quote-verified answer. Siblings = same codebook topic, or same middle
    qid token (rif, transfer), or an explicit 'Code ND if <qid>' dependency in the notes,
    or >=2 shared codebook keywords. Runs on the full per-document merged dict, so it works
    even when every subbatch was loaded from cache. Bounded by MAX_RECONCILE_REASKS."""
    qs = [q for _, _, bqs in subbatches for q in bqs]
    by_qid = {q.qid: q for q in qs}

    def middle_token(qid: str):
        parts = qid.split("_")
        return parts[1] if len(parts) >= 3 else None

    term_sets = {q.qid: {t for t in terms_from_question(q) if len(t) >= 5} for q in qs}

    def siblings(q: Question) -> set:
        sibs = set()
        mt = middle_token(q.qid)
        for other in qs:
            if other.qid == q.qid:
                continue
            if (other.topic and other.topic == q.topic) or (mt and middle_token(other.qid) == mt):
                sibs.add(other.qid)
            elif term_sets[q.qid] and len(term_sets[q.qid] & term_sets[other.qid]) >= 2:
                sibs.add(other.qid)
        for m in _DEP_RE.finditer(q.notes or ""):
            if m.group(1) in by_qid:
                sibs.add(m.group(1))
        return sibs

    recovered = 0
    for q in qs:
        if recovered >= MAX_RECONCILE_REASKS:
            break
        rec = merged.get(q.qid)
        if not rec:
            continue
        orig = _normalize_answer(rec.get("answer"))
        if orig != "not_discussed" and orig != "no":
            continue
        windows: list[str] = []
        for sib in siblings(q):
            srec = merged.get(sib) or {}
            if _normalize_answer(srec.get("answer")) in _MISSING_ANSWERS:
                continue
            sev = srec.get("evidence") or ""
            if not _quote_present(sev, full_text_norm):
                continue
            w = _evidence_window(full_text, sev)
            if w and w not in windows:
                windows.append(w)
        for window in windows[:3]:
            got = _reask_on_window(client, doc, q, q.qid.split("_")[0], window, full_text_norm)
            if got and _normalize_answer(got["answer"]) != orig:
                got["coder_notes"] = (str(got.get("coder_notes", "")) + " [cross-question]").strip()
                merged[q.qid] = got
                recovered += 1
                break
    return recovered


def _relevant_chunks(batch_qs, doc_chunks: list[str]) -> list[tuple[int, str]]:
    """(1-based section_index, section_text) pairs a sub-batch is actually run on when
    LLM_RETRIEVAL is enabled: the sections whose text contains one of the batch's codebook
    keywords. Keeps the real section index so per-chunk cache keys stay stable. Returns ALL
    sections when there is only one, when the batch has no usable (>=4-char) keywords, or
    when no section matches — so a sparse-keyword batch is never silently skipped (recall)."""
    numbered = list(enumerate(doc_chunks, start=1))
    if len(doc_chunks) <= LLM_RETRIEVAL_TOPK:   # small docs: no benefit, run everything
        return numbered
    kws: set[str] = set()
    for q in batch_qs:
        kw = getattr(q, "keywords", None) or []
        if isinstance(kw, str):
            kw = re.split(r"[,;|]", kw)
        for k in kw:
            k = str(k).strip().lower()
            if len(k) >= 4:
                kws.add(k)
    if not kws:
        return numbered
    # Score each section by how many DISTINCT batch keywords it contains, keep the top-K
    # densest (the sections most likely to actually discuss this batch's topics). Ties and
    # the K cutoff keep the densest; a batch whose keywords hit nothing falls back to all.
    scored = [(sum(1 for k in kws if k in ct.lower()), ci, ct) for ci, ct in numbered]
    scored = [s for s in scored if s[0] > 0]
    if not scored:
        return numbered
    scored.sort(key=lambda s: -s[0])
    top = scored[:LLM_RETRIEVAL_TOPK]
    return [(ci, ct) for _, ci, ct in sorted(top, key=lambda s: s[1])]  # restore doc order


def _process_document(
    client,
    doc: Document,
    subbatches: list[tuple[str, int, list[Question]]],
) -> tuple[dict[str, dict], int, int]:
    """Returns (merged answers, batches_failed, total_batches).

    Stage 1 is run per document section (chunk) and results merged before Stage 2.
    Stage 2 receives the merged Stage 1 answers plus the original document text so
    it can catch passages Stage 1 missed.

    Final per-subbatch results are cached at
      cache/llm_cache/{document_id}__{cat}_{idx:02d}.json
    Intermediate per-chunk Stage-1 results are cached at
      cache/llm_cache/{document_id}__{cat}_{idx:02d}__s1c{ci:02d}.json
    so an interrupted run resumes at the next uncached chunk rather than
    re-querying everything.

    With LLM_TWO_VIEW=1 (the default) this whole path is bypassed in favour of
    two_view.code_document -- whole-document + FTS5 retrieval, unioned and quote-gated.
    The legacy path is kept, and selectable with LLM_TWO_VIEW=0, because the recovery and
    reconciliation passes it contains do recover real answers; removing them should be an
    A/B result, not an assumption.
    """
    if TWO_VIEW:
        import two_view
        coded = two_view.code_document(
            client, doc.document_id, doc.text,
            [q for _, _, batch in subbatches for q in batch],
        )
        return coded, 0, len(subbatches)

    # Use the full document text — no truncation. The chunker splits it into
    # DOC_CHUNK_SIZE sections so each Stage-1 call stays within a manageable
    # context window, and every part of even a very long document gets read.
    full_text = doc.text
    # Normalized once for cheap whole-document quote lookups in _coherent_merge
    # (used to keep a Stage-1 answer whose quote lies past Stage 2's capped view).
    full_text_norm = _norm_ws(full_text)
    doc_chunks = _chunk_document(full_text)
    n_chunks = len(doc_chunks)
    # Stage 2 gets a capped view because it is called once per subbatch (not once
    # per chunk) and the model's context window cannot hold a full-length document
    # alongside the audit prompt and Stage-1 results. Stage 1 chunking already
    # covers the full document, so Stage 2's main role is verification, not discovery.
    stage2_doc = full_text[:STAGE2_DOC_CHARS]

    merged: dict[str, dict] = {}
    batches_failed = 0
    # Subbatches loaded from cache skip the in-loop recovery below (which only runs on a fresh
    # call). Collect them so recovery still runs post-loop on a resumed/re-run doc — the v9 bug
    # was that recovery NEVER ran for cached subbatches, so the recall fix was silently inert.
    recovery_pending: list[tuple[str, list[Question]]] = []

    for cat, idx, batch_qs in subbatches:
        final_cache = CACHE_DIR / f"{doc.document_id}__{cat}_{idx:02d}.json"
        if final_cache.exists():
            result = json.loads(final_cache.read_text(encoding="utf-8"))
            recovery_pending.append((cat, batch_qs))
        else:
            # Stage 1: one call per document section, results merged across sections.
            chunk_s1_results: list[dict[str, dict]] = []
            chunk_texts_used: list[str] = []  # parallel to chunk_s1_results (for 2b)
            # Retrieval: only run this sub-batch on the sections its keywords hit (falls back
            # to all). n_chunks stays the full count so section-of-N framing + cache keys are
            # unchanged; skipped sections simply aren't queried.
            section_iter = (_relevant_chunks(batch_qs, doc_chunks) if LLM_RETRIEVAL
                            else list(enumerate(doc_chunks, start=1)))
            for ci, chunk_text in section_iter:
                if n_chunks > 1:
                    s1_cache = CACHE_DIR / f"{doc.document_id}__{cat}_{idx:02d}__s1c{ci:02d}.json"
                else:
                    s1_cache = CACHE_DIR / f"{doc.document_id}__{cat}_{idx:02d}__s1.json"

                if s1_cache.exists():
                    chunk_s1 = json.loads(s1_cache.read_text(encoding="utf-8"))
                else:
                    try:
                        chunk_s1 = _call_stage1(
                            client, doc, batch_qs, cat, chunk_text, ci, n_chunks,
                        )
                        s1_cache.write_text(
                            json.dumps(chunk_s1, indent=2, ensure_ascii=False),
                            encoding="utf-8",
                        )
                        time.sleep(0.4)
                    except Exception as exc:
                        print(
                            f"      {cat} batch {idx} section {ci}/{n_chunks}: "
                            f"stage1 ERROR {exc}"
                        )
                        continue
                chunk_s1_results.append(chunk_s1)
                chunk_texts_used.append(chunk_text)

            s1 = _merge_stage1_chunks(batch_qs, chunk_s1_results)

            # 2b — targeted Stage-2 verification: ground the audit in the chunks where
            # Stage 1 actually found evidence, rather than a blind first-STAGE2_DOC_CHARS
            # prefix (which can't see late provisions in long documents). Fall back to
            # the prefix when no chunk produced a substantive answer for this batch.
            hit_texts = [
                ct for ct, cs in zip(chunk_texts_used, chunk_s1_results)
                if any(cs.get(q.qid)
                       and _normalize_answer(cs[q.qid].get("answer")) not in _MISSING_ANSWERS
                       for q in batch_qs)
            ]
            stage2_doc_local = ""
            for ct in hit_texts:
                if len(stage2_doc_local) + len(ct) > STAGE2_DOC_CHARS:
                    break
                stage2_doc_local += ct + "\n\n"
            stage2_doc_local = stage2_doc_local or stage2_doc

            try:
                s2 = _call_stage2(client, batch_qs, s1, cat, stage2_doc_local)
            except Exception as exc:
                print(f"      {cat} batch {idx}: stage2 ERROR {exc} — using stage 1 result")
                s2 = {}

            if not chunk_s1_results and not s2:
                batches_failed += 1

            # Merge each question's Stage-1 and Stage-2 records atomically so the
            # answer and its evidence can never disagree, and Stage 2 cannot blank
            # a substantive, document-supported Stage-1 answer.
            result = {
                q.qid: _coherent_merge(
                    s1.get(q.qid, {}), s2.get(q.qid, {}), full_text_norm,
                )
                for q in batch_qs
            }

            # L-A/L-C — recover false negatives before this fresh subbatch is cached: a
            # not_discussed OR a bare "no" that contradicts the model's own on-topic quote,
            # or whose codebook keywords occur in the document, is re-asked on focused
            # windows and adopted only if the re-read yields a different, supported answer.
            if chunk_s1_results:
                _recover_missed_answers(
                    client, doc, batch_qs, cat, result, full_text, full_text_norm,
                )

            # Only persist a result that came from a real call; caching a wholly
            # failed subbatch would lock its questions in as not_discussed forever.
            if chunk_s1_results or s2:
                final_cache.write_text(
                    json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8",
                )
                time.sleep(0.4)

        merged.update(result)
        n = len(batch_qs)
        section_note = f" ({n_chunks} sections)" if n_chunks > 1 else ""
        print(f"      {cat} batch {idx}: {n} question{'s' if n != 1 else ''} done{section_note}")

    # L-A/L-C (cache path) — run false-negative recovery for subbatches that were loaded from
    # cache and therefore skipped the in-loop recovery. Fresh subbatches already recovered above
    # (and cached the recovered result); this catches resumed/re-run docs so recovery is applied
    # exactly once per subbatch regardless of cache state.
    n_rec_cached = 0
    for cat, batch_qs in recovery_pending:
        n_rec_cached += _recover_missed_answers(
            client, doc, batch_qs, cat, merged, full_text, full_text_norm,
        )
    if n_rec_cached:
        print(f"      recovery (cache-loaded subbatches) recovered {n_rec_cached} answer(s)")

    # L-B — cross-question reconciliation over the full document: recover a
    # not_discussed/"no" whose sibling question already quoted the provision (siblings
    # split across separate subbatches can't see each other). Runs on every invocation,
    # including cache-loaded subbatches, so it improves prior results without a full re-run.
    n_recon = _reconcile_across_questions(client, doc, subbatches, merged, full_text, full_text_norm)
    if n_recon:
        print(f"      cross-question reconciliation recovered {n_recon} answer(s)")

    return merged, batches_failed, len(subbatches)


# ── output writers ────────────────────────────────────────────────────────────

def _write_outputs(
    questions: list[Question],
    results: list[tuple[Document, dict, dict[str, dict]]],
) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    meta_fields = [
        "document_id", "file_name", "district_name", "state",
        "document_type", "bargaining_unit", "start_year", "end_year",
        "effective_dates", "school_years_covered", "union_name",
        "source_document_notes",
    ]
    wide_fields = meta_fields + [
        f"{q.qid}_{suffix}"
        for q in questions
        for suffix in ("answer", "evidence", "page", "confidence")
    ]
    log_fields = [
        "document_id", "file_name", "Question ID", "topic category",
        "question", "answer", "evidence", "page number", "confidence", "coder notes",
    ]

    wide_rows: list[dict] = []
    log_rows: list[dict] = []

    for doc, metadata, coded in results:
        wide = dict(metadata)
        for q in questions:
            cell = {**_FALLBACK, **coded.get(q.qid, {})}
            cell["answer"] = _normalize_answer(cell["answer"]) or "not_discussed"
            wide[f"{q.qid}_answer"] = cell["answer"]
            wide[f"{q.qid}_evidence"] = cell["evidence"]
            wide[f"{q.qid}_page"] = cell["page"]
            wide[f"{q.qid}_confidence"] = cell["confidence"]
            log_rows.append({
                "document_id":    metadata["document_id"],
                "file_name":      metadata["file_name"],
                "Question ID":    q.qid,
                "topic category": q.topic,
                "question":       q.question,
                "answer":         cell["answer"],
                "evidence":       cell["evidence"],
                "page number":    cell["page"],
                "confidence":     cell["confidence"],
                "coder notes":    cell.get("coder_notes", ""),
            })
        wide_rows.append(wide)

    main_path = OUT_DIR / "llm_main_dataset.csv"
    log_path  = OUT_DIR / "llm_coding_log.csv"

    with main_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=wide_fields)
        w.writeheader()
        w.writerows(wide_rows)

    with log_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=log_fields)
        w.writeheader()
        w.writerows(log_rows)

    print(f"  {len(wide_rows)} document rows  → {main_path}")
    print(f"  {len(log_rows)} log rows        → {log_path}")


# ── entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--max-docs", type=int, default=MAX_DOCS,
        help="Limit number of documents processed from the full sample",
    )
    parser.add_argument(
        "--doc", action="append", metavar="DISTRICT|FILE.pdf",
        help="Process specific document(s) instead of the full sample. May be repeated.",
    )
    args = parser.parse_args()

    # Register the request-hash cache + telemetry sink. som_client only records calls when
    # a sink is registered, so this must happen at every entry point or a real run produces
    # no cache and no telemetry (which is how the first v11 smoke test ran).
    try:
        import store
        store.get_store().start_run(notes="llm_extract")
    except Exception as exc:      # never let instrumentation stop a run
        print(f"  [store] telemetry unavailable: {exc}")


    client = get_client()

    print("Reading codebook and sample ...")
    questions = read_codebook()
    if args.doc:
        sample = [tuple(d.split("|", 1)) for d in args.doc]
    else:
        full_sample = read_sample()
        sample = full_sample[:args.max_docs] if args.max_docs else full_sample
    docs       = load_documents(sample)
    batches    = group_by_category(questions)
    subbatches = split_into_subbatches(batches)

    print(
        f"  {len(questions)} questions | {len(batches)} categories | "
        f"{len(subbatches)} sub-batches (max {MAX_QUESTIONS_PER_BATCH}/batch) | "
        f"{len(docs)} document(s)"
    )

    CACHE_DIR.mkdir(exist_ok=True)

    results: list[tuple[Document, dict, dict[str, dict]]] = []
    errors:  list[str] = []

    for i, doc in enumerate(docs, start=1):
        metadata = build_metadata(doc)
        print(f"[{i:>2}/{len(docs)}] {doc.file_name} ...")

        try:
            coded, batches_failed, total_batches = _process_document(client, doc, subbatches)
            results.append((doc, metadata, coded))
            if batches_failed:
                print(f"      {batches_failed}/{total_batches} sub-batches failed (no model answer)")
        except Exception as exc:
            print(f"  ERROR ({exc}) — document skipped, answers will be missing")
            errors.append(doc.file_name)
            results.append((doc, metadata, {}))

    print("\nWriting outputs ...")
    _write_outputs(questions, results)

    if errors:
        print(f"\nDocuments with errors ({len(errors)}):")
        for name in errors:
            print(f"  - {name}")
        print("Re-run to retry; successful sub-batches are cached.")


if __name__ == "__main__":
    main()
