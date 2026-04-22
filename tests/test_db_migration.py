"""Tests for DB schema migration via alembic (Task 9 / v0.4 F-07)."""
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text


def _get_tables(db_path: str):
    engine = create_engine(f"sqlite:///{db_path}")
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


@pytest.fixture
def fresh_db_path(tmp_path):
    """Path to a fresh SQLite DB file (not yet created)."""
    return str(tmp_path / "fresh.db")


class TestDBMigration:
    """Fresh DB must have all v0.5 tables after `create_tables`."""

    # Actual tables from the 4 alembic phase migrations (no push_devices —
    # that model does not exist in this codebase).
    REQUIRED_TABLES = {
        "invoices",
        "monitor_state",
        "notification_log",
        "api_request_log",
        "invoice_artifacts",
        "push_instances",
        "initial_load_jobs",
        "alembic_version",
    }

    def test_fresh_db_has_all_tables(self, fresh_db_path):
        from app.database import Database
        db = Database(fresh_db_path)
        db.create_tables()
        tables = _get_tables(fresh_db_path)
        missing = self.REQUIRED_TABLES - tables
        assert not missing, f"missing tables: {missing}"

    def test_create_tables_is_idempotent(self, fresh_db_path):
        from app.database import Database
        db = Database(fresh_db_path)
        db.create_tables()
        tables_after_first = _get_tables(fresh_db_path)

        # Run again — must not error
        db2 = Database(fresh_db_path)
        db2.create_tables()
        tables_after_second = _get_tables(fresh_db_path)

        assert tables_after_first == tables_after_second

    def test_alembic_version_marks_head(self, fresh_db_path):
        """After create_tables, alembic_version.version_num matches head."""
        from app.database import Database
        db = Database(fresh_db_path)
        db.create_tables()
        engine = create_engine(f"sqlite:///{fresh_db_path}")
        try:
            with engine.connect() as conn:
                row = conn.execute(
                    text("SELECT version_num FROM alembic_version")
                ).first()
                assert row is not None, "alembic_version table has no row"
                # d9e0f1g2h345 is the head (phase4_initial_load_jobs)
                assert row[0] == "d9e0f1g2h345", (
                    f"expected head revision 'd9e0f1g2h345', got {row[0]!r}"
                )
        finally:
            engine.dispose()
