from __future__ import annotations

import logging
import time
from collections import deque

logger = logging.getLogger(__name__)


class SlidingWindowRateLimiter:
    """
    Enforces requests-per-minute and tokens-per-minute before each LLM API call.
    Uses monotonic clock; safe for long calibration runs.
    """

    def __init__(
        self,
        *,
        requests_per_minute: int | None,
        tokens_per_minute: int | None,
        min_interval_seconds: float = 0.0,
    ) -> None:
        self._rpm = requests_per_minute
        self._tpm = tokens_per_minute
        self._min_interval = max(0.0, min_interval_seconds)
        self._request_times: deque[float] = deque()
        self._token_events: deque[tuple[float, int]] = deque()
        self._last_request_at: float | None = None

    def _prune(self, now: float) -> None:
        cutoff = now - 60.0
        while self._request_times and self._request_times[0] <= cutoff:
            self._request_times.popleft()
        while self._token_events and self._token_events[0][0] <= cutoff:
            self._token_events.popleft()

    def _tokens_in_window(self) -> int:
        return sum(t for _, t in self._token_events)

    def wait_for_slot(self, estimated_tokens: int) -> float:
        """Block until the next request is within RPM/TPM/min-interval limits. Returns seconds slept."""
        slept = 0.0
        estimated_tokens = max(1, estimated_tokens)

        while True:
            now = time.monotonic()
            self._prune(now)
            wait = 0.0

            if self._min_interval and self._last_request_at is not None:
                gap = self._min_interval - (now - self._last_request_at)
                wait = max(wait, gap)

            if self._rpm is not None and len(self._request_times) >= self._rpm:
                wait = max(wait, 60.0 - (now - self._request_times[0]) + 0.05)

            if self._tpm is not None:
                used = self._tokens_in_window()
                if used + estimated_tokens > self._tpm and self._token_events:
                    wait = max(wait, 60.0 - (now - self._token_events[0][0]) + 0.05)

            if wait <= 0:
                break
            if wait > 1.0:
                logger.info(
                    "LLM rate limit throttle: sleeping %.1fs (rpm=%s tpm=%s est_tokens=%s)",
                    wait,
                    self._rpm,
                    self._tpm,
                    estimated_tokens,
                )
            time.sleep(wait)
            slept += wait

        return slept

    def record_request(self, estimated_tokens: int) -> None:
        now = time.monotonic()
        self._prune(now)
        self._request_times.append(now)
        self._token_events.append((now, max(1, estimated_tokens)))
        self._last_request_at = now
