#!/usr/bin/env python3
"""Shared utilities for the contract-coding pipeline.

Provides codebook parsing, document loading, text extraction, metadata inference,
and keyword-matching helpers used by llm_extract.py and merge_llm_parts.py.
Not intended to be run directly.
"""

from __future__ import annotations

import csv
import hashlib
import os
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


# utils.py lives in contract_coding_CG/scripts/, so WORK (contract_coding_CG)
# and ROOT (contracts/, the parent containing nctq_contracts) are each one
# level deeper than the file itself.
ROOT = Path(__file__).resolve().parents[2]
WORK = Path(__file__).resolve().parents[1]
PDF_ROOT = ROOT / "nctq_contracts"
CODEBOOK = WORK / "extraction_elements_reduced.md"
README = WORK / "readme.md"
TEXT_DIR = WORK / "cache" / "extracted_text"
OCR_TEXT_DIR = WORK / "cache" / "ocr_text"
# Autonomous OCR: extract_text() decides on its own whether a document needs OCR (from the
# native-text density) and builds the override remotely via the SOM vision model, so no manual
# OCR staging, GPU allocation or ocr-examples checkout is ever needed. AUTO_OCR=0 disables it (fall back to the old behaviour of only reading a pre-built
# override). A page with fewer than AUTO_OCR_MIN_CHARS non-space chars counts as scanned; OCR
# fires when at least AUTO_OCR_MIN_SCANNED pages are scanned OR the whole document is.
AUTO_OCR = os.environ.get("AUTO_OCR", "1") == "1"
AUTO_OCR_MIN_CHARS = int(os.environ.get("AUTO_OCR_MIN_CHARS", "50"))
AUTO_OCR_MIN_SCANNED = int(os.environ.get("AUTO_OCR_MIN_SCANNED", "3"))
# The waiter timeout was sized for an olmocr2/SLURM build that could take over an hour.
# SOM-API OCR runs at ~7s/page across 8 concurrent pages, so a 300-page scan finishes in
# minutes; 4200s of blocking per document is fatal at corpus scale.
AUTO_OCR_WAIT_S = int(os.environ.get("AUTO_OCR_WAIT_S", "900"))   # concurrent-caller wait cap
# "som"  -> transcribe via the SOM vision model through som_client (default: governed,
#           cached, instrumented, no GPU allocation or ocr-examples checkout required)
# "olmocr2" -> the legacy hybrid_ocr/vLLM-on-SLURM path, kept for comparison
AUTO_OCR_ENGINE = os.environ.get("AUTO_OCR_ENGINE", "som").strip().lower()
# Output version dir. Override with CONTRACT_OUT_DIR to target a fresh run (e.g.
# output_v4) without disturbing the previous version's CSVs.
OUT_DIR = WORK / os.environ.get("CONTRACT_OUT_DIR", "output_v3")


MISSING_CODES = {"not_discussed", "discussed_unclear", "not_applicable"}


# ── quote / document-text matching (shared by llm_extract and rights_score) ──────
_NORM_RE = re.compile(r"[^a-z0-9]+")


def norm_ws(s) -> str:
    """Lowercase and reduce to alphanumeric tokens joined by single spaces, so a quote
    matches the document regardless of punctuation, hyphenation, or whitespace/line-break
    differences introduced by PDF/OCR text extraction."""
    return _NORM_RE.sub(" ", str(s).casefold()).strip()


def quote_present(quote: str, full_text_norm: str) -> bool:
    """True if `quote` is really supported by the document text (already norm_ws'd).

    Tries an exact (normalized) substring first, then falls back to 4-word-shingle
    overlap: an extracted quote is not always a verbatim contiguous span — it can
    conflate phrases that each appear in the document but not together — so a quote
    whose windows mostly occur in the text is treated as present, while a fabricated
    quote shares few/no shingles and is rejected."""
    q = norm_ws(quote)
    if len(q) < 12:
        return False
    if q in full_text_norm:
        return True
    words = q.split()
    if len(words) < 6:
        return False
    shingles = [" ".join(words[i:i + 4]) for i in range(len(words) - 3)]
    hits = sum(1 for s in shingles if s in full_text_norm)
    return hits >= max(2, int(0.6 * len(shingles)))


