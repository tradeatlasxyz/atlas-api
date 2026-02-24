from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from api.execution.scheduler import ExecutionScheduler
from api.execution.trade_executor import TradeResult
from api.execution.models import Signal


class DummyScheduler:
    def __init__(self):
        self.jobs = []
        self.started = False

    def add_job(self, func, trigger, id=None, name=None, replace_existing=None):
        self.jobs.append({"id": id, "trigger": trigger, "name": name})

    def start(self):
        self.started = True

    def shutdown(self, wait=True):
        self.started = False

    def get_jobs(self):
        return self.jobs


@dataclass
class DummyVault:
    last_checked_at: datetime | None
    check_interval: str | None


@pytest.mark.asyncio
async def test_should_check_when_never_checked():
    sched = ExecutionScheduler()
    vault = DummyVault(last_checked_at=None, check_interval="1m")
    assert sched._should_check(vault, datetime.utcnow()) is True


@pytest.mark.asyncio
async def test_should_check_respects_interval():
    sched = ExecutionScheduler()
    now = datetime.utcnow()
    vault = DummyVault(last_checked_at=now - timedelta(seconds=30), check_interval="1m")
    assert sched._should_check(vault, now) is False
    vault = DummyVault(last_checked_at=now - timedelta(seconds=61), check_interval="1m")
    assert sched._should_check(vault, now) is True


@pytest.mark.asyncio
async def test_start_registers_jobs(monkeypatch):
    sched = ExecutionScheduler()
    sched.scheduler = DummyScheduler()
    sched.referral_indexer = SimpleNamespace(enabled=False)
    await sched.start()
    job_ids = {job["id"] for job in sched.scheduler.jobs}
    assert job_ids == {"main_loop", "snapshots", "health"}
    await sched.stop()
    assert sched._running is False


@pytest.mark.asyncio
async def test_start_is_idempotent(monkeypatch):
    sched = ExecutionScheduler()
    sched.scheduler = DummyScheduler()
    sched.referral_indexer = SimpleNamespace(enabled=False)
    await sched.start()
    assert len(sched.scheduler.jobs) == 3
    await sched.start()
    assert len(sched.scheduler.jobs) == 3
    await sched.stop()


@pytest.mark.asyncio
async def test_start_registers_referral_indexer_job_when_enabled(monkeypatch):
    sched = ExecutionScheduler()
    sched.scheduler = DummyScheduler()
    sched.referral_indexer = SimpleNamespace(enabled=True, index_once=_no_op)
    await sched.start()
    job_ids = {job["id"] for job in sched.scheduler.jobs}
    assert "referral_indexer" in job_ids
    await sched.stop()


async def _no_op(*_args, **_kwargs):
    return None


@pytest.mark.asyncio
async def test_process_vault_no_strategy(monkeypatch):
    sched = ExecutionScheduler()
    vault = SimpleNamespace(address="0xvault", strategy_id=1, synthetix_account_id=2)

    async def _no_strategy(*_args, **_kwargs):
        return None

    async def _fail(*_args, **_kwargs):
        raise AssertionError("Should not be called")

    monkeypatch.setattr("api.execution.scheduler.load_strategy_by_vault", _no_strategy)
    monkeypatch.setattr("api.execution.scheduler.log_signal", _fail)
    monkeypatch.setattr("api.execution.scheduler.log_trade", _fail)

    await sched._process_vault(None, vault)


@pytest.mark.asyncio
async def test_process_vault_actionable_signal(monkeypatch):
    sched = ExecutionScheduler()
    vault = SimpleNamespace(address="0xvault", strategy_id=7, synthetix_account_id=3)
    strategy = SimpleNamespace(slug="test-strategy")

    signal = Signal(direction=1, confidence=0.8, size_pct=0.2, reason="test", current_price=100.0, asset="BTC")
    result = TradeResult(
        success=False,
        tx_hash=None,
        error="failed",
        gas_used=0,
        timestamp=datetime.utcnow(),
        direction=1,
        asset=signal.asset,
        size=0.0,
        entry_price=signal.current_price,
    )

    called = {"signal": 0, "trade": 0}

    async def _load_strategy(*_args, **_kwargs):
        return strategy

    async def _generate_signal(*_args, **_kwargs):
        return signal

    async def _execute_trade(*_args, **_kwargs):
        return result

    async def _log_signal(*_args, **_kwargs):
        called["signal"] += 1

    async def _log_trade(*_args, **_kwargs):
        called["trade"] += 1

    async def _no_positions(*_args, **_kwargs):
        return []

    monkeypatch.setattr("api.execution.scheduler.load_strategy_by_vault", _load_strategy)
    monkeypatch.setattr(sched.signal_generator, "generate_signal", _generate_signal)
    monkeypatch.setattr(sched.trade_executor, "execute_trade", _execute_trade)
    monkeypatch.setattr("api.execution.scheduler.log_signal", _log_signal)
    monkeypatch.setattr("api.execution.scheduler.log_trade", _log_trade)
    monkeypatch.setattr(sched, "_get_vault_positions_for_asset", _no_positions)

    await sched._process_vault(None, vault)
    assert called == {"signal": 1, "trade": 1}


