"""phase6_login_attempts

Revision ID: f1a2b3c45678
Revises: e0f1g2h34567
Create Date: 2026-05-04 12:00:00.000000

Per-username failed-login counter + temporary lockout (audit U-03).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect as sa_inspect


# revision identifiers, used by Alembic.
revision: str = 'f1a2b3c45678'
down_revision: Union[str, Sequence[str], None] = 'e0f1g2h34567'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add ui_login_attempts table for per-username brute-force lockout.

    Idempotent: skips CREATE TABLE if Base.metadata.create_all already
    materialized the table on a stale-alembic-version deployment.
    """
    if "ui_login_attempts" not in sa_inspect(op.get_bind()).get_table_names():
        op.create_table(
            "ui_login_attempts",
            sa.Column("username", sa.String(length=64), nullable=False),
            sa.Column(
                "failed_count", sa.Integer(), nullable=False, server_default="0"
            ),
            sa.Column("locked_until", sa.DateTime(), nullable=True),
            sa.Column("last_failed_at", sa.DateTime(), nullable=True),
            sa.Column("last_success_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("username"),
        )


def downgrade() -> None:
    op.drop_table('ui_login_attempts')
