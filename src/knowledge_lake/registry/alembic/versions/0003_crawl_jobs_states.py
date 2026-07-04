"""Extend jobs table and create crawl_states for per-URL crawl tracking.

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-03

This migration:
  - Adds columns to jobs: source_id, job_type, crawler, config, stats, updated_at
  - Creates crawl_states table with UNIQUE(job_id, normalized_url)
  - Creates index ix_crawl_states_job_status on (job_id, status) for resume query

The UNIQUE constraint is keyed on (job_id, normalized_url) NOT content_hash —
identical content under a new URL produces a new state row pointing at the
no-op'd existing artifact (Pitfall 4, T-02-05).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic
revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Extend jobs table ────────────────────────────────────────────────────
    op.add_column(
        "jobs",
        sa.Column(
            "source_id",
            sa.String(64),
            sa.ForeignKey("sources.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "jobs",
        sa.Column("job_type", sa.String(32), nullable=False, server_default="crawl"),
    )
    op.add_column(
        "jobs",
        sa.Column("crawler", sa.String(64), nullable=True),
    )
    op.add_column(
        "jobs",
        sa.Column("config", sa.JSON, nullable=True),
    )
    op.add_column(
        "jobs",
        sa.Column("stats", sa.JSON, nullable=True),
    )
    op.add_column(
        "jobs",
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )

    # ── Create crawl_states table ────────────────────────────────────────────
    op.create_table(
        "crawl_states",
        sa.Column("id", sa.String(64), nullable=False, primary_key=True),
        sa.Column(
            "job_id",
            sa.String(64),
            sa.ForeignKey("jobs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("url", sa.Text, nullable=False),
        sa.Column("normalized_url", sa.Text, nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column(
            "raw_artifact_id",
            sa.String(64),
            sa.ForeignKey("artifacts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "bronze_artifact_id",
            sa.String(64),
            sa.ForeignKey("artifacts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )

    # UNIQUE on (job_id, normalized_url) — NOT content_hash (Pitfall 4)
    op.create_unique_constraint(
        "uq_crawl_states_job_url",
        "crawl_states",
        ["job_id", "normalized_url"],
    )

    # Index for resume query: WHERE job_id = ? AND status = 'pending'
    op.create_index(
        "ix_crawl_states_job_status",
        "crawl_states",
        ["job_id", "status"],
    )

    # Index on job_id for FK lookups
    op.create_index(
        "ix_crawl_states_job_id",
        "crawl_states",
        ["job_id"],
    )


def downgrade() -> None:
    # Drop crawl_states (reverse order)
    op.drop_index("ix_crawl_states_job_id", table_name="crawl_states")
    op.drop_index("ix_crawl_states_job_status", table_name="crawl_states")
    op.drop_constraint("uq_crawl_states_job_url", "crawl_states", type_="unique")
    op.drop_table("crawl_states")

    # Remove jobs columns (reverse order of addition)
    op.drop_column("jobs", "updated_at")
    op.drop_column("jobs", "stats")
    op.drop_column("jobs", "config")
    op.drop_column("jobs", "crawler")
    op.drop_column("jobs", "job_type")
    op.drop_column("jobs", "source_id")
