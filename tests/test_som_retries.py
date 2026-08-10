"""The retry loop must terminate on every failure path, and wait out a dropped network.

Two properties, both learned from a measured failure:

1. **Losing the connection gets its own, much longer budget.** The endpoint is reachable
   only over the Yale VPN. `MAX_RETRIES` x `RETRY_BACKOFF_SECONDS` gives up after about
   30 seconds, which a dropped tunnel outlasts easily. One overnight drop silently
   voided 41.6% of one document's sweep windows and 19.3% of another's — and because an
   errored window simply returns no hits, nothing downstream could tell "read it, found
   nothing" from "never read it".

2. **Every path is bounded.** The loop was rewritten from `for attempt in range(...)` to
   `while True` to give connection errors a separate counter. That makes a missed
   increment an infinite loop against a live API rather than a test failure, so each
   path is asserted to make exactly the number of calls its budget allows.
"""

from __future__ import annotations

import json
import sys
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import openai

import som_client


def fake_client(counter: dict, exc: Exception | None = None,
                content: str | None = None, finish: str = "stop"):
    """A stand-in whose create() raises, or returns the given content."""
    class Client:
        class chat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    counter["n"] += 1
                    if exc is not None:
                        raise exc
                    message = types.SimpleNamespace(content=content)
                    return types.SimpleNamespace(
                        choices=[types.SimpleNamespace(message=message,
                                                       finish_reason=finish)])
    return Client()


class RetryBudgetTest(unittest.TestCase):
    def setUp(self) -> None:
        # Keep the real budgets, drop only the waiting.
        self._backoff = som_client.RETRY_BACKOFF_SECONDS
        self._conn_backoff = som_client.CONNECTION_BACKOFF_SECONDS
        som_client.RETRY_BACKOFF_SECONDS = 0
        som_client.CONNECTION_BACKOFF_SECONDS = 0
        self.counter = {"n": 0}

    def tearDown(self) -> None:
        som_client.RETRY_BACKOFF_SECONDS = self._backoff
        som_client.CONNECTION_BACKOFF_SECONDS = self._conn_backoff

    def test_a_good_response_costs_one_call(self) -> None:
        result = som_client.create_with_retries(
            fake_client(self.counter, content='{"answer": 1}'))
        self.assertEqual(result, {"answer": 1})
        self.assertEqual(self.counter["n"], 1)

    def test_connection_errors_get_the_long_budget(self) -> None:
        with self.assertRaises(openai.APIConnectionError):
            som_client.create_with_retries(
                fake_client(self.counter, exc=openai.APIConnectionError(request=None)))
        self.assertEqual(self.counter["n"], som_client.CONNECTION_RETRIES,
                         "a dropped network must be waited out, not given up on in "
                         "the same handful of seconds as a malformed response")
        self.assertGreater(som_client.CONNECTION_RETRIES, som_client.MAX_RETRIES)

    def test_timeouts_do_not_inherit_the_connection_budget(self) -> None:
        """APITimeoutError subclasses APIConnectionError; it must be caught first.

        A dropped connection fails instantly, so 12 retries cost ~6 minutes. A timeout
        costs the client's full 600s request timeout *per attempt*, so the same budget
        blocks a worker for over two hours on one batch — which is exactly what
        happened before these were separated.
        """
        with self.assertRaises(openai.APITimeoutError):
            som_client.create_with_retries(
                fake_client(self.counter, exc=openai.APITimeoutError(request=None)))
        self.assertEqual(self.counter["n"], som_client.TIMEOUT_RETRIES)
        self.assertLess(som_client.TIMEOUT_RETRIES, som_client.CONNECTION_RETRIES)

    def test_other_errors_keep_the_short_budget(self) -> None:
        with self.assertRaises(RuntimeError):
            som_client.create_with_retries(
                fake_client(self.counter, exc=RuntimeError("backend blew up")))
        self.assertEqual(self.counter["n"], som_client.MAX_RETRIES)

    def test_truncated_response_is_bounded(self) -> None:
        with self.assertRaises(RuntimeError):
            som_client.create_with_retries(
                fake_client(self.counter, content=None, finish="length"))
        self.assertEqual(self.counter["n"], som_client.MAX_RETRIES)

    def test_unparseable_json_is_bounded(self) -> None:
        with self.assertRaises(json.JSONDecodeError):
            som_client.create_with_retries(
                fake_client(self.counter, content="I think the answer is yes."))
        self.assertEqual(self.counter["n"], som_client.MAX_RETRIES)


if __name__ == "__main__":
    unittest.main()
