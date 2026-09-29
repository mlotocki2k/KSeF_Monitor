"""
Schema migration at startup must not reconfigure the app's logging: alembic's
fileConfig() disabled every logger created before it (e.g. __main__) and
replaced the root handlers, so most startup/monitor logs vanished.
"""

import logging

from app.database import Database


def test_create_tables_keeps_existing_loggers_and_handlers(tmp_path):
    early = logging.getLogger("app.test_pre_existing_logger")
    early.disabled = False
    root = logging.getLogger()
    handlers_before = list(root.handlers)

    Database(str(tmp_path / "fresh.db")).create_tables()

    assert early.disabled is False
    assert root.handlers == handlers_before
