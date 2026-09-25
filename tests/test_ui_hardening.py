"""
UI hardening: first-admin setup needs the install code, cookie-authenticated
state changes need a same-origin request, lockout rows do not pile up.
"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.database import Base, Database, UiLoginAttempt
from app.ui_auth import count_users, create_user, record_login_failure

TOKEN = "a" * 32
SETUP = {"username": "admin2", "password": "SolidPass_88!", "password_confirm": "SolidPass_88!"}


@pytest.fixture
def db(tmp_path):
    d = Database(str(tmp_path / "ui.db"))
    Base.metadata.create_all(d.engine)
    return d


@pytest.fixture
def client(db):
    return TestClient(create_app(db=db, auth_token=TOKEN), base_url="http://testserver")


def _users(db):
    with db.get_session() as s:
        return count_users(s)


# ── Setup install code ───────────────────────────────────────────────────────


def test_setup_without_code_rejected(client, db):
    r = client.post("/ui/setup", data=SETUP, follow_redirects=False)
    assert r.status_code == 303
    assert "/ui/setup?error=" in r.headers["location"]
    assert _users(db) == 0


def test_setup_with_wrong_code_rejected(client, db):
    r = client.post("/ui/setup", data={**SETUP, "setup_code": "b" * 32},
                    follow_redirects=False)
    assert "/ui/setup?error=" in r.headers["location"]
    assert _users(db) == 0


def test_setup_with_code_creates_admin(client, db):
    r = client.post("/ui/setup", data={**SETUP, "setup_code": f"  {TOKEN}\n"},
                    follow_redirects=False)
    assert r.headers["location"] == "/ui"
    assert _users(db) == 1


def test_setup_form_asks_for_code(client):
    assert 'name="setup_code"' in client.get("/ui/setup").text


# ── Same-origin check for cookie sessions ────────────────────────────────────


@pytest.fixture
def logged_in(client, db):
    with db.get_session() as s:
        create_user(s, "alice", "SolidPass_88!")
    client.post("/ui/login", data={"username": "alice", "password": "SolidPass_88!"})
    assert client.cookies.get("mksef_session")
    return client


def test_cross_origin_post_with_cookie_rejected(logged_in):
    r = logged_in.post("/ui/logout", headers={"Origin": "https://evil.example"},
                       follow_redirects=False)
    assert r.status_code == 403


def test_same_origin_post_with_cookie_allowed(logged_in):
    r = logged_in.post("/ui/logout", headers={"Origin": "http://testserver"},
                       follow_redirects=False)
    assert r.status_code == 303


def test_post_without_origin_allowed(logged_in):
    # Non-browser clients (curl with a cookie) send no Origin/Referer
    r = logged_in.post("/ui/logout", follow_redirects=False)
    assert r.status_code == 303


def test_cross_site_referer_rejected(logged_in):
    r = logged_in.post("/ui/logout", headers={"Referer": "https://evil.example/x"},
                       follow_redirects=False)
    assert r.status_code == 403


def test_bearer_post_ignores_origin(client):
    r = client.post("/api/v1/monitor/trigger",
                    headers={"Authorization": f"Bearer {TOKEN}", "Origin": "https://x.example"})
    assert r.status_code != 403


# ── Lockout table pruning ────────────────────────────────────────────────────


def test_stale_login_attempt_rows_pruned(db):
    old = datetime.now(timezone.utc) - timedelta(days=2)
    with db.get_session() as s:
        for i in range(20):
            s.add(UiLoginAttempt(username=f"ghost{i}", failed_count=1, last_failed_at=old))
        s.commit()
        record_login_failure(s, "someone")
        remaining = {r.username for r in s.query(UiLoginAttempt).all()}
    assert remaining == {"someone"}
