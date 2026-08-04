#!/usr/bin/env python3
"""Score worker rights and responsibilities in district employment contracts.

Operationalizes a version of the clause-classification framework in Arold, Ash,
MacLeod & Naidu, "Worker Rights in Collective Bargaining" (2025), Section 3: every
clause is classified by its grammatical subject, modal verb, negation, voice, and
verb-lexical-category into one of Hohfeld's four relations (obligation, prohibition,
permission, right), following the paper's Table A.3 logic. The paper uses spaCy
dependency parsing plus fixed verb dictionaries for this; here an LLM does the
linguistic feature extraction (subject, modal, negation, voice, verb category) per
clause, and this script's classify_statement_type()/modal_strength_for() apply the
same Table A.3-style rules deterministically in Python — kept separate from the LLM
call so the classification rules and modal weights can be audited or changed without
re-querying the API. The LLM also gives its own holistic statement-type judgment per
clause (llm_judgment) purely as a cross-check against the deterministic rule.

Two extensions beyond the paper:

1. Modal-strength weighting. The paper uses modal restrictiveness (shall/must vs.
   may/can) only as a binary input to classification; here each clause additionally
   gets a continuous weight (MODAL_STRENGTH below) so a "shall" entitlement counts
   more than a discretionary "may" one, instead of every clause of a given type
   counting equally.

2. Correlative (protected_party) scoring. Every clause is read for who the acting
   party is (acting_party: worker/management/other) AND who actually benefits
   (protected_party: worker/management — binary, always computed, for every clause
   type). Obligations and prohibitions credit the acting party's responsibilities.
   Rights and permissions credit the protected party's rights. Each clause
   contributes to exactly one bucket so the four totals sum to total_weight.

KNOWN CAVEAT: clause-level counting (here and in the original paper) does not
deduplicate semantically identical entitlements restated in different grammatical
framings. If a contract states the same benefit twice — once as "the district shall
provide health insurance" (a management obligation, crediting a correlative worker
right) and again elsewhere as "teachers shall receive health insurance" (a direct
worker right) — both clauses are counted, so the worker-rights score double-counts
that single underlying entitlement. This is a known limitation of clause-counting
methods in general, not something this script attempts to resolve.

Outputs:
  output/rights_score_long.csv     - one row per extracted clause
  output/rights_score_summary.csv  - one row per document with aggregated scores

Per-document-chunk results are cached in cache/rights_score_cache/ as JSON so an
interrupted run can be resumed without re-querying the API.

Usage:
    python3 rights_score.py                              # run the full 40-doc sample
    python3 rights_score.py --max-docs 2                  # limit for a quick test
    python3 rights_score.py --doc "Davis School District|Davis_2019-2020.pdf"
    python3 rights_score.py --district "Granite School District" --file "professional_agreement_with_gea_2020_2023.pdf"
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils import OUT_DIR, PDF_ROOT, TEXT_DIR, WORK, extract_text, norm_ws, quote_present
from som_client import (
    MAX_TOKENS, MODEL, budgeted_max_tokens, create_with_retries, get_client,
    reasoning_kwargs,
)
from salary_schedule import MAIN_DATASET, document_id_for

CACHE_DIR = WORK / "cache" / "rights_score_cache"

# 3000/400 was chosen when som_client believed the context window was 32k tokens and
# clamped max_tokens to 16000, so a dense chunk's clause JSON truncated. The real window is
# 131k (see som_client), and a 3000-char chunk uses ~0.4% of it: the median 253k-char
# document cost ~96 extraction calls and the largest ~456. 12000 is a 4x call reduction and
# is deliberately a middle step — raise toward 20000 only with clause recall measured at
# each step, since larger chunks trade call count against attention dilution.
CHUNK_SIZE = int(os.environ.get("RIGHTS_CHUNK_SIZE", "12000"))
CHUNK_OVERLAP = int(os.environ.get("RIGHTS_CHUNK_OVERLAP", "1200"))
# For extremely long documents, optionally cap how many (slow) extraction chunks a
# single document is broken into by enlarging each chunk. 0 disables the cap (fixed
# CHUNK_SIZE — the default, so normal-length docs are unaffected). When set, the doc
# is split into at most this many larger pieces and the per-chunk clause results are
# stitched back together by the existing quote-dedup — same accuracy machinery, just
# fewer/larger pieces so the number of API calls stays bounded on huge documents.
RIGHTS_MAX_CHUNKS = int(os.environ.get("RIGHTS_MAX_CHUNKS", "0"))
# The SOM model is a reasoning model (long chain-of-thought per call), so a document's
# chunks are sent as several concurrent API calls. ThreadPoolExecutor.map yields
# results in input order, so clause order (and the overlap-dedup below) is identical
# to sequential processing. Override with the RIGHTS_CONCURRENCY env var.
MAX_CONCURRENCY = int(os.environ.get("RIGHTS_CONCURRENCY", "8"))

# Clauses are classified in a second LLM pass; this many per classification call.
CLASSIFY_BATCH_SIZE = int(os.environ.get("RIGHTS_CLASSIFY_BATCH", "30"))

# Extraction is a mechanical linguistic-feature task (copy the clause, tag its modal,
# voice, and acting party), so the slow chain-of-thought is reserved for classification.
#   "off" (default) — disable thinking on extraction. Measured ~10x faster per call; the
#                     chat-template switch is confirmed working against api.som.chat
#                     (reasoning_tokens drops 221 -> 0 on a control prompt).
#   "on"  — the previous default. Set RIGHTS_EXTRACT_REASONING=on to A/B clause recall.
# Only the extraction call is affected; classification and re-verification, which are
# genuine judgment calls, always keep reasoning on.
EXTRACT_REASONING = os.environ.get("RIGHTS_EXTRACT_REASONING", "off").strip().lower()


def _reasoning_off_kwargs() -> dict:
    """extra_body that disables the reasoning model's chain-of-thought, or {} when
    reasoning is left on. Delegates to som_client.reasoning_kwargs so the exact vLLM
    parameter lives in exactly one place."""
    if EXTRACT_REASONING == "off":
        return {"extra_body": reasoning_kwargs(False)}
    return {}

# ── modal strength + classification tables (the Table A.3 / verb-lexicon analogue) ──

MODAL_STRENGTH = {
    "must": 1.00,
    "shall": 1.00,
    "will": 0.90,
    "should": 0.70,
    "ought": 0.70,
    "need": 0.70,
    "may": 0.30,
    "can": 0.30,
    "could": 0.20,
    "might": 0.10,
}
RESTRICTIVE_MODALS = {"must", "shall", "will", "should", "ought", "need"}
PERMISSIVE_MODALS = {"may", "can", "could", "might"}
NON_MODAL_WEIGHT = 0.85  # e.g. "is entitled to", "is required to" — no modal verb present

SPECIAL_VERB_CATEGORIES = {
    "obligation_verb", "prohibition_verb", "permission_verb", "rights_active", "rights_passive",
}


def modal_strength_for(modal: str | None, verb_category: str) -> float:
    if modal and modal in MODAL_STRENGTH:
        return MODAL_STRENGTH[modal]
    if verb_category in SPECIAL_VERB_CATEGORIES:
        return NON_MODAL_WEIGHT
    return 0.0


def classify_statement_type(modal: str | None, negation: bool, verb_category: str) -> str:
    """Table A.3 analogue: combine negation + modal class + verb-lexical-category
    into one of obligation/prohibition/permission/right, or "other" if none fit."""
    modal_class = (
        "restrictive" if modal in RESTRICTIVE_MODALS else
        "permissive" if modal in PERMISSIVE_MODALS else
        "none"
    )
    if not negation:
        if verb_category == "obligation_verb":
            return "obligation"
        if verb_category == "prohibition_verb":
            return "prohibition"
        if verb_category == "permission_verb":
            return "permission"
        if verb_category in ("rights_active", "rights_passive"):
            return "right"
        if verb_category == "plain":
            if modal_class == "restrictive":
                return "obligation"
            if modal_class == "permissive":
                return "permission"
        return "other"
    else:
        if verb_category == "obligation_verb":
            return "right"        # "may not be required" — relief from a duty is a right
        if verb_category == "prohibition_verb":
            return "permission"   # "shall not be prohibited" — double negative
        if verb_category == "permission_verb":
            return "prohibition"  # "shall not be allowed"
        if verb_category == "plain":
            return "prohibition"  # "shall not exceed"
        return "other"            # negated rights verb ("shall not receive") — paper's
                                   # table doesn't define this case; leave unclassified
                                   # rather than guess.


# ── appendix/exhibit exclusion ───────────────────────────────────────────────────

# Mirrors the paper's exclusion of "wage schedules, exhibits, appendices, and other
# miscellaneous materials" before clause extraction. Heuristic, page-granular: once
# an APPENDIX/EXHIBIT-style heading is seen, treat subsequent pages as excluded until
# the next ARTICLE-level heading reappears (or end of document).
APPENDIX_RE = re.compile(r"^\s*(APPENDIX|Appendix|EXHIBIT|Exhibit|ADDENDUM|Addendum)\b", re.M)
# Reset on the next ARTICLE heading — Roman numeral, digit, OR spelled-out ordinal.
# Some contracts write "Article One", "Article Two", …; requiring [IVXLC0-9] alone
# meant the appendix-exclusion never reset for those docs and blanked the whole body.
_ARTICLE_ORDINAL = ("one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
                    "thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|"
                    "twenty|thirty|forty|fifty")
ARTICLE_RE = re.compile(
    r"^\s*ARTICLE\s+([IVXLC0-9]+|(?:%s))\b" % _ARTICLE_ORDINAL, re.M | re.I)


def exclude_appendices(pages: list[str]) -> list[str]:
    kept: list[str] = []
    in_appendix = False
    for page in pages:
        if APPENDIX_RE.search(page):
            in_appendix = True
        elif ARTICLE_RE.search(page):
            in_appendix = False
        kept.append("" if in_appendix else page)
    # Safety backstop: this is a coarse heuristic. If it would blank more than 60% of
    # the document text it has clearly misfired (e.g. an "Appendix A" line in the table
    # of contents tripped it and no recognized ARTICLE heading reset it — Broward 2011).
    # Fall back to the full text rather than silently dropping most of the contract.
    orig = sum(len(p) for p in pages)
    if orig and sum(len(p) for p in kept) < 0.4 * orig:
        return list(pages)
    return kept


def chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    if not text:
        return []
    n = len(text)
    # For extremely long docs, enlarge each chunk so the piece count (and thus the
    # number of slow extraction calls) stays under RIGHTS_MAX_CHUNKS. Normal-length
    # docs never trip this. Overlap is preserved, so the quote-dedup still stitches
    # boundary-spanning clauses correctly.
    if RIGHTS_MAX_CHUNKS and n > RIGHTS_MAX_CHUNKS * (size - overlap):
        size = -(-n // RIGHTS_MAX_CHUNKS) + overlap  # ceil(n / cap) + overlap
    chunks: list[str] = []
    start = 0
    while start < n:
        end = min(start + size, n)
        chunks.append(text[start:end])
        if end >= n:
            break
        start = end - overlap
    return chunks


# ── prompt ────────────────────────────────────────────────────────────────────────

RIGHTS_SYSTEM_PROMPT = """\
You are extracting legally meaningful clauses from a U.S. public school district \
employment contract (collective bargaining agreement, handbook, or policy manual), \
following the legal framework of Hohfeld (1913): every clause assigns either a RIGHT, \
an OBLIGATION (duty to act), a PROHIBITION (duty not to act), or a PERMISSION \
(discretion to act or not) to whichever party is its grammatical subject.

