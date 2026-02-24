"""Load strategies from the file system and database."""
from __future__ import annotations

import importlib.util
import logging
import sys
import inspect
import numpy as np
from pathlib import Path
from typing import Callable, Optional, Dict, Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from api.models.database import Strategy, Vault

logger = logging.getLogger(__name__)

STRATEGIES_DIR = Path(__file__).parent / "strategies" / "deployed"


class LoadedStrategy:
    """A loaded strategy ready for execution."""

    def __init__(
        self,
        slug: str,
        generate_signals: Callable,
        meta: Dict[str, Any],
        code_path: Path,
    ):
        self.slug = slug
        self.generate_signals = generate_signals
        self.meta = meta
        self.code_path = code_path

    @property
    def asset(self) -> str:
        return self.meta.get("asset", "BTC")

    @property
    def timeframe(self) -> str:
        return self.meta.get("timeframe", "1H")

    @property
    def stop_loss_pct(self) -> float:
        return float(self.meta.get("stop_loss_pct", 0.02))

    @property
    def take_profit_pct(self) -> float:
        return float(self.meta.get("take_profit_pct", 0.05))


_strategy_cache: Dict[str, LoadedStrategy] = {}


def load_strategy_from_file(code_path: Path) -> LoadedStrategy:
    """Load a strategy module from a Python file."""
    if not code_path.exists():
        raise FileNotFoundError(f"Strategy file not found: {code_path}")

    slug = code_path.stem
    module_name = f"strategies.deployed.{slug}"

    spec = importlib.util.spec_from_file_location(module_name, code_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load strategy from {code_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)

    if not hasattr(module, "generate_signals"):
        raise AttributeError(f"Strategy {slug} missing generate_signals function")

    generate_signals = module.generate_signals
    meta = getattr(module, "STRATEGY_META", {})

    signature = inspect.signature(generate_signals)
    params = list(signature.parameters.values())
    if len(params) >= 2:
        config_cls = getattr(module, "StrategyConfig", None)
        default_config = config_cls() if config_cls else None
        raw_generate_signals = generate_signals

        def _wrapped_generate_signals(df, config=default_config):
            result = raw_generate_signals(df, config)
            if hasattr(result, "__getitem__") and "signal" in result:
                signal_series = result["signal"]
                mapping = {"BUY": 1, "SELL": -1, "HOLD": 0}
                mapped = signal_series.map(lambda x: mapping.get(x, x))
                return np.asarray(mapped, dtype=int)
            return result

        generate_signals = _wrapped_generate_signals

    logger.info("Loaded strategy %s from %s", slug, code_path)
    return LoadedStrategy(
        slug=slug,
        generate_signals=generate_signals,
        meta=meta,
        code_path=code_path,
    )


def get_cached_strategy(slug: str) -> Optional[LoadedStrategy]:
    return _strategy_cache.get(slug)


def cache_strategy(strategy: LoadedStrategy) -> None:
    _strategy_cache[strategy.slug] = strategy


def clear_cache() -> None:
    _strategy_cache.clear()


async def load_strategy_by_slug(db: AsyncSession, slug: str) -> Optional[LoadedStrategy]:
    query = select(Strategy).where(Strategy.slug == slug)
    result = await db.execute(query)
    strategy = result.scalar_one_or_none()

    if not strategy:
        return None

    code_path = _resolve_code_path(strategy)
    if not code_path:
        return None

    # Auto-fix missing code_path in DB
    if not strategy.code_path or strategy.code_path != str(code_path):
        strategy.code_path = str(code_path)
        await db.commit()

    cached = get_cached_strategy(strategy.slug)
    if cached:
        return cached

    loaded = load_strategy_from_file(code_path)
    loaded.meta.update({"strategy_id": strategy.id, "asset": strategy.asset, "timeframe": strategy.timeframe})
    cache_strategy(loaded)
    return loaded


def _resolve_code_path(strategy) -> Optional[Path]:
    """Resolve code_path from DB or auto-detect from deployed strategies directory."""
    if strategy.code_path:
        p = Path(strategy.code_path)
        if p.exists():
            return p
    # Auto-detect from deployed strategies directory by slug
    candidate = STRATEGIES_DIR / f"{strategy.slug}.py"
    if candidate.exists():
        return candidate
    return None


async def load_strategy_by_vault(db: AsyncSession, vault_address: str) -> Optional[LoadedStrategy]:
    query = (
        select(Vault)
        .options(selectinload(Vault.strategy))
        .where(Vault.address == vault_address.lower())
        .where(Vault.status == "active")
    )
    result = await db.execute(query)
    vault = result.scalar_one_or_none()

    if not vault or not vault.strategy:
        logger.warning("No active vault found: %s", vault_address)
        return None

    strategy = vault.strategy
    code_path = _resolve_code_path(strategy)
    if not code_path:
        logger.error("Strategy %s has no code_path and no deployed file found", strategy.slug)
        return None

    # Auto-fix missing code_path in DB
    if not strategy.code_path or strategy.code_path != str(code_path):
        strategy.code_path = str(code_path)
        await db.commit()
        logger.info("Auto-set code_path for %s → %s", strategy.slug, code_path)

    cached = get_cached_strategy(strategy.slug)
    if cached:
        return cached

    loaded = load_strategy_from_file(code_path)
    loaded.meta.update({"strategy_id": strategy.id, "asset": strategy.asset, "timeframe": strategy.timeframe})
    cache_strategy(loaded)
    return loaded


async def get_active_vaults_with_strategies(db: AsyncSession) -> list[tuple[str, str, str]]:
    query = (
        select(Vault.address, Strategy.slug, Strategy.timeframe)
        .join(Strategy, Vault.strategy_id == Strategy.id)
        .where(Vault.status == "active")
    )
    result = await db.execute(query)
    return [(row[0], row[1], row[2]) for row in result.fetchall()]
