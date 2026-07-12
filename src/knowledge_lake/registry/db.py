"""
SQLAlchemy engine and session factory for the Knowledge Lake registry.

All registry database access goes through this module.  The engine is built
lazily on first use (via ``get_engine()``) rather than at module import time.
This prevents env-var reads during test collection and allows tests that
set KLAKE_DATABASE_URL before the first session to use the correct URL.

Usage::

    from knowledge_lake.registry.db import get_session

    with get_session() as session:
        source = repo.create_source(session, name="…", source_type="web")
        session.commit()

For tests or Dagster assets that need a custom engine, monkey-patch ``get_engine``
(or replace the module-level ``_engine`` attribute) before any session is opened.
"""

from __future__ import annotations

import threading
from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from knowledge_lake.config.settings import get_settings


def _build_engine() -> Engine:
    """Build a SQLAlchemy engine from the current Settings.database_url."""
    settings = get_settings()
    return create_engine(
        settings.database_url,
        pool_pre_ping=True,           # auto-reconnect on stale connections
        echo=False,                   # flip to True for SQL debugging
    )


# Module-level engine holder — lazily initialised on first get_engine() call (CR-05).
# None means "not yet built". Tests can monkey-patch get_engine() or reset _engine
# to None to force a fresh build after changing KLAKE_DATABASE_URL.
_engine: Engine | None = None
_engine_lock = threading.Lock()


def get_engine() -> Engine:
    """Return the shared SQLAlchemy engine, building it lazily on first call.

    Lazy initialisation means importing this module does NOT trigger a
    Settings load or .env file read, so test collection is safe and tests
    that set KLAKE_DATABASE_URL before first use receive the correct engine.

    Uses double-checked locking (WR-01) to prevent two threads from both
    calling _build_engine() simultaneously under concurrent access (e.g.
    multiple uvicorn worker threads or parallel Dagster assets). Only one
    engine and one connection pool are ever created per process.
    """
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:  # double-checked locking
                _engine = _build_engine()
    return _engine


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """Yield a managed SQLAlchemy session.

    Commits on clean exit; rolls back and re-raises on any exception.

    Example::

        with get_session() as session:
            repo.create_source(session, name="…", source_type="web")
    """
    with Session(get_engine()) as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
