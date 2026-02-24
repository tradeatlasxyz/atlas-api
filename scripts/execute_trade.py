#!/usr/bin/env python3
"""
Execute a real GMX V2 trade through a dHEDGE vault.

Usage:
    python scripts/execute_trade.py --asset BTC --direction long --size 10
    python scripts/execute_trade.py --asset ETH --direction short --size 20
    python scripts/execute_trade.py --dry-run  # Just show what would happen
"""
import argparse
import asyncio
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from web3 import Web3
from api.config import settings
from api.onchain.vault_reader import VaultReader
from api.onchain.wallet import WalletManager
from api.onchain.gmx import get_market_address_for_asset
from api.execution.trade_executor import TradeExecutor
from api.execution.market_data import MarketDataFetcher
from api.execution.models import Signal


async def check_vault(web3, vault_address: str) -> dict:
    """Check vault status and balances."""
    reader = VaultReader(web3)
    
    # ERC20 ABI
    ERC20_ABI = [
        {"inputs": [{"name": "account", "type": "address"}], "name": "balanceOf", 
         "outputs": [{"type": "uint256"}], "stateMutability": "view", "type": "function"},
    ]
    
    state = reader.get_vault_state(vault_address)
    
    # Check USDC
    usdc = web3.eth.contract(
        address=Web3.to_checksum_address(settings.gmx_collateral_token), 
        abi=ERC20_ABI
    )
    usdc_balance = usdc.functions.balanceOf(Web3.to_checksum_address(vault_address)).call()
    
    return {
        "tvl": state.tvl,
        "usdc_balance": usdc_balance / 10**6,
        "manager": state.manager,
    }


async def execute_trade(
    asset: str,
    direction: str,
    size_usd: float,
    vault_address: str,
    dry_run: bool = False,
):
    """Execute a trade on GMX V2 through dHEDGE vault."""
    
    print("=" * 60)
    print(f"  GMX V2 TRADE {'(DRY RUN)' if dry_run else 'EXECUTION'}")
    print("=" * 60)
    print()
    
    # 1. Setup
    web3 = Web3(Web3.HTTPProvider(settings.arbitrum_rpc_url))
    wallet = WalletManager(web3=web3)
    
    print(f"Network: Arbitrum (Chain ID: {web3.eth.chain_id})")
    print(f"Trader: {wallet.address}")
    print(f"Vault: {vault_address}")
    print()
    
    # 2. Check vault
    print("Checking vault...")
    vault_info = await check_vault(web3, vault_address)
    print(f"  TVL: ${vault_info['tvl']:,.2f}")
    print(f"  USDC: ${vault_info['usdc_balance']:,.2f}")
    print()
    
    # 3. Check authorization
    if not wallet.is_trader(vault_address):
        print("❌ ERROR: Wallet is not authorized to trade for this vault")
        return False
    print("✅ Wallet authorized")
    print()
    
    # 4. Get market price
    print(f"Fetching {asset} price...")
    market_data = MarketDataFetcher()
    current_price = await market_data.get_current_price(asset)
    print(f"  {asset} Price: ${current_price:,.2f}")
    print()
    
    # 5. Build signal
    is_long = direction.lower() == "long"
    signal = Signal(
        direction=1 if is_long else -1,
        confidence=0.9,
        size_pct=size_usd / max(vault_info['tvl'], 1),
        reason=f"Manual {direction.upper()} order",
        current_price=current_price,
        asset=asset,
        timeframe="1H",
    )
    
    print(f"Trade Details:")
    print(f"  Asset: {asset}")
    print(f"  Direction: {signal.direction_str}")
    print(f"  Size: ${size_usd:.2f}")
    print(f"  Leverage: {settings.gmx_default_leverage}x")
    print(f"  Collateral: ${size_usd / settings.gmx_default_leverage:.2f} USDC")
    print()
    
    # 6. Check if vault has enough funds
    required_collateral = size_usd / settings.gmx_default_leverage
    if vault_info['usdc_balance'] < required_collateral:
        print(f"❌ ERROR: Insufficient USDC in vault")
        print(f"   Need: ${required_collateral:.2f}")
        print(f"   Have: ${vault_info['usdc_balance']:.2f}")
        return False
    
    # 7. Check trader ETH balance
    trader_balance = web3.eth.get_balance(wallet.address)
    exec_fee = settings.gmx_execution_fee_wei
    if trader_balance < exec_fee:
        print(f"❌ ERROR: Insufficient ETH for execution fee")
        print(f"   Need: {exec_fee / 10**18:.6f} ETH")
        print(f"   Have: {trader_balance / 10**18:.6f} ETH")
        return False
    
    print(f"✅ Funds sufficient")
    print()
    
    if dry_run:
        print("=" * 60)
        print("  DRY RUN - Trade NOT executed")
        print("=" * 60)
        print()
        print("To execute for real, run without --dry-run flag")
        return True
    
    # 8. Execute trade
    print("Executing trade...")
    print("(This may take up to 60 seconds for confirmation)")
    print()
    
    executor = TradeExecutor()
    
    # Patch to print tx hash immediately
    original_execute = executor._execute_via_vault
    async def patched_execute(*args, **kwargs):
        tx_hash = await original_execute(*args, **kwargs)
        print(f"📤 TX Submitted: {tx_hash}")
        print(f"   View on Arbiscan: https://arbiscan.io/tx/{tx_hash}")
        print("   Waiting for confirmation...")
        return tx_hash
    executor._execute_via_vault = patched_execute
    
    result = await executor.execute_trade(signal, vault_address)
    
    if result.success:
        print("=" * 60)
        print("  ✅ TRADE EXECUTED SUCCESSFULLY")
        print("=" * 60)
        print(f"  TX Hash: {result.tx_hash}")
        print(f"  Gas Used: {result.gas_used}")
        print(f"  Direction: {signal.direction_str}")
        print(f"  Size: ${result.size:.2f}")
        print(f"  Entry Price: ${result.entry_price:,.2f}")
    else:
        print("=" * 60)
        print("  ❌ TRADE FAILED")
        print("=" * 60)
        print(f"  Error: {result.error}")
    
    return result.success


def main():
    parser = argparse.ArgumentParser(description="Execute GMX V2 trade")
    parser.add_argument("--asset", type=str, default="BTC", choices=["BTC", "ETH", "SOL"],
                        help="Asset to trade")
    parser.add_argument("--direction", type=str, default="long", choices=["long", "short"],
                        help="Trade direction")
    parser.add_argument("--size", type=float, default=10.0,
                        help="Position size in USD")
    parser.add_argument("--vault", type=str, default=None,
                        help="Vault address (defaults to TESTNET_VAULT_ADDRESS)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would happen without executing")
    
    args = parser.parse_args()
    
    vault = args.vault or os.getenv("TESTNET_VAULT_ADDRESS")
    if not vault:
        print("ERROR: No vault address. Set TESTNET_VAULT_ADDRESS or use --vault")
        sys.exit(1)
    
    if not settings.trading_enabled and not args.dry_run:
        print("ERROR: Trading is disabled. Set TRADING_ENABLED=true in .env")
        sys.exit(1)
    
    success = asyncio.run(execute_trade(
        asset=args.asset,
        direction=args.direction,
        size_usd=args.size,
        vault_address=vault,
        dry_run=args.dry_run,
    ))
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
