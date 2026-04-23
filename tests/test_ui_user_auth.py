"""
Tests for V5-13 UI user accounts (DB-backed sessions, bcrypt passwords,
first-launch setup wizard).
"""

import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.database import Base, Database, UiSession, UiUser
from app.ui_auth import (
    SESSION_TTL,
    cleanup_expired_sessions,
    count_users,
    create_session,
    create_user,
    get_user_by_username,
    hash_password,
    set_password,
    validate_password,
    validate_session,
    validate_username,
    verify_password,
)


@pytest.fixture
def db(tmp_path):
    d = Database(str(tmp_path / "test.db"))
    Base.metadata.create_all(d.engine)
    return d


@pytest.fixture
def app_auth(db):
    return create_app(db=db, auth_token="a" * 32)


@pytest.fixture
def client(app_auth):
    return TestClient(app_auth, follow_redirects=False)


# ── ui_auth helpers ─────────────────────────────────────────────────────────


class TestPasswordHashing:
    def test_hash_verify_roundtrip(self):
        h = hash_password("CorrectHorseBatteryStaple")
        assert verify_password("CorrectHorseBatteryStaple", h)

    def test_wrong_password_rejected(self):
        h = hash_password("right")
        assert not verify_password("wrong", h)

    def test_empty_password_rejected(self):
        h = hash_password("right")
        assert not verify_password("", h)

    def test_corrupted_hash_returns_false_not_raises(self):
        assert verify_password("any", "not-a-valid-hash") is False


class TestValidation:
    def test_username_too_short(self):
        assert validate_username("ab") is not None

    def test_username_too_long(self):
        assert validate_username("a" * 65) is not None

    def test_username_special_chars_rejected(self):
        assert validate_username("user@example") is not None
        assert validate_username("user space") is not None

    def test_username_allowed_chars_pass(self):
        assert validate_username("admin") is None
        assert validate_username("user.name_2") is None
        assert validate_username("a-b-c") is None

    def test_password_too_short(self):
        assert validate_password("short") is not None

    def test_password_min_length_passes(self):
        assert validate_password("12345678") is None


class TestUserCrud:
    def test_count_users_starts_at_zero(self, db):
        with db.get_session() as s:
            assert count_users(s) == 0

    def test_create_user_increments_count(self, db):
        with db.get_session() as s:
            create_user(s, "alice", "password123")
            assert count_users(s) == 1

    def test_get_user_by_username(self, db):
        with db.get_session() as s:
            create_user(s, "alice", "password123")
            u = get_user_by_username(s, "alice")
            assert u is not None
            assert u.username == "alice"

    def test_set_password_revokes_sessions(self, db):
        with db.get_session() as s:
            u = create_user(s, "alice", "old-password-123")
            sid = create_session(s, u)
            assert validate_session(s, sid) is not None
            set_password(s, u, "new-password-456")
            assert validate_session(s, sid) is None
            assert verify_password("new-password-456", u.password_hash)
            assert not verify_password("old-password-123", u.password_hash)


class TestSessionLifecycle:
    def test_create_session_returns_64_char_hex(self, db):
        with db.get_session() as s:
            u = create_user(s, "alice", "password123")
            sid = create_session(s, u)
            assert len(sid) == 64
            assert all(c in "0123456789abcdef" for c in sid)

    def test_validate_session_returns_user(self, db):
        with db.get_session() as s:
            u = create_user(s, "alice", "password123")
            sid = create_session(s, u)
            result = validate_session(s, sid)
            assert result is not None
            user, _ = result
            assert user.username == "alice"

    def test_validate_session_unknown_returns_none(self, db):
        with db.get_session() as s:
            assert validate_session(s, "deadbeef" * 8) is None

    def test_validate_session_short_sid_returns_none(self, db):
        with db.get_session() as s:
            assert validate_session(s, "short") is None

    def test_validate_session_none_returns_none(self, db):
        with db.get_session() as s:
            assert validate_session(s, None) is None

    def test_expired_session_purged(self, db):
        from datetime import datetime, timedelta, timezone

        with db.get_session() as s:
            u = create_user(s, "alice", "password123")
            sid = create_session(s, u)
            row = s.get(UiSession, sid)
            row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            s.commit()
            assert validate_session(s, sid) is None
            assert s.get(UiSession, sid) is None

    def test_validate_extends_expiry(self, db):
        from datetime import datetime, timezone

        with db.get_session() as s:
            u = create_user(s, "alice", "password123")
            sid = create_session(s, u)
            before = s.get(UiSession, sid).expires_at
            validate_session(s, sid)
            after = s.get(UiSession, sid).expires_at
            assert after >= before

    def test_cleanup_expired_returns_count(self, db):
        from datetime import datetime, timedelta, timezone

        with db.get_session() as s:
            u = create_user(s, "alice", "password123")
            sid_a = create_session(s, u)
            sid_b = create_session(s, u)
            past = datetime.now(timezone.utc) - timedelta(days=1)
            for sid in (sid_a, sid_b):
                s.get(UiSession, sid).expires_at = past
            s.commit()
            assert cleanup_expired_sessions(s) == 2


