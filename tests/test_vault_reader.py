import time

import pytest

from api.onchain.vault_reader import VaultReader


class DummyCall:
    def __init__(self, value, counter=None):
        self._value = value
        self._counter = counter

    def call(self):
        if self._counter is not None:
            self._counter["count"] += 1
        return self._value


class DummyFunctions:
    def __init__(self, counters):
        self._counters = counters

    def tokenPriceWithoutManagerFee(self):
        return DummyCall(200 * 10**18, self._counters["tvl"])

    def tokenPrice(self):
        return DummyCall(105 * 10**16, self._counters["share_price"])

    def totalSupply(self):
        return DummyCall(10 * 10**18, self._counters["supply"])

    def poolManagerLogic(self):
        return DummyCall("0x0000000000000000000000000000000000000002")

    def manager(self):
        return DummyCall("0x000000000000000000000000000000000000dEaD", self._counters["manager"])

    def trader(self):
        return DummyCall("0x000000000000000000000000000000000000dEaD", self._counters["manager"])

    def isTrader(self, _addr):
        return DummyCall(True, self._counters["is_trader"])


class DummyContract:
    def __init__(self, counters):
        self.functions = DummyFunctions(counters)


class DummyEth:
    def __init__(self, counters):
        self._counters = counters

    def contract(self, address=None, abi=None):
        return DummyContract(self._counters)


class DummyWeb3:
    def __init__(self, counters):
        self.eth = DummyEth(counters)


def _counters():
    return {
        "tvl": {"count": 0},
        "share_price": {"count": 0},
        "supply": {"count": 0},
        "manager": {"count": 0},
        "is_trader": {"count": 0},
    }


def test_get_vault_state_reads_contract():
    counters = _counters()
    reader = VaultReader(DummyWeb3(counters), cache_ttl=300)
    state = reader.get_vault_state("0x0000000000000000000000000000000000000001")

    assert state.tvl == pytest.approx(200.0, rel=1e-6)
    assert state.share_price == pytest.approx(1.05, rel=1e-6)
    assert state.total_supply == pytest.approx(10.0, rel=1e-6)
    assert state.manager.lower() == "0x000000000000000000000000000000000000dead"


def test_cache_hit_avoids_rpc_calls():
    counters = _counters()
    reader = VaultReader(DummyWeb3(counters), cache_ttl=300)
    reader.get_tvl("0x0000000000000000000000000000000000000001")
    reader.get_tvl("0x0000000000000000000000000000000000000001")
    assert counters["tvl"]["count"] == 1


def test_cache_ttl_expires(monkeypatch):
    counters = _counters()
    reader = VaultReader(DummyWeb3(counters), cache_ttl=1)
    reader.get_tvl("0x0000000000000000000000000000000000000001")
    original_time = time.time
    monkeypatch.setattr(time, "time", lambda: original_time() + 2)
    reader.get_tvl("0x0000000000000000000000000000000000000001")
    assert counters["tvl"]["count"] == 2


def test_invalid_address_raises():
    counters = _counters()
    reader = VaultReader(DummyWeb3(counters), cache_ttl=300)
    with pytest.raises(ValueError):
        reader.get_tvl("not-an-address")


def test_retry_call_succeeds(monkeypatch):
    counters = _counters()
    reader = VaultReader(DummyWeb3(counters), cache_ttl=300, max_retries=1)
    calls = {"count": 0}

    def _flaky():
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("timeout")
        return 123

    monkeypatch.setattr(time, "sleep", lambda *_: None)
    assert reader._retry_call(_flaky) == 123


def test_manager_address_cached():
    counters = _counters()
    reader = VaultReader(DummyWeb3(counters), cache_ttl=300)
    reader.get_manager_address("0x0000000000000000000000000000000000000001")
    reader.get_manager_address("0x0000000000000000000000000000000000000001")
    assert counters["manager"]["count"] == 1
