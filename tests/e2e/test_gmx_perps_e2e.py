"""End-to-end tests for GMX V2 perpetuals integration.

These tests verify the GMX V2 integration on Arbitrum mainnet.
Run with: pytest tests/e2e/test_gmx_perps_e2e.py -m e2e -v

Components tested:
1. GMX Market Resolution - Resolve asset symbols to GMX market addresses
2. Vault Reader - Read dHEDGE vault state (TVL, positions)
3. Trade Executor - Build and validate GMX order calldata
4. Position Tracking - Read open positions from GMX

Environment variables needed:
- ARBITRUM_RPC_URL: Arbitrum mainnet RPC (required)
- TESTNET_VAULT_ADDRESS: A real dHEDGE vault address for testing (optional)
"""
import os

import pytest
from web3 import Web3

from api.config import settings
from api.onchain.gmx import (
    resolve_market_addresses,
    get_market_address_for_asset,
    get_symbol_for_market,
)
from api.onchain.vault_reader import VaultReader
from api.execution.trade_executor import TradeExecutor
from api.execution.models import Signal


def get_web3():
    """Get Web3 instance connected to Arbitrum."""
    rpc = os.getenv("ARBITRUM_RPC_URL") or settings.arbitrum_rpc_url
    if not rpc:
        pytest.skip("ARBITRUM_RPC_URL required")
    return Web3(Web3.HTTPProvider(rpc))


# =============================================================================
# 1. GMX MARKET RESOLUTION TESTS
# =============================================================================

@pytest.mark.e2e
def test_gmx_resolve_markets_from_chain():
    """Verify we can resolve GMX V2 markets from on-chain Reader contract."""
    web3 = get_web3()

    symbol_to_market, market_to_symbol = resolve_market_addresses(
        web3=web3,
        reader_address=settings.gmx_reader,
        data_store_address=settings.gmx_data_store,
    )

    # Should have found some markets
    assert len(symbol_to_market) > 0, "Expected to find GMX markets"
    assert len(market_to_symbol) > 0, "Expected market reverse mapping"

    # Print discovered markets
    print(f"\n=== GMX V2 Markets Discovered ({len(symbol_to_market)}) ===")
    for symbol, market in sorted(symbol_to_market.items()):
        print(f"  {symbol}: {market}")


@pytest.mark.e2e
def test_gmx_get_market_address_for_btc():
    """Verify we can get BTC market address."""
    web3 = get_web3()

    market = get_market_address_for_asset(web3, "BTC")
    assert market.startswith("0x")
    assert len(market) == 42
    print(f"\nBTC Market Address: {market}")


@pytest.mark.e2e
def test_gmx_get_market_address_for_eth():
    """Verify we can get ETH market address."""
    web3 = get_web3()

    market = get_market_address_for_asset(web3, "ETH")
    assert market.startswith("0x")
    assert len(market) == 42
    print(f"\nETH Market Address: {market}")


@pytest.mark.e2e
def test_gmx_get_market_address_for_sol():
    """Verify we can get SOL market address."""
    web3 = get_web3()

    market = get_market_address_for_asset(web3, "SOL")
    assert market.startswith("0x")
    assert len(market) == 42
    print(f"\nSOL Market Address: {market}")


@pytest.mark.e2e
def test_gmx_reverse_lookup_market_to_symbol():
    """Verify we can reverse lookup market address to symbol."""
    web3 = get_web3()

    # Get BTC market address
    btc_market = settings.gmx_market_addresses.get("BTC")
    if not btc_market:
        pytest.skip("BTC market address not configured")

    symbol = get_symbol_for_market(web3, btc_market)
    assert symbol == "BTC"


@pytest.mark.e2e
def test_gmx_all_configured_markets_valid():
    """Verify all configured market addresses are valid on-chain."""
    web3 = get_web3()

    configured = settings.gmx_market_addresses
    if not configured:
        pytest.skip("No GMX market addresses configured")

    print(f"\n=== Validating {len(configured)} Configured Markets ===")
    for asset, address in configured.items():
        # Verify address is valid
        assert Web3.is_address(address), f"Invalid address for {asset}: {address}"

        # Verify reverse lookup works
        resolved_symbol = get_symbol_for_market(web3, address)
        print(f"  {asset}: {address} -> {resolved_symbol}")