STATE_BY_DISTRICT = {
    "Granite School District": "UT",
    "Santa Ana Unified School District": "CA",
    "Birmingham City Schools": "AL",
    "District of Columbia Public Schools": "DC",
    "Osceola County School District": "FL",
    "Montgomery County Public Schools": "MD",
    "Prince Georges County Public Schools": "MD",
    "Northside Independent School District": "TX",
    "West Ada School District": "ID",
    "Cincinnati Public Schools": "OH",
    "San Francisco Unified School District": "CA",
    "Indianapolis Public Schools": "IN",
    "Kansas City Public Schools, MO": "MO",
    "Aldine Independent School District": "TX",
    "Pinellas County Schools": "FL",
    "Albuquerque Public Schools": "NM",
    "Minneapolis Public Schools": "MN",
    "Fresno Unified School District": "CA",
    "School District of Palm Beach County": "FL",
    "Garland Independent School District": "TX",
}


UNION_BY_DISTRICT = {
    "Granite School District": "Granite Education Association",
    "Santa Ana Unified School District": "Santa Ana Educators Association",
    "District of Columbia Public Schools": "Washington Teachers' Union",
    "Osceola County School District": "Osceola County Education Association",
    "Montgomery County Public Schools": "Montgomery County Education Association",
    "Prince Georges County Public Schools": "Prince George's County Educators' Association",
    "West Ada School District": "Meridian Education Association",
    "Cincinnati Public Schools": "Cincinnati Federation of Teachers",
    "San Francisco Unified School District": "United Educators of San Francisco",
    "Indianapolis Public Schools": "Indianapolis Education Association",
    "Kansas City Public Schools, MO": "Kansas City Federation of Teachers",
    "Pinellas County Schools": "Pinellas Classroom Teachers Association",
    "Albuquerque Public Schools": "Albuquerque Teachers Federation",
    "Minneapolis Public Schools": "Minneapolis Federation of Teachers",
    "Fresno Unified School District": "Fresno Teachers Association",
    "School District of Palm Beach County": "Classroom Teachers Association",
}


GENERIC_SYNONYMS = {
    "salary": ["compensation", "wage", "pay", "remuneration"],
    "health": ["medical", "hospitalization", "group insurance"],
    "preparation": ["prep", "planning", "conference period"],
    "grievance": ["complaint", "dispute", "appeal"],
    "layoff": ["reduction in force", "RIF", "reduction in staff", "retrenchment", "excessing"],
    "seniority": ["length of service", "continuous service", "years of service"],
    "leave": ["absence", "absences", "days"],
    "evaluation": ["appraisal", "observation", "performance"],
    "teacher": ["unit member", "bargaining unit member", "educator", "instructional employee"],
    # v9 FN fixes (Drill 1): docs phrase step movement as "increment"/"base-salary adjustment",
    # and retiree provisions as tax-deferred savings — neither reachable from the old keywords.
    "increment": ["step increment", "salary adjustment", "base salary adjustment", "annual adjustment"],
    "retiree": ["pension", "403(b)", "403b", "457", "post-employment", "supplemental retirement",
                "supplemental pension"],
    "retirement": ["pension", "403(b)", "403b", "457", "post-employment"],
}


NEGATIVE_PATTERNS = [
    re.compile(r"\bdoes\s+not\s+provide\b", re.I),
    re.compile(r"\bnot\s+available\b", re.I),
    re.compile(r"\bnot\s+eligible\b", re.I),
    re.compile(r"\bno\s+(?:health|dental|vision|life|disability|salary|benefit|insurance|leave|parking|arbitration|grievance)\b", re.I),
]


@dataclass
class Question:
    qid: str
    topic: str
    question: str
    answer_type: str
    extract: str
    keywords: str
    frequency: str
    notes: str


