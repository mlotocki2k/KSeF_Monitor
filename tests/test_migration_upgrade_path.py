"""
Databases created at an old alembic revision must reach head on startup.
create_all() used to run before the upgrade and pre-create tables that the
phase 2-4 migrations create unconditionally: the upgrade failed with
'table already exists' and the DB stayed on the old revision.
"""

import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

from app.database import Database

ROOT = Path(__file__).parent.parent


def _cfg(db_path):
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.attributes["configure_logger"] = False
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    return cfg


@pytest.mark.parametrize("revision", ["a6a08e11ea74", "b7c2d3e4f567", "c8d3e4f56789"])
def test_old_revision_upgrades_to_head(tmp_path, revision):
    db_path = tmp_path / f"{revision}.db"
    cfg = _cfg(db_path)
    command.upgrade(cfg, revision)

    Database(str(db_path)).create_tables()

    head = ScriptDirectory.from_config(cfg).get_current_head()
    con = sqlite3.connect(db_path)
    try:
        current = con.execute("select version_num from alembic_version").fetchone()[0]
        invoice_cols = {r[1] for r in con.execute("pragma table_info(invoices)")}
    finally:
        con.close()
    assert current == head
    assert "source" in invoice_cols


def test_fresh_db_still_stamped_at_head(tmp_path):
    db_path = tmp_path / "fresh.db"
    Database(str(db_path)).create_tables()
    head = ScriptDirectory.from_config(_cfg(db_path)).get_current_head()
    con = sqlite3.connect(db_path)
    try:
        assert con.execute("select version_num from alembic_version").fetchone()[0] == head
    finally:
        con.close()


def test_failed_upgrade_is_retried_on_next_start(tmp_path, monkeypatch):
    """Round 7: one failed upgrade must not leave the DB stuck for good."""
    db_path = tmp_path / "retry.db"
    command.upgrade(_cfg(db_path), "a6a08e11ea74")
    real_upgrade = command.upgrade
    calls = {"n": 0}

    def flaky(cfg, rev):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("database is locked")
        return real_upgrade(cfg, rev)

    monkeypatch.setattr(command, "upgrade", flaky)
    Database(str(db_path)).create_tables()   # fails once
    Database(str(db_path)).create_tables()   # next start
    head = ScriptDirectory.from_config(_cfg(db_path)).get_current_head()
    con = sqlite3.connect(db_path)
    try:
        assert con.execute("select version_num from alembic_version").fetchone()[0] == head
    finally:
        con.close()


def test_migrations_tolerate_precreated_tables(tmp_path):
    """Phase 2-4 migrations skip tables/indexes/columns that already exist."""
    from app.database import Base
    from sqlalchemy import create_engine
    db_path = tmp_path / "pre.db"
    command.upgrade(_cfg(db_path), "a6a08e11ea74")
    Base.metadata.create_all(create_engine(f"sqlite:///{db_path}"))  # older app behaviour
    command.upgrade(_cfg(db_path), "head")
