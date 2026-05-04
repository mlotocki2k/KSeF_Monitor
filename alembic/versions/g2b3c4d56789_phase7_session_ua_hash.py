"""phase7_session_ua_hash

Revision ID: g2b3c4d56789
Revises: f1a2b3c45678
Create Date: 2026-05-04 13:00:00.000000

Add ua_hash column to ui_sessions for opt-in UA-fingerprint binding (U-04).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'g2b3c4d56789'
down_revision: Union[str, Sequence[str], None] = 'f1a2b3c45678'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'ui_sessions',
        sa.Column('ua_hash', sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('ui_sessions', 'ua_hash')
