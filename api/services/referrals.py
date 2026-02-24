from __future__ import annotations

from decimal import Decimal
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.models.database import ReferralAbuseReview, ReferralAttribution, ReferralRewardClaim


ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
ZERO_CODE = f"0x{'0' * 64}"


def _to_int(value: Optional[int | Decimal]) -> int:
    if value is None:
        return 0
    if isinstance(value, Decimal):
        return int(value)
    return int(value)


def _to_wei_string(value: Optional[int | Decimal]) -> str:
    return str(_to_int(value))


def _is_non_zero_code(value: Optional[str]) -> bool:
    return bool(value) and value.lower() != ZERO_CODE


def _is_non_zero_address(value: Optional[str]) -> bool:
    return bool(value) and value.lower() != ZERO_ADDRESS


def _attribution_to_payload(row: ReferralAttribution) -> dict:
    return {
        "event_type": row.event_type,
        "vault_address": row.vault_address,
        "trader_address": row.trader_address,
        "referrer_address": row.referrer_address,
        "referral_code": row.referral_code,
        "deposit_amount_wei": _to_wei_string(row.deposit_amount_wei),
        "shares_wei": _to_wei_string(row.shares_wei),
        "tx_hash": row.tx_hash,
        "block_number": int(row.block_number),
        "block_timestamp": row.block_timestamp,
    }


def _claim_to_payload(row: ReferralRewardClaim) -> dict:
    return {
        "referrer_address": row.referrer_address,
        "amount_wei": _to_wei_string(row.amount_wei),
        "tx_hash": row.tx_hash,
        "block_number": int(row.block_number),
        "block_timestamp": row.block_timestamp,
    }


async def get_referral_summary(db: AsyncSession, address: str) -> dict:
    normalized = address.lower()

    stats_result = await db.execute(
        select(
            func.count(ReferralAttribution.id),
            func.count(func.distinct(ReferralAttribution.trader_address)),
            func.coalesce(func.sum(ReferralAttribution.deposit_amount_wei), 0),
        ).where(
            ReferralAttribution.event_type == "ReferredDeposit",
            ReferralAttribution.referrer_address == normalized,
        )
    )
    referred_deposits, referred_users, referred_volume = stats_result.one()

    claim_result = await db.execute(
        select(
            func.coalesce(func.sum(ReferralRewardClaim.amount_wei), 0),
        ).where(ReferralRewardClaim.referrer_address == normalized)
    )
    total_claimed = claim_result.scalar_one()

    code_result = await db.execute(
        select(ReferralAttribution.referral_code)
        .where(
            ReferralAttribution.referrer_address == normalized,
            ReferralAttribution.referral_code.is_not(None),
        )
        .distinct()
    )
    referral_codes = [code for code in code_result.scalars().all() if _is_non_zero_code(code)]

    latest_attribution_rows = await db.execute(
        select(ReferralAttribution)
        .where(
            ReferralAttribution.event_type == "ReferredDeposit",
            ReferralAttribution.referrer_address == normalized,
        )
        .order_by(ReferralAttribution.block_number.desc(), ReferralAttribution.log_index.desc())
        .limit(25)
    )
    latest_claim_rows = await db.execute(
        select(ReferralRewardClaim)
        .where(ReferralRewardClaim.referrer_address == normalized)
        .order_by(ReferralRewardClaim.block_number.desc(), ReferralRewardClaim.log_index.desc())
        .limit(25)
    )

    return {
        "address": normalized,
        "referral_codes": sorted(referral_codes),
        "referred_users": int(referred_users or 0),
        "referred_deposits": int(referred_deposits or 0),
        "referred_volume_wei": _to_wei_string(referred_volume),
        "total_claimed_wei": _to_wei_string(total_claimed),
        "latest_attributions": [_attribution_to_payload(row) for row in latest_attribution_rows.scalars().all()],
        "latest_claims": [_claim_to_payload(row) for row in latest_claim_rows.scalars().all()],
    }


