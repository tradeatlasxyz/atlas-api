from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException, Path
from web3 import Web3

from api.config import settings
from api.execution.market_data import get_market_data
from api.execution.models import Signal
from api.execution.trade_executor import TradeExecutor
from api.models.schemas import FundVaultRequest, FundVaultResponse, ManualTradeRequest, ManualTradeResponse
from api.onchain.gmx import get_market_address_for_asset
from api.onchain.wallet import WalletManager

router = APIRouter(prefix="/api", tags=["Trading"])

ADDRESS_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")


def normalize_vault_address(address: str) -> str:
    if not ADDRESS_RE.match(address):
        raise HTTPException(status_code=422, detail="Invalid vault address")
    return address.lower()


def _resolve_fund_amount(request: FundVaultRequest) -> int:
    if request.amountWei is not None:
        amount_wei = int(request.amountWei)
        if amount_wei <= 0:
            raise HTTPException(status_code=422, detail="Amount must be positive")
        return amount_wei
    if request.amount is not None:
        amount_wei = int(Web3.to_wei(request.amount, "ether"))
        if amount_wei <= 0:
            raise HTTPException(status_code=422, detail="Amount must be positive")
        return amount_wei
    raise HTTPException(status_code=422, detail="Provide amount or amountWei")


def _transfer_weth(web3: Web3, wallet: WalletManager, vault_address: str, amount_wei: int) -> str:
    erc20_abi = [
        {
            "inputs": [{"name": "recipient", "type": "address"}, {"name": "amount", "type": "uint256"}],
            "name": "transfer",
            "outputs": [{"type": "bool"}],
            "stateMutability": "nonpayable",
            "type": "function",
        },
        {
            "inputs": [{"name": "account", "type": "address"}],
            "name": "balanceOf",
            "outputs": [{"type": "uint256"}],
            "stateMutability": "view",
            "type": "function",
        },
    ]
    token = web3.eth.contract(
        address=Web3.to_checksum_address(settings.gmx_execution_fee_token),
        abi=erc20_abi,
    )
    balance = token.functions.balanceOf(Web3.to_checksum_address(wallet.address)).call()
    if balance < amount_wei:
        raise HTTPException(
            status_code=400,
            detail=f"Insufficient WETH in trader wallet. Required {amount_wei}, have {balance}",
        )
    estimate = token.functions.transfer(
        Web3.to_checksum_address(vault_address),
        amount_wei,
    ).estimate_gas({"from": wallet.address})
    tx = token.functions.transfer(
        Web3.to_checksum_address(vault_address),
        amount_wei,
    ).build_transaction(
        {
            "from": wallet.address,
            "gas": int(estimate * 1.2),
            "maxFeePerGas": web3.eth.gas_price * 2,
            "maxPriorityFeePerGas": web3.to_wei(0.1, "gwei"),
        }
    )
    signed = wallet.sign_transaction(tx)
    tx_hash = web3.eth.send_raw_transaction(signed.raw_transaction)
    return tx_hash.hex()


@router.post(
    "/vaults/{vault_address}/fund-weth",
    response_model=FundVaultResponse,
    summary="Fund vault with WETH for GMX execution fees",
)
async def fund_vault_weth(
    request: FundVaultRequest,
    vault_address: str = Path(..., description="Vault address (0x... format)"),
) -> FundVaultResponse:
    vault_address = normalize_vault_address(vault_address)
    if not settings.arbitrum_rpc_url:
        raise HTTPException(status_code=503, detail="ARBITRUM_RPC_URL not configured")
    
    web3 = Web3(Web3.HTTPProvider(settings.arbitrum_rpc_url))
    try:
        wallet = WalletManager(web3=web3)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=f"Wallet configuration error: {exc}") from exc
    if not wallet.is_trader(vault_address):
        raise HTTPException(status_code=403, detail="Wallet is not authorized for this vault")
    amount_wei = _resolve_fund_amount(request)
    try:
        tx_hash = _transfer_weth(web3, wallet, vault_address, amount_wei)
        return FundVaultResponse(success=True, txHash=tx_hash, amountWei=amount_wei)
    except HTTPException:
        raise
    except Exception as exc:
        return FundVaultResponse(success=False, txHash=None, error=str(exc), amountWei=amount_wei)


@router.post(
    "/vaults/{vault_address}/trade",
    response_model=ManualTradeResponse,
    summary="Execute a manual GMX trade for a vault",
)
async def manual_trade(
    request: ManualTradeRequest,
    vault_address: str = Path(..., description="Vault address (0x... format)"),
) -> ManualTradeResponse:
    vault_address = normalize_vault_address(vault_address)
    direction = request.direction.lower()
    if direction not in {"long", "short"}:
        raise HTTPException(status_code=422, detail="Direction must be 'long' or 'short'")
    direction_value = 1 if direction == "long" else -1

    if not settings.arbitrum_rpc_url:
        raise HTTPException(status_code=503, detail="ARBITRUM_RPC_URL not configured")
    
    web3 = Web3(Web3.HTTPProvider(settings.arbitrum_rpc_url))
    try:
        wallet = WalletManager(web3=web3)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=f"Wallet configuration error: {exc}") from exc
    if not wallet.is_trader(vault_address):
        raise HTTPException(status_code=403, detail="Wallet is not authorized for this vault")

    if not request.dryRun and (request.fundWethWei or request.fundWeth):
        fund_amount = FundVaultRequest(amount=request.fundWeth, amountWei=request.fundWethWei)
        amount_wei = _resolve_fund_amount(fund_amount)
        _transfer_weth(web3, wallet, vault_address, amount_wei)

    market_data = get_market_data()
    asset = request.asset.upper()
    try:
        current_price = await market_data.get_current_price(asset)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Price fetch failed: {exc}") from exc

    try:
        market_address = get_market_address_for_asset(web3, asset)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    executor = TradeExecutor()
    size_pct = 1.0 if request.sizeUsd > 0 else 0.0

    signal = Signal(
        direction=direction_value,
        confidence=1.0,
        size_pct=size_pct,
        reason="Manual trade",
        current_price=current_price,
        asset=asset,
        timeframe="1H",
    )

    try:
        if request.dryRun:
            payload, gas_limit = executor._prepare_trade_payload(
                vault_address=vault_address,
                market_address=market_address,
                size_usd=request.sizeUsd,
                is_long=direction_value > 0,
                current_price=current_price,
            )
            return ManualTradeResponse(
                success=True,
                txHash=None,
                error=None,
                gasUsed=0,
                executionFeeWei=payload.execution_fee,
                gasLimit=gas_limit,
            )

        result = await executor.execute_trade(
            signal,
            vault_address,
            size_usd_override=request.sizeUsd,
        )
        return ManualTradeResponse(
            success=result.success,
            txHash=result.tx_hash,
            error=result.error,
            gasUsed=result.gas_used,
            executionFeeWei=None,
            gasLimit=None,
        )
    except Exception as exc:
        return ManualTradeResponse(
            success=False,
            txHash=None,
            error=str(exc),
            gasUsed=0,
            executionFeeWei=None,
            gasLimit=None,
        )
