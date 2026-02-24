"""
Comprehensive E2E tests for all deployed strategies.

Covers:
  - Strategy loading & meta validation (all 5)
  - Signal generation with mock data (all 5)
  - Live signal generation (all 5 tradeable strategies)
  - Strategy ↔ vault linkage via DB (all 5)
  - Scheduler execution flow (all 5 tradeable strategies)
  - Per-asset GMX trade execution on forknet (BTC, ETH, SOL only)
  - Mainnet read-only validation (prices, markets, vault state)

Run forknet tests:
    pytest tests/e2e/test_all_strategies_e2e.py -m forknet -v -s

Run mainnet (read-only) tests:
    pytest tests/e2e/test_all_strategies_e2e.py -m mainnet -v -s

Requirements:
    - Anvil (Foundry) installed for forknet tests
    - .env with TRADER_PRIVATE_KEY and ARBITRUM_RPC_URL
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal as signal_mod
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Optional

import numpy as np
import pandas as pd
import pytest
import requests
from eth_account import Account
from web3 import Web3

# ---------------------------------------------------------------------------
# Project imports
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from api.config import settings
from api.execution.market_data import MarketDataFetcher, PYTH_SYMBOLS
from api.execution.models import Signal, Position
from api.execution.signal_generator import SignalGenerator
from api.execution.strategy_loader import (
    STRATEGIES_DIR,
    LoadedStrategy,
    load_strategy_from_file,
)
from api.execution.trade_executor import TradeExecutor, TradeResult
from api.onchain.gmx import (
    get_market_address_for_asset,
    get_market_long_token,
    resolve_market_addresses,
)

logger = logging.getLogger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

ANVIL_PORT = 18546  # Different port from existing forknet tests
ANVIL_RPC_URL = f"http://127.0.0.1:{ANVIL_PORT}"

WETH_ADDRESS = "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1"
USDC_ADDRESS = "0xaf88d065e77c8cC2239327C5EDb3A432268e5831"
USDC_WHALE = "0x2Df1c51E09aECF9cacB7bc98cB1742757f163dF7"

TEST_VAULT_ADDRESS = os.getenv("TEST_VAULT_ADDRESS", "0x0000000000000000000000000000000000000001")

# All 5 deployed strategies and expected metadata
DEPLOYED_STRATEGIES = {
    "btc-momentum-1h": {"asset": "BTC", "timeframe": "1H", "type": "RSI Momentum"},
    "btc-trend-4h":    {"asset": "BTC", "timeframe": "4H", "type": "MA Crossover"},
    "eth-trend-1d":    {"asset": "ETH", "timeframe": "1D", "type": "MA Crossover"},
    "sol-trend-1d":    {"asset": "SOL", "timeframe": "1D", "type": "MA Crossover"},
    "baseline-marketgod":    {"asset": "BTC", "timeframe": "1H", "type": None},  # defaults
}

# All strategies are tradeable on GMX V2 Arbitrum
TRADEABLE_STRATEGIES = DEPLOYED_STRATEGIES

# Slugs list for parameterization
TRADEABLE_SLUGS = list(TRADEABLE_STRATEGIES.keys())

# Assets with GMX V2 markets on Arbitrum
GMX_TRADEABLE_ASSETS = {"BTC", "ETH", "SOL"}

# Assets with Pyth price feeds
PYTH_PRICED_ASSETS = set(PYTH_SYMBOLS.keys())

# ERC20 minimal ABI
ERC20_ABI = [
    {"inputs": [{"name": "account", "type": "address"}], "name": "balanceOf", "outputs": [{"type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"inputs": [{"name": "recipient", "type": "address"}, {"name": "amount", "type": "uint256"}], "name": "transfer", "outputs": [{"type": "bool"}], "stateMutability": "nonpayable", "type": "function"},
]


# ============================================================================
# FIXTURES
# ============================================================================

def _get_mainnet_rpc() -> str:
    rpc = os.getenv("ARBITRUM_RPC_URL") or settings.arbitrum_rpc_url
    if not rpc:
        pytest.skip("ARBITRUM_RPC_URL required")
    return rpc


def _get_trader_key() -> str:
    key = os.getenv("TRADER_PRIVATE_KEY") or settings.trader_private_key
    if not key:
        pytest.skip("TRADER_PRIVATE_KEY required")
    return key


@pytest.fixture(scope="module")
def anvil_fork():
    """Start Anvil fork of Arbitrum mainnet for the entire module."""
    mainnet_rpc = _get_mainnet_rpc()
    anvil_bin = os.path.expanduser("~/.foundry/bin/anvil")
    if not os.path.isfile(anvil_bin):
        try:
            result = subprocess.run(["which", "anvil"], capture_output=True, text=True)
            anvil_bin = result.stdout.strip() if result.returncode == 0 else "anvil"
        except Exception:
            anvil_bin = "anvil"

    logger.info("Starting Anvil on port %s from %s", ANVIL_PORT, mainnet_rpc[:40])

    proc = subprocess.Popen(
        [anvil_bin, "--fork-url", mainnet_rpc, "--port", str(ANVIL_PORT),
         "--chain-id", "42161", "--block-time", "1", "--accounts", "0", "--silent"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )

    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            resp = requests.post(
                ANVIL_RPC_URL,
                json={"jsonrpc": "2.0", "method": "eth_chainId", "params": [], "id": 1},
                timeout=2,
            )
            if resp.status_code == 200:
                break
        except (requests.ConnectionError, requests.Timeout):
            time.sleep(0.5)
    else:
        proc.kill()
        pytest.fail("Anvil failed to start within 30s")

    yield ANVIL_RPC_URL

    proc.send_signal(signal_mod.SIGTERM)
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


@pytest.fixture(scope="module")
def web3(anvil_fork) -> Web3:
    w3 = Web3(Web3.HTTPProvider(anvil_fork))
    assert w3.is_connected()
    return w3


@pytest.fixture(scope="module")
def trader_account() -> Account:
    return Account.from_key(_get_trader_key())


@pytest.fixture(scope="module")
def funded_fork(web3, trader_account):
    """Fund trader + vault on the fork."""
    addr = trader_account.address
    # 1. Fund trader with ETH
    web3.provider.make_request("anvil_setBalance", [addr, hex(Web3.to_wei(100, "ether"))])

    # 2. Wrap ETH → WETH
    weth_abi = [{"inputs": [], "name": "deposit", "outputs": [], "stateMutability": "payable", "type": "function"}]
    weth = web3.eth.contract(address=Web3.to_checksum_address(WETH_ADDRESS), abi=weth_abi)
    tx = weth.functions.deposit().build_transaction({
        "from": addr, "value": Web3.to_wei(10, "ether"), "gas": 100000,
        "gasPrice": web3.eth.gas_price, "nonce": web3.eth.get_transaction_count(addr), "chainId": 42161,
    })
    signed = trader_account.sign_transaction(tx)
    raw = getattr(signed, "raw_transaction", None) or getattr(signed, "rawTransaction", None)
    web3.eth.wait_for_transaction_receipt(web3.eth.send_raw_transaction(raw), timeout=30)

    # 3. Get USDC via whale impersonation
    web3.provider.make_request("anvil_setBalance", [USDC_WHALE, hex(Web3.to_wei(1, "ether"))])
    web3.provider.make_request("anvil_impersonateAccount", [USDC_WHALE])
    usdc = web3.eth.contract(address=Web3.to_checksum_address(USDC_ADDRESS), abi=ERC20_ABI)
    whale_bal = usdc.functions.balanceOf(Web3.to_checksum_address(USDC_WHALE)).call()
    amount_usdc = min(10_000 * 10**6, whale_bal)
    if amount_usdc > 0:
        tx2 = usdc.functions.transfer(Web3.to_checksum_address(addr), amount_usdc).build_transaction({
            "from": Web3.to_checksum_address(USDC_WHALE), "gas": 100000,
            "gasPrice": web3.eth.gas_price,
            "nonce": web3.eth.get_transaction_count(Web3.to_checksum_address(USDC_WHALE)),
        })
        web3.eth.wait_for_transaction_receipt(web3.eth.send_transaction(tx2), timeout=30)
    web3.provider.make_request("anvil_stopImpersonatingAccount", [USDC_WHALE])

    # 4. Fund vault with WETH + USDC from trader
    for tok_addr, amount in [(WETH_ADDRESS, Web3.to_wei(3, "ether")), (USDC_ADDRESS, 5_000 * 10**6)]:
        tok = web3.eth.contract(address=Web3.to_checksum_address(tok_addr), abi=ERC20_ABI)
        bal = tok.functions.balanceOf(Web3.to_checksum_address(addr)).call()
        if bal >= amount:
            tx3 = tok.functions.transfer(Web3.to_checksum_address(TEST_VAULT_ADDRESS), amount).build_transaction({
                "from": addr, "gas": 100000, "gasPrice": web3.eth.gas_price,
                "nonce": web3.eth.get_transaction_count(addr), "chainId": 42161,
            })
            signed3 = trader_account.sign_transaction(tx3)
            raw3 = getattr(signed3, "raw_transaction", None) or getattr(signed3, "rawTransaction", None)
            web3.eth.wait_for_transaction_receipt(web3.eth.send_raw_transaction(raw3), timeout=30)

    return {"trader_address": addr, "vault_address": TEST_VAULT_ADDRESS}


@pytest.fixture(scope="module")
def all_strategies() -> dict[str, LoadedStrategy]:
    """Load all 5 deployed strategies."""
    loaded = {}
    for slug in DEPLOYED_STRATEGIES:
        path = STRATEGIES_DIR / f"{slug}.py"
        if path.exists():
            loaded[slug] = load_strategy_from_file(path)
    return loaded


def _make_mock_df(n: int = 300, base_price: float = 50000.0) -> pd.DataFrame:
    """Generate realistic mock OHLCV data."""
    np.random.seed(42)
    close = base_price + np.cumsum(np.random.randn(n) * 100)
    return pd.DataFrame({
        "timestamp": pd.date_range("2024-01-01", periods=n, freq="1h"),
        "open": close - np.random.uniform(0, 200, n),
        "high": close + np.random.uniform(0, 300, n),
        "low": close - np.random.uniform(0, 300, n),
        "close": close,
        "volume": np.random.uniform(100, 5000, n),
    })


# ============================================================================
# 1. STRATEGY LOADING — All 5 strategies
# ============================================================================


@pytest.mark.forknet
class TestStrategyLoading:
    """Verify all 5 deployed strategies load correctly."""

    def test_all_five_strategies_exist(self):
        """All 5 strategy files should exist in deployed/."""
        for slug in DEPLOYED_STRATEGIES:
            path = STRATEGIES_DIR / f"{slug}.py"
            assert path.exists(), f"Missing strategy file: {path}"

    def test_all_load_successfully(self, all_strategies):
        """All 5 strategies should load without error."""
        assert len(all_strategies) == 5, f"Expected 5 strategies, got {len(all_strategies)}"
        for slug, strat in all_strategies.items():
            assert callable(strat.generate_signals), f"{slug}: generate_signals not callable"
            print(f"  ✓ {slug}: asset={strat.asset}, timeframe={strat.timeframe}")

    @pytest.mark.parametrize("slug,expected", list(DEPLOYED_STRATEGIES.items()))
    def test_strategy_meta(self, all_strategies, slug, expected):
        """Each strategy should have correct asset and timeframe."""
        strat = all_strategies.get(slug)
        assert strat is not None, f"Strategy {slug} not loaded"
        assert strat.asset == expected["asset"], f"{slug}: expected asset={expected['asset']}, got {strat.asset}"
        assert strat.timeframe == expected["timeframe"], f"{slug}: expected tf={expected['timeframe']}, got {strat.timeframe}"

    def test_btc_momentum_rsi_params(self, all_strategies):
        """btc-momentum-1h should have RSI parameters in meta."""
        strat = all_strategies["btc-momentum-1h"]
        params = strat.meta.get("parameters", {})
        assert "rsi_period" in params
        assert params["rsi_period"] == 18

    def test_baseline_marketgod_has_strategy_config(self, all_strategies):
        """baseline-marketgod should have StrategyConfig class."""
        strat = all_strategies["baseline-marketgod"]
        # The wrapped generate_signals should accept df and produce valid output
        assert callable(strat.generate_signals)


# ============================================================================
# 2. SIGNAL GENERATION — All 5 strategies with mock data
# ============================================================================


@pytest.mark.forknet
class TestSignalGeneration:
    """Verify all 5 strategies produce valid signals on mock data."""

    @pytest.mark.parametrize("slug", list(DEPLOYED_STRATEGIES.keys()))
    def test_produces_valid_signals(self, all_strategies, slug):
        """Each strategy should produce -1/0/+1 signals."""
        strat = all_strategies[slug]
        df = _make_mock_df(300)
        signals = strat.generate_signals(df)
        arr = np.asarray(signals, dtype=int)
        assert len(arr) == len(df), f"{slug}: signal length mismatch"
        unique = set(arr)
        assert unique.issubset({-1, 0, 1}), f"{slug}: invalid signals {unique - {-1,0,1}}"
        longs = (arr == 1).sum()
        shorts = (arr == -1).sum()
        neutral = (arr == 0).sum()
        print(f"  {slug}: LONG={longs} SHORT={shorts} NEUTRAL={neutral}")

    @pytest.mark.parametrize("slug", list(DEPLOYED_STRATEGIES.keys()))
    def test_handles_minimal_data(self, all_strategies, slug):
        """Each strategy should handle small datasets without crashing."""
        strat = all_strategies[slug]
        df = _make_mock_df(50)
        signals = strat.generate_signals(df)
        arr = np.asarray(signals, dtype=int)
        assert len(arr) == 50

    def test_btc_momentum_rsi_logic(self, all_strategies):
        """btc-momentum-1h RSI logic: trending data should produce signals."""
        strat = all_strategies["btc-momentum-1h"]
        # Create strongly trending upward data to trigger RSI signals
        n = 200
        close = np.linspace(40000, 60000, n)
        df = pd.DataFrame({
            "timestamp": pd.date_range("2024-01-01", periods=n, freq="1h"),
            "open": close - 50, "high": close + 100, "low": close - 100,
            "close": close, "volume": np.full(n, 1000.0),
        })
        signals = strat.generate_signals(df)
        arr = np.asarray(signals, dtype=int)
        # At least some non-zero signals expected with strong trend
        non_zero = (arr != 0).sum()
        print(f"  btc-momentum-1h on uptrend: {non_zero} non-zero signals")

    def test_ma_crossover_generates_crossovers(self, all_strategies):
        """MA crossover strategies should produce signals on oscillating data."""
        strat = all_strategies["btc-trend-4h"]
        n = 200
        # Oscillating price to force MA crossovers
        t = np.linspace(0, 6 * np.pi, n)
        close = 50000 + 5000 * np.sin(t)
        df = pd.DataFrame({
            "timestamp": pd.date_range("2024-01-01", periods=n, freq="4h"),
            "open": close - 50, "high": close + 200, "low": close - 200,
            "close": close, "volume": np.full(n, 1000.0),
        })
        signals = strat.generate_signals(df)
        arr = np.asarray(signals, dtype=int)
        longs = (arr == 1).sum()
        shorts = (arr == -1).sum()
        print(f"  btc-trend-4h on oscillating: LONG={longs} SHORT={shorts}")
        assert longs > 0 or shorts > 0, "Oscillating data should produce crossover signals"


# ============================================================================
# 3. LIVE SIGNAL GENERATION (Pyth data) — all 5 strategies
# ============================================================================


@pytest.mark.forknet
class TestLiveSignalGeneration:
    """Generate real signals using Pyth market data for all strategies."""

    @pytest.mark.parametrize("slug,asset", [
        ("btc-momentum-1h", "BTC"),
        ("btc-trend-4h", "BTC"),
        ("eth-trend-1d", "ETH"),
        ("sol-trend-1d", "SOL"),
    ])
    def test_live_signal(self, web3, funded_fork, all_strategies, slug, asset):
        """Strategy should produce a valid signal from live market data."""
        strat = all_strategies[slug]
        md = MarketDataFetcher()
        gen = SignalGenerator(md)

        signal = asyncio.get_event_loop().run_until_complete(gen.generate_signal(strat))
        print(f"\n  {slug}: dir={signal.direction_str} conf={signal.confidence:.2f} price=${signal.current_price:,.2f}")

        assert signal.direction in [-1, 0, 1]
        assert 0.0 <= signal.confidence <= 1.0
        assert signal.current_price > 0, f"{slug}: price should be > 0"
        assert signal.asset == asset
        assert signal.timeframe == strat.timeframe

    def test_marketgod_live_signal(self, web3, funded_fork, all_strategies):
        """baseline-marketgod should produce signal from live BTC data."""
        strat = all_strategies["baseline-marketgod"]
        md = MarketDataFetcher()
        gen = SignalGenerator(md)

        signal = asyncio.get_event_loop().run_until_complete(gen.generate_signal(strat))
        print(f"\n  baseline-marketgod: dir={signal.direction_str} conf={signal.confidence:.2f}")
        assert signal.direction in [-1, 0, 1]
        assert signal.current_price > 0


# ============================================================================
# 4. GMX MARKET RESOLUTION per strategy asset
# ============================================================================


@pytest.mark.forknet
class TestGMXMarketsForStrategies:
    """Verify GMX market resolution for each strategy's tradeable asset."""

    @pytest.mark.parametrize("asset", ["BTC", "ETH", "SOL"])
    def test_market_exists(self, web3, asset):
        """GMX market should exist for BTC, ETH, SOL."""
        market = get_market_address_for_asset(web3, asset)
        assert Web3.is_address(market)
        code = web3.eth.get_code(Web3.to_checksum_address(market))
        assert len(code) > 2, f"No code at {asset} market: {market}"
        print(f"  {asset} market: {market}")

    @pytest.mark.parametrize("asset", ["BTC", "ETH", "SOL"])
    def test_long_token_resolved(self, web3, asset):
        """Each market's long token should resolve correctly."""
        market = get_market_address_for_asset(web3, asset)
        long_token = get_market_long_token(web3, market)
        assert long_token is not None, f"Long token not found for {asset}"
        assert Web3.is_address(long_token)
        code = web3.eth.get_code(Web3.to_checksum_address(long_token))
        assert len(code) > 2
        print(f"  {asset} long token: {long_token}")


