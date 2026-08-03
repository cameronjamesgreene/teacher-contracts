"""Two-view question coding: whole-document + FTS5 retrieval, unioned and quote-gated.

REPLACES the chunk x sub-batch x recovery x reconciliation superstructure in llm_extract.
That machinery existed to work around a context window the endpoint never had (som_client
believed 32k; it is 131k), and it cost 184-713 sequential calls per document while still
producing the error profile it was built to prevent.

THE DECISION RULE IS AN OR, NOT A VOTE. On the only unbiased audit, 69 of 73 coding errors
were `not_discussed` on a provision that was present, and ZERO were fabricated values. That
loss function is asymmetric, so majority voting is the wrong aggregator: if two samples say
not_discussed and one produces a verbatim quote of the provision, the majority is wrong. We
take any substantive answer whose quote verifies against the source, and spend the budget
on DIVERSE views rather than repeated samples of one view.

The two views fail on disjoint sets, which is what makes the union pay:

    whole document  -- sees everything, but loses provisions in the middle of long documents
                       (Houston, 113k tokens: returned not_discussed for a salary schedule)
    FTS5 BM25       -- finds the needle by name, but misses answers requiring synthesis
                       across distant sections, and is blind to number-only table pages

Measured on four documented false negatives: whole-doc 2/4, FTS5 3/4, union 3/4, and the
never-silent escalation below targets the residual.

THREE-STAGE ESCALATION per question:
  1. both views -> union. Substantive + verified quote wins over not_discussed.
  2. if the result is still not_discussed but FTS5 finds the topic's keywords in the
     document, re-ask on JUST those pages. This is the honest version of a claim the old
     `_recover_missed_answers` docstring made falsely -- it used str.find() on the first 3
     occurrences of each term, so on a document where "salary schedule" appears 200 times
     the three windows it examined were narrative prose and never the appendix.
  3. if it survives all that as not_discussed, emit it WITH the page numbers where the
     keywords were found. A residual false negative then costs an inspection, not a silent
     zero -- which is the difference between a bounded error list and an unmeasurable one.
"""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import corpus
import som_client as sc
from som_client import MODEL, budgeted_max_tokens, cap_text, create_with_retries
from utils import Question, norm_ws, quote_present, terms_from_question

# Sub-batch size. Was 6 under the 32k-window assumption. Larger batches mean fewer calls and
# a shared document prefix, but dilute attention across questions; 8 is a measured-safe step
# rather than a guess. A/B with LLM_QUESTIONS_PER_BATCH.
QUESTIONS_PER_BATCH = int(os.environ.get("LLM_QUESTIONS_PER_BATCH", "8"))
VIEW_CONCURRENCY = int(os.environ.get("LLM_VIEW_CONCURRENCY", "8"))
FTS_TOPK = int(os.environ.get("LLM_FTS_TOPK", "12"))
ESCALATE = os.environ.get("LLM_ESCALATE", "1") == "1"
# Require a source-verified quote before one view may override the other's not_discussed.
# This is the recall/precision dial for the union rule -- see _union() for the measured
# trade-off. Default on: an ungrounded assertion is worse than an admitted uncertainty.
REQUIRE_VERIFIED = os.environ.get("LLM_REQUIRE_VERIFIED", "1") == "1"

MISSING = {"not_discussed", "discussed_unclear", "", "none", "null", "no_answer"}