# =============================================================================
# 2. VAULT READER TESTS
# =============================================================================

@pytest.mark.e2e
def test_vault_reader_initialization():
    """Verify VaultReader initializes correctly."""
    web3 = get_web3()
    reader = VaultReader(web3, cache_ttl=60)

    assert reader.web3 is not None
    assert reader.cache_ttl == 60
    assert reader.max_retries == 2


@pytest.mark.e2e
def test_vault_reader_with_real_vault():
    """Test VaultReader against a real dHEDGE vault."""
    web3 = get_web3()
    vault_address = os.getenv("TESTNET_VAULT_ADDRESS")
    if not vault_address:
        pytest.skip("TESTNET_VAULT_ADDRESS required")

    reader = VaultReader(web3)
    state = reader.get_vault_state(vault_address)

    print(f"\n=== Vault State: {vault_address[:10]}... ===")
    print(f"  TVL: ${state.tvl:,.2f}")
    print(f"  Share Price: ${state.share_price:.4f}")
    print(f"  Total Supply: {state.total_supply:,.2f}")
    print(f"  Manager: {state.manager}")

    # Basic validation
    assert state.tvl >= 0
    assert state.share_price >= 0
    assert state.total_supply >= 0
    assert state.manager.startswith("0x")


@pytest.mark.e2e
def test_vault_reader_get_positions():
    """Test reading GMX positions from a vault."""
    web3 = get_web3()
    vault_address = os.getenv("TESTNET_VAULT_ADDRESS")
    if not vault_address:
        pytest.skip("TESTNET_VAULT_ADDRESS required")

    reader = VaultReader(web3)
    positions = reader.get_positions(vault_address)

    print(f"\n=== Vault Positions: {vault_address[:10]}... ===")
    if not positions:
        print("  No open positions")
    else:
        for pos in positions:
            print(f"  {pos.asset}: size={pos.size:.4f}, pnl=${pos.unrealized_pnl:.2f}")

    # Positions should be a list
    assert isinstance(positions, list)


@pytest.mark.e2e
def test_vault_reader_caching():
    """Verify VaultReader caching works correctly."""
    web3 = get_web3()
    vault_address = os.getenv("TESTNET_VAULT_ADDRESS")
    if not vault_address:
        pytest.skip("TESTNET_VAULT_ADDRESS required")

    reader = VaultReader(web3, cache_ttl=300)

    # First call - should hit RPC
    tvl1 = reader.get_tvl(vault_address)

    # Second call - should hit cache
    tvl2 = reader.get_tvl(vault_address)

    # Values should be identical (from cache)
    assert tvl1 == tvl2

    # Verify cache was populated
    cache_key = f"{vault_address.lower()}:tvl"
    assert cache_key in reader._cache


@pytest.mark.e2e
def test_vault_reader_invalid_address():
    """Verify VaultReader rejects invalid addresses."""
    web3 = get_web3()
    reader = VaultReader(web3)

    with pytest.raises(ValueError, match="Invalid vault address"):
        reader.get_tvl("not-an-address")


# =============================================================================
# 3. TRADE EXECUTOR TESTS (No actual trading)
# =============================================================================

@pytest.mark.e2e
def test_trade_executor_initialization():
    """Verify TradeExecutor initializes correctly."""
    # Should not throw even without private key
    executor = TradeExecutor()

    assert executor.web3 is not None
    assert executor.PRICE_SCALE == 10**30
    assert executor.USDC_DECIMALS == 10**6


