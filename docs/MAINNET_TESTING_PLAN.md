# Mainnet Testing Plan

## ✅ Forknet Testing Complete

### Issues Fixed

1. **Execution Fee Calculation** (Critical)
   - **Problem**: Was calculating 0.003 ETH (~$10) per trade
   - **Root Cause**: Using low gas estimates (300k-400k) when GMX keepers need 5-6M gas
   - **Solution**: Updated `_calculate_execution_fee()` to use 5M+ gas for keeper execution
   - **Result**: 
     - Forknet (1 gwei): ~$25-30 (expected for testnet)
     - Mainnet (0.02 gwei): ~$0.50-0.60 ✅

2. **Callback Gas Limit** 
   - **Problem**: Reduced to 300k, GMX requires minimum 750k
   - **Solution**: Restored `CALLBACK_GAS_LIMIT = 750000`

3. **WETH Balance for Execution Fee**
   - Vault needs WETH to pay GMX keeper fee (not just USDC)
   - On mainnet: ~0.0002 ETH minimum per trade

### Cost Breakdown (Mainnet)

| Component | Cost |
|-----------|------|
| Transaction Gas | ~$0.10 |
| GMX Keeper Fee | ~$0.50 |
| **Total per Trade** | **~$0.60** |

This is comparable to GMX's web interface.

---

## Mainnet Testing Checklist

### Pre-Flight Checks

- [ ] **Trader Wallet**
  - [ ] Fund with 0.01 ETH (enough for ~15-20 trades)
  - [ ] Verify private key is correct in `.env`
  - [ ] Check: `TRADER_PRIVATE_KEY` is set

- [ ] **Vault Setup**
  - [ ] Vault is registered in database with strategy linked
  - [ ] Trader wallet is authorized on-chain (`vault.trader() == our_address`)
  - [ ] USDC balance: $20+ recommended for test trades
  - [ ] WETH balance: 0.002+ ETH for execution fees

- [ ] **Configuration**
  - [ ] `TRADING_ENABLED=true`
  - [ ] `ARBITRUM_RPC_URL` points to mainnet
  - [ ] `GMX_EXECUTION_FEE_WEI=100000000000000` (0.0001 ETH minimum floor)

### Test Sequence

#### Phase 1: Dry Run (No Real Trades)
```bash
# Set TRADING_ENABLED=false
# Trigger the scheduler to verify signals generate correctly
curl -X POST http://127.0.0.1:8000/admin/trigger/0xVAULT_ADDRESS
```

Expected: Logs show "Trading disabled" but signal generated correctly.

#### Phase 2: Small Trade Test
```bash
# Set TRADING_ENABLED=true
# Manually trigger a $20 trade via API
curl -X POST http://127.0.0.1:8000/trading/trade \
  -H "Content-Type: application/json" \
  -d '{
    "vault_address": "0xVAULT_ADDRESS",
    "asset": "BTC",
    "direction": 1,
    "size_usd": 20.0
  }'
```

Expected: 
- Transaction hash returned
- GMX order created on-chain
- Cost: ~$0.60

#### Phase 3: Verify Order Execution
- GMX orders are async - keepers execute them
- Check Arbiscan for the transaction
- Verify position opened in vault

#### Phase 4: Automated Trading
- Let scheduler run for 4H (one BTC strategy period)
- Monitor logs for signal generation
- Verify trades execute correctly

### Monitoring Commands

```bash
# Check trader balance
python -c "from api.execution.trade_executor import TradeExecutor; e = TradeExecutor(); print(f'Balance: {e.web3.eth.get_balance(e.trader.address) / 10**18:.4f} ETH')"

# Check vault balances
python scripts/check_vault_balances.py

# View recent trades in DB
python -c "
from api.database import get_db_session
from api.models.database import Trade
from sqlalchemy import select, desc
with get_db_session() as db:
    trades = db.execute(select(Trade).order_by(desc(Trade.created_at)).limit(5)).scalars().all()
    for t in trades:
        print(f'{t.created_at}: {t.asset} {\"LONG\" if t.direction > 0 else \"SHORT\"} ${t.size_usd:.2f}')
"
```

### Risk Management

1. **Start Small**: First trade should be $20 max
2. **Monitor Gas**: Arbitrum gas can spike during congestion
3. **Position Limits**: Default leverage is 5x - don't exceed vault balance
4. **GMX Limits**: Minimum position size is $10

### Troubleshooting

| Error | Cause | Solution |
|-------|-------|----------|
| `InsufficientExecutionFee` | Gas price spiked | Increase `gmx_execution_fee_wei` |
| `ERC20: transfer exceeds balance` | Vault has no WETH | Fund vault with WETH |
| `max leverage exceeded` | Position too large for collateral | Reduce trade size |
| `longToken not supported` | Asset not enabled for vault | Add to vault's supported assets |

---

## Summary

The Atlas trading system is now ready for mainnet testing:

1. ✅ Execution fee calculation fixed
2. ✅ Forknet trade successful
3. ✅ E2E flow matches dHEDGE documentation
4. ✅ Costs are reasonable (~$0.60/trade)

**Next Step**: Fund trader wallet and vault, then run Phase 1 dry test.
