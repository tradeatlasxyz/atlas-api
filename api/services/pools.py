from __future__ import annotations

from collections import OrderedDict
from datetime import date, datetime, timezone
from typing import Optional, Tuple

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.execution.scheduler import (
    CIRCUIT_BREAKER_COOLDOWN,
    CIRCUIT_BREAKER_THRESHOLD,
    get_scheduler,
)
from api.models.database import PerformanceSnapshot, SignalLog, Trade, Vault


def _bucket_key(ts: datetime, interval: str):
    if interval == "hourly":
        return ts.replace(minute=0, second=0, microsecond=0)
    if interval == "weekly":
        iso = ts.isocalendar()
        return (iso.year, iso.week)
    return ts.date()


def _aggregate_snapshots(
    snapshots: list[PerformanceSnapshot], interval: str
) -> list[PerformanceSnapshot]:
    if interval == "hourly":
        return snapshots

    buckets: "OrderedDict[object, PerformanceSnapshot]" = OrderedDict()
    for snapshot in snapshots:
        buckets[_bucket_key(snapshot.timestamp, interval)] = snapshot

    return list(buckets.values())


def _snapshot_to_point(
    snapshot: PerformanceSnapshot, previous_price: Optional[float]
) -> tuple[dict, float]:
    share_price = float(snapshot.share_price)
    tvl = float(snapshot.tvl)
    daily_return = None

    if snapshot.daily_return is not None:
        daily_return = float(snapshot.daily_return)
    elif previous_price is not None and previous_price > 0:
        daily_return = (share_price - previous_price) / previous_price

    point = {
        "timestamp": int(snapshot.timestamp.timestamp() * 1000),
        "share_price": share_price,
        "tvl": tvl,
        "depositor_count": snapshot.depositor_count,
        "daily_return": daily_return,
    }
    return point, share_price


def _derive_date_range(
    start_date: Optional[date],
    end_date: Optional[date],
    snapshots: list[PerformanceSnapshot],
) -> tuple[Optional[str], Optional[str]]:
    if start_date:
        start_str = start_date.isoformat()
    elif snapshots:
        start_str = snapshots[0].timestamp.date().isoformat()
    else:
        start_str = None

    if end_date:
        end_str = end_date.isoformat()
    elif snapshots:
        end_str = snapshots[-1].timestamp.date().isoformat()
    else:
        end_str = None

    return start_str, end_str


async def get_vault_history(
    db: AsyncSession,
    *,
    vault_address: str,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    interval: str = "daily",
    limit: int = 365,
) -> Tuple[Optional[list[dict]], Optional[dict]]:
    vault_query = select(Vault).where(Vault.address == vault_address)
    vault_result = await db.execute(vault_query)
    vault = vault_result.scalar_one_or_none()

    if not vault:
        return None, None

    query = (
        select(PerformanceSnapshot)
        .where(PerformanceSnapshot.vault_address == vault_address)
        .order_by(PerformanceSnapshot.timestamp.asc())
    )

    if start_date:
        query = query.where(
            PerformanceSnapshot.timestamp
            >= datetime.combine(start_date, datetime.min.time())
        )
    if end_date:
        query = query.where(
            PerformanceSnapshot.timestamp
            <= datetime.combine(end_date, datetime.max.time())
        )

    query = query.limit(limit)

    result = await db.execute(query)
    snapshots = list(result.scalars().all())

    snapshots = _aggregate_snapshots(snapshots, interval)

    data_points = []
    previous_price = None
    for snapshot in snapshots:
        point, previous_price = _snapshot_to_point(snapshot, previous_price)
        data_points.append(point)

    start_str, end_str = _derive_date_range(start_date, end_date, snapshots)

    meta = {
        "vault_address": vault_address,
        "start_date": start_str,
        "end_date": end_str,
        "data_points": len(data_points),
        "interval": interval,
    }

    return data_points, meta


async def get_vault_trades(
    db: AsyncSession,
    *,
    vault_address: str,
    page: int = 1,
    limit: int = 50,
    include_errors: bool = False,
) -> tuple[Optional[list[Trade]], Optional[dict]]:
    vault_query = select(Vault.address).where(Vault.address == vault_address)
    vault_result = await db.execute(vault_query)
    if vault_result.scalar_one_or_none() is None:
        return None, None

    base_filters = [Trade.vault_address == vault_address]
    if not include_errors:
        base_filters.append(Trade.error_message.is_(None))

    total_query = select(func.count(Trade.id)).where(*base_filters)
    total_result = await db.execute(total_query)
    total = int(total_result.scalar_one() or 0)

    offset = (page - 1) * limit
    trades_query = (
        select(Trade)
        .where(*base_filters)
        .order_by(Trade.timestamp.desc())
        .offset(offset)
        .limit(limit)
    )
    trades_result = await db.execute(trades_query)
    trades = list(trades_result.scalars().all())

    meta = {
        "vault_address": vault_address,
        "page": page,
        "limit": limit,
        "total": total,
        "has_more": (offset + len(trades)) < total,
    }
    return trades, meta


