"""Create users, accounts and inverters.

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("telegram_id", sa.BigInteger(), autoincrement=False, primary_key=True),
        sa.Column("language", sa.String(length=8), nullable=False),
    )
    op.create_table(
        "accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.telegram_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("brand", sa.String(length=32), nullable=False),
        sa.Column("region", sa.String(length=16), nullable=False),
        sa.Column("encrypted_credentials", sa.LargeBinary(), nullable=False),
        sa.Column("needs_reauth", sa.Boolean(), nullable=False),
    )
    op.create_table(
        "inverters",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "account_id",
            sa.Integer(),
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("serial", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("notifications_enabled", sa.Boolean(), nullable=False),
        sa.Column("grid_state", sa.String(length=16), nullable=True),
        sa.Column("pending_grid_state", sa.String(length=16), nullable=True),
        sa.UniqueConstraint("account_id", "serial"),
    )


def downgrade() -> None:
    op.drop_table("inverters")
    op.drop_table("accounts")
    op.drop_table("users")
