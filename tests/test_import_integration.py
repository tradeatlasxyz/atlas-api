from pathlib import Path

import pytest
from sqlalchemy import select

from api.models.database import InvestorReport, Strategy
from api.services import import_service
from api.services.import_service import import_strategy_from_folder


@pytest.mark.asyncio
async def test_import_from_analytics_fixture(db_session, tmp_path, monkeypatch):
    fixture_dir = Path(__file__).parent / "fixtures" / "analytics" / "baseline_marketgod"
    assert (fixture_dir / "llm_context.json").exists()
    assert (fixture_dir / "strategy.py").exists()

    monkeypatch.setattr(import_service, "STRATEGIES_DIR", tmp_path / "strategies")

    result = await import_strategy_from_folder(db_session, fixture_dir, dry_run=False)
    assert result.success is True

    strategy = (await db_session.execute(select(Strategy))).scalar_one()
    assert strategy.slug == "baseline-marketgod"

    report = (await db_session.execute(select(InvestorReport))).scalar_one()
    assert float(report.win_rate) == pytest.approx(0.3239, rel=1e-3)

    assert Path(result.code_path).exists()