# ── HTTP endpoints ──────────────────────────────────────────────────────────


class TestSetupWizard:
    def test_setup_form_accessible_when_no_users(self, client):
        resp = client.get("/ui/setup")
        assert resp.status_code == 200
        assert "Utwórz konto" in resp.text

    def test_setup_redirects_to_login_when_users_exist(self, db, client):
        with db.get_session() as s:
            create_user(s, "alice", "password123")
        resp = client.get("/ui/setup")
        assert resp.status_code == 303
        assert resp.headers["location"] == "/ui/login"

    def test_first_visit_redirects_to_setup_when_no_users(self, client):
        resp = client.get("/ui")
        assert resp.status_code == 303
        assert resp.headers["location"] == "/ui/setup"

    def test_setup_creates_user_and_logs_in(self, client, db):
        resp = client.post(
            "/ui/setup",
            data={
                "username": "alice",
                "password": "password123",
                "password_confirm": "password123",
            },
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == "/ui"
        assert "mksef_session" in resp.cookies
        with db.get_session() as s:
            assert count_users(s) == 1
            u = get_user_by_username(s, "alice")
            assert u and verify_password("password123", u.password_hash)

    def test_setup_rejects_short_password(self, client):
        resp = client.post(
            "/ui/setup",
            data={
                "username": "alice",
                "password": "short",
                "password_confirm": "short",
            },
        )
        assert resp.status_code == 303
        assert "/ui/setup?error=" in resp.headers["location"]

    def test_setup_rejects_mismatched_passwords(self, client):
        resp = client.post(
            "/ui/setup",
            data={
                "username": "alice",
                "password": "password123",
                "password_confirm": "different456",
            },
        )
        assert resp.status_code == 303
        assert "/ui/setup?error=" in resp.headers["location"]

    def test_setup_locked_after_first_user(self, client, db):
        client.post(
            "/ui/setup",
            data={
                "username": "alice",
                "password": "password123",
                "password_confirm": "password123",
            },
        )
        client.cookies.clear()
        resp = client.post(
            "/ui/setup",
            data={
                "username": "bob",
                "password": "password456",
                "password_confirm": "password456",
            },
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == "/ui/login"
        with db.get_session() as s:
            assert count_users(s) == 1


class TestLoginFlow:
    def test_login_form_renders_when_users_exist(self, db, client):
        with db.get_session() as s:
            create_user(s, "alice", "password123")
        resp = client.get("/ui/login")
        assert resp.status_code == 200
        assert "username" in resp.text.lower()

    def test_login_success_sets_cookie(self, db, client):
        with db.get_session() as s:
            create_user(s, "alice", "password123")
        resp = client.post(
            "/ui/login",
            data={"username": "alice", "password": "password123", "next": "/ui"},
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == "/ui"
        assert "mksef_session" in resp.cookies
        sid = resp.cookies["mksef_session"]
        assert len(sid) == 64

    def test_login_wrong_password_no_cookie(self, db, client):
        with db.get_session() as s:
            create_user(s, "alice", "password123")
        resp = client.post(
            "/ui/login",
            data={"username": "alice", "password": "wrong", "next": "/ui"},
        )
        assert resp.status_code == 303
        assert "error=invalid" in resp.headers["location"]
        assert "mksef_session" not in resp.cookies

    def test_login_unknown_user_no_cookie(self, db, client):
        with db.get_session() as s:
            create_user(s, "alice", "password123")
        resp = client.post(
            "/ui/login",
            data={"username": "ghost", "password": "anything", "next": "/ui"},
        )
        assert resp.status_code == 303
        assert "error=invalid" in resp.headers["location"]

    def test_login_no_users_bounces_to_setup(self, client):
        resp = client.post(
            "/ui/login", data={"username": "x", "password": "y"}
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == "/ui/setup"

    def test_login_open_redirect_blocked(self, db, client):
        with db.get_session() as s:
            create_user(s, "alice", "password123")
        resp = client.post(
            "/ui/login",
            data={
                "username": "alice",
                "password": "password123",
                "next": "https://evil.example/x",
            },
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == "/ui"

    def test_login_protocol_relative_blocked(self, db, client):
        with db.get_session() as s:
            create_user(s, "alice", "password123")
        resp = client.post(
            "/ui/login",
            data={
                "username": "alice",
                "password": "password123",
                "next": "//evil.example",
            },
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == "/ui"

    def test_cookie_is_httponly_and_strict(self, db, client):
        with db.get_session() as s:
            create_user(s, "alice", "password123")
        resp = client.post(
            "/ui/login",
            data={"username": "alice", "password": "password123"},
        )
        cookie_header = resp.headers.get("set-cookie", "").lower()
        assert "httponly" in cookie_header
        assert "samesite=strict" in cookie_header


class TestSessionAuth:
    def _login(self, db, client, username="alice", password="password123"):
        with db.get_session() as s:
            create_user(s, username, password)
        resp = client.post(
            "/ui/login", data={"username": username, "password": password}
        )
        return resp.cookies["mksef_session"]

    def test_cookie_grants_ui_access(self, db, app_auth):
        client = TestClient(app_auth, follow_redirects=False, raise_server_exceptions=False)
        with db.get_session() as s:
            create_user(s, "alice", "password123")
        client.post("/ui/login", data={"username": "alice", "password": "password123"})
        resp = client.get("/ui")
        assert resp.status_code != 303
        assert resp.status_code != 401

    def test_cookie_grants_api_access(self, db, app_auth):
        client = TestClient(app_auth, follow_redirects=False)
        with db.get_session() as s:
            create_user(s, "alice", "password123")
        client.post("/ui/login", data={"username": "alice", "password": "password123"})
        resp = client.get("/api/v1/monitor/ksef-status")
        assert resp.status_code != 401

    def test_bearer_still_works_for_api(self, db, client):
        resp = client.get(
            "/api/v1/monitor/ksef-status",
            headers={"Authorization": f"Bearer {'a' * 32}"},
        )
        assert resp.status_code != 401

    def test_invalid_cookie_redirects_to_login(self, db, client):
        with db.get_session() as s:
            create_user(s, "alice", "password123")
        client.cookies.set("mksef_session", "deadbeef" * 8)
        resp = client.get("/ui")
        assert resp.status_code == 303
        assert "/ui/login" in resp.headers["location"]


class TestLogout:
    def test_logout_revokes_db_session(self, db, app_auth):
        client = TestClient(app_auth, follow_redirects=False)
        with db.get_session() as s:
            create_user(s, "alice", "password123")
        login = client.post(
            "/ui/login", data={"username": "alice", "password": "password123"}
        )
        sid = login.cookies["mksef_session"]
        with db.get_session() as s:
            assert s.get(UiSession, sid) is not None
        resp = client.post("/ui/logout")
        assert resp.status_code == 303
        assert resp.headers["location"] == "/ui/login"
        with db.get_session() as s:
            assert s.get(UiSession, sid) is None

    def test_logout_clears_cookie(self, db, client):
        with db.get_session() as s:
            create_user(s, "alice", "password123")
        client.post("/ui/login", data={"username": "alice", "password": "password123"})
        resp = client.post("/ui/logout")
        cookie_hdr = resp.headers.get("set-cookie", "").lower()
        assert "mksef_session" in cookie_hdr
        assert ("max-age=0" in cookie_hdr) or ("expires=" in cookie_hdr)


class TestAccountPasswordChange:
    def _login(self, db, client):
        with db.get_session() as s:
            create_user(s, "alice", "old-password-123")
        client.post(
            "/ui/login", data={"username": "alice", "password": "old-password-123"}
        )

    def test_change_password_requires_current(self, db, client):
        self._login(db, client)
        resp = client.post(
            "/ui/account/password",
            data={
                "current_password": "wrong",
                "new_password": "new-password-456",
                "new_password_confirm": "new-password-456",
            },
        )
        assert resp.status_code == 303
        assert "error" in resp.headers["location"]

    def test_change_password_rejects_mismatch(self, db, client):
        self._login(db, client)
        resp = client.post(
            "/ui/account/password",
            data={
                "current_password": "old-password-123",
                "new_password": "new-password-456",
                "new_password_confirm": "different",
            },
        )
        assert resp.status_code == 303
        assert "error" in resp.headers["location"]

    def test_change_password_succeeds_and_logs_out(self, db, client):
        self._login(db, client)
        resp = client.post(
            "/ui/account/password",
            data={
                "current_password": "old-password-123",
                "new_password": "new-password-456",
                "new_password_confirm": "new-password-456",
            },
        )
        assert resp.status_code == 303
        assert "/ui/login" in resp.headers["location"]
        assert "ok=password" in resp.headers["location"]
        with db.get_session() as s:
            u = get_user_by_username(s, "alice")
            assert verify_password("new-password-456", u.password_hash)
            assert not verify_password("old-password-123", u.password_hash)

    def test_account_unauthenticated_redirects(self, client, db):
        with db.get_session() as s:
            create_user(s, "alice", "password123")
        resp = client.get("/ui/account")
        assert resp.status_code == 303
        assert "/ui/login" in resp.headers["location"]


class TestUpgradeBootstrap:
    """V5-13: existing v0.5.0 deployments with api.auth_token must keep working
    after upgrade. main.py auto-creates 'admin' user with password = auth_token
    on first start when 0 users exist. Bearer also keeps working — verified in
    test_api_auth.py."""

    def test_login_with_bootstrapped_admin_works(self, db, client):
        token = "bootstrap-token-" + "x" * 32
        with db.get_session() as s:
            create_user(s, "admin", token)
        resp = client.post(
            "/ui/login", data={"username": "admin", "password": token}
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == "/ui"
        assert "mksef_session" in resp.cookies

    def test_existing_bearer_still_grants_api(self, db, client):
        """The same auth_token that became the admin password also still works
        as Bearer for curl/integrations — they're independent auth paths."""
        with db.get_session() as s:
            create_user(s, "admin", "any-password-456")
        resp = client.get(
            "/api/v1/monitor/ksef-status",
            headers={"Authorization": f"Bearer {'a' * 32}"},
        )
        assert resp.status_code != 401


class TestSessionResolver:
    """Regression tests for V5-13 fix: cookie session state populates
    request.state.ui_user_id/ui_username independently of auth gate, so
    /ui/account and navbar links work under all config permutations."""

    def _login_and_get_cookie(self, client, db, username="admin", password="x" * 20):
        with db.get_session() as s:
            create_user(s, username, password)
        resp = client.post(
            "/ui/login", data={"username": username, "password": password}
        )
        assert resp.status_code == 303
        return client.cookies.get("mksef_session")

    def test_account_page_works_with_ui_public_true(self, db):
        """With ui_public=True, auth gate bypasses /ui but resolver still
        validates cookie → /ui/account must render the form, not redirect."""
        app = create_app(db=db, auth_token="a" * 32, ui_public=True)
        client = TestClient(app, follow_redirects=False)
        self._login_and_get_cookie(client, db)

        resp = client.get("/ui/account")
        assert resp.status_code == 200
        assert "current_password" in resp.text
        assert "new_password" in resp.text

    def test_navbar_shows_username_with_ui_public_true(self, db):
        """Navbar account link visibility is gated on ui_username; must be
        set even when ui_public bypasses auth gate."""
        app = create_app(db=db, auth_token="a" * 32, ui_public=True)
        client = TestClient(app, follow_redirects=False)
        self._login_and_get_cookie(client, db, username="admin")

        resp = client.get("/ui")
        assert resp.status_code == 200
        assert "/ui/account" in resp.text
        assert "Wyloguj" in resp.text

    def test_account_page_works_without_auth_token(self, db):
        """When auth_token is empty (dev mode), no auth gate registered, but
        cookie resolver still runs so /ui/account serves the form."""
        app = create_app(db=db, auth_token=None)
        client = TestClient(app, follow_redirects=False)
        self._login_and_get_cookie(client, db)

        resp = client.get("/ui/account")
        assert resp.status_code == 200
        assert "current_password" in resp.text

    def test_password_change_revokes_and_forces_relogin_ui_public(self, db):
        """End-to-end: even under ui_public, password change revokes the
        session and subsequent /ui/account requires fresh login."""
        app = create_app(db=db, auth_token="a" * 32, ui_public=True)
        client = TestClient(app, follow_redirects=False)
        self._login_and_get_cookie(client, db, password="old-password-xyz1")

        resp = client.post(
            "/ui/account/password",
            data={
                "current_password": "old-password-xyz1",
                "new_password": "new-password-xyz2",
                "new_password_confirm": "new-password-xyz2",
            },
        )
        assert resp.status_code == 303
        assert "/ui/login" in resp.headers["location"]

        # Old session gone — /ui/account should redirect back to login.
        resp = client.get("/ui/account")
        assert resp.status_code == 303
        assert "/ui/login" in resp.headers["location"]
