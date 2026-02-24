"""Add strategy import fields

Revision ID: 20260123_02
Revises: 20260123_01
Create Date: 2026-01-23 22:55:00
"""
from alembic import op
import sqlalchemy as sa

revision = "20260123_02"
down_revision = "20260123_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("strategies", sa.Column("description", sa.Text(), nullable=True))
    op.add_column("strategies", sa.Column("code_path", sa.String(length=500), nullable=True))

    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("trades") as batch_op:
            batch_op.add_column(sa.Column("strategy_id", sa.Integer(), nullable=True))
            batch_op.create_index("idx_trades_strategy", ["strategy_id"], unique=False)
            batch_op.create_foreign_key(
                "fk_trades_strategy_id",
                "strategies",
                ["strategy_id"],
                ["id"],
                ondelete="CASCADE",
            )
            batch_op.alter_column("size", existing_type=sa.Numeric(20, 8), nullable=True)
    else:
        op.add_column("trades", sa.Column("strategy_id", sa.Integer(), nullable=True))
        op.create_index("idx_trades_strategy", "trades", ["strategy_id"], unique=False)
        op.create_foreign_key(
            "fk_trades_strategy_id",
            "trades",
            "strategies",
            ["strategy_id"],
            ["id"],
            ondelete="CASCADE",
        )
        op.alter_column("trades", "size", existing_type=sa.Numeric(20, 8), nullable=True)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("trades") as batch_op:
            batch_op.alter_column("size", existing_type=sa.Numeric(20, 8), nullable=False)
            batch_op.drop_constraint("fk_trades_strategy_id", type_="foreignkey")
            batch_op.drop_index("idx_trades_strategy")
            batch_op.drop_column("strategy_id")
    else:
        op.alter_column("trades", "size", existing_type=sa.Numeric(20, 8), nullable=False)
        op.drop_constraint("fk_trades_strategy_id", "trades", type_="foreignkey")
        op.drop_index("idx_trades_strategy", table_name="trades")
        op.drop_column("trades", "strategy_id")

    op.drop_column("strategies", "code_path")
    op.drop_column("strategies", "description")
