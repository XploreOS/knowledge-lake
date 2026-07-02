"""
Knowledge Lake Dagster definitions — minimal real Definitions() for FOUND-01.

This file provides a valid Dagster code location so the compose dagster service
can load and display a healthy asset graph. Pipeline assets (ingest, parse, chunk,
embed, index) are added in plan 01-05 after the plain-function pipeline is proven
(D-01/D-02 — prove flow first, orchestrate second).

The dagster service entry point in docker-compose.yml points to this module.
"""

from __future__ import annotations

import structlog
from dagster import Definitions

logger = structlog.get_logger(__name__)

# ── Minimal real Definitions ──────────────────────────────────────────────────
# Phase 1: no assets yet — the compose service runs healthy with an empty asset graph.
# Assets wrapping the pipeline functions are added before the phase closes (D-01).

defs = Definitions(
    assets=[],
    resources={},
)
