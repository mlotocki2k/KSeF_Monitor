"""phase5_ui_users

Revision ID: e0f1g2h34567
Revises: d9e0f1g2h345
Create Date: 2026-04-23 09:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e0f1g2h34567'
down_revision: Union[str, Sequence[str], None] = 'd9e0f1g2h345'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add ui_users + ui_sessions tables for browser UI user accounts (V5-13)."""
    op.create_table(
        'ui_users',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('username', sa.String(length=64), nullable=False),
        sa.Column('password_hash', sa.String(length=255), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False,
                  server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('last_login_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_ui_users_username', 'ui_users', ['username'], unique=True)

    op.create_table(
        'ui_sessions',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False,
                  server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('last_accessed_at', sa.DateTime(), nullable=False,
                  server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['user_id'], ['ui_users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_ui_sessions_user', 'ui_sessions', ['user_id'])
    op.create_index('ix_ui_sessions_expires', 'ui_sessions', ['expires_at'])


def downgrade() -> None:
    """Remove ui_users + ui_sessions tables."""
    op.drop_index('ix_ui_sessions_expires', table_name='ui_sessions')
    op.drop_index('ix_ui_sessions_user', table_name='ui_sessions')
    op.drop_table('ui_sessions')
    op.drop_index('ix_ui_users_username', table_name='ui_users')
    op.drop_table('ui_users')