SYSTEM = (
    "You are coding a teacher collective-bargaining agreement or employee handbook for a "
    "research dataset. For EACH question id you are given, return an object with keys: "
    '"answer", "evidence", "page", "confidence", "coder_notes".\n\n'
    "answer: for yes/no questions use exactly \"yes\" or \"no\"; for value questions give the "
    "value itself. Use \"not_discussed\" ONLY when the topic is genuinely absent from the "
    "document. Use \"discussed_unclear\" when the topic appears but cannot be coded.\n"
    "evidence: a VERBATIM quote copied character-for-character from the document. Never "
    "paraphrase, never splice two passages together, never use an ellipsis to join text. If "
    "you cannot copy an exact quote, answer not_discussed instead.\n"
    "page: the printed page number the quote came from, or null.\n"
    "confidence: high, medium, or low.\n\n"
    "Search the ENTIRE text you are given, including appendices, exhibits, memoranda of "
    "understanding, side letters and tables at the back. Provisions are frequently located "
    "there rather than in the numbered articles.\n\n"
    "THE PROVISION MUST BE PRESENT. Code \"yes\" only when THIS document states the substance "
    "of the thing asked about. A bare cross-reference to an external document — \"as provided "
    "in the district salary schedule\", \"subject to Board Policy 4118\", \"per state law\" — is "
    "NOT sufficient on its own, because the substance is not in front of you and cannot be "
    "coded from this text. A mention of a topic is not a provision about it.\n"
    "The ONE exception is the question's own wording: if a question explicitly asks whether "
    "the document \"contains OR REFERENCES\" something, then a clear reference does qualify. "
    "Answer each question exactly as worded — neither stricter nor looser.\n"
    "Reserve \"no\" for the document affirmatively stating the thing does NOT exist or does "
    "not apply. If the topic simply never comes up, that is \"not_discussed\", not \"no\". If "
    "the topic is raised but only by cross-reference, that is \"discussed_unclear\".\n"
    'Reply with JSON only: {"<question_id>": {...}, ...}'
)

_FALLBACK = {"answer": "not_discussed", "evidence": "", "page": None,
             "confidence": "low", "coder_notes": ""}


def _questions_block(batch: list) -> str:
    return json.dumps([
        {"question_id": q.qid, "question": q.question,
         "answer_type": getattr(q, "answer_type", ""), "what_to_extract": q.extract}
        for q in batch
    ], indent=1)


# Output budget per coding call. Measured on a 4-document run at 8 questions/batch with
# reasoning on: ~4,900 reasoning tokens + ~5,900 answer tokens = ~10,800. A 6,000 budget
# truncated 34 of 144 calls; each truncation costs a full re-generation at double the budget,
# so under-budgeting here is far more expensive than over-budgeting (max_tokens is only a
# cap — unused headroom is free). Scaled by batch size so a single-question escalation call
# doesn't reserve a batch-sized budget.
_OUTPUT_PER_QUESTION = int(os.environ.get("LLM_OUTPUT_PER_QUESTION", "1800"))
_OUTPUT_FLOOR = int(os.environ.get("LLM_OUTPUT_FLOOR", "6000"))


def _ask(client, body: str, batch: list, stage: str, document_id: str) -> dict:
    """One coding call. The DOCUMENT GOES FIRST so the long prefix is identical across every
    sub-batch of this document and vLLM's automatic prefix cache can reuse it; the old
    prompt put the document last, behind per-batch text, defeating that entirely."""
    user = f"{body}\n\nQUESTIONS TO CODE:\n{_questions_block(batch)}"
    budget = max(_OUTPUT_FLOOR, _OUTPUT_PER_QUESTION * len(batch) + 4000)
    try:
        raw = create_with_retries(
            client, _stage=stage, _document_id=document_id,
            _qids=",".join(q.qid for q in batch),
            model=MODEL,
            max_tokens=budgeted_max_tokens(SYSTEM, user, max_output=budget),
            response_format={"type": "json_object"},
            messages=[{"role": "system", "content": SYSTEM},
                      {"role": "user", "content": user}],
        )
    except Exception as exc:
        # A failed call is NOT evidence of absence. Marking it no_answer keeps a transient
        # backend error from being written to the dataset as "the contract doesn't say".
        return {q.qid: {**_FALLBACK, "answer": "no_answer",
                        "coder_notes": f"{stage} call failed: {type(exc).__name__}"}
                for q in batch}
    out = {}
    for q in batch:
        entry = raw.get(q.qid)
        if not isinstance(entry, dict):
            # A missing key is a call defect, not an absent provision -- same reasoning.
            out[q.qid] = {**_FALLBACK, "answer": "no_answer",
                          "coder_notes": f"{stage} omitted this question id"}
            continue
        out[q.qid] = {
            "answer": str(entry.get("answer", "not_discussed") or "not_discussed").strip(),
            "evidence": str(entry.get("evidence", "") or "").strip(),
            "page": entry.get("page"),
            "confidence": str(entry.get("confidence", "low") or "low").strip().lower(),
            "coder_notes": str(entry.get("coder_notes", "") or "").strip(),
        }
    return out


