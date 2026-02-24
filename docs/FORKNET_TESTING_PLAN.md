# Forknet Testing Plan

> Complete guide to testing Atlas on Arbitrum forknet before mainnet deployment

## Overview

This document outlines the steps to test the complete Atlas E2E flow on a local Arbitrum fork before deploying to mainnet.

## Prerequisites

### 1. Environment Setup

```bash
# Clone both repos
cd ~/Documents/GitHub
git clone <atlas-api>
git clone <atlas-frontend>

# Install dependencies
cd atlas-api && pip install -r requirements.txt
cd ../atlas-frontend && pnpm install
```

### 2. Required Environment Variables

**atlas-api/.env:**
```bash
# Database
DATABASE_URL=postgresql://...

# Arbitrum Fork RPC (will be set after starting Hardhat)
ARBITRUM_RPC_URL=http://127.0.0.1:8545

# Trader wallet (use a test wallet for forknet)
TRADER_PRIVATE_KEY=0x...  # Will be funded from fork

# Trading
TRADING_ENABLED=true

# GMX Configuration
GMX_EXECUTION_FEE_WEI=100000000000000
GMX_SLIPPAGE_BPS=50
GMX_COLLATERAL_TOKEN=0xaf88d065e77c8cC2239327C5EDb3A432268e5831
```

**atlas-frontend/.env.local:**
```bash
ALGO_ENGINE_API_URL=http://127.0.0.1:8000
NEXT_PUBLIC_ARBITRUM_RPC_URL=http://127.0.0.1:8545
```

---

## Phase 1: Start Arbitrum Fork

### 1.1 Start Hardhat Fork

```bash
cd atlas-frontend

# Start Arbitrum fork (requires ARBITRUM_URL in .env)
pnpm fork:arbitrum
```

This starts a local Hardhat node forking Arbitrum mainnet at `http://127.0.0.1:8545`.

### 1.2 Fund Test Accounts

```bash
# In a new terminal
cd atlas-api

# Fund the trader wallet with ETH and USDC
python scripts/fund_test_wallet.py
```

Or manually via Hardhat console:

```javascript
// Connect to fork
const { ethers } = require("hardhat");

// Impersonate a whale account with USDC
const whaleAddress = "0x..."; // USDC whale on Arbitrum
await hre.network.provider.request({
  method: "hardhat_impersonateAccount",
  params: [whaleAddress],
});

// Transfer USDC to trader
const usdc = await ethers.getContractAt("IERC20", "0xaf88d065e77c8cC2239327C5EDb3A432268e5831");
const whale = await ethers.getSigner(whaleAddress);
await usdc.connect(whale).transfer(traderAddress, ethers.parseUnits("1000", 6));
```

---

## Phase 2: Vault Creation Tests

### 2.1 Test Frontend Vault Creation

1. **Start Frontend:**
   ```bash
   cd atlas-frontend
   pnpm -C apps/web dev
   ```

2. **Start Backend:**
   ```bash
   cd atlas-api
   source venv/bin/activate
   uvicorn api.main:app --reload
   ```

3. **Create Test Vault via UI:**
   - Navigate to http://localhost:3000/manage
   - Connect wallet (MetaMask configured for localhost:8545)
   - Click "Create New Vault"
   - Fill in:
     - Vault Name: "Forknet Test Vault"
     - Symbol: "FTV"
     - Manager Name: "Test Manager"
     - Performance Fee: 10%
     - Management Fee: 2%
   - Select assets: USDC, WETH, WBTC
   - Add GMX markets (if available)
   - Confirm transaction

4. **Verify Vault Creation:**
   ```bash
   # Check database
   curl http://127.0.0.1:8000/admin/vaults | python -m json.tool
   ```

### 2.2 Test Backend Vault Registration

```bash
# Register vault manually
curl -X POST http://127.0.0.1:8000/admin/vaults/register \
  -H "Content-Type: application/json" \
  -d '{
    "address": "<VAULT_ADDRESS>",
    "name": "Forknet Test Vault",
    "chain": "arbitrum",
    "strategy_id": 4
  }'
```

---

## Phase 3: Trading Tests

### 3.1 Fund Vault for Trading

```bash
# Transfer USDC and WETH to vault
python scripts/fund_vault.py --vault <VAULT_ADDRESS> --usdc 100 --weth 0.01
```

### 3.2 Test Manual Trade via API

```bash
# Dry run first
curl -X POST http://127.0.0.1:8000/api/vaults/<VAULT_ADDRESS>/trade \
  -H "Content-Type: application/json" \
  -d '{
    "direction": "LONG",
    "asset": "BTC",
    "sizeUsd": 50,
    "dryRun": true
  }'

# Execute real trade
curl -X POST http://127.0.0.1:8000/api/vaults/<VAULT_ADDRESS>/trade \
  -H "Content-Type: application/json" \
  -d '{
    "direction": "LONG",
    "asset": "BTC",
    "sizeUsd": 50,
    "dryRun": false
  }'
```

### 3.3 Test Strategy Signal Generation

```bash
# Trigger signal check
curl -X POST http://127.0.0.1:8000/admin/trigger/<VAULT_ADDRESS>

# Check signal logs
curl http://127.0.0.1:8000/admin/vaults/<VAULT_ADDRESS>/signals
```

### 3.4 Test Automatic Trading Loop

