"""Add inverter display name and group chat for alerts.

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("inverters", sa.Column("display_name", sa.String(length=64), nullable=True))
    op.add_column("inverters", sa.Column("group_chat_id", sa.BigInteger(), nullable=True))
    op.add_column("inverters", sa.Column("group_chat_title", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("inverters", "group_chat_title")
    op.drop_column("inverters", "group_chat_id")
    op.drop_column("inverters", "display_name")
