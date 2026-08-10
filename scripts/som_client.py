"""Shared Yale SOM API client setup (OpenAI-compatible endpoint) and retry helper.

Used by salary_schedule.py and rights_score.py instead of each defining their own
copy of the client setup / retry logic. The preferred key is SOM_HPC_LLM_API_KEY;
SOM_API_KEY and som_api_key.txt next to this script remain compatibility fallbacks.
The only model available on
this endpoint as of this writing, Qwen3.6-35B-A3B-FP8, is a reasoning model that
emits a long chain-of-thought (returned separately as reasoning_content) before its
final JSON answer, so MAX_TOKENS is set high to give it room to finish; truncated or
failed responses are retried with backoff, since the backend has been observed to
intermittently return "backend_unavailable" errors.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

SOM_BASE_URL = "https://api.som.chat/v1"
SOM_API_KEY_FILE = Path(__file__).resolve().parent / "som_api_key.txt"
MODEL = "Qwen3.6-35B-A3B-FP8"
MAX_TOKENS = 32000
MAX_RETRIES = 4
RETRY_BACKOFF_SECONDS = 5
# Losing the connection is a different failure class from a bad response, and it needs a
# far longer patience. The endpoint is reachable only over the Yale VPN, so a dropped
# tunnel, a laptop sleeping, or a backend restart takes the network away for minutes —
# while MAX_RETRIES x RETRY_BACKOFF_SECONDS gives up after about 30 seconds. Measured
# cost of that mismatch: one overnight VPN drop silently voided 41.6% of one document's
# sweep windows and 19.3% of another's. An errored window returns no hits, so nothing
# downstream can distinguish "read this and found nothing" from "never read this".
CONNECTION_RETRIES = 12
CONNECTION_BACKOFF_SECONDS = 30      # ~6 minutes of outage tolerated before giving up
# A timeout is NOT the same as a dropped connection, even though openai models it as a
# subclass of one. A dropped connection fails instantly, so 12 attempts cost ~6 minutes.
# A timeout costs the client's full request timeout (600s) *per attempt*, so the same 12
# attempts block a worker for over two hours on a single batch — measured, after this
# distinction was first missed: batches stalled 1.8, 5.4 and 5.8 hours. Timeouts get a
# small budget because each retry is expensive, and APITimeoutError must be caught
# before APIConnectionError or it inherits the wrong one.
TIMEOUT_RETRIES = 3                  # ~30 min at a 600s request timeout

# ── context-window budgeting ──────────────────────────────────────────────────────
# The model shares ONE context window (CTX_LIMIT tokens) between the prompt and the
# generated output. max_tokens is only a CAP, but the vLLM backend rejects a request when
# prompt_tokens + max_tokens exceeds the window, and a reasoning model will try to fill
# whatever cap it is given. So a fixed max_tokens=MAX_TOKENS (32000) alongside any real
# prompt can blow the 32k window (big Stage-2 document views especially). Callers must size
# max_tokens from the actual prompt with budgeted_max_tokens(), and cap large variable text
# with cap_text() so a usable output always fits.
CTX_LIMIT = int(os.environ.get("SOM_CTX_LIMIT", "32000"))
CTX_MARGIN = 1200                 # headroom kept below the hard window
MIN_OUTPUT_TOKENS = 4000          # never leave the answer less room than this
DEFAULT_MAX_OUTPUT = 16000        # cap output even when the window has more room free


def est_tokens(text: str) -> int:
    """Conservative (~3 chars/token) token estimate, biased high so we stay under limit."""
    return len(text) // 3 + 1


def budgeted_max_tokens(*prompt_parts: str, min_output: int = MIN_OUTPUT_TOKENS,
                        max_output: int = DEFAULT_MAX_OUTPUT) -> int:
    """max_tokens sized so est(prompt) + max_tokens <= CTX_LIMIT - margin, clamped to
    [min_output, max_output]. Pair with cap_text() on large inputs so it never floors
    below min_output (which would let prompt+min_output exceed the window)."""
    used = sum(est_tokens(p) for p in prompt_parts) + 500   # +system/format overhead
    room = CTX_LIMIT - CTX_MARGIN - used
    return max(min_output, min(max_output, room))


def max_input_chars(reserve_output: int = MIN_OUTPUT_TOKENS,
                    prompt_overhead_tokens: int = 2500) -> int:
    """Max chars of variable text one call may include and still leave reserve_output
    tokens for the answer (after prompt_overhead_tokens of fixed instructions/questions)."""
    return max(1, (CTX_LIMIT - CTX_MARGIN - reserve_output - prompt_overhead_tokens)) * 3


def cap_text(text: str, reserve_output: int = MIN_OUTPUT_TOKENS,
             prompt_overhead_tokens: int = 2500) -> str:
    """Truncate variable text so the assembled call fits the window with room for output."""
    lim = max_input_chars(reserve_output, prompt_overhead_tokens)
    return text if len(text) <= lim else text[:lim]


def get_client():
    import openai
    api_key = os.environ.get("SOM_HPC_LLM_API_KEY") or os.environ.get("SOM_API_KEY")
    if not api_key and SOM_API_KEY_FILE.exists():
        api_key = SOM_API_KEY_FILE.read_text(encoding="utf-8").strip()
    if not api_key:
        raise SystemExit(
            "Error: no SOM API key found. Set SOM_HPC_LLM_API_KEY (preferred) or "
            f"SOM_API_KEY, or create {SOM_API_KEY_FILE} containing the key, and re-run."
        )
    return openai.OpenAI(api_key=api_key, base_url=SOM_BASE_URL, timeout=600.0)


def _strip_fences(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw[raw.index("\n") + 1:]
        if "```" in raw:
            raw = raw[:raw.rindex("```")]
    return raw.strip()


def create_with_retries(client, **kwargs) -> dict:
    """Call chat.completions.create with retries for transient backend errors and for
    responses truncated mid-reasoning or mid-JSON. Truncation shows up two ways: (a)
    content is None (cut off before any answer text), or (b) finish_reason is "length"
    but content is non-None — a reasoning model that runs out of output tokens partway
    through writing its JSON answer, leaving syntactically incomplete content that
    raises JSONDecodeError. Both are retried with backoff rather than failing the
    chunk outright."""
    import openai as _openai
    last_exc: Exception | None = None
    attempt = 0             # bad or unusable response: the request got through
    connection_attempt = 0  # no response at all: the network is gone
    timeout_attempt = 0     # the request hung: each retry costs the full timeout
    while True:
        try:
            response = client.chat.completions.create(**kwargs)
        except _openai.APITimeoutError as exc:
            # MUST precede APIConnectionError — it is a subclass, and inheriting the
            # connection budget blocks a worker for hours on one batch.
            last_exc = exc
            timeout_attempt += 1
            if timeout_attempt >= TIMEOUT_RETRIES:
                raise
            time.sleep(RETRY_BACKOFF_SECONDS * timeout_attempt)
            continue
        except _openai.APIConnectionError as exc:
            # Counted separately and waited out for minutes, not seconds. See
            # CONNECTION_RETRIES above for why this is worth its own budget.
            last_exc = exc
            connection_attempt += 1
            if connection_attempt >= CONNECTION_RETRIES:
                raise
            time.sleep(CONNECTION_BACKOFF_SECONDS)
            continue
        except Exception as exc:
            last_exc = exc
            attempt += 1
            if attempt >= MAX_RETRIES:
                raise
            # Rate-limit errors need a much longer pause than transient errors.
            wait = 60 if isinstance(exc, _openai.RateLimitError) else RETRY_BACKOFF_SECONDS * attempt
            time.sleep(wait)
            continue
        choice = response.choices[0]
        message = choice.message
        if message.content is None or choice.finish_reason == "length":
            last_exc = RuntimeError(
                f"Response truncated before final answer (finish_reason="
                f"{choice.finish_reason!r}); increase MAX_TOKENS or retry."
            )
            attempt += 1
            if attempt >= MAX_RETRIES:
                raise last_exc
            time.sleep(RETRY_BACKOFF_SECONDS * attempt)
            continue
        try:
            return json.loads(_strip_fences(message.content))
        except json.JSONDecodeError as exc:
            last_exc = exc
            attempt += 1
            if attempt >= MAX_RETRIES:
                raise
            time.sleep(RETRY_BACKOFF_SECONDS * attempt)
            continue
