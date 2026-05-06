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
        "initial_load_windows",
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
                # h3c4d5e67890 is the head (phase8_initial_load_windows)
                assert row[0] == "h3c4d5e67890", (
                    f"expected head revision 'h3c4d5e67890', got {row[0]!r}"
                )
        finally:
            engine.dispose()

    def test_upgrade_from_stale_alembic_version_is_idempotent(self, fresh_db_path):
        """Regression for the 2026-05-05 prod incident.

        Reproduce the prod-test state: Base.metadata.create_all materialized
        every table for the *current* model BUT alembic_version is pinned at
        d9e0f1g2h345 (phase4) — and the existing ui_sessions row is missing
        the ua_hash column that phase7 introduces. `alembic upgrade head`
        must reach h3c4d5e67890 without fighting CREATE TABLE collisions
        and must add the missing column.
        """
        from sqlalchemy import create_engine, text, inspect as sa_inspect
        from app.database import Base

        # Step 1: build full current model
        engine = create_engine(f"sqlite:///{fresh_db_path}")
        try:
            Base.metadata.create_all(engine)

            # Step 2: rebuild ui_sessions WITHOUT ua_hash to simulate the
            # state of a deployment that ran on v0.5.1 model + create_all.
            with engine.begin() as conn:
                conn.execute(text("DROP TABLE ui_sessions"))
                conn.execute(text(
                    "CREATE TABLE ui_sessions ("
                    "  id VARCHAR(64) PRIMARY KEY,"
                    "  user_id INTEGER NOT NULL,"
                    "  expires_at DATETIME NOT NULL,"
                    "  created_at DATETIME NOT NULL,"
                    "  last_accessed_at DATETIME NOT NULL,"
                    "  FOREIGN KEY(user_id) REFERENCES ui_users(id) ON DELETE CASCADE"
                    ")"
                ))
                conn.execute(text(
                    "CREATE INDEX ix_ui_sessions_user ON ui_sessions(user_id)"
                ))
                conn.execute(text(
                    "CREATE INDEX ix_ui_sessions_expires ON ui_sessions(expires_at)"
                ))

                # Step 3: pin alembic_version to a stale revision
                conn.execute(text("CREATE TABLE IF NOT EXISTS alembic_version "
                                   "(version_num VARCHAR(32) PRIMARY KEY)"))
                conn.execute(text("DELETE FROM alembic_version"))
                conn.execute(text(
                    "INSERT INTO alembic_version VALUES ('d9e0f1g2h345')"
                ))
        finally:
            engine.dispose()

        # Step 4: run the production code path — must converge to head
        from app.database import Database
        db = Database(fresh_db_path)
        db.create_tables()

        # Step 5: verify migrations completed
        engine = create_engine(f"sqlite:///{fresh_db_path}")
        try:
            with engine.connect() as conn:
                ver = conn.execute(
                    text("SELECT version_num FROM alembic_version")
                ).scalar()
                assert ver == "h3c4d5e67890", (
                    f"upgrade did not reach head; got {ver!r}"
                )
            cols = [c["name"] for c in sa_inspect(engine).get_columns("ui_sessions")]
            assert "ua_hash" in cols, (
                f"phase7 ALTER missing — ui_sessions cols: {cols}"
            )
        finally:
            engine.dispose()
