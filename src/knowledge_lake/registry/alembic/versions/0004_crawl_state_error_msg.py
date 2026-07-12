"""Add error_msg column to crawl_states for failure diagnostics (WR-03).

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-04

This migration:
  - Adds error_msg (Text, nullable) to crawl_states
  - Stores the human-readable failure reason for 'failed'/'robots_blocked' states
  - NULL for successful 'complete' states

Without this column, operators cannot determine which URLs failed or why from
the registry alone, making production triage of crawl failures impossible.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic
revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "crawl_states",
        sa.Column("error_msg", sa.Text, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("crawl_states", "error_msg")
