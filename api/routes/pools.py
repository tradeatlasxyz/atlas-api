from __future__ import annotations

from datetime import date
import re
from typing import Optional

from eth_account import Account
from eth_account.messages import encode_defunct
from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession
from web3 import Web3

from api.config import settings
from api.models.schemas import (
    HistoryMetaSchema,
    HistoryPointSchema,
    HistoryResponseSchema,
    InvestorReportSchema,
    LivePerformanceSchema,
    PositionsResponseSchema,
    SignalLogMetaSchema,
    SignalLogResponseSchema,
    SignalSchema,
    TradeHistoryMetaSchema,
    TradeHistoryResponseSchema,
    TradeSchema,
    VaultHealthSchema,
)
from api.onchain.vault_reader import VaultReader
from api.services.database import get_db
from api.services.pools import (
    get_vault_history,
    get_vault_health,
    get_vault_live_performance,
    get_vault_positions,
    get_vault_signals,
    get_vault_trades,
)
from api.services.strategy import get_investor_report_by_vault

router = APIRouter()

ADDRESS_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")
SIGNAL_DIRECTION_LABELS = {
    -1: "SHORT",
    0: "NEUTRAL",
    1: "LONG",
}


def _signal_field(signal, field: str):
    if isinstance(signal, dict):
        return signal.get(field)
    return getattr(signal, field)


def _assert_manager_signature(vault_address: str, signer: str, signature: str) -> None:
    if not Web3.is_address(signer):
        raise HTTPException(status_code=422, detail="Invalid signer address")

    message = encode_defunct(text=f"atlas-health:{vault_address}")
    try:
        recovered = Account.recover_message(message, signature=signature)
    except Exception as exc:  # pragma: no cover - defensive parse guard
        raise HTTPException(status_code=401, detail="Invalid signature") from exc

    if recovered.lower() != signer.lower():
        raise HTTPException(status_code=401, detail="Signature does not match signer")

    if not settings.arbitrum_rpc_url:
        raise HTTPException(status_code=503, detail="ARBITRUM_RPC_URL not configured")

    reader = VaultReader(web3=Web3(Web3.HTTPProvider(settings.arbitrum_rpc_url)))
    try:
        manager = reader.get_manager_address(vault_address)
        trader = reader.get_trader_address(vault_address)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Unable to verify vault roles: {exc}") from exc

    signer_lower = signer.lower()
    if signer_lower not in {manager.lower(), trader.lower()}:
        raise HTTPException(
            status_code=403,
            detail="Signer is not authorized as manager/trader for this vault",
        )


def normalize_vault_address(address: str) -> str:
    if not ADDRESS_RE.match(address):
        raise HTTPException(status_code=422, detail="Invalid vault address")
    return address.lower()


@router.get(
    "/pool/{address}/investor-report",
    response_model=InvestorReportSchema,
    response_model_by_alias=True,
    summary="Get Investor Report",
    description="Fetch backtest metrics for a vault's strategy.",
)
async def get_investor_report(
    address: str = Path(..., description="Vault address (0x... format)"),
    db: AsyncSession = Depends(get_db),
):
    address = normalize_vault_address(address)
    report = await get_investor_report_by_vault(db, address)

    if report is None:
        raise HTTPException(status_code=404, detail="Investor report not found")

    return InvestorReportSchema.model_validate(report)


@router.get(
    "/pool/{address}/history",
    response_model=HistoryResponseSchema,
    response_model_by_alias=True,
    summary="Get Historical Performance",
    description="Fetch historical TVL and share price data for charts.",
)
async def get_pool_history(
    address: str = Path(..., description="Vault address (0x... format)"),
    startDate: Optional[date] = Query(None, alias="startDate", description="Start date (YYYY-MM-DD)"),
    endDate: Optional[date] = Query(None, alias="endDate", description="End date (YYYY-MM-DD)"),
    interval: str = Query("daily", description="Data interval: hourly, daily, weekly"),
    limit: int = Query(365, ge=1, le=1000, description="Max data points"),
    db: AsyncSession = Depends(get_db),
):
    address = normalize_vault_address(address)

    allowed_intervals = {"hourly", "daily", "weekly"}
    if interval not in allowed_intervals:
        raise HTTPException(
            status_code=422, detail="Invalid interval. Must be: hourly, daily, weekly"
        )
    if startDate and endDate and startDate > endDate:
        raise HTTPException(status_code=422, detail="startDate must be before endDate")

    data, meta = await get_vault_history(
        db,
        vault_address=address,
        start_date=startDate,
        end_date=endDate,
        interval=interval,
        limit=limit,
    )

    if meta is None:
        raise HTTPException(status_code=404, detail="Vault not found")

    payload = [HistoryPointSchema.model_validate(item) for item in data]
    return HistoryResponseSchema(meta=HistoryMetaSchema.model_validate(meta), data=payload)