@pytest.mark.asyncio
async def test_process_vault_skips_duplicate_position(monkeypatch):
    """If signal matches the current on-chain position direction, skip opening."""
    sched = ExecutionScheduler()
    vault = SimpleNamespace(address="0xvault", strategy_id=7, synthetix_account_id=3)
    strategy = SimpleNamespace(slug="test-strategy")

    # LONG signal while already LONG => should NOT open
    signal = Signal(direction=1, confidence=0.9, size_pct=0.3, reason="test", current_price=100.0, asset="BTC")
    existing_position = SimpleNamespace(
        market_id="0xmarket", asset="BTC", size=0.5, entry_price=99.0,
        current_price=100.0, unrealized_pnl=5.0, leverage=5.0,
    )

    called = {"signal": 0, "trade": 0}

    async def _load_strategy(*_args, **_kwargs):
        return strategy

    async def _generate_signal(*_args, **_kwargs):
        return signal

    async def _execute_trade(*_args, **_kwargs):
        raise AssertionError("execute_trade should NOT be called for duplicate position")

    async def _log_signal(*_args, **_kwargs):
        called["signal"] += 1

    async def _log_trade(*_args, **_kwargs):
        called["trade"] += 1

    async def _existing_positions(*_args, **_kwargs):
        return [existing_position]

    monkeypatch.setattr("api.execution.scheduler.load_strategy_by_vault", _load_strategy)
    monkeypatch.setattr(sched.signal_generator, "generate_signal", _generate_signal)
    monkeypatch.setattr(sched.trade_executor, "execute_trade", _execute_trade)
    monkeypatch.setattr("api.execution.scheduler.log_signal", _log_signal)
    monkeypatch.setattr("api.execution.scheduler.log_trade", _log_trade)
    monkeypatch.setattr(sched, "_get_vault_positions_for_asset", _existing_positions)

    await sched._process_vault(None, vault)
    # Signal is always logged, but no trade because already positioned
    assert called == {"signal": 1, "trade": 0}


@pytest.mark.asyncio
async def test_process_vault_neutral_closes_position(monkeypatch):
    """NEUTRAL signal should close existing position."""
    sched = ExecutionScheduler()
    vault = SimpleNamespace(address="0xvault", strategy_id=7, synthetix_account_id=3)
    strategy = SimpleNamespace(slug="test-strategy")

    # NEUTRAL signal while LONG => should close
    signal = Signal(direction=0, confidence=0.0, size_pct=0.0, reason="neutral", current_price=100.0, asset="BTC")
    existing_position = SimpleNamespace(
        market_id="0xmarket", asset="BTC", size=0.5, entry_price=99.0,
        current_price=100.0, unrealized_pnl=5.0, leverage=5.0,
    )

    close_result = TradeResult(
        success=True, tx_hash="0xclose", error=None, gas_used=100,
        timestamp=datetime.utcnow(), direction=0, asset="BTC",
        size=50.0, entry_price=100.0,
    )

    called = {"signal": 0, "trade": 0, "close": 0}

    async def _load_strategy(*_args, **_kwargs):
        return strategy

    async def _generate_signal(*_args, **_kwargs):
        return signal

    async def _log_signal(*_args, **_kwargs):
        called["signal"] += 1

    async def _log_trade(*_args, **_kwargs):
        called["trade"] += 1

    async def _existing_positions(*_args, **_kwargs):
        return [existing_position]

    async def _close_positions(*_args, **_kwargs):
        called["close"] += 1
        return close_result

    monkeypatch.setattr("api.execution.scheduler.load_strategy_by_vault", _load_strategy)
    monkeypatch.setattr(sched.signal_generator, "generate_signal", _generate_signal)
    monkeypatch.setattr("api.execution.scheduler.log_signal", _log_signal)
    monkeypatch.setattr("api.execution.scheduler.log_trade", _log_trade)
    monkeypatch.setattr(sched, "_get_vault_positions_for_asset", _existing_positions)
    monkeypatch.setattr(sched, "_close_positions", _close_positions)

    await sched._process_vault(None, vault)
    # Signal logged, close was called and logged as a trade
    assert called == {"signal": 1, "trade": 1, "close": 1}
