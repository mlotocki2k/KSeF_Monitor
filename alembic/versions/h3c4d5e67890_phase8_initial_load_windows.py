"""phase8_initial_load_windows

Revision ID: h3c4d5e67890
Revises: g2b3c4d56789
Create Date: 2026-05-06 10:00:00.000000

Per-window log for initial load jobs — surface success/failure of each
date-range chunk in the GUI without grepping container stderr.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect as sa_inspect


revision: str = 'h3c4d5e67890'
down_revision: Union[str, Sequence[str], None] = 'g2b3c4d56789'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add initial_load_windows table. Idempotent against Base.metadata.create_all."""
    insp = sa_inspect(op.get_bind())
    if "initial_load_windows" not in insp.get_table_names():
        op.create_table(
            "initial_load_windows",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("job_id", sa.String(length=36), nullable=False, index=True),
            sa.Column("subject_type", sa.String(length=32), nullable=False),
            sa.Column("window_start", sa.DateTime(), nullable=False),
            sa.Column("window_end", sa.DateTime(), nullable=False),
            sa.Column("status", sa.String(length=24), nullable=False),
            sa.Column("imported", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("skipped", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("duration_ms", sa.Integer(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.current_timestamp(),
            ),
            sa.ForeignKeyConstraint(
                ["job_id"], ["initial_load_jobs.id"], ondelete="CASCADE"
            ),
        )
        op.create_index(
            "ix_initial_load_windows_job_created",
            "initial_load_windows",
            ["job_id", "created_at"],
        )


def downgrade() -> None:
    op.drop_index("ix_initial_load_windows_job_created", table_name="initial_load_windows")
    op.drop_table("initial_load_windows")
