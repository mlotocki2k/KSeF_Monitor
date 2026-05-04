"""
Web UI router — server-side rendered HTML dashboard.

Routes are excluded from OpenAPI schema (include_in_schema=False).
Auth is bypassed for these routes (added to whitelist in api/__init__.py),
matching the same policy as /docs — the port is typically bound to
127.0.0.1 or behind a reverse proxy.

Data is fetched directly from request.app.state.db (same as API routers)
to avoid internal HTTP calls and token management in browser.
"""

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from .._limiter import limiter

from app import __version__

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent.parent.parent / "ui" / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter(tags=["ui"], include_in_schema=False)

_NIP_RE = re.compile(r"^\d{10}$")


# ── Jinja2 filters ────────────────────────────────────────────────────────────

def _fmt_amount(value, currency: str = "PLN") -> str:
    """Format decimal amount as Polish number string."""
    if value is None:
        return "—"
    try:
        v = float(value)
        formatted = f"{v:,.2f}".replace(",", " ").replace(".", ",")
        return f"{formatted} {currency}"
    except (ValueError, TypeError):
        return str(value)


def _fmt_dt(value) -> str:
    """Format datetime to Polish-friendly string."""
    if value is None:
        return "—"
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return value
    try:
        return value.strftime("%d.%m.%Y %H:%M")
    except AttributeError:
        return str(value)


def _fmt_date(value) -> str:
    """Format date string."""
    if not value:
        return "—"
    return str(value)[:10]


def _subject_label(value: str) -> str:
    labels = {
        "Subject1": "Sprzedażowe",
        "Subject2": "Zakupowe",
        "Subject3": "Inne",
        "SubjectAuthorized": "Upoważniony",
    }
    return labels.get(value, value or "—")


def _ksef_short(value: str) -> str:
    """Return last 10 chars of KSeF number for compact display."""
    if not value:
        return "—"
    return f"…{value[-10:]}" if len(value) > 10 else value


templates.env.filters["fmt_amount"] = _fmt_amount
templates.env.filters["fmt_dt"] = _fmt_dt
templates.env.filters["fmt_date"] = _fmt_date
templates.env.filters["subject_label"] = _subject_label
templates.env.filters["ksef_short"] = _ksef_short


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_db(request: Request):
    return getattr(request.app.state, "db", None)


def _get_initial_load_manager(request: Request):
    return getattr(request.app.state, "initial_load_manager", None)


def _auth_token(request: Request) -> Optional[str]:
    """Return configured auth token (or None)."""
    return getattr(request.app.state, "auth_token", None) or None


def _get_push_manager(request: Request):
    return getattr(request.app.state, "push_manager", None)


def _base_ctx(request: Request) -> dict:
    nav = [
        {"href": "/ui", "label": "Dashboard"},
        {"href": "/ui/invoices", "label": "Faktury"},
        {"href": "/ui/initial-load", "label": "Import historyczny"},
    ]
    if _get_push_manager(request):
        nav.append({"href": "/ui/push", "label": "Parowanie iOS"})
    username = getattr(request.state, "ui_username", None)
    return {
        "request": request,
        "auth_required": bool(_auth_token(request)),
        "ui_username": username,
        "nav": nav,
        "docs_enabled": request.app.openapi_url is not None,
        "ui_version": __version__,
    }


# ── Dashboard ─────────────────────────────────────────────────────────────────