You will be given a chunk of contract text. Find every clause that fits a \
Subject-Verb-Object pattern describing a right, duty, or permission — skip \
preambles, definitions, recitals, and purely procedural/structural text with no real \
entitlement or duty content. If a sentence contains more than one independent clause \
(joined by "and," "but," "however," or a semicolon), extract each as a separate \
entry. If a clause's quote is clearly truncated at the very start of this chunk (no \
complete sentence), skip it — it will be captured from a later chunk containing its \
true beginning.

SKIP these clause types even if they are grammatically complete sentences:
  - Recognition/preamble clauses that merely acknowledge an existing legal status \
    (e.g. "The Board recognizes the Association as the exclusive representative...").
  - Descriptive-summary sentences that introduce a policy without themselves \
    granting anything (e.g. "The Sick Leave Policy provides full pay in cases of illness").
  - Administrative-timing rules about when something takes effect, not whether it \
    exists (e.g. "Insurance coverage shall be effective the first day of the month...").
  - Policy cross-references with no operative content (e.g. "...refer to Board Policy").
  - Definitional exclusions or classifications (e.g. "No benefit shall be considered \
    as salary or pay", "Payment for extended contracts shall be considered compensation \
    for extra duty") — these define terms, they do not grant or restrict anything.

For each clause, identify:

1. quote — the verbatim clause text (the full sentence or independent clause, not a
   paraphrase).
2. subject_text — the verbatim grammatical subject (e.g. "the Board", "a teacher").
3. acting_party — which side the subject belongs to:
   - "worker": teacher, employee, union, union member, association, bargaining unit
   - "management": school, district, principal, superintendent, board, state,
     employer, administration
   - "other": neither (e.g. an arbitrator, "the parties" acting jointly, students)
