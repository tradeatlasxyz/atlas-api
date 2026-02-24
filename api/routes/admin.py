from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from api.execution.market_data import get_market_data, MarketDataFetcher
from api.execution.position_tracker import run_snapshot_job
from api.execution.scheduler import get_scheduler
from api.execution.trade_executor import TradeExecutor
from api.execution.strategy_loader import STRATEGIES_DIR
from api.models.database import Strategy, Vault
from api.models.schemas import (
    ReferralAbuseReviewRequest,
    ReferralAbuseReviewResponse,
    SuspiciousReferralPatternSchema,
)
from api.services.database import get_db
from api.services.referrals import create_abuse_review, scan_suspicious_patterns
from api.onchain.gmx import get_market_long_token, get_market_address_for_asset
from api.onchain.vault_reader import VaultReader
from api.config import settings
from web3 import Web3

router = APIRouter(prefix="/admin", tags=["Admin"])

# Map strategy timeframes to sensible check intervals
TIMEFRAME_TO_CHECK_INTERVAL = {
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "1h": "1m",   # Check every minute for 1H strategies (catch signals quickly)
    "4h": "5m",   # Check every 5 minutes for 4H strategies
    "1d": "15m",  # Check every 15 minutes for 1D strategies
}


def _check_interval_for_strategy(strategy: Strategy) -> str:
    """Derive a sensible check_interval from the strategy's timeframe."""
    tf = (strategy.timeframe or "1h").lower()
    return TIMEFRAME_TO_CHECK_INTERVAL.get(tf, "1m")


def _validate_strategy_code(strategy: Strategy) -> Optional[str]:
    """Validate that a strategy has a loadable code file. Returns error or None."""
    # Check explicit code_path
    if strategy.code_path:
        if Path(strategy.code_path).exists():
            return None
    # Check auto-detected path in deployed dir
    candidate = STRATEGIES_DIR / f"{strategy.slug}.py"
    if candidate.exists():
        return None
    return f"Strategy '{strategy.slug}' has no deployed code file at {candidate}"


class RegisterVaultRequest(BaseModel):
    """Request to register a vault."""

    address: str = Field(..., description="Vault address (0x...)")
    name: str = Field(..., description="Vault display name")
    strategy_slug: Optional[str] = Field(None, description="Strategy slug to link")
    strategy_id: Optional[int] = Field(None, description="Strategy id to link")
    chain: str = Field(default="arbitrum", description="Chain name")


class LinkVaultRequest(BaseModel):
    """Request to link vault to strategy."""

    strategy_slug: Optional[str] = Field(None, description="Strategy slug to link")
    strategy_id: Optional[int] = Field(None, description="Strategy id to link")


class UpdateVaultRequest(BaseModel):
    """Request to update vault settings."""

    name: Optional[str] = Field(None, description="New vault name")
    status: Optional[str] = Field(None, description="active or paused")
    check_interval: Optional[str] = Field(None, description="1m, 5m, 15m, 1H, 4H")


class VaultLongTokenStatus(BaseModel):
    vault: str
    pool_manager_logic: str
    manager: str
    trader: str
    supported_assets: list[str]
    required_long_tokens: list[str]
    missing_long_tokens: list[str]


class SimulateTradeRequest(BaseModel):
    asset: str = Field(..., description="Asset symbol (e.g. BTC, ETH, SOL)")
    direction: str = Field("long", description="long or short")
    size_usd: float = Field(10.0, description="Position size in USD")
    current_price: Optional[float] = Field(
        None, description="Optional current price override"
    )
    from_address: Optional[str] = Field(
        None, description="Override sender for simulation (e.g. manager address)"
    )


@router.post("/trigger/{vault_address}")
async def trigger_signal(vault_address: str) -> dict:
    scheduler = get_scheduler()
    await scheduler.trigger_vault(vault_address)
    return {"status": "triggered", "vault": vault_address}


@router.get("/vaults/{address}/long-tokens", response_model=VaultLongTokenStatus)
async def get_vault_long_token_status(address: str) -> VaultLongTokenStatus:
    reader = VaultReader()
    try:
        pool_manager_logic = reader.get_pool_manager_logic(address)
        manager = reader.get_manager_address(address)
        trader = reader.get_trader_address(address)
        supported = reader.get_supported_assets(address)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    supported_set = {a.lower() for a, _ in supported}
    required_tokens: list[str] = []
    for market in settings.gmx_market_addresses.values():
        try:
            token = get_market_long_token(reader.web3, market)
            if token:
                required_tokens.append(Web3.to_checksum_address(token))
        except Exception:
            continue
    required_tokens = list(dict.fromkeys(required_tokens))
    missing = [t for t in required_tokens if t.lower() not in supported_set]

    return VaultLongTokenStatus(
        vault=Web3.to_checksum_address(address),
        pool_manager_logic=pool_manager_logic,
        manager=manager,
        trader=trader,
        supported_assets=[a for a, _ in supported],
        required_long_tokens=required_tokens,
        missing_long_tokens=missing,
    )


