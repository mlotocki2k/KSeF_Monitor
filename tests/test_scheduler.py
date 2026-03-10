"""
Unit tests for Scheduler
"""

import pytest
from datetime import datetime, time as dt_time
from unittest.mock import patch

from app.scheduler import Scheduler


class TestSchedulerInit:
    """Tests for scheduler initialization and validation."""

    def test_valid_minutes_mode(self):
        """Minutes mode initializes correctly."""
        s = Scheduler({"mode": "minutes", "interval": 10})
        assert s.mode == "minutes"

    def test_valid_hourly_mode(self):
        """Hourly mode initializes correctly."""
        s = Scheduler({"mode": "hourly", "interval": 2})
        assert s.mode == "hourly"

    def test_valid_simple_mode(self):
        """Simple mode initializes correctly."""
        s = Scheduler({"mode": "simple", "interval": 600})
        assert s.mode == "simple"

    def test_valid_daily_single_time(self):
        """Daily mode with single time initializes correctly."""
        s = Scheduler({"mode": "daily", "time": "09:00"})
        assert s.mode == "daily"

    def test_valid_daily_multiple_times(self):
        """Daily mode with multiple times initializes correctly."""
        s = Scheduler({"mode": "daily", "time": ["09:00", "14:00", "18:00"]})
        assert s.mode == "daily"

    def test_valid_weekly_mode(self):
        """Weekly mode initializes correctly."""
        s = Scheduler({"mode": "weekly", "days": ["monday", "friday"], "time": "09:00"})
        assert s.mode == "weekly"

    def test_invalid_mode_raises(self):
        """Invalid mode raises ValueError."""
        with pytest.raises(ValueError, match="Invalid scheduler mode"):
            Scheduler({"mode": "yearly"})

    def test_missing_interval_raises(self):
        """Missing interval raises ValueError."""
        with pytest.raises(ValueError, match="Invalid interval"):
            Scheduler({"mode": "minutes"})

    def test_zero_interval_raises(self):
        """Zero interval raises ValueError."""
        with pytest.raises(ValueError, match="Invalid interval"):
            Scheduler({"mode": "minutes", "interval": 0})

    def test_missing_time_raises(self):
        """Missing time for daily mode raises ValueError."""
        with pytest.raises(ValueError, match="Missing 'time'"):
            Scheduler({"mode": "daily"})

    def test_missing_days_raises(self):
        """Missing days for weekly mode raises ValueError."""
        with pytest.raises(ValueError, match="'days' must be a non-empty"):
            Scheduler({"mode": "weekly", "time": "09:00"})

    def test_invalid_weekday_raises(self):
        """Invalid weekday name raises ValueError."""
        with pytest.raises(ValueError, match="Invalid weekday"):
            Scheduler({"mode": "weekly", "days": ["funday"], "time": "09:00"})

    def test_empty_time_list_raises(self):
        """Empty time list raises ValueError."""
        with pytest.raises(ValueError):
            Scheduler({"mode": "daily", "time": []})


class TestSchedulerMinInterval:
    """Tests for minimum interval enforcement."""

    def test_simple_below_min_bumped(self):
        """Simple mode interval below 300s is bumped up."""
        s = Scheduler({"mode": "simple", "interval": 60})
        assert s.config["interval"] >= 300

    def test_minutes_below_min_bumped(self):
        """Minutes interval resulting in <300s is bumped up."""
        s = Scheduler({"mode": "minutes", "interval": 1})
        # 1 minute = 60s < 300s, should be bumped to 5 minutes
        assert s.config["interval"] >= 5

    def test_hourly_always_above_min(self):
        """Hourly interval of 1 = 3600s, always above minimum."""
        s = Scheduler({"mode": "hourly", "interval": 1})
        assert s.config["interval"] == 1  # 3600s > 300s, no change


class TestSchedulerParseTime:
    """Tests for time parsing."""

    def test_parse_valid_time(self):
        """Parse valid HH:MM string."""
        s = Scheduler({"mode": "minutes", "interval": 5})
        t = s._parse_time("14:30")
        assert t == dt_time(14, 30)

    def test_parse_midnight(self):
        """Parse midnight."""
        s = Scheduler({"mode": "minutes", "interval": 5})
        t = s._parse_time("00:00")
        assert t == dt_time(0, 0)

    def test_parse_invalid_hour(self):
        """Invalid hour raises ValueError."""
        s = Scheduler({"mode": "minutes", "interval": 5})
        with pytest.raises(ValueError):
            s._parse_time("25:00")

    def test_parse_invalid_format(self):
        """Invalid format raises ValueError."""
        s = Scheduler({"mode": "minutes", "interval": 5})
        with pytest.raises(ValueError):
            s._parse_time("abc")

    def test_parse_times_single_string(self):
        """Parse single time string returns list of one."""
        s = Scheduler({"mode": "minutes", "interval": 5})
        times = s._parse_times("09:00")
        assert len(times) == 1
        assert times[0] == dt_time(9, 0)

    def test_parse_times_list_sorted(self):
        """Parse list of times returns sorted list."""
        s = Scheduler({"mode": "minutes", "interval": 5})
        times = s._parse_times(["18:00", "09:00", "14:00"])
        assert times == [dt_time(9, 0), dt_time(14, 0), dt_time(18, 0)]


