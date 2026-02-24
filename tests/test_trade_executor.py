import asyncio

import pytest

from api.config import settings
from api.execution.models import Signal
from api.execution.trade_executor import TradeExecutor, TradeResult


def test_calculate_size_usd_from_tvl(monkeypatch):
    executor = TradeExecutor()
    monkeypatch.setattr(executor, "_get_vault_tvl", lambda _addr: 1000.0)
    size = executor._calculate_size_usd(
        asset="BTC",
        size_pct=0.1,
        current_price=100.0,
        vault_address="0xvault",
    )
    assert size == pytest.approx(100.0)  # 10% of $1000


def test_calculate_size_usd_fallback(monkeypatch):
    executor = TradeExecutor()
    monkeypatch.setattr(executor, "_get_vault_tvl", lambda _addr: 0.0)
    size = executor._calculate_size_usd(
        asset="BTC",
        size_pct=0.5,
        current_price=50000.0,
        vault_address="0xvault",
    )
    # Fallback: 0.01 BTC * $50000 * 0.5 = $250
    assert size == pytest.approx(250.0)


def test_execute_trade_trading_disabled(monkeypatch):
    monkeypatch.setattr(settings, "trading_enabled", False)
    monkeypatch.setattr(settings, "trader_private_key", "")
    executor = TradeExecutor()
    signal = Signal(direction=1, confidence=0.9, size_pct=0.2, reason="test", current_price=100.0, asset="BTC")
    res = asyncio.run(executor.execute_trade(signal, "0xvault"))
    assert res.success is False
    assert res.error == "Trading disabled"


def test_execute_trade_missing_key(monkeypatch):
    monkeypatch.setattr(settings, "trading_enabled", True)
    monkeypatch.setattr(settings, "trader_private_key", "")
    executor = TradeExecutor()
    signal = Signal(direction=1, confidence=0.9, size_pct=0.2, reason="test", current_price=100.0, asset="BTC")
    res = asyncio.run(executor.execute_trade(signal, "0xvault"))
    assert res.success is False
    assert res.error == "Missing trader private key"


def test_execute_trade_not_actionable(monkeypatch):
    monkeypatch.setattr(settings, "trading_enabled", True)
    executor = TradeExecutor()
    signal = Signal(direction=0, confidence=0.1, size_pct=0.0, reason="test", current_price=50.0, asset="BTC")
    res = asyncio.run(executor.execute_trade(signal, "0xvault"))
    assert res.success is True
    assert res.error == "Signal not actionable"


def test_execute_trade_unknown_market(monkeypatch):
    monkeypatch.setattr(settings, "trading_enabled", True)
    monkeypatch.setattr(settings, "trader_private_key", "0x" + "11" * 32)
    monkeypatch.setattr(settings, "gmx_execution_fee_wei", 100000000000000)
    executor = TradeExecutor()
    executor.trader = object()
    signal = Signal(direction=1, confidence=0.9, size_pct=0.2, reason="test", current_price=100.0, asset="DOGE")
    res = asyncio.run(executor.execute_trade(signal, "0xvault"))
    assert res.success is False
    assert "DOGE" in (res.error or "") or "market" in (res.error or "").lower()


def test_wait_for_confirmation_success(monkeypatch):
    executor = TradeExecutor()

    class DummyEth:
        def get_transaction_receipt(self, _tx_hash):
            return {"status": 1, "gasUsed": 123}

    executor.web3 = type("DummyWeb3", (), {"eth": DummyEth()})()
    receipt = asyncio.run(executor._wait_for_confirmation("0xhash", timeout=1))
    assert receipt["gasUsed"] == 123


def test_wait_for_confirmation_reverted_raises_runtime_error(monkeypatch):
    executor = TradeExecutor()

    class DummyEth:
        def get_transaction_receipt(self, _tx_hash):
            return {"status": 0}

    executor.web3 = type("DummyWeb3", (), {"eth": DummyEth()})()
    with pytest.raises(RuntimeError, match="Transaction reverted"):
        asyncio.run(executor._wait_for_confirmation("0xhash", timeout=1))


def test_wait_for_confirmation_timeout(monkeypatch):
    executor = TradeExecutor()

    class DummyEth:
        def get_transaction_receipt(self, _tx_hash):
            return None

    executor.web3 = type("DummyWeb3", (), {"eth": DummyEth()})()
    with pytest.raises(TimeoutError, match="Transaction confirmation timeout"):
        asyncio.run(executor._wait_for_confirmation("0xhash", timeout=0))