@router.get("/ui", response_class=HTMLResponse)
def ui_dashboard(request: Request):
    """Main dashboard — stats, monitor state, KSeF health."""
    db = _get_db(request)
    ctx = _base_ctx(request)
    ctx["page"] = "dashboard"

    if not db:
        ctx["error"] = "Baza danych niedostępna."
        return templates.TemplateResponse(request, "dashboard.html", ctx)

    from app.database import Invoice, MonitorState

    session = db.get_session()
    try:
        from sqlalchemy import func

        # Invoice counts
        total = session.query(Invoice).count()
        by_subject = dict(
            session.query(Invoice.subject_type, func.count(Invoice.id))
            .group_by(Invoice.subject_type)
            .all()
        )
        # Recent invoices (last 5)
        recent = (
            session.query(Invoice)
            .order_by(Invoice.created_at.desc())
            .limit(5)
            .all()
        )
        # Monitor state
        states = session.query(MonitorState).all()
    finally:
        session.close()

    # Initial load status
    il_mgr = _get_initial_load_manager(request)
    il_status = il_mgr.get_status() if il_mgr else None

    ctx.update({
        "total_invoices": total,
        "by_subject": by_subject,
        "monitor_states": states,
        "recent_invoices": recent,
        "il_status": il_status,
    })
    return templates.TemplateResponse(request, "dashboard.html", ctx)


# ── Invoice list ──────────────────────────────────────────────────────────────

