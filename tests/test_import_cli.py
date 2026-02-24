import sys
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from api.cli.import_strategy import parse_args, run
from api.services.import_service import ImportResult


def test_parse_args_with_flags(monkeypatch, tmp_path):
    test_path = tmp_path / "results"
    argv = ["import_strategy", str(test_path), "--dry-run", "--force", "-v"]
    monkeypatch.setattr(sys, "argv", argv)

    args = parse_args()
    assert args.path == Path(test_path)
    assert args.dry_run is True
    assert args.force is True
    assert args.verbose is True


@pytest.mark.asyncio
async def test_run_path_not_found(monkeypatch, tmp_path):
    argv = ["import_strategy", str(tmp_path / "missing")]
    monkeypatch.setattr(sys, "argv", argv)
    assert await run() == 1


@pytest.mark.asyncio
async def test_run_success(monkeypatch, tmp_path):
    argv = ["import_strategy", str(tmp_path)]
    monkeypatch.setattr(sys, "argv", argv)

    @asynccontextmanager
    async def _fake_session():
        yield object()

    async def _fake_import(*_args, **_kwargs):
        return ImportResult(success=True, strategy_name="Test Strategy", strategy_id=1, code_path=tmp_path / "x.py")

    monkeypatch.setattr("api.cli.import_strategy.async_session", _fake_session)
    monkeypatch.setattr("api.cli.import_strategy.import_strategy_from_folder", _fake_import)

    assert await run() == 0
