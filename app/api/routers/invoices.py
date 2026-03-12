"""
Invoice endpoints — read-only access to invoice data.

All queries use SQLAlchemy ORM (parametrized) — no raw SQL.
Response models ensure only declared fields are serialized.
"""

import logging
import re
from typing import Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from ..schemas import InvoiceDetail, InvoiceSummary, PaginatedInvoices

logger = logging.getLogger(__name__)

router = APIRouter(tags=["invoices"])

# Validation patterns
_NIP_PATTERN = re.compile(r"^\d{10}$")
_KSEF_PATTERN = re.compile(r"^\d{10}-\d{8}-[A-F0-9]{6}-[A-F0-9]{2}$")


@router.get("/invoices", response_model=PaginatedInvoices)
def list_invoices(
    request: Request,
    page: int = Query(1, ge=1, le=10000),
    per_page: int = Query(20, ge=1, le=100),
    subject_type: Optional[str] = Query(None, pattern="^(subject[12])$"),
    seller_nip: Optional[str] = None,
    buyer_nip: Optional[str] = None,
    issue_date_from: Optional[str] = None,
    issue_date_to: Optional[str] = None,
    search: Optional[str] = None,
    sort_by: str = Query("created_at", pattern="^(created_at|issue_date|gross_amount|ksef_number)$"),
    sort_order: str = Query("desc", pattern="^(asc|desc)$"),
):
    """List invoices with pagination, filtering, and sorting."""
    db = request.app.state.db
    if not db:
        return JSONResponse(status_code=503, content={"detail": "Database not available"})

    # Validate NIP format if provided
    if seller_nip and not _NIP_PATTERN.match(seller_nip):
        return JSONResponse(status_code=400, content={"detail": "Invalid seller_nip format (expected 10 digits)"})
    if buyer_nip and not _NIP_PATTERN.match(buyer_nip):
        return JSONResponse(status_code=400, content={"detail": "Invalid buyer_nip format (expected 10 digits)"})

    from app.database import Invoice

    session = db.get_session()
    try:
        query = session.query(Invoice)

        # Apply filters
        if subject_type:
            query = query.filter(Invoice.subject_type == subject_type)
        if seller_nip:
            query = query.filter(Invoice.seller_nip == seller_nip)
        if buyer_nip:
            query = query.filter(Invoice.buyer_nip == buyer_nip)
        if issue_date_from:
            query = query.filter(Invoice.issue_date >= issue_date_from)
        if issue_date_to:
            query = query.filter(Invoice.issue_date <= issue_date_to)
        if search:
            # Search in ksef_number, invoice_number, seller_name, buyer_name
            like_term = f"%{search[:100]}%"
            query = query.filter(
                Invoice.ksef_number.contains(search[:100])
                | Invoice.invoice_number.contains(search[:100])
                | Invoice.seller_name.ilike(like_term)
                | Invoice.buyer_name.ilike(like_term)
            )

        # Count before pagination
        total = query.count()

        # Sorting
        sort_column = getattr(Invoice, sort_by, Invoice.created_at)
        if sort_order == "desc":
            query = query.order_by(sort_column.desc())
        else:
            query = query.order_by(sort_column.asc())

        # Pagination
        offset = (page - 1) * per_page
        items = query.offset(offset).limit(per_page).all()

        pages = (total + per_page - 1) // per_page if total > 0 else 0

        return PaginatedInvoices(
            items=[InvoiceSummary.model_validate(inv) for inv in items],
            total=total,
            page=page,
            per_page=per_page,
            pages=pages,
        )
    finally:
        session.close()


@router.get("/invoices/{ksef_number}", response_model=InvoiceDetail)
def get_invoice(request: Request, ksef_number: str):
    """Get invoice details by KSeF number."""
    db = request.app.state.db
    if not db:
        return JSONResponse(status_code=503, content={"detail": "Database not available"})

    from app.database import Invoice

    session = db.get_session()
    try:
        invoice = session.query(Invoice).filter_by(ksef_number=ksef_number).first()
        if not invoice:
            return JSONResponse(status_code=404, content={"detail": "Invoice not found"})

        return InvoiceDetail.model_validate(invoice)
    finally:
        session.close()
