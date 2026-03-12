"""
Sliding window rate limiter for KSeF API.

Enforces 3 concurrent limits (from KSeF OpenAPI spec):
- per second (default 10)
- per minute (default 30)
- per hour (default 120)

Thread-safe: all operations protected by threading.Lock.
Uses time.monotonic() for clock manipulation resistance.
Fail-closed: unknown state blocks requests (does not let them through).

No PII or tokens are logged — only technical metrics (remaining, wait_time).
"""

import logging
import time
import threading
from collections import deque
from typing import Dict

logger = logging.getLogger(__name__)


class RateLimiter:
    """Sliding window rate limiter with multiple time windows.

    Each API call must pass through acquire() before execution.
    If any window is full, acquire() blocks until a slot opens.
    """

    def __init__(self, per_second: int = 10, per_minute: int = 30, per_hour: int = 120):
        if per_second <= 0 or per_minute <= 0 or per_hour <= 0:
            raise ValueError("All rate limits must be positive integers")

        self._windows = [
            {"window": 1.0, "max": per_second, "timestamps": deque(), "label": "1s"},
            {"window": 60.0, "max": per_minute, "timestamps": deque(), "label": "60s"},
            {"window": 3600.0, "max": per_hour, "timestamps": deque(), "label": "3600s"},
        ]
        self._lock = threading.Lock()
        self._total_calls = 0
        self._total_waits = 0
        self._paused_until = 0.0  # monotonic time until which all requests are blocked

        logger.info(
            "Rate limiter initialized: %d/s, %d/min, %d/h",
            per_second, per_minute, per_hour,
        )

    def acquire(self, timeout: float = 3700.0) -> float:
        """Block until a request slot is available.

        Args:
            timeout: Maximum time to wait in seconds (default ~1h + buffer).
                     Prevents infinite blocking on misconfiguration.

        Returns:
            Total wait time in seconds (0.0 if no wait was needed).

        Raises:
            TimeoutError: If slot could not be acquired within timeout.
        """
        total_wait = 0.0
        deadline = time.monotonic() + timeout

        while True:
            with self._lock:
                now = time.monotonic()

                # Check forced pause (from 429 Retry-After)
                if now < self._paused_until:
                    wait = self._paused_until - now
                else:
                    wait = self._calculate_wait(now)

                if wait <= 0:
                    # Slot available — record timestamp in all windows
                    for window in self._windows:
                        window["timestamps"].append(now)
                    self._total_calls += 1
                    return total_wait

            # Fail-closed: check timeout before sleeping
            if time.monotonic() + wait > deadline:
                raise TimeoutError(
                    f"Rate limiter could not acquire slot within {timeout}s "
                    f"(waited {total_wait:.1f}s so far)"
                )

            # Wait outside lock to allow other threads
            time.sleep(wait)
            total_wait += wait
            self._total_waits += 1

            if total_wait > 5.0:
                logger.debug("Rate limiter waited %.1fs so far", total_wait)

    def _calculate_wait(self, now: float) -> float:
        """Calculate seconds to wait for the most restrictive window.

        Must be called with self._lock held.
        """
        max_wait = 0.0

        for window in self._windows:
            # Evict expired timestamps
            timestamps = window["timestamps"]
            window_size = window["window"]
            while timestamps and (now - timestamps[0]) > window_size:
                timestamps.popleft()

            if len(timestamps) >= window["max"]:
                # Window full — must wait until oldest timestamp expires
                oldest = timestamps[0]
                wait = window_size - (now - oldest) + 0.01  # +10ms buffer
                max_wait = max(max_wait, wait)

        return max_wait

    def remaining(self) -> Dict[str, int]:
        """Return remaining calls in each window and total call count.

        Returns:
            Dict with keys '1s', '60s', '3600s' (remaining slots)
            and 'total_calls', 'total_waits' (cumulative counters).
        """
        with self._lock:
            now = time.monotonic()
            result = {}

            for window in self._windows:
                timestamps = window["timestamps"]
                window_size = window["window"]
                while timestamps and (now - timestamps[0]) > window_size:
                    timestamps.popleft()
                result[window["label"]] = window["max"] - len(timestamps)

            result["total_calls"] = self._total_calls
            result["total_waits"] = self._total_waits
            return result

    def pause_until(self, seconds: float) -> None:
        """Force-pause all requests for given duration.

        Typically called after receiving HTTP 429 with Retry-After header.
        Does not affect already-waiting acquire() calls (they will re-check).

        Args:
            seconds: Duration to pause (capped at 1800s for safety).
        """
        seconds = min(max(seconds, 0), 1800.0)  # cap: 30 minutes

        with self._lock:
            pause_end = time.monotonic() + seconds
            # Only extend, never shorten an existing pause
            if pause_end > self._paused_until:
                self._paused_until = pause_end
                logger.warning(
                    "Rate limiter paused for %.0fs (429 backoff)", seconds
                )

    def reset(self) -> None:
        """Reset all windows and counters. For testing only."""
        with self._lock:
            for window in self._windows:
                window["timestamps"].clear()
            self._total_calls = 0
            self._total_waits = 0
            self._paused_until = 0.0
