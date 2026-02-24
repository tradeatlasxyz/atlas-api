"""Background scheduler for execution loop."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional, List

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select, update

from api.config import settings
from api.execution.market_data import get_market_data
from api.execution.position_tracker import PositionTracker, run_snapshot_job
from api.execution.signal_generator import SignalGenerator
from api.execution.signal_logger import log_signal
from api.execution.strategy_loader import load_strategy_by_vault
from api.execution.trade_executor import TradeExecutor, TradeResult
from api.execution.trade_logger import log_trade
from api.execution.models import Position
from api.models.database import Vault, Strategy
from api.services.database import async_session
from api.services.referral_indexer import ReferralEventIndexer

logger = logging.getLogger(__name__)

INTERVAL_SECONDS = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "1H": 3600,
    "1h": 3600,
    "4H": 14400,
    "4h": 14400,
}


CIRCUIT_BREAKER_THRESHOLD = 5  # Pause after N consecutive failures
CIRCUIT_BREAKER_COOLDOWN = 3600  # Resume after 1 hour (seconds)


class ExecutionScheduler:
    def __init__(self) -> None:
        self.scheduler = AsyncIOScheduler()
        self.market_data = get_market_data()
        self.signal_generator = SignalGenerator(self.market_data)
        self.trade_executor = TradeExecutor()
        self.referral_indexer = ReferralEventIndexer()
        self._running = False
        # Circuit breaker state: vault_address -> {failures: int, tripped_at: datetime}
        self._circuit_breaker: dict[str, dict] = {}

    async def start(self) -> None:
        if self._running:
            return
        logger.info("Starting execution scheduler...")

        self.scheduler.add_job(
            self._main_loop,
            IntervalTrigger(minutes=1),
            id="main_loop",
            name="Signal Generation Loop",
            replace_existing=True,
        )
        self.scheduler.add_job(
            self._snapshot_loop,
            CronTrigger(minute=0),
            id="snapshots",
            name="Position Snapshots",
            replace_existing=True,
        )
        self.scheduler.add_job(
            self._health_check,
            IntervalTrigger(minutes=5),
            id="health",
            name="Health Check",
            replace_existing=True,
        )
        if self.referral_indexer.enabled:
            self.scheduler.add_job(
                self._referral_index_loop,
                IntervalTrigger(seconds=max(10, settings.referral_indexer_interval_seconds)),
                id="referral_indexer",
                name="Referral Event Indexer",
                replace_existing=True,
            )

        self.scheduler.start()
        self._running = True
        logger.info("Scheduler started")

    async def stop(self) -> None:
        if not self._running:
            return
        logger.info("Stopping scheduler...")
        self.scheduler.shutdown(wait=True)
        self._running = False

    async def _main_loop(self) -> None:
        logger.debug("Running main loop...")
        now = datetime.now(timezone.utc)
        async with async_session() as db:
            query = select(Vault).join(Strategy).where(Vault.status == "active")
            result = await db.execute(query)
            vaults = result.scalars().all()
            for vault in vaults:
                try:
                    if self._should_check(vault, now):
                        await self._process_vault(db, vault)
                        await db.execute(
                            update(Vault)
                            .where(Vault.address == vault.address)
                            .values(last_checked_at=now)
                        )
                        await db.commit()
                except Exception as exc:
                    logger.exception("Error processing vault %s: %s", vault.address, exc)

    def _should_check(self, vault, now: datetime) -> bool:
        if vault.last_checked_at is None:
            return True
        interval = vault.check_interval or "1m"
        interval_secs = INTERVAL_SECONDS.get(interval, 60)
        last = vault.last_checked_at
        # Normalise: make both aware (UTC) or both naive so subtraction works
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        elapsed = (now - last).total_seconds()
        return elapsed >= interval_secs

    def _is_circuit_broken(self, vault_address: str) -> bool:
        """Check if the vault's circuit breaker is tripped."""
        state = self._circuit_breaker.get(vault_address)
        if not state:
            return False
        if state["failures"] < CIRCUIT_BREAKER_THRESHOLD:
            return False
        # Check cooldown
        tripped_at = state.get("tripped_at")
        if tripped_at:
            elapsed = (datetime.now(timezone.utc) - tripped_at).total_seconds()
            if elapsed >= CIRCUIT_BREAKER_COOLDOWN:
                # Reset after cooldown
                logger.info(
                    "Circuit breaker cooldown expired for %s — resuming trading",
                    vault_address[:10],
                )
                self._circuit_breaker.pop(vault_address, None)
                return False
        return True

    def _record_trade_result(self, vault_address: str, success: bool) -> None:
        """Update circuit breaker state after a trade attempt."""
        if success:
            self._circuit_breaker.pop(vault_address, None)
            return
        state = self._circuit_breaker.setdefault(
            vault_address, {"failures": 0, "tripped_at": None}
        )
        state["failures"] += 1
        if state["failures"] >= CIRCUIT_BREAKER_THRESHOLD and not state["tripped_at"]:
            state["tripped_at"] = datetime.now(timezone.utc)
            logger.error(
                "CIRCUIT BREAKER TRIPPED for vault %s after %d consecutive failures. "
                "Trading paused for %d seconds. Check vault balances and configuration.",
                vault_address[:10],
                state["failures"],
                CIRCUIT_BREAKER_COOLDOWN,
            )

    async def _process_vault(self, db, vault) -> None:
        logger.info("Processing vault: %s...", vault.address[:10])

        # Circuit breaker check
        if self._is_circuit_broken(vault.address):
            state = self._circuit_breaker.get(vault.address, {})
            logger.debug(
                "Skipping vault %s — circuit breaker active (%d failures)",
                vault.address[:10],
                state.get("failures", 0),
            )
            return

        strategy = await load_strategy_by_vault(db, vault.address)
        if not strategy:
            logger.warning("No strategy loaded for %s", vault.address)
            return
        signal = await self.signal_generator.generate_signal(strategy)
        logger.info(
            "Signal for %s: %s (confidence %.2f)",
            vault.address[:10],
            signal.direction_str,
            signal.confidence,
        )
        await log_signal(
            db=db,
            vault_address=vault.address,
            strategy_id=vault.strategy_id,
            signal=signal,
        )

        # ---- Position-aware execution ----
        # 1. Fetch current on-chain positions for this vault's asset
        current_positions = await self._get_vault_positions_for_asset(
            vault.address, signal.asset
        )
        current_direction = self._net_position_direction(current_positions)

        # 2. Determine what actions are needed
        desired_direction = signal.direction  # 1=LONG, -1=SHORT, 0=NEUTRAL
        needs_close = False
        needs_open = False

        if desired_direction == 0:
            # Neutral signal: close any existing position
            if current_direction != 0:
                needs_close = True
                logger.info(
                    "Neutral signal for %s — closing existing %s position",
                    vault.address[:10],
                    "LONG" if current_direction > 0 else "SHORT",
                )
        elif desired_direction == current_direction:
            # Already positioned in the same direction — skip
            logger.info(
                "Vault %s already has a %s position — skipping duplicate open",
                vault.address[:10],
                signal.direction_str,
            )
        else:
            # Direction mismatch: close opposite if any, then open new
            if current_direction != 0:
                needs_close = True
                logger.info(
                    "Flipping position for %s: closing %s, opening %s",
                    vault.address[:10],
                    "LONG" if current_direction > 0 else "SHORT",
                    signal.direction_str,
                )
            needs_open = signal.is_actionable

        # 3. Execute close if needed
        if needs_close:
            close_result = await self._close_positions(
                vault.address, signal.asset, current_positions, signal.current_price
            )
            if close_result:
                await log_trade(
                    db=db,
                    vault_address=vault.address,
                    strategy_id=vault.strategy_id,
                    result=close_result,
                )
                self._record_trade_result(vault.address, close_result.success)
                if close_result.success:
                    logger.info("Position closed: %s", close_result.tx_hash)
                else:
                    logger.error("Close failed: %s — aborting open", close_result.error)
                    return  # Don't open if close failed

        # 4. Execute open if needed
        if needs_open:
            result = await self.trade_executor.execute_trade(
                signal=signal, vault_address=vault.address
            )
            await log_trade(
                db=db,
                vault_address=vault.address,
                strategy_id=vault.strategy_id,
                result=result,
            )
            self._record_trade_result(vault.address, result.success)
            if result.success:
                logger.info("Trade executed: %s", result.tx_hash)
            else:
                logger.error("Trade failed: %s", result.error)

    async def _get_vault_positions_for_asset(
        self, vault_address: str, asset: str
    ) -> List[Position]:
        """Fetch current GMX positions for a specific asset in the vault."""
        try:
            tracker = PositionTracker(self.market_data)
            all_positions = await tracker.get_vault_positions(vault_address)
            return [p for p in all_positions if p.asset.upper() == asset.upper()]
        except Exception as exc:
            logger.warning(
                "Failed to fetch positions for %s/%s (non-fatal): %s",
                vault_address[:10],
                asset,
                exc,
            )
            return []

    def _net_position_direction(self, positions: List[Position]) -> int:
        """Return net position direction: 1=long, -1=short, 0=flat."""
        if not positions:
            return 0
        net_size = sum(p.size for p in positions)
        if net_size > 0:
            return 1
        elif net_size < 0:
            return -1
        return 0

    async def _close_positions(
        self,
        vault_address: str,
        asset: str,
        positions: List[Position],
        current_price: float,
    ) -> Optional[TradeResult]:
        """Close existing positions for an asset in the vault."""
        if not positions:
            return None
        # Sum all position sizes for this asset
        total_size_usd = sum(abs(p.size * p.current_price) for p in positions)
        if total_size_usd <= 0:
            return None
        is_long = positions[0].size > 0  # Direction of position to close
        try:
            from api.onchain.gmx import get_market_address_for_asset

            market_address = get_market_address_for_asset(
                self.trade_executor.web3, asset
            )
            calldata, execution_fee = self.trade_executor._build_close_order_calldata(
                vault_address=vault_address,
                market_address=market_address,
                size_usd=total_size_usd,
                is_long=is_long,
                current_price=current_price,
            )
            tx_hash = await self.trade_executor._execute_via_vault(
                vault_address=vault_address,
                target=self.trade_executor.GMX_EXCHANGE_ROUTER,
                calldata=calldata,
                value=0,
            )
            receipt = await self.trade_executor._wait_for_confirmation(tx_hash)
            logger.info("Close trade executed: %s %s tx=%s", asset, "LONG" if is_long else "SHORT", tx_hash)
            return TradeResult(
                success=True,
                tx_hash=tx_hash,
                error=None,
                gas_used=receipt.get("gasUsed", 0),
                timestamp=datetime.now(timezone.utc),
                direction=0,  # Closing = neutral
                asset=asset,
                size=total_size_usd,
                entry_price=current_price,
            )
        except Exception as exc:
            logger.error("Close trade failed for %s/%s: %s", vault_address[:10], asset, exc)
            return TradeResult(
                success=False,
                tx_hash=None,
                error=str(exc),
                gas_used=0,
                timestamp=datetime.now(timezone.utc),
                direction=0,
                asset=asset,
                size=0.0,
                entry_price=current_price,
            )

    async def _snapshot_loop(self) -> None:
        logger.info("Running position snapshots...")
        async with async_session() as db:
            query = select(Vault).where(Vault.status == "active")
            result = await db.execute(query)
            vaults = result.scalars().all()
            for vault in vaults:
                try:
                    await run_snapshot_job(
                        db=db,
                        vault_address=vault.address,
                        market_data=self.market_data,
                    )
                except Exception as exc:
                    logger.error("Snapshot failed for %s: %s", vault.address, exc)
        logger.info("Snapshots complete for %s vaults", len(vaults))

    async def _health_check(self) -> None:
        jobs = len(self.scheduler.get_jobs())
        buffer_status = self.market_data.get_buffer_status()
        logger.info(
            "Health: %s jobs, candle buffers: %s, referral_indexer=%s",
            jobs,
            buffer_status,
            "enabled" if self.referral_indexer.enabled else "disabled",
        )

    async def _referral_index_loop(self) -> None:
        try:
            result = await self.referral_indexer.index_once()
            if result.get("status") == "indexed":
                logger.info(
                    "Referral indexer processed %s events (%s -> %s)",
                    result.get("processed_events"),
                    result.get("from_block"),
                    result.get("to_block"),
                )
        except Exception as exc:
            logger.exception("Referral indexer job failed: %s", exc)

    async def trigger_vault(self, vault_address: str) -> None:
        async with async_session() as db:
            query = select(Vault).where(Vault.address == vault_address.lower())
            result = await db.execute(query)
            vault = result.scalar_one_or_none()
            if vault:
                await self._process_vault(db, vault)
            else:
                logger.error("Vault not found: %s", vault_address)


_scheduler: Optional[ExecutionScheduler] = None


def get_scheduler() -> ExecutionScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = ExecutionScheduler()
    return _scheduler
