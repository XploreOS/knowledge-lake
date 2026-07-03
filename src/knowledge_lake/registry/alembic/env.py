"""
Alembic environment script for Knowledge Lake registry migrations.

DB URL is read from Settings.database_url (never from alembic.ini) so
no credentials need to be committed to the repository.

target_metadata is set to the models' MetaData so autogenerate works
correctly and all table definitions are known to Alembic.
"""

from __future__ import annotations

import re
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# ── Import models so their metadata is registered ────────────────────────────
# All model classes must be imported (or their module imported) BEFORE
# calling context.configure() so Alembic's autogenerate detects them.
from knowledge_lake.registry.models import Base  # noqa: F401

# ── Alembic config object ─────────────────────────────────────────────────────
config = context.config

# Set up Python logging from alembic.ini if a file config is present.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ── Target metadata ───────────────────────────────────────────────────────────
# Alembic uses this to compare the current DB state against the models
# when autogenerating migrations.
target_metadata = Base.metadata


def _get_db_url() -> str:
    """Return the database URL for Alembic to use.

    Priority order:
      1. ``sqlalchemy.url`` already set programmatically via
         ``config.set_main_option("sqlalchemy.url", ...)`` — respected
         as-is.  Tests use this to point migrations at a test database.
      2. Settings.database_url (via env/dotenv/defaults) — used when
         running ``alembic upgrade head`` from the CLI without overrides.

    psycopg 3 uses ``postgresql+psycopg://``; async variants are normalised
    to the synchronous driver because Alembic uses synchronous connections.
    """
    # Check for a programmatic override first (set by tests or CI via
    # config.set_main_option("sqlalchemy.url", ...)).
    programmatic_url = config.get_main_option("sqlalchemy.url")
    if programmatic_url:
        url = programmatic_url
    else:
        from knowledge_lake.config.settings import get_settings
        url = get_settings().database_url

    # Normalise async variants to synchronous for Alembic:
    # postgresql+psycopg_async:// -> postgresql+psycopg://
    url = re.sub(r"\+psycopg_async", "+psycopg", url)
    return url


def run_migrations_offline() -> None:
    """Run migrations without a DB connection (generates SQL to stdout)."""
    url = _get_db_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live database connection."""
    # Resolve the URL (respects programmatic overrides from tests/CI).
    db_url = _get_db_url()

    ini_section = config.get_section(config.config_ini_section, {})
    ini_section["sqlalchemy.url"] = db_url

    connectable = engine_from_config(
        ini_section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,  # each migration run gets its own connection
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
