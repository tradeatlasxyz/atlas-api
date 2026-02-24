"""Execute trades on GMX V2 via dHEDGE vaults."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from eth_account import Account
from eth_account.signers.local import LocalAccount
from web3 import Web3

from api.config import settings
from api.execution.models import Signal
from api.onchain.gmx import get_market_address_for_asset, get_market_long_token

logger = logging.getLogger(__name__)


@dataclass
class TradeResult:
    success: bool
    tx_hash: Optional[str]
    error: Optional[str]
    gas_used: int
    timestamp: datetime
    direction: int
    asset: str
    size: float
    entry_price: float

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "tx_hash": self.tx_hash,
            "error": self.error,
            "gas_used": self.gas_used,
            "timestamp": self.timestamp.isoformat(),
            "direction": self.direction,
            "asset": self.asset,
            "size": self.size,
            "entry_price": self.entry_price,
        }


@dataclass
class TradePayload:
    calldata: bytes
    execution_fee: int
    value: int
    size_usd: float
    gas_limit: int

    def to_dict(self) -> dict:
        return {
            "calldata": self.calldata.hex(),
            "execution_fee": self.execution_fee,
            "value": self.value,
            "size_usd": self.size_usd,
            "gas_limit": self.gas_limit,
        }


class TradeExecutor:
    PRICE_SCALE = 10**30
    USDC_DECIMALS = 10**6
    DEFAULT_GAS_LIMIT = 800000

    def __init__(self) -> None:
        self.web3 = Web3(Web3.HTTPProvider(settings.arbitrum_rpc_url))
        if settings.trader_private_key:
            self.trader: LocalAccount = Account.from_key(settings.trader_private_key)
        else:
            self.trader = None
        self.pool_logic_abi = self._get_pool_logic_abi()
        self.exchange_router_abi = self._get_exchange_router_abi()
        if self.trader:
            logger.info("Trade executor initialized. Trader: %s", self.trader.address)

    async def execute_trade(
        self,
        signal: Signal,
        vault_address: str,
        size_usd_override: Optional[float] = None,
    ) -> TradeResult:
        if not signal.is_actionable:
            return TradeResult(
                success=True,
                tx_hash=None,
                error="Signal not actionable",
                gas_used=0,
                timestamp=datetime.utcnow(),
                direction=0,
                asset=signal.asset,
                size=0.0,
                entry_price=signal.current_price,
            )
        if not settings.trading_enabled:
            return TradeResult(
                success=False,
                tx_hash=None,
                error="Trading disabled",
                gas_used=0,
                timestamp=datetime.utcnow(),
                direction=signal.direction,
                asset=signal.asset,
                size=0.0,
                entry_price=signal.current_price,
            )
        if not self.trader:
            return TradeResult(
                success=False,
                tx_hash=None,
                error="Missing trader private key",
                gas_used=0,
                timestamp=datetime.utcnow(),
                direction=signal.direction,
                asset=signal.asset,
                size=0.0,
                entry_price=signal.current_price,
            )

        try:
            market_address = get_market_address_for_asset(self.web3, signal.asset)

            # Pre-flight: ensure vault has the market's long token as a
            # supported asset (required by dHEDGE GMX V2 Guard).
            self._validate_vault_assets(vault_address, market_address)

            size_usd = (
                float(size_usd_override)
                if size_usd_override and size_usd_override > 0
                else self._calculate_size_usd(
                    signal.asset,
                    signal.size_pct,
                    signal.current_price,
                    vault_address,
                )
            )
            if size_usd <= 0:
                raise ValueError("Computed trade size is zero")

            payload, _ = self._prepare_trade_payload(
                vault_address=vault_address,
                market_address=market_address,
                size_usd=size_usd,
                is_long=signal.direction > 0,
                current_price=signal.current_price,
            )

            # Using sendTokens with WETH, so no ETH value needed
            # Use the new working exchange router
            tx_hash = await self._execute_via_vault(
                vault_address=vault_address,
                target=self.GMX_EXCHANGE_ROUTER,
                calldata=payload.calldata,
                value=payload.value,  # 0 - using WETH tokens instead of native ETH
            )

            receipt = await self._wait_for_confirmation(tx_hash)
            logger.info(
                "Trade executed: %s %s size_usd=%.2f tx=%s",
                signal.direction_str,
                signal.asset,
                size_usd,
                tx_hash,
            )
            return TradeResult(
                success=True,
                tx_hash=tx_hash,
                error=None,
                gas_used=receipt.get("gasUsed", 0),
                timestamp=datetime.utcnow(),
                direction=signal.direction,
                asset=signal.asset,
                size=size_usd,
                entry_price=signal.current_price,
            )
        except Exception as exc:
            logger.error("Trade execution failed: %s", exc)
            return TradeResult(
                success=False,
                tx_hash=None,
                error=str(exc),
                gas_used=0,
                timestamp=datetime.utcnow(),
                direction=signal.direction,
                asset=signal.asset,
                size=0.0,
                entry_price=signal.current_price,
            )

    def _validate_vault_assets(self, vault_address: str, market_address: str) -> None:
        """Pre-flight check: ensure the vault has the market's long token as a supported asset.

        The dHEDGE GMX V2 Guard requires the market's long token to be in the
        vault's ``getSupportedAssets()``.  Without it, ``createOrder`` reverts
        with the error code ``lt`` (long token not supported).

        For example, the BTC market uses WBTC as long token — the vault must
        list WBTC even though USDC is the collateral.
        """
        long_token = get_market_long_token(self.web3, market_address)
        if not long_token:
            logger.warning(
                "Could not resolve long token for market %s – skipping pre-flight check",
                market_address,
            )
            return

        pool_manager_abi = [
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
        pool_logic_mgr_abi = [
            {
                "inputs": [],
                "name": "poolManagerLogic",
                "outputs": [{"type": "address"}],
                "stateMutability": "view",
                "type": "function",
            }
        ]

        try:
            vault = self.web3.eth.contract(
                address=Web3.to_checksum_address(vault_address),
                abi=pool_logic_mgr_abi,
            )
            mgr_addr = vault.functions.poolManagerLogic().call()
            mgr = self.web3.eth.contract(
                address=Web3.to_checksum_address(mgr_addr),
                abi=pool_manager_abi,
            )
            assets = mgr.functions.getSupportedAssets().call()
            supported = {Web3.to_checksum_address(a[0]) for a in assets}

            if Web3.to_checksum_address(long_token) not in supported:
                raise ValueError(
                    f"Vault {vault_address} is missing the market's long token "
                    f"({long_token}) in supported assets. Add it via "
                    f"changeAssets() on the PoolManagerLogic before trading. "
                    f"Without this asset the dHEDGE guard rejects createOrder "
                    f"with error 'lt'."
                )
            logger.debug("Vault %s has long token %s ✓", vault_address, long_token)
        except ValueError:
            raise
        except Exception as exc:
            logger.warning("Could not validate vault assets: %s", exc)

    def _calculate_size_usd(
        self,
        asset: str,
        size_pct: float,
        current_price: float,
        vault_address: str,
    ) -> float:
        """Calculate trade size in USD based on vault TVL.

        Always sizes relative to TVL. If TVL cannot be determined or is too
        low, returns 0 so the caller can abort gracefully instead of placing
        an impossible trade.
        """
        tvl_usd = self._get_vault_tvl(vault_address)
        if tvl_usd <= 0:
            logger.warning(
                "Vault %s has zero TVL — cannot calculate trade size",
                vault_address[:10],
            )
            return 0.0

        size_usd = tvl_usd * size_pct
        leverage = max(float(settings.gmx_default_leverage), 1.0)
        collateral_needed = size_usd / leverage

        # Pre-flight: verify the vault has enough USDC for collateral
        usdc_balance = self._get_vault_token_balance(
            vault_address, settings.gmx_collateral_token, 6
        )
        if collateral_needed > usdc_balance:
            # Cap size to what the vault can actually afford (with 5% buffer)
            max_size = usdc_balance * leverage * 0.95
            if max_size < 1.0:  # Less than $1 — not worth trading
                logger.warning(
                    "Vault %s USDC balance ($%.2f) too low for any trade "
                    "(needs $%.2f collateral for $%.2f size at %.0fx leverage)",
                    vault_address[:10],
                    usdc_balance,
                    collateral_needed,
                    size_usd,
                    leverage,
                )
                return 0.0
            logger.info(
                "Capping trade size from $%.2f to $%.2f (vault USDC: $%.2f)",
                size_usd,
                max_size,
                usdc_balance,
            )
            size_usd = max_size

        # Also verify WETH for execution fee
        weth_balance = self._get_vault_token_balance(
            vault_address, self.WETH_ADDRESS, 18
        )
        execution_fee_eth = self._calculate_execution_fee() / 10**18
        if weth_balance < execution_fee_eth:
            logger.warning(
                "Vault %s WETH balance (%.6f) insufficient for execution fee (%.6f)",
                vault_address[:10],
                weth_balance,
                execution_fee_eth,
            )
            return 0.0

        return size_usd

    def _get_vault_token_balance(
        self, vault_address: str, token_address: str, decimals: int
    ) -> float:
        """Get the vault's balance of a specific ERC-20 token."""
        try:
            erc20_abi = [
                {
                    "inputs": [{"name": "account", "type": "address"}],
                    "name": "balanceOf",
                    "outputs": [{"type": "uint256"}],
                    "stateMutability": "view",
                    "type": "function",
                },
            ]
            token = self.web3.eth.contract(
                address=Web3.to_checksum_address(token_address), abi=erc20_abi
            )
            balance_raw = token.functions.balanceOf(
                Web3.to_checksum_address(vault_address)
            ).call()
            return balance_raw / (10**decimals)
        except Exception as exc:
            logger.warning("Failed to fetch token balance: %s", exc)
            return 0.0

    # GMX V2 Contract Addresses (Arbitrum - Updated to working deployed contracts)
    WETH_ADDRESS = "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1"
    GMX_ORDER_VAULT = "0x31eF83a530Fde1B38EE9A18093A333D8Bbbc40D5"
    GMX_V2_GUARD = "0x10Ae41dF7781940Ff22b596B9FdEDd88b3A08feC"  # New working guard
    GMX_EXCHANGE_ROUTER = "0x1C3fa76e6E1088bCE750f23a5BFcffa1efEF6A41"  # New working router
    GMX_BASE_ROUTER = "0x7452c558d45f8afC8c83dAe62C3f8A5BE19c71f6"  # For approvals
    GMX_UI_FEE_RECEIVER = settings.gmx_ui_fee_receiver
    CALLBACK_GAS_LIMIT = 750000

    def _calculate_execution_fee(self) -> int:
        """Calculate GMX execution fee dynamically based on gas price.

        GMX V2.1 validates: executionFee >= adjustedGasLimit * tx.gasprice
        where adjustedGasLimit ≈ (baseGas + callbackGasLimit) * multiplierFactor.
        On Arbitrum the base execution gas for market increase orders is ~4,000,000.
        We add 1.5× safety margin so keepers always accept the order.
        """
        EXECUTION_GAS = 4_000_000  # GMX V2.1 base gas for market increase/decrease
        gas_price = self.web3.eth.gas_price
        total_gas = EXECUTION_GAS + self.CALLBACK_GAS_LIMIT
        execution_fee = int(gas_price * total_gas * 1.5)  # 1.5x safety margin
        
        # Use config value as minimum floor (fallback for extremely low gas)
        min_fee = int(settings.gmx_execution_fee_wei) if settings.gmx_execution_fee_wei > 0 else 0
        return max(execution_fee, min_fee)

    def _build_order_calldata(
        self,
        vault_address: str,
        market_address: str,
        size_usd: float,
        is_long: bool,
        current_price: float,
    ) -> tuple[bytes, int]:
        execution_fee = self._calculate_execution_fee()
        logger.info("Calculated execution fee: %s wei (%.6f ETH)", execution_fee, execution_fee / 1e18)

        leverage = max(float(settings.gmx_default_leverage), 1.0)
        collateral_usd = size_usd / leverage
        collateral_amount = int(collateral_usd * self.USDC_DECIMALS)
        size_delta_usd = int(size_usd * self.PRICE_SCALE)
        slippage = max(int(settings.gmx_slippage_bps), 0) / 10_000
        if current_price <= 0:
            raise ValueError("Missing current price for acceptablePrice calc")
        if is_long:
            acceptable_price = int(current_price * (1 + slippage) * self.PRICE_SCALE)
        else:
            acceptable_price = int(current_price * (1 - slippage) * self.PRICE_SCALE)

        exchange_router = self.web3.eth.contract(
            address=Web3.to_checksum_address(self.GMX_EXCHANGE_ROUTER),
            abi=self.exchange_router_abi,
        )

        # Order parameters with correct addresses for dHEDGE integration
        order_params = (
            (
                Web3.to_checksum_address(vault_address),  # receiver
                "0x0000000000000000000000000000000000000000",  # cancellationReceiver
                Web3.to_checksum_address(self.GMX_V2_GUARD),  # callbackContract (V2 Guard!)
                Web3.to_checksum_address(self.GMX_UI_FEE_RECEIVER),  # uiFeeReceiver
                Web3.to_checksum_address(market_address),  # market
                Web3.to_checksum_address(settings.gmx_collateral_token),  # initialCollateralToken
                [],  # swapPath
            ),
            (
                size_delta_usd,  # sizeDeltaUsd
                collateral_amount,  # initialCollateralDeltaAmount
                0,  # triggerPrice
                acceptable_price,  # acceptablePrice
                execution_fee,  # executionFee
                self.CALLBACK_GAS_LIMIT,  # callbackGasLimit (750000)
                0,  # minOutputAmount
                0,  # validFromTime
            ),
            2,  # orderType: MarketIncrease
            0,  # decreasePositionSwapType: NoSwap
            is_long,  # isLong
            False,  # shouldUnwrapNativeToken
            False,  # autoCancel
            bytes(32),  # referralCode
            [],  # dataList (bytes32[]) - required by new router
        )

        # Build multicall with sendTokens for WETH (NOT sendWnt!)
        multicall_payloads = [
            # 1. Send WETH (execution fee) to order vault
            exchange_router.encode_abi(
                "sendTokens",
                args=[
                    Web3.to_checksum_address(self.WETH_ADDRESS),  # token: WETH
                    Web3.to_checksum_address(self.GMX_ORDER_VAULT),  # receiver
                    execution_fee,  # amount
                ],
            ),
            # 2. Send collateral (USDC) to order vault
            exchange_router.encode_abi(
                "sendTokens",
                args=[
                    Web3.to_checksum_address(settings.gmx_collateral_token),
                    Web3.to_checksum_address(self.GMX_ORDER_VAULT),
                    collateral_amount,
                ],
            ),
            # 3. Create the order
            exchange_router.encode_abi("createOrder", args=[order_params]),
        ]

        calldata = exchange_router.encode_abi(
            "multicall", args=[multicall_payloads]
        )
        return bytes.fromhex(calldata[2:]), execution_fee

    def _prepare_trade_payload(
        self,
        vault_address: str,
        market_address: str,
        size_usd: float,
        is_long: bool,
        current_price: float,
    ) -> tuple[TradePayload, int]:
        if size_usd <= 0:
            raise ValueError("Trade size must be positive")
        calldata, execution_fee = self._build_order_calldata(
            vault_address=vault_address,
            market_address=market_address,
            size_usd=size_usd,
            is_long=is_long,
            current_price=current_price,
        )
        value = 0
        gas_limit = self.DEFAULT_GAS_LIMIT
        if self.trader:
            try:
                vault = self.web3.eth.contract(
                    address=Web3.to_checksum_address(vault_address),
                    abi=self.pool_logic_abi,
                )
                if value > 0:
                    estimate = vault.functions.execTransactionWithValue(
                        Web3.to_checksum_address(self.GMX_EXCHANGE_ROUTER),
                        calldata,
                        value,
                    ).estimate_gas({"from": self.trader.address})
                else:
                    estimate = vault.functions.execTransaction(
                        Web3.to_checksum_address(self.GMX_EXCHANGE_ROUTER),
                        calldata,
                    ).estimate_gas({"from": self.trader.address})
                gas_limit = int(estimate * 1.2)
            except Exception as exc:
                logger.warning("Gas estimate failed: %s", exc)
        payload = TradePayload(
            calldata=calldata,
            execution_fee=execution_fee,
            value=value,
            size_usd=size_usd,
            gas_limit=gas_limit,
        )
        return payload, gas_limit

    def _build_close_order_calldata(
        self,
        vault_address: str,
        market_address: str,
        size_usd: float,
        is_long: bool,
        current_price: float,
    ) -> tuple[bytes, int]:
        """Build calldata for MarketDecrease (close position) order."""
        execution_fee = self._calculate_execution_fee()
        logger.info("Calculated execution fee for close: %s wei (%.6f ETH)", execution_fee, execution_fee / 1e18)

        size_delta_usd = int(size_usd * self.PRICE_SCALE)
        slippage = max(int(settings.gmx_slippage_bps), 0) / 10_000
        if current_price <= 0:
            raise ValueError("Missing current price for acceptablePrice calc")
        
        # For closing: longs want min price, shorts want max price
        if is_long:
            acceptable_price = int(current_price * (1 - slippage) * self.PRICE_SCALE)
        else:
            acceptable_price = int(current_price * (1 + slippage) * self.PRICE_SCALE)

        exchange_router = self.web3.eth.contract(
            address=Web3.to_checksum_address(self.GMX_EXCHANGE_ROUTER),
            abi=self.exchange_router_abi,
        )

        # Order parameters for MarketDecrease
        order_params = (
            (
                Web3.to_checksum_address(vault_address),  # receiver
                "0x0000000000000000000000000000000000000000",  # cancellationReceiver
                Web3.to_checksum_address(self.GMX_V2_GUARD),  # callbackContract
                Web3.to_checksum_address(self.GMX_UI_FEE_RECEIVER),  # uiFeeReceiver
                Web3.to_checksum_address(market_address),  # market
                Web3.to_checksum_address(settings.gmx_collateral_token),  # initialCollateralToken
                [],  # swapPath
            ),
            (
                size_delta_usd,  # sizeDeltaUsd
                0,  # initialCollateralDeltaAmount (0 for close)
                0,  # triggerPrice
                acceptable_price,  # acceptablePrice
                execution_fee,  # executionFee
                self.CALLBACK_GAS_LIMIT,  # callbackGasLimit
                0,  # minOutputAmount
                0,  # validFromTime
            ),
            4,  # orderType: MarketDecrease
            0,  # decreasePositionSwapType: NoSwap
            is_long,  # isLong (position direction we're closing)
            False,  # shouldUnwrapNativeToken
            False,  # autoCancel
            bytes(32),  # referralCode
            [],  # dataList (bytes32[]) - required by new router
        )

        # For close orders, only send execution fee (WETH)
        multicall_payloads = [
            exchange_router.encode_abi(
                "sendTokens",
                args=[
                    Web3.to_checksum_address(self.WETH_ADDRESS),
                    Web3.to_checksum_address(self.GMX_ORDER_VAULT),
                    execution_fee,
                ],
            ),
            exchange_router.encode_abi("createOrder", args=[order_params]),
        ]

        calldata = exchange_router.encode_abi(
            "multicall", args=[multicall_payloads]
        )
        return bytes.fromhex(calldata[2:]), execution_fee

    async def _execute_via_vault(
        self, vault_address: str, target: str, calldata: bytes, value: int = 0
    ) -> str:
        vault = self.web3.eth.contract(
            address=Web3.to_checksum_address(vault_address),
            abi=self.pool_logic_abi,
        )
        nonce = self.web3.eth.get_transaction_count(self.trader.address)

        # Use execTransactionWithValue if sending ETH, otherwise execTransaction
        if value > 0:
            # Estimate gas for the transaction
            try:
                estimated_gas = vault.functions.execTransactionWithValue(
                    Web3.to_checksum_address(target), calldata, value
                ).estimate_gas({"from": self.trader.address, "value": value})
                gas_limit = int(estimated_gas * 1.3)  # 30% buffer
            except Exception as exc:
                error_msg = str(exc)
                if "execution reverted" in error_msg:
                    raise RuntimeError(
                        f"Transaction will revert on-chain: {error_msg}"
                    ) from exc
                logger.warning("Gas estimation failed, using default: %s", exc)
                gas_limit = 2000000  # Default for GMX trades
            
            tx = vault.functions.execTransactionWithValue(
                Web3.to_checksum_address(target), calldata, value
            ).build_transaction(
                {
                    "from": self.trader.address,
                    "nonce": nonce,
                    "gas": gas_limit,
                    "chainId": getattr(self.web3.eth, "chain_id", 42161),
                    "maxFeePerGas": self.web3.eth.gas_price * 2,
                    "maxPriorityFeePerGas": self.web3.to_wei(0.1, "gwei"),
                    "value": value,
                }
            )
        else:
            # Estimate gas for the transaction
            try:
                estimated_gas = vault.functions.execTransaction(
                    Web3.to_checksum_address(target), calldata
                ).estimate_gas({"from": self.trader.address})
                gas_limit = int(estimated_gas * 1.3)  # 30% buffer
            except Exception as exc:
                error_msg = str(exc)
                if "execution reverted" in error_msg:
                    raise RuntimeError(
                        f"Transaction will revert on-chain: {error_msg}"
                    ) from exc
                logger.warning("Gas estimation failed, using default: %s", exc)
                gas_limit = 2000000  # Default for GMX trades
            
            tx = vault.functions.execTransaction(
                Web3.to_checksum_address(target), calldata
            ).build_transaction(
                {
                    "from": self.trader.address,
                    "nonce": nonce,
                    "gas": gas_limit,
                    "chainId": getattr(self.web3.eth, "chain_id", 42161),
                    "maxFeePerGas": self.web3.eth.gas_price * 2,
                    "maxPriorityFeePerGas": self.web3.to_wei(0.1, "gwei"),
                    "value": 0,
                }
            )

        signed_tx = self.trader.sign_transaction(tx)
        # Handle both web3.py 5 (rawTransaction) and web3.py 6+ (raw_transaction)
        raw_tx = getattr(signed_tx, 'raw_transaction', None) or getattr(signed_tx, 'rawTransaction', None)
        tx_hash = self.web3.eth.send_raw_transaction(raw_tx)
        hex_hash = tx_hash.hex()
        return hex_hash if hex_hash.startswith("0x") else f"0x{hex_hash}"

    async def _wait_for_confirmation(self, tx_hash: str, timeout: int = 120) -> dict:
        import asyncio

        start = datetime.utcnow()
        while (datetime.utcnow() - start).total_seconds() < timeout:
            try:
                receipt = self.web3.eth.get_transaction_receipt(tx_hash)
                if receipt:
                    if receipt["status"] == 0:
                        raise RuntimeError(f"Transaction reverted: {tx_hash}")
                    return receipt
            except RuntimeError:
                raise
            except Exception:
                pass
            await asyncio.sleep(2)  # yield to event loop between polls
        raise TimeoutError(f"Transaction confirmation timeout after {timeout}s: {tx_hash}")

    def _get_pool_logic_abi(self) -> list:
        return [
            {
                "inputs": [
                    {"name": "target", "type": "address"},
                    {"name": "data", "type": "bytes"},
                ],
                "name": "execTransaction",
                "outputs": [],
                "stateMutability": "nonpayable",
                "type": "function",
            },
            {
                "inputs": [
                    {"name": "target", "type": "address"},
                    {"name": "data", "type": "bytes"},
                    {"name": "value", "type": "uint256"},
                ],
                "name": "execTransactionWithValue",
                "outputs": [],
                "stateMutability": "payable",
                "type": "function",
            },
            {
                "inputs": [],
                "name": "totalFundValue",
                "outputs": [{"type": "uint256"}],
                "stateMutability": "view",
                "type": "function",
            },
        ]

    def _get_vault_tvl(self, vault_address: str) -> float:
        """Fetch vault TVL with multiple fallback strategies.

        1. PoolManagerLogic.totalFundValue() (most reliable)
        2. PoolLogic.totalFundValue() (may revert on some vaults)
        3. tokenPrice() * totalSupply() (computed fallback)
        """
        checksum = Web3.to_checksum_address(vault_address)
        try:
            code = self.web3.eth.get_code(checksum)
            if not code or code == b"\x00":
                logger.warning("No contract code at vault %s, returning 0.0", vault_address)
                return 0.0
        except Exception as exc:
            logger.warning("Failed to inspect vault code for %s: %s", vault_address, exc)
            return 0.0

        # Strategy 1: PoolManagerLogic.totalFundValue()
        try:
            pool_mgr_abi = [
                {
                    "inputs": [],
                    "name": "poolManagerLogic",
                    "outputs": [{"type": "address"}],
                    "stateMutability": "view",
                    "type": "function",
                },
            ]
            mgr_tvl_abi = [
                {
                    "inputs": [],
                    "name": "totalFundValue",
                    "outputs": [{"type": "uint256"}],
                    "stateMutability": "view",
                    "type": "function",
                },
            ]
            vault_contract = self.web3.eth.contract(address=checksum, abi=pool_mgr_abi)
            mgr_addr = vault_contract.functions.poolManagerLogic().call()
            if mgr_addr and mgr_addr != "0x0000000000000000000000000000000000000000":
                mgr = self.web3.eth.contract(
                    address=Web3.to_checksum_address(mgr_addr), abi=mgr_tvl_abi
                )
                tvl_wei = mgr.functions.totalFundValue().call()
                tvl = tvl_wei / 10**18
                if tvl > 0:
                    logger.debug("Vault TVL via PoolManagerLogic: $%.2f", tvl)
                    return tvl
        except Exception as exc:
            logger.debug("PoolManagerLogic.totalFundValue() failed: %s", exc)
            # If the provided address is already a PoolManagerLogic, try it directly.
            try:
                mgr = self.web3.eth.contract(address=checksum, abi=mgr_tvl_abi)
                tvl_wei = mgr.functions.totalFundValue().call()
                tvl = tvl_wei / 10**18
                if tvl > 0:
                    logger.debug("Vault TVL via direct ManagerLogic: $%.2f", tvl)
                    return tvl
            except Exception as direct_exc:
                logger.debug("Direct ManagerLogic.totalFundValue() failed: %s", direct_exc)

        # Strategy 2: PoolLogic.totalFundValue()
        try:
            vault_contract = self.web3.eth.contract(
                address=checksum, abi=self.pool_logic_abi
            )
            tvl_wei = vault_contract.functions.totalFundValue().call()
            tvl = tvl_wei / 10**18
            if tvl > 0:
                logger.debug("Vault TVL via PoolLogic: $%.2f", tvl)
                return tvl
        except Exception as exc:
            logger.debug("PoolLogic.totalFundValue() failed: %s", exc)

        # Strategy 3: tokenPrice() * totalSupply()
        try:
            token_price_abi = [
                {
                    "inputs": [],
                    "name": "tokenPrice",
                    "outputs": [{"type": "uint256"}],
                    "stateMutability": "view",
                    "type": "function",
                },
            ]
            erc20_abi = [
                {
                    "inputs": [],
                    "name": "totalSupply",
                    "outputs": [{"type": "uint256"}],
                    "stateMutability": "view",
                    "type": "function",
                },
            ]
            pool = self.web3.eth.contract(address=checksum, abi=token_price_abi)
            token_price_wei = pool.functions.tokenPrice().call()
            token_price = token_price_wei / 10**18

            erc20 = self.web3.eth.contract(address=checksum, abi=erc20_abi)
            total_supply_wei = erc20.functions.totalSupply().call()
            total_supply = total_supply_wei / 10**18

            tvl = token_price * total_supply
            if tvl > 0:
                logger.info(
                    "Vault TVL via tokenPrice*totalSupply: $%.2f (price=%.4f, supply=%.4f)",
                    tvl, token_price, total_supply,
                )
                return tvl
        except Exception as exc:
            logger.warning("tokenPrice*totalSupply fallback failed: %s", exc)

        logger.warning("All TVL methods failed for vault %s, returning 0.0", vault_address)
        return 0.0

    def _get_exchange_router_abi(self) -> list:
        return [
            {
                "inputs": [
                    {"name": "data", "type": "bytes[]"},
                ],
                "name": "multicall",
                "outputs": [{"name": "results", "type": "bytes[]"}],
                "stateMutability": "payable",
                "type": "function",
            },
            {
                "inputs": [
                    {"name": "receiver", "type": "address"},
                    {"name": "amount", "type": "uint256"},
                ],
                "name": "sendWnt",
                "outputs": [],
                "stateMutability": "payable",
                "type": "function",
            },
            {
                "inputs": [
                    {"name": "token", "type": "address"},
                    {"name": "receiver", "type": "address"},
                    {"name": "amount", "type": "uint256"},
                ],
                "name": "sendTokens",
                "outputs": [],
                "stateMutability": "nonpayable",
                "type": "function",
            },
            {
                "inputs": [
                    {
                        "components": [
                            {
                                "components": [
                                    {"name": "receiver", "type": "address"},
                                    {"name": "cancellationReceiver", "type": "address"},
                                    {"name": "callbackContract", "type": "address"},
                                    {"name": "uiFeeReceiver", "type": "address"},
                                    {"name": "market", "type": "address"},
                                    {"name": "initialCollateralToken", "type": "address"},
                                    {"name": "swapPath", "type": "address[]"},
                                ],
                                "name": "addresses",
                                "type": "tuple",
                            },
                            {
                                "components": [
                                    {"name": "sizeDeltaUsd", "type": "uint256"},
                                    {"name": "initialCollateralDeltaAmount", "type": "uint256"},
                                    {"name": "triggerPrice", "type": "uint256"},
                                    {"name": "acceptablePrice", "type": "uint256"},
                                    {"name": "executionFee", "type": "uint256"},
                                    {"name": "callbackGasLimit", "type": "uint256"},
                                    {"name": "minOutputAmount", "type": "uint256"},
                                    {"name": "validFromTime", "type": "uint256"},
                                ],
                                "name": "numbers",
                                "type": "tuple",
                            },
                            {"name": "orderType", "type": "uint8"},
                            {"name": "decreasePositionSwapType", "type": "uint8"},
                            {"name": "isLong", "type": "bool"},
                            {"name": "shouldUnwrapNativeToken", "type": "bool"},
                            {"name": "autoCancel", "type": "bool"},
                            {"name": "referralCode", "type": "bytes32"},
                            {"name": "dataList", "type": "bytes32[]"},
                        ],
                        "name": "params",
                        "type": "tuple",
                    }
                ],
                "name": "createOrder",
                "outputs": [{"name": "orderKey", "type": "bytes32"}],
                "stateMutability": "payable",
                "type": "function",
            }
        ]
