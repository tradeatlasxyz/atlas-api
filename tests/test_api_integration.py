from datetime import datetime, timedelta

import pytest
import httpx
import pytest_asyncio
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from api.main import app
from api.models.database import Base, InvestorReport, PerformanceSnapshot, Strategy, Vault
from api.services.database import get_db


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(_type, _compiler, **_kw):
    return "JSON"


def _override_get_db(session):
    async def _override():
        yield session

    return _override


@pytest_asyncio.fixture()
async def db_session(tmp_path) -> AsyncSession:
    db_path = tmp_path / "test.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", echo=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    async with session_maker() as session:
        yield session

    await engine.dispose()


@pytest.mark.asyncio
async def test_strategy_discoveries_integration(db_session):
    strategy = Strategy(
        name="BTC Momentum",
        slug="btc-momentum",
        strategy_type="Momentum",
        asset="BTC",
        timeframe="1H",
        leverage_range=None,
        status="preview",
        featured=True,
        passed_curation=True,
        parameters=None,
    )
    report = InvestorReport(
        strategy=strategy,
        win_rate=0.6,
        sharpe=1.2,
        total_return=1.4,
        max_drawdown=0.2,
    )
    vault = Vault(
        address="0x1234567890abcdef1234567890abcdef12345678",
        name="BTC Momentum Vault",
        strategy=strategy,
    )
    db_session.add_all([strategy, report, vault])
    await db_session.commit()

    app.dependency_overrides[get_db] = _override_get_db(db_session)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/strategies/discoveries?limit=10")
    app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["strategies"][0]["asset"] == "BTC"
    assert payload["strategies"][0]["vaultAddress"] == vault.address


@pytest.mark.asyncio
async def test_investor_report_integration(db_session):
    strategy = Strategy(
        name="ETH Trend",
        slug="eth-trend",
        strategy_type="Trend",
        asset="ETH",
        timeframe="4H",
        leverage_range=None,
        status="preview",
        featured=False,
        passed_curation=False,
        parameters=None,
    )
    report = InvestorReport(
        strategy=strategy,
        win_rate=0.55,
        sharpe=1.1,
        total_return=1.1,
        max_drawdown=0.25,
        trade_count=12,
        profit_factor=1.5,
        avg_trade_duration="3 days",
        leverage=1.5,
        description="Demo report",
        report_url="/reports/eth.html",
        equity_curve=[{"date": "2024-01-01", "value": 100000}],
    )
    vault = Vault(
        address="0xabcdefabcdefabcdefabcdefabcdefabcdefabcd",
        name="ETH Trend Vault",
        strategy=strategy,
    )
    db_session.add_all([strategy, report, vault])
    await db_session.commit()

    app.dependency_overrides[get_db] = _override_get_db(db_session)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(f"/api/pool/{vault.address}/investor-report")
    app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert data["strategyType"] == "Trend"
    assert data["winRate"] == 0.55


@pytest.mark.asyncio
async def test_pool_history_integration(db_session):
    vault = Vault(
        address="0x2222222222222222222222222222222222222222",
        name="History Vault",
    )
    db_session.add(vault)
    await db_session.flush()

    now = datetime.utcnow()
    snapshots = [
        PerformanceSnapshot(
            vault_address=vault.address,
            timestamp=now - timedelta(days=2),
            tvl=100000,
            share_price=1.0,
            depositor_count=10,
            daily_return=0.01,
        ),
        PerformanceSnapshot(
            vault_address=vault.address,
            timestamp=now - timedelta(days=1),
            tvl=105000,
            share_price=1.05,
            depositor_count=12,
            daily_return=0.05,
        ),
    ]
    db_session.add_all(snapshots)
    await db_session.commit()

    app.dependency_overrides[get_db] = _override_get_db(db_session)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(f"/api/pool/{vault.address}/history?interval=daily")
    app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["meta"]["vaultAddress"] == vault.address
    assert payload["meta"]["dataPoints"] == 2
    assert payload["data"][0]["sharePrice"] == 1.0
