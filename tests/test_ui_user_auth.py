"""
Tests for V5-13 UI user accounts (DB-backed sessions, bcrypt passwords,
first-launch setup wizard).
"""

import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.database import Base, Database, UiSession, UiUser
from app.ui_auth import (
    LOGIN_FAIL_WINDOW,
    LOGIN_LOCKOUT_DURATION,
    LOGIN_LOCKOUT_THRESHOLD,
    SESSION_ABSOLUTE_LIFETIME,
    SESSION_TTL,
    cleanup_expired_sessions,
    count_users,
    create_first_admin_atomic,
    create_session,
    create_user,
    get_user_by_username,
    hash_password,
    hash_user_agent,
    is_login_locked,
    record_login_failure,
    record_login_success,
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

    # U-02 — bcrypt 72-byte boundary: SHA256+b64 pre-hash for >72B inputs
    def test_long_password_round_trip(self):
        long_pw = "A" * 100
        h = hash_password(long_pw)
        assert verify_password(long_pw, h)

    def test_very_long_password_round_trip(self):
        long_pw = "Z" * 1000  # well above bcrypt's 72-byte boundary
        h = hash_password(long_pw)
        assert verify_password(long_pw, h)

    def test_long_passwords_differing_after_72_bytes_do_not_collide(self):
        # Plain bcrypt would silently truncate both to the same 72 bytes.
        pw_a = ("A" * 72) + "_alpha_suffix"
        pw_b = ("A" * 72) + "_omega_suffix"
        h_a = hash_password(pw_a)
        assert verify_password(pw_a, h_a)
        assert not verify_password(pw_b, h_a)

    def test_unicode_long_password(self):
        # Multi-byte chars: 50 chars × 4 bytes = 200 bytes (above 72B boundary)
        long_pw = "🔐" * 50
        h = hash_password(long_pw)
        assert verify_password(long_pw, h)
        assert not verify_password("🔐" * 49, h)


# U-17 — case-insensitive username lookup.
class TestUsernameCaseInsensitive:
    def test_lookup_finds_user_with_different_case(self, db):
        with db.get_session() as s:
            create_user(s, "Admin", "SolidPass_88!")
        with db.get_session() as s:
            assert get_user_by_username(s, "admin") is not None
            assert get_user_by_username(s, "ADMIN") is not None
            assert get_user_by_username(s, "Admin") is not None

    def test_login_works_with_different_case(self, db, client):
        with db.get_session() as s:
            create_user(s, "Alice", "SolidPass_88!")
        resp = client.post(
            "/ui/login",
            data={"username": "ALICE", "password": "SolidPass_88!"},
        )
        assert resp.status_code == 303
        assert "mksef_session" in resp.cookies

    def test_lockout_shared_across_casing_variants(self, db, client):
        with db.get_session() as s:
            create_user(s, "alice", "SolidPass_88!")
        # Hammer with different casings — counter must aggregate.
        for u in ["alice", "ALICE", "Alice", "ALICE", "alice"]:
            client.post("/ui/login", data={"username": u, "password": "wrong"})
        # All five variants should now be locked.
        with db.get_session() as s:
            assert is_login_locked(s, "alice") is not None
            assert is_login_locked(s, "ALICE") is not None


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
        # Distinct from the breached blocklist; validates pure length floor.
        assert validate_password("Solid_Pass_88!") is None

    # U-11 — strength: blocklist + username substring guard
    def test_password_in_blocklist_rejected(self):
        for pw in ["12345678", "password", "qwerty123", "PASSWORD123", "iloveyou"]:
            err = validate_password(pw)
            assert err is not None, f"{pw!r} should be flagged"

    def test_password_containing_username_rejected(self):
        assert validate_password("alicePass!", username="alice") is not None
        assert validate_password("Hello_ALICE_2026", username="alice") is not None

    def test_password_unrelated_to_username_passes(self):
        assert validate_password("Solid_Pass_88!", username="alice") is None

    def test_short_username_does_not_trigger_substring_check(self):
        # 2-char usernames would false-positive too much; only check ≥3 chars.
        assert validate_password("Solid_Pass_88!", username="bo") is None


class TestUserCrud:
    def test_count_users_starts_at_zero(self, db):
        with db.get_session() as s:
            assert count_users(s) == 0

    def test_create_user_increments_count(self, db):
        with db.get_session() as s:
            create_user(s, "alice", "SolidPass_88!")
            assert count_users(s) == 1

    def test_get_user_by_username(self, db):
        with db.get_session() as s:
            create_user(s, "alice", "SolidPass_88!")
            u = get_user_by_username(s, "alice")
            assert u is not None
            assert u.username == "alice"

    def test_set_password_revokes_sessions(self, db):
        with db.get_session() as s:
            u = create_user(s, "alice", "OldSolid_66!")
            sid = create_session(s, u)
            assert validate_session(s, sid) is not None
            set_password(s, u, "new-password-456")
            assert validate_session(s, sid) is None
            assert verify_password("new-password-456", u.password_hash)
            assert not verify_password("OldSolid_66!", u.password_hash)


class TestSessionLifecycle:
    def test_create_session_returns_64_char_hex(self, db):
        with db.get_session() as s:
            u = create_user(s, "alice", "SolidPass_88!")
            sid = create_session(s, u)
            assert len(sid) == 64
            assert all(c in "0123456789abcdef" for c in sid)

    def test_validate_session_returns_user(self, db):
        with db.get_session() as s:
            u = create_user(s, "alice", "SolidPass_88!")
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
            u = create_user(s, "alice", "SolidPass_88!")
            sid = create_session(s, u)
            row = s.get(UiSession, sid)
            row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            s.commit()
            assert validate_session(s, sid) is None
            assert s.get(UiSession, sid) is None

    def test_validate_extends_expiry(self, db):
        from datetime import datetime, timezone

        with db.get_session() as s:
            u = create_user(s, "alice", "SolidPass_88!")
            sid = create_session(s, u)
            before = s.get(UiSession, sid).expires_at
            validate_session(s, sid)
            after = s.get(UiSession, sid).expires_at
            assert after >= before

    # U-09 — absolute lifetime cap
    def test_session_revoked_past_absolute_lifetime(self, db):
        from datetime import datetime, timedelta, timezone

        with db.get_session() as s:
            u = create_user(s, "alice", "SolidPass_88!")
            sid = create_session(s, u)
            row = s.get(UiSession, sid)
            # Simulate a session that was created longer ago than the
            # absolute cap, but has been kept alive by sliding renewal.
            row.created_at = datetime.now(timezone.utc) - SESSION_ABSOLUTE_LIFETIME - timedelta(minutes=1)
            row.expires_at = datetime.now(timezone.utc) + timedelta(days=1)
            s.commit()
            assert validate_session(s, sid) is None
            # Row deleted as side effect.
            assert s.get(UiSession, sid) is None

    def test_session_inside_absolute_lifetime_still_valid(self, db):
        from datetime import datetime, timedelta, timezone

        with db.get_session() as s:
            u = create_user(s, "alice", "SolidPass_88!")
            sid = create_session(s, u)
            row = s.get(UiSession, sid)
            row.created_at = datetime.now(timezone.utc) - SESSION_ABSOLUTE_LIFETIME + timedelta(hours=1)
            s.commit()
            assert validate_session(s, sid) is not None

    def test_cleanup_expired_returns_count(self, db):
        from datetime import datetime, timedelta, timezone

        with db.get_session() as s:
            u = create_user(s, "alice", "SolidPass_88!")
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
            create_user(s, "alice", "SolidPass_88!")
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
                "password": "SolidPass_88!",
                "password_confirm": "SolidPass_88!",
            },
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == "/ui"
        assert "mksef_session" in resp.cookies
        with db.get_session() as s:
            assert count_users(s) == 1
            u = get_user_by_username(s, "alice")
            assert u and verify_password("SolidPass_88!", u.password_hash)

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
                "password": "SolidPass_88!",
                "password_confirm": "Different_99!",
            },
        )
        assert resp.status_code == 303
        assert "/ui/setup?error=" in resp.headers["location"]

    # U-06 — atomic helper guarantees a single first admin even if the handler
    # path is bypassed or invoked twice.
    def test_atomic_first_admin_creates_user_and_session(self, db):
        result = create_first_admin_atomic(db, "alice", "SolidPass_88!")
        assert result is not None
        user_id, sid = result
        assert isinstance(user_id, int) and user_id > 0
        assert len(sid) == 64
        with db.get_session() as s:
            assert count_users(s) == 1
            assert get_user_by_username(s, "alice") is not None

    def test_atomic_first_admin_returns_none_when_user_exists(self, db):
        first = create_first_admin_atomic(db, "alice", "SolidPass_88!")
        assert first is not None
        # Any subsequent call must NOT create a second user.
        second = create_first_admin_atomic(db, "mallory", "password789")
        assert second is None
        with db.get_session() as s:
            assert count_users(s) == 1
            assert get_user_by_username(s, "alice") is not None
            assert get_user_by_username(s, "mallory") is None

    def test_atomic_first_admin_session_validates(self, db):
        result = create_first_admin_atomic(db, "alice", "SolidPass_88!")
        assert result is not None
        _, sid = result
        with db.get_session() as s:
            validated = validate_session(s, sid)
            assert validated is not None
            user, _ = validated
            assert user.username == "alice"

    def test_setup_locked_after_first_user(self, client, db):
        client.post(
            "/ui/setup",
            data={
                "username": "alice",
                "password": "SolidPass_88!",
                "password_confirm": "SolidPass_88!",
            },
        )
        client.cookies.clear()
        resp = client.post(
            "/ui/setup",
            data={
                "username": "bob",
                "password": "SolidPass_99!",
                "password_confirm": "SolidPass_99!",
            },
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == "/ui/login"
        with db.get_session() as s:
            assert count_users(s) == 1


class TestLoginFlow:
    def test_login_form_renders_when_users_exist(self, db, client):
        with db.get_session() as s:
            create_user(s, "alice", "SolidPass_88!")
        resp = client.get("/ui/login")
        assert resp.status_code == 200
        assert "username" in resp.text.lower()

    def test_login_success_sets_cookie(self, db, client):
        with db.get_session() as s:
            create_user(s, "alice", "SolidPass_88!")
        resp = client.post(
            "/ui/login",
            data={"username": "alice", "password": "SolidPass_88!", "next": "/ui"},
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == "/ui"
        assert "mksef_session" in resp.cookies
        sid = resp.cookies["mksef_session"]
        assert len(sid) == 64

    def test_login_wrong_password_no_cookie(self, db, client):
        with db.get_session() as s:
            create_user(s, "alice", "SolidPass_88!")
        resp = client.post(
            "/ui/login",
            data={"username": "alice", "password": "wrong", "next": "/ui"},
        )
        assert resp.status_code == 303
        assert "error=invalid" in resp.headers["location"]
        assert "mksef_session" not in resp.cookies

    def test_login_unknown_user_no_cookie(self, db, client):
        with db.get_session() as s:
            create_user(s, "alice", "SolidPass_88!")
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
            create_user(s, "alice", "SolidPass_88!")
        resp = client.post(
            "/ui/login",
            data={
                "username": "alice",
                "password": "SolidPass_88!",
                "next": "https://evil.example/x",
            },
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == "/ui"

    def test_login_protocol_relative_blocked(self, db, client):
        with db.get_session() as s:
            create_user(s, "alice", "SolidPass_88!")
        resp = client.post(
            "/ui/login",
            data={
                "username": "alice",
                "password": "SolidPass_88!",
                "next": "//evil.example",
            },
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == "/ui"

    def test_cookie_is_httponly_and_strict(self, db, client):
        with db.get_session() as s:
            create_user(s, "alice", "SolidPass_88!")
        resp = client.post(
            "/ui/login",
            data={"username": "alice", "password": "SolidPass_88!"},
        )
        cookie_header = resp.headers.get("set-cookie", "").lower()
        assert "httponly" in cookie_header
        assert "samesite=strict" in cookie_header


# U-03 — per-username brute-force lockout.
class TestLoginLockout:
    def test_no_lock_initially(self, db):
        with db.get_session() as s:
            assert is_login_locked(s, "alice") is None

    def test_lock_engages_at_threshold(self, db):
        with db.get_session() as s:
            for _ in range(LOGIN_LOCKOUT_THRESHOLD - 1):
                assert record_login_failure(s, "alice") is None
                assert is_login_locked(s, "alice") is None
            locked = record_login_failure(s, "alice")
            assert locked is not None
            still_locked = is_login_locked(s, "alice")
            assert still_locked is not None

    def test_success_resets_counter(self, db):
        with db.get_session() as s:
            for _ in range(LOGIN_LOCKOUT_THRESHOLD - 1):
                record_login_failure(s, "alice")
            record_login_success(s, "alice")
            assert is_login_locked(s, "alice") is None
            # one more failure must NOT immediately re-lock
            assert record_login_failure(s, "alice") is None

    def test_separate_usernames_dont_share_counter(self, db):
        with db.get_session() as s:
            for _ in range(LOGIN_LOCKOUT_THRESHOLD):
                record_login_failure(s, "alice")
            assert is_login_locked(s, "alice") is not None
            assert is_login_locked(s, "bob") is None

    def test_lock_blocks_login_endpoint(self, db, client):
        with db.get_session() as s:
            create_user(s, "alice", "SolidPass_88!")
            for _ in range(LOGIN_LOCKOUT_THRESHOLD):
                record_login_failure(s, "alice")
        # Even with correct password, locked user gets 'locked' error.
        resp = client.post(
            "/ui/login",
            data={"username": "alice", "password": "SolidPass_88!"},
        )
        assert resp.status_code == 303
        assert "error=locked" in resp.headers["location"]
        assert "mksef_session" not in resp.cookies

    def test_unknown_user_login_increments_counter(self, db, client):
        # Hits the dummy-hash branch but still records the attempt so a
        # botnet can't probe usernames forever without tripping lockout.
        with db.get_session() as s:
            create_user(s, "real_admin", "SolidPass_88!")  # so count_users > 0
        for _ in range(LOGIN_LOCKOUT_THRESHOLD):
            client.post(
                "/ui/login",
                data={"username": "ghost", "password": "wrong"},
            )
        with db.get_session() as s:
            assert is_login_locked(s, "ghost") is not None

    def test_successful_login_resets_after_some_failures(self, db, client):
        with db.get_session() as s:
            create_user(s, "alice", "SolidPass_88!")
        # 3 failed attempts, then successful login
        for _ in range(3):
            client.post(
                "/ui/login",
                data={"username": "alice", "password": "wrong"},
            )
        resp = client.post(
            "/ui/login",
            data={"username": "alice", "password": "SolidPass_88!"},
        )
        assert resp.status_code == 303
        assert "mksef_session" in resp.cookies
        with db.get_session() as s:
            assert is_login_locked(s, "alice") is None


# U-05 — CSP nonce, drop unsafe-inline from script-src.
class TestCspNonce:
    def test_csp_uses_per_request_nonce_not_unsafe_inline(self, client):
        resp = client.get("/ui/login")
        csp = resp.headers.get("content-security-policy", "")
        assert csp, "CSP header must be present on /ui/login"
        # script-src directive: must include nonce-..., must NOT include unsafe-inline
        # Find the script-src segment.
        script_src = next(
            (part.strip() for part in csp.split(";") if part.strip().startswith("script-src")),
            "",
        )
        assert script_src, f"script-src directive missing in CSP: {csp!r}"
        assert "'unsafe-inline'" not in script_src, (
            f"script-src must not contain 'unsafe-inline'; got {script_src!r}"
        )
        assert "'nonce-" in script_src, (
            f"script-src must contain a per-request nonce; got {script_src!r}"
        )

    def test_each_request_gets_a_fresh_nonce(self, client):
        r1 = client.get("/ui/login").headers["content-security-policy"]
        r2 = client.get("/ui/login").headers["content-security-policy"]
        # Extract nonce values
        def _extract_nonce(csp: str) -> str:
            for part in csp.split(";"):
                if "nonce-" in part:
                    # format: script-src 'self' 'nonce-XYZ'
                    for token in part.split():
                        if token.startswith("'nonce-"):
                            return token
            return ""
        n1 = _extract_nonce(r1)
        n2 = _extract_nonce(r2)
        assert n1 and n2 and n1 != n2

    def test_inline_script_carries_nonce_in_template(self, db, app_auth):
        # Setup wizard renders without auth — easy fixture for HTML inspection.
        local_client = TestClient(app_auth, follow_redirects=False)
        resp = local_client.get("/ui/setup")
        assert resp.status_code == 200
        # setup.html has no inline script, but base.html (used by dashboard
        # etc.) does. Render account page after a real login.
        with db.get_session() as s:
            create_user(s, "alice", "SolidPass_88!")
        local_client.post(
            "/ui/login",
            data={"username": "alice", "password": "SolidPass_88!"},
        )
        resp = local_client.get("/ui")
        assert resp.status_code == 200
        # Each <script ...> tag in the rendered HTML must carry nonce="…".
        # Bare "<script>" (no attrs) would block under our CSP.
        import re
        bare_scripts = re.findall(r"<script(?![^>]*\bnonce=)[^>]*>", resp.text)
        assert not bare_scripts, (
            f"unsafe inline scripts (no nonce) found: {bare_scripts!r}"
        )


# U-04 — opt-in UA fingerprint binding.
class TestSessionUaBinding:
    def test_create_session_records_ua_hash(self, db):
        with db.get_session() as s:
            u = create_user(s, "alice", "SolidPass_88!")
            sid = create_session(s, u, ua="Mozilla/5.0 SomeBrowser")
            row = s.get(UiSession, sid)
            assert row.ua_hash == hash_user_agent("Mozilla/5.0 SomeBrowser")

    def test_strict_off_allows_ua_change(self, db):
        with db.get_session() as s:
            u = create_user(s, "alice", "SolidPass_88!")
            sid = create_session(s, u, ua="UA-A")
            assert validate_session(s, sid, ua="UA-B", strict_ua=False) is not None

    def test_strict_on_revokes_on_mismatch(self, db):
        with db.get_session() as s:
            u = create_user(s, "alice", "SolidPass_88!")
            sid = create_session(s, u, ua="UA-A")
            assert validate_session(s, sid, ua="UA-B", strict_ua=True) is None
            # Row deleted
            assert s.get(UiSession, sid) is None

    def test_strict_on_accepts_matching_ua(self, db):
        with db.get_session() as s:
            u = create_user(s, "alice", "SolidPass_88!")
            sid = create_session(s, u, ua="UA-A")
            assert validate_session(s, sid, ua="UA-A", strict_ua=True) is not None

    def test_strict_on_legacy_session_no_ua_hash_grandfathered(self, db):
        # Pre-existing session without ua_hash (e.g. created before this fix
        # rolled out) must not be revoked just because strict mode flipped.
        with db.get_session() as s:
            u = create_user(s, "alice", "SolidPass_88!")
            sid = create_session(s, u, ua=None)
            row = s.get(UiSession, sid)
            assert row.ua_hash is None
            assert validate_session(s, sid, ua="UA-X", strict_ua=True) is not None

    def test_e2e_strict_binding_blocks_stolen_cookie(self, db):
        # Login from one browser, then send the cookie with a different UA
        # to a strict-mode app — should bounce to /ui/login.
        app = create_app(
            db=db,
            auth_token="a" * 32,
            session_strict_binding=True,
        )
        with db.get_session() as s:
            create_user(s, "alice", "SolidPass_88!")
        login_client = TestClient(app, follow_redirects=False)
        login_client.headers["user-agent"] = "BrowserA/1.0"
        resp = login_client.post(
            "/ui/login",
            data={"username": "alice", "password": "SolidPass_88!"},
        )
        sid = resp.cookies["mksef_session"]

        # Same cookie, different UA → revoked.
        attacker_client = TestClient(app, follow_redirects=False)
        attacker_client.cookies.set("mksef_session", sid)
        attacker_client.headers["user-agent"] = "AttackerBrowser/1.0"
        resp2 = attacker_client.get("/ui")
        # Without a valid session, the gate redirects to /ui/login.
        assert resp2.status_code in (303, 401)
        if resp2.status_code == 303:
            assert "/ui/login" in resp2.headers["location"]


# U-01 — cookie Secure flag honors X-Forwarded-Proto + cookie_secure_mode override.
class TestCookieSecureFlag:
    def _login_and_get_set_cookie(self, db, app, headers=None):
        client = TestClient(app, follow_redirects=False)
        with db.get_session() as s:
            create_user(s, "alice", "SolidPass_88!")
        resp = client.post(
            "/ui/login",
            data={"username": "alice", "password": "SolidPass_88!"},
            headers=headers or {},
        )
        return resp.headers.get("set-cookie", "").lower()

    def test_auto_no_proxy_header_no_secure(self, db):
        # TestClient defaults to http://; without X-Forwarded-Proto, no Secure.
        app = create_app(db=db, auth_token="a" * 32, cookie_secure_mode="auto")
        cookie = self._login_and_get_set_cookie(db, app)
        assert "secure" not in cookie

    def test_auto_xforwarded_proto_https_sets_secure(self, db):
        app = create_app(db=db, auth_token="a" * 32, cookie_secure_mode="auto")
        cookie = self._login_and_get_set_cookie(
            db, app, headers={"X-Forwarded-Proto": "https"}
        )
        assert "secure" in cookie

    def test_auto_xforwarded_proto_http_no_secure(self, db):
        app = create_app(db=db, auth_token="a" * 32, cookie_secure_mode="auto")
        cookie = self._login_and_get_set_cookie(
            db, app, headers={"X-Forwarded-Proto": "http"}
        )
        assert "secure" not in cookie

    def test_always_mode_forces_secure_even_on_http(self, db):
        app = create_app(db=db, auth_token="a" * 32, cookie_secure_mode="always")
        cookie = self._login_and_get_set_cookie(db, app)
        assert "secure" in cookie

    def test_never_mode_strips_secure_even_with_https_header(self, db):
        app = create_app(db=db, auth_token="a" * 32, cookie_secure_mode="never")
        cookie = self._login_and_get_set_cookie(
            db, app, headers={"X-Forwarded-Proto": "https"}
        )
        assert "secure" not in cookie

    def test_invalid_mode_falls_back_to_auto(self, db):
        app = create_app(db=db, auth_token="a" * 32, cookie_secure_mode="garbage")
        cookie = self._login_and_get_set_cookie(
            db, app, headers={"X-Forwarded-Proto": "https"}
        )
        assert "secure" in cookie  # auto + https header → Secure


class TestSessionAuth:
    def _login(self, db, client, username="alice", password="SolidPass_88!"):
        with db.get_session() as s:
            create_user(s, username, password)
        resp = client.post(
            "/ui/login", data={"username": username, "password": password}
        )
        return resp.cookies["mksef_session"]

    def test_cookie_grants_ui_access(self, db, app_auth):
        client = TestClient(app_auth, follow_redirects=False, raise_server_exceptions=False)
        with db.get_session() as s:
            create_user(s, "alice", "SolidPass_88!")
        client.post("/ui/login", data={"username": "alice", "password": "SolidPass_88!"})
        resp = client.get("/ui")
        assert resp.status_code != 303
        assert resp.status_code != 401

    def test_cookie_grants_api_access(self, db, app_auth):
        client = TestClient(app_auth, follow_redirects=False)
        with db.get_session() as s:
            create_user(s, "alice", "SolidPass_88!")
        client.post("/ui/login", data={"username": "alice", "password": "SolidPass_88!"})
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
            create_user(s, "alice", "SolidPass_88!")
        client.cookies.set("mksef_session", "deadbeef" * 8)
        resp = client.get("/ui")
        assert resp.status_code == 303
        assert "/ui/login" in resp.headers["location"]


class TestLogout:
    def test_logout_revokes_db_session(self, db, app_auth):
        client = TestClient(app_auth, follow_redirects=False)
        with db.get_session() as s:
            create_user(s, "alice", "SolidPass_88!")
        login = client.post(
            "/ui/login", data={"username": "alice", "password": "SolidPass_88!"}
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
            create_user(s, "alice", "SolidPass_88!")
        client.post("/ui/login", data={"username": "alice", "password": "SolidPass_88!"})
        resp = client.post("/ui/logout")
        cookie_hdr = resp.headers.get("set-cookie", "").lower()
        assert "mksef_session" in cookie_hdr
        assert ("max-age=0" in cookie_hdr) or ("expires=" in cookie_hdr)


class TestAccountPasswordChange:
    def _login(self, db, client):
        with db.get_session() as s:
            create_user(s, "alice", "OldSolid_66!")
        client.post(
            "/ui/login", data={"username": "alice", "password": "OldSolid_66!"}
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
                "current_password": "OldSolid_66!",
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
                "current_password": "OldSolid_66!",
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
            assert not verify_password("OldSolid_66!", u.password_hash)

    def test_account_unauthenticated_redirects(self, client, db):
        with db.get_session() as s:
            create_user(s, "alice", "SolidPass_88!")
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