@router.post("/vaults/{address}/simulate-trade")
async def simulate_trade(address: str, request: SimulateTradeRequest) -> dict:
    executor = TradeExecutor()
    if not executor.trader:
        raise HTTPException(status_code=400, detail="Missing TRADER_PRIVATE_KEY")

    asset = (request.asset or "").strip().upper()
    if not asset:
        raise HTTPException(status_code=400, detail="Asset is required")
    is_long = (request.direction or "long").lower() == "long"
    size_usd = float(request.size_usd or 0)
    if size_usd <= 0:
        raise HTTPException(status_code=400, detail="size_usd must be positive")

    market_address = get_market_address_for_asset(executor.web3, asset)
    long_token = get_market_long_token(executor.web3, market_address)

    reader = VaultReader(executor.web3)
    supported = reader.get_supported_assets(address)
    supported_set = {a.lower() for a, _ in supported}
    has_long_token = bool(long_token and long_token.lower() in supported_set)

    price = request.current_price
    if price is None:
        price = await MarketDataFetcher().get_current_price(asset)
    if not price or price <= 0:
        raise HTTPException(status_code=400, detail="Missing current price for asset")

    payload, _ = executor._prepare_trade_payload(
        vault_address=address,
        market_address=market_address,
        size_usd=size_usd,
        is_long=is_long,
        current_price=price,
    )

    vault = executor.web3.eth.contract(
        address=Web3.to_checksum_address(address),
        abi=executor.pool_logic_abi,
    )
    from_addr = request.from_address or executor.trader.address
    if not Web3.is_address(from_addr):
        raise HTTPException(status_code=400, detail="Invalid from_address")

    estimate_ok = True
    estimate_error = None
    try:
        if payload.value > 0:
            _ = vault.functions.execTransactionWithValue(
                Web3.to_checksum_address(executor.GMX_EXCHANGE_ROUTER),
                payload.calldata,
                payload.value,
            ).estimate_gas({"from": from_addr, "value": payload.value})
        else:
            _ = vault.functions.execTransaction(
                Web3.to_checksum_address(executor.GMX_EXCHANGE_ROUTER),
                payload.calldata,
            ).estimate_gas({"from": from_addr})
    except Exception as exc:
        estimate_ok = False
        estimate_error = str(exc)

    call_ok = True
    call_error = None
    try:
        if payload.value > 0:
            _ = vault.functions.execTransactionWithValue(
                Web3.to_checksum_address(executor.GMX_EXCHANGE_ROUTER),
                payload.calldata,
                payload.value,
            ).call({"from": from_addr, "value": payload.value})
        else:
            _ = vault.functions.execTransaction(
                Web3.to_checksum_address(executor.GMX_EXCHANGE_ROUTER),
                payload.calldata,
            ).call({"from": from_addr})
    except Exception as exc:
        call_ok = False
        call_error = str(exc)

    return {
        "vault": Web3.to_checksum_address(address),
        "asset": asset,
        "direction": "long" if is_long else "short",
        "size_usd": size_usd,
        "current_price": price,
        "market_address": Web3.to_checksum_address(market_address),
        "required_long_token": Web3.to_checksum_address(long_token)
        if long_token
        else None,
        "has_long_token": has_long_token,
        "supported_assets": [a for a, _ in supported],
        "estimate_ok": estimate_ok,
        "estimate_error": estimate_error,
        "call_ok": call_ok,
        "call_error": call_error,
        "from": Web3.to_checksum_address(from_addr),
    }


@router.get("/strategies")
async def list_strategies(db: AsyncSession = Depends(get_db)) -> list[dict]:
    """List all strategies available for linking."""
    result = await db.execute(select(Strategy))
    strategies = result.scalars().all()
    return [
        {
            "id": s.id,
            "name": s.name,
            "slug": s.slug,
            "asset": s.asset,
            "timeframe": s.timeframe,
            "status": s.status,
            "code_path": s.code_path,
            "has_deployed_file": (STRATEGIES_DIR / f"{s.slug}.py").exists(),
        }
        for s in strategies
    ]


