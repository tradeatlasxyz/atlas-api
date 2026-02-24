"""Signal log table

Revision ID: 20260124_02
Revises: 20260124_01
Create Date: 2026-01-24 12:05:00
"""
from alembic import op
import sqlalchemy as sa


revision = "20260124_02"
down_revision = "20260124_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "signal_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "vault_address",
            sa.String(42),
            sa.ForeignKey("vaults.address", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "strategy_id",
            sa.Integer(),
            sa.ForeignKey("strategies.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("asset", sa.String(50), nullable=False),
        sa.Column("timeframe", sa.String(20), nullable=False),
        sa.Column("direction", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Numeric(6, 4), nullable=True),
        sa.Column("size_pct", sa.Numeric(6, 4), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("current_price", sa.Numeric(20, 8), nullable=True),
        sa.Column("stop_loss", sa.Numeric(20, 8), nullable=True),
        sa.Column("take_profit", sa.Numeric(20, 8), nullable=True),
    )
    op.create_index(
        "idx_signal_logs_vault_timestamp",
        "signal_logs",
        ["vault_address", "timestamp"],
        unique=False,
    )
    op.create_index(
        "idx_signal_logs_strategy",
        "signal_logs",
        ["strategy_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_signal_logs_strategy", table_name="signal_logs")
    op.drop_index("idx_signal_logs_vault_timestamp", table_name="signal_logs")
    op.drop_table("signal_logs")
