"""
Monitor state and health endpoints.
"""

import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app import __version__
from ..schemas import HealthResponse, MonitorStateResponse, TriggerResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["monitor"])


@router.get("/monitor/health", response_model=HealthResponse)
def health_check(request: Request):
    """Health check — always accessible (no auth required)."""
    db = request.app.state.db
    db_connected = False

    if db:
        try:
            session = db.get_session()
            from sqlalchemy import text
            session.execute(text("SELECT 1"))
            session.close()
            db_connected = True
        except Exception:
            pass

    return HealthResponse(
        status="ok",
        version=__version__,
        db_connected=db_connected,
    )


@router.get("/monitor/state", response_model=list)
def get_monitor_state(request: Request):
    """Get monitor state for all NIP+subject pairs."""
    db = request.app.state.db
    if not db:
        return JSONResponse(status_code=503, content={"detail": "Database not available"})

    from app.database import MonitorState

    session = db.get_session()
    try:
        states = session.query(MonitorState).all()
        return [MonitorStateResponse.model_validate(s) for s in states]
    finally:
        session.close()


@router.get("/monitor/ksef-status")
def ksef_api_status(request: Request):
    """Check KSeF API availability (public endpoint, no KSeF auth required).

    Probes /security/public-key-certificates as a connectivity check.
    Returns available, environment, latency_ms, http_status.
    """
    monitor = request.app.state.monitor
    if not monitor or not hasattr(monitor, 'ksef'):
        return JSONResponse(
            status_code=503,
            content={"available": False, "error": "Monitor not initialised", "environment": "unknown"},
        )
    try:
        status = monitor.ksef.get_api_status()
        return JSONResponse(content=status)
    except Exception as e:
        logger.error("KSeF status probe failed: %s", e)
        return JSONResponse(
            status_code=500,
            content={"available": False, "error": str(e), "environment": "unknown"},
        )


@router.post("/monitor/trigger", response_model=TriggerResponse)
def trigger_check(request: Request):
    """Trigger an immediate invoice check."""
    monitor = request.app.state.monitor
    if not monitor:
        return TriggerResponse(message="Monitor not available", triggered=False)

    try:
        # Signal the monitor to run a check on next cycle
        if hasattr(monitor, 'scheduler') and monitor.scheduler:
            monitor.scheduler.force_next_run()
            return TriggerResponse(
                message="Check scheduled for next cycle",
                triggered=True,
            )
        return TriggerResponse(
            message="Scheduler not available",
            triggered=False,
        )
    except Exception as e:
        logger.error("Failed to trigger check: %s", str(e))
        return TriggerResponse(message="Trigger failed", triggered=False)
