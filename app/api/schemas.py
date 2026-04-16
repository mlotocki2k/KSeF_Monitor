"""
Pydantic response models for the REST API.

Only declared fields are serialized — no accidental data leaks.
No internal IDs, file paths, or sensitive data in responses.
"""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


# ── Invoice schemas ──────────────────────────────────────────────────────


class InvoiceSummary(BaseModel):
    """Invoice list item — minimal data for listing."""

    ksef_number: str
    invoice_number: Optional[str] = None
    invoice_type: Optional[str] = None
    subject_type: str
    issue_date: Optional[str] = None
    gross_amount: Optional[float] = None
    currency: str = "PLN"
    seller_nip: str
    seller_name: Optional[str] = None
    buyer_nip: Optional[str] = None
    buyer_name: Optional[str] = None
    has_xml: bool = False
    has_pdf: bool = False
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class InvoiceDetail(InvoiceSummary):
    """Full invoice detail — extends summary with amounts and metadata."""

    net_amount: Optional[float] = None
    vat_amount: Optional[float] = None
    invoicing_date: Optional[datetime] = None
    acquisition_date: Optional[datetime] = None
    form_code: Optional[str] = None
    is_self_invoicing: bool = False
    has_attachment: bool = False
    source: Optional[str] = None
    updated_at: Optional[datetime] = None


class PaginatedInvoices(BaseModel):
    """Paginated invoice list response."""

    items: List[InvoiceSummary]
    total: int
    page: int
    per_page: int
    pages: int


# ── Stats schemas ────────────────────────────────────────────────────────


class StatsSummary(BaseModel):
    """Overall invoice statistics."""

    total_invoices: int = 0
    by_subject_type: dict = Field(default_factory=dict)
    by_month: dict = Field(default_factory=dict)


class ApiStats(BaseModel):
    """KSeF Monitor API call statistics."""

    total_requests: int = 0
    error_count: int = 0
    avg_response_time_ms: float = 0.0
    period_hours: int = 1


# ── Monitor schemas ──────────────────────────────────────────────────────


class MonitorStateResponse(BaseModel):
    """Monitor state for a NIP+subject pair."""

    nip: str
    subject_type: str
    last_check: Optional[datetime] = None
    last_invoice_at: Optional[datetime] = None
    last_ksef_number: Optional[str] = None
    invoices_count: int = 0
    consecutive_errors: int = 0
    status: str = "active"

    model_config = ConfigDict(from_attributes=True)


class HealthResponse(BaseModel):
    """Health check response (F-09: auth_enabled removed — info disclosure)."""

    status: str = "ok"
    version: str = "0.4.0"
    db_connected: bool = False


class TriggerResponse(BaseModel):
    """Response after triggering a check."""

    message: str
    triggered: bool


class PushResetResponse(BaseModel):
    """Response after resetting push credentials."""

    message: str
    reset: bool
    pairing_code: Optional[str] = None


# ── Artifact schemas ─────────────────────────────────────────────────────


class ArtifactResponse(BaseModel):
    """Artifact status (no file_path exposed)."""

    artifact_type: str
    status: str
    download_attempts: int = 0
    file_size: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class PendingArtifacts(BaseModel):
    """List of artifacts pending download."""

    items: List[ArtifactResponse]
    total: int
