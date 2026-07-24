"""Reliability primitives: bounded retry with backoff + per-source circuit breaker.

Both take an injectable ``sleep`` so tests exercise the backoff logic without wall-clock
delay. The circuit breaker is the "fail safely when an integration is unavailable"
requirement: after N consecutive failures a source is opened and skipped for the rest of
the run instead of retrying forever.
"""

from __future__ import annotations

from typing import Callable, Dict, TypeVar

T = TypeVar("T")


class RetryError(Exception):
    """Raised when all retry attempts are exhausted; wraps the last underlying error."""

    def __init__(self, attempts: int, last: BaseException) -> None:
        super().__init__(f"failed after {attempts} attempt(s): {last!r}")
        self.attempts = attempts
        self.last = last


def run_with_retry(
    fn: Callable[[], T],
    retries: int = 2,
    backoff_base: float = 0.2,
    sleep: Callable[[float], None] = None,  # type: ignore[assignment]
) -> T:
    """Call ``fn`` up to ``1 + retries`` times with exponential backoff between tries.

    ``retries=0`` means a single attempt. Backoff for attempt *n* (0-indexed) is
    ``backoff_base * 2**n``. Raises RetryError once attempts are exhausted.
    """
    if sleep is None:
        import time

        sleep = time.sleep
    attempts = 0
    last: BaseException = RuntimeError("no attempt made")
    total = retries + 1
    while attempts < total:
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - deliberately broad; we re-raise wrapped
            last = exc
            attempts += 1
            if attempts >= total:
                break
            sleep(backoff_base * (2 ** (attempts - 1)))
    raise RetryError(attempts, last)


class CircuitBreaker:
    """Per-source consecutive-failure breaker.

    ``record_ok`` / ``record_fail`` update per-source state; ``is_open`` tells the engine
    to skip a source whose failures reached ``threshold``. Once open it stays open for the
    run (no half-open probing — a drain run is short-lived).
    """

    def __init__(self, threshold: int = 3) -> None:
        self.threshold = threshold
        self._fails: Dict[str, int] = {}
        self._open: Dict[str, bool] = {}

    def record_ok(self, source: str) -> None:
        self._fails[source] = 0

    def record_fail(self, source: str) -> None:
        self._fails[source] = self._fails.get(source, 0) + 1
        if self._fails[source] >= self.threshold:
            self._open[source] = True

    def is_open(self, source: str) -> bool:
        return self._open.get(source, False)

    def failures(self, source: str) -> int:
        return self._fails.get(source, 0)