@router.get("/ui/invoices", response_class=HTMLResponse)
def ui_invoices(
    request: Request,
    page: int = Query(1, ge=1, le=10000),
    per_page: int = Query(20, ge=1, le=100),
    subject_type: Optional[str] = None,
    seller_nip: Optional[str] = None,
    buyer_nip: Optional[str] = None,
    issue_date_from: Optional[str] = None,
    issue_date_to: Optional[str] = None,
    search: Optional[str] = None,
    sort_by: str = Query("created_at"),
    sort_order: str = Query("desc"),
):
    """Invoice list with pagination and filters."""
    db = _get_db(request)
    ctx = _base_ctx(request)
    ctx["page"] = "invoices"

    # Carry filters back to template
    filters = {
        "subject_type": subject_type or "",
        "seller_nip": seller_nip or "",
        "buyer_nip": buyer_nip or "",
        "issue_date_from": issue_date_from or "",
        "issue_date_to": issue_date_to or "",
        "search": search or "",
        "sort_by": sort_by,
        "sort_order": sort_order,
    }
    ctx["filters"] = filters

    if not db:
        ctx["error"] = "Baza danych niedostępna."
        ctx["invoices"] = []
        ctx["pagination"] = {"page": 1, "pages": 0, "total": 0, "per_page": per_page}
        return templates.TemplateResponse(request, "invoices.html", ctx)

    # Validate NIP
    errors = []
    if seller_nip and not _NIP_RE.match(seller_nip):
        errors.append("Nieprawidłowy format NIP sprzedawcy (10 cyfr).")
        seller_nip = None
    if buyer_nip and not _NIP_RE.match(buyer_nip):
        errors.append("Nieprawidłowy format NIP nabywcy (10 cyfr).")
        buyer_nip = None
    if errors:
        ctx["errors"] = errors

    from app.database import Invoice

    _SORT_COLS = {"created_at", "issue_date", "gross_amount", "ksef_number"}
    if sort_by not in _SORT_COLS:
        sort_by = "created_at"
    if sort_order not in ("asc", "desc"):
        sort_order = "desc"

    session = db.get_session()
    try:
        q = session.query(Invoice)

        if subject_type and subject_type in ("Subject1", "Subject2", "Subject3", "SubjectAuthorized"):
            q = q.filter(Invoice.subject_type == subject_type)
        if seller_nip:
            q = q.filter(Invoice.seller_nip == seller_nip)
        if buyer_nip:
            q = q.filter(Invoice.buyer_nip == buyer_nip)
        if issue_date_from:
            q = q.filter(Invoice.issue_date >= issue_date_from)
        if issue_date_to:
            q = q.filter(Invoice.issue_date <= issue_date_to)
        if search:
            term = f"%{search[:100]}%"
            q = q.filter(
                Invoice.ksef_number.contains(search[:100])
                | Invoice.invoice_number.contains(search[:100])
                | Invoice.seller_name.ilike(term)
                | Invoice.buyer_name.ilike(term)
            )

        total = q.count()
        sort_col = getattr(Invoice, sort_by, Invoice.created_at)
        q = q.order_by(sort_col.desc() if sort_order == "desc" else sort_col.asc())
        items = q.offset((page - 1) * per_page).limit(per_page).all()
        pages = max(1, (total + per_page - 1) // per_page) if total else 0
    finally:
        session.close()

    ctx.update({
        "invoices": items,
        "pagination": {"page": page, "pages": pages, "total": total, "per_page": per_page},
    })
    return templates.TemplateResponse(request, "invoices.html", ctx)


# ── Invoice detail ────────────────────────────────────────────────────────────

@router.get("/ui/invoices/{ksef_number:path}", response_class=HTMLResponse)
def ui_invoice_detail(request: Request, ksef_number: str):
    """Invoice detail view with optional PDF generation."""
    db = _get_db(request)
    ctx = _base_ctx(request)
    ctx["page"] = "invoices"

    if not db:
        ctx["error"] = "Baza danych niedostępna."
        return templates.TemplateResponse(request, "invoice_detail.html", ctx)

    from app.database import Invoice

    session = db.get_session()
    try:
        invoice = session.query(Invoice).filter_by(ksef_number=ksef_number).first()
        if not invoice:
            ctx["error"] = f"Faktura {ksef_number!r} nie znaleziona."
            return templates.TemplateResponse(request, "invoice_detail.html", ctx, status_code=404)

        # Parse raw_metadata if available
        raw = None
        if invoice.raw_metadata:
            try:
                raw = json.loads(invoice.raw_metadata)
            except (json.JSONDecodeError, TypeError):
                pass

        ctx["invoice"] = invoice
        ctx["raw_metadata"] = raw
    finally:
        session.close()

    return templates.TemplateResponse(request, "invoice_detail.html", ctx)


# ── Initial Load panel ────────────────────────────────────────────────────────

@router.get("/ui/initial-load", response_class=HTMLResponse)
def ui_initial_load(request: Request):
    """Initial load job status and controls."""
    ctx = _base_ctx(request)
    ctx["page"] = "initial_load"

    il_mgr = _get_initial_load_manager(request)
    ctx["il_available"] = il_mgr is not None
    ctx["il_status"] = il_mgr.get_status() if il_mgr else None

    # Read config defaults
    monitor = getattr(request.app.state, "monitor", None)
    cfg_start_date = ""
    cfg_subject_types = ["Subject1", "Subject2"]
    if monitor and hasattr(monitor, "config"):
        il_cfg = monitor.config.get("initial_load") or {}
        cfg_start_date = il_cfg.get("start_date", "")
        cfg_subject_types = il_cfg.get("subject_types", ["Subject1", "Subject2"])

    ctx["cfg_start_date"] = cfg_start_date
    ctx["cfg_subject_types"] = cfg_subject_types
    return templates.TemplateResponse(request, "initial_load.html", ctx)


# ── iOS Push pairing ──────────────────────────────────────────────────────────

@router.get("/ui/push", response_class=HTMLResponse)
def ui_push(request: Request):
    """iOS Push pairing page — QR code and pairing code."""
    ctx = _base_ctx(request)
    ctx["page"] = "push"

    push_manager = _get_push_manager(request)
    if not push_manager:
        ctx["error"] = "Push notifications not configured (ios_push.enabled = false)."
        ctx["push"] = None
        return templates.TemplateResponse(request, "push.html", ctx)

    ctx["push"] = push_manager.pairing_info
    return templates.TemplateResponse(request, "push.html", ctx)


# ── Setup / Login / Logout (V5-13 user accounts + DB sessions) ───────────────

_SESSION_COOKIE = "mksef_session"
_COOKIE_MAX_AGE = 60 * 60 * 24 * 7  # 7 days


def _safe_next(value: Optional[str]) -> str:
    """Whitelist redirect target to internal /ui paths only."""
    if not value:
        return "/ui"
    if value.startswith("//"):
        return "/ui"
    if value == "/ui" or value.startswith("/ui/"):
        return value
    return "/ui"


def _is_secure_request(request: Request) -> bool:
    """Determine whether the cookie should carry the Secure attribute.

    Honors `app.state.cookie_secure_mode`:
      - "always": Secure unconditionally (prod behind TLS-terminating proxy)
      - "never": Secure off (dev / plain-HTTP)
      - "auto" (default): trust X-Forwarded-Proto, fall back to request.url.scheme

    Pure request.url.scheme is wrong when uvicorn runs behind a reverse proxy
    that terminates TLS — scheme stays "http" and the cookie loses Secure
    despite the user-facing connection being HTTPS (U-01).
    """
    mode = getattr(request.app.state, "cookie_secure_mode", "auto") or "auto"
    if mode == "always":
        return True
    if mode == "never":
        return False
    fwd_proto = request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower()
    if fwd_proto in ("https", "http"):
        return fwd_proto == "https"
    return request.url.scheme == "https"


def _set_session_cookie(resp, sid: str, request: Request) -> None:
    resp.set_cookie(
        key=_SESSION_COOKIE,
        value=sid,
        max_age=_COOKIE_MAX_AGE,
        httponly=True,
        secure=_is_secure_request(request),
        samesite="strict",
        path="/",
    )


@router.get("/ui/setup", response_class=HTMLResponse)
def ui_setup_form(request: Request, error: Optional[str] = None):
    """First-launch wizard: create the initial user. Locked once any user exists."""
    db = _get_db(request)
    if db is not None:
        from app.ui_auth import count_users

        with db.get_session() as s:
            if count_users(s) > 0:
                return RedirectResponse(url="/ui/login", status_code=303)
    ctx = {
        "request": request,
        "error": error,
        "ui_version": __version__,
        "docs_enabled": request.app.openapi_url is not None,
    }
    return templates.TemplateResponse(request, "setup.html", ctx)


@router.post("/ui/setup")
@limiter.limit("3/minute")
def ui_setup_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    password_confirm: str = Form(...),
):
    """Create the initial user atomically (race-safe). Auto-login on success."""
    from app.ui_auth import (
        create_first_admin_atomic,
        validate_password,
        validate_username,
    )

    db = _get_db(request)
    if db is None:
        return RedirectResponse(url="/ui/setup?error=db", status_code=303)

    username = username.strip()
    err = (
        validate_username(username)
        or validate_password(password)
        or (None if password == password_confirm else "Hasła nie są takie same.")
    )
    if err:
        from urllib.parse import quote

        return RedirectResponse(
            url=f"/ui/setup?error={quote(err)}", status_code=303
        )

    # Atomic check-and-insert via BEGIN IMMEDIATE — closes U-06 race window.
    result = create_first_admin_atomic(db, username, password)
    if result is None:
        return RedirectResponse(url="/ui/login", status_code=303)
    _, sid = result

    resp = RedirectResponse(url="/ui", status_code=303)
    _set_session_cookie(resp, sid, request)
    return resp


