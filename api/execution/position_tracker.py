"""Track positions and vault state from on-chain data."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import List

from web3 import Web3
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from api.config import settings
from api.execution.market_data import MarketDataFetcher
from api.execution.models import Position, VaultSnapshot
from api.models.database import PerformanceSnapshot, Vault
from api.onchain.gmx import get_symbol_for_market

logger = logging.getLogger(__name__)


class PositionTracker:
    PRICE_SCALE = 10**30
    USDC_DECIMALS = 10**6

    def __init__(self, market_data: MarketDataFetcher):
        self.web3 = Web3(Web3.HTTPProvider(settings.arbitrum_rpc_url))
        self.market_data = market_data
        self.pool_logic_abi = self._get_pool_logic_abi()
        self.managed_abi = self._get_managed_abi()
        self.gmx_reader_abi = self._get_gmx_reader_abi()

    async def get_vault_positions(self, vault_address: str) -> List[Position]:
        positions: list[Position] = []
        reader = self.web3.eth.contract(
            address=Web3.to_checksum_address(settings.gmx_reader),
            abi=self.gmx_reader_abi,
        )
        try:
            raw_positions = reader.functions.getAccountPositions(
                Web3.to_checksum_address(settings.gmx_data_store),
                Web3.to_checksum_address(vault_address),
                0,
                10,
            ).call()
        except Exception as exc:
            logger.warning("Failed to fetch GMX positions: %s", exc)
            return positions

        for raw in raw_positions:
            try:
                parsed = self._parse_gmx_position(raw)
                market_address = parsed["market"]
                asset = get_symbol_for_market(self.web3, market_address)
                size_usd = parsed["size_usd"]
                size_tokens = parsed["size_tokens"]
                collateral_usd = parsed["collateral_usd"]
                is_long = parsed["is_long"]
                if size_usd == 0:
                    continue
                try:
                    current_price = await self.market_data.get_current_price(asset)
                except Exception as exc:
                    logger.warning("Missing market price for %s: %s", asset, exc)
                    current_price = 0.0
                entry_price = current_price
                if size_tokens > 0:
                    entry_price = size_usd / size_tokens
                if current_price <= 0:
                    current_price = entry_price
                signed_size = size_tokens if is_long else -size_tokens
                unrealized_pnl = (current_price - entry_price) * signed_size
                leverage = (size_usd / collateral_usd) if collateral_usd > 0 else 0.0
                positions.append(
                    Position(
                        market_id=market_address,
                        asset=asset,
                        size=signed_size,
                        entry_price=entry_price,
                        current_price=current_price,
                        unrealized_pnl=unrealized_pnl,
                        leverage=leverage,
                    )
                )
            except Exception as exc:
                logger.warning("Failed to parse GMX position: %s", exc)
                continue
        return positions

    async def get_vault_tvl(self, vault_address: str) -> float:
        vault = self.web3.eth.contract(
            address=Web3.to_checksum_address(vault_address), abi=self.pool_logic_abi
        )
        try:
            tvl_wei = vault.functions.totalFundValue().call()
            return tvl_wei / 10**18
        except Exception as exc:
            logger.error("Failed to get TVL: %s", exc)
            return 0.0

    async def get_share_price(self, vault_address: str) -> float:
        vault = self.web3.eth.contract(
            address=Web3.to_checksum_address(vault_address), abi=self.pool_logic_abi
        )
        try:
            price_wei = vault.functions.tokenPrice().call()
            return price_wei / 10**18
        except Exception as exc:
            logger.error("Failed to get share price: %s", exc)
            return 1.0

    async def get_depositor_count(self, vault_address: str) -> int:
        vault = self.web3.eth.contract(
            address=Web3.to_checksum_address(vault_address), abi=self.pool_logic_abi
        )
        try:
            manager_logic = vault.functions.poolManagerLogic().call()
            managed = self.web3.eth.contract(
                address=Web3.to_checksum_address(manager_logic), abi=self.managed_abi
            )
            members = managed.functions.getMembers().call()
            return len(members)
        except Exception as exc:
            logger.error("Failed to get depositor count: %s", exc)
            return 0

    async def snapshot_vault(self, vault_address: str) -> VaultSnapshot:
        positions_task = self.get_vault_positions(vault_address)
        tvl_task = self.get_vault_tvl(vault_address)
        share_price_task = self.get_share_price(vault_address)
        depositor_task = self.get_depositor_count(vault_address)
        positions, tvl, share_price, depositors = await asyncio.gather(
            positions_task, tvl_task, share_price_task, depositor_task
        )
        total_pnl = sum(p.unrealized_pnl for p in positions)
        return VaultSnapshot(
            vault_address=vault_address,
            timestamp=datetime.utcnow(),
            tvl=tvl,
            share_price=share_price,
            depositor_count=depositors,
            positions=positions,
            total_unrealized_pnl=total_pnl,
        )

    def _get_pool_logic_abi(self) -> list:
        return [
            {
                "inputs": [],
                "name": "totalFundValue",
                "outputs": [{"type": "uint256"}],
                "stateMutability": "view",
                "type": "function",
            },
            {
                "inputs": [],
                "name": "tokenPrice",
                "outputs": [{"type": "uint256"}],
                "stateMutability": "view",
                "type": "function",
            },
            {
                "inputs": [],
                "name": "poolManagerLogic",
                "outputs": [{"type": "address"}],
                "stateMutability": "view",
                "type": "function",
            },
        ]

    def _get_managed_abi(self) -> list:
        return [
            {
                "inputs": [],
                "name": "getMembers",
                "outputs": [{"type": "address[]"}],
                "stateMutability": "view",
                "type": "function",
            }
        ]

    def _get_gmx_reader_abi(self) -> list:
        return [
            {
                "inputs": [
                    {"name": "dataStore", "type": "address"},
                    {"name": "account", "type": "address"},
                    {"name": "start", "type": "uint256"},
                    {"name": "end", "type": "uint256"},
                ],
                "name": "getAccountPositions",
                "outputs": [
                    {
                        "name": "positions",
                        "type": "tuple[]",
                        "components": [
                            {
                                "name": "addresses",
                                "type": "tuple",
                                "components": [
                                    {"name": "account", "type": "address"},
                                    {"name": "market", "type": "address"},
                                    {"name": "collateralToken", "type": "address"},
                                ],
                            },
                            {
                                "name": "numbers",
                                "type": "tuple",
                                "components": [
                                    {"name": "sizeInUsd", "type": "uint256"},
                                    {"name": "sizeInTokens", "type": "uint256"},
                                    {"name": "collateralAmount", "type": "uint256"},
                                    {"name": "borrowingFactor", "type": "uint256"},
                                    {"name": "fundingFeeAmountPerSize", "type": "uint256"},
                                    {"name": "longTokenClaimableFundingAmountPerSize", "type": "uint256"},
                                    {"name": "shortTokenClaimableFundingAmountPerSize", "type": "uint256"},
                                    {"name": "increasedAtBlock", "type": "uint256"},
                                    {"name": "decreasedAtBlock", "type": "uint256"},
                                    {"name": "increasedAtTime", "type": "uint256"},
                                    {"name": "decreasedAtTime", "type": "uint256"},
                                ],
                            },
                            {
                                "name": "flags",
                                "type": "tuple",
                                "components": [
                                    {"name": "isLong", "type": "bool"},
                                ],
                            },
                        ],
                    }
                ],
                "stateMutability": "view",
                "type": "function",
            }
        ]

    def _parse_gmx_position(self, raw_position) -> dict:
        addresses = raw_position[0] if isinstance(raw_position, (list, tuple)) else raw_position.get("addresses")
        numbers = raw_position[1] if isinstance(raw_position, (list, tuple)) else raw_position.get("numbers")
        flags = raw_position[2] if isinstance(raw_position, (list, tuple)) else raw_position.get("flags")
        market = addresses[1] if isinstance(addresses, (list, tuple)) else addresses.get("market")
        collateral_token = addresses[2] if isinstance(addresses, (list, tuple)) else addresses.get("collateralToken")
        size_in_usd = numbers[0]
        size_in_tokens = numbers[1]
        collateral_amount = numbers[2]
        is_long = flags[0] if isinstance(flags, (list, tuple)) else flags.get("isLong", True)
        return {
            "market": Web3.to_checksum_address(market),
            "collateral_token": Web3.to_checksum_address(collateral_token),
            "size_usd": float(size_in_usd) / self.PRICE_SCALE,
            "size_tokens": float(size_in_tokens) / self.PRICE_SCALE,  # GMX uses 1e30 precision
            "collateral_usd": float(collateral_amount) / self.USDC_DECIMALS,
            "is_long": bool(is_long),
        }


async def save_performance_snapshot(
    db: AsyncSession, snapshot: VaultSnapshot
) -> PerformanceSnapshot:
    addr = snapshot.vault_address.lower()
    db_snapshot = PerformanceSnapshot(
        vault_address=addr,
        timestamp=snapshot.timestamp,
        tvl=snapshot.tvl,
        share_price=snapshot.share_price,
        depositor_count=snapshot.depositor_count,
        positions_json=[vars(p) for p in snapshot.positions],
        unrealized_pnl=snapshot.total_unrealized_pnl,
    )
    db.add(db_snapshot)
    await db.execute(
        update(Vault)
        .where(Vault.address == addr)
        .values(
            tvl=snapshot.tvl,
            share_price=snapshot.share_price,
            depositor_count=snapshot.depositor_count,
        )
    )
    await db.commit()
    logger.info(
        "Snapshot saved: %s TVL=$%.2f SharePrice=$%.4f",
        snapshot.vault_address,
        snapshot.tvl,
        snapshot.share_price,
    )
    return db_snapshot


async def run_snapshot_job(
    db: AsyncSession, vault_address: str, market_data: MarketDataFetcher
) -> VaultSnapshot:
    tracker = PositionTracker(market_data)
    snapshot = await tracker.snapshot_vault(vault_address)
    await save_performance_snapshot(db, snapshot)
    return snapshot
