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
                    time: "HH:MM" - time of day to run
                For 'weekly' mode:
                    days: list of weekday names (e.g., ['monday', 'friday'])
                    time: "HH:MM" - time of day to run
        """
        self.mode = config.get('mode', 'simple').lower()
        self.config = config
        self.last_run = None

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
            time_str = self.config.get('time')
            if not time_str:
                raise ValueError(f"Missing 'time' for {self.mode} mode")
            try:
                self._parse_time(time_str)
            except ValueError as e:
                raise ValueError(f"Invalid time format '{time_str}': {e}")

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
            time_str = self.config['time']
            logger.info(f"  Schedule: Daily at {time_str}")

        elif self.mode == 'weekly':
            days = self.config['days']
            time_str = self.config['time']
            days_str = ', '.join(d.capitalize() for d in days)
            logger.info(f"  Schedule: Weekly on {days_str} at {time_str}")

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
            target_time = self._parse_time(self.config['time'])
            current_time = now.time()

            # Check if we've passed target time since last run
            if (current_time >= target_time and
                (self.last_run.date() < now.date() or
                 self.last_run.time() < target_time)):
                self.last_run = now
                return True

        elif self.mode == 'weekly':
            target_time = self._parse_time(self.config['time'])
            current_time = now.time()
            current_weekday_num = now.weekday()
            current_weekday = self.VALID_WEEKDAYS[current_weekday_num]

            # Check if today is a scheduled day
            scheduled_days = [day.lower() for day in self.config['days']]
            if current_weekday not in scheduled_days:
                return False

            # Check if we've passed target time today and haven't run yet
            if (current_time >= target_time and
                (self.last_run.date() < now.date() or
                 (self.last_run.date() == now.date() and self.last_run.time() < target_time))):
                self.last_run = now
                return True

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
            target_time = self._parse_time(self.config['time'])
            today_target = datetime.combine(now.date(), target_time)

            if now.time() < target_time:
                return f"Next check today at {self.config['time']}"
            else:
                return f"Next check tomorrow at {self.config['time']}"

        elif self.mode == 'weekly':
            target_time = self._parse_time(self.config['time'])
            scheduled_days = [self.WEEKDAY_MAP[day.lower()] for day in self.config['days']]
            current_weekday = now.weekday()

            # Find next scheduled day
            next_days = [d for d in scheduled_days if d > current_weekday or
                        (d == current_weekday and now.time() < target_time)]

            if next_days:
                next_day = min(next_days)
                next_day_name = self.VALID_WEEKDAYS[next_day]
                if next_day == current_weekday:
                    return f"Next check today at {self.config['time']}"
                return f"Next check on {next_day_name.capitalize()} at {self.config['time']}"
            else:
                # Next week
                next_day = min(scheduled_days)
                next_day_name = self.VALID_WEEKDAYS[next_day]
                return f"Next check next {next_day_name.capitalize()} at {self.config['time']}"

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
