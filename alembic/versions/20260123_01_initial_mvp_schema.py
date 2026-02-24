"""Initial MVP schema

Revision ID: 20260123_01
Revises: 
Create Date: 2026-01-23 21:10:00
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")

# revision identifiers, used by Alembic.
revision = "20260123_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "strategies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("strategy_type", sa.String(length=100), nullable=False),
        sa.Column("asset", sa.String(length=50), nullable=False),
        sa.Column("timeframe", sa.String(length=20), nullable=False),
        sa.Column("leverage_range", sa.String(length=50)),
        sa.Column("status", sa.String(length=20), server_default=sa.text("'preview'")),
        sa.Column("featured", sa.Boolean(), server_default=sa.text("false")),
        sa.Column("passed_curation", sa.Boolean(), server_default=sa.text("false")),
        sa.Column("parameters", JSON_TYPE),
        sa.Column(
            "discovered_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("slug"),
    )
    op.create_index("idx_strategies_slug", "strategies", ["slug"], unique=True)
    op.create_index("idx_strategies_status", "strategies", ["status"], unique=False)
    op.create_index(
        "idx_strategies_asset_timeframe",
        "strategies",
        ["asset", "timeframe"],
        unique=False,
    )

    op.create_table(
        "investor_reports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "strategy_id",
            sa.Integer(),
            sa.ForeignKey("strategies.id", ondelete="CASCADE"),
            unique=True,
        ),
        sa.Column("win_rate", sa.Numeric(5, 4)),
        sa.Column("total_return", sa.Numeric(10, 4)),
        sa.Column("sharpe", sa.Numeric(6, 3)),
        sa.Column("sortino", sa.Numeric(6, 3)),
        sa.Column("max_drawdown", sa.Numeric(5, 4)),
        sa.Column("trade_count", sa.Integer()),
        sa.Column("profit_factor", sa.Numeric(8, 3)),
        sa.Column("avg_trade_duration", sa.String(length=50)),
        sa.Column("leverage", sa.Numeric(6, 2)),
        sa.Column("description", sa.Text()),
        sa.Column("report_url", sa.String(length=500)),
        sa.Column("equity_curve", JSON_TYPE),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
    )

    op.create_table(
        "vaults",
        sa.Column("address", sa.String(length=42), primary_key=True),
        sa.Column("strategy_id", sa.Integer(), sa.ForeignKey("strategies.id")),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("chain", sa.String(length=50), server_default=sa.text("'base'")),
        sa.Column("tvl", sa.Numeric(20, 8)),
        sa.Column("share_price", sa.Numeric(20, 8)),
        sa.Column("depositor_count", sa.Integer()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("idx_vaults_strategy", "vaults", ["strategy_id"], unique=False)

    op.create_table(
        "trades",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "vault_address",
            sa.String(length=42),
            sa.ForeignKey("vaults.address", ondelete="CASCADE"),
        ),
        sa.Column("trade_num", sa.Integer(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("side", sa.String(length=10), nullable=False),
        sa.Column("asset", sa.String(length=50), nullable=False),
        sa.Column("size", sa.Numeric(20, 8), nullable=False),
        sa.Column("entry_price", sa.Numeric(20, 8), nullable=False),
        sa.Column("exit_price", sa.Numeric(20, 8)),
        sa.Column("exit_timestamp", sa.DateTime(timezone=True)),
        sa.Column("pnl", sa.Numeric(20, 8)),
        sa.Column("pnl_pct", sa.Numeric(8, 4)),
        sa.Column("result", sa.String(length=10)),
        sa.Column("tx_hash", sa.String(length=66)),
    )
    op.create_index(
        "idx_trades_vault_timestamp",
        "trades",
        ["vault_address", "timestamp"],
        unique=False,
    )

    op.create_table(
        "performance_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "vault_address",
            sa.String(length=42),
            sa.ForeignKey("vaults.address", ondelete="CASCADE"),
        ),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tvl", sa.Numeric(20, 8), nullable=False),
        sa.Column("share_price", sa.Numeric(20, 8), nullable=False),
        sa.Column("depositor_count", sa.Integer()),
        sa.Column("daily_return", sa.Numeric(8, 4)),
    )
    op.create_index(
        "idx_snapshots_vault_timestamp",
        "performance_snapshots",
        ["vault_address", "timestamp"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_snapshots_vault_timestamp", table_name="performance_snapshots")
    op.drop_table("performance_snapshots")
    op.drop_index("idx_trades_vault_timestamp", table_name="trades")
    op.drop_table("trades")
    op.drop_index("idx_vaults_strategy", table_name="vaults")
    op.drop_table("vaults")
    op.drop_table("investor_reports")
    op.drop_index("idx_strategies_asset_timeframe", table_name="strategies")
    op.drop_index("idx_strategies_status", table_name="strategies")
    op.drop_index("idx_strategies_slug", table_name="strategies")
    op.drop_table("strategies")
