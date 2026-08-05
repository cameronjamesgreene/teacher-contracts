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
    last_exc: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.chat.completions.create(**kwargs)
        except Exception as exc:
            last_exc = exc
            if attempt < MAX_RETRIES:
                # Rate-limit errors need a much longer pause than transient errors.
                import openai as _openai
                wait = 60 if isinstance(exc, _openai.RateLimitError) else RETRY_BACKOFF_SECONDS * attempt
                time.sleep(wait)
                continue
            raise
        choice = response.choices[0]
        message = choice.message
        if message.content is None or choice.finish_reason == "length":
            last_exc = RuntimeError(
                f"Response truncated before final answer (finish_reason="
                f"{choice.finish_reason!r}); increase MAX_TOKENS or retry."
            )
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_BACKOFF_SECONDS * attempt)
                continue
            raise last_exc
        try:
            return json.loads(_strip_fences(message.content))
        except json.JSONDecodeError as exc:
            last_exc = exc
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_BACKOFF_SECONDS * attempt)
                continue
            raise
    raise last_exc  # pragma: no cover — loop always returns or raises above
