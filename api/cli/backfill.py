#!/usr/bin/env python3
"""CLI for market data backfill."""
from __future__ import annotations

import argparse
import asyncio

from api.services.backfill import BackfillService


async def _run(args: argparse.Namespace) -> None:
    service = BackfillService()
    if args.check:
        status = await service.check_backfill_status()
        for asset, frames in status.items():
            print(asset, frames)
        return
    if args.asset:
        await service.backfill_asset(args.asset)
        return
    await service.backfill_all()


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill historical market data")
    parser.add_argument("--check", action="store_true", help="Check backfill status")
    parser.add_argument("--asset", help="Backfill a specific asset (BTC, ETH, SOL)")
    args = parser.parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
