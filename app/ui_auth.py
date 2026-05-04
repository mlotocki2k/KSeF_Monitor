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
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.database import UiSession, UiUser

logger = logging.getLogger(__name__)

# 7-day rolling sessions; refreshed on each authenticated request.
SESSION_TTL = timedelta(days=7)
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
    """Return error string or None. Whitelist: alphanumerics, dot, dash, underscore."""
    if not username:
        return "Nazwa użytkownika jest wymagana."
    if len(username) < USERNAME_MIN_LEN:
        return f"Nazwa użytkownika musi mieć co najmniej {USERNAME_MIN_LEN} znaków."
    if len(username) > USERNAME_MAX_LEN:
        return f"Nazwa użytkownika nie może przekraczać {USERNAME_MAX_LEN} znaków."
    if not all(c.isalnum() or c in "._-" for c in username):
        return "Nazwa użytkownika może zawierać tylko litery, cyfry, kropkę, myślnik i podkreślenie."
    return None


def validate_password(password: str) -> Optional[str]:
    """Return error string or None."""
    if not password:
        return "Hasło jest wymagane."
    if len(password) < PASSWORD_MIN_LEN:
        return f"Hasło musi mieć co najmniej {PASSWORD_MIN_LEN} znaków."
    return None


# ── User CRUD ───────────────────────────────────────────────────────────────


def count_users(session: Session) -> int:
    return session.execute(select(UiUser.id)).scalars().all().__len__()


def get_user_by_username(session: Session, username: str) -> Optional[UiUser]:
    return session.execute(
        select(UiUser).where(UiUser.username == username)
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
    db, username: str, password: str
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
                    "INSERT INTO ui_sessions (id, user_id, expires_at, created_at, last_accessed_at) "
                    "VALUES (:sid, :uid, :ex, :now, :now)"
                ),
                {"sid": sid, "uid": user_id, "ex": expires, "now": now},
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


def create_session(session: Session, user: UiUser) -> str:
    """Create a new session, persist it, return the opaque cookie value."""
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
        )
    )
    session.commit()
    return sid


def validate_session(
    session: Session, sid: Optional[str]
) -> Optional[Tuple[UiUser, UiSession]]:
    """Look up session by cookie value. Returns (user, session) on success.

    Sliding expiry: each successful validation extends expires_at by SESSION_TTL.
    """
    if not sid or len(sid) != 64:
        return None
    row = session.execute(
        select(UiSession).where(UiSession.id == sid)
    ).scalar_one_or_none()
    if row is None:
        return None
    now = datetime.now(timezone.utc)
    expires = row.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires < now:
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

    Auto-clears stale locks where locked_until is in the past.
    """
    from app.database import UiLoginAttempt

    row = session.get(UiLoginAttempt, username)
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
    one that triggered a fresh lockout, otherwise None.
    """
    from app.database import UiLoginAttempt

    now = datetime.now(timezone.utc)
    row = session.get(UiLoginAttempt, username)
    if row is None:
        row = UiLoginAttempt(username=username, failed_count=1, last_failed_at=now)
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
            "UI login locked for %r until %s (after %d failures)",
            username, locked_until.isoformat(), row.failed_count,
        )
    session.commit()
    return locked_until


def record_login_success(session: Session, username: str) -> None:
    """Reset fail counter / clear lock on successful login."""
    from app.database import UiLoginAttempt

    now = datetime.now(timezone.utc)
    row = session.get(UiLoginAttempt, username)
    if row is None:
        row = UiLoginAttempt(username=username, last_success_at=now)
        session.add(row)
    else:
        row.failed_count = 0
        row.locked_until = None
        row.last_success_at = now
    session.commit()
