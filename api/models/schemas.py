from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class StrategyDiscoverySchema(BaseModel):
    """Strategy discovery response schema - matches frontend TypeScript type."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: str
    name: str
    strategyType: str = Field(validation_alias=AliasChoices("strategyType", "strategy_type"))
    asset: str
    timeframe: str
    leverageRange: Optional[str] = Field(
        default=None, validation_alias=AliasChoices("leverageRange", "leverage_range")
    )
    winRate: float = Field(
        validation_alias=AliasChoices("winRate", "win_rate"), ge=0, le=1
    )
    sharpe: float
    sortino: Optional[float] = None
    maxDrawdown: float = Field(
        validation_alias=AliasChoices("maxDrawdown", "max_drawdown"), ge=0, le=1
    )
    totalReturn: Optional[float] = Field(
        default=None, validation_alias=AliasChoices("totalReturn", "total_return")
    )
    discoveredAt: datetime = Field(
        validation_alias=AliasChoices("discoveredAt", "discovered_at")
    )
    featured: Optional[bool] = False
    passedCuration: Optional[bool] = Field(
        default=False, validation_alias=AliasChoices("passedCuration", "passed_curation")
    )
    status: str
    vaultAddress: Optional[str] = Field(
        default=None, validation_alias=AliasChoices("vaultAddress", "vault_address")
    )


class StrategyDiscoveryResponse(BaseModel):
    """Paginated response for strategy discoveries."""

    strategies: List[StrategyDiscoverySchema]
    total: int
    page: int
    limit: int


class EquityCurvePoint(BaseModel):
    """Single point in equity curve."""

    date: str
    value: float


class InvestorReportSchema(BaseModel):
    """Investor report schema served to frontend."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    winRate: Optional[float] = Field(
        default=None, validation_alias=AliasChoices("winRate", "win_rate"), ge=0, le=1
    )
    totalReturn: Optional[float] = Field(
        default=None, validation_alias=AliasChoices("totalReturn", "total_return")
    )
    sharpe: Optional[float] = None
    sortino: Optional[float] = None
    maxDrawdown: Optional[float] = Field(
        default=None, validation_alias=AliasChoices("maxDrawdown", "max_drawdown"), ge=0, le=1
    )
    tradeCount: Optional[int] = Field(
        default=None, validation_alias=AliasChoices("tradeCount", "trade_count"), ge=0
    )
    profitFactor: Optional[float] = Field(
        default=None, validation_alias=AliasChoices("profitFactor", "profit_factor")
    )
    avgTradeDuration: Optional[str] = Field(
        default=None, validation_alias=AliasChoices("avgTradeDuration", "avg_trade_duration")
    )
    leverage: Optional[float] = None
    strategyType: Optional[str] = Field(
        default=None, validation_alias=AliasChoices("strategyType", "strategy_type")
    )
    timeframe: Optional[str] = None
    asset: Optional[str] = None
    description: Optional[str] = None
    reportUrl: Optional[str] = Field(
        default=None, validation_alias=AliasChoices("reportUrl", "report_url")
    )
    equityCurve: Optional[List[EquityCurvePoint]] = Field(
        default=None, validation_alias=AliasChoices("equityCurve", "equity_curve")
    )