async def _resolve_strategy(
    db: AsyncSession,
    strategy_slug: Optional[str],
    strategy_id: Optional[int],
) -> Strategy:
    """Resolve a strategy from slug or id, raising HTTPException on failure."""
    strategy = None
    if strategy_slug:
        result = await db.execute(
            select(Strategy).where(Strategy.slug == strategy_slug)
        )
        strategy = result.scalar_one_or_none()
        if not strategy:
            raise HTTPException(
                status_code=404, detail=f"Strategy not found: {strategy_slug}"
            )
    elif strategy_id is not None:
        result = await db.execute(
            select(Strategy).where(Strategy.id == strategy_id)
        )
        strategy = result.scalar_one_or_none()
        if not strategy:
            raise HTTPException(
                status_code=404, detail=f"Strategy not found: {strategy_id}"
            )
    else:
        raise HTTPException(
            status_code=422, detail="strategy_slug or strategy_id required"
        )

    # Validate that the strategy has deployable code
    code_error = _validate_strategy_code(strategy)
    if code_error:
        raise HTTPException(status_code=422, detail=code_error)

    return strategy


@router.post("/vaults/register")
async def register_vault(
    request: RegisterVaultRequest, db: AsyncSession = Depends(get_db)
) -> dict:
    """Register a vault and optionally link it to a strategy."""
    address = request.address.lower()

    # Check if vault already exists
    existing = await db.execute(select(Vault).where(Vault.address == address))
    vault = existing.scalar_one_or_none()

    strategy = None
    if request.strategy_slug or request.strategy_id is not None:
        strategy = await _resolve_strategy(db, request.strategy_slug, request.strategy_id)

    check_interval = _check_interval_for_strategy(strategy) if strategy else "1m"

    if vault:
        # Update existing vault
        vault.name = request.name
        vault.chain = request.chain
        if strategy:
            vault.strategy_id = strategy.id
            vault.check_interval = check_interval
        await db.commit()
        return {
            "status": "updated",
            "address": address,
            "strategy_id": strategy.id if strategy else vault.strategy_id,
            "check_interval": vault.check_interval,
        }
    else:
        # Create new vault
        vault = Vault(
            address=address,
            name=request.name,
            chain=request.chain,
            strategy_id=strategy.id if strategy else None,
            check_interval=check_interval,
        )
        db.add(vault)
        await db.commit()
        return {
            "status": "created",
            "address": address,
            "strategy_id": strategy.id if strategy else None,
            "check_interval": check_interval,
        }


@router.post("/vaults/{address}/link")
async def link_vault_to_strategy(
    address: str, request: LinkVaultRequest, db: AsyncSession = Depends(get_db)
) -> dict:
    """Link an existing vault to a strategy."""
    address = address.lower()

    # Look up vault
    result = await db.execute(select(Vault).where(Vault.address == address))
    vault = result.scalar_one_or_none()

    if not vault:
        raise HTTPException(status_code=404, detail="Vault not found")

    strategy = await _resolve_strategy(db, request.strategy_slug, request.strategy_id)

    vault.strategy_id = strategy.id
    vault.check_interval = _check_interval_for_strategy(strategy)
    await db.commit()

    return {
        "status": "linked",
        "address": address,
        "strategy_id": strategy.id,
        "strategy_name": strategy.name,
        "check_interval": vault.check_interval,
    }


@router.patch("/vaults/{address}")
async def update_vault(
    address: str, request: UpdateVaultRequest, db: AsyncSession = Depends(get_db)
) -> dict:
    """Update vault settings (name, status, check_interval)."""
    address = address.lower()

    result = await db.execute(select(Vault).where(Vault.address == address))
    vault = result.scalar_one_or_none()

    if not vault:
        raise HTTPException(status_code=404, detail="Vault not found")

    if request.name is not None:
        vault.name = request.name
    if request.status is not None:
        if request.status not in {"active", "paused"}:
            raise HTTPException(
                status_code=422, detail="Status must be 'active' or 'paused'"
            )
        vault.status = request.status
    if request.check_interval is not None:
        valid_intervals = {"1m", "5m", "15m", "1H", "4H"}
        if request.check_interval not in valid_intervals:
            raise HTTPException(
                status_code=422,
                detail=f"check_interval must be one of: {', '.join(sorted(valid_intervals))}",
            )
        vault.check_interval = request.check_interval

    await db.commit()
    return {
        "status": "updated",
        "address": address,
        "name": vault.name,
        "vault_status": vault.status,
        "check_interval": vault.check_interval,
    }


