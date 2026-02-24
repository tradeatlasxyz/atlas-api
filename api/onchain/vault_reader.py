"""Read vault state and positions from chain with caching."""
from __future__ import annotations

from dataclasses import dataclass
import logging
import time
from typing import Optional, Callable, Any

from web3 import Web3

from api.config import settings
from api.onchain.gmx import get_symbol_for_market

logger = logging.getLogger(__name__)

@dataclass
class VaultPosition:
    market_id: str
    asset: str
    size: float
    unrealized_pnl: float


@dataclass
class VaultState:
    address: str
    tvl: float
    share_price: float
    total_supply: float
    manager: str


class VaultReader:
    PRICE_SCALE = 10**30
    USDC_DECIMALS = 10**6

    def __init__(
        self,
        web3: Optional[Web3] = None,
        cache_ttl: int = 300,
        max_retries: int = 2,
        backoff_seconds: float = 0.5,
    ) -> None:
        self.web3 = web3 or Web3(Web3.HTTPProvider(settings.arbitrum_rpc_url))
        self.cache_ttl = cache_ttl
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds
        self._cache: dict[str, tuple[object, float]] = {}
        self.pool_logic_abi = self._pool_logic_abi()
        self.managed_abi = self._managed_abi()
        self.gmx_reader_abi = self._gmx_reader_abi()

    def _get_cached(self, key: str) -> Optional[object]:
        value = self._cache.get(key)
        if not value:
            return None
        cached_value, ts = value
        if (time.time() - ts) > self.cache_ttl:
            self._cache.pop(key, None)
            return None
        return cached_value

    def _set_cache(self, key: str, value: object) -> None:
        self._cache[key] = (value, time.time())

    def _get_contract(self, vault_address: str):
        if not Web3.is_address(vault_address):
            raise ValueError(f"Invalid vault address: {vault_address}")
        return self.web3.eth.contract(
            address=Web3.to_checksum_address(vault_address),
            abi=self.pool_logic_abi,
        )

    def _get_managed_contract(self, address: str):
        if not Web3.is_address(address):
            raise ValueError(f"Invalid managed address: {address}")
        return self.web3.eth.contract(
            address=Web3.to_checksum_address(address),
            abi=self.managed_abi,
        )

    def _retry_call(self, fn: Callable[[], Any], cache_key: Optional[str] = None) -> Any:
        last_exc: Optional[Exception] = None
        for attempt in range(self.max_retries + 1):
            try:
                return fn()
            except Exception as exc:
                last_exc = exc
                if cache_key:
                    self._cache.pop(cache_key, None)
                if attempt >= self.max_retries:
                    break
                time.sleep(self.backoff_seconds * (2**attempt))
        raise RuntimeError(self._format_error(last_exc)) from last_exc

    def _format_error(self, exc: Optional[Exception]) -> str:
        if exc is None:
            return "Unknown RPC error"
        message = str(exc)
        if "execution reverted" in message:
            return message
        if "timeout" in message.lower():
            return f"RPC timeout: {message}"
        return message

    def get_tvl(self, vault_address: str) -> float:
        cache_key = f"{vault_address.lower()}:tvl"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached
        contract = self._get_contract(vault_address)
        try:
            tvl_wei = self._retry_call(
                lambda: contract.functions.totalFundValue().call(),
                cache_key=cache_key,
            )
        except Exception:
            tvl_wei = self._retry_call(
                lambda: contract.functions.tokenPriceWithoutManagerFee().call(),
                cache_key=cache_key,
            )
        tvl = tvl_wei / 10**18
        self._set_cache(cache_key, float(tvl))
        return float(tvl)

    def get_share_price(self, vault_address: str) -> float:
        cache_key = f"{vault_address.lower()}:share_price"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached
        contract = self._get_contract(vault_address)
        price_wei = self._retry_call(
            lambda: contract.functions.tokenPrice().call(),
            cache_key=cache_key,
        )
        price = price_wei / 10**18
        self._set_cache(cache_key, float(price))
        return float(price)

    def get_total_supply(self, vault_address: str) -> float:
        cache_key = f"{vault_address.lower()}:total_supply"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached
        contract = self._get_contract(vault_address)
        supply_wei = self._retry_call(
            lambda: contract.functions.totalSupply().call(),
            cache_key=cache_key,
        )
        supply = supply_wei / 10**18
        self._set_cache(cache_key, float(supply))
        return float(supply)

    def get_manager_address(self, vault_address: str) -> str:
        cache_key = f"{vault_address.lower()}:manager"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return Web3.to_checksum_address(str(cached))
        manager_logic = self.get_pool_manager_logic(vault_address)
        managed = self._get_managed_contract(manager_logic)
        manager = self._retry_call(lambda: managed.functions.manager().call(), cache_key=cache_key)
        self._set_cache(cache_key, manager)
        return Web3.to_checksum_address(manager)

    def get_trader_address(self, vault_address: str) -> str:
        cache_key = f"{vault_address.lower()}:trader"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return Web3.to_checksum_address(str(cached))
        manager_logic = self.get_pool_manager_logic(vault_address)
        managed = self._get_managed_contract(manager_logic)
        trader = self._retry_call(lambda: managed.functions.trader().call(), cache_key=cache_key)
        self._set_cache(cache_key, trader)
        return Web3.to_checksum_address(trader)

    def get_pool_manager_logic(self, vault_address: str) -> str:
        cache_key = f"{vault_address.lower()}:pool_manager_logic"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return Web3.to_checksum_address(str(cached))
        contract = self._get_contract(vault_address)
        manager_logic = self._retry_call(
            lambda: contract.functions.poolManagerLogic().call(),
            cache_key=cache_key,
        )
        self._set_cache(cache_key, manager_logic)
        return Web3.to_checksum_address(manager_logic)

    def get_supported_assets(self, vault_address: str) -> list[tuple[str, bool]]:
        manager_logic = self.get_pool_manager_logic(vault_address)
        abi = [
            {
                "inputs": [],
                "name": "getSupportedAssets",
                "outputs": [
                    {
                        "components": [
                            {"name": "asset", "type": "address"},
                            {"name": "isDeposit", "type": "bool"},
                        ],
                        "type": "tuple[]",
                    }
                ],
                "stateMutability": "view",
                "type": "function",
            }
        ]
        manager = self.web3.eth.contract(
            address=Web3.to_checksum_address(manager_logic), abi=abi
        )
        assets = self._retry_call(lambda: manager.functions.getSupportedAssets().call())
        return [(Web3.to_checksum_address(a[0]), bool(a[1])) for a in assets]

    def get_vault_state(self, vault_address: str) -> VaultState:
        return VaultState(
            address=vault_address,
            tvl=self.get_tvl(vault_address),
            share_price=self.get_share_price(vault_address),
            total_supply=self.get_total_supply(vault_address),
            manager=self.get_manager_address(vault_address),
        )

    def get_positions(self, vault_address: str) -> list[VaultPosition]:
        positions: list[VaultPosition] = []
        reader = self.web3.eth.contract(
            address=Web3.to_checksum_address(settings.gmx_reader),
            abi=self.gmx_reader_abi,
        )
        raw_positions = self._retry_call(
            lambda: reader.functions.getAccountPositions(
                Web3.to_checksum_address(settings.gmx_data_store),
                Web3.to_checksum_address(vault_address),
                0,
                10,
            ).call()
        )
        for raw in raw_positions:
            parsed = self._parse_gmx_position(raw)
            if parsed["size_usd"] == 0:
                continue
            asset = get_symbol_for_market(self.web3, parsed["market"])
            size_tokens = parsed["size_tokens"]
            signed_size = size_tokens if parsed["is_long"] else -size_tokens
            positions.append(
                VaultPosition(
                    market_id=parsed["market"],
                    asset=asset,
                    size=signed_size,
                    unrealized_pnl=0.0,
                )
            )
        return positions

    def _pool_logic_abi(self) -> list[dict]:
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
                "name": "tokenPriceWithoutManagerFee",
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
                "name": "totalSupply",
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

    def _managed_abi(self) -> list[dict]:
        return [
            {
                "inputs": [],
                "name": "manager",
                "outputs": [{"type": "address"}],
                "stateMutability": "view",
                "type": "function",
            },
            {
                "inputs": [],
                "name": "trader",
                "outputs": [{"type": "address"}],
                "stateMutability": "view",
                "type": "function",
            },
            {
                "inputs": [],
                "name": "getMembers",
                "outputs": [{"type": "address[]"}],
                "stateMutability": "view",
                "type": "function",
            },
        ]

    def _gmx_reader_abi(self) -> list[dict]:
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
