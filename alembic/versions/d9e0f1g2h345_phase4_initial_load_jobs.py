"""phase4_initial_load_jobs

Revision ID: d9e0f1g2h345
Revises: c8d3e4f56789
Create Date: 2026-04-16 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd9e0f1g2h345'
down_revision: Union[str, Sequence[str], None] = 'c8d3e4f56789'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add initial_load_jobs table for async historical invoice import tracking."""
    op.create_table(
        'initial_load_jobs',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=False, server_default='pending'),
        sa.Column('subject_types', sa.Text(), nullable=False),
        sa.Column('date_type', sa.String(), nullable=False, server_default='Invoicing'),
        sa.Column('start_date', sa.DateTime(), nullable=False),
        sa.Column('end_date', sa.DateTime(), nullable=False),
        sa.Column('current_window_from', sa.DateTime(), nullable=True),
        sa.Column('current_window_to', sa.DateTime(), nullable=True),
        sa.Column('current_subject_type', sa.String(), nullable=True),
        sa.Column('windows_total', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('windows_completed', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('invoices_imported', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('invoices_skipped', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False,
                  server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(), nullable=False,
                  server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_initial_load_jobs_status', 'initial_load_jobs', ['status'])
    op.create_index('ix_initial_load_jobs_created', 'initial_load_jobs', ['created_at'])


def downgrade() -> None:
    """Remove initial_load_jobs table."""
    op.drop_index('ix_initial_load_jobs_created', table_name='initial_load_jobs')
    op.drop_index('ix_initial_load_jobs_status', table_name='initial_load_jobs')
    op.drop_table('initial_load_jobs')
