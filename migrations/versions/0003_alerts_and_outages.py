"""Add low charge and connection tracking, and outage history.

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("inverters", sa.Column("battery_full_voltage", sa.Float(), nullable=True))
    op.add_column("inverters", sa.Column("battery_empty_voltage", sa.Float(), nullable=True))
    op.add_column("inverters", sa.Column("low_charge_percent", sa.Integer(), nullable=True))
    for column in ("low_charge_alerted", "low_charge_pending", "offline_alerted"):
        op.add_column(
            "inverters",
            sa.Column(column, sa.Boolean(), nullable=False, server_default=sa.false()),
        )
        op.alter_column("inverters", column, server_default=None)
    op.add_column(
        "inverters",
        sa.Column("offline_readings", sa.Integer(), nullable=False, server_default="0"),
    )
    op.alter_column("inverters", "offline_readings", server_default=None)
    op.create_table(
        "outages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "inverter_id",
            sa.Integer(),
            sa.ForeignKey("inverters.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("outages")
    for column in (
        "offline_readings",
        "offline_alerted",
        "low_charge_pending",
        "low_charge_alerted",
        "low_charge_percent",
        "battery_empty_voltage",
        "battery_full_voltage",
    ):
        op.drop_column("inverters", column)