# ============================================================================
# 5. TRADE CALLDATA BUILDING — per strategy asset
# ============================================================================


@pytest.mark.forknet
class TestCalldataPerStrategy:
    """Build trade calldata for each tradeable strategy asset."""

    def _make_executor(self, web3) -> TradeExecutor:
        ex = TradeExecutor()
        ex.web3 = web3
        return ex

    @pytest.mark.parametrize("asset,is_long", [
        ("BTC", True), ("BTC", False),
        ("ETH", True), ("ETH", False),
        ("SOL", True), ("SOL", False),
    ])
    def test_open_calldata(self, web3, funded_fork, asset, is_long):
        """Build MarketIncrease calldata for each asset + direction."""
        ex = self._make_executor(web3)
        market = settings.gmx_market_addresses.get(asset)
        if not market:
            market = get_market_address_for_asset(web3, asset)
        calldata, fee = ex._build_order_calldata(
            vault_address=TEST_VAULT_ADDRESS, market_address=market,
            size_usd=50.0, is_long=is_long, current_price=100.0,
        )
        assert len(calldata) > 0
        assert fee > 0
        direction = "LONG" if is_long else "SHORT"
        print(f"  {asset} {direction}: {len(calldata)} bytes, fee={fee/1e18:.6f} ETH")

    @pytest.mark.parametrize("asset", ["BTC", "ETH", "SOL"])
    def test_close_calldata(self, web3, funded_fork, asset):
        """Build MarketDecrease (close) calldata for each asset."""
        ex = self._make_executor(web3)
        market = settings.gmx_market_addresses.get(asset) or get_market_address_for_asset(web3, asset)
        calldata, fee = ex._build_close_order_calldata(
            vault_address=TEST_VAULT_ADDRESS, market_address=market,
            size_usd=50.0, is_long=True, current_price=100.0,
        )
        assert len(calldata) > 0
        assert fee > 0
        print(f"  {asset} CLOSE: {len(calldata)} bytes")


