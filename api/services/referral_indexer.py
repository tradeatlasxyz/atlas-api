from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select
from web3 import Web3

from api.config import settings
from api.models.database import ReferralAttribution, ReferralIndexerState, ReferralRewardClaim
from api.services.database import async_session


logger = logging.getLogger(__name__)

ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
ZERO_CODE = f"0x{'0' * 64}"


class ReferralEventIndexer:
    def __init__(self, web3_client: Optional[Web3] = None) -> None:
        self.chain_id = settings.referral_chain_id
        self.state_key = f"referrals:{self.chain_id}"
        self.enabled = bool(
            settings.referral_indexer_enabled
            and settings.arbitrum_rpc_url
            and settings.referral_registry_address
            and settings.referral_deposit_router_address
            and settings.referral_reward_pool_address
        )

        self.web3 = web3_client
        self.registry_contract = None
        self.deposit_router_contract = None
        self.reward_pool_contract = None

        if not self.enabled:
            return

        self.web3 = web3_client or Web3(Web3.HTTPProvider(settings.arbitrum_rpc_url))
        if self.web3 is None:
            self.enabled = False
            return

        self.registry_contract = self.web3.eth.contract(
            address=Web3.to_checksum_address(settings.referral_registry_address),
            abi=[
                {
                    "anonymous": False,
                    "inputs": [
                        {"indexed": True, "internalType": "address", "name": "vault", "type": "address"},
                        {"indexed": True, "internalType": "address", "name": "trader", "type": "address"},
                        {"indexed": True, "internalType": "bytes32", "name": "code", "type": "bytes32"},
                        {"indexed": False, "internalType": "address", "name": "referrer", "type": "address"},
                    ],
                    "name": "TraderReferralCodeSet",
                    "type": "event",
                }
            ],
        )
        self.deposit_router_contract = self.web3.eth.contract(
            address=Web3.to_checksum_address(settings.referral_deposit_router_address),
            abi=[
                {
                    "anonymous": False,
                    "inputs": [
                        {"indexed": True, "internalType": "address", "name": "vault", "type": "address"},
                        {"indexed": True, "internalType": "address", "name": "trader", "type": "address"},
                        {"indexed": True, "internalType": "bytes32", "name": "referralCode", "type": "bytes32"},
                        {"indexed": False, "internalType": "uint256", "name": "amount", "type": "uint256"},
                        {"indexed": False, "internalType": "uint256", "name": "shares", "type": "uint256"},
                    ],
                    "name": "ReferredDeposit",
                    "type": "event",
                }
            ],
        )
        self.reward_pool_contract = self.web3.eth.contract(
            address=Web3.to_checksum_address(settings.referral_reward_pool_address),
            abi=[
                {
                    "anonymous": False,
                    "inputs": [
                        {"indexed": True, "internalType": "address", "name": "referrer", "type": "address"},
                        {"indexed": False, "internalType": "uint256", "name": "amount", "type": "uint256"},
                    ],
                    "name": "RewardClaimed",
                    "type": "event",
                }
            ],
        )

    async def index_once(self) -> dict:
        if not self.enabled or self.web3 is None:
            return {"status": "disabled"}

        latest_chain_block = int(self.web3.eth.block_number)
        max_indexable_block = latest_chain_block - settings.referral_indexer_confirmations
        if max_indexable_block < settings.referral_indexer_start_block:
            return {"status": "waiting"}

        async with async_session() as db:
            state = await self._get_or_create_state(db)
            from_block = max(int(state.last_processed_block) + 1, settings.referral_indexer_start_block)
            if from_block > max_indexable_block:
                return {
                    "status": "idle",
                    "last_processed_block": int(state.last_processed_block),
                }

            to_block = min(
                from_block + settings.referral_indexer_chunk_size - 1,
                max_indexable_block,
            )
            try:
                processed = 0
                block_timestamps: dict[int, datetime] = {}

                processed += await self._index_trader_referral_code_set(
                    db, from_block, to_block, block_timestamps
                )
                processed += await self._index_referred_deposits(
                    db, from_block, to_block, block_timestamps
                )
                processed += await self._index_reward_claimed(
                    db, from_block, to_block, block_timestamps
                )

                state.last_processed_block = to_block
                state.updated_at = datetime.now(timezone.utc)
                await db.commit()

                return {
                    "status": "indexed",
                    "from_block": from_block,
                    "to_block": to_block,
                    "processed_events": processed,
                }
            except Exception:
                await db.rollback()
                raise

    async def _get_or_create_state(self, db) -> ReferralIndexerState:
        result = await db.execute(
            select(ReferralIndexerState).where(ReferralIndexerState.indexer_key == self.state_key)
        )
        state = result.scalar_one_or_none()
        if state:
            return state

        state = ReferralIndexerState(
            indexer_key=self.state_key,
            chain_id=self.chain_id,
            last_processed_block=max(settings.referral_indexer_start_block - 1, 0),
        )
        db.add(state)
        await db.flush()
        return state

    async def _index_trader_referral_code_set(
        self,
        db,
        from_block: int,
        to_block: int,
        block_timestamps: dict[int, datetime],
    ) -> int:
        if self.registry_contract is None:
            return 0

        logs = self.registry_contract.events.TraderReferralCodeSet().get_logs(
            fromBlock=from_block,
            toBlock=to_block,
        )
        processed = 0
        for log in logs:
            tx_hash = log["transactionHash"].hex()
            log_index = int(log["logIndex"])
            if await self._attribution_exists(db, tx_hash, log_index):
                continue

            block_number = int(log["blockNumber"])
            event = log["args"]
            code = self._normalize_code(event.get("code"))
            block_timestamp = self._resolve_block_timestamp(block_number, block_timestamps)

            row = ReferralAttribution(
                chain_id=self.chain_id,
                event_type="TraderReferralCodeSet",
                vault_address=str(event.get("vault")).lower(),
                trader_address=str(event.get("trader")).lower(),
                referral_code=code,
                referrer_address=str(event.get("referrer")).lower(),
                tx_hash=tx_hash,
                log_index=log_index,
                block_number=block_number,
                block_timestamp=block_timestamp,
                metadata_json={"contract": settings.referral_registry_address.lower()},
            )
            db.add(row)
            processed += 1

        return processed

    async def _index_referred_deposits(
        self,
        db,
        from_block: int,
        to_block: int,
        block_timestamps: dict[int, datetime],
    ) -> int:
        if self.deposit_router_contract is None:
            return 0

        logs = self.deposit_router_contract.events.ReferredDeposit().get_logs(
            fromBlock=from_block,
            toBlock=to_block,
        )
        processed = 0
        for log in logs:
            tx_hash = log["transactionHash"].hex()
            log_index = int(log["logIndex"])
            if await self._attribution_exists(db, tx_hash, log_index):
                continue

            block_number = int(log["blockNumber"])
            event = log["args"]
            vault_address = str(event.get("vault")).lower()
            trader_address = str(event.get("trader")).lower()
            referral_code = self._normalize_code(event.get("referralCode"))
            referrer = await self._lookup_referrer(
                db,
                vault_address=vault_address,
                trader_address=trader_address,
                referral_code=referral_code,
                block_number=block_number,
            )
            block_timestamp = self._resolve_block_timestamp(block_number, block_timestamps)

            row = ReferralAttribution(
                chain_id=self.chain_id,
                event_type="ReferredDeposit",
                vault_address=vault_address,
                trader_address=trader_address,
                referral_code=referral_code,
                referrer_address=referrer,
                deposit_amount_wei=int(event.get("amount") or 0),
                shares_wei=int(event.get("shares") or 0),
                tx_hash=tx_hash,
                log_index=log_index,
                block_number=block_number,
                block_timestamp=block_timestamp,
                metadata_json={"contract": settings.referral_deposit_router_address.lower()},
            )
            db.add(row)
            processed += 1

        return processed

    async def _index_reward_claimed(
        self,
        db,
        from_block: int,
        to_block: int,
        block_timestamps: dict[int, datetime],
    ) -> int:
        if self.reward_pool_contract is None:
            return 0

        logs = self.reward_pool_contract.events.RewardClaimed().get_logs(
            fromBlock=from_block,
            toBlock=to_block,
        )
        processed = 0
        for log in logs:
            tx_hash = log["transactionHash"].hex()
            log_index = int(log["logIndex"])
            exists_result = await db.execute(
                select(ReferralRewardClaim.id).where(
                    ReferralRewardClaim.chain_id == self.chain_id,
                    ReferralRewardClaim.tx_hash == tx_hash,
                    ReferralRewardClaim.log_index == log_index,
                )
            )
            if exists_result.scalar_one_or_none() is not None:
                continue

            block_number = int(log["blockNumber"])
            event = log["args"]
            block_timestamp = self._resolve_block_timestamp(block_number, block_timestamps)

            row = ReferralRewardClaim(
                chain_id=self.chain_id,
                referrer_address=str(event.get("referrer")).lower(),
                amount_wei=int(event.get("amount") or 0),
                tx_hash=tx_hash,
                log_index=log_index,
                block_number=block_number,
                block_timestamp=block_timestamp,
                metadata_json={"contract": settings.referral_reward_pool_address.lower()},
            )
            db.add(row)
            processed += 1

        return processed

    async def _attribution_exists(self, db, tx_hash: str, log_index: int) -> bool:
        exists_result = await db.execute(
            select(ReferralAttribution.id).where(
                ReferralAttribution.chain_id == self.chain_id,
                ReferralAttribution.tx_hash == tx_hash,
                ReferralAttribution.log_index == log_index,
            )
        )
        return exists_result.scalar_one_or_none() is not None

    async def _lookup_referrer(
        self,
        db,
        *,
        vault_address: str,
        trader_address: str,
        referral_code: str,
        block_number: int,
    ) -> Optional[str]:
        if referral_code == ZERO_CODE:
            return None

        result = await db.execute(
            select(ReferralAttribution.referrer_address)
            .where(
                ReferralAttribution.event_type == "TraderReferralCodeSet",
                ReferralAttribution.vault_address == vault_address,
                ReferralAttribution.trader_address == trader_address,
                ReferralAttribution.referral_code == referral_code,
                ReferralAttribution.block_number <= block_number,
            )
            .order_by(ReferralAttribution.block_number.desc(), ReferralAttribution.log_index.desc())
            .limit(1)
        )
        referrer = result.scalar_one_or_none()
        if referrer and referrer != ZERO_ADDRESS:
            return referrer
        return None

    def _resolve_block_timestamp(
        self, block_number: int, cache: dict[int, datetime]
    ) -> datetime:
        cached = cache.get(block_number)
        if cached:
            return cached

        assert self.web3 is not None
        block = self.web3.eth.get_block(block_number)
        timestamp = datetime.fromtimestamp(int(block["timestamp"]), tz=timezone.utc)
        cache[block_number] = timestamp
        return timestamp

    @staticmethod
    def _normalize_code(value: Any) -> str:
        if value is None:
            return ZERO_CODE
        normalized = Web3.to_hex(value)
        if len(normalized) == 66:
            return normalized.lower()
        if len(normalized) < 66:
            return ("0x" + normalized[2:].rjust(64, "0")).lower()
        return normalized[:66].lower()
