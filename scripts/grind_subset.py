#!/usr/bin/env python3
"""Post-processing pass: enrich substantive answers with grounded subset variations.

Both upstream extractors score ~0.52 on completeness for the same structural reason:
they find a provision's main rule in its article and stop. The material *variations* —
a different figure for job sharers, part-time staff, a named specialist role, another
school level, another health-plan option, another contract year — are usually stated
somewhere else in the document, most often in an appendix or a schedule that shares
almost no vocabulary with the question. One retrieval pass aimed at the question finds
the main rule and, having found it, has no reason to keep looking.

This pass re-retrieves *per answer* with the question's own topic terms crossed against
five families of subset vocabulary (employment fraction, role, structure, time/plan,
school level), then asks the model one narrow question: does anything here state a
different rule for a *named* subgroup that the current answer omits? Every claimed
variation must come back with a contiguous verbatim quote, which the host re-locates
with `ground()`; anything that will not ground is dropped without comment.

Two invariants make the pass monotone — it cannot make an answer worse:

1. **The original evidence string is never touched.** The natural move, appending the
   variation's quote to the evidence field, would destroy the property that evidence is
   one unbroken span of the document: the concatenation of two quotes from pages 29 and
   50 appears nowhere. The variation's quote is carried in `subset_variations` (and its
   substance in the answer text) instead, so evidence contiguity is preserved by
   construction rather than by hope.
2. **Merging is append-only.** The merged answer keeps the original answer as its first
   sentence and adds one sentence per accepted variation; the page field gains the
   variation's page and loses nothing. So discussion status, required tokens and pages
   can only stay the same or improve, whatever the model returns.

An answer with nothing grounded is written through byte-identical.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import som_client
from grind_retrieve import (Passage, document_pages, fused_passages, ground,
                            locate_in_document, norm, open_database, passage_payload)
from utils import WORK, read_codebook

DB_PATH = WORK / "cache" / "contract_search_structural.sqlite3"
# The reconciled ensemble is the pipeline's normal output, so it is the natural input
# for a completeness polish.
DEFAULT_INPUT = WORK / "output" / "extraction" / "results" / "ensemble.jsonl"
DEFAULT_OUT = WORK / "output" / "extraction" / "results" / "subset.jsonl"

# An answer is only a completeness problem if it asserts something. These are the
# non-assertions; the sibling passes own them.
SKIP_STATUS = {"not_discussed", "not discussed", "not_applicable", "not applicable",
               "discussed_unclear", "discussed unclear", "no", "no.", "none", ""}

# ── subset vocabulary ─────────────────────────────────────────────────────────────
# Five families, each a plain-language phrase appended to the question's own topic
# terms to make one retrieval query. They are deliberately question-independent: the
# same five run for every question, so nothing here can be tuned to a question ID.
# The families exist because a variation is almost always indexed on *who or when* it
# applies to rather than on the provision's own words, and each family names a
# different axis a contract slices a provision along.
SUBSET_FAMILIES = {
    "fraction": ("job share job sharing shared position part-time part time half-time "
                 "less than full time pro-rated prorated proportionate per diem hourly"),
    "role": ("specialist coordinator supervisor department head chairperson director "
             "psychologist nurse guidance counselor social worker librarian media "
             "vocational special education"),
    "structure": ("appendix appendices schedule addendum exhibit index memorandum of "
                  "understanding memorandum of agreement side letter letter of agreement"),
    "time_plan": ("fiscal year school year effective date first year second year third "
                  "year optional plan option tier single two person family coverage"),
    "level": ("elementary middle school junior high senior high grade level "
              "kindergarten building"),
}
FAMILY_BUDGET = 4        # passages pulled per family before interleaving
PASSAGE_LIMIT = 14       # passages shown to the model (read_passages caps at 20)
PASSAGE_CHARS = 15000    # ~5k tokens; leaves the reasoning model room to finish
MAX_VARIATIONS = 3       # kept per answer, to keep merged answers readable
MAX_DEPTH = 2            # retrieval slices tried per answer before giving up

_STOPWORDS = {
    "the", "and", "for", "are", "any", "all", "does", "did", "what", "which", "who",
    "whom", "when", "how", "this", "that", "there", "their", "with", "from", "into",
    "not", "but", "its", "may", "can", "must", "shall", "will", "have", "has", "had",
    "was", "were", "been", "being", "such", "state", "states", "stated", "document",
    "contract", "agreement", "provision", "provisions", "describe", "specify", "list",
    "include", "included", "other", "others", "than", "per", "each", "one", "two",
    "also", "same", "these", "those", "they", "them", "then", "some", "more", "most",
    "yes", "under", "over", "about", "used", "use", "given", "give",
}
_WORD = re.compile(r"[a-z][a-z'-]+|\d+")
_TOKEN = re.compile(r"[a-z]+|\d+")


def topic_terms(question, limit: int = 14) -> str:
    """Compact topic phrase for a question: its content words plus its codebook keywords.

    The full question sentence dilutes both BM25 and the dense embedding once a subset
    phrase is appended to it, so function words and codebook boilerplate are dropped.
    """
    seen: list[str] = []
    for source in (question.question, " ".join(question.keywords or [])):
        for word in _WORD.findall(norm(source)):
            if word in _STOPWORDS or len(word) < 3:
                continue
            if word not in seen:
                seen.append(word)
    return " ".join(seen[:limit])


def subset_passages(connection, question, depth: int = 0) -> list[Passage]:
    """Retrieve for one answer: topic × each subset family, interleaved round-robin.

    Interleaving rather than concatenating matters — a single family that happens to
    match the provision's own wording would otherwise fill the whole budget and the
    pass would see nothing it did not already see.

    `depth` skips the first `depth * FAMILY_BUDGET` hits of every family, which is how
    a later pass gets a disjoint slice of the document to look at rather than re-reading
    the passages that already yielded nothing.
    """
    topic = topic_terms(question)
    per_family: list[list[Passage]] = []
    for phrase in SUBSET_FAMILIES.values():
        query = f"{topic} {phrase}".strip()
        try:
            hits = fused_passages(connection, query,
                                  budget=min(20, FAMILY_BUDGET * (depth + 1)))
        except Exception:
            hits = []                  # one bad family must not fail the answer
        per_family.append(hits[depth * FAMILY_BUDGET:])
    ordered: list[Passage] = []
    seen: set[int] = set()
    budget_chars = 0
    for index in range(FAMILY_BUDGET):
        for hits in per_family:
            if index >= len(hits):
                continue
            passage = hits[index]
            if passage.passage_id in seen:
                continue
            if len(ordered) >= PASSAGE_LIMIT or budget_chars + len(passage.text) > PASSAGE_CHARS:
                continue
            seen.add(passage.passage_id)
            ordered.append(passage)
            budget_chars += len(passage.text)
    return ordered


# ── the model call ────────────────────────────────────────────────────────────────
SYSTEM = ("You audit extracted contract answers for completeness. You report only what "
          "the supplied passages state verbatim. Reply with JSON only.")

INSTRUCTIONS = """You are given one codebook question, the answer a coder already recorded, and passages retrieved from elsewhere in the same contract.

