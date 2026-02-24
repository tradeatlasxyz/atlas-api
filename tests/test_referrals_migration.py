from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from api.config import settings


def test_referrals_migration_upgrade_and_downgrade(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    db_path = tmp_path / "referrals_migration.db"
    async_db_url = f"sqlite+aiosqlite:///{db_path}"
    sync_db_url = f"sqlite:///{db_path}"

    alembic_cfg = Config(str(repo_root / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(repo_root / "alembic"))

    original_db_url = settings.database_url
    settings.database_url = async_db_url

    engine = create_engine(sync_db_url)
    try:
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE IF NOT EXISTS vaults (address VARCHAR(42) PRIMARY KEY)"))
            conn.execute(text("CREATE TABLE IF NOT EXISTS trades (id INTEGER PRIMARY KEY)"))

        command.stamp(alembic_cfg, "20260124_02")
        command.upgrade(alembic_cfg, "head")

        inspector = inspect(engine)
        table_names = set(inspector.get_table_names())
        assert "referral_attributions" in table_names
        assert "referral_reward_claims" in table_names
        assert "referral_indexer_state" in table_names
        assert "referral_abuse_reviews" in table_names

        command.downgrade(alembic_cfg, "20260124_02")
        inspector = inspect(engine)
        table_names = set(inspector.get_table_names())
        assert "referral_attributions" not in table_names
        assert "referral_reward_claims" not in table_names
        assert "referral_indexer_state" not in table_names
        assert "referral_abuse_reviews" not in table_names
    finally:
        engine.dispose()
        settings.database_url = original_db_url
