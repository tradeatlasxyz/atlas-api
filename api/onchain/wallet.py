"""Wallet manager for signing and trader verification."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Optional

from eth_account import Account
from eth_account.signers.local import LocalAccount
from web3 import Web3

from api.config import settings
from api.onchain.vault_reader import VaultReader

logger = logging.getLogger(__name__)


@dataclass
class SignedTransaction:
    raw_transaction: bytes
    hash: str


class WalletManager:
    def __init__(
        self,
        web3: Optional[Web3] = None,
        private_key: Optional[str] = None,
        vault_reader: Optional[VaultReader] = None,
    ) -> None:
        self.web3 = web3 or Web3(Web3.HTTPProvider(settings.arbitrum_rpc_url))
        env_key = os.getenv("TRADER_PRIVATE_KEY", "")
        key = private_key or env_key or settings.trader_private_key
        if not key:
            raise ValueError("Missing TRADER_PRIVATE_KEY")
        raw = key[2:] if key.startswith("0x") else key
        if len(raw) != 64 or any(c not in "0123456789abcdefABCDEF" for c in raw):
            raise ValueError("Invalid private key")
        key = f"0x{raw}"
        try:
            self._account: LocalAccount = Account.from_key(key)
        except Exception as exc:
            raise ValueError("Invalid private key") from exc
        self._vault_reader = vault_reader or VaultReader(self.web3)

    @property
    def address(self) -> str:
        return self._account.address

    def __repr__(self) -> str:
        return f"WalletManager(address={self.address})"

    def sign_transaction(self, tx: dict) -> SignedTransaction:
        tx = dict(tx)
        if "chainId" not in tx:
            tx["chainId"] = 42161
        if "nonce" not in tx:
            tx["nonce"] = self.web3.eth.get_transaction_count(self.address)
        if "gas" not in tx:
            try:
                tx["gas"] = self.web3.eth.estimate_gas(tx)
            except Exception:
                tx["gas"] = 500000
        if "gasPrice" not in tx and "maxFeePerGas" not in tx:
            tx["gasPrice"] = getattr(self.web3.eth, "gas_price", 0)
        signed = self._account.sign_transaction(tx)
        raw_tx = getattr(signed, "rawTransaction", None) or getattr(signed, "raw_transaction", None)
        tx_hash = signed.hash.hex()
        if not tx_hash.startswith("0x"):
            tx_hash = f"0x{tx_hash}"
        return SignedTransaction(raw_transaction=raw_tx, hash=tx_hash)

    def is_trader(self, vault_address: str) -> bool:
        try:
            trader = self._vault_reader.get_trader_address(vault_address)
            if trader.lower() == self.address.lower():
                return True
            manager = self._vault_reader.get_manager_address(vault_address)
            return manager.lower() == self.address.lower()
        except Exception as exc:
            logger.error("Trader verification failed: %s", exc)
            return False
