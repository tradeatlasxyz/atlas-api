from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from api.models.schemas import StrategyDiscoveryResponse, StrategyDiscoverySchema
from api.services.database import get_db
from api.services.strategy import get_strategy_discoveries, strategy_to_discovery_dict

router = APIRouter()


@router.get(
    "/strategies/discoveries",
    response_model=StrategyDiscoveryResponse,
    response_model_by_alias=True,
    summary="List Strategy Discoveries",
    description="Paginated list of discovered strategies with filtering and sorting.",
)
async def list_strategy_discoveries(
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    limit: int = Query(10, ge=1, le=100, description="Items per page"),
    asset: Optional[str] = Query(None, description="Filter by asset (BTC, ETH, etc.)"),
    timeframe: Optional[str] = Query(None, description="Filter by timeframe (15m, 1H, 4H, 1D)"),
    strategyType: Optional[str] = Query(None, alias="strategyType", description="Strategy type"),
    status: Optional[str] = Query(None, description="Status (preview, deployable, deployed)"),
    featured: Optional[bool] = Query(None, description="Featured only"),
    passedCuration: Optional[bool] = Query(None, alias="passedCuration", description="Curated only"),
    sort: str = Query("latest", description="Sort by: latest, winrate, sharpe, return"),
    db: AsyncSession = Depends(get_db),
):
    allowed_sorts = {"latest", "winrate", "sharpe", "return"}
    if sort not in allowed_sorts:
        raise HTTPException(
            status_code=422,
            detail="Invalid sort. Must be one of: latest, winrate, sharpe, return",
        )

    strategies, total = await get_strategy_discoveries(
        db,
        page=page,
        limit=limit,
        asset=asset,
        timeframe=timeframe,
        strategy_type=strategyType,
        status=status,
        featured=featured,
        passed_curation=passedCuration,
        sort=sort,
    )

    strategy_dicts = [strategy_to_discovery_dict(strategy) for strategy in strategies]
    payload = [StrategyDiscoverySchema.model_validate(item) for item in strategy_dicts]

    return StrategyDiscoveryResponse(
        strategies=payload,
        total=total,
        page=page,
        limit=limit,
    )