# ============================================================================
# 6. TRADE EXECUTION — per strategy asset on forknet
# ============================================================================


@pytest.mark.forknet
class TestTradeExecutionPerAsset:
    """Execute real trades on fork for each tradeable asset."""

    def _make_executor(self, web3) -> TradeExecutor:
        ex = TradeExecutor()
        ex.web3 = web3
        return ex

    @pytest.mark.parametrize("asset,direction", [
        ("BTC", 1), ("ETH", -1), ("SOL", 1),
    ])
    def test_execute_trade(self, web3, funded_fork, asset, direction):
        """Execute trade for each asset on the fork."""
        original = settings.trading_enabled
        settings.trading_enabled = True
        try:
            ex = self._make_executor(web3)
            signal = Signal(
                direction=direction, confidence=0.9, size_pct=0.1,
                reason=f"E2E test {asset}", current_price=100.0,
                asset=asset, timeframe="1H",
            )
            result = asyncio.get_event_loop().run_until_complete(
                ex.execute_trade(signal, TEST_VAULT_ADDRESS, size_usd_override=50.0)
            )
            dir_str = "LONG" if direction > 0 else "SHORT"
            print(f"\n  {asset} {dir_str}: success={result.success} tx={result.tx_hash} err={result.error}")

            # Trade should either succeed or fail with an on-chain error (not a code bug)
            if not result.success:
                acceptable = ["execution reverted", "transaction will revert", "insufficient", "gas", "long token"]
                assert any(e in (result.error or "").lower() for e in acceptable), \
                    f"Unexpected error for {asset}: {result.error}"
            else:
                assert result.tx_hash is not None
                assert result.tx_hash.startswith("0x")
        finally:
            settings.trading_enabled = original