def _substantive(rec: dict) -> bool:
    return str(rec.get("answer", "")).strip().lower() not in MISSING


_CONF_RANK = {"high": 3, "medium": 2, "low": 1}


def _union(a: dict, b: dict, text_norm: str) -> tuple:
    """Combine one question's two views. Returns (record, provenance).

    Quote verification is the precision guard that makes an OR rule safe: an answer is only
    allowed to override a not_discussed if its quote is actually in the document.
    """
    a_ok, b_ok = _substantive(a), _substantive(b)
    a_q = a_ok and quote_present(a.get("evidence", ""), text_norm)
    b_q = b_ok and quote_present(b.get("evidence", ""), text_norm)

    if a_ok and b_ok:
        # Both found something. Prefer the verified one, then the more confident.
        if a_q != b_q:
            return (a, "both:A-verified") if a_q else (b, "both:B-verified")
        rank_a = _CONF_RANK.get(a.get("confidence"), 1)
        rank_b = _CONF_RANK.get(b.get("confidence"), 1)
        return (a, "both:A") if rank_a >= rank_b else (b, "both:B")
    # Single-view adoption is where the union spends precision, so it is the knob. Measured
    # on the 4-document gold set: the union lifted recall on substantive provisions from
    # 0.765 to 0.962 (false negatives 50 -> 8) and fixed 31 of the 52 cells the human audit
    # had marked wrong -- but precision fell from 1.000 to 0.837 (40 new false positives, 37
    # of them carrying quotes that DO verify against the source). The model is finding real
    # text and over-reading it as a provision. Requiring a verified quote before one view may
    # override the other's not_discussed is the cheapest brake; set REQUIRE_VERIFIED=0 to
    # maximise recall instead, at a further precision cost.
    if a_ok and (a_q or not REQUIRE_VERIFIED):
        return (a, "only:A" + ("" if a_q else ":unverified"))
    if b_ok and (b_q or not REQUIRE_VERIFIED):
        return (b, "only:B" + ("" if b_q else ":unverified"))
    if a_ok or b_ok:
        # Substantive but unverifiable: record it as unclear rather than asserting it, and
        # keep the text so a human can adjudicate.
        src = a if a_ok else b
        return ({**src, "answer": "discussed_unclear",
                 "coder_notes": (str(src.get("coder_notes", "")) +
                                 " [downgraded: no verbatim quote located in source]").strip()},
                "unverified:downgraded")
    # Neither view found it: prefer whichever gave a real negative over a failed call.
    if str(a.get("answer")).lower() == "no_answer" and str(b.get("answer")).lower() != "no_answer":
        return b, "neither:B"
    return a, "neither:A"


