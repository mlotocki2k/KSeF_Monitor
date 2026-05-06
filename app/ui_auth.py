"""
UI user authentication — bcrypt password hashing + opaque DB-backed sessions.

Distinct from `api.auth_token` (Bearer key for curl/integrations). UI users
are created via the /ui/setup wizard on first launch — no SSH/CLI required.

Sessions: opaque uuid4 hex stored in HttpOnly cookie + ui_sessions row.
Password change can revoke all sessions cleanly without rotating cookies.
"""

import base64
import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

import bcrypt
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.database import UiSession, UiUser

logger = logging.getLogger(__name__)

# 7-day rolling sessions; refreshed on each authenticated request.
SESSION_TTL = timedelta(days=7)
# Absolute upper bound regardless of sliding renewal (U-09): even an
# always-active user must re-authenticate every 30 days, capping the value
# of a stolen cookie.
SESSION_ABSOLUTE_LIFETIME = timedelta(days=30)
BCRYPT_ROUNDS = 12

USERNAME_MIN_LEN = 3
USERNAME_MAX_LEN = 64
PASSWORD_MIN_LEN = 8

_BCRYPT_INPUT_LIMIT = 72

# U-03 — per-username brute-force lockout
LOGIN_LOCKOUT_THRESHOLD = 5                       # fails before lock
LOGIN_LOCKOUT_DURATION = timedelta(minutes=15)
LOGIN_FAIL_WINDOW = timedelta(minutes=15)         # sliding window for counter

# Pre-computed bcrypt hash that NEVER matches a real password but takes the
# same ~250ms to verify — used for constant-time login when username does not
# exist (defense against timing-based username enumeration; U-07 partial,
# also closes a side-channel that bypasses U-03 lockout via fast-path).
_DUMMY_HASH = bcrypt.hashpw(
    b"____never_matches____", bcrypt.gensalt(rounds=BCRYPT_ROUNDS)
).decode("utf-8")


# ── Password hashing ────────────────────────────────────────────────────────


def _bcrypt_safe(plaintext: str) -> bytes:
    """Pre-hash long passwords with SHA256+base64 to bypass bcrypt's 72-byte limit.

    bcrypt 4.x silently truncated >72-byte inputs (collision risk); bcrypt 5.0
    raises ValueError. We SHA-256 + base64-encode (44 ASCII bytes, well under
    72) so collision space is the full 256-bit hash and behavior is uniform
    across bcrypt versions. Inputs ≤72 bytes pass through unchanged so that
    pre-existing hashes from short passwords still verify.
    """
    pw = plaintext.encode("utf-8")
    if len(pw) > _BCRYPT_INPUT_LIMIT:
        pw = base64.b64encode(hashlib.sha256(pw).digest())
    return pw


def hash_password(plaintext: str) -> str:
    """Hash plaintext password using bcrypt (12 rounds, SHA-256 pre-wrap >72B)."""
    return bcrypt.hashpw(
        _bcrypt_safe(plaintext), bcrypt.gensalt(rounds=BCRYPT_ROUNDS)
    ).decode("utf-8")


