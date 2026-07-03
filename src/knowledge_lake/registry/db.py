"""
SQLAlchemy engine and session factory for the Knowledge Lake registry.

All registry database access goes through this module.  The engine is built
once from ``Settings.database_url`` so there is a single connection pool for
the process lifetime.

Usage::

    from knowledge_lake.registry.db import get_session

    with get_session() as session:
        source = repo.create_source(session, name="…", source_type="web")
        session.commit()

For background tasks (Dagster assets), use ``engine`` directly with
``Session(engine)`` for explicit lifecycle control.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from knowledge_lake.config.settings import get_settings


def _build_engine() -> Engine:
    """Build a SQLAlchemy engine from the current Settings.database_url.

    Called once at module import time.  Tests can monkey-patch ``get_settings``
    or replace the module-level ``engine`` to point at a test database.
    """
    settings = get_settings()
    return create_engine(
        settings.database_url,
        pool_pre_ping=True,           # auto-reconnect on stale connections
        echo=False,                   # flip to True for SQL debugging
    )


# Module-level engine — shared across the process lifetime.
# Tests that need a different database should replace this attribute.
engine: Engine = _build_engine()


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """Yield a managed SQLAlchemy session.

    Commits on clean exit; rolls back and re-raises on any exception.

    Example::

        with get_session() as session:
            repo.create_source(session, name="…", source_type="web")
    """
    with Session(engine) as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
