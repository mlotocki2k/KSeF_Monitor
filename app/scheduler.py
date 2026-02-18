"""
Scheduler module for flexible check scheduling
Supports multiple scheduling modes: minutes, hourly, daily, weekly
"""

import logging
import time
from datetime import datetime, time as dt_time
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class Scheduler:
    """Flexible scheduler supporting multiple scheduling modes"""

    VALID_WEEKDAYS = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
    WEEKDAY_MAP = {
        'monday': 0, 'tuesday': 1, 'wednesday': 2, 'thursday': 3,
        'friday': 4, 'saturday': 5, 'sunday': 6
    }

    def __init__(self, config: Dict):
        """
        Initialize scheduler with configuration

        Args:
            config: Schedule configuration dictionary
                mode: 'simple' | 'minutes' | 'hourly' | 'daily' | 'weekly'
                For 'simple' mode:
                    interval: seconds between checks
                For 'minutes' mode:
                    interval: minutes between checks
                For 'hourly' mode:
                    interval: hours between checks
                For 'daily' mode:
                    time: "HH:MM" or ["HH:MM", "HH:MM", ...] - time(s) of day to run
                For 'weekly' mode:
                    days: list of weekday names (e.g., ['monday', 'friday'])
                    time: "HH:MM" or ["HH:MM", "HH:MM", ...] - time(s) of day to run
        """
        self.mode = config.get('mode', 'simple').lower()
        self.config = config
        self.last_run = None
        self.completed_times_today = set()  # Track completed times for current day

        self._validate_config()
        logger.info(f"Scheduler initialized with mode: {self.mode}")
        self._log_schedule_info()

    def _validate_config(self):
        """Validate scheduler configuration"""
        if self.mode not in ['simple', 'minutes', 'hourly', 'daily', 'weekly']:
            raise ValueError(f"Invalid scheduler mode: {self.mode}")

        if self.mode in ['simple', 'minutes', 'hourly']:
            interval = self.config.get('interval')
            if not interval or not isinstance(interval, (int, float)) or interval <= 0:
                raise ValueError(f"Invalid interval for {self.mode} mode: {interval}")

        elif self.mode in ['daily', 'weekly']:
            time_config = self.config.get('time')
            if not time_config:
                raise ValueError(f"Missing 'time' for {self.mode} mode")

            # Validate time(s) - can be string or list
            try:
                self._parse_times(time_config)
            except ValueError as e:
                raise ValueError(f"Invalid time format: {e}")

            if self.mode == 'weekly':
                days = self.config.get('days', [])
                if not days or not isinstance(days, list):
                    raise ValueError("'days' must be a non-empty list for weekly mode")
                for day in days:
                    if day.lower() not in self.VALID_WEEKDAYS:
                        raise ValueError(f"Invalid weekday: {day}")

    def _parse_time(self, time_str: str) -> dt_time:
        """Parse time string in HH:MM format"""
        try:
            hour, minute = map(int, time_str.split(':'))
            if not (0 <= hour < 24 and 0 <= minute < 60):
                raise ValueError("Hour must be 0-23, minute must be 0-59")
            return dt_time(hour, minute)
        except Exception as e:
            raise ValueError(f"Time must be in HH:MM format: {e}")

    def _parse_times(self, time_config) -> List[dt_time]:
        """
        Parse time configuration - can be single string or list of strings

        Args:
            time_config: Either "HH:MM" or ["HH:MM", "HH:MM", ...]

        Returns:
            List of dt_time objects, sorted chronologically
        """
        if isinstance(time_config, str):
            return [self._parse_time(time_config)]
        elif isinstance(time_config, list):
            if not time_config:
                raise ValueError("Time list cannot be empty")
            times = [self._parse_time(t) for t in time_config]
            return sorted(times)
        else:
            raise ValueError("Time must be a string or list of strings")

    def _log_schedule_info(self):
        """Log human-readable schedule information"""
        if self.mode == 'simple':
            interval = self.config['interval']
            logger.info(f"  Schedule: Every {interval} seconds")

        elif self.mode == 'minutes':
            interval = self.config['interval']
            logger.info(f"  Schedule: Every {interval} minute(s)")

        elif self.mode == 'hourly':
            interval = self.config['interval']
            logger.info(f"  Schedule: Every {interval} hour(s)")

        elif self.mode == 'daily':
            times = self._parse_times(self.config['time'])
            if len(times) == 1:
                logger.info(f"  Schedule: Daily at {times[0].strftime('%H:%M')}")
            else:
                times_str = ', '.join(t.strftime('%H:%M') for t in times)
                logger.info(f"  Schedule: Daily at {times_str} ({len(times)} times per day)")

        elif self.mode == 'weekly':
            days = self.config['days']
            times = self._parse_times(self.config['time'])
            days_str = ', '.join(d.capitalize() for d in days)
            if len(times) == 1:
                logger.info(f"  Schedule: Weekly on {days_str} at {times[0].strftime('%H:%M')}")
            else:
                times_str = ', '.join(t.strftime('%H:%M') for t in times)
                logger.info(f"  Schedule: Weekly on {days_str} at {times_str} ({len(times)} times per day)")

    def should_run(self) -> bool:
        """
        Check if it's time to run based on schedule

        Returns:
            True if check should run now, False otherwise
        """
        now = datetime.now()

        # First run always executes
        if self.last_run is None:
            self.last_run = now
            return True

        if self.mode == 'simple':
            elapsed = (now - self.last_run).total_seconds()
            if elapsed >= self.config['interval']:
                self.last_run = now
                return True

        elif self.mode == 'minutes':
            elapsed = (now - self.last_run).total_seconds()
            interval_seconds = self.config['interval'] * 60
            if elapsed >= interval_seconds:
                self.last_run = now
                return True

        elif self.mode == 'hourly':
            elapsed = (now - self.last_run).total_seconds()
            interval_seconds = self.config['interval'] * 3600
            if elapsed >= interval_seconds:
                self.last_run = now
                return True

        elif self.mode == 'daily':
            times = self._parse_times(self.config['time'])
            current_time = now.time()

            # Reset completed times if it's a new day
            if self.last_run and self.last_run.date() < now.date():
                self.completed_times_today = set()

            # Find next scheduled time that hasn't been completed today
            for target_time in times:
                time_key = target_time.strftime('%H:%M')
                if time_key in self.completed_times_today:
                    continue

                # Check if we've passed this target time
                if current_time >= target_time:
                    self.last_run = now
                    self.completed_times_today.add(time_key)
                    return True

            return False

        elif self.mode == 'weekly':
            times = self._parse_times(self.config['time'])
            current_time = now.time()
            current_weekday_num = now.weekday()
            current_weekday = self.VALID_WEEKDAYS[current_weekday_num]

            # Check if today is a scheduled day
            scheduled_days = [day.lower() for day in self.config['days']]
            if current_weekday not in scheduled_days:
                return False

            # Reset completed times if it's a new day
            if self.last_run and self.last_run.date() < now.date():
                self.completed_times_today = set()

            # Find next scheduled time that hasn't been completed today
            for target_time in times:
                time_key = target_time.strftime('%H:%M')
                if time_key in self.completed_times_today:
                    continue

                # Check if we've passed this target time
                if current_time >= target_time:
                    self.last_run = now
                    self.completed_times_today.add(time_key)
                    return True

            return False

        return False

    def get_next_run_info(self) -> str:
        """
        Get human-readable info about next scheduled run

        Returns:
            String describing when next run will occur
        """
        now = datetime.now()

        if self.mode == 'simple':
            interval = self.config['interval']
            if self.last_run:
                elapsed = (now - self.last_run).total_seconds()
                remaining = max(0, interval - elapsed)
                return f"Next check in {int(remaining)} seconds"
            return "Next check immediately"

        elif self.mode == 'minutes':
            interval = self.config['interval']
            if self.last_run:
                elapsed = (now - self.last_run).total_seconds()
                interval_seconds = interval * 60
                remaining = max(0, interval_seconds - elapsed)
                remaining_minutes = int(remaining / 60)
                return f"Next check in {remaining_minutes} minute(s)"
            return "Next check immediately"

        elif self.mode == 'hourly':
            interval = self.config['interval']
            if self.last_run:
                elapsed = (now - self.last_run).total_seconds()
                interval_seconds = interval * 3600
                remaining = max(0, interval_seconds - elapsed)
                remaining_hours = int(remaining / 3600)
                return f"Next check in {remaining_hours} hour(s)"
            return "Next check immediately"

        elif self.mode == 'daily':
            times = self._parse_times(self.config['time'])
            current_time = now.time()

            # Find next time today that hasn't been completed
            for target_time in times:
                time_key = target_time.strftime('%H:%M')
                if time_key not in self.completed_times_today and current_time < target_time:
                    return f"Next check today at {time_key}"

            # All times for today are done or passed, show first time tomorrow
            next_time = times[0].strftime('%H:%M')
            return f"Next check tomorrow at {next_time}"

        elif self.mode == 'weekly':
            times = self._parse_times(self.config['time'])
            scheduled_days = [self.WEEKDAY_MAP[day.lower()] for day in self.config['days']]
            current_weekday = now.weekday()
            current_time = now.time()

            # Check if there's a time remaining today (if today is a scheduled day)
            if current_weekday in scheduled_days:
                for target_time in times:
                    time_key = target_time.strftime('%H:%M')
                    if time_key not in self.completed_times_today and current_time < target_time:
                        return f"Next check today at {time_key}"

            # Find next scheduled day
            next_days = [d for d in scheduled_days if d > current_weekday]

            if next_days:
                next_day = min(next_days)
                next_day_name = self.VALID_WEEKDAYS[next_day]
                next_time = times[0].strftime('%H:%M')
                return f"Next check on {next_day_name.capitalize()} at {next_time}"
            else:
                # Next week
                next_day = min(scheduled_days)
                next_day_name = self.VALID_WEEKDAYS[next_day]
                next_time = times[0].strftime('%H:%M')
                return f"Next check next {next_day_name.capitalize()} at {next_time}"

        return "Unknown"

    def wait_until_next_run(self):
        """Sleep until it's time for the next run"""
        sleep_time = self._calculate_sleep_time()
        if sleep_time > 0:
            logger.info(f"Waiting {sleep_time} seconds until next check...")
            time.sleep(sleep_time)

    def _calculate_sleep_time(self) -> int:
        """Calculate how many seconds to sleep before next check"""
        now = datetime.now()

        if self.mode == 'simple':
            if self.last_run is None:
                return 0
            elapsed = (now - self.last_run).total_seconds()
            return max(1, int(self.config['interval'] - elapsed))

        elif self.mode == 'minutes':
            if self.last_run is None:
                return 0
            elapsed = (now - self.last_run).total_seconds()
            interval_seconds = self.config['interval'] * 60
            return max(1, int(interval_seconds - elapsed))

        elif self.mode == 'hourly':
            if self.last_run is None:
                return 0
            elapsed = (now - self.last_run).total_seconds()
            interval_seconds = self.config['interval'] * 3600
            return max(1, int(interval_seconds - elapsed))

        elif self.mode in ['daily', 'weekly']:
            # For time-based schedules, check every minute
            return 60

        return 1
