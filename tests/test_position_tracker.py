import pytest

from api.execution.position_tracker import PositionTracker


class DummyCall:
    def __init__(self, value):
        self._value = value

    def call(self):
        return self._value


class DummyFunctions:
    def __init__(self, member_count=5):
        self._member_count = member_count

    def poolManagerLogic(self):
        return DummyCall("0x0000000000000000000000000000000000000002")

    def getMembers(self):
        return DummyCall(["0x1"] * self._member_count)


class DummyContract:
    def __init__(self, member_count=5):
        self.functions = DummyFunctions(member_count)


class DummyEth:
    def __init__(self, member_count=5):
        self._member_count = member_count

    def contract(self, address=None, abi=None):
        return DummyContract(self._member_count)


class DummyWeb3:
    def __init__(self, member_count=5):
        self.eth = DummyEth(member_count)


class DummyMarketData:
    async def get_current_price(self, asset: str) -> float:
        return 100.0


@pytest.mark.asyncio
async def test_get_depositor_count_reads_contract():
    tracker = PositionTracker(DummyMarketData())
    tracker.web3 = DummyWeb3(member_count=42)
    count = await tracker.get_depositor_count("0x0000000000000000000000000000000000000000")
    assert count == 42
