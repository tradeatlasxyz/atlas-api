import os

import pytest
from web3 import Web3

from api.onchain.wallet import WalletManager


@pytest.mark.integration
@pytest.mark.asyncio
async def test_wallet_is_trader():
    rpc = os.getenv("ARBITRUM_RPC_URL")
    vault = os.getenv("TESTNET_VAULT_ADDRESS")
    key = os.getenv("TRADER_PRIVATE_KEY")
    if not rpc or not vault or not key:
        pytest.skip("ARBITRUM_RPC_URL, TESTNET_VAULT_ADDRESS, TRADER_PRIVATE_KEY required")

    manager = WalletManager(web3=Web3(Web3.HTTPProvider(rpc)), private_key=key)
    result = manager.is_trader(vault)
    assert isinstance(result, bool)