```bash
# Start scheduler in test mode
cd atlas-api
python -m api.execution.scheduler --test-mode

# Watch logs for signal generation and trade execution
```

---

## Phase 4: UI Verification Tests

### 4.1 Investor Report Display

1. Navigate to http://localhost:3000/pool/<VAULT_ADDRESS>?network=42161
2. Verify investor report card shows:
   - Total Return
   - Sharpe Ratio
   - Trade Count
   - Strategy info (BTC/4H)
3. Confirm "Preview data" warning is NOT shown (fallback: false)

### 4.2 Trade History

1. Check Trade History table shows executed trades
2. Verify transaction hashes link to block explorer

### 4.3 Portfolio View

1. Check vault positions are displayed correctly
2. Verify asset balances match on-chain state

---

## Phase 5: Edge Case Tests

### 5.1 Insufficient Balance

```bash
# Try trade with insufficient collateral
curl -X POST http://127.0.0.1:8000/api/vaults/<VAULT_ADDRESS>/trade \
  -H "Content-Type: application/json" \
  -d '{
    "direction": "LONG",
    "asset": "BTC",
    "sizeUsd": 100000,
    "dryRun": false
  }'
# Should return error about insufficient balance
```

### 5.2 Unsupported Asset

```bash
# Try trade with unsupported market
curl -X POST http://127.0.0.1:8000/api/vaults/<VAULT_ADDRESS>/trade \
  -H "Content-Type: application/json" \
  -d '{
    "direction": "LONG",
    "asset": "DOGE",
    "sizeUsd": 50,
    "dryRun": false
  }'
# Should return error about unsupported market
```

### 5.3 Wrong Trader Wallet

```bash
# Temporarily change trader private key in .env
# Try trade - should fail with "not manager" error
```

### 5.4 Missing Token Approvals

```bash
# Remove approvals from vault
# Try trade - should fail with "allowance" error
```

---

## Phase 6: Test Checklist

### Vault Creation
- [ ] Create vault via /manage page
- [ ] Create vault via /explore page  
- [ ] Create vault via /lab (strategy deployment)
- [ ] Verify vault registered in database
- [ ] Verify strategy linked correctly
- [ ] Verify vault tokens minted to creator

### Trading
- [ ] Manual trade (dry run)
- [ ] Manual trade (real execution)
- [ ] Strategy signal generation
- [ ] Automatic trade execution
- [ ] Trade recorded in database
- [ ] Transaction hash valid

### UI Display
- [ ] Investor report shows (not fallback)
- [ ] Trade history populated
- [ ] Vault balance correct
- [ ] Token price updates

### Error Handling
- [ ] Insufficient balance error
- [ ] Unsupported asset error
- [ ] Wrong network error
- [ ] Transaction revert error

---

## Phase 7: Mainnet Deployment Plan

### Pre-Deployment Checklist

- [ ] All forknet tests passing
- [ ] Production environment variables set
- [ ] Trader wallet funded with ETH (for gas)
- [ ] Database schema up to date
- [ ] API deployed to production (Railway)
- [ ] Frontend deployed to production (Vercel)

### Mainnet Testing Steps

1. **Create Test Vault on Mainnet:**
   - Use small amounts ($10-50 USDC)
   - Select only essential assets

2. **Test Manual Trade:**
   - Start with $11 minimum position
   - Execute via API with dryRun=true first
   - Then execute real trade

3. **Monitor for 24 Hours:**
   - Watch for any errors in logs
   - Verify signals are being generated
   - Check trades are being recorded

4. **Scale Up:**
   - Increase vault funding
   - Enable more strategies
   - Open to investors

### Rollback Plan

If issues occur on mainnet:

1. **Disable Trading:**
   ```bash
   # Set in production environment
   TRADING_ENABLED=false
   ```

2. **Close Positions:**
   - Manually close all open positions via GMX UI
   - Or use emergency close endpoint

3. **Investigate:**
   - Check API logs
   - Check database state
   - Review transaction failures

---

## Scripts for Testing

### fund_vault.py

```python
#!/usr/bin/env python3
"""Fund a vault with USDC and WETH for testing."""

import asyncio
import argparse
from web3 import Web3
from api.config import settings

async def main(vault_address: str, usdc_amount: float, weth_amount: float):
    web3 = Web3(Web3.HTTPProvider(settings.arbitrum_rpc_url))
    
    # Impersonate USDC whale (only works on fork)
    usdc_whale = "0x..."  # Find a whale address
    
    # Transfer USDC
    usdc = web3.eth.contract(
        address=Web3.to_checksum_address(settings.gmx_collateral_token),
        abi=[{...}],  # ERC20 ABI
    )
    
    # ... transfer logic
    print(f"Funded {vault_address} with ${usdc_amount} USDC and {weth_amount} WETH")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--vault", required=True)
    parser.add_argument("--usdc", type=float, default=100)
    parser.add_argument("--weth", type=float, default=0.01)
    args = parser.parse_args()
    asyncio.run(main(args.vault, args.usdc, args.weth))
```

### check_vault_state.py

```python
#!/usr/bin/env python3
"""Check vault state on-chain."""

from web3 import Web3
from api.config import settings

VAULT = "0x..."

web3 = Web3(Web3.HTTPProvider(settings.arbitrum_rpc_url))

# Check balances, positions, approvals...
```

---

*Last updated: January 31, 2026*
