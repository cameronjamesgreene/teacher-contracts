"""Shared Yale SOM API client (OpenAI-compatible endpoint), adaptive concurrency governor,
and retry helper.

Used by llm_extract.py, salary_schedule.py and rights_score.py instead of each defining its
own client setup / retry logic. The key is read from som_api_key.txt next to this script
(override with the SOM_API_KEY env var).

The only model on this endpoint, Qwen3.6-35B-A3B-FP8, is a reasoning model: it emits a long
chain-of-thought (returned separately as reasoning_content) that is billed against the SAME
max_tokens budget as the answer. Measured on one 150k-char prompt: 13.9s with thinking on vs
1.4s with it off. Use reasoning_kwargs(False) wherever the task is mechanical transcription
and reasoning_kwargs(True) where it is genuine judgment -- see the policy table in
docs/AGENTS.md. A trivial prompt spends 228 completion tokens thinking and 6 answering, so a
too-small max_tokens returns finish_reason="length" with EMPTY content; that is the single
most common transient failure and is retried with a larger budget.

── Context window ───────────────────────────────────────────────────────────────────────
This file previously hard-coded CTX_LIMIT = 32000 and estimated 3 chars/token. Both were
wrong, and everything expensive downstream (45k-char document chunking, 23 question
sub-batches x sections, the recovery/reconciliation re-ask passes, 3000-char rights chunks)
existed to work around the resulting phantom limit. Measured against the live endpoint:

    GET /v1/models          -> max_model_len: 131072
    response header         -> x-som-policy-output-cap: 32768
    210,000 chars of real contract text -> usage.prompt_tokens = 37,336   (5.62 chars/token)

So the old cap_text() truncated at 72,900 chars believing that was 24k tokens when it was
~13k -- the pipeline was using about a tenth of the window it had.

Enlarging the window is NOT a free win, and must be A/B'd rather than assumed. In a
controlled test on four known false negatives, whole-document recall DEGRADED at 113k
tokens (the model returned not_discussed for a salary schedule that keyword retrieval found
verbatim in an appendix) -- classic lost-in-the-middle. MAX_INPUT_TOKENS therefore defaults
to a deliberately conservative 80k (~p85 of the corpus), separately from the hard CTX_LIMIT.
Treat the window as a budget, not a target.

── Concurrency ──────────────────────────────────────────────────────────────────────────
The endpoint is not the bottleneck; the client was. Measured admission behaviour:

    16 concurrent -> 16 immediate,           0 errors,  ~0.7s each
    48 concurrent -> 44 immediate + 4 queued, 0 errors,  queue wait <= 0.7s
    96 concurrent -> 44 immediate + 32 queued + 20 REJECTED (clean HTTP 429)

i.e. ~44 in-flight is admitted, overflow is queued briefly, and true overload returns fast
429s rather than hanging. (An older operational note described a "freeze" at 8 concurrent
chunks; that is no longer the observed behaviour under scheduler phase1-rr-v1.)

x-som-global-in-flight is GLOBAL across every SOM tenant, so 44 is the shared ceiling, not
our allowance. The governor below targets SOM_MAX_INFLIGHT (default 14) and yields permits
when the global count is high, so we stay a good neighbour while still running ~2x the old
effective rate with a fraction of the calls.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

SOM_BASE_URL = "https://api.som.chat/v1"
SOM_API_KEY_FILE = Path(__file__).resolve().parent / "som_api_key.txt"
MODEL = os.environ.get("SOM_MODEL", "Qwen3.6-35B-A3B-FP8")

# Bumped whenever prompts or request-shaping change, so cache keys invalidate automatically.
PROMPT_VERSION = os.environ.get("SOM_PROMPT_VERSION", "v11")

MAX_RETRIES = int(os.environ.get("SOM_MAX_RETRIES", "4"))
RETRY_BACKOFF_SECONDS = 5

# ── context-window budgeting ──────────────────────────────────────────────────────────────
CTX_LIMIT = int(os.environ.get("SOM_CTX_LIMIT", "131072"))        # was 32000 (wrong)
OUTPUT_CAP = int(os.environ.get("SOM_OUTPUT_CAP", "32768"))       # x-som-policy-output-cap
CTX_MARGIN = 2048                                                  # headroom below the window
MIN_OUTPUT_TOKENS = 1500
DEFAULT_MAX_OUTPUT = int(os.environ.get("SOM_DEFAULT_MAX_OUTPUT", "8000"))
CHARS_PER_TOKEN = float(os.environ.get("SOM_CHARS_PER_TOKEN", "5.6"))   # measured, was 3.0

# Deliberately below CTX_LIMIT: recall degrades on very long single prompts (see module
# docstring). A/B by setting SOM_MAX_INPUT_TOKENS to 40000 / 80000 / 120000.
MAX_INPUT_TOKENS = int(os.environ.get("SOM_MAX_INPUT_TOKENS", "80000"))

# MAX_TOKENS is kept as a name for backward compatibility with existing call sites that pass
# max_tokens=MAX_TOKENS. It is now a sane output cap rather than the whole window.
MAX_TOKENS = DEFAULT_MAX_OUTPUT


def est_tokens(text: str) -> int:
    """Token estimate at the measured 5.6 chars/token, biased ~10% high for safety."""
    return int(len(text) / CHARS_PER_TOKEN * 1.1) + 1


def budgeted_max_tokens(*prompt_parts: str, min_output: int = MIN_OUTPUT_TOKENS,
                        max_output: int = DEFAULT_MAX_OUTPUT) -> int:
    """max_tokens sized so est(prompt) + max_tokens <= CTX_LIMIT - margin, clamped to
    [min_output, min(max_output, OUTPUT_CAP)]."""
    used = sum(est_tokens(p) for p in prompt_parts) + 500        # +system/format overhead
    room = CTX_LIMIT - CTX_MARGIN - used
    ceiling = min(max_output, OUTPUT_CAP)
    return max(min_output, min(ceiling, room))


def max_input_chars(reserve_output: int = MIN_OUTPUT_TOKENS,
                    prompt_overhead_tokens: int = 2500) -> int:
    """Max chars of variable text one call may include and still leave reserve_output tokens
    for the answer. Bounded by MAX_INPUT_TOKENS as well as the hard window."""
    by_window = CTX_LIMIT - CTX_MARGIN - reserve_output - prompt_overhead_tokens
    budget_tokens = max(1, min(by_window, MAX_INPUT_TOKENS))
    return int(budget_tokens * CHARS_PER_TOKEN)


def cap_text(text: str, reserve_output: int = MIN_OUTPUT_TOKENS,
             prompt_overhead_tokens: int = 2500) -> str:
    """Truncate variable text so the assembled call fits with room for the answer."""
    lim = max_input_chars(reserve_output, prompt_overhead_tokens)
    return text if len(text) <= lim else text[:lim]


def reasoning_kwargs(enabled: bool) -> dict:
    """extra_body toggling Qwen's chain-of-thought.

    Reasoning off is ~10x faster and is correct for mechanical work (transcribing an
    already-2-D salary grid, tagging grammatical features). It measurably HURTS recall on
    judgment tasks -- on four known false negatives, whole-document coding scored 3/4 with
    thinking on and 2/4 with it off -- so leave it on for anything that requires deciding
    whether a provision exists.
    """
    if enabled:
        return {}
    return {"chat_template_kwargs": {"enable_thinking": False}}


# ── adaptive concurrency governor ─────────────────────────────────────────────────────────
SOM_MAX_INFLIGHT = int(os.environ.get("SOM_MAX_INFLIGHT", "14"))
SOM_MIN_INFLIGHT = int(os.environ.get("SOM_MIN_INFLIGHT", "2"))
SOM_START_INFLIGHT = int(os.environ.get("SOM_START_INFLIGHT", "8"))
# Yield permits when the shared endpoint is this busy across ALL tenants.
SOM_GLOBAL_YIELD = int(os.environ.get("SOM_GLOBAL_YIELD", "30"))
_GROW_AFTER_CLEAN = 8          # additive increase: +1 permit per N consecutive clean calls


class _Governor:
    """AIMD permit pool driven by the endpoint's own admission headers.

    A plain Semaphore cannot shrink, so this uses a Condition and an explicit permit count.
    Growth is additive and slow; shrinkage on backpressure is immediate; a 429 halves the
    pool. 429 is treated as a control signal, not an error -- it is a clean, fast rejection
    (measured sub-second), so the right response is to back off and retry, not to fail work.
    """

    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._permits = max(SOM_MIN_INFLIGHT, min(SOM_START_INFLIGHT, SOM_MAX_INFLIGHT))
        self._in_use = 0
        self._clean_streak = 0
        self.stats = {"acquired": 0, "rate_limited": 0, "shrinks": 0, "grows": 0}

    @property
    def permits(self) -> int:
        with self._cond:
            return self._permits

    def acquire(self) -> None:
        with self._cond:
            while self._in_use >= self._permits:
                self._cond.wait(timeout=5.0)
            self._in_use += 1
            self.stats["acquired"] += 1

    def release(self) -> None:
        with self._cond:
            self._in_use = max(0, self._in_use - 1)
            self._cond.notify()

    def _resize(self, delta: int, reason: str) -> None:
        with self._cond:
            new = max(SOM_MIN_INFLIGHT, min(SOM_MAX_INFLIGHT, self._permits + delta))
            if new != self._permits:
                if new > self._permits:
                    self.stats["grows"] += 1
                else:
                    self.stats["shrinks"] += 1
                self._permits = new
                self._cond.notify_all()

    def observe(self, headers: dict) -> None:
        """Feed one successful response's admission headers back into the pool size."""
        def _int(name):
            try:
                return int(headers.get(name, ""))
            except (TypeError, ValueError):
                return None

        decision = (headers.get("x-som-admission-decision") or "").lower()
        queue_wait = _int("x-som-queue-wait-ms")
        global_inflight = _int("x-som-global-in-flight")

        if global_inflight is not None and global_inflight > SOM_GLOBAL_YIELD:
            self._clean_streak = 0
            self._resize(-1, "global-pressure")
            return
        if decision == "queued" or (queue_wait is not None and queue_wait > 250):
            self._clean_streak = 0
            self._resize(-1, "queued")
            return
        if decision == "immediate" and (queue_wait is None or queue_wait < 50):
            self._clean_streak += 1
            if self._clean_streak >= _GROW_AFTER_CLEAN:
                self._clean_streak = 0
                self._resize(+1, "clean")

    def on_rate_limit(self) -> float:
        """Halve the pool and return a jittered sleep in seconds."""
        self.stats["rate_limited"] += 1
        self._clean_streak = 0
        with self._cond:
            new = max(SOM_MIN_INFLIGHT, self._permits // 2)
            if new != self._permits:
                self.stats["shrinks"] += 1
                self._permits = new
                self._cond.notify_all()
        return 2.0 + random.random() * 3.0


GOVERNOR = _Governor()


# ── telemetry / cache sink ────────────────────────────────────────────────────────────────
# store.py registers itself here at import time. Keeping this a plain hook means the client
# owns telemetry (no call site can forget it) without som_client depending on the store.
_SINK: Optional[Any] = None


def register_sink(sink: Any) -> None:
    """Register an object with .lookup(cache_key) -> dict|None and .record(**fields)."""
    global _SINK
    _SINK = sink


def request_cache_key(**kwargs: Any) -> str:
    """sha256 over the FULL request, so any prompt/model/sampling change is a natural miss.

    The old cache keyed on (document, category, sub-batch, section index) only -- which is
    exactly why a cache written on Jul 1 and an audit written on Jun 29 could describe two
    different systems under identical filenames. Never key on metadata again.
    """
    payload = {
        "model": kwargs.get("model", MODEL),
        "prompt_version": PROMPT_VERSION,
        "messages": kwargs.get("messages"),
        "max_tokens": kwargs.get("max_tokens"),
        "temperature": kwargs.get("temperature"),
        "top_p": kwargs.get("top_p"),
        "seed": kwargs.get("seed"),
        "response_format": kwargs.get("response_format"),
        "extra_body": kwargs.get("extra_body"),
    }
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def get_client():
    import httpx
    import openai
    api_key = os.environ.get("SOM_API_KEY")
    if not api_key and SOM_API_KEY_FILE.exists():
        api_key = SOM_API_KEY_FILE.read_text(encoding="utf-8").strip()
    if not api_key:
        raise SystemExit(
            f"Error: no SOM API key found. Set the SOM_API_KEY environment variable, "
            f"or create {SOM_API_KEY_FILE} containing the key, and re-run."
        )
    return openai.OpenAI(
        api_key=api_key,
        base_url=SOM_BASE_URL,
        # Own our retries: the SDK's default 2 retries silently swallow the 429s the
        # governor needs to see, and stack multiplicatively with MAX_RETRIES below.
        max_retries=0,
        # A bare float would set a 600s CONNECT timeout, so a dead socket parked a worker
        # for ten minutes. Split it: fail fast on connect, stay patient on read.
        timeout=httpx.Timeout(connect=10.0, read=900.0, write=120.0, pool=60.0),
    )


def _strip_fences(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw[raw.index("\n") + 1:]
        if "```" in raw:
            raw = raw[:raw.rindex("```")]
    return raw.strip()


class TruncatedResponse(RuntimeError):
    """finish_reason == 'length' -- the reasoning trace ate the output budget."""


def create_with_retries(client, _stage: str = "", _document_id: str = "",
                        _qids: str = "", _use_cache: bool = True, **kwargs) -> dict:
    """Call chat.completions with governed concurrency, retries, caching and telemetry.

    Returns the parsed JSON object from the model's message content (unchanged contract from
    the previous version of this function).

    Three failure classes are handled distinctly, where the old code conflated them:
      * transient backend error / 429  -> back off (429 also shrinks the permit pool)
      * finish_reason == "length"      -> retry with a LARGER max_tokens. The old code
                                          retried with the same budget and truncated again.
      * JSONDecodeError                -> retry; on final failure raise rather than let a
                                          parse failure masquerade as an absent provision.
    """
    import openai as _openai

    kwargs.setdefault("model", MODEL)
    cache_key = request_cache_key(**kwargs)

    if _use_cache and _SINK is not None:
        hit = _SINK.lookup(cache_key)
        if hit is not None:
            return hit

    max_tokens = kwargs.get("max_tokens") or DEFAULT_MAX_OUTPUT
    last_exc: Optional[Exception] = None

    for attempt in range(1, MAX_RETRIES + 1):
        kwargs["max_tokens"] = min(int(max_tokens), OUTPUT_CAP)
        started = time.time()
        headers: dict = {}
        status = 0
        finish_reason = ""
        usage = None

        GOVERNOR.acquire()
        try:
            raw = client.chat.completions.with_raw_response.create(**kwargs)
            headers = {k.lower(): v for k, v in raw.headers.items()}
            status = getattr(raw, "status_code", 200)
            response = raw.parse()
            GOVERNOR.observe(headers)
        except _openai.RateLimitError as exc:
            last_exc = exc
            status = 429
            wait = GOVERNOR.on_rate_limit()
            _emit(_stage, _document_id, _qids, kwargs, headers, status, started,
                  None, "", attempt, str(exc))
            if attempt < MAX_RETRIES:
                time.sleep(wait)
                continue
            raise
        except Exception as exc:
            last_exc = exc
            _emit(_stage, _document_id, _qids, kwargs, headers, status, started,
                  None, "", attempt, str(exc))
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_BACKOFF_SECONDS * attempt + random.random())
                continue
            raise
        finally:
            GOVERNOR.release()

        choice = response.choices[0]
        message = choice.message
        finish_reason = choice.finish_reason or ""
        usage = response.usage

        if message.content is None or finish_reason == "length":
            # The reasoning trace consumed the whole budget. Retrying with the SAME budget
            # (what the old code did) reproduces the truncation deterministically.
            last_exc = TruncatedResponse(
                f"response truncated before the answer (finish_reason={finish_reason!r})"
            )
            _emit(_stage, _document_id, _qids, kwargs, headers, status, started,
                  usage, finish_reason, attempt, "truncated")
            if attempt < MAX_RETRIES:
                max_tokens = min(int(max_tokens * 2), OUTPUT_CAP)
                time.sleep(RETRY_BACKOFF_SECONDS * attempt)
                continue
            raise last_exc

        try:
            parsed = json.loads(_strip_fences(message.content))
        except json.JSONDecodeError as exc:
            last_exc = exc
            _emit(_stage, _document_id, _qids, kwargs, headers, status, started,
                  usage, finish_reason, attempt, "json_decode_error")
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_BACKOFF_SECONDS * attempt)
                continue
            raise

        _emit(_stage, _document_id, _qids, kwargs, headers, status, started,
              usage, finish_reason, attempt, None, response_json=parsed,
              cache_key=cache_key)
        if _use_cache and _SINK is not None:
            _SINK.put(cache_key, parsed)
        return parsed

    raise last_exc  # pragma: no cover -- the loop always returns or raises