4. protected_party — which side ULTIMATELY BENEFITS from this clause, regardless of
   who the grammatical subject is. Binary: "worker" or "management". Usually matches
   acting_party's natural beneficiary, but watch for divergence:
   - A management OBLIGATION or PROHIBITION usually protects workers (e.g. "the
     district shall not assign more than 3 hours of duty-free lunch supervision to
     teachers" — acting_party=management, protected_party=worker).
   - A worker OBLIGATION or PROHIBITION usually protects management (e.g. "teachers
     shall not leave the building during instructional hours without permission" —
     acting_party=worker, protected_party=management).
   - A clause that VOIDS or BARS an action harmful to a named worker class protects
     the WORKER, even when its acting_party is "other" or a rule (e.g. "no exemption
     shall exist if it results in surplusing of a tenured employee by a non-tenured
     employee" — the carve-out shields the tenured employee => protected_party=worker).
   - A discretionary PERMISSION held by one side can still ultimately benefit the
     other (e.g. "the district may grant additional leave beyond the contractual
     maximum at its discretion" — acting_party=management, protected_party=worker).
   - Watch for clauses whose subject is an excluded management classification
     (principal, administrator, supervisor): a right or permission held by a
     principal is a MANAGEMENT right, not a worker right, even if it sounds like an
     entitlement (e.g. "school principals are entitled to 6 weeks of vacation
     annually" — acting_party=management, protected_party=management).
   - PASSIVE-VOICE CLAUSES (e.g. "teachers shall be notified", "employees are
     entitled to receive X", "the grievance shall be reviewed"): the grammatical
     subject is the recipient, not the actor. Set acting_party to the implicit
     agent (usually management for duties imposed on the district) and
     protected_party to whoever benefits from the clause.
   - IMPERSONAL OR JOINT-SUBJECT CLAUSES (e.g. "the parties agree", "it is agreed
     that", "this agreement provides"): determine protected_party by asking — if
     this clause were removed from the contract, whose position would weaken? That
     party is the protected_party.
5. modal — the literal modal verb, lowercased: must, shall, will, should, ought,
   need, may, can, could, might — or null if no modal verb is present.
6. negation — true if the verb phrase is negated ("shall not", "may not", "is not
   required to"), false otherwise.
7. voice — "active" or "passive".
8. verb_lexical_category — classify the main verb phrase as one of:
   - "obligation_verb": be required, be expected, be compelled, be obliged,
     be obligated, have to, ought to, or a clear paraphrase
   - "prohibition_verb": be prohibited, be forbidden, be banned, be barred,
     be restricted, be proscribed, or a clear paraphrase
   - "permission_verb": be allowed, be permitted, be authorized, or a clear paraphrase
   - "rights_active": receive, gain, earn (the subject actively gets something)
   - "rights_passive": entitled, given, offered, reimbursed, paid, granted, provided,
     compensated, guaranteed, hired, trained, supplied, protected, covered, informed,
     notified, selected, awarded, or a clear paraphrase
   - "plain": any other ordinary action verb (e.g. "shall provide", "shall notify",
     "shall not exceed", "may request")
9. llm_judgment — your own holistic read of the clause type: "obligation",
   "prohibition", "permission", "right", or "other". This is a cross-check against a
   separate rule-based classification — answer from your own understanding of the
   clause, not by reverse-engineering a rule. Anchors:
   - Use "obligation" when a party is required/compelled to do something, including
     management obligations that happen to benefit workers (e.g. "the district shall
     provide X to teachers" is an obligation, not a right — that workers benefit is
     captured by protected_party, not by changing the judgment to "right").
   - Use "right" only when the grammatical subject itself explicitly holds or is
     granted a right (e.g. "the teacher shall have the right to...", "teachers are
     entitled to receive...", "employees may request...").
   - Use "prohibition" for "shall not" / "may not" clauses where the modal clearly
     restricts action; do not call a negated obligation ("shall not be required to")
     a prohibition — it is a right/relief from a duty.
   - Use "other" for clauses with no modal and no clear entitlement or duty (e.g.
     pure status statements, recitals, or definitions that slipped through).
10. topic — the single best-fitting subject-matter category, one of: "benefits",
    "class_size", "compensation", "discipline", "evaluation", "job_security",
    "layoffs", "leave", "professional_development", "safety_and_working_conditions",
    "seniority", "teacher_rights_and_conduct", "transfers", "workload", "other".
    Extra-duty pay, noon/lunch supervision pay, coaching stipends, and
    experience/step credit for salary placement are "compensation". Occasional/
    substitute-teacher leave proration and school-calendar-aligned holidays are
    "leave". Grievance and appeal procedures are "discipline".
11. notes — anything genuinely ambiguous about the classification, or empty string.

Return ONLY a valid JSON object, no markdown fences:
{
  "clauses": [
    {"quote": "...", "subject_text": "...", "acting_party": "worker|management|other",
     "protected_party": "worker|management", "modal": "shall" or null,
     "negation": true|false, "voice": "active|passive",
     "verb_lexical_category": "...", "llm_judgment": "...", "topic": "...", "notes": "..."}
  ]
}

If this chunk contains no clauses worth extracting (e.g. it is entirely a wage table,
signature page, or table of contents), return {"clauses": []}.\
"""


# RIGHTS_SYSTEM_PROMPT above does extraction AND classification in one call and is
# kept intact for rights_score_noapi.py, which still imports it. The API path below
# splits that work into two prompts: EXTRACT_SYSTEM_PROMPT reports only the mechanical
# linguistic features (flat, shallow JSON, reasoning off-able), and
# CLASSIFY_SYSTEM_PROMPT does the interpretive "thinking" (who benefits, topic,
# holistic type) over the already-extracted clauses.

EXTRACT_SYSTEM_PROMPT = """\
You are extracting legally meaningful clauses from a U.S. public school district \
employment contract (collective bargaining agreement, handbook, or policy manual), \
following the legal framework of Hohfeld (1913): every clause assigns either a RIGHT, \
an OBLIGATION (duty to act), a PROHIBITION (duty not to act), or a PERMISSION \
(discretion to act or not) to whichever party is its grammatical subject.

You will be given a chunk of contract text. Find every clause that fits a \
Subject-Verb-Object pattern describing a right, duty, or permission — skip \
preambles, definitions, recitals, and purely procedural/structural text with no real \
entitlement or duty content. If a sentence contains more than one independent clause \
(joined by "and," "but," "however," or a semicolon), extract each as a separate \
entry. If a clause's quote is clearly truncated at the very start of this chunk (no \
complete sentence), skip it — it will be captured from a later chunk containing its \
true beginning.

SKIP these clause types even if they are grammatically complete sentences:
  - Recognition/preamble clauses that merely acknowledge an existing legal status \
    (e.g. "The Board recognizes the Association as the exclusive representative...").
  - Descriptive-summary sentences that introduce a policy without themselves \
    granting anything (e.g. "The Sick Leave Policy provides full pay in cases of illness").
  - Administrative-timing rules about when something takes effect, not whether it \
    exists (e.g. "Insurance coverage shall be effective the first day of the month...").
  - Policy cross-references with no operative content (e.g. "...refer to Board Policy").
  - Definitional exclusions or classifications (e.g. "No benefit shall be considered \
    as salary or pay", "Payment for extended contracts shall be considered compensation \
    for extra duty") — these define terms, they do not grant or restrict anything.

This is the EXTRACTION step: report only the literal, mechanical linguistic features \
of each clause. Do NOT judge who ultimately benefits, the clause's subject-matter \
topic, or its overall Hohfeldian type — a separate classification step does that. For \
each clause, identify:

1. quote — the verbatim clause text (the full sentence or independent clause, not a
   paraphrase).
2. subject_text — the verbatim grammatical subject (e.g. "the Board", "a teacher").
3. acting_party — which side the ACTOR belongs to (the party that carries out the
   verb, which is NOT always the grammatical subject — see the passive rule below):
   - "worker": teacher, employee, union, union member, association, bargaining unit
   - "management": school, district, principal, superintendent, board, state,
     employer, administration
   - "other": neither (e.g. an arbitrator, "the parties" acting jointly, students)
   - INANIMATE / IMPERSONAL SUBJECT: if the actor is a document or thing, not a
     person or party (e.g. "This schedule shall replace...", "This Agreement provides...",
     "Section 5 governs...", "This policy applies..."), set acting_party to "other" —
     an inanimate subject performs no party's action.
   - PASSIVE VOICE (when voice is "passive", e.g. "teachers shall be notified",
     "employees must be relieved of duty", "the grievance shall be reviewed"): the
     grammatical subject is the RECIPIENT, not the actor. Set acting_party to the
     IMPLICIT AGENT. EXCEPTION FIRST: if the clause names its agent in an explicit
     "by <X>" phrase (e.g. "meetings may be held on school property BY FACULTY MEMBERS",
     "the report shall be prepared BY THE PRINCIPAL"), the actor is <X> — use <X>'s side
     (faculty/teachers/union => worker; principal/board/district => management). ONLY when
     there is no "by <agent>" phrase, fall back to the implicit agent — usually
     "management" for duties imposed on the district — NOT the subject's side.
4. modal — the literal modal verb governing the clause's OPERATIVE (main) deontic verb,
   lowercased: must, shall, will, should, ought, need, may, can, could, might — or null
   if none. Take the modal of the MAIN commitment, NOT a modal buried inside a
   parenthetical or relative clause (e.g. in "BPS agrees to maintain staffing (which may
   be contained in the appendix)", the operative verb is "agrees to maintain" — modal is
   null/`shall`-like, NOT the parenthetical "may").
5. negation — true if the clause's OPERATIVE deontic verb is negated, false otherwise.
   This includes verb-phrase negation of the main verb ("shall not", "may not", "is not
   required to") AND subject-side quantifier negation ("No teacher may...", "No waivers
   may be requested", "Nothing shall impede...", "Neither party shall..."). It does NOT
   include a "not" that sits only in a SUBJECT QUALIFIER or relative clause while the
   operative verb stays affirmative (e.g. "Teachers NOT afforded a duty-free lunch shall
   be paid 1/5 of the rate" — the operative "shall be paid" is affirmative => negation=false).
   Also, "No later than / No fewer than / No more than / No greater than X" is an
   affirmative floor/ceiling, NOT negation.
6. voice — "active" or "passive". Decide from the OPERATIVE verb only:
   - PASSIVE = a form of "be"/"get" + a PAST PARTICIPLE, where the grammatical subject
     RECEIVES the action. A modal and/or negation do NOT change this — "shall be notified",
     "shall not be employed", "shall not be required", "must be relieved", "may be
     reassigned", and copular "is not impacted / abrogated / diminished / affected" are ALL
     passive. Do not call a clause active just because it has "shall"/"will"/"not".
   - ACTIVE = the subject performs the verb: "the teacher receives", "the Board shall
     provide", and relative-clause verbs like "an employee who left" / "who will be
     returning" (the subject does the leaving/returning) are active.
   - Judge the MAIN clause verb, not a subordinate one; when the main predicate is
     be+participle, it is passive regardless of surrounding words.
7. verb_lexical_category — classify the main verb phrase as one of:
   - "obligation_verb": be required, be expected, be compelled, be obliged,
     be obligated, have to, ought to, or a clear paraphrase
   - "prohibition_verb": be prohibited, be forbidden, be banned, be barred,
     be restricted, be proscribed, or a clear paraphrase
   - "permission_verb": be allowed, be permitted, be authorized, or a clear paraphrase
   - "rights_active": receive, gain, earn (the subject actively gets something)
   - "rights_passive": entitled, given, offered, reimbursed, paid, granted, provided,
     compensated, guaranteed, hired, trained, supplied, protected, covered, informed,
     notified, selected, awarded, or a clear paraphrase
   - "plain": any other ordinary action verb (e.g. "shall provide", "shall notify",
     "shall not exceed", "may request")
8. notes — anything genuinely ambiguous about the clause, or empty string.

Return ONLY a valid JSON object, no markdown fences:
{
  "clauses": [
    {"quote": "...", "subject_text": "...", "acting_party": "worker|management|other",
     "modal": "shall" or null, "negation": true|false, "voice": "active|passive",
     "verb_lexical_category": "...", "notes": "..."}
  ]
}

If this chunk contains no clauses worth extracting (e.g. it is entirely a wage table,
signature page, or table of contents), return {"clauses": []}.\
"""


CLASSIFY_SYSTEM_PROMPT = """\
You are classifying already-extracted clauses from a U.S. public school district \
employment contract, following Hohfeld (1913). Each input clause already has its \
verbatim quote, grammatical subject, acting party, and modal/negation/voice/verb \
features extracted, and a rule-based statement_type (obligation / prohibition / \
permission / right / other) already computed from those features and given to you. \
Your job is the interpretive judgment the mechanical extraction could not make.

You will receive a JSON array of clauses, each with an "index". For each clause return \
three fields, keyed by that same index:

1. protected_party — which side ULTIMATELY BENEFITS from this clause, regardless of
   who the grammatical subject is. Binary: "worker" or "management".
   DO NOT DEFAULT protected_party TO THE ACTING PARTY'S SIDE — that is the most common
   error. Instead ask WHO THE CLAUSE ACTS UPON OR FOR: the party whose position is
   strengthened, shielded, or served. When MANAGEMENT is the actor (pays, prorates,
   provides, assigns, evaluates, notifies) and the effect lands on teachers/employees,
   protected_party is WORKER, not management (e.g. "the district shall prorate the
   teacher's salary", "the District shall pay employees for X" — acting_party=management,
   protected_party=worker). A right or permission a WORKER may exercise (e.g. "a teacher
   may request assistance") protects the WORKER even though exercising it is the worker's
   own act. Match protected_party to the beneficiary, not the subject/actor. Then watch for:
   - A management OBLIGATION or PROHIBITION usually protects workers (e.g. "the
     district shall not assign more than 3 hours of duty-free lunch supervision to
     teachers" — acting_party=management, protected_party=worker).
   - A worker OBLIGATION or PROHIBITION usually protects management (e.g. "teachers
     shall not leave the building during instructional hours without permission" —
     acting_party=worker, protected_party=management).
   - A clause that VOIDS or BARS an action harmful to a named worker class protects
     the WORKER, even when its acting_party is "other" or a rule (e.g. "no exemption
     shall exist if it results in surplusing of a tenured employee by a non-tenured
     employee" — the carve-out shields the tenured employee => protected_party=worker).
   - A discretionary PERMISSION held by one side can still ultimately benefit the
     other (e.g. "the district may grant additional leave beyond the contractual
     maximum at its discretion" — acting_party=management, protected_party=worker).
   - Watch for clauses whose subject is an excluded management classification
     (principal, administrator, supervisor): a right or permission held by a
     principal is a MANAGEMENT right, not a worker right, even if it sounds like an
     entitlement (e.g. "school principals are entitled to 6 weeks of vacation
     annually" — acting_party=management, protected_party=management).
   - PASSIVE-VOICE CLAUSES (e.g. "teachers shall be notified", "employees are
     entitled to receive X", "the grievance shall be reviewed"): the grammatical
     subject is the recipient, not the actor. The implicit agent is usually
     management; set protected_party to whoever benefits from the clause.
   - IMPERSONAL OR JOINT-SUBJECT CLAUSES (e.g. "the parties agree", "it is agreed
     that", "this agreement provides"): determine protected_party by asking — if
     this clause were removed from the contract, whose position would weaken? That
     party is the protected_party.
2. llm_judgment — your own holistic read of the clause type: "obligation",
   "prohibition", "permission", "right", or "other". This is an independent cross-check
   against the given rule-based statement_type — answer from your own understanding of
   the clause, not by copying statement_type. Anchors:
   - Use "obligation" when a party is required/compelled to do something, including
     management obligations that happen to benefit workers (e.g. "the district shall
     provide X to teachers" is an obligation, not a right — that workers benefit is
     captured by protected_party, not by changing the judgment to "right").
   - Use "right" only when the grammatical subject itself explicitly holds or is
     granted a right (e.g. "the teacher shall have the right to...", "teachers are
     entitled to receive...", "employees may request...").
   - Use "prohibition" for "shall not" / "may not" clauses where the modal clearly
     restricts action; do not call a negated obligation ("shall not be required to")
     a prohibition — it is a right/relief from a duty.
   - Use "other" for clauses with no modal and no clear entitlement or duty (e.g.
     pure status statements, recitals, or definitions that slipped through).
3. topic — the single best-fitting subject-matter category, one of: "benefits",
   "class_size", "compensation", "discipline", "evaluation", "job_security",
   "layoffs", "leave", "professional_development", "safety_and_working_conditions",
   "seniority", "teacher_rights_and_conduct", "transfers", "workload", "other".
   Extra-duty pay, noon/lunch supervision pay, coaching stipends, and
   experience/step credit for salary placement are "compensation". Occasional/
   substitute-teacher leave proration and school-calendar-aligned holidays are
   "leave". Grievance and appeal procedures are "discipline".

Return ONLY a valid JSON object, no markdown fences:
{
  "classified": [
    {"index": 0, "protected_party": "worker|management", "llm_judgment": "...", "topic": "..."}
  ]
}
Return one entry for every input clause, preserving its index.\
"""


REVERIFY_SYSTEM_PROMPT = """\
You are re-checking a SMALL set of already-classified contract clauses that an automated screen
flagged as error-prone on two specific features. Scrutinize ONLY these and correct them if
wrong. For each clause you get its verbatim quote plus its current tags. Re-decide, from the
quote alone:

1. voice — "active" or "passive". PASSIVE = the operative verb is a form of be/get + a PAST
   PARTICIPLE and the subject RECEIVES the action; a modal and/or "not" do NOT make it active
   ("shall be notified", "shall not be employed", "shall not be required", "must be relieved",
   "is not impacted / abrogated / diminished" are ALL passive). ACTIVE = the subject performs
   the verb ("the teacher receives", "an employee who left / who will be returning", "the Board
   shall provide").
2. acting_party — "worker" | "management" | "other" (the party carrying out the verb). On a
   PASSIVE clause the grammatical subject is the RECIPIENT, not the actor: use the "by <X>"
   agent if named, else the implicit agent (usually management for duties imposed on the
   district). An inanimate/impersonal subject ("this Agreement", "Section 5") is "other".
3. protected_party — "worker" | "management": WHO ULTIMATELY BENEFITS, i.e. whom the clause
   acts upon or for. DO NOT default this to the acting party. When management is the actor
   (pays, prorates, provides, assigns, evaluates) and the effect lands on teachers/employees,
   protected_party is WORKER. A management obligation/prohibition usually protects the worker;
   a worker obligation/prohibition usually protects management; a right/permission protects
   whoever holds or exercises it.
4. llm_judgment — "obligation" | "prohibition" | "permission" | "right" | "other": your own
   holistic read (a management duty that happens to benefit workers is an "obligation", not a
   "right").

Return ONLY a valid JSON object, no markdown fences:
{
  "reverified": [
    {"index": 0, "voice": "active|passive", "acting_party": "worker|management|other",
     "protected_party": "worker|management", "llm_judgment": "..."}
  ]
}
Return one entry for every input clause, preserving its index.\
"""


def call_extract_llm(client, doc_label: str, chunk: str, chunk_index: int, total_chunks: int) -> dict:
    user_str = (
        f"Document: {doc_label}\nChunk {chunk_index} of {total_chunks}.\n\n"
        f"---TEXT---\n{chunk}\n---END---\n\nExtract every clause from this chunk."
    )
    return create_with_retries(
        client,
        model=MODEL,
        max_tokens=budgeted_max_tokens(EXTRACT_SYSTEM_PROMPT, user_str),
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": EXTRACT_SYSTEM_PROMPT},
            {"role": "user", "content": user_str},
        ],
        **_reasoning_off_kwargs(),
    )


def call_classify_llm(client, doc_label: str, clauses_payload: list[dict]) -> dict:
    """Classify a batch of already-extracted clauses (reasoning left on)."""
    user_str = (
        f"Document: {doc_label}\n\nClassify each extracted clause below. Return "
        f"protected_party, llm_judgment, and topic for each, keyed by its index.\n\n"
        f"---CLAUSES---\n{json.dumps(clauses_payload, ensure_ascii=False)}\n---END---"
    )
    return create_with_retries(
        client,
        model=MODEL,
        max_tokens=budgeted_max_tokens(CLASSIFY_SYSTEM_PROMPT, user_str),
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": CLASSIFY_SYSTEM_PROMPT},
            {"role": "user", "content": user_str},
        ],
    )


def call_reverify_llm(client, doc_label: str, clauses_payload: list[dict]) -> dict:
    """Focused re-verification of flagged clauses' voice / acting_party / protected_party /
    llm_judgment (reasoning left on)."""
    user_str = (
        f"Document: {doc_label}\n\nRe-check each flagged clause below and return corrected "
        f"voice, acting_party, protected_party, and llm_judgment, keyed by its index.\n\n"
        f"---CLAUSES---\n{json.dumps(clauses_payload, ensure_ascii=False)}\n---END---"
    )
    return create_with_retries(
        client,
        model=MODEL,
        max_tokens=budgeted_max_tokens(REVERIFY_SYSTEM_PROMPT, user_str),
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": REVERIFY_SYSTEM_PROMPT},
            {"role": "user", "content": user_str},
        ],
    )


# ── per-document pipeline ────────────────────────────────────────────────────────

# Deterministic safety nets applied to the extracted features before scoring.
_MODAL_IN_QUOTE_RE = re.compile(
    r"\b(must|shall|will|should|ought|need|may|can|could|might)\b", re.I)
# Subject-side quantifier negation ("No teacher may…", "Nothing shall…") that the
# model's verb-phrase-only negation rule can miss.
_SUBJECT_NEG_RE = re.compile(r"^\W*(no|nothing|neither|nor)\b", re.I)
# But "No later/fewer/more/greater/less/earlier/sooner than X" is an affirmative
# floor/ceiling, NOT negation — exclude it from the subject-negation backstop.
_NO_QUANTIFIER_RE = re.compile(
    r"^\W*no\s+(later|fewer|more|greater|less|earlier|sooner|longer)\s+than\b", re.I)
# Parenthetical spans, stripped before modal recovery so a modal inside "(which may…)"
# is not mistaken for the operative modal.
_PAREN_RE = re.compile(r"\([^)]*\)")
# Party keyword lexicons for resolving an explicit passive "by <agent>" phrase.
_WORKER_WORDS = re.compile(
    r"\b(teacher|teachers|faculty|employee|employees|union|unions|association|"
    r"bargaining unit|staff|educator|educators|member|members|nurse|nurses|"
    r"paraprofessional|paraprofessionals|aide|aides|counselor|counselors)\b", re.I)
_MGMT_WORDS = re.compile(
    r"\b(district|districts|board|principal|principals|superintendent|administration|"
    r"administrator|administrators|management|employer|committee|department|supervisor|"
    r"supervisors|school|schools|state|company)\b", re.I)
# An explicit agent phrase in a passive clause ("… held on school property by faculty
# members", "… prepared by the principal"). Captures the noun phrase after "by".
_BY_AGENT_RE = re.compile(r"\bby\s+(?:the\s+|a\s+|an\s+)?([A-Za-z][A-Za-z '\-]{2,40})", re.I)
# An inanimate/impersonal grammatical subject ("This schedule…", "The Agreement…") that
# performs no party's action -> acting_party "other".
_INANIMATE_SUBJ_RE = re.compile(
    r"^\W*(this|that|the)\s+(schedule|agreement|section|article|paragraph|policy|"
    r"contract|provision|plan|memorandum|mou|appendix|clause|table)\b", re.I)


def _by_agent_side(quote: str):
    """Return 'worker'/'management' if the clause names its agent in a `by <X>` phrase
    whose noun phrase maps cleanly to a side, else None. Non-agentive `by` phrases
    ("by June 30", "by mutual agreement") map to no side and return None."""
    for m in _BY_AGENT_RE.finditer(quote):
        span = m.group(1)
        if _WORKER_WORDS.search(span):
            return "worker"
        if _MGMT_WORDS.search(span):
            return "management"
    return None


def classify_and_score(clause: dict) -> dict:
    quote = clause.get("quote") or ""
    modal = (clause.get("modal") or "").strip().lower() or None
    # 1a — modal recovery: the extractor sometimes drops the modal (e.g. "will not
    # be used" -> modal=""), which mis-scores the clause. When it's null, recover the
    # first standalone modal verb from the quote — but NOT one inside a parenthetical
    # (that is not the operative modal). Only fills nulls, never overrides.
    if modal is None:
        m = _MODAL_IN_QUOTE_RE.search(_PAREN_RE.sub(" ", quote))
        if m:
            modal = m.group(1).lower()
    negation = bool(clause.get("negation"))
    # 1c backstop — subject-side quantifier negation the model missed, EXCEPT the
    # affirmative "No later/fewer/more than …" floor/ceiling openings.
    if not negation and _SUBJECT_NEG_RE.match(quote) and not _NO_QUANTIFIER_RE.match(quote):
        negation = True
    # acting_party backstops — the model can mis-default a passive or inanimate actor.
    # An explicit passive "by <agent>" phrase names the real actor and overrides the
    # usual "management" default; otherwise an inanimate subject is "other".
    acting = clause.get("acting_party")
    voice = (clause.get("voice") or "").strip().lower()
    by_side = _by_agent_side(quote) if voice == "passive" else None
    if by_side:
        acting = by_side
    elif _INANIMATE_SUBJ_RE.match(clause.get("subject_text") or ""):
        acting = "other"
    verb_category = clause.get("verb_lexical_category") or "plain"
    statement_type = classify_statement_type(modal, negation, verb_category)
    weight = modal_strength_for(modal, verb_category) if statement_type != "other" else 0.0
    return {
        **clause,
        "acting_party": acting,
        "modal": modal,
        "negation": negation,
        "statement_type": statement_type,
        "modal_strength": weight,
        "statement_type_match": statement_type == clause.get("llm_judgment"),
    }


def _worth_extracting(chunk: str) -> bool:
    """Skip near-empty chunks so the reasoning model isn't invoked just to return
    {"clauses": []}. exclude_appendices() blanks appendix/exhibit pages to "", which
    become whitespace-only chunks after chunking; those (and trivial fragments) hold
    no extractable clause. Conservative on purpose — only genuinely empty chunks are
    dropped, so no real clause is lost."""
    return len(chunk.strip()) >= 40


def _dedup_by_quote(clauses: list[dict]) -> list[dict]:
    """Drop clauses whose exact quote already appeared (the CHUNK_OVERLAP region
    re-extracts the same clause in the next chunk). Order-preserving."""
    seen: set[str] = set()
    out: list[dict] = []
    for clause in clauses:
        q = (clause.get("quote") or "").strip()
        if q and q in seen:
            continue
        if q:
            seen.add(q)
        out.append(clause)
    return out


def _fallback_protected_party(clause: dict) -> str:
    """Deterministic protected_party for a clause the classifier dropped (no entry for its
    index) — better than a blank field. Standard Hohfeld heuristic: an obligation/prohibition
    protects the party OPPOSITE the actor; a right/permission protects the actor's own side;
    an inanimate/other actor defaults to the worker as beneficiary."""
    acting = (clause.get("acting_party") or "").strip().lower()
    st = (clause.get("statement_type") or "").strip().lower()
    if acting not in ("worker", "management"):
        return "worker"
    if st in ("obligation", "prohibition"):
        return "management" if acting == "worker" else "worker"
    return acting


def _classify_clauses(client, document_id: str, file_name: str, clauses: list[dict]) -> None:
    """Second LLM pass: assign protected_party / llm_judgment / topic to each already-
    extracted clause via CLASSIFY_SYSTEM_PROMPT, mutating `clauses` in place. Batches
    are cached at {document_id}__classify{NNN}.json and run concurrently. A failed
    batch leaves its clauses' classification fields empty (they go uncredited in
    aggregate) rather than aborting the document."""
    if not clauses:
        return
    batches = [clauses[i:i + CLASSIFY_BATCH_SIZE] for i in range(0, len(clauses), CLASSIFY_BATCH_SIZE)]

    def run_batch(item: tuple[int, list[dict]]) -> tuple[int, dict | None]:
        bi, batch = item
        cache_path = CACHE_DIR / f"{document_id}__classify{bi:03d}.json"
        if cache_path.exists():
            try:
                return bi, json.loads(cache_path.read_text(encoding="utf-8"))
            except Exception:
                pass  # corrupt/partial cache -> re-fetch below
        payload = [
            {"index": j, "quote": c.get("quote", ""), "subject_text": c.get("subject_text", ""),
             "acting_party": c.get("acting_party", ""), "statement_type": c.get("statement_type", "")}
            for j, c in enumerate(batch)
        ]
        try:
            raw = call_classify_llm(client, file_name, payload)
        except Exception:
            return bi, None
        cache_path.write_text(json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8")
        return bi, raw

    with ThreadPoolExecutor(max_workers=MAX_CONCURRENCY) as pool:
        results = dict(pool.map(run_batch, enumerate(batches, start=1)))

    for bi, batch in enumerate(batches, start=1):
        raw = results.get(bi)
        by_index: dict[int, dict] = {}
        if raw and "error" not in raw:
            for item in raw.get("classified", []):
                idx = item.get("index")
                if isinstance(idx, int):
                    by_index[idx] = item
        for j, c in enumerate(batch):
            cl = by_index.get(j, {})
            # No-blank guard: when the classifier drops a clause (returns no entry for its
            # index — v9: Prince George's c1 had blank judgment + protected_party), fall back
            # to deterministic values rather than emitting empty fields.
            c["protected_party"] = cl.get("protected_party") or _fallback_protected_party(c)
            c["llm_judgment"] = cl.get("llm_judgment") or (c.get("statement_type") or "")
            c["topic"] = cl.get("topic") or ""


# 2A — targeted re-verification. A clause is re-checked only when it lands in a v9 error zone,
# so the paid second pass runs on a small minority of clauses, not all of them.
_PASSIVE_RISK_RE = re.compile(
    r"\b(?:shall|will|may|must|should|can|could|might)\s+(?:not\s+)?be\s+\w+ed\b"
    r"|\b(?:is|are|was|were|been|being)\s+(?:not\s+)?\w+ed\b",
    re.I,
)


def _needs_reverify(c: dict) -> bool:
    """Flag a clause for focused re-verification when it hits a v9 error zone:
    (1) MISSED PASSIVE — a be+past-participle / modal(+not)+be pattern in the quote but voice
        tagged active (v9: "shall not be employed/required", "is not impacted" read active), or
    (2) PROTECTED DEFAULTED TO ACTOR — protected_party equals acting_party on an obligation or
        prohibition, where the beneficiary is usually the OTHER side (v9: management duty tagged
        protected=management instead of worker)."""
    quote = c.get("quote", "") or ""
    voice = (c.get("voice") or "").strip().lower()
    acting = (c.get("acting_party") or "").strip().lower()
    protected = (c.get("protected_party") or "").strip().lower()
    st = (c.get("statement_type") or "").strip().lower()
    if voice != "passive" and _PASSIVE_RISK_RE.search(quote):
        return True
    if protected and protected == acting and acting in ("worker", "management") \
            and st in ("obligation", "prohibition"):
        return True
    return False


def _reverify_ambiguous_clauses(
    client, document_id: str, file_name: str, clauses: list[dict],
) -> int:
    """Focused second pass over ONLY the clauses `_needs_reverify` flags. Re-decides voice /
    acting_party / protected_party / llm_judgment with a targeted prompt and adopts the
    corrections in place; the downstream classify_and_score then re-derives statement_type and
    the passive acting-party backstop from the corrected voice. Batched + cached; runs only on
    the flagged minority so the added cost stays small. Returns the number of clauses changed."""
    flagged = [(idx, c) for idx, c in enumerate(clauses) if _needs_reverify(c)]
    if not flagged:
        return 0
    batches = [flagged[i:i + CLASSIFY_BATCH_SIZE] for i in range(0, len(flagged), CLASSIFY_BATCH_SIZE)]

    def run_batch(item: tuple[int, list]) -> tuple[int, dict | None]:
        bi, batch = item
        cache_path = CACHE_DIR / f"{document_id}__reverify{bi:03d}.json"
        if cache_path.exists():
            try:
                return bi, json.loads(cache_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        payload = [
            {"index": j, "quote": c.get("quote", ""), "voice": c.get("voice", ""),
             "acting_party": c.get("acting_party", ""),
             "protected_party": c.get("protected_party", ""),
             "statement_type": c.get("statement_type", ""),
             "llm_judgment": c.get("llm_judgment", "")}
            for j, (_, c) in enumerate(batch)
        ]
        try:
            raw = call_reverify_llm(client, file_name, payload)
        except Exception:
            return bi, None
        cache_path.write_text(json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8")
        return bi, raw

    with ThreadPoolExecutor(max_workers=MAX_CONCURRENCY) as pool:
        results = dict(pool.map(run_batch, enumerate(batches, start=1)))

    changed = 0
    for bi, batch in enumerate(batches, start=1):
        raw = results.get(bi)
        by_index: dict[int, dict] = {}
        if raw and "error" not in raw:
            for item in raw.get("reverified", []):
                if isinstance(item.get("index"), int):
                    by_index[item["index"]] = item
        for j, (_, c) in enumerate(batch):
            rv = by_index.get(j)
            if not rv:
                continue
            touched = False
            for field in ("voice", "acting_party", "protected_party", "llm_judgment"):
                val = (rv.get(field) or "").strip()
                if val and val != (c.get(field) or ""):
                    c[field] = val
                    touched = True
            if touched:
                changed += 1
                c["reverified"] = True
    return changed


def process_document(
    client, document_id: str, file_name: str, district: str,
) -> tuple[list[dict], str, int, int]:
    """Returns (clauses, status, failed_chunks, total_chunks)."""
    pdf_path = PDF_ROOT / district / file_name
    text_path = TEXT_DIR / f"{document_id}.txt"
    # Use cached text when the PDF is a 0-byte Dropbox placeholder; only bail out
    # if neither the PDF nor the cached extraction is usable.
    if (not pdf_path.exists() or pdf_path.stat().st_size == 0) and not text_path.exists():
        return [], "needs_dropbox_hydration", 0, 0

    text = extract_text(pdf_path, text_path)
    pages = text.split("\f") if text else []
    if not pages:
        return [], "no_extractable_text", 0, 0

    filtered_text = "\f".join(exclude_appendices(pages))
    chunks = chunk_text(filtered_text)
    if not chunks:
        return [], "no_extractable_text", 0, 0

    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # Phase 1 — EXTRACTION: one mechanical (optionally reasoning-off) call per non-
    # empty chunk, concurrently. map() yields in input order, so clause order (and the
    # overlap-dedup below) is identical to sequential processing.
    extract_items = [(i, ch) for i, ch in enumerate(chunks, start=1) if _worth_extracting(ch)]
    skipped = len(chunks) - len(extract_items)
    all_clauses: list[dict] = []
    failed_chunks = 0
    malformed_clauses = 0

    def fetch_raw(item: tuple[int, str]) -> tuple[int, dict | None]:
        """Return (chunk_index, raw) for one chunk, using the cache when present.
        Returns raw=None on API failure so the chunk is retried on the next run: the
        failure is deliberately not cached (the model may have run out of output tokens
        mid-JSON even after som_client's own retries)."""
        i, chunk = item
        cache_path = CACHE_DIR / f"{document_id}__chunk{i:03d}.json"
        if cache_path.exists():
            try:
                return i, json.loads(cache_path.read_text(encoding="utf-8"))
            except Exception:
                pass  # corrupt/partial cache (e.g. killed mid-write) -> re-fetch below
        try:
            raw = call_extract_llm(client, file_name, chunk, i, len(chunks))
        except Exception:
            return i, None
        cache_path.write_text(json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8")
        return i, raw

    with ThreadPoolExecutor(max_workers=MAX_CONCURRENCY) as pool:
        for i, raw in pool.map(fetch_raw, extract_items):
            if raw is None or "error" in raw:
                failed_chunks += 1
                continue
            for clause in raw.get("clauses", []):
                # The model occasionally returns a bare string (or null) where a clause
                # object belongs. Assuming every element is a dict crashed an entire
                # document on one malformed element -- Polk County lost all four steps'
                # rights output to a single stray string. A malformed clause should cost
                # that clause, not the document.
                if not isinstance(clause, dict):
                    malformed_clauses += 1
                    continue
                clause["chunk_index"] = i
                # Deterministic statement_type now (needs only the mechanical fields);
                # it is handed to the classification pass and re-derived identically by
                # classify_and_score in Phase 3.
                clause["statement_type"] = classify_statement_type(
                    (clause.get("modal") or "").strip().lower() or None,
                    bool(clause.get("negation")),
                    clause.get("verb_lexical_category") or "plain",
                )
                all_clauses.append(clause)

    # Dedup the overlap re-extractions before the (paid) classification pass.
    deduped = _dedup_by_quote(all_clauses)

    # Phase 2 — CLASSIFICATION: reasoning pass adding protected_party/llm_judgment/topic.
    _classify_clauses(client, document_id, file_name, deduped)

    # Phase 2b — targeted re-verification (2A): re-check only the voice/party error-prone
    # clauses (missed passive, protected_party defaulted to the actor) with a focused prompt.
    n_rev = _reverify_ambiguous_clauses(client, document_id, file_name, deduped)
    if n_rev:
        print(f"      re-verified {n_rev} ambiguous clause(s)")

    # Phase 3 — deterministic scoring (modal_strength + statement_type_match) plus a
    # quote-presence guard: mark whether each clause's quote is actually found in the
    # document text so fabricated/stitched quotes are excluded from the score (aggregate).
    full_text_norm = norm_ws(text)
    scored = []
    for c in deduped:
        entry = classify_and_score(c)
        entry["quote_verified"] = quote_present(entry.get("quote", ""), full_text_norm)
        scored.append(entry)

    if skipped:
        print(f"      (skipped {skipped}/{len(chunks)} empty/appendix chunks)")
    if malformed_clauses:
        # Visible, not swallowed: skipping a malformed element is the right recovery, but a
        # document quietly losing clauses to schema drift would be indistinguishable from a
        # document that genuinely contains fewer.
        print(f"      {malformed_clauses} malformed clause element(s) skipped "
              f"(model returned a non-object where a clause was expected)")
    return scored, "ok", failed_chunks, len(chunks)


# ── aggregation ──────────────────────────────────────────────────────────────────

def aggregate(clauses: list[dict]) -> dict:
    totals = {
        "worker_rights": 0.0, "worker_responsibilities": 0.0,
        "management_rights": 0.0, "management_responsibilities": 0.0,
        "total_weight": 0.0, "total_clauses_scored": 0,
    }
    for c in clauses:
        if c.get("quote_verified") is False:
            continue  # fabricated/stitched quote (not found in the document) — exclude
        st = c["statement_type"]
        w = c["modal_strength"]
        if st == "other" or w <= 0:
            continue
        totals["total_weight"] += w
        totals["total_clauses_scored"] += 1
        acting = c.get("acting_party")
        protected = c.get("protected_party")
        if st in ("obligation", "prohibition"):
            if acting == "worker":
                totals["worker_responsibilities"] += w
            elif acting == "management":
                totals["management_responsibilities"] += w
        else:  # right or permission: credit the protected party
            if protected == "worker":
                totals["worker_rights"] += w
            elif protected == "management":
                totals["management_rights"] += w
    tw = totals["total_weight"] or 1.0
    for key in ("worker_rights", "worker_responsibilities", "management_rights", "management_responsibilities"):
        totals[f"{key}_share"] = totals[key] / tw
    return totals


# ── output writers ───────────────────────────────────────────────────────────────

LONG_FIELDS = [
    "document_id", "file_name", "district_name", "chunk_index", "quote", "subject_text",
    "acting_party", "protected_party", "modal", "negation", "voice", "verb_lexical_category",
    "statement_type", "llm_judgment", "statement_type_match", "modal_strength", "topic",
    "quote_verified", "notes",
]

SUMMARY_FIELDS = [
    "document_id", "file_name", "district_name", "total_chunks", "chunks_failed",
    "total_clauses_extracted", "total_clauses_scored",
    "total_weight", "worker_rights", "worker_responsibilities", "management_rights",
    "management_responsibilities", "worker_rights_share", "worker_responsibilities_share",
    "management_rights_share", "management_responsibilities_share",
]


def write_long_csv(rows: list[dict]) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / "rights_score_long.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=LONG_FIELDS)
        w.writeheader()
        w.writerows(rows)
    return path


def write_summary_csv(rows: list[dict]) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / "rights_score_summary.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=SUMMARY_FIELDS)
        w.writeheader()
        w.writerows(rows)
    return path


def build_long_rows(document_id: str, file_name: str, district: str, clauses: list[dict]) -> list[dict]:
    return [
        {
            "document_id": document_id, "file_name": file_name, "district_name": district,
            "chunk_index": c.get("chunk_index", ""),
            "quote": c.get("quote", ""), "subject_text": c.get("subject_text", ""),
            "acting_party": c.get("acting_party", ""), "protected_party": c.get("protected_party", ""),
            "modal": c.get("modal") or "", "negation": c.get("negation", ""), "voice": c.get("voice", ""),
            "verb_lexical_category": c.get("verb_lexical_category", ""),
            "statement_type": c.get("statement_type", ""), "llm_judgment": c.get("llm_judgment", ""),
            "statement_type_match": c.get("statement_type_match", ""),
            "modal_strength": c.get("modal_strength", ""), "topic": c.get("topic", ""),
            "quote_verified": c.get("quote_verified", ""),
            "notes": c.get("notes", ""),
        }
        for c in clauses
    ]


# ── input loading ────────────────────────────────────────────────────────────────

def load_all_targets(max_docs: int | None) -> list[tuple[str, str, str]]:
    """Return (document_id, file_name, district_name) for every document in the
    40-doc sample (the wide output of llm_extract.py), used as the default batch
    when no --doc/--district/--file is given."""
    if not MAIN_DATASET.exists():
        sys.exit(f"Error: {MAIN_DATASET} not found — run llm_extract.py first.")
    rows = []
    with MAIN_DATASET.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rows.append((row["document_id"], row["file_name"], row["district_name"]))
    return rows[:max_docs] if max_docs else rows


def load_targets(args) -> list[tuple[str, str, str]]:
    if args.doc:
        return [
            (document_id_for(district, file_name), file_name, district)
            for district, file_name in (d.split("|", 1) for d in args.doc)
        ]
    if args.district or args.file:
        if not (args.district and args.file):
            sys.exit("Error: --district and --file must be given together.")
        return [(document_id_for(args.district, args.file), args.file, args.district)]
    return load_all_targets(args.max_docs)


# ── entry point ───────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--doc", action="append", metavar="DISTRICT|FILE.pdf",
        help="Process specific document(s), writing one combined output. May be repeated.",
    )
    parser.add_argument("--district", help="Process a single PDF: district folder name")
    parser.add_argument("--file", help="Process a single PDF: file name within --district")
    parser.add_argument(
        "--max-docs", type=int, default=None,
        help="Limit number of documents processed (only applies to the full-sample default run)",
    )
    args = parser.parse_args()

    # Register the request-hash cache + telemetry sink. som_client only records calls when
    # a sink is registered, so this must happen at every entry point or a real run produces
    # no cache and no telemetry (which is how the first v11 smoke test ran).
    try:
        import store
        store.get_store().start_run(notes="rights_score")
    except Exception as exc:      # never let instrumentation stop a run
        print(f"  [store] telemetry unavailable: {exc}")


    targets = load_targets(args)
    client = get_client()

    print(f"Processing {len(targets)} document(s) ...")
    long_rows: list[dict] = []
    summary_rows: list[dict] = []
    statuses: dict[str, int] = {}

    for i, (document_id, file_name, district) in enumerate(targets, start=1):
        print(f"[{i:>2}/{len(targets)}] {file_name} ...")
        clauses, status, failed_chunks, total_chunks = process_document(
            client, document_id, file_name, district,
        )
        statuses[status] = statuses.get(status, 0) + 1
        if status != "ok":
            print(f"      {status}")
            continue
        totals = aggregate(clauses)
        summary_rows.append({
            "document_id": document_id, "file_name": file_name, "district_name": district,
            "total_chunks": total_chunks, "chunks_failed": failed_chunks,
            "total_clauses_extracted": len(clauses), **totals,
        })
        long_rows.extend(build_long_rows(document_id, file_name, district, clauses))
        note = f", {failed_chunks}/{total_chunks} chunks failed" if failed_chunks else ""
        print(f"      {len(clauses)} clauses extracted, {totals['total_clauses_scored']} scored{note}")

    long_path = write_long_csv(long_rows)
    summary_path = write_summary_csv(summary_rows)
    print(f"\n{len(long_rows)} clause rows    -> {long_path}")
    print(f"{len(summary_rows)} document rows -> {summary_path}")
    print(f"Document status summary: {statuses}")


if __name__ == "__main__":
    main()
