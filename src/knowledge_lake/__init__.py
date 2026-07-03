"""
Knowledge Lake Framework — domain-agnostic framework for turning resources into AI-ready assets.

Every resource ingested is traceable from raw source through every transformation to its
final AI-ready output. External tools are plugins; lineage and registries are core.
"""

import os
import sys
from importlib.metadata import PackageNotFoundError, version

import structlog

try:
    __version__ = version("knowledge-lake")
except PackageNotFoundError:
    __version__ = "0.0.0"


def _configure_logging() -> None:
    """Configure structlog once at package import.

    Uses ConsoleRenderer (human-readable, coloured) when stdout is a TTY or
    KLAKE_LOG_FORMAT=dev is set. Falls back to JSONRenderer for production
    (log aggregators require JSON-structured logs per CLAUDE.md). (WR-01)
    """
    _use_dev = sys.stdout.isatty() or os.environ.get("KLAKE_LOG_FORMAT", "").lower() == "dev"
    _renderer = (
        structlog.dev.ConsoleRenderer()
        if _use_dev
        else structlog.processors.JSONRenderer()
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            _renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(20),  # INFO
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


_configure_logging()

__all__ = ["__version__"]