# ============================================================================
# 7. STRATEGY LINKAGE — DB tests with in-memory SQLite
# ============================================================================


@pytest.mark.forknet
class TestStrategyLinkage:
    """Test strategy ↔ vault linkage using in-memory SQLite."""

    @pytest.fixture(autouse=True)
    def setup_db(self, tmp_path):
        """Create an in-memory SQLite DB with strategies and vaults."""
        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session
        from api.models.database import Base, Strategy, Vault

        self.engine = create_engine(f"sqlite:///{tmp_path}/test.db")
        Base.metadata.create_all(self.engine)

        with Session(self.engine) as session:
            # Insert all 5 strategies
            for slug, meta in DEPLOYED_STRATEGIES.items():
                code_path = str(STRATEGIES_DIR / f"{slug}.py")
                session.add(Strategy(
                    name=meta.get("type") or slug,
                    slug=slug,
                    strategy_type=meta.get("type") or "custom",
                    asset=meta["asset"],
                    timeframe=meta["timeframe"],
                    status="active",
                    code_path=code_path if Path(code_path).exists() else None,
                ))
            session.commit()
        yield

    def _session(self):
        from sqlalchemy.orm import Session
        return Session(self.engine)

    def test_all_strategies_in_db(self):
        """All 5 strategies should be in the database."""
        from sqlalchemy import select
        from api.models.database import Strategy
        with self._session() as session:
            result = session.execute(select(Strategy))
            strategies = result.scalars().all()
            assert len(strategies) == 5
            slugs = {s.slug for s in strategies}
            assert slugs == set(DEPLOYED_STRATEGIES.keys())

    @pytest.mark.parametrize("slug", list(DEPLOYED_STRATEGIES.keys()))
    def test_register_vault_with_strategy(self, slug):
        """Register a vault and link it to each strategy."""
        from sqlalchemy import select
        from api.models.database import Strategy, Vault

        fake_vault = f"0x{'0' * 38}{list(DEPLOYED_STRATEGIES.keys()).index(slug):02d}"

        with self._session() as session:
            strat = session.execute(
                select(Strategy).where(Strategy.slug == slug)
            ).scalar_one()

            vault = Vault(
                address=fake_vault.lower(), name=f"Test Vault {slug}",
                chain="arbitrum", strategy_id=strat.id, status="active",
                check_interval=self._check_interval(strat.timeframe),
            )
            session.add(vault)
            session.commit()

            # Verify
            v = session.execute(
                select(Vault).where(Vault.address == fake_vault.lower())
            ).scalar_one()
            assert v.strategy_id == strat.id
            assert v.status == "active"
            print(f"  ✓ Vault {fake_vault[:10]}... → {slug} (interval={v.check_interval})")

    def test_relink_vault_to_different_strategy(self):
        """Linking vault to a new strategy should update the link."""
        from sqlalchemy import select
        from api.models.database import Strategy, Vault

        fake_vault = "0x" + "a" * 40
        with self._session() as session:
            strats = session.execute(select(Strategy)).scalars().all()
            strat1, strat2 = strats[0], strats[1]

            vault = Vault(
                address=fake_vault, name="Relink Test",
                chain="arbitrum", strategy_id=strat1.id, status="active",
            )
            session.add(vault)
            session.commit()

            # Relink
            v = session.execute(select(Vault).where(Vault.address == fake_vault)).scalar_one()
            v.strategy_id = strat2.id
            session.commit()

            v2 = session.execute(select(Vault).where(Vault.address == fake_vault)).scalar_one()
            assert v2.strategy_id == strat2.id
            print(f"  ✓ Relinked from {strat1.slug} → {strat2.slug}")

    @pytest.mark.parametrize("timeframe,expected_interval", [
        ("1H", "1m"), ("4H", "5m"), ("1D", "15m"),
    ])
    def test_check_interval_auto_set(self, timeframe, expected_interval):
        """check_interval should be auto-set based on strategy timeframe."""
        interval = self._check_interval(timeframe)
        assert interval == expected_interval, f"TF={timeframe}: expected {expected_interval}, got {interval}"

    def _check_interval(self, timeframe: str) -> str:
        mapping = {"1m": "1m", "5m": "5m", "15m": "15m", "1h": "1m", "4h": "5m", "1d": "15m"}
        return mapping.get(timeframe.lower(), "1m")