@router.get(
    "/pool/{address}/trades",
    response_model=TradeHistoryResponseSchema,
    response_model_by_alias=True,
    summary="Get Trade History",
    description="Fetch paginated live trade history for a vault.",
)
async def get_pool_trades(
    address: str = Path(..., description="Vault address (0x... format)"),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(50, ge=1, le=200, description="Page size"),
    includeErrors: bool = Query(
        False,
        alias="includeErrors",
        description="Include failed execution attempts with error messages",
    ),
    db: AsyncSession = Depends(get_db),
):
    address = normalize_vault_address(address)
    trades, meta = await get_vault_trades(
        db,
        vault_address=address,
        page=page,
        limit=limit,
        include_errors=includeErrors,
    )

    if meta is None:
        raise HTTPException(status_code=404, detail="Vault not found")

    payload = [TradeSchema.model_validate(item) for item in trades]
    return TradeHistoryResponseSchema(
        trades=payload,
        meta=TradeHistoryMetaSchema.model_validate(meta),
    )


@router.get(
    "/pool/{address}/signals",
    response_model=SignalLogResponseSchema,
    response_model_by_alias=True,
    summary="Get Signal Log",
    description="Fetch paginated strategy signal history for a vault.",
)
async def get_pool_signals(
    address: str = Path(..., description="Vault address (0x... format)"),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(50, ge=1, le=200, description="Page size"),
    db: AsyncSession = Depends(get_db),
):
    address = normalize_vault_address(address)
    signals, meta = await get_vault_signals(
        db,
        vault_address=address,
        page=page,
        limit=limit,
    )

    if meta is None:
        raise HTTPException(status_code=404, detail="Vault not found")

    payload = [
        SignalSchema.model_validate(
            {
                "id": _signal_field(signal, "id"),
                "timestamp": _signal_field(signal, "timestamp"),
                "asset": _signal_field(signal, "asset"),
                "timeframe": _signal_field(signal, "timeframe"),
                "direction": _signal_field(signal, "direction"),
                "direction_label": SIGNAL_DIRECTION_LABELS.get(
                    _signal_field(signal, "direction"), "NEUTRAL"
                ),
                "confidence": _signal_field(signal, "confidence"),
                "size_pct": _signal_field(signal, "size_pct"),
                "reason": _signal_field(signal, "reason"),
                "current_price": _signal_field(signal, "current_price"),
                "stop_loss": _signal_field(signal, "stop_loss"),
                "take_profit": _signal_field(signal, "take_profit"),
            }
        )
        for signal in signals
    ]
    return SignalLogResponseSchema(
        data=payload,
        meta=SignalLogMetaSchema.model_validate(meta),
    )


@router.get(
    "/pool/{address}/live-performance",
    response_model=LivePerformanceSchema,
    response_model_by_alias=True,
    summary="Get Live Performance Summary",
    description="Aggregated live metrics from executed trades and performance snapshots.",
)
async def get_pool_live_performance(
    address: str = Path(..., description="Vault address (0x... format)"),
    db: AsyncSession = Depends(get_db),
):
    address = normalize_vault_address(address)
    result = await get_vault_live_performance(db, vault_address=address)
    if result is None:
        raise HTTPException(status_code=404, detail="Vault not found")
    return LivePerformanceSchema.model_validate(result)


@router.get(
    "/pool/{address}/positions",
    response_model=PositionsResponseSchema,
    response_model_by_alias=True,
    summary="Get Current Open Positions",
    description="Returns open positions from the most recent performance snapshot.",
)
async def get_pool_positions(
    address: str = Path(..., description="Vault address (0x... format)"),
    db: AsyncSession = Depends(get_db),
):
    address = normalize_vault_address(address)
    result = await get_vault_positions(db, vault_address=address)
    if result is None:
        raise HTTPException(status_code=404, detail="Vault not found")
    return PositionsResponseSchema.model_validate(result)


@router.get(
    "/pool/{address}/health",
    response_model=VaultHealthSchema,
    response_model_by_alias=True,
    summary="Get Vault Health Status",
    description="Returns circuit breaker and latest execution health data for a vault.",
)
async def get_pool_health(
    address: str = Path(..., description="Vault address (0x... format)"),
    signer: str = Query(..., description="Manager or trader wallet address"),
    signature: str = Query(..., description="Signature of atlas-health:{vaultAddress}"),
    db: AsyncSession = Depends(get_db),
):
    address = normalize_vault_address(address)
    _assert_manager_signature(address, signer, signature)
    result = await get_vault_health(db, vault_address=address)
    if result is None:
        raise HTTPException(status_code=404, detail="Vault not found")
    return VaultHealthSchema.model_validate(result)
