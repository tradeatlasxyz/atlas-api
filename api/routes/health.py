from __future__ import annotations

from datetime import datetime, timezone
import time
from typing import Optional, Tuple

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from sqlalchemy import text

from api.config import settings
from api.services.database import async_session

router = APIRouter()


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def check_database() -> Tuple[bool, Optional[float], Optional[str]]:
    start = time.perf_counter()
    try:
        async with async_session() as session:
            await session.execute(text("SELECT 1"))
        latency_ms = (time.perf_counter() - start) * 1000
        return True, latency_ms, None
    except Exception as exc:  # pragma: no cover - exercised via integration
        latency_ms = (time.perf_counter() - start) * 1000
        return False, latency_ms, str(exc)


@router.get("/health/live")
async def liveness_check() -> dict:
    return {
        "status": "alive",
        "version": settings.api_version,
        "timestamp": utc_now_iso(),
    }


@router.get("/health/ready")
async def readiness_check():
    ok, latency_ms, _ = await check_database()
    payload = {
        "status": "ready" if ok else "not_ready",
        "version": settings.api_version,
        "timestamp": utc_now_iso(),
        "database": "ok" if ok else "error",
        "database_latency_ms": round(latency_ms, 2) if latency_ms is not None else None,
    }
    if ok:
        return payload
    return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content=payload)


@router.get("/health")
async def health_check():
    """Basic health check — always returns 200 so Railway keeps the container alive.
    Use /health/ready for a strict DB-aware probe."""
    ok, latency_ms, error = await check_database()
    payload = {
        "status": "ok" if ok else "degraded",
        "version": settings.api_version,
        "timestamp": utc_now_iso(),
        "database": "ok" if ok else "unavailable",
        "database_latency_ms": round(latency_ms, 2) if latency_ms is not None else None,
    }
    if not ok:
        payload["database_error"] = error
    return payload


@router.get("/health/detailed")
async def detailed_health():
    ok, latency_ms, error = await check_database()
    payload = {
        "status": "ok" if ok else "error",
        "version": settings.api_version,
        "timestamp": utc_now_iso(),
        "checks": {
            "database": {
                "status": "ok" if ok else "error",
                "latency_ms": round(latency_ms, 2) if latency_ms is not None else None,
                "error": error,
            }
        },
    }
    if ok:
        return payload
    return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content=payload)