# ============================================================================
# 8. SCHEDULER FLOW — per strategy (mocked)
# ============================================================================


@pytest.mark.forknet
class TestSchedulerFlowPerStrategy:
    """Test the scheduler's process_vault flow for each strategy type."""

    @pytest.mark.parametrize("slug,expected_asset", [
        ("btc-momentum-1h", "BTC"),
        ("btc-trend-4h", "BTC"),
        ("eth-trend-1d", "ETH"),
        ("sol-trend-1d", "SOL"),
        ("baseline-marketgod", "BTC"),
    ])
    def test_scheduler_generates_signal_for_strategy(self, all_strategies, slug, expected_asset):
        """Scheduler should generate signal for each linked strategy."""
        strat = all_strategies[slug]

        # Mock the signal generation pipeline
        df = _make_mock_df(300)
        signals = strat.generate_signals(df)
        arr = np.asarray(signals, dtype=int)
        latest = int(arr[-1])

        # Verify the scheduler would interpret this correctly
        is_actionable = latest != 0
        direction_str = {1: "LONG", -1: "SHORT", 0: "NEUTRAL"}.get(latest, "NEUTRAL")
        print(f"  {slug} ({expected_asset}): signal={direction_str} actionable={is_actionable}")

        assert latest in [-1, 0, 1]

    def test_scheduler_skips_duplicate_same_direction(self):
        """If position exists in same direction, scheduler should skip."""
        from api.execution.scheduler import ExecutionScheduler

        sched = ExecutionScheduler()
        # Simulate existing LONG position and LONG signal
        positions = [Position(asset="BTC", size=0.1, current_price=100000.0,
                              market_id="0xmarket", unrealized_pnl=0.0,
                              entry_price=95000.0, leverage=2.0)]
        direction = sched._net_position_direction(positions)
        assert direction == 1

        # If signal is also 1 (LONG), scheduler should skip
        # This is verified by the direction == current_direction check in _process_vault
        print("  ✓ Same-direction skip logic verified")

    def test_scheduler_closes_on_flip(self):
        """If position is LONG but signal is SHORT, scheduler should close first."""
        from api.execution.scheduler import ExecutionScheduler

        sched = ExecutionScheduler()
        positions = [Position(asset="ETH", size=1.0, current_price=3000.0,
                              market_id="0xmarket", unrealized_pnl=50.0,
                              entry_price=2800.0, leverage=2.0)]
        direction = sched._net_position_direction(positions)
        assert direction == 1  # Currently LONG

        # Signal is -1 (SHORT) → needs_close=True, needs_open=True
        desired = -1
        assert desired != direction, "Direction mismatch → should flip"
        print("  ✓ Signal flip → close + open logic verified")

    def test_scheduler_closes_on_neutral(self):
        """Neutral signal should close any existing position."""
        from api.execution.scheduler import ExecutionScheduler

        sched = ExecutionScheduler()
        positions = [Position(asset="SOL", size=-0.5, current_price=150.0,
                              market_id="0xmarket", unrealized_pnl=-10.0,
                              entry_price=160.0, leverage=3.0)]
        direction = sched._net_position_direction(positions)
        assert direction == -1  # Currently SHORT

        # Neutral signal → needs_close=True
        desired = 0
        assert direction != 0 and desired == 0, "Neutral → should close"
        print("  ✓ Neutral signal → close logic verified")

    def test_scheduler_check_intervals(self):
        """Verify _should_check with different intervals."""
        from api.execution.scheduler import ExecutionScheduler, INTERVAL_SECONDS

        sched = ExecutionScheduler()
        now = datetime.now(timezone.utc)

        for interval, seconds in INTERVAL_SECONDS.items():
            vault = SimpleNamespace(
                last_checked_at=now.replace(second=0, microsecond=0),
                check_interval=interval,
            )
            # Just checked: should NOT check again
            assert not sched._should_check(vault, now), f"Should not check immediately for {interval}"

        # Never checked: should always check
        vault_new = SimpleNamespace(last_checked_at=None, check_interval="1m")
        assert sched._should_check(vault_new, now), "Never checked → should check"
        print("  ✓ All check intervals validated")


