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
from fastapi.responses import JSONResponse
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

    # Auth middleware (if token configured) — registered FIRST (innermost)
    if auth_token:
        if len(auth_token) < 32:
            logger.warning(
                "API auth_token is shorter than 32 characters - use a stronger token"
            )

        # V5-01: Narrow whitelist — docs + health only. UI and invoice
        # downloads now require auth. Legacy deployments behind a trusted
        # reverse proxy can re-enable UI bypass via api.ui_public=true.
        _EXEMPT_EXACT = {
            "/docs", "/redoc", "/openapi.json",
            "/api/v1/monitor/health",
        }

        @app.middleware("http")
        async def verify_auth(request: Request, call_next):
            path = request.url.path
            if path in _EXEMPT_EXACT:
                return await call_next(request)
            if ui_public and path.startswith("/ui"):
                return await call_next(request)

            auth_header = request.headers.get("Authorization", "")
            if not auth_header.startswith("Bearer "):
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Missing or invalid Authorization header"},
                )
            provided = auth_header[7:]
            if not hmac.compare_digest(provided, auth_token):
                logger.warning(
                    "Failed auth attempt from %s",
                    request.client.host if request.client else "unknown",
                )
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Invalid authentication token"},
                )
            return await call_next(request)
    else:
        logger.warning("API running without authentication - set api.auth_token for production")

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
