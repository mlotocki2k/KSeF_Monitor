"""phase3_push_instances

Revision ID: c8d3e4f56789
Revises: b7c2d3e4f567
Create Date: 2026-03-12 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c8d3e4f56789'
down_revision: Union[str, Sequence[str], None] = 'b7c2d3e4f567'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Idempotent: tables of later phases may already exist (created by
# Base.metadata.create_all on older app versions) — see app/database.py.
def _has_table(name: str) -> bool:
    return name in sa.inspect(op.get_bind()).get_table_names()


def _has_index(table: str, name: str) -> bool:
    return any(i["name"] == name for i in sa.inspect(op.get_bind()).get_indexes(table))


def _has_column(table: str, name: str) -> bool:
    return any(c["name"] == name for c in sa.inspect(op.get_bind()).get_columns(table))


def upgrade() -> None:
    """Add push_instances table for iOS push notification credentials."""
    if not _has_table('push_instances'):
        op.create_table(
            'push_instances',
            sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
            sa.Column('instance_id', sa.String(), nullable=False),
            sa.Column('instance_key', sa.String(), nullable=False),
            sa.Column('pairing_code', sa.String(), nullable=False),
            sa.Column('central_push_url', sa.String(), nullable=False,
                      server_default='https://push.monitorksef.com'),
            sa.Column('registered_at', sa.String(), nullable=True),
            sa.Column('label', sa.String(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False,
                      server_default=sa.text('CURRENT_TIMESTAMP')),
            sa.Column('updated_at', sa.DateTime(), nullable=False,
                      server_default=sa.text('CURRENT_TIMESTAMP')),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('instance_id'),
        )


def downgrade() -> None:
    """Remove push_instances table."""
    op.drop_table('push_instances')