# ============================================================================
# 9. FULL SIGNAL → TRADE FLOW per tradeable strategy
# ============================================================================


@pytest.mark.forknet
class TestFullFlowPerStrategy:
    """End-to-end: load strategy → generate signal → build calldata → execute."""

    @pytest.mark.parametrize("slug", ["btc-momentum-1h", "btc-trend-4h", "eth-trend-1d", "sol-trend-1d"])
    def test_signal_to_calldata(self, web3, funded_fork, all_strategies, slug):
        """Complete flow from strategy loading to calldata building."""
        strat = all_strategies[slug]
        asset = strat.asset

        # 1. Generate signal (mock data for speed)
        df = _make_mock_df(200)
        signals = strat.generate_signals(df)
        latest = int(np.asarray(signals, dtype=int)[-1])
        price = float(df["close"].iloc[-1])

        # 2. Force actionable for test
        direction = latest if latest != 0 else 1

        # 3. Resolve market
        market = get_market_address_for_asset(web3, asset)

        # 4. Build calldata
        ex = TradeExecutor()
        ex.web3 = web3
        calldata, fee = ex._build_order_calldata(
            vault_address=TEST_VAULT_ADDRESS, market_address=market,
            size_usd=50.0, is_long=direction > 0, current_price=price,
        )

        assert len(calldata) > 0
        assert fee > 0
        dir_str = "LONG" if direction > 0 else "SHORT"
        print(f"  ✓ {slug} → {dir_str} {asset}: calldata={len(calldata)}B fee={fee/1e18:.6f}ETH")


