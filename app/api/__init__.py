"""
REST API for KSeF Monitor.

FastAPI application factory with security defaults.
"""

import hmac
import logging
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .routers import invoices, stats, monitor, artifacts

logger = logging.getLogger(__name__)


def create_app(
    db=None,
    monitor_instance=None,
    auth_token: Optional[str] = None,
    cors_origins: Optional[list] = None,
) -> FastAPI:
    """Create and configure FastAPI application.

    Args:
        db: Database instance for query access
        monitor_instance: InvoiceMonitor for state/trigger access
        auth_token: Shared secret for Bearer auth (None = open access)
        cors_origins: List of allowed CORS origins (empty = CORS disabled)
    """
    app = FastAPI(
        title="KSeF Monitor API",
        version="0.4.0",
        docs_url="/docs",
        redoc_url="/redoc",
        debug=False,
    )

    # Store shared state
    app.state.db = db
    app.state.monitor = monitor_instance
    app.state.auth_token = auth_token

    # Auth middleware (if token configured) — registered FIRST (innermost)
    if auth_token:
        if len(auth_token) < 32:
            logger.warning(
                "API auth_token is shorter than 32 characters - consider using a stronger token"
            )

        @app.middleware("http")
        async def verify_auth(request: Request, call_next):
            # Allow docs and health without auth
            if request.url.path in ("/docs", "/redoc", "/openapi.json",
                                     "/api/v1/monitor/health"):
                return await call_next(request)

            auth_header = request.headers.get("Authorization", "")
            if not auth_header.startswith("Bearer "):
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Missing or invalid Authorization header"},
                )

            provided_token = auth_header[7:]  # Strip "Bearer "
            if not hmac.compare_digest(provided_token, auth_token):
                logger.warning("Failed auth attempt from %s", request.client.host if request.client else "unknown")
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
        return response

    # CORS (disabled by default)
    if cors_origins:
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
