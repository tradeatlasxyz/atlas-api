from __future__ import annotations

from typing import Optional, Tuple

from sqlalchemy import desc, func, nullslast, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from api.models.database import InvestorReport, Strategy, Vault


async def get_strategy_discoveries(
    db: AsyncSession,
    *,
    page: int = 1,
    limit: int = 10,
    asset: Optional[str] = None,
    timeframe: Optional[str] = None,
    strategy_type: Optional[str] = None,
    status: Optional[str] = None,
    featured: Optional[bool] = None,
    passed_curation: Optional[bool] = None,
    sort: str = "latest",
) -> Tuple[list[Strategy], int]:
    filters = []
    if asset:
        filters.append(Strategy.asset == asset)
    if timeframe:
        filters.append(Strategy.timeframe == timeframe)
    if strategy_type:
        filters.append(Strategy.strategy_type == strategy_type)
    if status:
        filters.append(Strategy.status == status)
    if featured is not None:
        filters.append(Strategy.featured == featured)
    if passed_curation is not None:
        filters.append(Strategy.passed_curation == passed_curation)

    count_query = select(func.count()).select_from(Strategy)
    if filters:
        count_query = count_query.where(*filters)
    total = await db.scalar(count_query)

    query = (
        select(Strategy)
        .options(selectinload(Strategy.investor_report), selectinload(Strategy.vaults))
        .outerjoin(InvestorReport, Strategy.id == InvestorReport.strategy_id)
    )
    if filters:
        query = query.where(*filters)

    if sort == "winrate":
        query = query.order_by(nullslast(desc(InvestorReport.win_rate)))
    elif sort == "sharpe":
        query = query.order_by(nullslast(desc(InvestorReport.sharpe)))
    elif sort == "return":
        query = query.order_by(nullslast(desc(InvestorReport.total_return)))
    else:
        query = query.order_by(desc(Strategy.discovered_at))

    offset = (page - 1) * limit
    query = query.offset(offset).limit(limit)

    result = await db.execute(query)
    strategies = result.scalars().all()

    return list(strategies), int(total or 0)


def _strategy_identifier(strategy: Strategy) -> str:
    if strategy.slug:
        return strategy.slug
    return f"strat_{strategy.id}"


def strategy_to_discovery_dict(strategy: Strategy) -> dict:
    report = strategy.investor_report
    vault = strategy.vaults[0] if strategy.vaults else None

    win_rate = float(report.win_rate) if report and report.win_rate is not None else 0.0
    max_drawdown = (
        float(report.max_drawdown) if report and report.max_drawdown is not None else 0.0
    )

    return {
        "id": _strategy_identifier(strategy),
        "name": strategy.name,
        "strategy_type": strategy.strategy_type,
        "asset": strategy.asset.upper() if strategy.asset else strategy.asset,
        "timeframe": strategy.timeframe,
        "leverage_range": strategy.leverage_range,
        "win_rate": win_rate,
        "sharpe": float(report.sharpe) if report and report.sharpe is not None else 0.0,
        "sortino": float(report.sortino) if report and report.sortino is not None else None,
        "max_drawdown": max_drawdown,
        "total_return": (
            float(report.total_return) if report and report.total_return is not None else None
        ),
        "discovered_at": strategy.discovered_at,
        "featured": strategy.featured,
        "passed_curation": strategy.passed_curation,
        "status": strategy.status,
        "vault_address": vault.address if vault else None,
    }


def _report_value(value):
    return float(value) if value is not None else None


def _build_investor_report_response(strategy: Strategy, report: Optional[InvestorReport]) -> dict:
    response = {
        "strategy_type": strategy.strategy_type,
        "timeframe": strategy.timeframe,
        "asset": strategy.asset,
    }

    if report:
        response.update(
            {
                "win_rate": _report_value(report.win_rate),
                "total_return": _report_value(report.total_return),
                "sharpe": _report_value(report.sharpe),
                "sortino": _report_value(report.sortino),
                "max_drawdown": _report_value(report.max_drawdown),
                "trade_count": report.trade_count,
                "profit_factor": _report_value(report.profit_factor),
                "avg_trade_duration": report.avg_trade_duration,
                "leverage": _report_value(report.leverage),
                "description": report.description,
                "report_url": report.report_url,
                "equity_curve": report.equity_curve,
            }
        )

    return response


async def get_investor_report_by_vault(
    db: AsyncSession, vault_address: str
) -> Optional[dict]:
    query = (
        select(Vault)
        .options(
            selectinload(Vault.strategy).selectinload(Strategy.investor_report)
        )
        .where(Vault.address == vault_address)
    )
    result = await db.execute(query)
    vault = result.scalar_one_or_none()

    if not vault or not vault.strategy:
        return None

    strategy = vault.strategy
    report = strategy.investor_report
    return _build_investor_report_response(strategy, report)
