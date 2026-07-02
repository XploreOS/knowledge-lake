"""
Knowledge Lake Framework — domain-agnostic framework for turning resources into AI-ready assets.

Every resource ingested is traceable from raw source through every transformation to its
final AI-ready output. External tools are plugins; lineage and registries are core.
"""

from importlib.metadata import PackageNotFoundError, version

import structlog

try:
    __version__ = version("knowledge-lake")
except PackageNotFoundError:
    __version__ = "0.0.0"


def _configure_logging() -> None:
    """Configure structlog once at package import — structured JSON for all app logging."""
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(20),  # INFO
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


_configure_logging()

__all__ = ["__version__"]
