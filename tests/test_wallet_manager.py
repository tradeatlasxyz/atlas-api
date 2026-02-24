import json
import os

import pytest

from api.onchain.wallet import WalletManager


class DummyEth:
    def __init__(self):
        self.nonce = 7

    def get_transaction_count(self, _addr):
        return self.nonce

    def estimate_gas(self, _tx):
        return 21000

    def contract(self, address=None, abi=None):
        class DummyFunctions:
            def poolManagerLogic(self):
                class DummyCall:
                    def call(self_inner):
                        return "0x0000000000000000000000000000000000000002"
                return DummyCall()

            def manager(self):
                class DummyCall:
                    def call(self_inner):
                        return "0x000000000000000000000000000000000000dEaD"
                return DummyCall()

            def trader(self):
                class DummyCall:
                    def call(self_inner):
                        return "0x000000000000000000000000000000000000dEaD"
                return DummyCall()

        class DummyContract:
            functions = DummyFunctions()

        return DummyContract()


class DummyWeb3:
    def __init__(self):
        self.eth = DummyEth()


def test_loads_from_env(monkeypatch):
    test_key = "0x" + "a" * 64
    monkeypatch.setenv("TRADER_PRIVATE_KEY", test_key)
    manager = WalletManager(web3=DummyWeb3())
    assert manager.address.startswith("0x")


def test_rejects_invalid_key(monkeypatch):
    monkeypatch.setenv("TRADER_PRIVATE_KEY", "bad-key")
    with pytest.raises(ValueError):
        WalletManager(web3=DummyWeb3())


def test_private_key_not_in_repr(monkeypatch):
    test_key = "0x" + "b" * 64
    monkeypatch.setenv("TRADER_PRIVATE_KEY", test_key)
    manager = WalletManager(web3=DummyWeb3())
    assert "b" * 10 not in repr(manager)


def test_private_key_not_serializable(monkeypatch):
    test_key = "0x" + "c" * 64
    monkeypatch.setenv("TRADER_PRIVATE_KEY", test_key)
    manager = WalletManager(web3=DummyWeb3())
    with pytest.raises(TypeError):
        json.dumps(manager.__dict__)


def test_invalid_key_error_does_not_leak_key(monkeypatch):
    bad_key = "0x" + "g" * 64
    monkeypatch.setenv("TRADER_PRIVATE_KEY", bad_key)
    with pytest.raises(ValueError) as excinfo:
        WalletManager(web3=DummyWeb3())
    assert bad_key not in str(excinfo.value)


def test_sign_transaction_includes_chain_and_nonce(monkeypatch):
    test_key = "0x" + "d" * 64
    monkeypatch.setenv("TRADER_PRIVATE_KEY", test_key)
    manager = WalletManager(web3=DummyWeb3())
    signed = manager.sign_transaction({"to": manager.address, "value": 0})
    assert signed.raw_transaction is not None
    assert signed.hash.startswith("0x")


def test_is_trader_true(monkeypatch):
    test_key = "0x" + "e" * 64
    monkeypatch.setenv("TRADER_PRIVATE_KEY", test_key)
    manager = WalletManager(web3=DummyWeb3())
    manager._vault_reader.get_trader_address = lambda _vault: manager.address
    assert manager.is_trader("0x0000000000000000000000000000000000000001") is True


def test_is_trader_false(monkeypatch):
    test_key = "0x" + "1" * 64
    monkeypatch.setenv("TRADER_PRIVATE_KEY", test_key)
    manager = WalletManager(web3=DummyWeb3())
    manager._vault_reader.get_trader_address = lambda _vault: "0x0000000000000000000000000000000000000002"
    manager._vault_reader.get_manager_address = lambda _vault: "0x0000000000000000000000000000000000000003"
    assert manager.is_trader("0x0000000000000000000000000000000000000001") is False


def test_is_trader_manager_match(monkeypatch):
    test_key = "0x" + "2" * 64
    monkeypatch.setenv("TRADER_PRIVATE_KEY", test_key)
    manager = WalletManager(web3=DummyWeb3())
    manager._vault_reader.get_trader_address = lambda _vault: "0x0000000000000000000000000000000000000002"
    manager._vault_reader.get_manager_address = lambda _vault: manager.address
    assert manager.is_trader("0x0000000000000000000000000000000000000001") is True