@router.post("/vaults/{address}/snapshot")
async def trigger_vault_snapshot(
    address: str, db: AsyncSession = Depends(get_db)
) -> dict:
    """Run a performance snapshot for this vault now (TVL, share price, depositor count, history)."""
    address = address.lower()
    result = await db.execute(select(Vault).where(Vault.address == address))
    vault = result.scalar_one_or_none()
    if not vault:
        raise HTTPException(status_code=404, detail="Vault not found")
    market_data = get_market_data()
    snapshot = await run_snapshot_job(
        db=db,
        vault_address=vault.address,
        market_data=market_data,
    )
    return {
        "status": "ok",
        "address": address,
        "tvl": snapshot.tvl,
        "share_price": snapshot.share_price,
        "depositor_count": snapshot.depositor_count,
    }


@router.get("/vaults")
async def list_vaults(db: AsyncSession = Depends(get_db)) -> list[dict]:
    """List all registered vaults with strategy details."""
    result = await db.execute(
        select(Vault).options(selectinload(Vault.strategy))
    )
    vaults = result.scalars().all()
    return [
        {
            "address": v.address,
            "name": v.name,
            "chain": v.chain,
            "status": v.status,
            "check_interval": v.check_interval,
            "strategy_id": v.strategy_id,
            "strategy_name": v.strategy.name if v.strategy else None,
            "strategy_slug": v.strategy.slug if v.strategy else None,
            "strategy_asset": v.strategy.asset if v.strategy else None,
            "strategy_timeframe": v.strategy.timeframe if v.strategy else None,
            "last_checked_at": v.last_checked_at.isoformat() if v.last_checked_at else None,
            "created_at": v.created_at.isoformat() if v.created_at else None,
        }
        for v in vaults
    ]


@router.get("/vaults/{address}")
async def get_vault_detail(
    address: str, db: AsyncSession = Depends(get_db)
) -> dict:
    """Get detailed info about a specific vault."""
    address = address.lower()
    result = await db.execute(
        select(Vault)
        .options(selectinload(Vault.strategy), selectinload(Vault.trades))
        .where(Vault.address == address)
    )
    vault = result.scalar_one_or_none()

    if not vault:
        raise HTTPException(status_code=404, detail="Vault not found")

    recent_trades = sorted(vault.trades, key=lambda t: t.timestamp, reverse=True)[:10]

    return {
        "address": vault.address,
        "name": vault.name,
        "chain": vault.chain,
        "status": vault.status,
        "check_interval": vault.check_interval,
        "strategy": {
            "id": vault.strategy.id,
            "name": vault.strategy.name,
            "slug": vault.strategy.slug,
            "asset": vault.strategy.asset,
            "timeframe": vault.strategy.timeframe,
        } if vault.strategy else None,
        "tvl": float(vault.tvl) if vault.tvl else None,
        "share_price": float(vault.share_price) if vault.share_price else None,
        "last_checked_at": vault.last_checked_at.isoformat() if vault.last_checked_at else None,
        "created_at": vault.created_at.isoformat() if vault.created_at else None,
        "recent_trades": [
            {
                "id": t.id,
                "side": t.side,
                "asset": t.asset,
                "size": float(t.size) if t.size is not None else None,
                "entry_price": float(t.entry_price),
                "result": t.result,
                "tx_hash": t.tx_hash,
                "error_message": getattr(t, "error_message", None),
                "timestamp": t.timestamp.isoformat(),
            }
            for t in recent_trades
        ],
    }


@router.get(
    "/referrals/suspicious",
    response_model=list[SuspiciousReferralPatternSchema],
    response_model_by_alias=True,
)
async def admin_scan_suspicious_referrals(db: AsyncSession = Depends(get_db)):
    payload = await scan_suspicious_patterns(db)
    return [SuspiciousReferralPatternSchema.model_validate(item) for item in payload]


@router.post(
    "/referrals/suspicious-review",
    response_model=ReferralAbuseReviewResponse,
    response_model_by_alias=True,
)
async def admin_create_referral_review(
    request: ReferralAbuseReviewRequest,
    db: AsyncSession = Depends(get_db),
):
    payload = await create_abuse_review(
        db,
        referrer_address=request.referrerAddress,
        issue_type=request.issueType,
        reason=request.reason,
        notes=request.notes,
        details=request.details,
    )
    return ReferralAbuseReviewResponse.model_validate(payload)
