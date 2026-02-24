"""End-to-end tests for the deployed Atlas API.

These tests verify the production API is working correctly.
Run with: pytest tests/e2e/test_deployed_api_e2e.py -m e2e -v
"""
import os

import aiohttp
import pytest

# Production API URL - can be overridden via environment variable
API_BASE_URL = os.getenv("ATLAS_API_URL", "http://localhost:8000")


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_api_root():
    """Verify API root endpoint returns expected response."""
    async with aiohttp.ClientSession() as session:
        async with session.get(API_BASE_URL) as resp:
            assert resp.status == 200
            data = await resp.json()
            assert data["message"] == "Atlas API"
            assert data["docs"] == "/docs"


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_api_health():
    """Verify health endpoint returns OK status."""
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{API_BASE_URL}/health") as resp:
            assert resp.status == 200
            data = await resp.json()
            assert data["status"] == "ok"
            assert "version" in data
            assert "timestamp" in data
            assert data["database"] == "ok"


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_api_health_detailed():
    """Verify detailed health endpoint returns comprehensive status."""
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{API_BASE_URL}/health/detailed") as resp:
            assert resp.status == 200
            data = await resp.json()
            assert data["status"] == "ok"
            assert "checks" in data
            assert data["checks"]["database"]["status"] == "ok"
            assert "latency_ms" in data["checks"]["database"]


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_api_health_live():
    """Verify liveness probe endpoint."""
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{API_BASE_URL}/health/live") as resp:
            assert resp.status == 200
            data = await resp.json()
            assert data["status"] == "alive"


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_api_health_ready():
    """Verify readiness probe endpoint."""
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{API_BASE_URL}/health/ready") as resp:
            assert resp.status == 200
            data = await resp.json()
            assert data["status"] == "ready"


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_api_docs_accessible():
    """Verify Swagger docs are accessible."""
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{API_BASE_URL}/docs") as resp:
            assert resp.status == 200
            content = await resp.text()
            assert "swagger" in content.lower() or "openapi" in content.lower()


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_api_openapi_spec():
    """Verify OpenAPI spec is available and valid."""
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{API_BASE_URL}/openapi.json") as resp:
            assert resp.status == 200
            data = await resp.json()
            assert "openapi" in data
            assert "paths" in data
            assert "info" in data
            # Verify expected endpoints exist
            assert "/" in data["paths"]
            assert "/health" in data["paths"]


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_api_strategy_discoveries():
    """Verify strategy discoveries endpoint works."""
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{API_BASE_URL}/api/strategies/discoveries") as resp:
            assert resp.status == 200
            data = await resp.json()
            # Paginated response with strategies list
            assert "strategies" in data
            assert "total" in data
            assert "page" in data
            assert isinstance(data["strategies"], list)
            # Should have strategies deployed
            assert data["total"] >= 0
            if data["strategies"]:
                strategy = data["strategies"][0]
                assert "id" in strategy
                assert "asset" in strategy


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_api_response_times():
    """Verify API responds within acceptable time limits."""
    import time

    async with aiohttp.ClientSession() as session:
        # Health endpoint should respond quickly
        start = time.time()
        async with session.get(f"{API_BASE_URL}/health") as resp:
            elapsed = time.time() - start
            assert resp.status == 200
            # Should respond within 2 seconds (generous for cold starts)
            assert elapsed < 2.0, f"Health endpoint took {elapsed:.2f}s"

        # Root endpoint should be even faster
        start = time.time()
        async with session.get(API_BASE_URL) as resp:
            elapsed = time.time() - start
            assert resp.status == 200
            assert elapsed < 1.0, f"Root endpoint took {elapsed:.2f}s"


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_api_trigger_signal_endpoint():
    """Verify signal trigger endpoint accepts requests."""
    async with aiohttp.ClientSession() as session:
        # Test with a dummy vault address
        test_address = "0x0000000000000000000000000000000000000001"
        async with session.post(f"{API_BASE_URL}/admin/trigger/{test_address}") as resp:
            assert resp.status == 200
            data = await resp.json()
            assert data["status"] == "triggered"
            assert data["vault"] == test_address


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_api_strategies_have_required_fields():
    """Verify strategy discovery data has all required fields."""
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{API_BASE_URL}/api/strategies/discoveries") as resp:
            assert resp.status == 200
            data = await resp.json()

            assert data["total"] >= 5, "Expected at least 5 deployed strategies"

            for strategy in data["strategies"]:
                # Required fields
                assert "id" in strategy, "Strategy missing 'id'"
                assert "asset" in strategy, "Strategy missing 'asset'"
                assert "name" in strategy, "Strategy missing 'name'"
                assert "timeframe" in strategy, "Strategy missing 'timeframe'"

                # Asset should be a known crypto
                asset = str(strategy["asset"]).upper()
                assert asset in ["BTC", "ETH", "SOL", "MULTI"], \
                    f"Unknown asset: {strategy['asset']}"

                # Timeframe should be valid
                assert strategy["timeframe"] in ["1M", "5M", "15M", "1H", "4H", "1D"], \
                    f"Invalid timeframe: {strategy['timeframe']}"


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_api_strategies_cover_multiple_assets():
    """Verify deployed strategies cover different assets."""
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{API_BASE_URL}/api/strategies/discoveries") as resp:
            assert resp.status == 200
            data = await resp.json()

            assets = {s["asset"] for s in data["strategies"]}

            # Should have strategies for multiple assets
            assert len(assets) >= 3, f"Expected strategies for 3+ assets, got: {assets}"

            # Print summary
            print(f"\n=== Deployed Strategy Coverage ===")
            print(f"Total strategies: {data['total']}")
            print(f"Assets covered: {sorted(assets)}")
            for asset in sorted(assets):
                count = sum(1 for s in data["strategies"] if s["asset"] == asset)
                print(f"  {asset}: {count} strategies")