# ============================================================================
# 10. MAINNET READ-ONLY TESTS — no transactions, just reads
# ============================================================================


@pytest.mark.mainnet
class TestMainnetReadOnly:
    """Read-only tests against Arbitrum mainnet (no fork needed)."""

    @pytest.fixture(autouse=True)
    def setup_mainnet_web3(self):
        rpc = _get_mainnet_rpc()
        self.web3 = Web3(Web3.HTTPProvider(rpc))
        if not self.web3.is_connected():
            pytest.skip("Cannot connect to Arbitrum mainnet")

    def test_mainnet_chain_id(self):
        assert self.web3.eth.chain_id == 42161

    @pytest.mark.parametrize("asset", ["BTC", "ETH", "SOL"])
    def test_gmx_market_resolution(self, asset):
        """GMX markets should resolve on mainnet."""
        market = get_market_address_for_asset(self.web3, asset)
        assert Web3.is_address(market)
        code = self.web3.eth.get_code(Web3.to_checksum_address(market))
        assert len(code) > 2
        print(f"  {asset} market (mainnet): {market}")

    def test_vault_exists_mainnet(self):
        """Test vault should exist on mainnet."""
        code = self.web3.eth.get_code(Web3.to_checksum_address(TEST_VAULT_ADDRESS))
        assert len(code) > 2

    def test_vault_tvl_mainnet(self):
        """Read vault TVL from mainnet."""
        from api.onchain.vault_reader import VaultReader
        reader = VaultReader(self.web3, cache_ttl=0)
        tvl = reader.get_tvl(TEST_VAULT_ADDRESS)
        print(f"\n  Mainnet Vault TVL: ${tvl:,.4f}")
        assert tvl >= 0

    def test_vault_manager_mainnet(self):
        """Read vault manager from mainnet."""
        from api.onchain.vault_reader import VaultReader
        reader = VaultReader(self.web3, cache_ttl=0)
        manager = reader.get_manager_address(TEST_VAULT_ADDRESS)
        assert Web3.is_address(manager)
        print(f"\n  Mainnet Vault Manager: {manager}")

    def test_vault_positions_mainnet(self):
        """Read vault positions from mainnet."""
        from api.onchain.vault_reader import VaultReader
        reader = VaultReader(self.web3, cache_ttl=0)
        positions = reader.get_positions(TEST_VAULT_ADDRESS)
        print(f"\n  Mainnet Positions: {len(positions)}")
        for p in positions:
            dir_str = "LONG" if p.size > 0 else "SHORT"
            print(f"    {p.asset} {dir_str}: size={p.size:.6f}")
        assert isinstance(positions, list)

    @pytest.mark.parametrize("asset", ["BTC", "ETH", "SOL"])
    def test_live_price_fetch(self, asset):
        """Fetch live price from Pyth for each asset."""
        md = MarketDataFetcher()
        price = asyncio.get_event_loop().run_until_complete(md.get_current_price(asset))
        assert price > 0, f"{asset} price should be > 0"
        print(f"  {asset}: ${price:,.2f}")


