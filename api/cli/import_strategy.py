#!/usr/bin/env python3
"""Holistic import of strategy from analytics pipeline."""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from api.services.database import async_session
from api.services.import_service import import_strategy_from_folder


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Import strategy from analytics results folder",
    )
    parser.add_argument("path", type=Path, help="Path to results folder")
    parser.add_argument("--dry-run", action="store_true", help="Validate only")
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("--force", action="store_true", help="Overwrite existing")
    return parser.parse_args()


async def run() -> int:
    args = parse_args()

    if not args.path.exists():
        print(f"❌ Path not found: {args.path}")
        return 1

    async with async_session() as db:
        result = await import_strategy_from_folder(
            db=db,
            folder_path=args.path,
            dry_run=args.dry_run,
            force=args.force,
            verbose=args.verbose,
        )

    if result.success:
        print(f"✅ Imported: {result.strategy_name}")
        if result.strategy_id:
            print(f"   Database ID: {result.strategy_id}")
        if result.code_path:
            print(f"   Code file: {result.code_path}")
        return 0

    print(f"❌ Import failed: {result.error}")
    return 1


def main() -> int:
    return asyncio.run(run())


if __name__ == "__main__":
    sys.exit(main())