@dataclass
class Document:
    district: str
    file_name: str
    path: Path
    document_id: str
    text_path: Path
    text: str
    lower_text: str
    pages: list[str]
    lower_pages: list[str]
    page_count: int | None
    text_status: str


def slugify(value: str, max_len: int = 110) -> str:
    value = re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_").lower()
    return value[:max_len].strip("_")


def read_codebook() -> list[Question]:
    rows: list[Question] = []
    for line in CODEBOOK.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| "):
            continue
        if line.startswith("| Question ID") or line.startswith("|---"):
            continue
        parts = [p.strip() for p in line.strip().strip("|").split("|")]
        if len(parts) != 8:
            raise ValueError(f"Unexpected codebook row with {len(parts)} columns: {line[:120]}")
        rows.append(Question(*parts))
    return rows


def read_sample() -> list[tuple[str, str]]:
    sample: list[tuple[str, str]] = []
    in_table = False
    for line in README.read_text(encoding="utf-8").splitlines():
        if line.startswith("| District | Selected PDF |"):
            in_table = True
            continue
        if not in_table:
            continue
        if line.startswith("|---"):
            continue
        if not line.startswith("|"):
            if sample:
                break
            continue
        parts = [p.strip() for p in line.strip().strip("|").split("|")]
        if len(parts) == 2 and parts[0] and parts[1]:
            sample.append((parts[0], parts[1].strip("`")))
    if len(sample) != 40:
        raise ValueError(f"Expected 40 sampled PDFs from readme.md, found {len(sample)}")
    return sample


def pdf_page_count(path: Path) -> int | None:
    try:
        proc = subprocess.run(["pdfinfo", str(path)], text=True, capture_output=True, check=False)
    except FileNotFoundError:
        return None
    match = re.search(r"^Pages:\s+(\d+)", proc.stdout, re.M)
    return int(match.group(1)) if match else None


def _scanned_page_count(text: str) -> tuple[int, int]:
    """(scanned_pages, total_pages) for a form-feed-delimited pdftotext dump. A page with
    fewer than AUTO_OCR_MIN_CHARS non-space chars is treated as scanned/blank — the same rule
    hybrid_ocr uses to pick pages to OCR. An empty extraction (pure-image PDF with no text
    layer) counts as one fully-scanned page so it still triggers OCR."""
    pages = text.split("\f")          # "" -> [""] (one empty/scanned page), never []
    scanned = sum(1 for p in pages if len(re.sub(r"\s", "", p)) < AUTO_OCR_MIN_CHARS)
    return scanned, len(pages)


def _autoocr_override(path: Path, text_path: Path, native: str) -> str | None:
    """Autonomous, race-safe OCR. When the native pdftotext extraction looks scanned, build the
    OCR override via hybrid_ocr and return it. The build runs ONCE per document even though the
    three programs (llm/rights/salary) all call extract_text concurrently: an exclusive lockfile
    elects a single builder; the others wait for its output, and on any failure everyone degrades
    to the native text. Returns override text, or None to use the native text."""
    if not AUTO_OCR:
        return None
    scanned, total = _scanned_page_count(native)
    if total == 0 or not (scanned >= AUTO_OCR_MIN_SCANNED or (scanned and scanned == total)):
        return None  # text-native (or too few scanned pages to bother) — no OCR

    OCR_TEXT_DIR.mkdir(parents=True, exist_ok=True)
    ocr_path = OCR_TEXT_DIR / text_path.name
    lock = OCR_TEXT_DIR / (text_path.stem + ".ocr.lock")
    try:                                   # become the single builder, or fall through as a waiter
        fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode()); os.close(fd)
        builder = True
    except FileExistsError:
        builder = False

    if builder:
        try:
            district, file_name = path.parent.name, path.name
            print(f"  [auto-ocr] {file_name}: {scanned}/{total} page(s) scanned — building OCR override…")
            if AUTO_OCR_ENGINE == "som":
                # OCR through the SOM API, like every other model call: governed concurrency,
                # retry classification, request-hash cache and telemetry. The previous path
                # shelled out to olmocr2 via `uv run ... --use-hpc`, which needs the
                # ocr-examples checkout, a vLLM GPU worker and a SLURM allocation, and which
                # gave the caller no visibility into cost or failure.
                import ocr_remote          # lazy: avoids a utils<->ocr_remote load cycle
                from som_client import get_client
                res = ocr_remote.build_override(
                    get_client(), path, text_path.stem)
                print(f"  [auto-ocr] {file_name}: {res.get('status')} "
                      f"({res.get('pages_ocred', 0)} page(s) transcribed)")
            else:
                import hybrid_ocr          # lazy import: avoids a utils<->hybrid_ocr load cycle
                hybrid_ocr.build(district, file_name, AUTO_OCR_MIN_CHARS)
        except Exception as exc:
            print(f"  [auto-ocr] build FAILED for {path.name}: {exc} — using native text")
        finally:
            try:
                lock.unlink()
            except OSError:
                pass
    else:
        waited = 0                         # another program is building — wait for its output
        while waited < AUTO_OCR_WAIT_S:
            if ocr_path.exists() and ocr_path.read_text(encoding="utf-8", errors="ignore").strip():
                break
            if not lock.exists():          # builder finished/failed; use whatever exists now
                break
            time.sleep(5); waited += 5

    if ocr_path.exists():
        txt = ocr_path.read_text(encoding="utf-8", errors="ignore")
        if txt.strip():
            return txt
    return None