async def get_vault_referrals(db: AsyncSession, vault_address: str) -> dict:
    normalized_vault = vault_address.lower()

    summary_result = await db.execute(
        select(
            func.count(ReferralAttribution.id),
            func.count(func.distinct(ReferralAttribution.referrer_address)),
            func.coalesce(func.sum(ReferralAttribution.deposit_amount_wei), 0),
        ).where(
            ReferralAttribution.event_type == "ReferredDeposit",
            ReferralAttribution.vault_address == normalized_vault,
            ReferralAttribution.referrer_address.is_not(None),
            ReferralAttribution.referrer_address != ZERO_ADDRESS,
        )
    )
    referred_deposits, unique_referrers, referred_volume = summary_result.one()

    attribution_rows = await db.execute(
        select(ReferralAttribution)
        .where(
            ReferralAttribution.event_type == "ReferredDeposit",
            ReferralAttribution.vault_address == normalized_vault,
        )
        .order_by(ReferralAttribution.block_number.desc(), ReferralAttribution.log_index.desc())
        .limit(100)
    )

    return {
        "vault_address": normalized_vault,
        "referred_deposits": int(referred_deposits or 0),
        "unique_referrers": int(unique_referrers or 0),
        "referred_volume_wei": _to_wei_string(referred_volume),
        "attributions": [_attribution_to_payload(row) for row in attribution_rows.scalars().all()],
    }


async def get_vault_allocation(db: AsyncSession, vault_address: str) -> dict:
    normalized_vault = vault_address.lower()

    allocation_rows = await db.execute(
        select(
            ReferralAttribution.referrer_address,
            func.count(ReferralAttribution.id).label("referred_deposits"),
            func.coalesce(func.sum(ReferralAttribution.deposit_amount_wei), 0).label("referred_volume_wei"),
        )
        .where(
            ReferralAttribution.event_type == "ReferredDeposit",
            ReferralAttribution.vault_address == normalized_vault,
            ReferralAttribution.referrer_address.is_not(None),
            ReferralAttribution.referrer_address != ZERO_ADDRESS,
        )
        .group_by(ReferralAttribution.referrer_address)
        .order_by(func.coalesce(func.sum(ReferralAttribution.deposit_amount_wei), 0).desc())
    )

    grouped = allocation_rows.all()
    total_volume = sum(_to_int(row.referred_volume_wei) for row in grouped)

    allocations: list[dict] = []
    running_bps = 0
    for index, row in enumerate(grouped):
        volume = _to_int(row.referred_volume_wei)
        share = (volume / total_volume) if total_volume > 0 else 0.0
        if index == len(grouped) - 1:
            allocation_bps = max(0, 10_000 - running_bps) if total_volume > 0 else 0
        else:
            allocation_bps = int(share * 10_000) if total_volume > 0 else 0
            running_bps += allocation_bps

        allocations.append(
            {
                "referrer_address": row.referrer_address,
                "referred_volume_wei": str(volume),
                "referred_deposits": int(row.referred_deposits or 0),
                "allocation_bps": allocation_bps,
                "allocation_share": share,
            }
        )

    return {
        "vault_address": normalized_vault,
        "total_volume_wei": str(total_volume),
        "allocations": allocations,
    }


async def get_referral_stats(db: AsyncSession) -> dict:
    referral_result = await db.execute(
        select(
            func.count(ReferralAttribution.id),
            func.count(func.distinct(ReferralAttribution.referrer_address)),
            func.count(func.distinct(ReferralAttribution.trader_address)),
            func.coalesce(func.sum(ReferralAttribution.deposit_amount_wei), 0),
        ).where(
            ReferralAttribution.event_type == "ReferredDeposit",
            ReferralAttribution.referrer_address.is_not(None),
            ReferralAttribution.referrer_address != ZERO_ADDRESS,
        )
    )
    referred_deposits, unique_referrers, unique_referred_users, referred_volume = referral_result.one()

    claimed_result = await db.execute(select(func.coalesce(func.sum(ReferralRewardClaim.amount_wei), 0)))
    claimed_rewards = claimed_result.scalar_one()

    return {
        "referred_deposits": int(referred_deposits or 0),
        "unique_referrers": int(unique_referrers or 0),
        "unique_referred_users": int(unique_referred_users or 0),
        "referred_volume_wei": _to_wei_string(referred_volume),
        "claimed_rewards_wei": _to_wei_string(claimed_rewards),
    }


