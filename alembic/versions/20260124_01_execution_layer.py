"""Execution layer schema updates

Revision ID: 20260124_01
Revises: 20260123_02
Create Date: 2026-01-24 10:00:00
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import JSON
from sqlalchemy.dialects import postgresql

revision = "20260124_01"
down_revision = "20260123_02"
branch_labels = None
depends_on = None


def _json_type():
    return postgresql.JSONB().with_variant(JSON, "sqlite")


def upgrade() -> None:
    op.add_column(
        "vaults",
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
    )
    op.add_column(
        "vaults",
        sa.Column(
            "check_interval", sa.String(10), nullable=False, server_default="1m"
        ),
    )
    op.add_column(
        "vaults",
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "vaults",
        sa.Column("synthetix_account_id", sa.Integer(), nullable=True),
    )

    op.add_column(
        "performance_snapshots",
        sa.Column("positions_json", _json_type(), nullable=True),
    )
    op.add_column(
        "performance_snapshots",
        sa.Column("unrealized_pnl", sa.Numeric(20, 8), nullable=True),
    )

    op.create_table(
        "historical_candles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("asset", sa.String(20), nullable=False),
        sa.Column("timeframe", sa.String(10), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("open", sa.Numeric(20, 8), nullable=False),
        sa.Column("high", sa.Numeric(20, 8), nullable=False),
        sa.Column("low", sa.Numeric(20, 8), nullable=False),
        sa.Column("close", sa.Numeric(20, 8), nullable=False),
        sa.Column("volume", sa.Numeric(20, 8), nullable=True),
    )
    op.create_index(
        "idx_candles_asset_tf_ts",
        "historical_candles",
        ["asset", "timeframe", "timestamp"],
        unique=False,
    )

    op.alter_column("vaults", "status", server_default=None)
    op.alter_column("vaults", "check_interval", server_default=None)


def downgrade() -> None:
    op.drop_index("idx_candles_asset_tf_ts", table_name="historical_candles")
    op.drop_table("historical_candles")

    op.drop_column("performance_snapshots", "unrealized_pnl")
    op.drop_column("performance_snapshots", "positions_json")

    op.drop_column("vaults", "synthetix_account_id")
    op.drop_column("vaults", "last_checked_at")
    op.drop_column("vaults", "check_interval")
    op.drop_column("vaults", "status")