class HistoryPointSchema(BaseModel):
    """Single data point in performance history."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    timestamp: int
    sharePrice: float = Field(
        validation_alias=AliasChoices("sharePrice", "share_price")
    )
    tvl: float
    depositorCount: Optional[int] = Field(
        default=None, validation_alias=AliasChoices("depositorCount", "depositor_count")
    )
    dailyReturn: Optional[float] = Field(
        default=None, validation_alias=AliasChoices("dailyReturn", "daily_return")
    )


class HistoryMetaSchema(BaseModel):
    """Metadata about the history response."""

    model_config = ConfigDict(populate_by_name=True)

    vaultAddress: str = Field(validation_alias=AliasChoices("vaultAddress", "vault_address"))
    startDate: Optional[str] = Field(
        default=None, validation_alias=AliasChoices("startDate", "start_date")
    )
    endDate: Optional[str] = Field(
        default=None, validation_alias=AliasChoices("endDate", "end_date")
    )
    dataPoints: int = Field(validation_alias=AliasChoices("dataPoints", "data_points"))
    interval: str


class HistoryResponseSchema(BaseModel):
    """Complete history response with data and metadata."""

    data: List[HistoryPointSchema]
    meta: HistoryMetaSchema


class TradeSchema(BaseModel):
    """Single live trade row from execution history."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: int
    tradeNum: int = Field(validation_alias=AliasChoices("tradeNum", "trade_num"))
    timestamp: datetime
    side: str
    asset: str
    size: Optional[float] = None
    entryPrice: float = Field(validation_alias=AliasChoices("entryPrice", "entry_price"))
    exitPrice: Optional[float] = Field(
        default=None, validation_alias=AliasChoices("exitPrice", "exit_price")
    )
    exitTimestamp: Optional[datetime] = Field(
        default=None, validation_alias=AliasChoices("exitTimestamp", "exit_timestamp")
    )
    pnl: Optional[float] = None
    pnlPct: Optional[float] = Field(default=None, validation_alias=AliasChoices("pnlPct", "pnl_pct"))
    result: Optional[str] = None
    txHash: Optional[str] = Field(default=None, validation_alias=AliasChoices("txHash", "tx_hash"))


class TradeHistoryMetaSchema(BaseModel):
    """Pagination metadata for trade history responses."""

    model_config = ConfigDict(populate_by_name=True)

    vaultAddress: str = Field(validation_alias=AliasChoices("vaultAddress", "vault_address"))
    page: int
    limit: int
    total: int
    hasMore: bool = Field(validation_alias=AliasChoices("hasMore", "has_more"))


class TradeHistoryResponseSchema(BaseModel):
    """Complete trade history response payload."""

    trades: List[TradeSchema]
    meta: TradeHistoryMetaSchema


