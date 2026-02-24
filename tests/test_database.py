from api.services.database import _disable_prepared_statements


def test_disable_prepared_statements_on_pooler_host() -> None:
    url = "postgresql+asyncpg://user:pass@pooler.db-provider.example.com:6543/db"
    assert _disable_prepared_statements(url) is True


def test_disable_prepared_statements_on_pool_mode() -> None:
    url = "postgresql+asyncpg://user:pass@db.example.com:5432/db?pool_mode=transaction"
    assert _disable_prepared_statements(url) is True


def test_dont_disable_for_regular_postgres() -> None:
    url = "postgresql+asyncpg://user:pass@db.example.com:5432/db"
    assert _disable_prepared_statements(url) is False