def verify_password(plaintext: str, hashed: str) -> bool:
    """Constant-time bcrypt verification. Returns False on any error."""
    try:
        return bcrypt.checkpw(_bcrypt_safe(plaintext), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# ── Validation ──────────────────────────────────────────────────────────────


def validate_username(username: str) -> Optional[str]:
    """Return error string or None. Whitelist: alphanumerics, dot, dash, underscore.

    Username is treated case-insensitively at lookup time (U-17), so reject
    inputs that would only differ from an existing user by case at validation
    time as well (handled by the case-insensitive uniqueness check elsewhere).
    """
    if not username:
        return "Nazwa użytkownika jest wymagana."
    if len(username) < USERNAME_MIN_LEN:
        return f"Nazwa użytkownika musi mieć co najmniej {USERNAME_MIN_LEN} znaków."
    if len(username) > USERNAME_MAX_LEN:
        return f"Nazwa użytkownika nie może przekraczać {USERNAME_MAX_LEN} znaków."
    if not all(c.isalnum() or c in "._-" for c in username):
        return "Nazwa użytkownika może zawierać tylko litery, cyfry, kropkę, myślnik i podkreślenie."
    return None


def validate_password(password: str, username: Optional[str] = None) -> Optional[str]:
    """Return error string or None.

    Length floor (PASSWORD_MIN_LEN), top-N breach blocklist, and a
    cross-field check that the password isn't a trivial mutation of the
    username (U-11). NOT a substitute for full zxcvbn / HIBP — meant to
    catch the obvious 80% (admin/admin, password123, etc.) without adding
    a 1MB+ corpus dependency to a self-hosted single-admin app.
    """
    if not password:
        return "Hasło jest wymagane."
    if len(password) < PASSWORD_MIN_LEN:
        return f"Hasło musi mieć co najmniej {PASSWORD_MIN_LEN} znaków."
    pw_lower = password.lower()
    if pw_lower in _COMMON_PASSWORDS:
        return "Hasło zbyt popularne — wybierz mniej oczywiste."
    if username:
        u = username.strip().lower()
        if u and len(u) >= 3 and u in pw_lower:
            return "Hasło nie może zawierać nazwy użytkownika."
    return None


# Top-100 most common breached passwords (rockyou-top-100 / NIST SP 800-63B
# guidance). Covers ~80% of real-world brute-force dictionary attempts with
# zero filesystem dependency. Stored lower-cased; comparison is case-insensitive.
_COMMON_PASSWORDS = frozenset({
    "123456", "123456789", "qwerty", "password", "1234567", "12345678",
    "12345", "iloveyou", "111111", "123123", "abc123", "qwerty123",
    "1q2w3e4r", "admin", "qwertyuiop", "654321", "555555", "lovely",
    "7777777", "welcome", "888888", "princess", "dragon", "password1",
    "123qwe", "1234567890", "monkey", "letmein", "1234", "1q2w3e",
    "starwars", "121212", "bailey", "passw0rd", "shadow", "123321",
    "654321", "superman", "qazwsx", "michael", "football", "123123123",
    "trustno1", "jordan23", "harley", "password123", "robert", "matthew",
    "jordan", "asshole", "daniel", "andrew", "lakers", "andrea",
    "buster", "joshua", "1qaz2wsx", "fuckyou", "nicole", "hunter",
    "ranger", "buster1", "thomas", "robert", "soccer", "killer",
    "pepper", "freedom", "ginger", "blowme", "bubbles", "2000",
    "1212", "computer", "654321", "summer", "internet", "service",
    "canada", "hello", "ranger", "shadow", "baseball", "donald",
    "harley", "hockey", "letmein", "maggie", "mike", "mustang",
    "snoopy", "buster", "george", "jennifer", "nicole", "amanda",
    "joshua", "jessica", "sunshine", "monkey", "asdfgh", "pussy",
    "money1", "michelle", "secret", "summer", "internet", "hello",
})


# ── User CRUD ───────────────────────────────────────────────────────────────


def count_users(session: Session) -> int:
    """Number of UI users. Uses COUNT(*) — does not materialize all rows (U-13)."""
    return int(session.execute(select(func.count(UiUser.id))).scalar_one() or 0)


def _normalize_username(username: str) -> str:
    """Canonical lookup form — case-insensitive (U-17)."""
    return username.strip().lower()


def get_user_by_username(session: Session, username: str) -> Optional[UiUser]:
    """Case-insensitive lookup (U-17): 'admin' and 'Admin' resolve to same row."""
    canonical = _normalize_username(username)
    return session.execute(
        select(UiUser).where(func.lower(UiUser.username) == canonical)
    ).scalar_one_or_none()


def create_user(session: Session, username: str, password: str) -> UiUser:
    """Create a new user. Caller must validate inputs first."""
    user = UiUser(username=username, password_hash=hash_password(password))
    session.add(user)
    session.commit()
    session.refresh(user)
    logger.info("UI user created: %s (id=%d)", username, user.id)
    return user


def create_first_admin_atomic(
    db, username: str, password: str, ua: Optional[str] = None
) -> Optional[Tuple[int, str]]:
    """Race-safe creation of the very first UI admin.

    Returns (user_id, session_id) on success or None if a concurrent request
    has already created the first user. The default ORM `count_users()` +
    `create_user()` flow leaves a TOCTOU window open under autocommit-off
    deferred-BEGIN: two simultaneous setup POSTs can both observe count=0,
    both insert, and end with two admin accounts (U-06).

    SQLite-specific resolution: `BEGIN IMMEDIATE` acquires the RESERVED lock
    eagerly, serializing concurrent writers; the second one sees count > 0
    inside the same transaction and rolls back.
    """
    from sqlalchemy import text

    pw_hash = hash_password(password)
    sid = secrets.token_hex(32)
    now = datetime.now(timezone.utc)
    expires = now + SESSION_TTL

    with db.engine.connect() as conn:
        conn.exec_driver_sql("BEGIN IMMEDIATE")
        try:
            n = conn.execute(text("SELECT COUNT(*) FROM ui_users")).scalar() or 0
            if n > 0:
                conn.exec_driver_sql("ROLLBACK")
                return None

            result = conn.execute(
                text(
                    "INSERT INTO ui_users (username, password_hash, created_at, last_login_at) "
                    "VALUES (:u, :h, :now, :now)"
                ),
                {"u": username, "h": pw_hash, "now": now},
            )
            user_id = result.lastrowid

            conn.execute(
                text(
                    "INSERT INTO ui_sessions (id, user_id, expires_at, "
                    "created_at, last_accessed_at, ua_hash) "
                    "VALUES (:sid, :uid, :ex, :now, :now, :ua_hash)"
                ),
                {
                    "sid": sid, "uid": user_id, "ex": expires, "now": now,
                    "ua_hash": hash_user_agent(ua),
                },
            )
            conn.exec_driver_sql("COMMIT")
            logger.info(
                "UI first-admin created (atomic): %s (id=%d)", username, user_id
            )
            return user_id, sid
        except Exception:
            conn.exec_driver_sql("ROLLBACK")
            raise


def set_password(session: Session, user: UiUser, new_password: str) -> None:
    """Update user's password and revoke all their sessions."""
    user.password_hash = hash_password(new_password)
    session.execute(delete(UiSession).where(UiSession.user_id == user.id))
    session.commit()
    logger.info("Password changed for user %s; all sessions revoked", user.username)


# ── Session lifecycle ───────────────────────────────────────────────────────


def hash_user_agent(ua: Optional[str]) -> Optional[str]:
    """SHA-256 hex of User-Agent header. Returns None for empty/missing UA."""
    if not ua:
        return None
    return hashlib.sha256(ua.encode("utf-8")).hexdigest()


def create_session(
    session: Session, user: UiUser, ua: Optional[str] = None
) -> str:
    """Create a new session, persist it, return the opaque cookie value.

    Stores SHA-256(ua) when `ua` is provided. The strict-binding mode in
    `validate_session` consults this column; enabling/disabling strict mode
    is a runtime app.state flag — the column is always populated when a UA
    is available so future flips don't require re-login.
    """
    sid = secrets.token_hex(32)  # 64-char hex, 256 bits of entropy
    now = datetime.now(timezone.utc)
    user.last_login_at = now
    session.add(
        UiSession(
            id=sid,
            user_id=user.id,
            expires_at=now + SESSION_TTL,
            created_at=now,
            last_accessed_at=now,
            ua_hash=hash_user_agent(ua),
        )
    )
    session.commit()
    # U-12 audit trail: surface enough to reconstruct "who logged in" without
    # leaking the cookie itself; first 8 hex chars give a stable correlation
    # token across one session's lifetime.
    logger.info(
        "UI login session created: user=%s (id=%d) sid=%s…",
        user.username, user.id, sid[:8],
    )
    return sid


def validate_session(
    session: Session,
    sid: Optional[str],
    ua: Optional[str] = None,
    strict_ua: bool = False,
) -> Optional[Tuple[UiUser, UiSession]]:
    """Look up session by cookie value. Returns (user, session) on success.

    Sliding expiry: each successful validation extends expires_at by SESSION_TTL.
    Absolute lifetime cap (U-09): even with sliding renewal, a session is
    discarded `SESSION_ABSOLUTE_LIFETIME` after `created_at`.
    Optional UA fingerprint binding (U-04): when `strict_ua=True` and the row
    has a stored `ua_hash`, the request's UA hash must match — mismatch
    revokes the session and returns None. Pre-existing sessions without
    `ua_hash` are not refused (graceful upgrade).
    """
    if not sid or len(sid) != 64:
        return None
    row = session.execute(
        select(UiSession).where(UiSession.id == sid)
    ).scalar_one_or_none()
    if row is None:
        return None
    now = datetime.now(timezone.utc)
    expires = _aware(row.expires_at)
    created = _aware(row.created_at)
    if expires is None or expires < now:
        session.execute(delete(UiSession).where(UiSession.id == sid))
        session.commit()
        return None
    if created is not None and now > created + SESSION_ABSOLUTE_LIFETIME:
        # Hard cap reached — force re-login regardless of recent activity.
        logger.info(
            "UI session sid=%s… exceeded absolute lifetime — revoking",
            sid[:8],
        )
        session.execute(delete(UiSession).where(UiSession.id == sid))
        session.commit()
        return None
    if strict_ua and row.ua_hash:
        request_ua_hash = hash_user_agent(ua)
        if request_ua_hash != row.ua_hash:
            logger.warning(
                "UI session UA fingerprint mismatch — revoking sid=%s…",
                sid[:8],
            )
            session.execute(delete(UiSession).where(UiSession.id == sid))
            session.commit()
            return None
    user = session.get(UiUser, row.user_id)
    if user is None:
        session.execute(delete(UiSession).where(UiSession.id == sid))
        session.commit()
        return None
    row.last_accessed_at = now
    row.expires_at = now + SESSION_TTL
    session.commit()
    return user, row


def revoke_session(session: Session, sid: str) -> None:
    session.execute(delete(UiSession).where(UiSession.id == sid))
    session.commit()
    logger.info("UI session revoked: sid=%s…", sid[:8])


def cleanup_expired_sessions(session: Session) -> int:
    """Delete all expired sessions. Returns count deleted."""
    now = datetime.now(timezone.utc)
    result = session.execute(delete(UiSession).where(UiSession.expires_at < now))
    session.commit()
    return result.rowcount or 0


# ── Brute-force lockout (U-03) ──────────────────────────────────────────────


def dummy_password_hash() -> str:
    """Return the dummy bcrypt hash used for constant-time non-existent-user
    verification. Exposed for tests.
    """
    return _DUMMY_HASH


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    """Coerce DB-loaded naive datetimes to UTC (SQLite drops tzinfo)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def is_login_locked(session: Session, username: str) -> Optional[datetime]:
    """Return locked_until (UTC) if username is currently locked, else None.

    Lookup keyed by lower-cased username so casing variants share the lock
    (cooperates with U-17 case-insensitive username lookup).

    Auto-clears stale locks where locked_until is in the past.
    """
    from app.database import UiLoginAttempt

    row = session.get(UiLoginAttempt, _normalize_username(username))
    if row is None:
        return None
    locked = _aware(row.locked_until)
    if locked is None:
        return None
    if locked > datetime.now(timezone.utc):
        return locked
    # stale lock — let it expire silently next failure cycle
    return None


def record_login_failure(
    session: Session, username: str
) -> Optional[datetime]:
    """Increment fail counter and, if threshold crossed, set lockout.

    Sliding window: counter resets if last failure happened more than
    `LOGIN_FAIL_WINDOW` ago. Returns `locked_until` if this failure was the
    one that triggered a fresh lockout, otherwise None. Counter keyed by
    lower-cased username (U-17 cooperation).
    """
    from app.database import UiLoginAttempt

    canonical = _normalize_username(username)
    now = datetime.now(timezone.utc)
    row = session.get(UiLoginAttempt, canonical)
    if row is None:
        row = UiLoginAttempt(username=canonical, failed_count=1, last_failed_at=now)
        session.add(row)
    else:
        last_failed = _aware(row.last_failed_at)
        if last_failed is not None and last_failed < now - LOGIN_FAIL_WINDOW:
            row.failed_count = 1
        else:
            row.failed_count = (row.failed_count or 0) + 1
        row.last_failed_at = now

    locked_until: Optional[datetime] = None
    if row.failed_count >= LOGIN_LOCKOUT_THRESHOLD:
        locked_until = now + LOGIN_LOCKOUT_DURATION
        row.locked_until = locked_until
        logger.warning(
            "UI login locked (username_len=%d) until %s (after %d failures)",
            len(canonical), locked_until.isoformat(), row.failed_count,
        )
    session.commit()
    return locked_until


def record_login_success(session: Session, username: str) -> None:
    """Reset fail counter / clear lock on successful login."""
    from app.database import UiLoginAttempt

    canonical = _normalize_username(username)
    now = datetime.now(timezone.utc)
    row = session.get(UiLoginAttempt, canonical)
    if row is None:
        row = UiLoginAttempt(username=canonical, last_success_at=now)
        session.add(row)
    else:
        row.failed_count = 0
        row.locked_until = None
        row.last_success_at = now
    session.commit()