def code_document(client, document_id: str, text: str, questions: list,
                  con=None, progress=None) -> dict:
    """Code every question for one document. Returns {qid: record}."""
    con = con or corpus.get_con()
    text_norm = norm_ws(text)
    doc_view = "DOCUMENT:\n" + cap_text(text)

    batches = [questions[i:i + QUESTIONS_PER_BATCH]
               for i in range(0, len(questions), QUESTIONS_PER_BATCH)]

    def run_batch(batch: list) -> dict:
        terms: list = []
        for q in batch:
            terms.extend(terms_from_question(q))
        # Per-thread connection: a sqlite3.Connection cannot be shared across
        # concurrent execute() calls (see corpus.get_con).
        retrieved = corpus.passages(document_id, terms, k=FTS_TOPK,
                                    con=corpus.get_con())

        # The two views are independent, so run them concurrently. Real in-flight limits
        # are enforced centrally by som_client.GOVERNOR, not here.
        with ThreadPoolExecutor(max_workers=2) as ex:
            fa = ex.submit(_ask, client, doc_view, batch, "viewA", document_id)
            fb = (ex.submit(_ask, client, "KEYWORD-RETRIEVED PAGES:\n" + retrieved,
                            batch, "viewB", document_id)
                  if retrieved else None)
            a = fa.result()
            b = fb.result() if fb else {q.qid: dict(_FALLBACK) for q in batch}

        merged = {}
        for q in batch:
            rec, prov = _union(a[q.qid], b[q.qid], text_norm)
            rec = dict(rec)
            rec["_provenance"] = prov
            merged[q.qid] = rec
        return merged

    coded: dict = {}
    with ThreadPoolExecutor(max_workers=max(1, VIEW_CONCURRENCY)) as ex:
        for result in ex.map(run_batch, batches):
            coded.update(result)
            if progress:
                progress(len(coded), len(questions))

    if ESCALATE:
        _escalate(client, document_id, coded, questions, text_norm, con)

    for qid, rec in coded.items():
        _finalize(document_id, rec, text_norm, con)
    return coded


def _escalate(client, document_id: str, coded: dict, questions: list,
              text_norm: str, con) -> None:
    """Stage 2/3: never-silent false-negative check.

    For every question that came back not_discussed, ask the index whether the topic's
    keywords appear anywhere in this document. If they do, re-ask on exactly those pages;
    if the answer still comes back negative, record the pages so the residual is
    inspectable rather than invisible.
    """
    by_qid = {q.qid: q for q in questions}
    targets = [qid for qid, rec in coded.items() if not _substantive(rec)]
    if not targets:
        return

    def one(qid: str) -> None:
        q = by_qid.get(qid)
        if q is None:
            return
        terms = terms_from_question(q)
        pages = corpus.has_any_hit(document_id, terms, con=corpus.get_con())
        if not pages:
            return                                   # genuine absence; nothing to escalate
        focused = corpus.passages(document_id, terms, k=6, neighbours=1,
                                  con=corpus.get_con())
        if not focused:
            return
        body = ("PAGES WHERE THIS TOPIC'S KEYWORDS APPEAR IN THIS DOCUMENT.\n"
                "A previous pass coded this question not_discussed. The keywords ARE "
                "present below. Read carefully and code it again; if the provision truly "
                "is not stated here, answer not_discussed.\n\n" + focused)
        got = _ask(client, body, [q], "escalate", document_id)[qid]
        if _substantive(got) and quote_present(got.get("evidence", ""), text_norm):
            got = dict(got)
            got["_provenance"] = "escalated"
            coded[qid] = got
        else:
            coded[qid]["coder_notes"] = (
                (coded[qid].get("coder_notes", "") + " ").strip()
                + f"[review: topic keywords found on page(s) "
                  f"{', '.join(str(p) for p in pages[:8])} but no confirmable answer "
                  f"— verify this is not a false negative]").strip()

    with ThreadPoolExecutor(max_workers=max(1, VIEW_CONCURRENCY)) as ex:
        list(ex.map(one, targets))


def _finalize(document_id: str, rec: dict, text_norm: str, con) -> None:
    """Verify the quote and repair the page citation."""
    ev = rec.get("evidence", "")
    rec["quote_verified"] = bool(ev) and quote_present(ev, text_norm)
    if _substantive(rec) and ev and not rec["quote_verified"]:
        rec["coder_notes"] = (rec.get("coder_notes", "") + " "
                              "[quote not verbatim in source]").strip()
    # The page field is frequently wrong even when the answer is right; the index can
    # resolve it exactly from the quote.
    if rec["quote_verified"]:
        page = corpus.locate_quote(document_id, ev, con=corpus.get_con())
        if page:
            rec["page"] = page