async def scan_suspicious_patterns(db: AsyncSession) -> list[dict]:
    issues: list[dict] = []

    self_referral_rows = await db.execute(
        select(
            ReferralAttribution.referrer_address,
            ReferralAttribution.trader_address,
            ReferralAttribution.vault_address,
            func.count(ReferralAttribution.id).label("count"),
        )
        .where(
            ReferralAttribution.event_type == "ReferredDeposit",
            ReferralAttribution.referrer_address.is_not(None),
            ReferralAttribution.trader_address.is_not(None),
            func.lower(ReferralAttribution.referrer_address) == func.lower(ReferralAttribution.trader_address),
        )
        .group_by(
            ReferralAttribution.referrer_address,
            ReferralAttribution.trader_address,
            ReferralAttribution.vault_address,
        )
    )
    for row in self_referral_rows.all():
        issues.append(
            {
                "issue_type": "self_referral",
                "severity": "high",
                "description": "Referrer and trader addresses match for one or more deposits.",
                "metadata": {
                    "referrer_address": row.referrer_address,
                    "trader_address": row.trader_address,
                    "vault_address": row.vault_address,
                    "count": int(row.count),
                },
            }
        )

    repeated_pair_rows = await db.execute(
        select(
            ReferralAttribution.referrer_address,
            ReferralAttribution.trader_address,
            ReferralAttribution.vault_address,
            func.count(ReferralAttribution.id).label("count"),
        )
        .where(
            ReferralAttribution.event_type == "ReferredDeposit",
            ReferralAttribution.referrer_address.is_not(None),
            ReferralAttribution.trader_address.is_not(None),
        )
        .group_by(
            ReferralAttribution.referrer_address,
            ReferralAttribution.trader_address,
            ReferralAttribution.vault_address,
        )
        .having(func.count(ReferralAttribution.id) >= 3)
    )
    for row in repeated_pair_rows.all():
        issues.append(
            {
                "issue_type": "repeat_pair",
                "severity": "medium",
                "description": "Same referrer/trader pair has repeated referred deposits in one vault.",
                "metadata": {
                    "referrer_address": row.referrer_address,
                    "trader_address": row.trader_address,
                    "vault_address": row.vault_address,
                    "count": int(row.count),
                },
            }
        )

    concentration_rows = await db.execute(
        select(
            ReferralAttribution.vault_address,
            ReferralAttribution.referrer_address,
            func.count(ReferralAttribution.id).label("count"),
            func.coalesce(func.sum(ReferralAttribution.deposit_amount_wei), 0).label("volume"),
        )
        .where(
            ReferralAttribution.event_type == "ReferredDeposit",
            ReferralAttribution.referrer_address.is_not(None),
            ReferralAttribution.referrer_address != ZERO_ADDRESS,
            ReferralAttribution.vault_address.is_not(None),
        )
        .group_by(ReferralAttribution.vault_address, ReferralAttribution.referrer_address)
    )
    vault_rows: dict[str, list] = {}
    for row in concentration_rows.all():
        if not row.vault_address:
            continue
        vault_rows.setdefault(row.vault_address, []).append(row)

    for vault_address, rows in vault_rows.items():
        total_deposits = sum(int(row.count) for row in rows)
        if total_deposits < 5:
            continue
        top_row = max(rows, key=lambda item: int(item.count))
        share = int(top_row.count) / total_deposits if total_deposits else 0
        if share >= 0.8:
            issues.append(
                {
                    "issue_type": "concentrated_referrer",
                    "severity": "medium",
                    "description": "Single referrer controls the large majority of referral deposits for a vault.",
                    "metadata": {
                        "vault_address": vault_address,
                        "referrer_address": top_row.referrer_address,
                        "share": share,
                        "top_deposits": int(top_row.count),
                        "total_deposits": total_deposits,
                    },
                }
            )

    return issues


async def create_abuse_review(
    db: AsyncSession,
    *,
    referrer_address: Optional[str],
    issue_type: str,
    reason: str,
    notes: Optional[str] = None,
    details: Optional[dict] = None,
) -> dict:
    review = ReferralAbuseReview(
        referrer_address=referrer_address.lower() if referrer_address else None,
        issue_type=issue_type,
        status="open",
        reason=reason,
        notes=notes,
        details=details,
    )
    db.add(review)
    await db.commit()
    await db.refresh(review)

    return {
        "id": review.id,
        "status": review.status,
        "issue_type": review.issue_type,
        "referrer_address": review.referrer_address,
        "reason": review.reason,
        "notes": review.notes,
    }
