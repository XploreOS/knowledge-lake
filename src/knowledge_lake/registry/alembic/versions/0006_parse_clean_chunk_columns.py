"""Add quality_score, language, dedup_status to artifacts table (PARSE-04, CLEAN-02, CLEAN-03).

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-05

Adds three columns to the artifacts table to support Phase 3 parse/clean pipeline:

1. quality_score FLOAT (nullable) — heuristic 0.0–1.0 parse quality score computed
   by quality/scorer.py after each parse run (PARSE-04, D-04).

2. language VARCHAR(16) (nullable) — ISO 639-1 language code detected by
   lingua-language-detector, e.g. "en" (CLEAN-02).

3. dedup_status VARCHAR(32) (nullable) — deduplication status flag (CLEAN-03):
   NULL  = not yet checked
   "unique"    = confirmed unique in corpus
   "exact_dup" = exact hash match to an earlier artifact
   "near_dup"  = near-duplicate via MinHash LSH (Jaccard >= threshold)
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic
revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("artifacts", sa.Column("quality_score", sa.Float(), nullable=True))
    op.add_column("artifacts", sa.Column("language", sa.String(16), nullable=True))
    op.add_column("artifacts", sa.Column("dedup_status", sa.String(32), nullable=True))


def downgrade() -> None:
    op.drop_column("artifacts", "dedup_status")
    op.drop_column("artifacts", "language")
    op.drop_column("artifacts", "quality_score")
