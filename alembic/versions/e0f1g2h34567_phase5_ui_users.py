"""phase5_ui_users

Revision ID: e0f1g2h34567
Revises: d9e0f1g2h345
Create Date: 2026-04-23 09:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect as sa_inspect


# revision identifiers, used by Alembic.
revision: str = 'e0f1g2h34567'
down_revision: Union[str, Sequence[str], None] = 'd9e0f1g2h345'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(name: str) -> bool:
    return name in sa_inspect(op.get_bind()).get_table_names()


def _has_index(table: str, name: str) -> bool:
    return any(i["name"] == name for i in sa_inspect(op.get_bind()).get_indexes(table))


def upgrade() -> None:
    """Add ui_users + ui_sessions tables for browser UI user accounts (V5-13).

    Idempotent: skips CREATE TABLE / CREATE INDEX if the artifact already
    exists. Defends against the create_all + alembic-stale-version drift
    where Base.metadata.create_all built the tables before alembic version
    was advanced past d9e0f1g2h345.
    """
    if not _has_table("ui_users"):
        op.create_table(
            "ui_users",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("username", sa.String(length=64), nullable=False),
            sa.Column("password_hash", sa.String(length=255), nullable=False),
            sa.Column(
                "created_at", sa.DateTime(), nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column("last_login_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
    if not _has_index("ui_users", "ix_ui_users_username"):
        op.create_index("ix_ui_users_username", "ui_users", ["username"], unique=True)

    if not _has_table("ui_sessions"):
        op.create_table(
            "ui_sessions",
            sa.Column("id", sa.String(length=64), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column(
                "created_at", sa.DateTime(), nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column(
                "last_accessed_at", sa.DateTime(), nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.ForeignKeyConstraint(["user_id"], ["ui_users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
    if not _has_index("ui_sessions", "ix_ui_sessions_user"):
        op.create_index("ix_ui_sessions_user", "ui_sessions", ["user_id"])
    if not _has_index("ui_sessions", "ix_ui_sessions_expires"):
        op.create_index("ix_ui_sessions_expires", "ui_sessions", ["expires_at"])


def downgrade() -> None:
    """Remove ui_users + ui_sessions tables."""
    op.drop_index('ix_ui_sessions_expires', table_name='ui_sessions')
    op.drop_index('ix_ui_sessions_user', table_name='ui_sessions')
    op.drop_table('ui_sessions')
    op.drop_index('ix_ui_users_username', table_name='ui_users')
    op.drop_table('ui_users')
