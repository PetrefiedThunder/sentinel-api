from __future__ import annotations

import sqlite3
from pathlib import Path

from alembic.config import Config

from alembic import command

REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATION = REPO_ROOT / "alembic" / "versions" / "012_delivery_outbox.py"


def _config(db_path: Path, monkeypatch) -> Config:
    url = f"sqlite+aiosqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", url)
    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", url)
    return config


def test_delivery_outbox_migration_has_target_links_and_dedupe_constraint(
    tmp_path,
    monkeypatch,
):
    assert MIGRATION.exists(), "012 delivery outbox migration is missing"
    db_path = tmp_path / "outbox.sqlite"
    config = _config(db_path, monkeypatch)
    command.upgrade(config, "012")

    with sqlite3.connect(db_path) as connection:
        columns = {
            row[1]: {"type": row[2], "nullable": not bool(row[3]), "default": row[4]}
            for row in connection.execute("PRAGMA table_info(delivery_outbox)")
        }
        assert set(columns) == {
            "id",
            "tenant_id",
            "action_id",
            "kind",
            "dedupe_key",
            "notification_attempt_id",
            "webhook_delivery_id",
            "status",
            "attempt_count",
            "next_attempt_at",
            "lease_owner",
            "lease_expires_at",
            "last_error",
            "delivered_at",
            "created_at",
            "updated_at",
        }
        assert columns["status"]["default"] == "'pending'"
        assert columns["attempt_count"]["default"] == "0"
        foreign_targets = {
            row[3]: row[2] for row in connection.execute("PRAGMA foreign_key_list(delivery_outbox)")
        }
        assert foreign_targets == {
            "tenant_id": "tenants",
            "action_id": "approvals",
            "notification_attempt_id": "notification_attempts",
            "webhook_delivery_id": "webhook_deliveries",
        }
        indexes = list(connection.execute("PRAGMA index_list(delivery_outbox)"))
        unique_columns = {
            tuple(column[2] for column in connection.execute(f"PRAGMA index_info('{index[1]}')"))
            for index in indexes
            if index[2]
        }
        assert ("tenant_id", "dedupe_key") in unique_columns
        assert ("notification_attempt_id",) in unique_columns
        assert ("webhook_delivery_id",) in unique_columns
        index_columns = {
            tuple(column[2] for column in connection.execute(f"PRAGMA index_info('{index[1]}')"))
            for index in indexes
        }
        assert ("status", "next_attempt_at") in index_columns
        assert ("status", "lease_expires_at") in index_columns
        table_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'delivery_outbox'"
        ).fetchone()[0]
        assert "attempt_count >= 0" in table_sql
        assert "kind = 'approval.webhook'" in table_sql

    command.downgrade(config, "011")
    with sqlite3.connect(db_path) as connection:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    assert "delivery_outbox" not in tables