@pytest.mark.e2e
def test_trade_executor_build_order_calldata():
    """Test building GMX V2 order calldata without executing."""
    executor = TradeExecutor()

    # Use a test execution fee if not configured
    original_fee = settings.gmx_execution_fee_wei
    if settings.gmx_execution_fee_wei <= 0:
        # Set a test execution fee (0.0001 ETH)
        settings.gmx_execution_fee_wei = 100000000000000

    try:
        calldata, execution_fee = executor._build_order_calldata(
            vault_address="0x0000000000000000000000000000000000000001",
            market_address=settings.gmx_market_addresses.get("BTC", "0x47c031236e19d024b42f8AE6780E44A573170703"),
            size_usd=1000.0,
            is_long=True,
            current_price=100000.0,
        )

        assert isinstance(calldata, bytes)
        assert len(calldata) > 0
        assert execution_fee > 0

        print(f"\n=== Order Calldata Built ===")
        print(f"  Calldata length: {len(calldata)} bytes")
        print(f"  Execution fee: {execution_fee} wei ({execution_fee / 10**18:.6f} ETH)")
    finally:
        settings.gmx_execution_fee_wei = original_fee


@pytest.mark.e2e
def test_trade_executor_calculate_size():
    """Test trade size calculation."""
    executor = TradeExecutor()

    # Mock vault TVL
    class MockExecutor(TradeExecutor):
        def _get_vault_tvl(self, vault_address: str) -> float:
            return 10000.0  # $10k TVL

    mock_executor = MockExecutor()
    size = mock_executor._calculate_size_usd(
        asset="BTC",
        size_pct=0.1,  # 10% of TVL
        current_price=100000.0,
        vault_address="0x0001",
    )

    assert size == 1000.0  # 10% of $10k = $1000
    print(f"\n=== Size Calculation ===")
    print(f"  TVL: $10,000")
    print(f"  Size %: 10%")
    print(f"  Size USD: ${size:,.2f}")


@pytest.mark.e2e
def test_trade_executor_not_actionable_signal():
    """Test that non-actionable signals don't execute."""
    import asyncio

    executor = TradeExecutor()
    signal = Signal(
        direction=0,  # NEUTRAL
        confidence=0.5,
        size_pct=0.0,
        reason="Test neutral signal",
        current_price=100000.0,
        asset="BTC",
        timeframe="1H",
    )

    result = asyncio.run(executor.execute_trade(signal, "0x0001"))

    assert result.success is True
    assert result.error == "Signal not actionable"
    assert result.tx_hash is None


@pytest.mark.e2e
def test_trade_executor_trading_disabled():
    """Test that trading disabled returns appropriate error."""
    import asyncio

    # Ensure trading is disabled
    original = settings.trading_enabled
    settings.trading_enabled = False

    try:
        executor = TradeExecutor()
        signal = Signal(
            direction=1,  # LONG
            confidence=0.9,
            size_pct=0.1,
            reason="Test long signal",
            current_price=100000.0,
            asset="BTC",
            timeframe="1H",
        )

        result = asyncio.run(executor.execute_trade(signal, "0x0001"))

        assert result.success is False
        assert result.error == "Trading disabled"
    finally:
        settings.trading_enabled = original


# =============================================================================
# 4. FULL FLOW VALIDATION (No actual trading)
# =============================================================================

@pytest.mark.e2e
def test_full_signal_to_order_flow():
    """Test the complete flow from signal to order calldata without executing."""
    web3 = get_web3()

    # Use a test execution fee if not configured
    original_fee = settings.gmx_execution_fee_wei
    if settings.gmx_execution_fee_wei <= 0:
        settings.gmx_execution_fee_wei = 100000000000000

    try:
        # 1. Create a signal
        signal = Signal(
            direction=1,
            confidence=0.85,
            size_pct=0.1,
            reason="BTC momentum signal",
            current_price=100000.0,
            stop_loss=98000.0,
            take_profit=105000.0,
            asset="BTC",
            timeframe="1H",
            strategy_slug="btc-momentum-1h",
        )
        print(f"\n=== Signal Created ===")
        print(f"  Direction: {signal.direction_str}")
        print(f"  Asset: {signal.asset}")
        print(f"  Confidence: {signal.confidence:.0%}")
        print(f"  Price: ${signal.current_price:,.2f}")

        # 2. Resolve market
        market = get_market_address_for_asset(web3, signal.asset)
        print(f"\n=== Market Resolved ===")
        print(f"  {signal.asset} -> {market}")

        # 3. Build order calldata
        executor = TradeExecutor()
        calldata, fee = executor._build_order_calldata(
            vault_address="0x0000000000000000000000000000000000000001",
            market_address=market,
            size_usd=1000.0,
            is_long=signal.direction > 0,
            current_price=signal.current_price,
        )
        print(f"\n=== Order Calldata Built ===")
        print(f"  Calldata: {len(calldata)} bytes")
        print(f"  Fee: {fee} wei ({fee / 10**18:.6f} ETH)")

        # Verify all components worked
        assert signal.is_actionable
        assert Web3.is_address(market)
        assert len(calldata) > 0
        assert fee > 0
    finally:
        settings.gmx_execution_fee_wei = original_fee