def _emit(stage, document_id, qids, kwargs, headers, status, started,
          usage, finish_reason, attempt, error, response_json=None, cache_key=None) -> None:
    """Best-effort telemetry. Never let instrumentation break a run."""
    if _SINK is None:
        return
    try:
        def _int(name):
            try:
                return int(headers.get(name, ""))
            except (TypeError, ValueError):
                return None
        prompt_chars = sum(len(m.get("content") or "") for m in kwargs.get("messages") or [])
        details = getattr(usage, "prompt_tokens_details", None)
        # Reasoning is ON unless extra_body explicitly disabled it.
        thinking = (kwargs.get("extra_body") or {}) \
            .get("chat_template_kwargs", {}).get("enable_thinking", True)
        _SINK.record(
            cache_key=cache_key,
            stage=stage, document_id=document_id, qids=qids,
            model=kwargs.get("model"), prompt_version=PROMPT_VERSION,
            reasoning=1 if thinking else 0,
            temperature=kwargs.get("temperature"), top_p=kwargs.get("top_p"),
            seed=kwargs.get("seed"), max_tokens=kwargs.get("max_tokens"),
            prompt_chars=prompt_chars,
            prompt_tokens=getattr(usage, "prompt_tokens", None),
            cached_tokens=getattr(details, "cached_tokens", None) if details else None,
            completion_tokens=getattr(usage, "completion_tokens", None),
            reasoning_tokens=getattr(usage, "reasoning_tokens", None),
            latency_ms=int((time.time() - started) * 1000),
            queue_wait_ms=_int("x-som-queue-wait-ms"),
            admission_decision=headers.get("x-som-admission-decision"),
            global_in_flight=_int("x-som-global-in-flight"),
            estimated_cost=_int("x-som-estimated-cost"),
            policy_tier=headers.get("x-som-policy-tier"),
            permits=GOVERNOR.permits,
            http_status=status, attempt=attempt,
            finish_reason=finish_reason, error=error,
            response_json=response_json,
        )
    except Exception:
        pass