@router.get("/ui/login", response_class=HTMLResponse)
def ui_login_form(
    request: Request,
    next: Optional[str] = None,
    error: Optional[str] = None,
):
    """Render login form. Public. If no users exist, bounce to setup."""
    db = _get_db(request)
    if db is not None:
        from app.ui_auth import count_users

        with db.get_session() as s:
            if count_users(s) == 0:
                return RedirectResponse(url="/ui/setup", status_code=303)
    if not _auth_token(request):
        return RedirectResponse(url="/ui", status_code=303)
    ctx = {
        "request": request,
        "next": _safe_next(next),
        "error": error,
        "ui_version": __version__,
        "docs_enabled": request.app.openapi_url is not None,
    }
    return templates.TemplateResponse(request, "login.html", ctx)


@router.post("/ui/login")
@limiter.limit("5/minute")
def ui_login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next: Optional[str] = Form(None),
):
    """Validate user/pass, create DB session, set HttpOnly cookie, redirect."""
    from app.ui_auth import (
        count_users,
        create_session,
        dummy_password_hash,
        get_user_by_username,
        is_login_locked,
        record_login_failure,
        record_login_success,
        verify_password,
    )

    target = _safe_next(next)
    db = _get_db(request)
    if db is None:
        return RedirectResponse(url="/ui/login?error=db", status_code=303)

    username = username.strip()

    with db.get_session() as s:
        if count_users(s) == 0:
            return RedirectResponse(url="/ui/setup", status_code=303)

        # U-03 — check lockout BEFORE bcrypt to deny attacker the timing oracle
        # and to keep DoS-via-bcrypt off the table for a hot-locked account.
        if is_login_locked(s, username):
            client_host = request.client.host if request.client else "unknown"
            logger.warning(
                "UI login blocked (locked) for username_len=%d from %s",
                len(username), client_host,
            )
            return RedirectResponse(
                url=f"/ui/login?next={target}&error=locked", status_code=303
            )

        user = get_user_by_username(s, username)
        # U-07 partial — always run bcrypt to keep timing constant whether the
        # username exists or not. Combined with U-03 lockout this prevents
        # both "exists vs not" probes and unbounded brute-force.
        password_ok = verify_password(
            password, user.password_hash if user else dummy_password_hash()
        )
        if user is None or not password_ok:
            record_login_failure(s, username)
            client_host = request.client.host if request.client else "unknown"
            logger.warning(
                "Failed UI login (username_len=%d) from %s",
                len(username), client_host,
            )
            return RedirectResponse(
                url=f"/ui/login?next={target}&error=invalid", status_code=303
            )

        record_login_success(s, username)
        sid = create_session(s, user)

    resp = RedirectResponse(url=target, status_code=303)
    _set_session_cookie(resp, sid, request)
    return resp