def extract_text(path: Path, text_path: Path) -> str:
    """Return the document's plain text.

    Resolution order:
      1. An OCR override at cache/ocr_text/<name> (same basename as text_path). When present
         and non-empty it is authoritative -- it exists precisely because pdftotext produced too
         little usable text for this document. This single hook makes every pipeline that calls
         extract_text() (llm_extract, rights_score, salary_schedule) consume OCR text with no
         per-program change.
      2. The cached pdftotext -layout extraction at text_path (a fresh run when absent).
      3. AUTONOMOUS OCR: if that native extraction looks scanned, build an OCR override on the
         spot (hybrid_ocr, race-safe across the concurrent programs) and use it. No manual OCR
         staging is ever required; a text-native document skips this untouched.
    """
    text_path.parent.mkdir(parents=True, exist_ok=True)
    ocr_path = OCR_TEXT_DIR / text_path.name
    if ocr_path.exists():
        ocr_text = ocr_path.read_text(encoding="utf-8", errors="ignore")
        if ocr_text.strip():
            return ocr_text
    if not text_path.exists():
        subprocess.run(["pdftotext", "-layout", str(path), str(text_path)], check=False)
    native = text_path.read_text(encoding="utf-8", errors="ignore") if text_path.exists() else ""
    override = _autoocr_override(path, text_path, native)
    return override if override is not None else native


def load_documents(sample: list[tuple[str, str]]) -> list[Document]:
    docs: list[Document] = []
    for district, file_name in sample:
        path = PDF_ROOT / district / file_name
        if not path.exists():
            raise FileNotFoundError(path)
        doc_hash = hashlib.sha1(str(path.relative_to(ROOT)).encode("utf-8")).hexdigest()[:8]
        document_id = f"{slugify(district, 45)}__{slugify(Path(file_name).stem, 55)}__{doc_hash}"
        text_path = TEXT_DIR / f"{document_id}.txt"
        text = extract_text(path, text_path)
        pages = text.split("\f") if text else []
        page_count = pdf_page_count(path)
        char_count = len(re.sub(r"\s+", "", text))
        if page_count and char_count < max(1000, page_count * 20):
            text_status = "ocr_needed"
        elif char_count < 1000:
            text_status = "partial_or_ocr_needed"
        else:
            text_status = "usable"
        docs.append(
            Document(
                district,
                file_name,
                path,
                document_id,
                text_path,
                text,
                text.lower(),
                pages,
                [p.lower() for p in pages],
                page_count,
                text_status,
            )
        )
    return docs


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def year4(y: str) -> int:
    y = y.strip()
    if len(y) == 4:
        return int(y)
    yy = int(y)
    return 2000 + yy if yy < 50 else 1900 + yy


