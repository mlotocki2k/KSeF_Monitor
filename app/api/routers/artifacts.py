"""
Artifact status endpoints — no file paths exposed in responses.
"""

import logging

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from ..schemas import ArtifactResponse, PendingArtifacts

logger = logging.getLogger(__name__)

router = APIRouter(tags=["artifacts"])


@router.get("/artifacts/pending", response_model=PendingArtifacts)
def get_pending_artifacts(
    request: Request,
    limit: int = Query(50, ge=1, le=100),
):
    """List artifacts pending download."""
    db = request.app.state.db
    if not db:
        return JSONResponse(status_code=503, content={"detail": "Database not available"})

    session = db.get_session()
    try:
        items = db.get_pending_artifacts(session, limit=limit)
        return PendingArtifacts(
            items=[ArtifactResponse.model_validate(a) for a in items],
            total=len(items),
        )
    finally:
        session.close()
