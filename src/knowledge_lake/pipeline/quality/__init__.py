"""Pure, zero-I/O quality predicate package (QUAL-01).

Composable predicate functions of the shape
``f(text: str, metadata: dict) -> PredicateResult(passed, reason)``, a
``run_predicates()`` combinator, and a ``compute_substance_signals()`` helper.
Zero dependencies on I/O, S3, Dagster, or ``knowledge_lake.config.settings`` —
independently importable and testable with no infrastructure.

Consumed by Plan 19-04's ``classify_sections()`` (section-level
classification, CLEAN-04) and, per D-12, by Phase 20's chunk-level substance
gate (QUAL-03).
"""

from __future__ import annotations

from knowledge_lake.pipeline.quality.predicates import (
    PredicateResult,
    check_alpha_ratio,
    check_domain_allowlist,
    check_link_density,
    check_stopword_ratio,
    check_table_exemption,
    check_terminal_punct_ratio,
    check_token_floor,
    compute_substance_signals,
    run_predicates,
)

__all__ = [
    "PredicateResult",
    "check_token_floor",
    "check_alpha_ratio",
    "check_link_density",
    "check_stopword_ratio",
    "check_terminal_punct_ratio",
    "check_table_exemption",
    "check_domain_allowlist",
    "compute_substance_signals",
    "run_predicates",
]
