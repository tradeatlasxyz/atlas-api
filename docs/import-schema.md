# Atlas Strategy Import Schema (v1.0)

This document describes the holistic import payload used to ingest strategy metadata, performance metrics, trades, and code from the analytics pipeline into atlas-api.

## Supported Import Formats

### Option A: Separate Files (Recommended)

```
results/<run_id>/
├── llm_context.json
└── strategy.py
```

### Option B: Embedded Code

If `strategy.py` is not present, `llm_context.json` may include a `source_code` field.

## Payload: llm_context.json

```json
{
  "_llm_context": {
    "version": "1.0",
    "purpose": "strategy_import",
    "generated_at": "2026-01-24T12:00:00Z"
  },
  "strategy": {
    "name": "BTC Momentum 1H",
    "slug": "btc-momentum-1h",
    "strategy_type": "Momentum",
    "asset": "BTC",
    "timeframe": "1H",
    "leverage_range": "1-10x",
    "status": "deployable",
    "featured": false,
    "passed_curation": true,
    "discovered_at": "2026-01-24T12:00:00Z",
    "description": "A momentum strategy focused on trend continuation."
  },
  "vault": {
    "address": "0x0000000000000000000000000000000000000001",
    "name": "BTC Momentum Vault",
    "chain": "arbitrum",
    "status": "active",
    "check_interval": "1m",
    "synthetix_account_id": 1
  },
  "investor_report": {
    "win_rate": 0.63,
    "total_return": 1.799,
    "sharpe": 2.1,
    "sortino": 2.8,
    "max_drawdown": 0.18,
    "trade_count": 27,
    "profit_factor": 9.51,
    "avg_trade_duration": "4.2 days",
    "leverage": 22.8
  },
  "equity_curve": [
    {"date": "2024-01-01", "value": 100000},
    {"date": "2024-01-15", "value": 105230}
  ],
  "trades": [
    {
      "trade_num": 1,
      "entry_date": "2024-01-05T08:00:00Z",
      "exit_date": "2024-01-07T16:00:00Z",
      "entry_price": 42500.0,
      "exit_price": 43800.0,
      "side": "long",
      "size": 2.5,
      "pnl_pct": 0.0306,
      "result": "WIN"
    }
  ],
  "source_code": "import numpy as np\n..."
}
```

## Validation Rules
- `strategy.slug` must be lowercase and URL-safe (a-z, 0-9, hyphens).
- `strategy.description` must be investor-friendly (no indicator names like RSI, MACD).
- If `strategy.py` is missing, `source_code` must be provided.
- `vault` is optional. If provided without `chain`, it defaults to `arbitrum`.

## Notes
- The CLI checks for `strategy.py` first, then falls back to `source_code` in JSON.
- Schema versioning is stored under `_llm_context.version`.