The recorded answer states the provision's MAIN rule. Contracts frequently state a DIFFERENT rule or figure for a named subgroup, and state it far away from the main article (an appendix, a schedule, a memorandum, a side letter). Your only job is to find such variations in the supplied passages.

A variation qualifies only if ALL of these hold:
- It applies to an explicitly NAMED subgroup, school level, plan option, or year: e.g. job sharers, part-time or half-time staff, per-diem staff, a named role (specialist, coordinator, department head, nurse, psychologist, counselor), elementary vs high school, a named insurance plan or coverage tier, a named fiscal or contract year.
- It states something MATERIALLY different from the recorded answer: a different number, rate, amount, cap, duration, eligibility rule, or procedure. Not a restatement, not a cross-reference, not a definition, not a mere example.
- The recorded answer OMITS it.
- The supplied passages state it. You may not infer, compute, or generalise it.

For each qualifying variation report:
- "subset": the named subgroup / level / plan / year, in the contract's own words.
- "rule": one sentence stating the differing rule, naming the subset and keeping the contract's exact figures.
- "quote": ONE unbroken verbatim span copied character-for-character from a SINGLE passage, containing the differing rule. No ellipsis. Never join text separated by other text. If you cannot copy one unbroken span that states it, do not report the variation.
- "passage_id": the passage the quote came from.

