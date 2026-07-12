"""Add normalized_url column to sources table for URL-first dedup.

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-03

This migration adds:
  - sources.normalized_url (Text, nullable) — D-06 conservative normalization
  - ix_sources_normalized_url index on sources.normalized_url

The column is nullable so existing Phase 1 rows remain valid without a
data migration backfill.  New source registrations will always populate
normalized_url via normalize_url().

URL-first dedup (D-05) queries this column via
repo.get_source_by_normalized_url() before creating a new source.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic
revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "sources",
        sa.Column("normalized_url", sa.Text, nullable=True),
    )
    op.create_index(
        "ix_sources_normalized_url",
        "sources",
        ["normalized_url"],
    )


def downgrade() -> None:
    op.drop_index("ix_sources_normalized_url", table_name="sources")
    op.drop_column("sources", "normalized_url")
