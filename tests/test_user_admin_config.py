"""app.user_admin finds the config like main.py (/config, /data, cwd)."""

import json

from app import user_admin


def test_finds_config_in_candidate_dirs(tmp_path, monkeypatch):
    db_file = tmp_path / "x.db"
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"database": {"path": str(db_file)}}), encoding="utf-8")
    monkeypatch.delenv("CONFIG_PATH", raising=False)
    monkeypatch.setattr(user_admin, "_CONFIG_CANDIDATES", (str(tmp_path / "missing.json"), str(cfg)))
    db = user_admin._open_db()
    assert str(db.db_path) == str(db_file)


def test_config_path_env_wins(tmp_path, monkeypatch):
    db_file = tmp_path / "env.db"
    cfg = tmp_path / "env.json"
    cfg.write_text(json.dumps({"database": {"path": str(db_file)}}), encoding="utf-8")
    monkeypatch.setenv("CONFIG_PATH", str(cfg))
    assert str(user_admin._open_db().db_path) == str(db_file)