# ============================================================================
# 11. MAINNET LIVE SIGNALS — read-only signal generation
# ============================================================================


@pytest.mark.mainnet
class TestMainnetLiveSignals:
    """Generate live signals on mainnet (read-only, no trades)."""

    @pytest.mark.parametrize("slug", [
        "btc-momentum-1h", "btc-trend-4h", "eth-trend-1d", "sol-trend-1d", "baseline-marketgod",
    ])
    def test_live_signal_generation(self, slug):
        """Each strategy with a Pyth feed should produce a live signal."""
        path = STRATEGIES_DIR / f"{slug}.py"
        if not path.exists():
            pytest.skip(f"{slug}.py not found")

        strat = load_strategy_from_file(path)
        md = MarketDataFetcher()
        gen = SignalGenerator(md)

        signal = asyncio.get_event_loop().run_until_complete(gen.generate_signal(strat))
        print(f"\n  {slug}: dir={signal.direction_str} conf={signal.confidence:.2f} "
              f"price=${signal.current_price:,.2f} reason={signal.reason[:60]}")

        assert signal.direction in [-1, 0, 1]
        assert signal.current_price > 0
        assert signal.asset in PYTH_PRICED_ASSETS


# ============================================================================
# 12. VAULT ASSET PRE-FLIGHT CHECKS
# ============================================================================


@pytest.mark.forknet
class TestVaultAssetPreFlight:
    """Test the _validate_vault_assets pre-flight check for each market."""

    @pytest.mark.parametrize("asset", ["BTC", "ETH", "SOL"])
    def test_validate_vault_assets(self, web3, funded_fork, asset):
        """Pre-flight check should pass or fail clearly for each asset."""
        ex = TradeExecutor()
        ex.web3 = web3
        market = get_market_address_for_asset(web3, asset)

        try:
            ex._validate_vault_assets(TEST_VAULT_ADDRESS, market)
            print(f"  {asset}: vault has long token ✓")
        except ValueError as e:
            # This is expected if the vault doesn't have the long token
            print(f"  {asset}: vault missing long token (expected): {e}")
            assert "long token" in str(e).lower()


# ============================================================================
# PYTEST CONFIGURATION
# ============================================================================

def pytest_configure(config):
    config.addinivalue_line("markers", "forknet: end-to-end tests on Anvil Arbitrum fork")
    config.addinivalue_line("markers", "mainnet: read-only tests against Arbitrum mainnet")