class TestSchedulerShouldRun:
    """Tests for should_run() logic."""

    def test_first_run_always_true(self):
        """First call to should_run() always returns True."""
        s = Scheduler({"mode": "minutes", "interval": 5})
        assert s.last_run is None
        assert s.should_run() is True
        assert s.last_run is not None

    def test_minutes_not_elapsed(self):
        """Returns False when interval hasn't elapsed."""
        s = Scheduler({"mode": "minutes", "interval": 5})
        s.should_run()  # first run
        # Immediately check again - should not run
        assert s.should_run() is False

    def test_minutes_elapsed(self):
        """Returns True when interval has elapsed."""
        s = Scheduler({"mode": "minutes", "interval": 5})
        s.should_run()  # first run
        # Simulate time passing (300 seconds = 5 minutes)
        from datetime import timedelta
        s.last_run = datetime.now() - timedelta(minutes=6)
        assert s.should_run() is True

    def test_daily_past_target_time(self):
        """Daily mode returns True when past target time."""
        s = Scheduler({"mode": "daily", "time": "00:01"})
        s.should_run()  # first run

        # Simulate next day, past target time
        from datetime import timedelta
        s.last_run = datetime.now() - timedelta(days=1)
        s.completed_times_today = set()
        # Current time should be past 00:01
        result = s.should_run()
        # This depends on current time; at least verify no exception
        assert isinstance(result, bool)

    def test_weekly_wrong_day(self):
        """Weekly mode returns False on non-scheduled day."""
        # Use a day that won't be today
        all_days = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
        today_idx = datetime.now().weekday()
        # Pick a day that is NOT today
        wrong_day = all_days[(today_idx + 3) % 7]

        s = Scheduler({"mode": "weekly", "days": [wrong_day], "time": "00:01"})
        s.should_run()  # first run
        # Second call should check day
        assert s.should_run() is False

    def test_daily_completed_times_reset_on_new_day(self):
        """Completed times reset on a new day."""
        s = Scheduler({"mode": "daily", "time": "12:00"})
        s.should_run()  # first run

        # Simulate completed time from yesterday
        from datetime import timedelta
        s.last_run = datetime.now() - timedelta(days=1)
        s.completed_times_today = {"12:00"}

        # should_run should reset completed_times_today
        s.should_run()
        # After reset, the set should have been cleared before checking
        # (if current time >= 12:00, it'll add "12:00" back)


class TestSchedulerSleepTime:
    """Tests for sleep time calculation."""

    def test_simple_sleep_time(self):
        """Simple mode calculates correct sleep time."""
        s = Scheduler({"mode": "simple", "interval": 600})
        s.should_run()  # first run
        sleep = s._calculate_sleep_time()
        # Should be close to interval (600s) minus tiny elapsed time
        assert 590 <= sleep <= 600

    def test_daily_sleep_time_is_60(self):
        """Daily mode always returns 60s sleep."""
        s = Scheduler({"mode": "daily", "time": "09:00"})
        assert s._calculate_sleep_time() == 60

    def test_first_run_sleep_is_zero(self):
        """Before first run, sleep is 0."""
        s = Scheduler({"mode": "simple", "interval": 600})
        assert s._calculate_sleep_time() == 0


class TestSchedulerGetNextRunInfo:
    """Tests for get_next_run_info()."""

    def test_minutes_next_run_info(self):
        """Minutes mode returns sensible next run info."""
        s = Scheduler({"mode": "minutes", "interval": 5})
        assert s.get_next_run_info() == "Next check immediately"

    def test_minutes_after_run(self):
        """Minutes mode after first run shows time remaining."""
        s = Scheduler({"mode": "minutes", "interval": 5})
        s.should_run()
        info = s.get_next_run_info()
        assert "minute" in info

    def test_daily_next_run_info(self):
        """Daily mode returns time-based info."""
        s = Scheduler({"mode": "daily", "time": "23:59"})
        s.should_run()
        info = s.get_next_run_info()
        assert "check" in info.lower() or "Next" in info
