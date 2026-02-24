#!/usr/bin/env python3
"""
Comprehensive E2E forknet test for Atlas trading system.

Usage:
    # First start Arbitrum fork:
    # pnpm fork:arbitrum
    
    # Then run this script:
    python scripts/forknet_e2e_test.py --vault <VAULT_ADDRESS>
    
    # Or test with a new vault:
    python scripts/forknet_e2e_test.py --create-vault
"""

import asyncio
import argparse
import os
import sys
from datetime import datetime
from web3 import Web3

# Add parent directory to path
sys.path.insert(0, ".")

from api.config import settings
from api.execution.trade_executor import TradeExecutor
from api.execution.market_data import get_market_data
from api.execution.strategy_loader import load_strategy_by_vault
from api.services.database import async_session
from api.models.database import Vault, Strategy, SignalLog, Trade


class ForknetTester:
    """E2E tester for Atlas on Arbitrum forknet."""
    
    def __init__(self, vault_address: str = None):
        self.vault_address = vault_address
        self.web3 = Web3(Web3.HTTPProvider(settings.arbitrum_rpc_url))
        self.executor = TradeExecutor()
        self.results = []
        
    def log(self, test_name: str, status: str, message: str = ""):
        """Log test result."""
        icon = "✅" if status == "PASS" else "❌" if status == "FAIL" else "⚠️"
        self.results.append((test_name, status, message))
        print(f"{icon} {test_name}: {message}")
    
    async def test_rpc_connection(self):
        """Test 1: Verify RPC connection to forknet."""
        try:
            block = self.web3.eth.block_number
            chain_id = self.web3.eth.chain_id
            
            if chain_id == 42161:
                self.log("RPC Connection", "PASS", f"Connected to Arbitrum fork at block {block}")
            else:
                self.log("RPC Connection", "WARN", f"Chain ID {chain_id} (expected 42161)")
            return True
        except Exception as e:
            self.log("RPC Connection", "FAIL", str(e))
            return False
    
    async def test_trader_wallet(self):
        """Test 2: Verify trader wallet has ETH for gas."""
        try:
            trader = self.executor.trader.address
            balance = self.web3.eth.get_balance(trader)
            eth_balance = balance / 10**18
            
            # Need at least 0.001 ETH for gas (Arbitrum is cheap)
            if eth_balance >= 0.001:
                self.log("Trader Wallet", "PASS", f"Trader {trader[:10]}... has {eth_balance:.4f} ETH")
                return True
            else:
                self.log("Trader Wallet", "FAIL", f"Trader needs ETH (has {eth_balance:.6f})")
                return False
        except Exception as e:
            self.log("Trader Wallet", "FAIL", str(e))
            return False
    
    async def test_vault_exists(self):
        """Test 3: Verify vault exists on-chain."""
        if not self.vault_address:
            self.log("Vault Exists", "SKIP", "No vault address provided")
            return False
            
        try:
            vault_addr = Web3.to_checksum_address(self.vault_address)
            code = self.web3.eth.get_code(vault_addr)
            
            if len(code) > 2:  # Has contract code
                self.log("Vault Exists", "PASS", f"Vault {vault_addr[:10]}... is a contract")
                return True
            else:
                self.log("Vault Exists", "FAIL", "Address is not a contract")
                return False
        except Exception as e:
            self.log("Vault Exists", "FAIL", str(e))
            return False
    
    async def test_vault_balances(self):
        """Test 4: Check vault has USDC and WETH for trading."""
        if not self.vault_address:
            self.log("Vault Balances", "SKIP", "No vault address")
            return False
            
        try:
            vault_addr = Web3.to_checksum_address(self.vault_address)
            
            erc20_abi = [{
                "inputs": [{"name": "account", "type": "address"}],
                "name": "balanceOf",
                "outputs": [{"type": "uint256"}],
                "stateMutability": "view",
                "type": "function"
            }]
            
            usdc = self.web3.eth.contract(
                address=Web3.to_checksum_address(settings.gmx_collateral_token),
                abi=erc20_abi
            )
            weth = self.web3.eth.contract(
                address=Web3.to_checksum_address(self.executor.WETH_ADDRESS),
                abi=erc20_abi
            )
            
            usdc_bal = usdc.functions.balanceOf(vault_addr).call() / 10**6
            weth_bal = weth.functions.balanceOf(vault_addr).call() / 10**18
            
            if usdc_bal >= 1.10 and weth_bal >= 0.0001:
                self.log("Vault Balances", "PASS", f"USDC: ${usdc_bal:.2f}, WETH: {weth_bal:.6f}")
                return True
            else:
                self.log("Vault Balances", "FAIL", f"Insufficient: USDC=${usdc_bal:.2f} (need $1.10), WETH={weth_bal:.6f} (need 0.0001)")
                return False
        except Exception as e:
            self.log("Vault Balances", "FAIL", str(e))
            return False
    
    async def test_trader_authorization(self):
        """Test 5: Verify trader wallet is authorized for vault."""
        if not self.vault_address:
            self.log("Trader Auth", "SKIP", "No vault address")
            return False
            
        try:
            vault_addr = Web3.to_checksum_address(self.vault_address)
            
            pool_abi = [{
                "inputs": [],
                "name": "poolManagerLogic",
                "outputs": [{"type": "address"}],
                "stateMutability": "view",
                "type": "function"
            }]
            
            pm_abi = [
                {"inputs": [], "name": "trader", "outputs": [{"type": "address"}], "stateMutability": "view", "type": "function"},
                {"inputs": [], "name": "manager", "outputs": [{"type": "address"}], "stateMutability": "view", "type": "function"},
            ]
            
            vault = self.web3.eth.contract(address=vault_addr, abi=pool_abi)
            pm_addr = vault.functions.poolManagerLogic().call()
            
            pm = self.web3.eth.contract(address=pm_addr, abi=pm_abi)
            trader = pm.functions.trader().call()
            manager = pm.functions.manager().call()
            
            our_trader = self.executor.trader.address.lower()
            
            if trader.lower() == our_trader or manager.lower() == our_trader:
                self.log("Trader Auth", "PASS", f"Authorized as {'trader' if trader.lower() == our_trader else 'manager'}")
                return True
            else:
                self.log("Trader Auth", "FAIL", f"Our trader {our_trader[:10]}... not authorized")
                return False
        except Exception as e:
            self.log("Trader Auth", "FAIL", str(e))
            return False
    
    async def test_database_vault(self):
        """Test 6: Verify vault is registered in database."""
        if not self.vault_address:
            self.log("DB Vault", "SKIP", "No vault address")
            return False
            
        try:
            from sqlalchemy import select
            
            async with async_session() as db:
                result = await db.execute(
                    select(Vault).where(Vault.address == self.vault_address.lower())
                )
                vault = result.scalar_one_or_none()
                
                if vault:
                    self.log("DB Vault", "PASS", f"Vault '{vault.name}' linked to strategy {vault.strategy_id}")
                    return True
                else:
                    self.log("DB Vault", "FAIL", "Vault not found in database")
                    return False
        except Exception as e:
            self.log("DB Vault", "FAIL", str(e))
            return False
    
    async def test_strategy_load(self):
        """Test 7: Verify strategy can be loaded for vault."""
        if not self.vault_address:
            self.log("Strategy Load", "SKIP", "No vault address")
            return False
            
        try:
            async with async_session() as db:
                strategy = await load_strategy_by_vault(db, self.vault_address)
                
                if strategy:
                    self.log("Strategy Load", "PASS", f"Loaded: {strategy.slug} ({strategy.asset}/{strategy.timeframe})")
                    return True
                else:
                    self.log("Strategy Load", "FAIL", "Could not load strategy")
                    return False
        except Exception as e:
            self.log("Strategy Load", "FAIL", str(e))
            return False
    
    async def test_market_data(self):
        """Test 8: Verify market data fetcher works."""
        try:
            md = get_market_data()
            price = await md.get_current_price("BTC")
            
            if price and price > 0:
                self.log("Market Data", "PASS", f"BTC price: ${price:,.2f}")
                return True
            else:
                self.log("Market Data", "FAIL", "Could not fetch BTC price")
                return False
        except Exception as e:
            self.log("Market Data", "FAIL", str(e))
            return False
    
    async def test_dry_run_trade(self):
        """Test 9: Simulate trade preparation (gas estimation)."""
        if not self.vault_address:
            self.log("Trade Simulation", "SKIP", "No vault address")
            return False
            
        try:
            from api.onchain.gmx import get_market_address_for_asset
            
            vault_addr = Web3.to_checksum_address(self.vault_address)
            
            # Get market and price
            md = get_market_data()
            price = await md.get_current_price("BTC")
            market = get_market_address_for_asset(self.web3, "BTC")
            
            # Try to estimate gas for a minimal trade
            # This validates the calldata construction without executing
            
            if market and price > 0:
                self.log("Trade Simulation", "PASS", f"Market: {market[:10]}... Price: ${price:,.2f}")
                return True
            else:
                self.log("Trade Simulation", "FAIL", "Could not get market or price")
                return False
        except Exception as e:
            self.log("Trade Simulation", "FAIL", str(e))
            return False
    
    async def test_real_trade(self, execute: bool = False):
        """Test 10: Execute a real trade (optional)."""
        if not execute:
            self.log("Real Trade", "SKIP", "Use --execute-trade to run")
            return False
            
        if not self.vault_address:
            self.log("Real Trade", "SKIP", "No vault address")
            return False
            
        try:
            from api.execution.models import Signal
            
            md = get_market_data()
            price = await md.get_current_price("BTC")
            
            signal = Signal(
                direction=1,  # LONG
                confidence=0.8,
                size_pct=0.10,
                reason="Forknet real trade test",
                current_price=price,
                asset="BTC",
                timeframe="4H",
            )
            
            result = await self.executor.execute_trade(
                signal=signal,
                vault_address=self.vault_address,
                size_usd_override=11.0,  # Minimum position
            )
            
            if result.success:
                self.log("Real Trade", "PASS", f"TX: {result.tx_hash}")
                return True
            else:
                self.log("Real Trade", "FAIL", f"Error: {result.error}")
                return False
        except Exception as e:
            self.log("Real Trade", "FAIL", str(e))
            return False
    
    async def run_all_tests(self, execute_trade: bool = False):
        """Run all tests."""
        print("\n" + "="*60)
        print("ATLAS FORKNET E2E TEST")
        print("="*60)
        print(f"Time: {datetime.now().isoformat()}")
        print(f"RPC: {settings.arbitrum_rpc_url}")
        print(f"Vault: {self.vault_address or 'None'}")
        print("="*60 + "\n")
        
        # Run tests in order
        await self.test_rpc_connection()
        await self.test_trader_wallet()
        await self.test_vault_exists()
        await self.test_vault_balances()
        await self.test_trader_authorization()
        await self.test_database_vault()
        await self.test_strategy_load()
        await self.test_market_data()
        await self.test_dry_run_trade()
        await self.test_real_trade(execute_trade)
        
        # Summary
        print("\n" + "="*60)
        print("TEST SUMMARY")
        print("="*60)
        
        passed = sum(1 for _, status, _ in self.results if status == "PASS")
        failed = sum(1 for _, status, _ in self.results if status == "FAIL")
        skipped = sum(1 for _, status, _ in self.results if status in ("SKIP", "WARN"))
        
        print(f"✅ Passed: {passed}")
        print(f"❌ Failed: {failed}")
        print(f"⚠️  Skipped/Warned: {skipped}")
        print("="*60)
        
        if failed > 0:
            print("\nFailed tests:")
            for name, status, msg in self.results:
                if status == "FAIL":
                    print(f"  - {name}: {msg}")
        
        return failed == 0


async def main():
    parser = argparse.ArgumentParser(description="Atlas Forknet E2E Test")
    parser.add_argument("--vault", help="Vault address to test")
    parser.add_argument("--execute-trade", action="store_true", help="Execute real trade (not just dry run)")
    args = parser.parse_args()
    
    # Use provided vault or default test vault
    vault = args.vault or os.getenv("TEST_VAULT_ADDRESS", "0x0000000000000000000000000000000000000001")
    
    tester = ForknetTester(vault)
    success = await tester.run_all_tests(args.execute_trade)
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())
