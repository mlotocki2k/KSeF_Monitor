"""
Push notification setup and management endpoints.
"""

import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["push"])


@router.get("/push/setup")
def get_push_setup(request: Request):
    """Get push pairing info: QR code (base64), pairing_code, status."""
    push_manager = getattr(request.app.state, "push_manager", None)
    if not push_manager:
        return JSONResponse(
            status_code=503,
            content={"detail": "Push notifications not configured"},
        )

    return push_manager.pairing_info


@router.post("/push/regenerate")
def regenerate_pairing(request: Request):
    """Regenerate pairing code and QR code."""
    push_manager = getattr(request.app.state, "push_manager", None)
    if not push_manager:
        return JSONResponse(
            status_code=503,
            content={"detail": "Push notifications not configured"},
        )

    if push_manager.regenerate_pairing_code():
        return push_manager.pairing_info
    else:
        return JSONResponse(
            status_code=502,
            content={"detail": "Failed to regenerate pairing code"},
        )