def extract_years(file_name: str, text: str) -> tuple[str, str, str, str]:
    def collect(source: str) -> list[str]:
        source = re.sub(r"[_/]+", "-", source)
        out: list[str] = []
        for a, b in re.findall(r"\b(20\d{2}|19\d{2})\s*[-–]\s*(20\d{2}|19\d{2})\b", source):
            if int(b) >= int(a):
                out.append(f"{a}-{b}")
        for a, b in re.findall(r"\b(20\d{2}|19\d{2})\s*[-–]\s*(\d{2})\b", source):
            end = year4(b)
            if 0 <= end - int(a) <= 10:
                out.append(f"{a}-{end}")
        for a, b in re.findall(r"\b(\d{2})\s*[-–]\s*(\d{2})\b", source):
            start = year4(a)
            end = year4(b)
            if 0 <= end - start <= 10:
                out.append(f"{start}-{end}")
        return out

    hay = file_name + "\n" + text[:12000]
    filename_years = collect(file_name)
    school_years: list[str] = filename_years[:]
    for a, b in re.findall(r"\b(20\d{2}|19\d{2})\s*[-–]\s*(20\d{2}|19\d{2})\b", text[:12000]):
        if int(b) >= int(a):
            school_years.append(f"{a}-{b}")
    for a, b in re.findall(r"\b(20\d{2}|19\d{2})\s*[-–]\s*(\d{2})\b", text[:12000]):
        end = year4(b)
        if 0 <= end - int(a) <= 10:
            school_years.append(f"{a}-{end}")
    seen = []
    for sy in school_years:
        if sy not in seen:
            seen.append(sy)
    start_year = ""
    end_year = ""
    preferred = filename_years or seen
    if preferred:
        starts = [int(s.split("-")[0]) for s in preferred]
        ends = [int(s.split("-")[1]) for s in preferred]
        start_year = str(min(starts))
        end_year = str(max(ends))
    date_pattern = (
        r"(January|February|March|April|May|June|July|August|September|October|November|December)"
        r"\s+\d{1,2},?\s+(?:20|19)\d{2}"
    )
    dates = re.findall(date_pattern, hay)
    effective_dates = ""
    if re.search(r"effective|duration|term", hay, re.I):
        snippets = []
        for m in re.finditer(r".{0,55}(effective|duration|term).{0,120}", hay, re.I | re.S):
            snippets.append(normalize_space(m.group(0)))
            if len(snippets) >= 2:
                break
        effective_dates = " | ".join(snippets)
    return start_year, end_year, effective_dates, "; ".join(seen[:8])


def classify_document_type(file_name: str, text: str) -> str:
    hay = (file_name + "\n" + text[:5000]).lower()
    hay_s = re.sub(r"[_\-]+", " ", hay)
    if "employee handbook" in hay_s or "personnel handbook" in hay_s or "teacher handbook" in hay_s:
        return "employee handbook"
    if "policy manual" in hay_s or "board policies" in hay_s or "selected policies" in hay_s:
        return "board policy"
    if "benefits guide" in hay_s or "benefit guide" in hay_s:
        return "benefits guide"
    if "salary schedule" in hay_s and not re.search(r"collective bargaining|agreement|contract", hay_s):
        return "salary schedule"
    if "policy statement" in hay_s:
        return "policy statement"
    if "tentative agreement" in re.sub(r"[_\-]+", " ", file_name.lower()) or re.search(r"\bTA\b", file_name):
        return "other"
    if any(token in hay_s for token in ["collective bargaining agreement", "negotiated agreement", "master agreement"]):
        return "collective bargaining agreement"
    if "agreement" in hay_s or "contract" in hay_s:
        return "collective bargaining agreement"
    return "other"


def classify_bargaining_unit(text: str, doc_type: str) -> str:
    hay = text[:20000].lower()
    if "all employees" in hay and doc_type == "employee handbook":
        return "all employees"
    if "instructional employees" in hay:
        return "teachers"
    if "certificated" in hay or "certified" in hay:
        return "certified staff"
    if "teachers" in hay or "teacher" in hay:
        return "teachers"
    if doc_type == "employee handbook":
        return "all employees"
    return "unclear"