@router.post("/ui/logout")
def ui_logout(request: Request):
    """Revoke session in DB and clear cookie."""
    db = _get_db(request)
    sid = request.cookies.get(_SESSION_COOKIE)
    if db is not None and sid:
        from app.ui_auth import revoke_session

        with db.get_session() as s:
            revoke_session(s, sid)
    resp = RedirectResponse(url="/ui/login", status_code=303)
    resp.delete_cookie(_SESSION_COOKIE, path="/")
    return resp


@router.get("/ui/account", response_class=HTMLResponse)
def ui_account_form(request: Request, error: Optional[str] = None, ok: Optional[str] = None):
    """Account page — change password."""
    if getattr(request.state, "ui_user_id", None) is None:
        return RedirectResponse(url="/ui/login?next=/ui/account", status_code=303)
    ctx = _base_ctx(request)
    ctx["page"] = "account"
    ctx["error"] = error
    ctx["ok"] = ok
    return templates.TemplateResponse(request, "account.html", ctx)


@router.post("/ui/account/password")
@limiter.limit("5/minute")
def ui_account_change_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    new_password_confirm: str = Form(...),
):
    """Change own password. Revokes all sessions including current — forces re-login."""
    from urllib.parse import quote

    from app.database import UiUser
    from app.ui_auth import set_password, validate_password, verify_password

    user_id = getattr(request.state, "ui_user_id", None)
    db = _get_db(request)
    if user_id is None or db is None:
        return RedirectResponse(url="/ui/login", status_code=303)

    err = validate_password(new_password) or (
        None if new_password == new_password_confirm else "Hasła nie są takie same."
    )
    if err:
        return RedirectResponse(
            url=f"/ui/account?error={quote(err)}", status_code=303
        )

    with db.get_session() as s:
        fresh = s.get(UiUser, user_id)
        if fresh is None or not verify_password(current_password, fresh.password_hash):
            return RedirectResponse(
                url=f"/ui/account?error={quote('Aktualne hasło nieprawidłowe.')}",
                status_code=303,
            )
        set_password(s, fresh, new_password)
    resp = RedirectResponse(url="/ui/login?ok=password", status_code=303)
    resp.delete_cookie(_SESSION_COOKIE, path="/")
    return resp
