"""
Tests for app.rate_limiter — sliding window rate limiter.

Tests cover:
- Basic acquire/remaining semantics
- Window enforcement (slots fill up → acquire blocks)
- pause_until (429 backoff)
- Timeout handling
- Thread safety
- Reset
"""

import threading
import time
from unittest.mock import patch

import pytest

from app.rate_limiter import RateLimiter


class TestRateLimiterInit:
    """Constructor validation."""

    def test_valid_defaults(self):
        rl = RateLimiter()
        remaining = rl.remaining()
        assert remaining["1s"] == 10
        assert remaining["60s"] == 30
        assert remaining["3600s"] == 120

    def test_custom_limits(self):
        rl = RateLimiter(per_second=5, per_minute=20, per_hour=50)
        remaining = rl.remaining()
        assert remaining["1s"] == 5
        assert remaining["60s"] == 20
        assert remaining["3600s"] == 50

    def test_zero_per_second_raises(self):
        with pytest.raises(ValueError, match="positive"):
            RateLimiter(per_second=0)

    def test_negative_per_minute_raises(self):
        with pytest.raises(ValueError, match="positive"):
            RateLimiter(per_minute=-1)

    def test_negative_per_hour_raises(self):
        with pytest.raises(ValueError, match="positive"):
            RateLimiter(per_hour=-5)


class TestRateLimiterAcquire:
    """acquire() behavior — slot allocation and blocking."""

    def test_acquire_returns_zero_when_slots_available(self):
        rl = RateLimiter(per_second=10, per_minute=30, per_hour=120)
        wait = rl.acquire()
        assert wait == 0.0

    def test_acquire_decrements_remaining(self):
        rl = RateLimiter(per_second=3, per_minute=100, per_hour=1000)
        rl.acquire()
        remaining = rl.remaining()
        assert remaining["1s"] == 2

    def test_acquire_fills_all_windows(self):
        rl = RateLimiter(per_second=5, per_minute=100, per_hour=1000)
        for _ in range(5):
            rl.acquire()
        remaining = rl.remaining()
        assert remaining["1s"] == 0
        assert remaining["60s"] == 95
        assert remaining["3600s"] == 995

    def test_acquire_blocks_when_per_second_full(self):
        """When per_second window is full, acquire must wait."""
        rl = RateLimiter(per_second=2, per_minute=100, per_hour=1000)
        rl.acquire()
        rl.acquire()
        # Third call should block and return positive wait time
        start = time.monotonic()
        wait = rl.acquire()
        elapsed = time.monotonic() - start
        assert wait > 0
        assert elapsed >= 0.5  # Should wait ~1s for slot, at least 0.5s

    def test_acquire_respects_minute_window(self):
        """Per-minute window limits even if per-second has slots."""
        rl = RateLimiter(per_second=100, per_minute=2, per_hour=1000)
        rl.acquire()
        rl.acquire()
        # Third call limited by minute window — would take ~60s
        # We use timeout to avoid waiting
        with pytest.raises(TimeoutError):
            rl.acquire(timeout=0.1)

    def test_acquire_timeout_raises(self):
        rl = RateLimiter(per_second=1, per_minute=1, per_hour=1000)
        rl.acquire()
        with pytest.raises(TimeoutError, match="could not acquire"):
            rl.acquire(timeout=0.05)

    def test_total_calls_incremented(self):
        rl = RateLimiter(per_second=10, per_minute=30, per_hour=120)
        for _ in range(5):
            rl.acquire()
        remaining = rl.remaining()
        assert remaining["total_calls"] == 5


class TestRateLimiterRemaining:
    """remaining() — slot counts and counters."""

    def test_remaining_fresh(self):
        rl = RateLimiter(per_second=10, per_minute=30, per_hour=120)
        r = rl.remaining()
        assert r["1s"] == 10
        assert r["60s"] == 30
        assert r["3600s"] == 120
        assert r["total_calls"] == 0
        assert r["total_waits"] == 0

    def test_remaining_after_calls(self):
        rl = RateLimiter(per_second=10, per_minute=30, per_hour=120)
        rl.acquire()
        rl.acquire()
        r = rl.remaining()
        assert r["1s"] == 8
        assert r["60s"] == 28
        assert r["3600s"] == 118
        assert r["total_calls"] == 2


class TestRateLimiterPauseUntil:
    """pause_until() — forced pause from 429 Retry-After."""

    def test_pause_blocks_acquire(self):
        rl = RateLimiter(per_second=100, per_minute=1000, per_hour=10000)
        rl.pause_until(0.5)
        start = time.monotonic()
        rl.acquire()
        elapsed = time.monotonic() - start
        assert elapsed >= 0.4  # Should wait ~0.5s

    def test_pause_capped_at_1800(self):
        """Pause duration capped at 30 minutes."""
        rl = RateLimiter()
        rl.pause_until(5000)
        with rl._lock:
            # _paused_until should be ~1800s from now, not 5000s
            remaining_pause = rl._paused_until - time.monotonic()
            assert remaining_pause <= 1800
            assert remaining_pause > 1700  # Approximately 1800

    def test_pause_negative_ignored(self):
        rl = RateLimiter()
        rl.pause_until(-10)
        # Should not block
        wait = rl.acquire()
        assert wait == 0.0

    def test_pause_only_extends(self):
        """Shorter pause does not shorten existing longer pause."""
        rl = RateLimiter()
        rl.pause_until(2.0)
        with rl._lock:
            first_pause_end = rl._paused_until
        rl.pause_until(0.5)
        with rl._lock:
            # Should not have changed (0.5 < 2.0 remaining)
            assert rl._paused_until == first_pause_end


class TestRateLimiterReset:
    """reset() — clears all state."""

    def test_reset_clears_windows(self):
        rl = RateLimiter(per_second=2, per_minute=100, per_hour=1000)
        rl.acquire()
        rl.acquire()
        assert rl.remaining()["1s"] == 0
        rl.reset()
        r = rl.remaining()
        assert r["1s"] == 2
        assert r["total_calls"] == 0
        assert r["total_waits"] == 0

    def test_reset_clears_pause(self):
        rl = RateLimiter()
        rl.pause_until(100)
        rl.reset()
        wait = rl.acquire()
        assert wait == 0.0


class TestRateLimiterThreadSafety:
    """Concurrent access must not corrupt state."""

    def test_concurrent_acquire(self):
        """Multiple threads acquiring slots simultaneously."""
        rl = RateLimiter(per_second=100, per_minute=1000, per_hour=10000)
        errors = []

        def worker():
            try:
                for _ in range(10):
                    rl.acquire()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert not errors
        assert rl.remaining()["total_calls"] == 50

    def test_concurrent_remaining_no_crash(self):
        """remaining() called concurrently with acquire() must not crash."""
        rl = RateLimiter(per_second=100, per_minute=1000, per_hour=10000)
        errors = []

        def acquirer():
            try:
                for _ in range(20):
                    rl.acquire()
            except Exception as e:
                errors.append(e)

        def reader():
            try:
                for _ in range(20):
                    rl.remaining()
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=acquirer),
            threading.Thread(target=reader),
            threading.Thread(target=reader),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert not errors