async def get_vault_signals(
    db: AsyncSession,
    *,
    vault_address: str,
    page: int = 1,
    limit: int = 50,
) -> tuple[Optional[list[SignalLog]], Optional[dict]]:
    vault_query = select(Vault.address).where(Vault.address == vault_address)
    vault_result = await db.execute(vault_query)
    if vault_result.scalar_one_or_none() is None:
        return None, None

    total_query = select(func.count(SignalLog.id)).where(
        SignalLog.vault_address == vault_address
    )
    total_result = await db.execute(total_query)
    total = int(total_result.scalar_one() or 0)

    offset = (page - 1) * limit
    signals_query = (
        select(SignalLog)
        .where(SignalLog.vault_address == vault_address)
        .order_by(SignalLog.timestamp.desc())
        .offset(offset)
        .limit(limit)
    )
    signals_result = await db.execute(signals_query)
    signals = list(signals_result.scalars().all())

    meta = {
        "vault_address": vault_address,
        "page": page,
        "limit": limit,
        "total": total,
        "has_more": (offset + len(signals)) < total,
    }
    return signals, meta


async def get_vault_live_performance(
    db: AsyncSession,
    *,
    vault_address: str,
) -> Optional[dict]:
    vault_query = select(Vault.address).where(Vault.address == vault_address)
    vault_result = await db.execute(vault_query)
    if vault_result.scalar_one_or_none() is None:
        return None

    trades_query = (
        select(Trade)
        .where(Trade.vault_address == vault_address, Trade.error_message.is_(None))
        .order_by(Trade.timestamp.asc())
    )
    trades_result = await db.execute(trades_query)
    trades = list(trades_result.scalars().all())

    snapshots_query = (
        select(PerformanceSnapshot)
        .where(PerformanceSnapshot.vault_address == vault_address)
        .order_by(PerformanceSnapshot.timestamp.asc())
    )
    snapshots_result = await db.execute(snapshots_query)
    snapshots = list(snapshots_result.scalars().all())

    closed = [t for t in trades if t.result in ("win", "loss")]
    open_trades = [t for t in trades if t.result == "open" or t.result not in ("win", "loss")]
    wins = [t for t in closed if t.result == "win"]
    losses = [t for t in closed if t.result == "loss"]

    win_rate = (len(wins) / len(closed)) if closed else None

    realized_components = [float(t.pnl) for t in closed if t.pnl is not None]
    realized_pnl = sum(realized_components) if realized_components else None

    latest_snapshot = snapshots[-1] if snapshots else None
    unrealized_pnl = (
        float(latest_snapshot.unrealized_pnl)
        if latest_snapshot and latest_snapshot.unrealized_pnl is not None
        else None
    )
    total_pnl = (
        realized_pnl + unrealized_pnl
        if realized_pnl is not None and unrealized_pnl is not None
        else None
    )

    win_pnl = sum(float(t.pnl) for t in wins if t.pnl is not None)
    loss_pnl = abs(sum(float(t.pnl) for t in losses if t.pnl is not None))
    profit_factor = (win_pnl / loss_pnl) if loss_pnl > 0 else None

    durations = [
        (t.exit_timestamp - t.timestamp).total_seconds() / 3600
        for t in closed
        if t.exit_timestamp is not None and t.timestamp is not None
    ]
    avg_duration = (sum(durations) / len(durations)) if durations else None

    daily_returns = [
        float(snapshot.daily_return)
        for snapshot in snapshots
        if snapshot.daily_return is not None
    ]
    sharpe = None
    if len(daily_returns) >= 5:
        std = float(np.std(daily_returns, ddof=1))
        if std > 0:
            sharpe = (float(np.mean(daily_returns)) / std) * (252**0.5)

    return {
        "vault_address": vault_address,
        "total_trades": len(trades),
        "closed_trades": len(closed),
        "open_trades": len(open_trades),
        "win_rate": round(win_rate, 4) if win_rate is not None else None,
        "profit_factor": round(profit_factor, 3) if profit_factor is not None else None,
        "avg_trade_duration_hours": round(avg_duration, 2) if avg_duration is not None else None,
        "realized_pnl_usd": round(realized_pnl, 2) if realized_pnl is not None else None,
        "unrealized_pnl_usd": round(unrealized_pnl, 2) if unrealized_pnl is not None else None,
        "total_pnl_usd": round(total_pnl, 2) if total_pnl is not None else None,
        "sharpe": round(sharpe, 3) if sharpe is not None else None,
        "snapshot_count": len(snapshots),
        "first_trade_at": trades[0].timestamp if trades else None,
        "last_trade_at": trades[-1].timestamp if trades else None,
        "data_quality": {
            "hasClosedTrades": len(closed) > 0,
            "hasSnapshots": len(snapshots) > 0,
            "sharpeDataPoints": len(daily_returns),
            "sharpeAvailable": sharpe is not None,
        },
    }


