from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


JSON_TYPE = JSONB().with_variant(JSON, "sqlite")


class Base(DeclarativeBase):
    pass


class Strategy(Base):
    __tablename__ = "strategies"
    __table_args__ = (
        Index("idx_strategies_status", "status"),
        Index("idx_strategies_asset_timeframe", "asset", "timeframe"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    slug: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    strategy_type: Mapped[str] = mapped_column(String(100))
    asset: Mapped[str] = mapped_column(String(50))
    timeframe: Mapped[str] = mapped_column(String(20))
    leverage_range: Mapped[Optional[str]] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(20), default="preview")
    featured: Mapped[bool] = mapped_column(default=False)
    passed_curation: Mapped[bool] = mapped_column(default=False)
    parameters: Mapped[Optional[dict]] = mapped_column(JSON_TYPE)
    description: Mapped[Optional[str]] = mapped_column(Text)
    code_path: Mapped[Optional[str]] = mapped_column(String(500))
    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    investor_report: Mapped[Optional["InvestorReport"]] = relationship(
        back_populates="strategy", uselist=False
    )
    vaults: Mapped[list["Vault"]] = relationship(back_populates="strategy")


class InvestorReport(Base):
    __tablename__ = "investor_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    strategy_id: Mapped[int] = mapped_column(
        ForeignKey("strategies.id", ondelete="CASCADE"), unique=True
    )
    win_rate: Mapped[Optional[float]] = mapped_column(Numeric(5, 4))
    total_return: Mapped[Optional[float]] = mapped_column(Numeric(10, 4))
    sharpe: Mapped[Optional[float]] = mapped_column(Numeric(6, 3))
    sortino: Mapped[Optional[float]] = mapped_column(Numeric(6, 3))
    max_drawdown: Mapped[Optional[float]] = mapped_column(Numeric(5, 4))
    trade_count: Mapped[Optional[int]] = mapped_column(Integer)
    profit_factor: Mapped[Optional[float]] = mapped_column(Numeric(8, 3))
    avg_trade_duration: Mapped[Optional[str]] = mapped_column(String(50))
    leverage: Mapped[Optional[float]] = mapped_column(Numeric(6, 2))
    description: Mapped[Optional[str]] = mapped_column(Text)
    report_url: Mapped[Optional[str]] = mapped_column(String(500))
    equity_curve: Mapped[Optional[list]] = mapped_column(JSON_TYPE)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )

    strategy: Mapped["Strategy"] = relationship(back_populates="investor_report")


class Vault(Base):
    __tablename__ = "vaults"
    __table_args__ = (Index("idx_vaults_strategy", "strategy_id"),)

    address: Mapped[str] = mapped_column(String(42), primary_key=True)
    strategy_id: Mapped[Optional[int]] = mapped_column(ForeignKey("strategies.id"))
    name: Mapped[str] = mapped_column(String(255))
    chain: Mapped[str] = mapped_column(String(50), default="arbitrum")
    status: Mapped[str] = mapped_column(String(20), default="active")
    check_interval: Mapped[str] = mapped_column(String(10), default="1m")
    last_checked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    synthetix_account_id: Mapped[Optional[int]] = mapped_column(Integer)
    tvl: Mapped[Optional[float]] = mapped_column(Numeric(20, 8))
    share_price: Mapped[Optional[float]] = mapped_column(Numeric(20, 8))
    depositor_count: Mapped[Optional[int]] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    strategy: Mapped[Optional["Strategy"]] = relationship(back_populates="vaults")
    trades: Mapped[list["Trade"]] = relationship(back_populates="vault")
    snapshots: Mapped[list["PerformanceSnapshot"]] = relationship(
        back_populates="vault"
    )
    referral_attributions: Mapped[list["ReferralAttribution"]] = relationship(
        back_populates="vault"
    )


class Trade(Base):
    __tablename__ = "trades"
    __table_args__ = (
        Index("idx_trades_vault_timestamp", "vault_address", "timestamp"),
        Index("idx_trades_strategy", "strategy_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    vault_address: Mapped[Optional[str]] = mapped_column(
        ForeignKey("vaults.address", ondelete="CASCADE"), index=True
    )
    strategy_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("strategies.id", ondelete="CASCADE"), index=True
    )
    trade_num: Mapped[int] = mapped_column(Integer)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True
    )
    side: Mapped[str] = mapped_column(String(10))
    asset: Mapped[str] = mapped_column(String(50))
    size: Mapped[Optional[float]] = mapped_column(Numeric(20, 8))
    entry_price: Mapped[float] = mapped_column(Numeric(20, 8))
    exit_price: Mapped[Optional[float]] = mapped_column(Numeric(20, 8))
    exit_timestamp: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    pnl: Mapped[Optional[float]] = mapped_column(Numeric(20, 8))
    pnl_pct: Mapped[Optional[float]] = mapped_column(Numeric(8, 4))
    result: Mapped[Optional[str]] = mapped_column(String(10))
    tx_hash: Mapped[Optional[str]] = mapped_column(String(66))
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    vault: Mapped["Vault"] = relationship(back_populates="trades")
    referral_attributions: Mapped[list["ReferralAttribution"]] = relationship(
        back_populates="trade"
    )


