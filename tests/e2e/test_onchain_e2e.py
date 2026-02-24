import os

import pytest
from web3 import Web3

from api.onchain.vault_reader import VaultReader


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_vault_reader_e2e():
    rpc = os.getenv("ARBITRUM_RPC_URL")
    vault = os.getenv("TESTNET_VAULT_ADDRESS")
    if not rpc or not vault:
        pytest.skip("ARBITRUM_RPC_URL and TESTNET_VAULT_ADDRESS required")

    reader = VaultReader(Web3(Web3.HTTPProvider(rpc)))
    state = reader.get_vault_state(vault)
    assert state.tvl >= 0
