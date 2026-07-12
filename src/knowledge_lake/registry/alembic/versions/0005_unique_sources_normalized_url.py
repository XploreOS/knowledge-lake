"""Add UNIQUE constraint on sources.normalized_url and partial unique index on jobs.

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-04

This migration fixes two concurrent-write races (CR-004, WR-005):

1. UNIQUE constraint on sources.normalized_url (WR-005):
   Migration 0002 added only a plain index (ix_sources_normalized_url), which does
   not prevent concurrent workers from inserting duplicate source rows for the same
   URL.  A UNIQUE constraint enforces uniqueness at the database level — callers
   should catch IntegrityError as the dedup signal.

2. Partial UNIQUE index on jobs (source_id, crawler) for active jobs (CR-004):
   _find_or_create_job checks for an existing job in one session then creates a
   new one in a second session — a classic TOCTOU race.  A partial unique index
   on (source_id, crawler) WHERE status IN ('running', 'pending') makes duplicate
   active-job creation an IntegrityError rather than silently inserting two rows.

Note: PostgreSQL supports partial unique indexes but SQLite does not.  The
partial index is created with a WHERE clause; SQLite will silently create a
non-partial index if the dialect does not support partial indexes.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic
revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # WR-005: promote the existing plain index to a UNIQUE constraint
    # Drop the old plain index first (avoids duplicate index overhead)
    op.drop_index("ix_sources_normalized_url", table_name="sources")
    op.create_unique_constraint(
        "uq_sources_normalized_url",
        "sources",
        ["normalized_url"],
    )

    # CR-004: partial unique index on jobs for active (running/pending) jobs
    # Prevents duplicate job creation for the same (source_id, crawler) pair.
    op.create_index(
        "uq_jobs_source_crawler_active",
        "jobs",
        ["source_id", "crawler"],
        unique=True,
        postgresql_where=sa.text("status IN ('running', 'pending')"),
    )


def downgrade() -> None:
    op.drop_index("uq_jobs_source_crawler_active", table_name="jobs")
    op.drop_constraint("uq_sources_normalized_url", "sources", type_="unique")
    op.create_index(
        "ix_sources_normalized_url",
        "sources",
        ["normalized_url"],
    )
