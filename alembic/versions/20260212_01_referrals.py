"""Referral analytics and indexing tables

Revision ID: 20260212_01
Revises: 20260124_02
Create Date: 2026-02-12 09:30:00
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")

# revision identifiers, used by Alembic.
revision = "20260212_01"
down_revision = "20260124_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "referral_attributions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("chain_id", sa.Integer(), nullable=False, server_default=sa.text("42161")),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column(
            "vault_address",
            sa.String(length=42),
            sa.ForeignKey("vaults.address", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("trader_address", sa.String(length=42), nullable=True),
        sa.Column("referral_code", sa.String(length=66), nullable=True),
        sa.Column("referrer_address", sa.String(length=42), nullable=True),
        sa.Column("deposit_amount_wei", sa.BigInteger(), nullable=True),
        sa.Column("shares_wei", sa.BigInteger(), nullable=True),
        sa.Column("tx_hash", sa.String(length=66), nullable=False),
        sa.Column("log_index", sa.Integer(), nullable=False),
        sa.Column("block_number", sa.BigInteger(), nullable=False),
        sa.Column("block_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "trade_id",
            sa.Integer(),
            sa.ForeignKey("trades.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("metadata", JSON_TYPE, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("chain_id", "tx_hash", "log_index", name="uq_referral_attr_chain_tx_log"),
    )
    op.create_index("idx_referral_attr_referrer", "referral_attributions", ["referrer_address"], unique=False)
    op.create_index("idx_referral_attr_vault", "referral_attributions", ["vault_address"], unique=False)
    op.create_index("idx_referral_attr_trader", "referral_attributions", ["trader_address"], unique=False)
    op.create_index("idx_referral_attr_code", "referral_attributions", ["referral_code"], unique=False)
    op.create_index("ix_referral_attributions_chain_id", "referral_attributions", ["chain_id"], unique=False)
    op.create_index("ix_referral_attributions_vault_address", "referral_attributions", ["vault_address"], unique=False)
    op.create_index("ix_referral_attributions_trade_id", "referral_attributions", ["trade_id"], unique=False)
    op.create_index("ix_referral_attributions_block_number", "referral_attributions", ["block_number"], unique=False)
    op.create_index("ix_referral_attributions_tx_hash", "referral_attributions", ["tx_hash"], unique=False)

    op.create_table(
        "referral_reward_claims",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("chain_id", sa.Integer(), nullable=False, server_default=sa.text("42161")),
        sa.Column("referrer_address", sa.String(length=42), nullable=False),
        sa.Column("amount_wei", sa.BigInteger(), nullable=False),
        sa.Column("tx_hash", sa.String(length=66), nullable=False),
        sa.Column("log_index", sa.Integer(), nullable=False),
        sa.Column("block_number", sa.BigInteger(), nullable=False),
        sa.Column("block_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata", JSON_TYPE, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("chain_id", "tx_hash", "log_index", name="uq_referral_claim_chain_tx_log"),
    )
    op.create_index("idx_referral_claim_referrer", "referral_reward_claims", ["referrer_address"], unique=False)
    op.create_index("idx_referral_claim_block", "referral_reward_claims", ["block_number"], unique=False)
    op.create_index("ix_referral_reward_claims_chain_id", "referral_reward_claims", ["chain_id"], unique=False)
    op.create_index("ix_referral_reward_claims_referrer_address", "referral_reward_claims", ["referrer_address"], unique=False)
    op.create_index("ix_referral_reward_claims_tx_hash", "referral_reward_claims", ["tx_hash"], unique=False)
    op.create_index("ix_referral_reward_claims_block_number", "referral_reward_claims", ["block_number"], unique=False)

    op.create_table(
        "referral_indexer_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("indexer_key", sa.String(length=128), nullable=False),
        sa.Column("chain_id", sa.Integer(), nullable=False, server_default=sa.text("42161")),
        sa.Column("last_processed_block", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("indexer_key", name="uq_referral_indexer_state_key"),
    )
    op.create_index("ix_referral_indexer_state_indexer_key", "referral_indexer_state", ["indexer_key"], unique=False)

    op.create_table(
        "referral_abuse_reviews",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("referrer_address", sa.String(length=42), nullable=True),
        sa.Column("issue_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default=sa.text("'open'")),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("details", JSON_TYPE, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_referral_abuse_reviews_status", "referral_abuse_reviews", ["status"], unique=False)
    op.create_index("idx_referral_abuse_reviews_referrer", "referral_abuse_reviews", ["referrer_address"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_referral_abuse_reviews_referrer", table_name="referral_abuse_reviews")
    op.drop_index("idx_referral_abuse_reviews_status", table_name="referral_abuse_reviews")
    op.drop_table("referral_abuse_reviews")

    op.drop_index("ix_referral_indexer_state_indexer_key", table_name="referral_indexer_state")
    op.drop_table("referral_indexer_state")

    op.drop_index("ix_referral_reward_claims_block_number", table_name="referral_reward_claims")
    op.drop_index("ix_referral_reward_claims_tx_hash", table_name="referral_reward_claims")
    op.drop_index("ix_referral_reward_claims_referrer_address", table_name="referral_reward_claims")
    op.drop_index("ix_referral_reward_claims_chain_id", table_name="referral_reward_claims")
    op.drop_index("idx_referral_claim_block", table_name="referral_reward_claims")
    op.drop_index("idx_referral_claim_referrer", table_name="referral_reward_claims")
    op.drop_table("referral_reward_claims")

    op.drop_index("ix_referral_attributions_tx_hash", table_name="referral_attributions")
    op.drop_index("ix_referral_attributions_block_number", table_name="referral_attributions")
    op.drop_index("ix_referral_attributions_trade_id", table_name="referral_attributions")
    op.drop_index("ix_referral_attributions_vault_address", table_name="referral_attributions")
    op.drop_index("ix_referral_attributions_chain_id", table_name="referral_attributions")
    op.drop_index("idx_referral_attr_code", table_name="referral_attributions")
    op.drop_index("idx_referral_attr_trader", table_name="referral_attributions")
    op.drop_index("idx_referral_attr_vault", table_name="referral_attributions")
    op.drop_index("idx_referral_attr_referrer", table_name="referral_attributions")
    op.drop_table("referral_attributions")
