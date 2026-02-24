import json
from pathlib import Path

import pytest
from sqlalchemy import select

from api.models.database import InvestorReport, Strategy, Trade, Vault
from api.services import import_service
from api.services.import_service import import_strategy_from_folder


def write_import_folder(tmp_path: Path) -> Path:
    folder = tmp_path / "results"
    folder.mkdir()
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
    (folder / "llm_context.json").write_text(json.dumps(payload))
    (folder / "strategy.py").write_text("def generate_signals(df):\n    return [0] * len(df)\n")
    return folder


def write_import_folder_with_source(tmp_path: Path) -> Path:
    folder = tmp_path / "results"
    folder.mkdir()
    payload = {
        "strategy": {
            "name": "BTC Momentum 1H",
            "slug": "btc-momentum-1h",
            "strategy_type": "Momentum",
            "asset": "BTC",
            "timeframe": "1H",
            "description": "Momentum strategy focused on trend continuation.",
        },
        "source_code": "def generate_signals(df):\n    return [1] * len(df)\n",
        "equity_curve": [{"date": "2024-01-01", "value": 100000}],
        "trades": [],
    }
    (folder / "llm_context.json").write_text(json.dumps(payload))
    return folder


@pytest.mark.asyncio
async def test_import_service_dry_run(db_session, tmp_path, monkeypatch):
    folder = write_import_folder(tmp_path)
    monkeypatch.setattr(import_service, "STRATEGIES_DIR", tmp_path / "strategies")

    result = await import_strategy_from_folder(db_session, folder, dry_run=True)
    assert result.success is True

    strategies = (await db_session.execute(select(Strategy))).scalars().all()
    assert strategies == []
    assert not (tmp_path / "strategies").exists()


@pytest.mark.asyncio
async def test_import_service_writes_records(db_session, tmp_path, monkeypatch):
    folder = write_import_folder(tmp_path)
    monkeypatch.setattr(import_service, "STRATEGIES_DIR", tmp_path / "strategies")

    result = await import_strategy_from_folder(db_session, folder, dry_run=False)
    assert result.success is True

    strategy = (await db_session.execute(select(Strategy))).scalar_one()
    assert strategy.slug == "btc-momentum-1h"
    assert strategy.code_path is not None

    report = (await db_session.execute(select(InvestorReport))).scalar_one()
    assert float(report.win_rate) == pytest.approx(0.6)

    trades = (await db_session.execute(select(Trade))).scalars().all()
    assert len(trades) == 1
    assert trades[0].strategy_id == strategy.id
    assert trades[0].size is not None

    expected_file = Path(result.code_path)
    assert expected_file.exists()


@pytest.mark.asyncio
async def test_import_service_force_overwrite(db_session, tmp_path, monkeypatch):
    folder = write_import_folder(tmp_path)
    monkeypatch.setattr(import_service, "STRATEGIES_DIR", tmp_path / "strategies")

    first = await import_strategy_from_folder(db_session, folder, dry_run=False)
    assert first.success is True

    second = await import_strategy_from_folder(db_session, folder, dry_run=False)
    assert second.success is False

    third = await import_strategy_from_folder(db_session, folder, dry_run=False, force=True)
    assert third.success is True


@pytest.mark.asyncio
async def test_import_service_creates_vault(db_session, tmp_path, monkeypatch):
    folder = write_import_folder(tmp_path)
    monkeypatch.setattr(import_service, "STRATEGIES_DIR", tmp_path / "strategies")

    payload = json.loads((folder / "llm_context.json").read_text())
    payload["vault"] = {
        "address": "0x0000000000000000000000000000000000000001",
        "name": "BTC Momentum Vault",
        "chain": "arbitrum",
    }
    (folder / "llm_context.json").write_text(json.dumps(payload))

    result = await import_strategy_from_folder(db_session, folder, dry_run=False)
    assert result.success is True

    strategy = (await db_session.execute(select(Strategy))).scalar_one()
    vault = (await db_session.execute(select(Vault))).scalar_one()
    assert vault.address == "0x0000000000000000000000000000000000000001"
    assert vault.chain == "arbitrum"
    assert vault.strategy_id == strategy.id


@pytest.mark.asyncio
async def test_import_service_missing_llm_context(db_session, tmp_path):
    folder = tmp_path / "results"
    folder.mkdir()
    result = await import_strategy_from_folder(db_session, folder, dry_run=False)
    assert result.success is False
    assert "llm_context.json not found" in (result.error or "")


@pytest.mark.asyncio
async def test_import_service_invalid_llm_context(db_session, tmp_path):
    folder = tmp_path / "results"
    folder.mkdir()
    (folder / "llm_context.json").write_text("{not-json")
    result = await import_strategy_from_folder(db_session, folder, dry_run=False)
    assert result.success is False
    assert "Invalid llm_context.json" in (result.error or "")


@pytest.mark.asyncio
async def test_import_service_uses_embedded_source_code(db_session, tmp_path, monkeypatch):
    folder = write_import_folder_with_source(tmp_path)
    monkeypatch.setattr(import_service, "STRATEGIES_DIR", tmp_path / "strategies")

    result = await import_strategy_from_folder(db_session, folder, dry_run=False)
    assert result.success is True
    assert result.code_path is not None
    assert Path(result.code_path).exists()
