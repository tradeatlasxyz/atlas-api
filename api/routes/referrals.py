from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy.ext.asyncio import AsyncSession

from api.models.schemas import (
    ReferralAddressSummarySchema,
    ReferralAllocationResponseSchema,
    ReferralStatsSchema,
    ReferralVaultSummarySchema,
)
from api.services.database import get_db
from api.services.referrals import (
    get_referral_stats,
    get_referral_summary,
    get_vault_allocation,
    get_vault_referrals,
)


router = APIRouter(prefix="/api/referrals", tags=["Referrals"])

ADDRESS_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")


def normalize_address(address: str) -> str:
    if not ADDRESS_RE.match(address):
        raise HTTPException(status_code=422, detail="Invalid address")
    return address.lower()


@router.get(
    "/stats",
    response_model=ReferralStatsSchema,
    response_model_by_alias=True,
    summary="Get aggregate referral stats",
)
async def referrals_stats(db: AsyncSession = Depends(get_db)):
    payload = await get_referral_stats(db)
    return ReferralStatsSchema.model_validate(payload)


@router.get(
    "/vault/{vault_address}",
    response_model=ReferralVaultSummarySchema,
    response_model_by_alias=True,
    summary="Get referral summary for one vault",
)
async def referrals_for_vault(
    vault_address: str = Path(..., description="Vault address (0x... format)"),
    db: AsyncSession = Depends(get_db),
):
    normalized = normalize_address(vault_address)
    payload = await get_vault_referrals(db, normalized)
    return ReferralVaultSummarySchema.model_validate(payload)


@router.get(
    "/vault/{vault_address}/allocation",
    response_model=ReferralAllocationResponseSchema,
    response_model_by_alias=True,
    summary="Get per-referrer allocation weights for a vault",
)
async def referral_allocation_for_vault(
    vault_address: str = Path(..., description="Vault address (0x... format)"),
    db: AsyncSession = Depends(get_db),
):
    normalized = normalize_address(vault_address)
    payload = await get_vault_allocation(db, normalized)
    return ReferralAllocationResponseSchema.model_validate(payload)


@router.get(
    "/{address}",
    response_model=ReferralAddressSummarySchema,
    response_model_by_alias=True,
    summary="Get referral profile for one address",
)
async def referrals_for_address(
    address: str = Path(..., description="Referrer wallet address (0x... format)"),
    db: AsyncSession = Depends(get_db),
):
    normalized = normalize_address(address)
    payload = await get_referral_summary(db, normalized)
    return ReferralAddressSummarySchema.model_validate(payload)
