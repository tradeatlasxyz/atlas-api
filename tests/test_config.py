from api.config import Settings


def test_database_url_normalizes_postgres(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgres://user:pass@localhost:5432/db")
    settings = Settings()
    assert settings.database_url.startswith("postgresql+asyncpg://")


def test_database_url_normalizes_sqlite(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./atlas.db")
    settings = Settings()
    assert settings.database_url.startswith("sqlite+aiosqlite://")


def test_database_url_uses_private_url(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_PRIVATE_URL", "postgres://user:pass@private:5432/db")
    monkeypatch.setenv("DATABASE_URL", "postgres://user:pass@public:5432/db")
    settings = Settings()
    assert "private" in settings.database_url


def test_database_url_empty_falls_back_to_sqlite(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "")
    settings = Settings()
    assert settings.database_url.startswith("sqlite+aiosqlite://")


def test_database_url_maps_sslmode_to_ssl(monkeypatch) -> None:
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://user:pass@db.example.com:5432/app?sslmode=require",
    )
    settings = Settings()
    assert "sslmode=" not in settings.database_url
    assert "ssl=" in settings.database_url

def test_cors_origins_parses_comma_separated(monkeypatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", "http://a.test, http://b.test")
    settings = Settings()
    assert settings.cors_origins == ["http://a.test", "http://b.test"]


def test_cors_origins_parses_json_list(monkeypatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", "[\"http://a.test\",\"http://b.test\"]")
    settings = Settings()
    assert settings.cors_origins == ["http://a.test", "http://b.test"]
