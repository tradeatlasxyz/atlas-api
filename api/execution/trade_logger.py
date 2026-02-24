"""Persist executed trades to the database."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from api.execution.trade_executor import TradeResult
from api.models.database import Trade


async def log_trade(
    db: AsyncSession,
    vault_address: str,
    strategy_id: int,
    result: TradeResult,
) -> Trade:
    count_result = await db.execute(
        select(func.count(Trade.id)).where(Trade.vault_address == vault_address.lower())
    )
    trade_num = int(count_result.scalar() or 0) + 1

    trade = Trade(
        vault_address=vault_address.lower(),
        strategy_id=strategy_id,
        trade_num=trade_num,
        timestamp=result.timestamp or datetime.utcnow(),
        side="LONG" if result.direction == 1 else "SHORT",
        asset=result.asset,
        size=result.size,
        entry_price=result.entry_price,
        exit_price=None,
        exit_timestamp=None,
        pnl=None,
        pnl_pct=None,
        result="success" if result.success else "failed",
        tx_hash=result.tx_hash,
        error_message=result.error if not result.success else None,
    )
    db.add(trade)
    await db.commit()
    return trade
