"""
Shared fixtures for integration tests.

The session-scoped ``_apply_migrations`` fixture runs ``alembic upgrade head``
on both the default database (used by most integration tests via get_settings()
defaults) and the dedicated test database (used by test_migrations.py and any
test that injects the ``settings`` fixture). This ensures all registry tables
exist before any test hits the DB.
"""

from __future__ import annotations

import pytest
from alembic import command
from alembic.config import Config

DEFAULT_DB_URL = "postgresql+psycopg://klake:klake@localhost:5432/klake"
TEST_DB_URL = "postgresql+psycopg://klake:klake@localhost:5432/klake_test"


def _alembic_cfg(db_url: str) -> Config:
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", db_url)
    return cfg


@pytest.fixture(scope="session", autouse=True)
def _apply_migrations():
    """Run alembic upgrade head on both databases before integration tests."""
    for url in (DEFAULT_DB_URL, TEST_DB_URL):
        cfg = _alembic_cfg(url)
        command.upgrade(cfg, "head")
    yield
