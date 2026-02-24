import os

import pytest
from web3 import Web3

from api.onchain.gmx import resolve_market_addresses

# GMX V2 Arbitrum Sepolia deployment addresses from gmx-io/gmx-synthetics (deployments/arbitrumSepolia)
GMX_TESTNET_READER = os.getenv("GMX_TESTNET_READER", "0x4750376b9378294138Cf7B7D69a2d243f4940f71")
GMX_TESTNET_DATA_STORE = os.getenv("GMX_TESTNET_DATA_STORE", "0xCF4c2C4c53157BcC01A596e3788fFF69cBBCD201")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_gmx_markets_on_testnet():
    rpc = os.getenv("ARBITRUM_TESTNET_RPC_URL")
    if not rpc:
        pytest.skip("ARBITRUM_TESTNET_RPC_URL required")

    web3 = Web3(Web3.HTTPProvider(rpc))
    symbol_to_market, market_to_symbol = resolve_market_addresses(
        web3, GMX_TESTNET_READER, GMX_TESTNET_DATA_STORE
    )

    assert symbol_to_market, "Expected non-empty market mapping"
    assert market_to_symbol, "Expected non-empty market reverse mapping"

    # Validate at least one known asset is present if symbols are available
    known_assets = {"BTC", "ETH", "SOL"}
    assert known_assets & set(symbol_to_market.keys())
