from __future__ import annotations

import json
import os
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        enable_decoding=False,
    )

    database_url: str = Field(
        default="sqlite+aiosqlite:///./atlas.db",
        validation_alias=AliasChoices("DATABASE_PRIVATE_URL", "DATABASE_URL", "database_url"),
    )
    cors_origins: list[str] = ["http://localhost:3000"]
    api_version: str = "0.1.0"
    arbitrum_rpc_url: str = ""
    trader_private_key: str = ""
    trading_enabled: bool = False
    pyth_benchmarks_url: str = "https://benchmarks.pyth.network/v1/shims/tradingview/history"
    pyth_oracle_address: str = "0xff1a0f4744e8582DF1aE09D5611b887B6a12925C"
    pyth_symbols: dict[str, str] = {}
    pyth_price_ids: dict[str, str] = {}
    gmx_exchange_router: str = "0x900173A66dbD345006C51fA35fA3aB760FcD843b"
    gmx_data_store: str = "0xFD70de6b91282D8017aA4E741e9Ae325CAb992d8"
    gmx_order_vault: str = "0x31eF83a530Fde1B38EE9A18093A333D8Bbbc40D5"
    gmx_reader: str = "0x5Ca84c34a381434786738735265b9f3FD814b824"
    gmx_callback_contract: str = "0xEDB6e992c12D719AD89fBA7049b19b7bBf4e733c"
    gmx_collateral_token: str = "0xaf88d065e77c8cC2239327C5EDb3A432268e5831"
    gmx_execution_fee_wei: int = 0
    gmx_execution_fee_token: str = "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1"  # WETH on Arbitrum
    gmx_ui_fee_receiver: str = "0x0000000000000000000000000000000000000000"
    gmx_slippage_bps: int = 50
    gmx_default_leverage: float = 5.0
    gmx_market_addresses: dict[str, str] = {
        "BTC": "0x47c031236e19d024b42f8AE6780E44A573170703",
        "ETH": "0x70d95587d40A2caf56bd97485aB3Eec10Bee6336",
        "SOL": "0x09400D9DB990D5ed3f35D7be61DfAEB900Af03C9",
    }
    referral_indexer_enabled: bool = True
    referral_chain_id: int = 42161
    referral_registry_address: str = ""
    referral_deposit_router_address: str = ""
    referral_reward_pool_address: str = ""
    referral_indexer_start_block: int = 0
    referral_indexer_chunk_size: int = 2_000
    referral_indexer_confirmations: int = 3
    referral_indexer_interval_seconds: int = 60
    backfill_on_startup: bool = True

    @field_validator("database_url", mode="before")
    @classmethod
    def normalize_database_url(cls, value: str) -> str:
        if not isinstance(value, str):
            return value
        if not value.strip():
            return "sqlite+aiosqlite:///./atlas.db"
        url = value
        if url.startswith("postgres://"):
            url = "postgresql+asyncpg://" + url[len("postgres://") :]
        if url.startswith("postgresql://") and "+asyncpg" not in url:
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        if url.startswith("sqlite://") and "+aiosqlite" not in url:
            url = url.replace("sqlite://", "sqlite+aiosqlite://", 1)
        parts = urlsplit(url)
        if "asyncpg" in parts.scheme:
            query = parse_qs(parts.query, keep_blank_values=True)
            if "sslmode" in query and "ssl" not in query:
                mode = (query.pop("sslmode")[0] or "").lower()
                if mode in ("disable", "false", "0", "no"):
                    query["ssl"] = ["false"]
                else:
                    query["ssl"] = ["true"]
                url = urlunsplit(
                    (parts.scheme, parts.netloc, parts.path, urlencode(query, doseq=True), parts.fragment)
                )
        return url

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value):
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.startswith("[") and stripped.endswith("]"):
                try:
                    parsed = json.loads(stripped)
                    if isinstance(parsed, list):
                        return [str(item).strip() for item in parsed if str(item).strip()]
                except json.JSONDecodeError:
                    pass
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("pyth_price_ids", mode="before")
    @classmethod
    def parse_pyth_price_ids(cls, value):
        if isinstance(value, str):
            stripped = value.strip()
            # Try JSON format first: {"BTC": "0x...", "ETH": "0x..."}
            if stripped.startswith("{") and stripped.endswith("}"):
                try:
                    parsed = json.loads(stripped)
                    if isinstance(parsed, dict):
                        return {k.strip().upper(): v.strip() for k, v in parsed.items()}
                except json.JSONDecodeError:
                    pass
            # Fallback to comma-separated format: BTC:0x...,ETH:0x...
            items = [item.strip() for item in stripped.split(",") if item.strip()]
            parsed: dict[str, str] = {}
            for item in items:
                if ":" not in item:
                    continue
                asset, price_id = item.split(":", 1)
                parsed[asset.strip().upper()] = price_id.strip()
            return parsed
        return value

    @field_validator("pyth_symbols", mode="before")
    @classmethod
    def parse_pyth_symbols(cls, value):
        if isinstance(value, str):
            stripped = value.strip()
            # Try JSON format first: {"BTC": "Crypto.BTC/USD", "ETH": "Crypto.ETH/USD"}
            if stripped.startswith("{") and stripped.endswith("}"):
                try:
                    parsed = json.loads(stripped)
                    if isinstance(parsed, dict):
                        return {k.strip().upper(): v.strip() for k, v in parsed.items()}
                except json.JSONDecodeError:
                    pass
            # Fallback to comma-separated format: BTC:Crypto.BTC/USD,ETH:Crypto.ETH/USD
            items = [item.strip() for item in stripped.split(",") if item.strip()]
            parsed: dict[str, str] = {}
            for item in items:
                if ":" not in item:
                    continue
                asset, symbol = item.split(":", 1)
                parsed[asset.strip().upper()] = symbol.strip()
            return parsed
        return value

    @field_validator("gmx_execution_fee_wei", mode="before")
    @classmethod
    def parse_gmx_execution_fee_wei(cls, value):
        if isinstance(value, str) and value.strip() == "":
            return 0
        return value

    @field_validator("gmx_market_addresses", mode="before")
    @classmethod
    def parse_gmx_market_addresses(cls, value):
        if isinstance(value, str):
            stripped = value.strip()
            # Try JSON format first: {"BTC": "0x...", "ETH": "0x..."}
            if stripped.startswith("{") and stripped.endswith("}"):
                try:
                    parsed = json.loads(stripped)
                    if isinstance(parsed, dict):
                        return {k.strip().upper(): v.strip() for k, v in parsed.items()}
                except json.JSONDecodeError:
                    pass
            # Fallback to comma-separated format: BTC:0x...,ETH:0x...
            items = [item.strip() for item in stripped.split(",") if item.strip()]
            parsed: dict[str, str] = {}
            for item in items:
                if ":" not in item:
                    continue
                asset, address = item.split(":", 1)
                parsed[asset.strip().upper()] = address.strip()
            return parsed
        return value

settings = Settings()


def running_in_hosted_env() -> bool:
    """Detect hosted/runtime environments (Railway/containers) by common vars."""
    markers = (
        "RAILWAY_ENVIRONMENT",
        "RAILWAY_PROJECT_ID",
        "RAILWAY_SERVICE_NAME",
        "PORT",
    )
    return any(os.getenv(name) for name in markers)


def database_dsn_safe(raw_url: str | None = None) -> str:
    """Return a redacted DB URL for logs (no password)."""
    url = raw_url or settings.database_url
    if not isinstance(url, str):
        return "<invalid>"
    if url.startswith("sqlite"):
        return f"{urlsplit(url).scheme}://<local-file>"
    parts = urlsplit(url)
    host = parts.hostname or "<unknown>"
    port = parts.port or ""
    db = (parts.path or "").lstrip("/") or "<unknown>"
    port_str = f":{port}" if port else ""
    return f"{parts.scheme}://{host}{port_str}/{db}"
