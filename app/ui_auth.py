"""
UI user authentication — bcrypt password hashing + opaque DB-backed sessions.

Distinct from `api.auth_token` (Bearer key for curl/integrations). UI users
are created via the /ui/setup wizard on first launch — no SSH/CLI required.

Sessions: opaque uuid4 hex stored in HttpOnly cookie + ui_sessions row.
Password change can revoke all sessions cleanly without rotating cookies.
"""

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


# ── Password hashing ────────────────────────────────────────────────────────


def hash_password(plaintext: str) -> str:
    """Hash plaintext password using bcrypt (12 rounds)."""
    return bcrypt.hashpw(
        plaintext.encode("utf-8"), bcrypt.gensalt(rounds=BCRYPT_ROUNDS)
    ).decode("utf-8")


def verify_password(plaintext: str, hashed: str) -> bool:
    """Constant-time bcrypt verification. Returns False on any error."""
    try:
        return bcrypt.checkpw(plaintext.encode("utf-8"), hashed.encode("utf-8"))
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