def find_union_name(district: str, text: str) -> str:
    known = UNION_BY_DISTRICT.get(district, "")
    if known and known.lower().replace("'", "") in text[:60000].lower().replace("'", ""):
        return known
    candidates = re.findall(
        r"\b([A-Z][A-Za-z.'\-]+(?:\s+[A-Z][A-Za-z.'\-]+){0,6}\s+"
        r"(?:Education Association|Educators Association|Teachers Association|Teachers Federation|Federation of Teachers|Teachers Union|Classroom Teachers Association))\b",
        text[:80000],
    )
    if candidates:
        return candidates[0]
    return known if district not in {"Aldine Independent School District", "Garland Independent School District", "Northside Independent School District", "Birmingham City Schools"} else ""


def document_notes(doc: Document, doc_type: str) -> str:
    notes = [f"text_status={doc.text_status}"]
    if doc.page_count:
        notes.append(f"pages={doc.page_count}")
    if doc.text_status != "usable":
        notes.append("full coding requires OCR or visual PDF review")
    lower_name = doc.file_name.lower()
    if "tentative" in lower_name or "_ta" in lower_name:
        notes.append("appears to be a tentative agreement or summary rather than a complete contract")
    if "flyer" in lower_name or "summary" in lower_name or "highlights" in lower_name:
        notes.append("appears to be a short settlement summary")
    if doc_type == "board policy":
        notes.append("policy document may cover all employees, students, and operations")
    return "; ".join(notes)


def build_metadata(doc: Document) -> dict[str, str]:
    doc_type = classify_document_type(doc.file_name, doc.text)
    start_year, end_year, effective_dates, school_years = extract_years(doc.file_name, doc.text)
    return {
        "document_id": doc.document_id,
        "file_name": doc.file_name,
        "district_name": doc.district,
        "state": STATE_BY_DISTRICT.get(doc.district, "unclear"),
        "document_type": doc_type,
        "bargaining_unit": classify_bargaining_unit(doc.text, doc_type),
        "start_year": start_year or "unclear",
        "end_year": end_year or "unclear",
        "effective_dates": effective_dates or "unclear",
        "school_years_covered": school_years or "unclear",
        "union_name": find_union_name(doc.district, doc.text) or "unclear",
        "source_document_notes": document_notes(doc, doc_type),
    }


def terms_from_question(question: Question) -> list[str]:
    raw = " ".join([question.keywords, question.question, question.extract])
    parts: list[str] = []
    # Keywords are already curated search terms — split on list delimiters but do NOT strip
    # leading words. The old strip mangled domain phrases ("code of ethics" -> "of ethics",
    # "state law" -> "law"), weakening the exact-phrase matching recovery/retrieval depend on.
    for chunk in re.split(r"[,;/()]", question.keywords):
        chunk = normalize_space(chunk)
        if len(chunk) >= 3:
            parts.append(chunk)
    # Question + extract are prose — strip interrogative/imperative lead-ins only (and NOT
    # "code"/"state", which are domain nouns here, not sentence starters).
    for chunk in re.split(r"[,;/()]|\bor\b|\band\b", " ".join([question.question, question.extract])):
        chunk = normalize_space(chunk)
        if not chunk:
            continue
        chunk = re.sub(r"^(does|the|what|how|is|are|extract)\s+", "", chunk, flags=re.I)
        if len(chunk) >= 3:
            parts.append(chunk)
    for key, syns in GENERIC_SYNONYMS.items():
        if re.search(rf"\b{re.escape(key)}\b", raw, re.I):
            parts.extend(syns)
    cleaned: list[str] = []
    for part in parts:
        part = part.strip(" .?*`")
        if len(part) > 80:
            continue
        if part and part.lower() not in {p.lower() for p in cleaned}:
            cleaned.append(part)
    return cleaned[:28]