class SignalLog(Base):
    __tablename__ = "signal_logs"
    __table_args__ = (
        Index("idx_signal_logs_vault_timestamp", "vault_address", "timestamp"),
        Index("idx_signal_logs_strategy", "strategy_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    vault_address: Mapped[Optional[str]] = mapped_column(
        ForeignKey("vaults.address", ondelete="CASCADE"), index=True
    )
    strategy_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("strategies.id", ondelete="CASCADE"), index=True
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True
    )
    asset: Mapped[str] = mapped_column(String(50))
    timeframe: Mapped[str] = mapped_column(String(20))
    direction: Mapped[int] = mapped_column(Integer)
    confidence: Mapped[Optional[float]] = mapped_column(Numeric(6, 4))
    size_pct: Mapped[Optional[float]] = mapped_column(Numeric(6, 4))
    reason: Mapped[Optional[str]] = mapped_column(Text)
    current_price: Mapped[Optional[float]] = mapped_column(Numeric(20, 8))
    stop_loss: Mapped[Optional[float]] = mapped_column(Numeric(20, 8))
    take_profit: Mapped[Optional[float]] = mapped_column(Numeric(20, 8))


class PerformanceSnapshot(Base):
    __tablename__ = "performance_snapshots"
    __table_args__ = (
        Index("idx_snapshots_vault_timestamp", "vault_address", "timestamp"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    vault_address: Mapped[str] = mapped_column(
        ForeignKey("vaults.address", ondelete="CASCADE"), index=True
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True
    )
    tvl: Mapped[float] = mapped_column(Numeric(20, 8))
    share_price: Mapped[float] = mapped_column(Numeric(20, 8))
    depositor_count: Mapped[Optional[int]] = mapped_column(Integer)
    daily_return: Mapped[Optional[float]] = mapped_column(Numeric(8, 4))
    positions_json: Mapped[Optional[list]] = mapped_column(JSON_TYPE)
    unrealized_pnl: Mapped[Optional[float]] = mapped_column(Numeric(20, 8))

    vault: Mapped["Vault"] = relationship(back_populates="snapshots")


class HistoricalCandle(Base):
    __tablename__ = "historical_candles"
    __table_args__ = (
        Index("idx_candles_asset_tf_ts", "asset", "timeframe", "timestamp"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    asset: Mapped[str] = mapped_column(String(20), index=True)
    timeframe: Mapped[str] = mapped_column(String(10), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    open: Mapped[float] = mapped_column(Numeric(20, 8))
    high: Mapped[float] = mapped_column(Numeric(20, 8))
    low: Mapped[float] = mapped_column(Numeric(20, 8))
    close: Mapped[float] = mapped_column(Numeric(20, 8))
    volume: Mapped[Optional[float]] = mapped_column(Numeric(20, 8))


class ReferralAttribution(Base):
    __tablename__ = "referral_attributions"
    __table_args__ = (
        Index("idx_referral_attr_referrer", "referrer_address"),
        Index("idx_referral_attr_vault", "vault_address"),
        Index("idx_referral_attr_trader", "trader_address"),
        Index("idx_referral_attr_code", "referral_code"),
        UniqueConstraint("chain_id", "tx_hash", "log_index", name="uq_referral_attr_chain_tx_log"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    chain_id: Mapped[int] = mapped_column(Integer, default=42161, index=True)
    event_type: Mapped[str] = mapped_column(String(64))
    vault_address: Mapped[Optional[str]] = mapped_column(
        ForeignKey("vaults.address", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    trader_address: Mapped[Optional[str]] = mapped_column(String(42), nullable=True)
    referral_code: Mapped[Optional[str]] = mapped_column(String(66), nullable=True)
    referrer_address: Mapped[Optional[str]] = mapped_column(String(42), nullable=True)
    deposit_amount_wei: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    shares_wei: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    tx_hash: Mapped[str] = mapped_column(String(66), index=True)
    log_index: Mapped[int] = mapped_column(Integer)
    block_number: Mapped[int] = mapped_column(BigInteger, index=True)
    block_timestamp: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    trade_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("trades.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    metadata_json: Mapped[Optional[dict]] = mapped_column("metadata", JSON_TYPE)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
    )

    vault: Mapped[Optional["Vault"]] = relationship(back_populates="referral_attributions")
    trade: Mapped[Optional["Trade"]] = relationship(back_populates="referral_attributions")


class ReferralRewardClaim(Base):
    __tablename__ = "referral_reward_claims"
    __table_args__ = (
        Index("idx_referral_claim_referrer", "referrer_address"),
        Index("idx_referral_claim_block", "block_number"),
        UniqueConstraint("chain_id", "tx_hash", "log_index", name="uq_referral_claim_chain_tx_log"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    chain_id: Mapped[int] = mapped_column(Integer, default=42161, index=True)
    referrer_address: Mapped[str] = mapped_column(String(42), index=True)
    amount_wei: Mapped[int] = mapped_column(BigInteger)
    tx_hash: Mapped[str] = mapped_column(String(66), index=True)
    log_index: Mapped[int] = mapped_column(Integer)
    block_number: Mapped[int] = mapped_column(BigInteger, index=True)
    block_timestamp: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_json: Mapped[Optional[dict]] = mapped_column("metadata", JSON_TYPE)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
    )


class ReferralIndexerState(Base):
    __tablename__ = "referral_indexer_state"
    __table_args__ = (
        UniqueConstraint("indexer_key", name="uq_referral_indexer_state_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    indexer_key: Mapped[str] = mapped_column(String(128), index=True)
    chain_id: Mapped[int] = mapped_column(Integer, default=42161)
    last_processed_block: Mapped[int] = mapped_column(BigInteger, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )


class ReferralAbuseReview(Base):
    __tablename__ = "referral_abuse_reviews"
    __table_args__ = (
        Index("idx_referral_abuse_reviews_status", "status"),
        Index("idx_referral_abuse_reviews_referrer", "referrer_address"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    referrer_address: Mapped[Optional[str]] = mapped_column(String(42), nullable=True)
    issue_type: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="open")
    reason: Mapped[str] = mapped_column(Text)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    details: Mapped[Optional[dict]] = mapped_column(JSON_TYPE)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
    )
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
