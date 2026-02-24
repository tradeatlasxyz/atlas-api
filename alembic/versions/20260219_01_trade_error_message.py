"""Add error_message column to trades table

Revision ID: 20260219_01
Revises: 20260212_01
Create Date: 2026-02-19 10:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = "20260219_01"
down_revision = "20260212_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "trades",
        sa.Column("error_message", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("trades", "error_message")
