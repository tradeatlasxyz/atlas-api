"""Holistic strategy import service."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.models.database import InvestorReport, Strategy, Trade, Vault
from api.models.import_schema import StrategyImportPayload

STRATEGIES_DIR = Path(__file__).resolve().parent.parent / "execution" / "strategies" / "deployed"


@dataclass
class ImportResult:
    success: bool
    strategy_name: str = ""
    strategy_id: Optional[int] = None
    code_path: Optional[Path] = None
    error: Optional[str] = None


def _load_strategy_code(folder_path: Path, payload: StrategyImportPayload, verbose: bool) -> str:
    strategy_py_path = folder_path / "strategy.py"
    if strategy_py_path.exists():
        source_code = strategy_py_path.read_text()
        if verbose:
            print(f"✓ Found strategy.py ({len(source_code)} chars)")
        return source_code
    if payload.source_code:
        if verbose:
            print(f"✓ Using embedded source_code ({len(payload.source_code)} chars)")
        return payload.source_code
    raise FileNotFoundError(
        "No strategy code found (neither strategy.py nor source_code in JSON)"
    )


async def import_strategy_from_folder(
    db: AsyncSession,
    folder_path: Path,
    dry_run: bool = False,
    force: bool = False,
    verbose: bool = False,
) -> ImportResult:
    llm_context_path = folder_path / "llm_context.json"
    if not llm_context_path.exists():
        return ImportResult(success=False, error=f"llm_context.json not found in {folder_path}")

    try:
        data = json.loads(llm_context_path.read_text())
        payload = StrategyImportPayload(**data)
    except Exception as exc:
        return ImportResult(success=False, error=f"Invalid llm_context.json: {exc}")

    if verbose:
        print(f"✓ Loaded metadata: {payload.strategy.name}")

    try:
        source_code = _load_strategy_code(folder_path, payload, verbose)
    except Exception as exc:
        return ImportResult(success=False, error=str(exc))

    slug = payload.strategy.slug
    existing = await db.execute(select(Strategy).where(Strategy.slug == slug))
    existing_strategy = existing.scalar_one_or_none()

    if existing_strategy and not force:
        return ImportResult(
            success=False,
            strategy_name=payload.strategy.name,
            error=f"Strategy '{slug}' already exists. Use --force to overwrite.",
        )

    if dry_run:
        if verbose:
            print(f"✓ Dry run - would import: {payload.strategy.name}")
        return ImportResult(success=True, strategy_name=payload.strategy.name)

    STRATEGIES_DIR.mkdir(parents=True, exist_ok=True)
    code_file_path = STRATEGIES_DIR / f"{slug}.py"
    temp_path = code_file_path.with_suffix(".py.tmp")
    try:
        temp_path.write_text(source_code)
    except Exception as exc:
        return ImportResult(success=False, error=f"Failed to write strategy code: {exc}")

    if verbose:
        print(f"✓ Wrote code to temp file: {temp_path}")

    if existing_strategy and force:
        strategy = existing_strategy
        strategy.name = payload.strategy.name
        strategy.strategy_type = payload.strategy.strategy_type
        strategy.asset = payload.strategy.asset
        strategy.timeframe = payload.strategy.timeframe
        strategy.leverage_range = payload.strategy.leverage_range
        strategy.status = payload.strategy.status
        strategy.featured = payload.strategy.featured
        strategy.passed_curation = payload.strategy.passed_curation
        strategy.description = payload.strategy.description
        strategy.parameters = payload.strategy.parameters
        strategy.code_path = str(code_file_path)
    else:
        strategy = Strategy(
            name=payload.strategy.name,
            slug=slug,
            strategy_type=payload.strategy.strategy_type,
            asset=payload.strategy.asset,
            timeframe=payload.strategy.timeframe,
            leverage_range=payload.strategy.leverage_range,
            status=payload.strategy.status,
            featured=payload.strategy.featured,
            passed_curation=payload.strategy.passed_curation,
            discovered_at=payload.strategy.discovered_at,
            description=payload.strategy.description,
            parameters=payload.strategy.parameters,
            code_path=str(code_file_path),
        )
        db.add(strategy)

    await db.flush()

    if payload.vault:
        address = payload.vault.address.lower()
        existing_vault = await db.execute(
            select(Vault).where(Vault.address == address)
        )
        vault = existing_vault.scalar_one_or_none()

        if vault:
            vault.strategy_id = strategy.id
            vault.name = payload.vault.name
            if payload.vault.chain:
                vault.chain = payload.vault.chain
            if payload.vault.status:
                vault.status = payload.vault.status
            if payload.vault.check_interval:
                vault.check_interval = payload.vault.check_interval
            if payload.vault.synthetix_account_id is not None:
                vault.synthetix_account_id = payload.vault.synthetix_account_id
        else:
            vault = Vault(
                address=address,
                strategy_id=strategy.id,
                name=payload.vault.name,
                chain=payload.vault.chain or "arbitrum",
                status=payload.vault.status or "active",
                check_interval=payload.vault.check_interval or "1m",
                synthetix_account_id=payload.vault.synthetix_account_id,
            )
            db.add(vault)

    if payload.investor_report:
        existing_report = await db.execute(
            select(InvestorReport).where(InvestorReport.strategy_id == strategy.id)
        )
        report = existing_report.scalar_one_or_none()

        report_data = {
            "strategy_id": strategy.id,
            "win_rate": payload.investor_report.win_rate,
            "total_return": payload.investor_report.total_return,
            "sharpe": payload.investor_report.sharpe,
            "sortino": payload.investor_report.sortino,
            "max_drawdown": payload.investor_report.max_drawdown,
            "trade_count": payload.investor_report.trade_count,
            "profit_factor": payload.investor_report.profit_factor,
            "avg_trade_duration": payload.investor_report.avg_trade_duration,
            "leverage": payload.investor_report.leverage,
            "description": payload.strategy.description,
        }

        if payload.equity_curve:
            report_data["equity_curve"] = [
                {"date": point.date, "value": point.value}
                for point in payload.equity_curve
            ]

        if report:
            for key, value in report_data.items():
                setattr(report, key, value)
        else:
            report = InvestorReport(**report_data)
            db.add(report)

    if payload.trades:
        await db.execute(
            Trade.__table__.delete().where(Trade.strategy_id == strategy.id)
        )
        for trade_payload in payload.trades:
            trade = Trade(
                strategy_id=strategy.id,
                vault_address=None,
                trade_num=trade_payload.trade_num,
                timestamp=trade_payload.entry_date,
                side=trade_payload.side,
                asset=payload.strategy.asset,
                size=trade_payload.size,
                entry_price=trade_payload.entry_price,
                exit_price=trade_payload.exit_price,
                exit_timestamp=trade_payload.exit_date,
                pnl=None,
                pnl_pct=trade_payload.pnl_pct,
                result=trade_payload.result,
            )
            db.add(trade)

    try:
        await db.commit()
    except Exception as exc:
        await db.rollback()
        try:
            temp_path.unlink(missing_ok=True)
        except Exception:
            pass
        return ImportResult(success=False, error=f"Database commit failed: {exc}")

    try:
        temp_path.replace(code_file_path)
    except Exception as exc:
        return ImportResult(success=False, error=f"Failed to finalize strategy code: {exc}")

    if verbose:
        print("✓ Database records created/updated")

    return ImportResult(
        success=True,
        strategy_name=payload.strategy.name,
        strategy_id=strategy.id,
        code_path=code_file_path,
    )
