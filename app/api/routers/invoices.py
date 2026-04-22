"""
Invoice endpoints — read-only access to invoice data.

All queries use SQLAlchemy ORM (parametrized) — no raw SQL.
Response models ensure only declared fields are serialized.
"""

import logging
import os
import re
from io import BytesIO
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from app.api._limiter import limiter, _endpoint_limits
from ..schemas import InvoiceDetail, InvoiceSummary, PaginatedInvoices

logger = logging.getLogger(__name__)

router = APIRouter(tags=["invoices"])

# Validation patterns
_NIP_PATTERN = re.compile(r"^\d{10}$")
_KSEF_PATTERN = re.compile(r"^\d{10}-\d{8}-[A-Z0-9]{6,}-[A-Z0-9]{2}$")


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
    if not _KSEF_PATTERN.match(ksef_number):
        return JSONResponse(
            status_code=400,
            content={"detail": "Invalid KSeF number format"},
        )
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


@router.get("/invoices/{ksef_number}/xml")
@limiter.limit(lambda key: _endpoint_limits["invoice_download"])
def get_invoice_xml(request: Request, ksef_number: str):
    """Return invoice XML — from cached file first, then live from KSeF API.

    Returns Content-Type: application/xml.
    Falls back to fetching from KSeF if local cache not found.
    """
    if not _KSEF_PATTERN.match(ksef_number):
        return JSONResponse(
            status_code=400,
            content={"detail": "Invalid KSeF number format"},
        )
    db = request.app.state.db
    monitor = request.app.state.monitor

    # Try cached artifact path from DB
    if db:
        from app.database import Invoice, InvoiceArtifact
        session = db.get_session()
        try:
            invoice = session.query(Invoice).filter_by(ksef_number=ksef_number).first()
            if not invoice:
                return JSONResponse(status_code=404, content={"detail": "Invoice not found"})

            artifact = (
                session.query(InvoiceArtifact)
                .filter_by(invoice_id=invoice.id, artifact_type="xml", status="downloaded")
                .first()
            )
            if artifact and artifact.file_path and os.path.exists(artifact.file_path):
                with open(artifact.file_path, "r", encoding="utf-8") as f:
                    xml_content = f.read()
                safe_filename = quote(f"{ksef_number}.xml")
                return Response(
                    content=xml_content,
                    media_type="application/xml",
                    headers={"Content-Disposition": f'attachment; filename="{safe_filename}"'},
                )
        finally:
            session.close()

    # Fallback: fetch live from KSeF API
    if not monitor or not hasattr(monitor, 'ksef'):
        return JSONResponse(status_code=503, content={"detail": "KSeF client not available"})

    try:
        result = monitor.ksef.get_invoice_xml(ksef_number)
        if not result:
            return JSONResponse(status_code=404, content={"detail": "XML not found on KSeF"})
        safe_filename = quote(f"{ksef_number}.xml")
        return Response(
            content=result["xml_content"],
            media_type="application/xml",
            headers={"Content-Disposition": f'attachment; filename="{safe_filename}"'},
        )
    except Exception as e:
        logger.error("Failed to fetch XML for %s: %s", ksef_number, e)
        return JSONResponse(status_code=502, content={"detail": "KSeF API error"})


@router.get("/invoices/{ksef_number}/pdf")
@limiter.limit(lambda key: _endpoint_limits["invoice_download"])
def get_invoice_pdf(request: Request, ksef_number: str):
    """Generate and return invoice PDF on demand.

    Checks for cached PDF first. If not cached, fetches XML from KSeF
    and generates PDF using the configured generator chain.
    Returns Content-Type: application/pdf.
    """
    if not _KSEF_PATTERN.match(ksef_number):
        return JSONResponse(
            status_code=400,
            content={"detail": "Invalid KSeF number format"},
        )
    db = request.app.state.db
    monitor = request.app.state.monitor

    # Try cached PDF first
    if db:
        from app.database import Invoice, InvoiceArtifact
        session = db.get_session()
        try:
            invoice = session.query(Invoice).filter_by(ksef_number=ksef_number).first()
            if not invoice:
                return JSONResponse(status_code=404, content={"detail": "Invoice not found"})

            artifact = (
                session.query(InvoiceArtifact)
                .filter_by(invoice_id=invoice.id, artifact_type="pdf", status="downloaded")
                .first()
            )
            if artifact and artifact.file_path and os.path.exists(artifact.file_path):
                with open(artifact.file_path, "rb") as f:
                    pdf_bytes = f.read()
                safe_filename = quote(f"{ksef_number}.pdf")
                return Response(
                    content=pdf_bytes,
                    media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{safe_filename}"'},
                )
        finally:
            session.close()

    # Need to generate PDF: fetch XML first
    if not monitor or not hasattr(monitor, 'ksef'):
        return JSONResponse(status_code=503, content={"detail": "KSeF client not available"})

    try:
        xml_result = monitor.ksef.get_invoice_xml(ksef_number)
        if not xml_result:
            return JSONResponse(status_code=404, content={"detail": "XML not found on KSeF"})

        xml_content = xml_result["xml_content"]
    except Exception as e:
        logger.error("Failed to fetch XML for %s: %s", ksef_number, e)
        return JSONResponse(status_code=502, content={"detail": "KSeF API error"})

    # Generate PDF
    try:
        from app.invoice_pdf_generator import generate_invoice_pdf
        environment = monitor.ksef.environment if monitor and hasattr(monitor, 'ksef') else ''
        tz_name = monitor.config.get_timezone() if monitor and hasattr(monitor.config, 'get_timezone') else ''
        ksef_gen_url = (monitor.config.get('storage', 'pdf_ksef_generator_url')
                        if monitor and hasattr(monitor, 'config') else None)
        buf = generate_invoice_pdf(xml_content, ksef_number=ksef_number,
                                   environment=environment, timezone=tz_name,
                                   ksef_generator_url=ksef_gen_url)
        if buf is None:
            return JSONResponse(
                status_code=422,
                content={"detail": "PDF generation not supported for this invoice schema"},
            )
        pdf_bytes = buf.read() if hasattr(buf, 'read') else buf
        safe_filename = quote(f"{ksef_number}.pdf")
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{safe_filename}"'},
        )
    except Exception as e:
        logger.error("PDF generation failed for %s: %s", ksef_number, e)
        return JSONResponse(status_code=500, content={"detail": "PDF generation failed"})
