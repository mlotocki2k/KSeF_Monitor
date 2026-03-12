"""
Statistics endpoints — aggregated data, no PII.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import func

from ..schemas import ApiStats, StatsSummary

logger = logging.getLogger(__name__)

router = APIRouter(tags=["stats"])


@router.get("/stats/summary", response_model=StatsSummary)
def get_stats_summary(request: Request):
    """Get overall invoice statistics."""
    db = request.app.state.db
    if not db:
        return JSONResponse(status_code=503, content={"detail": "Database not available"})

    from app.database import Invoice

    session = db.get_session()
    try:
        total = session.query(Invoice).count()

        # By subject type
        by_subject = {}
        subject_counts = (
            session.query(Invoice.subject_type, func.count(Invoice.id))
            .group_by(Invoice.subject_type)
            .all()
        )
        for subject_type, count in subject_counts:
            by_subject[subject_type] = count

        # By month (issue_date is stored as ISO string YYYY-MM-DD)
        by_month = {}
        month_counts = (
            session.query(
                func.substr(Invoice.issue_date, 1, 7),
                func.count(Invoice.id),
            )
            .filter(Invoice.issue_date.isnot(None))
            .group_by(func.substr(Invoice.issue_date, 1, 7))
            .order_by(func.substr(Invoice.issue_date, 1, 7).desc())
            .limit(12)
            .all()
        )
        for month, count in month_counts:
            if month:
                by_month[month] = count

        return StatsSummary(
            total_invoices=total,
            by_subject_type=by_subject,
            by_month=by_month,
        )
    finally:
        session.close()


@router.get("/stats/api", response_model=ApiStats)
def get_api_stats(
    request: Request,
    hours: int = Query(1, ge=1, le=24),
):
    """Get KSeF API call statistics for the last N hours."""
    db = request.app.state.db
    if not db:
        return JSONResponse(status_code=503, content={"detail": "Database not available"})

    session = db.get_session()
    try:
        result = db.get_api_stats(session, hours=hours)
        return ApiStats(**result)
    finally:
        session.close()
