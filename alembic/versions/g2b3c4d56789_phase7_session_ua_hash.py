"""phase7_session_ua_hash

Revision ID: g2b3c4d56789
Revises: f1a2b3c45678
Create Date: 2026-05-04 13:00:00.000000

Add ua_hash column to ui_sessions for opt-in UA-fingerprint binding (U-04).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect as sa_inspect


# revision identifiers, used by Alembic.
revision: str = 'g2b3c4d56789'
down_revision: Union[str, Sequence[str], None] = 'f1a2b3c45678'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add ui_sessions.ua_hash column. Idempotent."""
    cols = [c["name"] for c in sa_inspect(op.get_bind()).get_columns("ui_sessions")]
    if "ua_hash" not in cols:
        op.add_column(
            "ui_sessions",
            sa.Column("ua_hash", sa.String(length=64), nullable=True),
        )


def downgrade() -> None:
    cols = [c["name"] for c in sa_inspect(op.get_bind()).get_columns("ui_sessions")]
    if "ua_hash" in cols:
        op.drop_column("ui_sessions", "ua_hash")
