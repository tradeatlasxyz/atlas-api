"""GMX V2 helpers for resolving markets on-chain."""
from __future__ import annotations

import logging
from typing import Dict, Optional, Tuple

from web3 import Web3

from api.config import settings

logger = logging.getLogger(__name__)

GMX_READER_ABI = [
    {
        "inputs": [
            {"internalType": "contract DataStore", "name": "dataStore", "type": "address"},
            {"internalType": "uint256", "name": "start", "type": "uint256"},
            {"internalType": "uint256", "name": "end", "type": "uint256"},
        ],
        "name": "getMarkets",
        "outputs": [
            {
                "components": [
                    {"internalType": "address", "name": "marketToken", "type": "address"},
                    {"internalType": "address", "name": "indexToken", "type": "address"},
                    {"internalType": "address", "name": "longToken", "type": "address"},
                    {"internalType": "address", "name": "shortToken", "type": "address"},
                ],
                "internalType": "struct Market.Props[]",
                "name": "",
                "type": "tuple[]",
            }
        ],
        "stateMutability": "view",
        "type": "function",
    }
]

ERC20_SYMBOL_ABI = [
    {
        "inputs": [],
        "name": "symbol",
        "outputs": [{"name": "", "type": "string"}],
        "stateMutability": "view",
        "type": "function",
    }
]

# Well-known long tokens for GMX markets on Arbitrum
# The dHEDGE GMX V2 Guard requires the market's long token to be in the
# vault's supported assets.  Error code 'lt' = long token not found.
GMX_MARKET_LONG_TOKENS: Dict[str, str] = {
    # BTC market → WBTC
    "0x47c031236e19d024b42f8AE6780E44A573170703": "0x2f2a2543B76A4166549F7aaB2e75Bef0aefC5B0f",
    # ETH market → WETH
    "0x70d95587d40A2caf56bd97485aB3Eec10Bee6336": "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1",
    # SOL market → SOL token
    "0x09400D9DB990D5ed3f35D7be61DfAEB900Af03C9": "0x2bcC6D6CdBbDC0a4071e48bb3B969b06B3330c07",
}


def _normalize_symbol(symbol: str) -> str:
    clean = symbol.upper()
    if clean.startswith("W") and len(clean) > 1:
        clean = clean[1:]
    return clean


def resolve_market_addresses(
    web3: Web3,
    reader_address: str,
    data_store_address: str,
    start: int = 0,
    end: int = 50,
) -> Tuple[Dict[str, str], Dict[str, str]]:
    reader = web3.eth.contract(
        address=Web3.to_checksum_address(reader_address),
        abi=GMX_READER_ABI,
    )
    markets = reader.functions.getMarkets(
        Web3.to_checksum_address(data_store_address), start, end
    ).call()

    symbol_to_market: Dict[str, str] = {}
    market_to_symbol: Dict[str, str] = {}
    for market in markets:
        market_token, index_token, _long_token, _short_token = market
        try:
            index_contract = web3.eth.contract(
                address=Web3.to_checksum_address(index_token),
                abi=ERC20_SYMBOL_ABI,
            )
            symbol = index_contract.functions.symbol().call()
        except Exception:
            continue
        normalized = _normalize_symbol(symbol)
        symbol_to_market[normalized] = Web3.to_checksum_address(market_token)
        market_to_symbol[Web3.to_checksum_address(market_token)] = normalized
    return symbol_to_market, market_to_symbol


def get_market_address_for_asset(web3: Web3, asset: str) -> str:
    asset = asset.upper()
    if settings.gmx_market_addresses and asset in settings.gmx_market_addresses:
        return settings.gmx_market_addresses[asset]

    symbol_to_market, _ = resolve_market_addresses(
        web3, settings.gmx_reader, settings.gmx_data_store
    )
    if asset in symbol_to_market:
        return symbol_to_market[asset]
    raise ValueError(f"Missing GMX market address for {asset}")


def get_symbol_for_market(web3: Web3, market_address: str) -> str:
    for symbol, address in settings.gmx_market_addresses.items():
        if address.lower() == market_address.lower():
            return symbol
    _, market_to_symbol = resolve_market_addresses(
        web3, settings.gmx_reader, settings.gmx_data_store
    )
    return market_to_symbol.get(Web3.to_checksum_address(market_address), market_address)


def get_market_long_token(web3: Web3, market_address: str) -> Optional[str]:
    """Return the long token address for a GMX market.

    The dHEDGE GMX V2 Guard requires the market's long token to exist in the
    vault's supported assets.  Without it ``createOrder`` reverts with ``lt``.

    Uses a static lookup table first and falls back to an on-chain call.
    """
    checksummed = Web3.to_checksum_address(market_address)
    if checksummed in GMX_MARKET_LONG_TOKENS:
        return Web3.to_checksum_address(GMX_MARKET_LONG_TOKENS[checksummed])

    # Fallback: read from on-chain
    try:
        reader = web3.eth.contract(
            address=Web3.to_checksum_address(settings.gmx_reader),
            abi=GMX_READER_ABI,
        )
        markets = reader.functions.getMarkets(
            Web3.to_checksum_address(settings.gmx_data_store), 0, 100
        ).call()
        for m in markets:
            if Web3.to_checksum_address(m[0]) == checksummed:
                return Web3.to_checksum_address(m[2])  # longToken
    except Exception as exc:
        logger.warning("Failed to fetch long token for market %s: %s", market_address, exc)
    return None
