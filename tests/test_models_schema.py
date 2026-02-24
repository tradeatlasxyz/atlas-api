from api.models import database


def test_strategy_slug_unique() -> None:
    slug_col = database.Strategy.__table__.columns["slug"]
    assert slug_col.unique is True


def test_investor_report_strategy_fk() -> None:
    fks = list(database.InvestorReport.__table__.columns["strategy_id"].foreign_keys)
    assert fks
    fk = fks[0]
    assert fk.column.table.name == "strategies"


def test_referral_attribution_unique_event_constraint() -> None:
    constraints = {
        constraint.name
        for constraint in database.ReferralAttribution.__table__.constraints
        if getattr(constraint, "name", None)
    }
    assert "uq_referral_attr_chain_tx_log" in constraints


def test_referral_claim_unique_event_constraint() -> None:
    constraints = {
        constraint.name
        for constraint in database.ReferralRewardClaim.__table__.constraints
        if getattr(constraint, "name", None)
    }
    assert "uq_referral_claim_chain_tx_log" in constraints
