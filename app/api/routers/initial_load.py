"""
Initial Load endpoints — start/status/cancel historical invoice import jobs.
"""

import logging
from datetime import datetime, timezone
from typing import Annotated, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, StringConstraints, field_validator, model_validator

JobIdPath = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")]

from app.api._limiter import limiter, _endpoint_limits

logger = logging.getLogger(__name__)

router = APIRouter(tags=["initial_load"])


class StartJobRequest(BaseModel):
    start_date: str  # ISO date string, e.g. "2024-01-01"
    end_date: str    # ISO date string, e.g. "2024-12-31"
    subject_types: list[str] = ["Subject1", "Subject2"]
    date_type: str = "Invoicing"

    @field_validator("subject_types")
    @classmethod
    def validate_subject_types(cls, v):
        allowed = {"Subject1", "Subject2", "Subject3", "SubjectAuthorized"}
        invalid = set(v) - allowed
        if invalid:
            raise ValueError(f"Invalid subject_types: {invalid}. Allowed: {allowed}")
        if not v:
            raise ValueError("subject_types must not be empty")
        return v

    @field_validator("date_type")
    @classmethod
    def validate_date_type(cls, v):
        allowed = {"Invoicing", "IssueDate"}
        if v not in allowed:
            raise ValueError(f"date_type must be one of {allowed}")
        return v

    @model_validator(mode="after")
    def check_range_not_excessive(self):
        """V5-11: reject ranges > 5 years to prevent KSeF API abuse / DB churn."""
        from datetime import datetime, timedelta
        try:
            start = datetime.fromisoformat(self.start_date)
            end = datetime.fromisoformat(self.end_date)
        except ValueError:
            # Let the endpoint's own date-parsing return 422 with a clearer msg
            return self
        if (end - start) > timedelta(days=1826):
            raise ValueError("date range exceeds 5 years (1826 days) — split into smaller jobs")
        return self


def _parse_date(date_str: str) -> Optional[datetime]:
    """Parse ISO date string to datetime (UTC midnight)."""
    try:
        return datetime.fromisoformat(date_str).replace(tzinfo=None)
    except ValueError:
        return None


@router.post("/initial-load/start")
@limiter.limit(lambda key: _endpoint_limits["initial_load_start"])
def start_initial_load(request: Request, body: StartJobRequest):
    """
    Start a new historical invoice import job.

    Parses the configured date range into ≤90-day windows and processes
    them sequentially in a background thread. Only one job can run at a time.
    """
    mgr = getattr(request.app.state, "initial_load_manager", None)
    if not mgr:
        return JSONResponse(
            status_code=503,
            content={"detail": "Initial load not configured"},
        )

    start_date = _parse_date(body.start_date)
    end_date = _parse_date(body.end_date)

    if not start_date or not end_date:
        return JSONResponse(
            status_code=422,
            content={"detail": "Invalid date format — use ISO 8601 (e.g. 2024-01-01)"},
        )

    if start_date >= end_date:
        return JSONResponse(
            status_code=422,
            content={"detail": "start_date must be before end_date"},
        )

    job_id = mgr.start_job(
        start_date=start_date,
        end_date=end_date,
        subject_types=body.subject_types,
        date_type=body.date_type,
    )

    if job_id is None:
        return JSONResponse(
            status_code=409,
            content={"detail": "Another initial load job is already running"},
        )

    return JSONResponse(
        status_code=202,
        content={"job_id": job_id, "status": "pending"},
    )


@router.get("/initial-load/status")
def get_initial_load_status(request: Request, job_id: Optional[JobIdPath] = None):
    """
    Get status of an initial load job.

    If job_id is omitted, returns the most recently created job.
    """
    mgr = getattr(request.app.state, "initial_load_manager", None)
    if not mgr:
        return JSONResponse(
            status_code=503,
            content={"detail": "Initial load not configured"},
        )

    status = mgr.get_status(job_id=job_id)
    if status is None:
        return JSONResponse(
            status_code=404,
            content={"detail": "No initial load job found"},
        )

    return status


@router.post("/initial-load/cancel")
def cancel_initial_load(request: Request, job_id: JobIdPath):
    """
    Cancel a running or pending initial load job.
    """
    mgr = getattr(request.app.state, "initial_load_manager", None)
    if not mgr:
        return JSONResponse(
            status_code=503,
            content={"detail": "Initial load not configured"},
        )

    cancelled = mgr.cancel_job(job_id)
    if not cancelled:
        return JSONResponse(
            status_code=404,
            content={"detail": "Job not found or not cancellable"},
        )

    return {"job_id": job_id, "status": "cancelled"}
