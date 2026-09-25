"""
REST API for KSeF Monitor.

FastAPI application factory with security defaults.
"""

import hmac
import logging
import secrets
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
from ._limiter import limiter, _endpoint_limits, configure_limiter, check_global_default_limit  # noqa: F401

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
    session_strict_binding: bool = False,  # U-04 — opt-in UA fingerprint
    trusted_origins: Optional[list] = None,  # extra origins for the same-origin check
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
    app.state.session_strict_binding = bool(session_strict_binding)

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
        # Failed Bearer attempts per client IP (independent of api.rate_limit)
        from limits import parse as _parse_limit
        from limits.storage import MemoryStorage
        from limits.strategies import MovingWindowRateLimiter

        _BEARER_FAIL_LIMIT = _parse_limit("10/15minutes")
        _bearer_failures = MovingWindowRateLimiter(MemoryStorage())

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
            # CSS/icons used by the login and setup pages — public assets;
            # StaticFiles itself refuses paths outside its directory.
            if ui_enabled and path.startswith("/ui/static/"):
                return await call_next(request)
            if ui_public and path.startswith("/ui"):
                return await call_next(request)

            # Cookie already validated by resolve_ui_session; ui_user_id
            # set means the session is valid.
            if getattr(request.state, "ui_user_id", None) is not None:
                return await call_next(request)

            auth_header = request.headers.get("Authorization", "")
            if auth_header.startswith("Bearer "):
                client_ip = request.client.host if request.client else "unknown"
                # Brute-force guard: the global rate limit is per path, so
                # guesses spread over many paths were not limited at all.
                if not _bearer_failures.test(_BEARER_FAIL_LIMIT, "bearer-fail", client_ip):
                    return JSONResponse(
                        status_code=429,
                        content={"detail": "Too many failed authentication attempts"},
                        headers={"Retry-After": "900"},
                    )
                provided = auth_header[7:]
                if hmac.compare_digest(provided.encode("utf-8"), auth_token.encode("utf-8")):
                    return await call_next(request)
                _bearer_failures.hit(_BEARER_FAIL_LIMIT, "bearer-fail", client_ip)
                logger.warning("Failed auth attempt from %s", client_ip)
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

    # CSRF defense in depth for the cookie session (SameSite=Strict already
    # blocks cross-site requests, but "same-site" includes sibling subdomains).
    # A browser state change made with a valid session must come from this
    # host. Compared by host name (ports differ behind proxies); the proxy's
    # public name comes from Host or the first X-Forwarded-Host entry, or from
    # api.trusted_origins when the proxy rewrites both. Requests without
    # Origin/Referer (non-browser clients), Bearer requests and requests
    # without a valid session are not affected.
    _SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
    from urllib.parse import urlsplit as _urlsplit

    _DEFAULT_PORTS = {"http": 80, "https": 443}

    def _authority(value: str):
        """(hostname, port or None) of an origin/URL/Host header value."""
        value = (value or "").strip()
        if not value:
            return None
        try:
            parts = _urlsplit(value if "//" in value else f"//{value}")
            host, port = parts.hostname, parts.port
        except ValueError:
            return None
        if not host:
            return None
        if port is not None and _DEFAULT_PORTS.get(parts.scheme) == port:
            port = None
        return host, port

    def _same_authority(source, allowed) -> bool:
        # Host names must match; ports too when both sides state one (a proxy
        # passing "Host: name" without the public port still matches).
        return source[0] == allowed[0] and (
            source[1] is None or allowed[1] is None or source[1] == allowed[1]
        )

    if isinstance(trusted_origins, str):
        trusted_origins = [trusted_origins]
    _trusted = [a for a in (_authority(o) for o in (trusted_origins or [])) if a]

    @app.middleware("http")
    async def same_origin_for_cookie_session(request: Request, call_next):
        if (
            request.method not in _SAFE_METHODS
            and getattr(request.state, "ui_user_id", None) is not None
            and not request.headers.get("authorization", "").startswith("Bearer ")
        ):
            source = request.headers.get("origin") or request.headers.get("referer")
            if source:
                source_auth = _authority(source)
                allowed = list(_trusted)
                for h in (
                    request.headers.get("host", ""),
                    request.headers.get("x-forwarded-host", "").split(",")[0],
                ):
                    auth = _authority(h)
                    if auth:
                        allowed.append(auth)
                if source_auth is None or not any(
                    _same_authority(source_auth, a) for a in allowed
                ):
                    logger.warning(
                        "Cross-origin %s %s rejected (cookie session)",
                        request.method, request.url.path,
                    )
                    return JSONResponse(
                        status_code=403,
                        content={"detail": "Cross-origin request rejected"},
                    )
        return await call_next(request)

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
                strict_ua = bool(getattr(request.app.state, "session_strict_binding", False))
                ua_header = request.headers.get("user-agent", "") or None
                with db_local.get_session() as s:
                    result = validate_session(
                        s, sid, ua=ua_header, strict_ua=strict_ua
                    )
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
        # U-05: per-request CSP nonce — generated BEFORE call_next so
        # templates can read it via request.state.csp_nonce when rendering
        # inline <script nonce="…"> tags.
        nonce = secrets.token_urlsafe(16)
        request.state.csp_nonce = nonce
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
        # CSP — script-src uses per-request nonce instead of 'unsafe-inline'
        # (U-05). style-src keeps 'unsafe-inline' because templates carry many
        # inline `style="…"` attributes (Tailwind utility deltas, dark theme
        # vars); a separate refactor is required to move them to a stylesheet.
        # data: allowed in img-src for QR codes / inline icons.
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
            f"script-src 'self' 'nonce-{nonce}'; "
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
            # Route template, not the raw path: raw paths carry invoice numbers
            # (seller NIP) and let unauthenticated clients mint unlimited series.
            route = request.scope.get("route")
            template = getattr(route, "path", None)
            if template:
                prefix = "/api/v1" if request.url.path.startswith("/api/v1/") else ""
                endpoint = prefix + template
            else:
                endpoint = "unmatched"
            prometheus_metrics.rest_api_requests_total.labels(
                endpoint=endpoint, method=request.method
            ).inc()
            return response

    # Rate limiting (F-07 / V5-06 security fix)
    rl_config = rate_limit_config or {}
    configure_limiter(rl_config)

    app.state.limiter = limiter
    app.state.rate_limit_config = rl_config
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)

    # Explicit global default-limit enforcement. slowapi's SlowAPIMiddleware fails
    # to apply the default limit to FastAPI include_router routes under Starlette
    # 1.x (route wrapped in `_IncludedRouter`, no `endpoint` → treated as exempt),
    # so enforce it here. Health/docs/static are exempt.
    _RL_EXEMPT = {"/docs", "/redoc", "/openapi.json", "/api/v1/monitor/health"}

    @app.middleware("http")
    async def enforce_global_default_limit(request: Request, call_next):
        path = request.url.path
        if path not in _RL_EXEMPT and not path.startswith("/ui/static"):
            if not check_global_default_limit(request):
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Rate limit exceeded"},
                    headers={"Retry-After": "60"},
                )
        return await call_next(request)

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
