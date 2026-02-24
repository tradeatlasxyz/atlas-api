from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

SLUG_REGEX = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
BANNED_DESCRIPTION_TOKENS = [
    "rsi",
    "macd",
    "sma",
    "ema",
    "atr",
    "bollinger",
    "stochastic",
    "vwap",
]


class LLMContextMeta(BaseModel):
    version: str = "1.0"
    purpose: str = "strategy_import"
    generated_at: Optional[datetime] = None


class StrategyImport(BaseModel):
    name: str = Field(..., max_length=255)
    slug: str = Field(..., max_length=255)
    strategy_type: str = Field(..., max_length=100)
    asset: str = Field(..., max_length=50)
    timeframe: str = Field(..., max_length=20)
    leverage_range: Optional[str] = Field(default=None, max_length=50)
    status: Literal["preview", "deployable", "deployed"] = "deployable"
    featured: bool = False
    passed_curation: bool = False
    discovered_at: Optional[datetime] = None
    description: Optional[str] = Field(default=None, max_length=2000)
    parameters: Optional[Dict[str, Any]] = None

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, value: str) -> str:
        if not SLUG_REGEX.match(value):
            raise ValueError("slug must be lowercase and URL-safe (a-z, 0-9, '-')")
        return value

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        lowered = value.lower()
        for token in BANNED_DESCRIPTION_TOKENS:
            if re.search(rf"\b{re.escape(token)}\b", lowered):
                raise ValueError("description must be investor-friendly (no indicator names)")
        return value


class InvestorReportImport(BaseModel):
    win_rate: Optional[float] = Field(None, ge=0, le=1)
    total_return: Optional[float] = None
    sharpe: Optional[float] = None
    sortino: Optional[float] = None
    max_drawdown: Optional[float] = None
    trade_count: Optional[int] = None
    profit_factor: Optional[float] = None
    avg_trade_duration: Optional[str] = None
    leverage: Optional[float] = None


class EquityCurvePoint(BaseModel):
    date: str
    value: float


class TradeImport(BaseModel):
    trade_num: int
    entry_date: datetime
    exit_date: Optional[datetime] = None
    entry_price: float
    exit_price: Optional[float] = None
    side: Literal["long", "short"]
    size: Optional[float] = None
    pnl_pct: Optional[float] = None
    result: Optional[Literal["WIN", "LOSS"]] = None


class VaultImport(BaseModel):
    address: str = Field(..., min_length=42, max_length=42)
    name: str = Field(..., max_length=255)
    chain: str = Field(default="arbitrum", max_length=50)
    status: Optional[str] = Field(default=None, max_length=20)
    check_interval: Optional[str] = Field(default=None, max_length=10)
    synthetix_account_id: Optional[int] = None

    @field_validator("chain")
    @classmethod
    def normalize_chain(cls, value: str) -> str:
        return value.lower()


class StrategyImportPayload(BaseModel):
    """Complete import payload from analytics pipeline."""

    model_config = ConfigDict(populate_by_name=True)

    llm_context: Optional[LLMContextMeta] = Field(default=None, alias="_llm_context")
    strategy: StrategyImport
    investor_report: Optional[InvestorReportImport] = None
    equity_curve: Optional[List[EquityCurvePoint]] = None
    trades: Optional[List[TradeImport]] = None
    vault: Optional[VaultImport] = None
    source_code: Optional[str] = None


IMPORT_SCHEMA_VERSION = "1.0"