@pytest.mark.e2e
def test_gmx_contract_addresses_valid():
    """Verify all GMX contract addresses in settings are valid."""
    print("\n=== GMX Contract Addresses ===")

    contracts = {
        "Exchange Router": settings.gmx_exchange_router,
        "Data Store": settings.gmx_data_store,
        "Order Vault": settings.gmx_order_vault,
        "Reader": settings.gmx_reader,
        "Callback Contract": settings.gmx_callback_contract,
        "Collateral Token (USDC)": settings.gmx_collateral_token,
    }

    for name, address in contracts.items():
        if address:
            assert Web3.is_address(address), f"Invalid {name}: {address}"
            print(f"  {name}: {address} ✓")
        else:
            print(f"  {name}: NOT CONFIGURED")


@pytest.mark.e2e
def test_gmx_settings_summary():
    """Print a summary of all GMX-related settings."""
    print("\n=== GMX Settings Summary ===")
    print(f"  Trading Enabled: {settings.trading_enabled}")
    print(f"  Default Leverage: {settings.gmx_default_leverage}x")
    print(f"  Slippage: {settings.gmx_slippage_bps} bps ({settings.gmx_slippage_bps / 100:.2f}%)")
    print(f"  Execution Fee: {settings.gmx_execution_fee_wei} wei")
    print(f"  RPC URL: {'Configured' if settings.arbitrum_rpc_url else 'NOT CONFIGURED'}")
    print(f"  Trader Key: {'Configured' if settings.trader_private_key else 'NOT CONFIGURED'}")

    print(f"\n  Configured Markets: {len(settings.gmx_market_addresses)}")
    for asset, addr in settings.gmx_market_addresses.items():
        print(f"    {asset}: {addr}")


# =============================================================================
# 5. WALLET MANAGER TESTS (Using configured TRADER_PRIVATE_KEY)
# =============================================================================

@pytest.mark.e2e
def test_wallet_manager_initialization():
    """Test WalletManager initializes with configured private key."""
    from api.onchain.wallet import WalletManager

    if not settings.trader_private_key:
        pytest.skip("TRADER_PRIVATE_KEY not configured")

    web3 = get_web3()
    wallet = WalletManager(web3=web3)

    assert wallet.address.startswith("0x")
    assert len(wallet.address) == 42
    print(f"\n=== Wallet Manager ===")
    print(f"  Address: {wallet.address}")


@pytest.mark.e2e
def test_wallet_balance():
    """Test we can read wallet ETH balance."""
    from api.onchain.wallet import WalletManager

    if not settings.trader_private_key:
        pytest.skip("TRADER_PRIVATE_KEY not configured")

    web3 = get_web3()
    wallet = WalletManager(web3=web3)

    balance_wei = web3.eth.get_balance(wallet.address)
    balance_eth = balance_wei / 10**18

    print(f"\n=== Wallet Balance ===")
    print(f"  Address: {wallet.address}")
    print(f"  Balance: {balance_eth:.6f} ETH")
    print(f"  Balance: {balance_wei} wei")

    assert balance_wei >= 0


@pytest.mark.e2e
def test_wallet_sign_transaction():
    """Test wallet can sign transactions."""
    from api.onchain.wallet import WalletManager

    if not settings.trader_private_key:
        pytest.skip("TRADER_PRIVATE_KEY not configured")

    web3 = get_web3()
    wallet = WalletManager(web3=web3)

    # Create a dummy transaction (won't broadcast)
    tx = {
        "to": wallet.address,
        "value": 0,
        "gas": 21000,
        "gasPrice": web3.eth.gas_price,
        "nonce": web3.eth.get_transaction_count(wallet.address),
        "chainId": 42161,  # Arbitrum
    }

    signed = wallet.sign_transaction(tx)

    assert signed.raw_transaction is not None
    assert len(signed.raw_transaction) > 0
    assert signed.hash.startswith("0x")

    print(f"\n=== Transaction Signed ===")
    print(f"  TX Hash: {signed.hash}")
    print(f"  Raw TX Length: {len(signed.raw_transaction)} bytes")


