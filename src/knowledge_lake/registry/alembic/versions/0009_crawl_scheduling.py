"""Add crawl scheduling columns to sources (SCHED-01, SCHED-02).

Revision ID: 0009
Revises: 0008
Create Date: 2026-07-10

Adds three nullable columns to the sources table for scheduled re-crawl
support:
  - crawl_schedule: 5-field UTC cron string (NULL = not auto-recrawled)
  - last_crawled_at: UTC timestamp of last re-crawl attempt
  - last_content_hash: SHA256 over normalized silver-stage text (change gate)

All columns are nullable with no server_default and no backfill —
forward-only, additive migration (D-01). Existing sources see NULL in all
three columns, which means "not scheduled" / "never crawled" / "always crawl".
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic
revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("sources", sa.Column("crawl_schedule", sa.String(255), nullable=True))
    op.add_column("sources", sa.Column("last_crawled_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("sources", sa.Column("last_content_hash", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("sources", "last_content_hash")
    op.drop_column("sources", "last_crawled_at")
    op.drop_column("sources", "crawl_schedule")
