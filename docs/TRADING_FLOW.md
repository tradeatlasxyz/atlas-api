# Atlas Trading Flow - Backend Reference

## Quick Overview

```
User Creates Vault → Registers with API → Scheduler Monitors → Strategy Generates Signal → Trade Executes on GMX
```

## Core Components

### 1. Vault Registration
```http
POST /admin/vaults/register
{
    "address": "0x...",
    "name": "My Vault",
    "chain": "arbitrum",
    "strategy_id": 4
}
```

### 2. Execution Scheduler (`api/execution/scheduler.py`)
- Runs continuously, checking vaults every minute
- Loads strategy for each vault
- Generates signals from market data
- Executes trades when signal ≠ NEUTRAL

### 3. Strategy System (`api/execution/strategies/`)
```python
def generate_signals(candles: pd.DataFrame) -> Signal:
    # Calculate indicators
    # Return: direction (1=LONG, -1=SHORT, 0=NEUTRAL)
    return Signal(direction=1, confidence=0.85, size_pct=0.10)
```

### 4. Trade Executor (`api/execution/trade_executor.py`)
- Builds GMX order params
- Executes via dHEDGE vault's `execTransaction`
- Records result in database

## Database Tables

| Table | Purpose |
|-------|---------|
| `strategies` | Strategy definitions (name, asset, timeframe) |
| `vaults` | Registered vaults with strategy links |
| `investor_reports` | Backtest performance metrics |
| `signal_logs` | Every signal generated (for audit) |
| `trades` | Executed trades with tx hashes |

## Key API Endpoints

| Endpoint | Purpose |
|----------|---------|
| `GET /api/pool/{addr}/investor-report` | Strategy performance |
| `POST /admin/trigger/{addr}` | Manual signal check |
| `POST /api/vaults/{addr}/trade` | Manual trade |

## GMX Configuration

```python
# api/config.py
GMX_EXCHANGE_ROUTER = "0x900173A66dbD345006C51fA35fA3aB760FcD843b"
GMX_ORDER_VAULT = "0x31eF83a530Fde1B38EE9A18093A333D8Bbbc40D5"
GMX_EXECUTION_FEE_WEI = 100000000000000  # 0.0001 ETH
GMX_SLIPPAGE_BPS = 50  # 0.5%
```

## Minimum Requirements for Trading

| Requirement | Value |
|-------------|-------|
| Min USDC | $1.10 |
| Min WETH | 0.0001 ETH |
| GMX Min Position | $11 |
| GMX Max Leverage | ~10x |

## Environment Variables

```bash
TRADING_ENABLED=true
TRADER_PRIVATE_KEY=0x...
DATABASE_URL=postgresql://...
ARBITRUM_RPC_URL=https://...
```

## Flow Diagram

```
┌─────────────┐     ┌──────────────┐     ┌─────────────────┐
│  Scheduler  │────▶│ Strategy     │────▶│  TradeExecutor  │
│  (every 1m) │     │ generate()   │     │  execute()      │
└─────────────┘     └──────────────┘     └─────────────────┘
      │                    │                     │
      ▼                    ▼                     ▼
┌─────────────┐     ┌──────────────┐     ┌─────────────────┐
│  Vaults DB  │     │ Signal Logs  │     │  Trades DB      │
└─────────────┘     └──────────────┘     └─────────────────┘
```