Report at most three, strongest first. If the passages contain no qualifying variation, return {"variations": []}. That is the expected outcome much of the time; an unsupported variation is worse than an omission.

Return exactly: {"variations": [{"subset": "...", "rule": "...", "quote": "...", "passage_id": 0}]}"""


def ask(client, question, answer: dict, passages: list[Passage]) -> list[dict]:
    payload = json.dumps({
        "question_id": question.qid,
        "question": question.question,
        "recorded_answer": answer.get("answer", ""),
        "recorded_evidence": answer.get("evidence", ""),
        "passages": passage_payload(passages),
    }, ensure_ascii=False)
    max_tokens = som_client.budgeted_max_tokens(SYSTEM, INSTRUCTIONS, payload)
    result = som_client.create_with_retries(
        client, model=som_client.MODEL, max_tokens=max_tokens, temperature=0,
        messages=[{"role": "system", "content": SYSTEM},
                  {"role": "user", "content": f"{INSTRUCTIONS}\n\n{payload}"}],
    )
    found = result.get("variations") or []
    return [v for v in found if isinstance(v, dict)]


# ── acceptance ────────────────────────────────────────────────────────────────────
def _content_tokens(text: str) -> set[str]:
    return {t for t in _TOKEN.findall(norm(text)) if len(t) >= 3 and t not in _STOPWORDS}


def subset_is_named(subset: str, quote: str, heading: str) -> bool:
    """The subset must actually be named where the rule is stated.

    Guards the failure mode where the model attaches a real quote to an invented
    audience ("this figure is the part-time rate") — the quote grounds, the label does
    not. Digit runs are split off alphabetic prefixes so "FY2009" can be matched by
    "2009".
    """
    tokens = _content_tokens(subset)
    if not tokens:
        return False
    context = f"{norm(quote)} {norm(heading)}"
    return any(token in context for token in tokens)


_SPAN = re.compile(r"[^\s-]+")     # splits hyphenated words, so "full-time" == "full time"
_PUNCT = re.compile(r"[^a-z0-9]")


def _compare_tokens(text: str) -> list[str]:
    """Word/number stream for alignment: hyphenation and punctuation are not signal."""
    return [_PUNCT.sub("", token) for token in _SPAN.findall(norm(text))]


def snap_quote(quote: str, passages: list[Passage],
               threshold: float = 0.92) -> str | None:
    """Realign a near-miss quote onto the source text it was transcribed from.

    A reasoning model transcribing a clause routinely drops a parenthetical numeral,
    re-hyphenates a word, or normalises "(20)" to "20", which makes an otherwise honest
    quote fail the verbatim test. This finds the passage window most similar to the
    quote word-for-word and returns *the document's* characters for that window, so
    what is recorded is source text rather than the model's typing.

    It cannot rescue a fabrication. The window has to match at `threshold` similarity,
    and every digit the model quoted has to be present in the window it is snapped to —
    so an invented figure fails here instead of being laundered into a real quote.
    """
    words = _compare_tokens(quote)
    if len(words) < 8:
        return None
    digits = {token for token in words if any(c.isdigit() for c in token)}
    best_ratio, best_text = 0.0, None
    for passage in passages:
        spans = list(_SPAN.finditer(passage.text))
        tokens = [_PUNCT.sub("", norm(span.group())) for span in spans]
        if len(tokens) < len(words):
            continue
        matcher = difflib.SequenceMatcher(a=words, b=tokens, autojunk=False)
        size, start = 0, 0
        for block in matcher.get_matching_blocks():
            if block.size > size:
                size, start = block.size, block.b - block.a
        if size < 4:
            continue
        start = max(0, min(start, len(tokens) - len(words)))
        window = tokens[start:start + len(words)]
        ratio = difflib.SequenceMatcher(a=words, b=window, autojunk=False).ratio()
        if ratio > best_ratio:
            text = passage.text[spans[start].start():spans[start + len(window) - 1].end()]
            if all(digit in norm(text) for digit in digits):
                best_ratio, best_text = ratio, text
    return best_text if best_ratio >= threshold else None


_PAGES: list[str] = []


def quote_page(quote: str, fallback: str) -> str:
    """The page the quote is actually printed on, preferring the document over the index.

    `ground()` reports the page range recorded for the passage the quote was found in,
    and for four variations in this contract that range was a page off from where the
    text really sits (the indexer attributes some appendix passages to the following
    page). Locating the quote in the form-feed-delimited document is exact where it
    succeeds; where it fails the quote straddles a page break, and the passage's range
    is then the right answer because it covers both pages.
    """
    global _PAGES
    if not _PAGES:
        _PAGES = document_pages()
    located = locate_in_document(quote, _PAGES)
    return located.page if located.contiguous and located.page.isdigit() else fallback


def accept(variations: list[dict], answer: dict,
           passages: list[Passage]) -> tuple[list[dict], list[dict]]:
    """Keep variations whose quote grounds contiguously and which add new content."""
    lookup = {p.passage_id: p for p in passages}
    baseline = _content_tokens(f"{answer.get('answer', '')} {answer.get('evidence', '')}")
    accepted: list[dict] = []
    rejected: list[dict] = []
    for variation in variations:
        subset = str(variation.get("subset") or "").strip()
        rule = str(variation.get("rule") or "").strip()
        quote = str(variation.get("quote") or "").strip()
        reason = ""
        if not (subset and rule and quote):
            reason = "incomplete variation"
        grounding = ground(quote, passages) if not reason else None
        snapped = False
        if grounding is not None and not (grounding.verbatim and grounding.contiguous):
            rescued = snap_quote(quote, passages)
            if rescued:
                quote, snapped = rescued, True
                grounding = ground(quote, passages)
        if not reason and not (grounding.verbatim and grounding.contiguous):
            reason = grounding.error or "not grounded"
        if not reason:
            heading = getattr(lookup.get(grounding.passage_id), "heading", "") or ""
            if not subset_is_named(subset, quote, heading):
                reason = "subset not named where the rule is stated"
        if not reason and not (_content_tokens(rule) - baseline):
            reason = "adds nothing the answer does not already say"
        # baseline grows as variations are accepted, so two proposals describing the
        # same subset from two angles do not both end up in the answer.
        if not reason and any(a["quote"] == quote for a in accepted):
            reason = "duplicate quote"
        if reason:
            rejected.append({"subset": subset, "rule": rule, "quote": quote,
                             "reason": reason})
            continue
        accepted.append({"subset": subset, "rule": rule, "quote": quote,
                         "page": quote_page(quote, grounding.page),
                         "passage_id": grounding.passage_id, "snapped": snapped})
        baseline |= _content_tokens(f"{subset} {rule}")
        if len(accepted) >= MAX_VARIATIONS:
            break
    return accepted, rejected


def merge(answer: dict, accepted: list[dict]) -> dict:
    """Append-only merge: the main rule first, then one sentence per named subset."""
    if not accepted:
        return answer
    merged = dict(answer)
    text = (answer.get("answer") or "").strip()
    sentences = [text.rstrip() if text.endswith((".", ";", ":")) else f"{text}."]
    for variation in accepted:
        rule = variation["rule"].strip()
        if not _content_tokens(variation["subset"]) & _content_tokens(rule):
            rule = f"For {variation['subset']}: {rule}"
        sentences.append(rule if rule.endswith(".") else f"{rule}.")
    merged["answer"] = " ".join(sentences)

    existing = [p.strip() for p in re.split(r"[;,]", str(answer.get("page") or "")) if p.strip()]
    for variation in accepted:
        if variation["page"] and variation["page"] not in existing:
            existing.append(variation["page"])
    if existing:
        merged["page"] = "; ".join(existing)

    note = ("subset enrichment: added " + "; ".join(
        f"{v['subset']} (p. {v['page']})" for v in accepted))
    merged["coder_notes"] = f"{(answer.get('coder_notes') or '').strip()} {note}".strip()
    merged["subset_variations"] = accepted
    return merged


# ── run loop ──────────────────────────────────────────────────────────────────────
_SKIP_NORMALIZED = {norm(s).replace("_", " ").rstrip(".") for s in SKIP_STATUS}


def is_substantive(answer: dict) -> bool:
    """True for answers that assert something, however tersely.

    A bare "yes" or a bare "18" counts: those are exactly the answers a completeness
    metric punishes, since they state the provision exists without stating who it
    applies to at which figure. Only the absence claims are skipped.
    """
    text = norm(answer.get("answer") or "").replace("_", " ").rstrip(".").strip()
    return bool(text) and text not in _SKIP_NORMALIZED


def load_records(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def load_cache(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    cache = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            entry = json.loads(line)
            cache[entry["key"]] = entry
    return cache


def answer_slot(answer: dict) -> str:
    """Checkpoint identity for one answer: its question plus a digest of its text.

    Upstream passes may emit the same question more than once (one record per document
    window), with the same or different answers. Keying on the question alone would let
    one window's enrichment leak onto another window's different answer; keying on file
    position would re-ask the model for text it has already judged. The digest does
    both: identical answers share one verdict, different ones get their own.
    """
    digest = hashlib.sha1(norm(answer.get("answer") or "").encode()).hexdigest()[:8]
    return f"{answer.get('question_id')}#{digest}"


def cache_key(document_id: str, slot: str, depth: int) -> str:
    return f"{document_id}|{slot}|d{depth}"


def variations_for(cache: dict[str, dict], document_id: str, slot: str,
                   before: int = MAX_DEPTH) -> list[dict]:
    """Everything accepted for one answer, across retrieval depths, deduplicated.

    `before` bounds the depths considered. A depth being re-decided must not count its
    own previous verdict as context, or replaying it would reject every variation as
    something the answer already says.
    """
    collected: list[dict] = []
    for depth in range(before):
        for variation in cache.get(cache_key(document_id, slot, depth), {}).get("accepted", []):
            if any(existing["quote"] == variation["quote"] for existing in collected):
                continue
            collected.append(variation)
    return collected[:MAX_VARIATIONS]


def write_output(path: Path, records: list[dict], cache: dict[str, dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for record in records:
        out = dict(record)
        out["answers"] = [
            merge(answer, variations_for(cache, record["document_id"],
                                         answer_slot(answer)))
            for answer in record.get("answers", [])
        ]
        lines.append(json.dumps(out, ensure_ascii=False))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--db", type=Path, default=DB_PATH)
    parser.add_argument("--limit", type=int, help="process at most N substantive answers")
    parser.add_argument("--resume", action="store_true",
                        help="reuse checkpointed answers instead of re-calling the model")
    parser.add_argument("--rescore", action="store_true",
                        help="re-apply the acceptance rules to checkpointed model "
                             "proposals and rewrite the output, with no model calls")
    parser.add_argument("--depths", type=int, default=MAX_DEPTH,
                        help="retrieval depths to try per answer; depth N reads the "
                             "passages ranked below those depth N-1 already rejected")
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()

    records = load_records(args.input)
    codebook = {question.qid: question for question in read_codebook()}
    cache_path = args.out.with_suffix(".cache.jsonl")
    cache = load_cache(cache_path) if (args.resume or args.rescore) else {}

    connection = open_database(args.db)
    client = None
    lock = threading.Lock()
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    sink = cache_path.open("a" if (args.resume or args.rescore) else "w", encoding="utf-8")
    calls = failures = 0

    def process(task):
        key, question, answer, passages = task
        try:
            return key, ask(client, question, answer, passages), answer, passages
        except Exception:                             # a dead answer, not a dead run
            return key, None, answer, passages

    for depth in range(min(args.depths, MAX_DEPTH)):
        tasks: list[tuple[str, object, dict, list[Passage]]] = []
        replays: list[tuple[str, dict, list[Passage]]] = []
        skipped = 0
        for record in records:
            for answer in record.get("answers", []):
                qid = answer.get("question_id")
                question = codebook.get(qid)
                if question is None or not is_substantive(answer):
                    skipped += 1
                    continue
                # Later depths see the answer as the earlier depths left it, so the
                # model is not asked again for a variation it has already supplied and
                # the "adds nothing new" test compares against the enriched answer.
                slot = answer_slot(answer)
                so_far = variations_for(cache, record["document_id"], slot, before=depth)
                current = merge(answer, so_far)
                key = cache_key(record["document_id"], slot, depth)
                if key in cache:
                    # Retrieval is deterministic, so the same passages can be rebuilt
                    # for free and the acceptance rules re-applied to what the model
                    # already proposed: tuning acceptance costs no model calls.
                    if args.rescore and cache[key].get("proposed"):
                        replays.append((key, current,
                                        subset_passages(connection, question, depth)))
                    continue
                if len(so_far) >= MAX_VARIATIONS:
                    continue
                if any(key == queued[0] for queued in tasks):
                    continue      # same question, same answer text, already queued
                if args.limit is not None and len(tasks) >= args.limit:
                    continue
                passages = subset_passages(connection, question, depth)
                if passages:
                    tasks.append((key, question, current, passages))
        print(f"depth {depth}: {len(tasks)} answers to ask, {len(replays)} replayed, "
              f"{skipped} non-substantive skipped", flush=True)

        for key, answer, passages in replays:
            entry = cache[key]
            entry["accepted"], entry["rejected"] = accept(entry["proposed"], answer,
                                                          passages)
        if not tasks:
            continue
        client = client or som_client.get_client()
        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
            for key, variations, answer, passages in pool.map(process, tasks):
                with lock:
                    calls += 1
                    if variations is None:
                        failures += 1
                        variations = []
                    accepted, rejected = accept(variations, answer, passages)
                    entry = {"key": key, "proposed": variations,
                             "accepted": accepted, "rejected": rejected}
                    cache[key] = entry
                    sink.write(json.dumps(entry, ensure_ascii=False) + "\n")
                    sink.flush()
                    write_output(args.out, records, cache)  # checkpoint the output too
                    if accepted:
                        print(f"  + d{depth} {key.split('|')[1].split('#')[0]}: "
                              + "; ".join(f"{v['subset']} p.{v['page']}" for v in accepted),
                              flush=True)
    sink.close()
    if args.rescore:
        # The checkpoint is rewritten wholesale so a replayed acceptance decision
        # replaces the superseded one rather than accumulating beside it.
        cache_path.write_text("".join(json.dumps(entry, ensure_ascii=False) + "\n"
                                      for entry in cache.values()), encoding="utf-8")

    write_output(args.out, records, cache)
    accepted_total = sum(len(variations_for(cache, record["document_id"],
                                            answer_slot(answer)))
                         for record in records for answer in record.get("answers", []))
    enriched = sum(1 for record in records for answer in record.get("answers", [])
                   if variations_for(cache, record["document_id"], answer_slot(answer)))
    proposed = sum(len(entry.get("proposed") or []) for entry in cache.values())
    discarded = sum(len(entry["rejected"]) for entry in cache.values())
    print(f"\ncalls={calls} failures={failures} proposed={proposed} "
          f"answers_enriched={enriched} variations_kept={accepted_total} "
          f"discarded={discarded}")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