def pattern_for_term(term: str) -> re.Pattern[str]:
    escaped = re.escape(term)
    escaped = escaped.replace(r"\ ", r"\s+")
    escaped = escaped.replace(r"\-", r"[-\s]?")
    return re.compile(escaped, re.I)


def find_evidence(doc: Document, terms: Iterable[str], answer_type: str = "") -> tuple[str, str, int]:
    best: tuple[str, str, int] = ("", "", 0)
    answer_type = answer_type.lower()
    for term in terms:
        if len(term) < 3:
            continue
        term_lower = term.lower()
        if term_lower not in doc.lower_text:
            continue
        pages = doc.pages or [doc.text]
        lower_pages = doc.lower_pages or [doc.lower_text]
        for page_idx, (page, lower_page) in enumerate(zip(pages, lower_pages), start=1):
            idx = lower_page.find(term_lower)
            seen_on_page = 0
            while idx >= 0 and seen_on_page < 12:
                start = max(0, idx - 180)
                end = min(len(page), idx + len(term) + 220)
                snippet = normalize_space(page[start:end])
                if len(snippet) > 500:
                    snippet = snippet[:497] + "..."
                score = len(term)
                if "dollar" in answer_type and "$" in snippet:
                    score += 100
                if "percentage" in answer_type and re.search(r"%|percent", snippet, re.I):
                    score += 100
                if "numeric" in answer_type and re.search(r"\b(days?|years?|hours?|minutes?|periods?|steps?|lanes?|weeks?)\b", snippet, re.I):
                    score += 80
                if re.search(r"\b(shall|will|must|entitled|granted|provided|required|eligible|receive|assigned)\b", snippet, re.I):
                    score += 25
                if re.search(r"\.{5,}", snippet) or "table of contents" in snippet.lower():
                    score -= 25
                if score > best[2]:
                    best = (snippet, str(page_idx), score)
                seen_on_page += 1
                idx = lower_page.find(term_lower, idx + max(1, len(term_lower)))
    return best


def extract_dollar(snippet: str) -> str:
    matches = re.findall(r"\$\s*([0-9][0-9,]*(?:\.\d+)?)", snippet)
    if matches:
        return matches[0].replace(",", "")
    return ""


def extract_percentage(snippet: str) -> str:
    matches = re.findall(r"([0-9]+(?:\.\d+)?)\s*(?:%|percent)", snippet, flags=re.I)
    return matches[0] if matches else ""


def extract_numeric(snippet: str) -> str:
    # Prefer numbers near useful units and ignore section-like decimals when possible.
    unit_match = re.search(
        r"\b([0-9]+(?:\.\d+)?)\s*(days?|hours?|minutes?|periods?|steps?|lanes?|years?|weeks?)\b",
        snippet,
        re.I,
    )
    if unit_match:
        return f"{unit_match.group(1)} {unit_match.group(2)}"
    word_values = {
        "one": 1,
        "two": 2,
        "three": 3,
        "four": 4,
        "five": 5,
        "six": 6,
        "seven": 7,
        "eight": 8,
        "nine": 9,
        "ten": 10,
        "eleven": 11,
        "twelve": 12,
        "thirteen": 13,
        "fourteen": 14,
        "fifteen": 15,
        "sixteen": 16,
        "seventeen": 17,
        "eighteen": 18,
        "nineteen": 19,
        "twenty": 20,
        "thirty": 30,
        "forty": 40,
        "forty-five": 45,
        "sixty": 60,
        "ninety": 90,
    }
    word_match = re.search(
        r"\b(" + "|".join(re.escape(k) for k in word_values) + r")\s*(days?|hours?|minutes?|periods?|steps?|lanes?|years?|weeks?)\b",
        snippet,
        re.I,
    )
    if word_match:
        return f"{word_values[word_match.group(1).lower()]} {word_match.group(2)}"
    return ""


def extract_date_value(snippet: str) -> str:
    m = re.search(r"\b(20\d{2}|19\d{2})\s*[-–]\s*(20\d{2}|19\d{2}|\d{2})\b", snippet)
    if m:
        start = int(m.group(1))
        end = year4(m.group(2))
        return f"{start}-{end}"
    m = re.search(
        r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+(20\d{2}|19\d{2})\b",
        snippet,
        re.I,
    )
    if m:
        return m.group(0)
    return ""


