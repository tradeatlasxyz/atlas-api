"""Persist generated signals for audit."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from api.execution.models import Signal
from api.models.database import SignalLog


async def log_signal(
    db: AsyncSession,
    vault_address: str,
    strategy_id: int,
    signal: Signal,
) -> SignalLog:
    entry = SignalLog(
        vault_address=vault_address.lower(),
        strategy_id=strategy_id,
        timestamp=signal.timestamp or datetime.utcnow(),
        asset=signal.asset,
        timeframe=signal.timeframe,
        direction=signal.direction,
        confidence=signal.confidence,
        size_pct=signal.size_pct,
        reason=signal.reason,
        current_price=signal.current_price,
        stop_loss=signal.stop_loss,
        take_profit=signal.take_profit,
    )
    db.add(entry)
    await db.commit()
    return entry