class SignalSchema(BaseModel):
    """Single strategy signal row."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: int
    timestamp: datetime
    asset: str
    timeframe: str
    direction: int
    directionLabel: str = Field(
        validation_alias=AliasChoices("directionLabel", "direction_label")
    )
    confidence: Optional[float] = None
    sizePct: Optional[float] = Field(default=None, validation_alias=AliasChoices("sizePct", "size_pct"))
    reason: Optional[str] = None
    currentPrice: Optional[float] = Field(
        default=None, validation_alias=AliasChoices("currentPrice", "current_price")
    )
    stopLoss: Optional[float] = Field(default=None, validation_alias=AliasChoices("stopLoss", "stop_loss"))
    takeProfit: Optional[float] = Field(
        default=None, validation_alias=AliasChoices("takeProfit", "take_profit")
    )


class SignalLogMetaSchema(BaseModel):
    """Pagination metadata for signal log responses."""

    model_config = ConfigDict(populate_by_name=True)

    vaultAddress: str = Field(validation_alias=AliasChoices("vaultAddress", "vault_address"))
    page: int
    limit: int
    total: int
    hasMore: bool = Field(validation_alias=AliasChoices("hasMore", "has_more"))


class SignalLogResponseSchema(BaseModel):
    """Complete signal log response payload."""

    data: List[SignalSchema]
    meta: SignalLogMetaSchema


class LivePerformanceSchema(BaseModel):
    """Aggregated live performance metrics for a vault."""

    model_config = ConfigDict(populate_by_name=True)

    vaultAddress: str = Field(validation_alias=AliasChoices("vaultAddress", "vault_address"))
    totalTrades: int = Field(validation_alias=AliasChoices("totalTrades", "total_trades"))
    closedTrades: int = Field(validation_alias=AliasChoices("closedTrades", "closed_trades"))
    openTrades: int = Field(validation_alias=AliasChoices("openTrades", "open_trades"))
    winRate: Optional[float] = Field(default=None, validation_alias=AliasChoices("winRate", "win_rate"))
    profitFactor: Optional[float] = Field(
        default=None, validation_alias=AliasChoices("profitFactor", "profit_factor")
    )
    avgTradeDurationHours: Optional[float] = Field(
        default=None,
        validation_alias=AliasChoices("avgTradeDurationHours", "avg_trade_duration_hours"),
    )
    realizedPnlUsd: Optional[float] = Field(
        default=None, validation_alias=AliasChoices("realizedPnlUsd", "realized_pnl_usd")
    )
    unrealizedPnlUsd: Optional[float] = Field(
        default=None, validation_alias=AliasChoices("unrealizedPnlUsd", "unrealized_pnl_usd")
    )
    totalPnlUsd: Optional[float] = Field(
        default=None, validation_alias=AliasChoices("totalPnlUsd", "total_pnl_usd")
    )
    sharpe: Optional[float] = None
    snapshotCount: int = Field(validation_alias=AliasChoices("snapshotCount", "snapshot_count"))
    firstTradeAt: Optional[datetime] = Field(
        default=None, validation_alias=AliasChoices("firstTradeAt", "first_trade_at")
    )
    lastTradeAt: Optional[datetime] = Field(
        default=None, validation_alias=AliasChoices("lastTradeAt", "last_trade_at")
    )
    dataQuality: dict = Field(default_factory=dict, validation_alias=AliasChoices("dataQuality", "data_quality"))


class PositionSchema(BaseModel):
    """Single open position from latest snapshot."""

    model_config = ConfigDict(populate_by_name=True)

    marketId: str = Field(validation_alias=AliasChoices("marketId", "market_id"))
    asset: str
    direction: str
    size: float
    sizeUsd: Optional[float] = Field(default=None, validation_alias=AliasChoices("sizeUsd", "size_usd"))
    entryPrice: float = Field(validation_alias=AliasChoices("entryPrice", "entry_price"))
    currentPrice: float = Field(validation_alias=AliasChoices("currentPrice", "current_price"))
    unrealizedPnl: float = Field(validation_alias=AliasChoices("unrealizedPnl", "unrealized_pnl"))
    unrealizedPnlPct: Optional[float] = Field(
        default=None, validation_alias=AliasChoices("unrealizedPnlPct", "unrealized_pnl_pct")
    )
    leverage: float
    liquidationPrice: Optional[float] = Field(
        default=None, validation_alias=AliasChoices("liquidationPrice", "liquidation_price")
    )


class PositionsResponseSchema(BaseModel):
    """Open positions payload for a vault."""

    model_config = ConfigDict(populate_by_name=True)

    vaultAddress: str = Field(validation_alias=AliasChoices("vaultAddress", "vault_address"))
    positions: List[PositionSchema]
    totalUnrealizedPnl: float = Field(
        validation_alias=AliasChoices("totalUnrealizedPnl", "total_unrealized_pnl")
    )
    snapshotAt: Optional[datetime] = Field(
        default=None, validation_alias=AliasChoices("snapshotAt", "snapshot_at")
    )
    isFlat: bool = Field(validation_alias=AliasChoices("isFlat", "is_flat"))


class VaultHealthSchema(BaseModel):
    """Operational health data for a vault."""

    model_config = ConfigDict(populate_by_name=True)

    vaultAddress: str = Field(validation_alias=AliasChoices("vaultAddress", "vault_address"))
    circuitBreakerTripped: bool = Field(
        validation_alias=AliasChoices("circuitBreakerTripped", "circuit_breaker_tripped")
    )
    consecutiveFailures: int = Field(
        validation_alias=AliasChoices("consecutiveFailures", "consecutive_failures")
    )
    trippedAt: Optional[datetime] = Field(default=None, validation_alias=AliasChoices("trippedAt", "tripped_at"))
    cooldownRemainingSeconds: Optional[int] = Field(
        default=None,
        validation_alias=AliasChoices("cooldownRemainingSeconds", "cooldown_remaining_seconds"),
    )
    circuitBreakerThreshold: int = Field(
        validation_alias=AliasChoices("circuitBreakerThreshold", "circuit_breaker_threshold")
    )
    circuitBreakerCooldown: int = Field(
        validation_alias=AliasChoices("circuitBreakerCooldown", "circuit_breaker_cooldown")
    )
    lastSuccessfulTradeAt: Optional[datetime] = Field(
        default=None, validation_alias=AliasChoices("lastSuccessfulTradeAt", "last_successful_trade_at")
    )
    lastFailedTradeAt: Optional[datetime] = Field(
        default=None, validation_alias=AliasChoices("lastFailedTradeAt", "last_failed_trade_at")
    )
    lastErrorMessage: Optional[str] = Field(
        default=None, validation_alias=AliasChoices("lastErrorMessage", "last_error_message")
    )
    lastCheckedAt: Optional[datetime] = Field(
        default=None, validation_alias=AliasChoices("lastCheckedAt", "last_checked_at")
    )
    status: str


class FundVaultRequest(BaseModel):
    amount: Optional[float] = Field(
        default=None,
        description="Amount of WETH to transfer (in WETH units)",
    )
    amountWei: Optional[int] = Field(
        default=None,
        validation_alias=AliasChoices("amountWei", "amount_wei"),
        description="Amount of WETH to transfer (in wei)",
    )


class FundVaultResponse(BaseModel):
    success: bool
    txHash: Optional[str] = Field(default=None, validation_alias=AliasChoices("txHash", "tx_hash"))
    error: Optional[str] = None
    amountWei: int = Field(validation_alias=AliasChoices("amountWei", "amount_wei"))


class ManualTradeRequest(BaseModel):
    asset: str
    direction: str
    sizeUsd: float = Field(validation_alias=AliasChoices("sizeUsd", "size_usd"), gt=0)
    dryRun: bool = Field(default=False, validation_alias=AliasChoices("dryRun", "dry_run"))
    fundWeth: Optional[float] = Field(
        default=None,
        validation_alias=AliasChoices("fundWeth", "fund_weth"),
        description="Optional WETH amount to fund the vault before trading",
    )
    fundWethWei: Optional[int] = Field(
        default=None,
        validation_alias=AliasChoices("fundWethWei", "fund_weth_wei"),
        description="Optional WETH amount in wei to fund the vault before trading",
    )


class ManualTradeResponse(BaseModel):
    success: bool
    txHash: Optional[str] = Field(default=None, validation_alias=AliasChoices("txHash", "tx_hash"))
    error: Optional[str] = None
    gasUsed: int = Field(default=0, validation_alias=AliasChoices("gasUsed", "gas_used"))
    executionFeeWei: Optional[int] = Field(
        default=None, validation_alias=AliasChoices("executionFeeWei", "execution_fee_wei")
    )
    gasLimit: Optional[int] = Field(default=None, validation_alias=AliasChoices("gasLimit", "gas_limit"))


class ReferralAttributionSchema(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    eventType: str = Field(validation_alias=AliasChoices("eventType", "event_type"))
    vaultAddress: Optional[str] = Field(
        default=None, validation_alias=AliasChoices("vaultAddress", "vault_address")
    )
    traderAddress: Optional[str] = Field(
        default=None, validation_alias=AliasChoices("traderAddress", "trader_address")
    )
    referrerAddress: Optional[str] = Field(
        default=None, validation_alias=AliasChoices("referrerAddress", "referrer_address")
    )
    referralCode: Optional[str] = Field(
        default=None, validation_alias=AliasChoices("referralCode", "referral_code")
    )
    depositAmountWei: Optional[str] = Field(
        default=None, validation_alias=AliasChoices("depositAmountWei", "deposit_amount_wei")
    )
    sharesWei: Optional[str] = Field(
        default=None, validation_alias=AliasChoices("sharesWei", "shares_wei")
    )
    txHash: str = Field(validation_alias=AliasChoices("txHash", "tx_hash"))
    blockNumber: int = Field(validation_alias=AliasChoices("blockNumber", "block_number"))
    blockTimestamp: Optional[datetime] = Field(
        default=None, validation_alias=AliasChoices("blockTimestamp", "block_timestamp")
    )


class ReferralClaimSchema(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    referrerAddress: str = Field(validation_alias=AliasChoices("referrerAddress", "referrer_address"))
    amountWei: str = Field(validation_alias=AliasChoices("amountWei", "amount_wei"))
    txHash: str = Field(validation_alias=AliasChoices("txHash", "tx_hash"))
    blockNumber: int = Field(validation_alias=AliasChoices("blockNumber", "block_number"))
    blockTimestamp: Optional[datetime] = Field(
        default=None, validation_alias=AliasChoices("blockTimestamp", "block_timestamp")
    )


class ReferralAddressSummarySchema(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    address: str
    referralCodes: List[str] = Field(
        default_factory=list, validation_alias=AliasChoices("referralCodes", "referral_codes")
    )
    referredUsers: int = Field(validation_alias=AliasChoices("referredUsers", "referred_users"))
    referredDeposits: int = Field(validation_alias=AliasChoices("referredDeposits", "referred_deposits"))
    referredVolumeWei: str = Field(
        validation_alias=AliasChoices("referredVolumeWei", "referred_volume_wei")
    )
    totalClaimedWei: str = Field(validation_alias=AliasChoices("totalClaimedWei", "total_claimed_wei"))
    latestAttributions: List[ReferralAttributionSchema] = Field(
        default_factory=list, validation_alias=AliasChoices("latestAttributions", "latest_attributions")
    )
    latestClaims: List[ReferralClaimSchema] = Field(
        default_factory=list, validation_alias=AliasChoices("latestClaims", "latest_claims")
    )


class ReferralVaultSummarySchema(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    vaultAddress: str = Field(validation_alias=AliasChoices("vaultAddress", "vault_address"))
    referredDeposits: int = Field(validation_alias=AliasChoices("referredDeposits", "referred_deposits"))
    uniqueReferrers: int = Field(validation_alias=AliasChoices("uniqueReferrers", "unique_referrers"))
    referredVolumeWei: str = Field(
        validation_alias=AliasChoices("referredVolumeWei", "referred_volume_wei")
    )
    attributions: List[ReferralAttributionSchema] = Field(default_factory=list)


class ReferralAllocationEntrySchema(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    referrerAddress: str = Field(validation_alias=AliasChoices("referrerAddress", "referrer_address"))
    referredVolumeWei: str = Field(
        validation_alias=AliasChoices("referredVolumeWei", "referred_volume_wei")
    )
    referredDeposits: int = Field(validation_alias=AliasChoices("referredDeposits", "referred_deposits"))
    allocationBps: int = Field(validation_alias=AliasChoices("allocationBps", "allocation_bps"))
    allocationShare: float = Field(
        validation_alias=AliasChoices("allocationShare", "allocation_share")
    )


class ReferralAllocationResponseSchema(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    vaultAddress: str = Field(validation_alias=AliasChoices("vaultAddress", "vault_address"))
    totalVolumeWei: str = Field(validation_alias=AliasChoices("totalVolumeWei", "total_volume_wei"))
    allocations: List[ReferralAllocationEntrySchema] = Field(default_factory=list)


class ReferralStatsSchema(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    referredDeposits: int = Field(validation_alias=AliasChoices("referredDeposits", "referred_deposits"))
    uniqueReferrers: int = Field(validation_alias=AliasChoices("uniqueReferrers", "unique_referrers"))
    uniqueReferredUsers: int = Field(
        validation_alias=AliasChoices("uniqueReferredUsers", "unique_referred_users")
    )
    referredVolumeWei: str = Field(
        validation_alias=AliasChoices("referredVolumeWei", "referred_volume_wei")
    )
    claimedRewardsWei: str = Field(
        validation_alias=AliasChoices("claimedRewardsWei", "claimed_rewards_wei")
    )


class SuspiciousReferralPatternSchema(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    issueType: str = Field(validation_alias=AliasChoices("issueType", "issue_type"))
    severity: str
    description: str
    metadata: dict = Field(default_factory=dict)


class ReferralAbuseReviewRequest(BaseModel):
    referrerAddress: Optional[str] = Field(
        default=None, validation_alias=AliasChoices("referrerAddress", "referrer_address")
    )
    issueType: str = Field(validation_alias=AliasChoices("issueType", "issue_type"))
    reason: str
    notes: Optional[str] = None
    details: Optional[dict] = None


class ReferralAbuseReviewResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: int
    status: str
    issueType: str = Field(validation_alias=AliasChoices("issueType", "issue_type"))
    referrerAddress: Optional[str] = Field(
        default=None, validation_alias=AliasChoices("referrerAddress", "referrer_address")
    )
    reason: str
    notes: Optional[str] = None
