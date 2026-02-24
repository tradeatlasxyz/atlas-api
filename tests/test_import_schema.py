import pytest

from api.models.import_schema import StrategyImportPayload


def build_payload(overrides=None):
    payload = {
        "strategy": {
            "name": "BTC Momentum 1H",
            "slug": "btc-momentum-1h",
            "strategy_type": "Momentum",
            "asset": "BTC",
            "timeframe": "1H",
            "description": "Momentum strategy focused on trend continuation.",
        },
        "investor_report": {
            "win_rate": 0.6,
            "sharpe": 1.8,
        },
        "equity_curve": [{"date": "2024-01-01", "value": 100000}],
        "trades": [
            {
                "trade_num": 1,
                "entry_date": "2024-01-01T00:00:00Z",
                "exit_date": "2024-01-02T00:00:00Z",
                "entry_price": 100.0,
                "exit_price": 110.0,
                "side": "long",
                "size": 2.5,
                "pnl_pct": 0.1,
                "result": "WIN",
            }
        ],
    }
    if overrides:
        payload.update(overrides)
    return payload


def test_import_schema_valid_payload():
    payload = build_payload()
    model = StrategyImportPayload(**payload)
    assert model.strategy.slug == "btc-momentum-1h"


def test_import_schema_invalid_slug():
    payload = build_payload()
    payload["strategy"]["slug"] = "Bad Slug"
    with pytest.raises(ValueError):
        StrategyImportPayload(**payload)


def test_import_schema_description_guardrails():
    payload = build_payload()
    payload["strategy"]["description"] = "Uses RSI and MACD signals"
    with pytest.raises(ValueError):
        StrategyImportPayload(**payload)


def test_import_schema_normalizes_vault_chain():
    payload = build_payload()
    payload["vault"] = {
        "address": "0x0000000000000000000000000000000000000001",
        "name": "BTC Momentum Vault",
        "chain": "Arbitrum",
    }
    model = StrategyImportPayload(**payload)
    assert model.vault is not None
    assert model.vault.chain == "arbitrum"
