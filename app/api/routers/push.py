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


@router.post("/push/reset")
def reset_push(request: Request):
    """Reset push credentials — generates new instance_id, key, and pairing code.

    Previously paired iOS devices will be disconnected.
    New QR code is logged to Docker logs.
    """
    push_manager = getattr(request.app.state, "push_manager", None)
    if not push_manager:
        return JSONResponse(
            status_code=503,
            content={"detail": "Push notifications not configured"},
        )

    if push_manager.reset():
        return {
            "message": "Push credentials reset — check Docker logs for new QR code",
            "reset": True,
            **push_manager.pairing_info,
        }
    else:
        return JSONResponse(
            status_code=500,
            content={"detail": "Failed to reset push credentials"},
        )


@router.get("/push/devices")
def get_devices(request: Request):
    """List paired iOS devices (no raw tokens — device_id is sha256 of token)."""
    push_manager = getattr(request.app.state, "push_manager", None)
    if not push_manager:
        return JSONResponse(status_code=503, content={"detail": "Push not configured"})
    devices = push_manager.get_devices()
    return {"devices": devices, "total": len(devices)}


@router.post("/push/devices/remove")
def remove_device(request: Request, device_id: str):
    """Remove a specific paired device by device_id."""
    push_manager = getattr(request.app.state, "push_manager", None)
    if not push_manager:
        return JSONResponse(status_code=503, content={"detail": "Push not configured"})
    removed = push_manager.remove_device(device_id)
    return {"removed": removed}