async def get_vault_positions(
    db: AsyncSession,
    *,
    vault_address: str,
) -> Optional[dict]:
    vault_query = select(Vault.address).where(Vault.address == vault_address)
    vault_result = await db.execute(vault_query)
    if vault_result.scalar_one_or_none() is None:
        return None

    snapshot_query = (
        select(PerformanceSnapshot)
        .where(PerformanceSnapshot.vault_address == vault_address)
        .order_by(PerformanceSnapshot.timestamp.desc())
        .limit(1)
    )
    snapshot_result = await db.execute(snapshot_query)
    snapshot = snapshot_result.scalar_one_or_none()

    if snapshot is None or not snapshot.positions_json:
        return {
            "vault_address": vault_address,
            "positions": [],
            "total_unrealized_pnl": 0.0,
            "snapshot_at": snapshot.timestamp if snapshot else None,
            "is_flat": True,
        }

    positions = []
    for raw in snapshot.positions_json:
        size = float(raw.get("size", 0))
        entry = float(raw.get("entry_price", 0))
        current = float(raw.get("current_price", 0))
        unrealized = float(raw.get("unrealized_pnl", 0))
        leverage = float(raw.get("leverage", 1))

        unrealized_pnl_pct = None
        if entry > 0 and leverage > 0:
            base_change = (current - entry) / entry
            if size < 0:
                base_change = -base_change
            unrealized_pnl_pct = round(base_change * leverage, 4)

        positions.append(
            {
                "market_id": raw.get("market_id", ""),
                "asset": raw.get("asset", ""),
                "direction": "long" if size >= 0 else "short",
                "size": abs(size),
                "size_usd": None,
                "entry_price": entry,
                "current_price": current,
                "unrealized_pnl": round(unrealized, 4),
                "unrealized_pnl_pct": unrealized_pnl_pct,
                "leverage": leverage,
                "liquidation_price": raw.get("liquidation_price"),
            }
        )

    if snapshot.unrealized_pnl is not None:
        total_unrealized = float(snapshot.unrealized_pnl)
    else:
        total_unrealized = sum(position["unrealized_pnl"] for position in positions)

    return {
        "vault_address": vault_address,
        "positions": positions,
        "total_unrealized_pnl": round(total_unrealized, 4),
        "snapshot_at": snapshot.timestamp,
        "is_flat": len(positions) == 0,
    }


async def get_vault_health(
    db: AsyncSession,
    *,
    vault_address: str,
) -> Optional[dict]:
    vault_query = select(Vault).where(Vault.address == vault_address)
    vault_result = await db.execute(vault_query)
    vault = vault_result.scalar_one_or_none()
    if vault is None:
        return None

    scheduler = get_scheduler()
    cb_state = scheduler._circuit_breaker.get(vault_address, {})
    failures = int(cb_state.get("failures", 0))
    tripped_at = cb_state.get("tripped_at")
    circuit_breaker_tripped = failures >= CIRCUIT_BREAKER_THRESHOLD

    cooldown_remaining = None
    if circuit_breaker_tripped and tripped_at is not None:
        elapsed = (datetime.now(timezone.utc) - tripped_at).total_seconds()
        cooldown_remaining = max(0, int(CIRCUIT_BREAKER_COOLDOWN - elapsed))

    last_success_query = (
        select(Trade)
        .where(Trade.vault_address == vault_address, Trade.error_message.is_(None))
        .order_by(Trade.timestamp.desc())
        .limit(1)
    )
    last_success_result = await db.execute(last_success_query)
    last_success = last_success_result.scalar_one_or_none()

    last_failure_query = (
        select(Trade)
        .where(Trade.vault_address == vault_address, Trade.error_message.is_not(None))
        .order_by(Trade.timestamp.desc())
        .limit(1)
    )
    last_failure_result = await db.execute(last_failure_query)
    last_failure = last_failure_result.scalar_one_or_none()

    if circuit_breaker_tripped:
        status = "paused"
    elif failures > 0 or last_failure is not None:
        status = "degraded"
    else:
        status = "healthy"

    return {
        "vault_address": vault_address,
        "circuit_breaker_tripped": circuit_breaker_tripped,
        "consecutive_failures": failures,
        "tripped_at": tripped_at,
        "cooldown_remaining_seconds": cooldown_remaining,
        "circuit_breaker_threshold": CIRCUIT_BREAKER_THRESHOLD,
        "circuit_breaker_cooldown": CIRCUIT_BREAKER_COOLDOWN,
        "last_successful_trade_at": last_success.timestamp if last_success else None,
        "last_failed_trade_at": last_failure.timestamp if last_failure else None,
        "last_error_message": last_failure.error_message if last_failure else None,
        "last_checked_at": vault.last_checked_at,
        "status": status,
    }
