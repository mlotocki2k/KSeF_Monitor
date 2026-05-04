"""
REST API for KSeF Monitor.

FastAPI application factory with security defaults.
"""

import hmac
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app import __version__

# Import module-level limiter and per-endpoint limits from dedicated submodule
# (must come before .routers imports to avoid circular import)
from ._limiter import limiter, _endpoint_limits, configure_limiter  # noqa: F401

from .routers import invoices, stats, monitor, artifacts, push, initial_load, ui

logger = logging.getLogger(__name__)


def create_app(
    db=None,
    monitor_instance=None,
    auth_token: Optional[str] = None,
    cors_origins: Optional[list] = None,
    rate_limit_config: Optional[Dict[str, Any]] = None,
    docs_enabled: bool = True,
    prometheus_metrics=None,
    push_manager=None,
    initial_load_manager=None,
    ui_enabled: bool = True,
    ui_public: bool = False,     # V5-01 — opt-in bypass for legacy/reverse-proxy
    cookie_secure_mode: str = "auto",  # U-01 — "auto" | "always" | "never"
) -> FastAPI:
    """Create and configure FastAPI application.

    Args:
        db: Database instance for query access
        monitor_instance: InvoiceMonitor for state/trigger access
        auth_token: Shared secret for Bearer auth (None = open access)
        cors_origins: List of allowed CORS origins (empty = CORS disabled)
        rate_limit_config: Rate limiting settings {"enabled": bool, "default": str, ...}
        docs_enabled: Enable /docs and /redoc endpoints (False in prod, F-02)
    """
    app = FastAPI(
        title="KSeF Monitor API",
        version=__version__,
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
        openapi_url="/openapi.json" if docs_enabled else None,
        debug=False,
    )
    if not docs_enabled:
        logger.info("API docs disabled (/docs, /redoc, /openapi.json)")

    # Store shared state
    app.state.db = db
    app.state.monitor = monitor_instance
    app.state.auth_token = auth_token
    app.state.prometheus_metrics = prometheus_metrics
    app.state.push_manager = push_manager
    app.state.initial_load_manager = initial_load_manager
    if cookie_secure_mode not in ("auto", "always", "never"):
        logger.warning(
            "Invalid cookie_secure_mode %r — falling back to 'auto'",
            cookie_secure_mode,
        )
        cookie_secure_mode = "auto"
    app.state.cookie_secure_mode = cookie_secure_mode

    _SESSION_COOKIE = "mksef_session"

    # Auth gate — only when token configured. Registered FIRST so it runs
    # AFTER resolve_ui_session (Starlette: last-registered runs first).
    if auth_token:
        if len(auth_token) < 32:
            logger.warning(
                "API auth_token is shorter than 32 characters - use a stronger token"
            )

        # V5-01: narrow whitelist — docs + health only. UI requires auth.
        # V5-12: HttpOnly cookie session for browser UI.
        # V5-13: cookie is opaque DB session ID; /ui/setup public for first-launch wizard.
        _EXEMPT_EXACT = {
            "/docs", "/redoc", "/openapi.json",
            "/api/v1/monitor/health",
            "/ui/login", "/ui/logout", "/ui/setup",
        }

        @app.middleware("http")
        async def verify_auth(request: Request, call_next):
            path = request.url.path
            if path in _EXEMPT_EXACT:
                return await call_next(request)
            if ui_public and path.startswith("/ui"):
                return await call_next(request)

            # Cookie already validated by resolve_ui_session; ui_user_id
            # set means the session is valid.
            if getattr(request.state, "ui_user_id", None) is not None:
                return await call_next(request)

            auth_header = request.headers.get("Authorization", "")
            if auth_header.startswith("Bearer "):
                provided = auth_header[7:]
                if hmac.compare_digest(provided, auth_token):
                    return await call_next(request)
                logger.warning(
                    "Failed auth attempt from %s",
                    request.client.host if request.client else "unknown",
                )
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Invalid authentication token"},
                )

            if path.startswith("/ui"):
                # First-launch redirect: no users yet → setup wizard.
                db_local = getattr(request.app.state, "db", None)
                if db_local:
                    from app.ui_auth import count_users

                    with db_local.get_session() as s:
                        if count_users(s) == 0:
                            return RedirectResponse(
                                url="/ui/setup", status_code=303
                            )
                return RedirectResponse(
                    url=f"/ui/login?next={path}", status_code=303
                )
            return JSONResponse(
                status_code=401,
                content={"detail": "Missing or invalid Authorization header"},
            )
    else:
        logger.warning("API running without authentication - set api.auth_token for production")

    # Session resolver — ALWAYS runs, registered AFTER auth gate so it runs
    # FIRST in request flow (Starlette: last-registered = outermost).
    # Populates request.state.ui_user_id / ui_username whenever a valid
    # cookie is present. Works regardless of auth_token / ui_public so
    # navbar links and /ui/account continue to function under reverse-proxy
    # setups and bypass configurations.
    @app.middleware("http")
    async def resolve_ui_session(request: Request, call_next):
        db_local = getattr(request.app.state, "db", None)
        sid = request.cookies.get(_SESSION_COOKIE)
        if sid and db_local:
            from sqlalchemy.exc import DBAPIError, OperationalError

            from app.ui_auth import validate_session

            try:
                with db_local.get_session() as s:
                    result = validate_session(s, sid)
                    if result is not None:
                        user, _ = result
                        request.state.ui_user_id = user.id
                        request.state.ui_username = user.username
            except (OperationalError, DBAPIError) as exc:
                # DB hiccup (locked, disk full, schema drift) must not 500 the UI.
                # Narrower than bare Exception (U-15) so genuine programming
                # errors propagate.
                logger.warning("Session resolver failed: %s", exc)
        return await call_next(request)

    # Security headers middleware — registered LAST (outermost, always runs)
    @app.middleware("http")
    async def add_security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = (
            "geolocation=(), camera=(), microphone=()"
        )
        # CSP — Tailwind is now self-hosted; data: allowed for QR codes.
        # 'unsafe-inline' needed for push.html reveal script (Task 5).
        # Tighten to nonces/hashes in a follow-up when inline <script> moves
        # to external /ui/static/push.js.
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
            "script-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
            "connect-src 'self'; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self'"
        )
        return response

    # REST API Prometheus metrics middleware
    if prometheus_metrics:
        @app.middleware("http")
        async def track_rest_metrics(request: Request, call_next):
            response = await call_next(request)
            prometheus_metrics.rest_api_requests_total.labels(
                endpoint=request.url.path, method=request.method
            ).inc()
            return response

    # Rate limiting (F-07 / V5-06 security fix)
    rl_config = rate_limit_config or {}
    configure_limiter(rl_config)

    app.state.limiter = limiter
    app.state.rate_limit_config = rl_config
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)
    if rl_config.get("enabled", False):
        logger.info("API rate limiting: default=%s", rl_config.get("default", "60/minute"))

    # CORS (disabled by default, F-10: reject wildcard when auth enabled)
    if cors_origins:
        if "*" in cors_origins and auth_token:
            logger.warning(
                "CORS wildcard '*' rejected — not allowed when auth_token is set. "
                "CORS disabled."
            )
        else:
            app.add_middleware(
                CORSMiddleware,
                allow_origins=cors_origins,
                allow_methods=["GET"],
                allow_headers=["Authorization"],
            )

    # Register routers
    app.include_router(invoices.router, prefix="/api/v1")
    app.include_router(stats.router, prefix="/api/v1")
    app.include_router(monitor.router, prefix="/api/v1")
    app.include_router(artifacts.router, prefix="/api/v1")
    app.include_router(push.router, prefix="/api/v1")
    app.include_router(initial_load.router, prefix="/api/v1")
    if ui_enabled:
        app.include_router(ui.router)
        logger.info("Web UI enabled at /ui")

    static_dir = Path(__file__).parent.parent / "ui" / "static"
    if ui_enabled and static_dir.is_dir():
        app.mount(
            "/ui/static",
            StaticFiles(directory=str(static_dir)),
            name="ui-static",
        )
        logger.info("UI static files mounted at /ui/static from %s", static_dir)

    # Generic error handler — no stack traces in production
    @app.exception_handler(Exception)
    async def generic_error_handler(request: Request, exc: Exception):
        logger.error("Unhandled API error: %s", str(exc))
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
        )

    logger.info("FastAPI application created")
    return app
