from __future__ import annotations

import pytest
from sqlalchemy import select

from api.config import settings
from api.models.database import ReferralIndexerState
from api.services import referral_indexer as referral_indexer_module
from api.services.referral_indexer import ReferralEventIndexer


class _DummyContract:
    class _Events:
        class _Event:
            def get_logs(self, **_kwargs):
                return []

        def TraderReferralCodeSet(self):
            return self._Event()

        def ReferredDeposit(self):
            return self._Event()

        def RewardClaimed(self):
            return self._Event()

    def __init__(self):
        self.events = self._Events()


class _DummyEth:
    def __init__(self, block_number: int):
        self.block_number = block_number

    def contract(self, **_kwargs):
        return _DummyContract()

    def get_block(self, block_number: int):
        return {"timestamp": block_number}


class _DummyWeb3:
    def __init__(self, block_number: int):
        self.eth = _DummyEth(block_number)


class _SessionFactory:
    def __init__(self, session):
        self._session = session

    def __call__(self):
        return self

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _configure_referral_settings(monkeypatch, *, start_block: int = 0, chunk_size: int = 100, confirmations: int = 0):
    monkeypatch.setattr(settings, "referral_indexer_enabled", True)
    monkeypatch.setattr(settings, "arbitrum_rpc_url", "https://arb1.example")
    monkeypatch.setattr(settings, "referral_registry_address", "0x1111111111111111111111111111111111111111")
    monkeypatch.setattr(settings, "referral_deposit_router_address", "0x2222222222222222222222222222222222222222")
    monkeypatch.setattr(settings, "referral_reward_pool_address", "0x3333333333333333333333333333333333333333")
    monkeypatch.setattr(settings, "referral_indexer_start_block", start_block)
    monkeypatch.setattr(settings, "referral_indexer_chunk_size", chunk_size)
    monkeypatch.setattr(settings, "referral_indexer_confirmations", confirmations)


@pytest.mark.asyncio
async def test_referral_indexer_updates_block_state(db_session, monkeypatch):
    _configure_referral_settings(monkeypatch, start_block=100, chunk_size=5, confirmations=0)
    monkeypatch.setattr(referral_indexer_module, "async_session", _SessionFactory(db_session))

    indexer = ReferralEventIndexer(web3_client=_DummyWeb3(block_number=110))

    async def fake_trader(*_args, **_kwargs):
        return 2

    async def fake_deposits(*_args, **_kwargs):
        return 3

    async def fake_claims(*_args, **_kwargs):
        return 4

    monkeypatch.setattr(indexer, "_index_trader_referral_code_set", fake_trader)
    monkeypatch.setattr(indexer, "_index_referred_deposits", fake_deposits)
    monkeypatch.setattr(indexer, "_index_reward_claimed", fake_claims)

    result = await indexer.index_once()
    assert result["status"] == "indexed"
    assert result["from_block"] == 100
    assert result["to_block"] == 104
    assert result["processed_events"] == 9

    state_result = await db_session.execute(
        select(ReferralIndexerState).where(ReferralIndexerState.indexer_key == "referrals:42161")
    )
    state = state_result.scalar_one()
    assert state.last_processed_block == 104


@pytest.mark.asyncio
async def test_referral_indexer_is_idempotent_without_new_blocks(db_session, monkeypatch):
    _configure_referral_settings(monkeypatch, start_block=50, chunk_size=10, confirmations=0)
    monkeypatch.setattr(referral_indexer_module, "async_session", _SessionFactory(db_session))

    indexer = ReferralEventIndexer(web3_client=_DummyWeb3(block_number=55))
    calls = {"count": 0}

    async def fake_events(*_args, **_kwargs):
        calls["count"] += 1
        return 0

    monkeypatch.setattr(indexer, "_index_trader_referral_code_set", fake_events)
    monkeypatch.setattr(indexer, "_index_referred_deposits", fake_events)
    monkeypatch.setattr(indexer, "_index_reward_claimed", fake_events)

    first = await indexer.index_once()
    assert first["status"] == "indexed"

    calls_before = calls["count"]
    second = await indexer.index_once()
    assert second["status"] == "idle"
    assert calls["count"] == calls_before
