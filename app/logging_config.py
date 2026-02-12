"""
Timezone-aware logging configuration for KSeF Monitor
"""

import sys
import logging

try:
    import pytz
    PYTZ_AVAILABLE = True
except ImportError:
    PYTZ_AVAILABLE = False

logger = logging.getLogger(__name__)

VALID_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


class TzFormatter(logging.Formatter):
    """Logging formatter that uses a configured timezone for timestamps"""

    def __init__(self, fmt=None, datefmt=None, tz=None):
        super().__init__(fmt, datefmt)
        self.tz = tz

    def formatTime(self, record, datefmt=None):
        from datetime import datetime
        dt = datetime.fromtimestamp(record.created, tz=self.tz)
        if datefmt:
            return dt.strftime(datefmt)
        return dt.strftime("%Y-%m-%d %H:%M:%S,%f")[:-3]


def setup_logging():
    """Initial logging setup with default (system) timezone"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )


def apply_config(config):
    """
    Reconfigure logging from config: timezone and logging level.

    Args:
        config: ConfigManager instance
    """
    # Apply logging level
    level_name = (config.get("monitoring", "logging_level", default="INFO") or "INFO").upper()
    if level_name not in VALID_LEVELS:
        logger.warning(f"Invalid logging_level '{level_name}', using INFO")
        level_name = "INFO"
    logging.root.setLevel(getattr(logging, level_name))
    logger.info(f"Logging level set to {level_name}")

    # Apply timezone
    if not PYTZ_AVAILABLE:
        logger.warning("pytz not available - logging uses system timezone")
        return

    try:
        tz_name = config.get("monitoring", "timezone", default="Europe/Warsaw")
        tz = pytz.timezone(tz_name)
        formatter = TzFormatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            tz=tz
        )
        for handler in logging.root.handlers:
            handler.setFormatter(formatter)
        logger.info(f"Logging timezone set to {tz_name}")
    except Exception as e:
        logger.warning(f"Failed to set logging timezone: {e}")
