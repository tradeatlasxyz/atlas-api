from urllib.parse import parse_qs, urlsplit

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from api.config import settings


def _disable_prepared_statements(database_url: str) -> bool:
    parts = urlsplit(database_url)
    if "asyncpg" not in parts.scheme:
        return False
    host = (parts.hostname or "").lower()
    if "pooler" in host or "pgbouncer" in host:
        return True
    if parts.port == 6543:
        return True
    query = parse_qs(parts.query)
    pool_mode = (query.get("pool_mode") or [""])[0].lower()
    if pool_mode in {"transaction", "statement"}:
        return True
    return False


connect_args = {}
if _disable_prepared_statements(settings.database_url):
    connect_args["statement_cache_size"] = 0

engine = create_async_engine(settings.database_url, echo=False, connect_args=connect_args)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db():
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()