@pytest.mark.e2e
def test_trade_executor_with_trader_key():
    """Test TradeExecutor initializes with trader key."""
    if not settings.trader_private_key:
        pytest.skip("TRADER_PRIVATE_KEY not configured")

    executor = TradeExecutor()

    assert executor.trader is not None
    assert executor.trader.address.startswith("0x")

    print(f"\n=== Trade Executor ===")
    print(f"  Trader Address: {executor.trader.address}")
    print(f"  Web3 Connected: {executor.web3.is_connected()}")


@pytest.mark.e2e
def test_complete_trade_flow_simulation():
    """Simulate complete trade flow without actually executing."""
    import asyncio
    from api.onchain.wallet import WalletManager

    if not settings.trader_private_key:
        pytest.skip("TRADER_PRIVATE_KEY not configured")

    web3 = get_web3()
    wallet = WalletManager(web3=web3)

    # Use a test execution fee
    original_fee = settings.gmx_execution_fee_wei
    original_trading = settings.trading_enabled
    settings.gmx_execution_fee_wei = 100000000000000  # 0.0001 ETH

    # Disable actual trading for safety
    settings.trading_enabled = False

    try:
        print(f"\n=== Complete Trade Flow Simulation ===")
        print(f"  Trader: {wallet.address}")

        # 1. Check wallet balance
        balance = web3.eth.get_balance(wallet.address)
        print(f"  Balance: {balance / 10**18:.6f} ETH")

        # 2. Create signal
        signal = Signal(
            direction=1,
            confidence=0.9,
            size_pct=0.1,
            reason="E2E test signal",
            current_price=100000.0,
            asset="BTC",
            timeframe="1H",
        )
        print(f"  Signal: {signal.direction_str} {signal.asset}")

        # 3. Resolve market
        market = get_market_address_for_asset(web3, signal.asset)
        print(f"  Market: {market}")

        # 4. Build order
        executor = TradeExecutor()
        calldata, fee = executor._build_order_calldata(
            vault_address="0x0000000000000000000000000000000000000001",
            market_address=market,
            size_usd=100.0,  # Small test size
            is_long=True,
            current_price=signal.current_price,
        )
        print(f"  Order Calldata: {len(calldata)} bytes")
        print(f"  Execution Fee: {fee / 10**18:.6f} ETH")

        # 5. Attempt execute (will fail because trading disabled)
        result = asyncio.run(executor.execute_trade(signal, "0x0001"))
        print(f"  Execute Result: {result.error}")

        assert result.success is False
        assert result.error == "Trading disabled"
        print(f"\n  ✓ Flow completed successfully (trading disabled for safety)")

    finally:
        settings.gmx_execution_fee_wei = original_fee
        settings.trading_enabled = original_trading


@pytest.mark.e2e
def test_all_markets_order_calldata():
    """Test building order calldata for all configured markets."""
    web3 = get_web3()

    original_fee = settings.gmx_execution_fee_wei
    if settings.gmx_execution_fee_wei <= 0:
        settings.gmx_execution_fee_wei = 100000000000000

    try:
        executor = TradeExecutor()

        print(f"\n=== Order Calldata for All Markets ===")
        for asset, market_addr in settings.gmx_market_addresses.items():
            try:
                calldata, fee = executor._build_order_calldata(
                    vault_address="0x0000000000000000000000000000000000000001",
                    market_address=market_addr,
                    size_usd=100.0,
                    is_long=True,
                    current_price=100.0,
                )
                print(f"  {asset}: {len(calldata)} bytes, fee={fee / 10**18:.6f} ETH ✓")
                assert len(calldata) > 0
            except Exception as e:
                print(f"  {asset}: FAILED - {e}")
                raise

    finally:
        settings.gmx_execution_fee_wei = original_fee
