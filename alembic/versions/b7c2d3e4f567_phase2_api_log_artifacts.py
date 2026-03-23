"""phase2_api_log_artifacts_source

Revision ID: b7c2d3e4f567
Revises: a6a08e11ea74
Create Date: 2026-03-12 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7c2d3e4f567'
down_revision: Union[str, Sequence[str], None] = 'a6a08e11ea74'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add Phase 2 tables and columns."""
    # New table: api_request_log
    op.create_table(
        'api_request_log',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('endpoint', sa.String(), nullable=False),
        sa.Column('method', sa.String(length=10), nullable=False),
        sa.Column('nip', sa.String(), nullable=True),
        sa.Column('status_code', sa.Integer(), nullable=True),
        sa.Column('response_time_ms', sa.Float(), nullable=True),
        sa.Column('retry_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('invoices_returned', sa.Integer(), nullable=True),
        sa.Column('requested_at', sa.DateTime(), nullable=False,
                  server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_api_log_requested', 'api_request_log', [sa.text('requested_at DESC')])
    op.create_index('ix_api_log_endpoint', 'api_request_log', ['endpoint', 'status_code'])

    # New table: invoice_artifacts
    op.create_table(
        'invoice_artifacts',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('invoice_id', sa.Integer(), nullable=False),
        sa.Column('artifact_type', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=False, server_default='pending'),
        sa.Column('download_attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('file_path', sa.String(), nullable=True),
        sa.Column('file_hash', sa.String(), nullable=True),
        sa.Column('file_size', sa.Integer(), nullable=True),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False,
                  server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(), nullable=False,
                  server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['invoice_id'], ['invoices.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('invoice_id', 'artifact_type', name='uq_artifact_invoice_type'),
    )
    op.create_index('ix_artifact_status', 'invoice_artifacts', ['status'])
    op.create_index('ix_artifact_invoice', 'invoice_artifacts', ['invoice_id'])

    # Add 'source' column to invoices table
    with op.batch_alter_table('invoices', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('source', sa.String(), nullable=True, server_default='polling')
        )


def downgrade() -> None:
    """Remove Phase 2 tables and columns."""
    op.drop_index('ix_artifact_invoice', table_name='invoice_artifacts')
    op.drop_index('ix_artifact_status', table_name='invoice_artifacts')
    op.drop_table('invoice_artifacts')

    op.drop_index('ix_api_log_endpoint', table_name='api_request_log')
    op.drop_index('ix_api_log_requested', table_name='api_request_log')
    op.drop_table('api_request_log')

    with op.batch_alter_table('invoices', schema=None) as batch_op:
        batch_op.drop_column('source')