def is_negative(snippet: str) -> bool:
    low = snippet.lower()
    if "no strike" in low or "no work stoppage" in low:
        return False
    return any(p.search(snippet) for p in NEGATIVE_PATTERNS)


def apply_special_rules(question: Question, doc: Document, snippet: str) -> str | None:
    qid = question.qid
    full = doc.text
    low = full.lower()
    if qid == "meta_doc_type_001":
        return classify_document_type(doc.file_name, doc.text)
    if qid == "meta_effective_dates_002":
        _, _, effective_dates, school_years = extract_years(doc.file_name, doc.text)
        return effective_dates or school_years or "discussed_unclear"
    if qid == "meta_bargaining_unit_003":
        return classify_bargaining_unit(doc.text, classify_document_type(doc.file_name, doc.text))
    if qid == "meta_document_scope_004":
        return classify_document_type(doc.file_name, doc.text)
    if qid == "meta_text_usability_005":
        return doc.text_status
    if qid == "pay_salary_schedule_001":
        if re.search(r"salary\s+(schedule|scale|guide|matrix)|professional compensation", low):
            return "yes"
        return None
    return None


def answer_question(question: Question, doc: Document, metadata: dict[str, str]) -> dict[str, str]:
    if doc.text_status == "ocr_needed":
        return {
            "answer": "discussed_unclear",
            "evidence": "PDF text extraction produced too little text for reliable coding; OCR or visual review needed.",
            "page": "not_available",
            "confidence": "low",
            "coder_notes": "Scanned/image-only or failed text extraction.",
        }

    terms = terms_from_question(question)
    snippet, page, score = find_evidence(doc, terms, question.answer_type)
    special = apply_special_rules(question, doc, snippet)
    if special:
        evidence = snippet or "Metadata or document-wide pattern extracted from title/text."
        conf = "high" if question.qid.startswith("meta_") or score >= 20 else "medium"
        return {
            "answer": special,
            "evidence": evidence,
            "page": page or "document",
            "confidence": conf,
            "coder_notes": "Special extraction rule applied.",
        }

    if not snippet:
        note = "No relevant keyword or synonym match found in extractable text."
        if metadata["document_type"] in {"salary schedule", "benefits guide"} and question.topic not in {
            "document metadata",
            "compensation",
            "benefits",
        }:
            return {
                "answer": "not_applicable",
                "evidence": "Narrow document type does not cover this topic in extractable text.",
                "page": "not_applicable",
                "confidence": "medium",
                "coder_notes": note,
            }
        return {
            "answer": "not_discussed",
            "evidence": note,
            "page": "not_applicable",
            "confidence": "medium",
            "coder_notes": "",
        }

    answer_type = question.answer_type.lower()
    answer = ""
    if "dollar" in answer_type:
        answer = extract_dollar(snippet)
    elif "percentage" in answer_type:
        answer = extract_percentage(snippet)
    elif "numeric" in answer_type:
        answer = extract_numeric(snippet)
    elif "date" in answer_type:
        answer = extract_date_value(snippet)
    elif "yes/no" in answer_type:
        answer = "no" if is_negative(snippet) else "yes"
    elif "categorical" in answer_type:
        answer = normalize_space(snippet[:180])
    elif "quote" in answer_type or "short text" in answer_type:
        answer = normalize_space(snippet[:220])
    else:
        answer = "yes" if snippet else "not_discussed"

    if not answer:
        answer = "discussed_unclear"
    confidence = "high" if answer not in MISSING_CODES and answer != "discussed_unclear" else "medium"
    if answer == "discussed_unclear":
        confidence = "low" if "$" not in snippet and not re.search(r"\d", snippet) else "medium"
    return {
        "answer": answer,
        "evidence": snippet,
        "page": page or "document",
        "confidence": confidence,
        "coder_notes": "Full-text keyword/synonym match; verify manually for publication." if confidence != "high" else "",
    }


