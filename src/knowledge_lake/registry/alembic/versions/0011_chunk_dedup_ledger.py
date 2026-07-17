"""Add chunk_dedup_ledger table — corpus-wide exact-dedup ledger (DEDUP-01..03).

Revision ID: 0011
Revises: 0010
Create Date: 2026-07-17

Index-time deduplication (v2.6 D-3, DEDUP-01/02/03) needs a durable,
concurrency-safe record of which (collection, text_sha256) pairs have already
been claimed and by whom. This table is that record: Postgres is the source
of truth (D-13) and the Qdrant payload's ``contributors``/``contributor_count``
fields are a rebuildable mirror of it.

The unique constraint is scoped to ``(collection, text_sha256)`` — not
``text_sha256`` alone (D-12) — so the same text in two different collection
aliases claims two independent rows; wiping/recreating one collection never
starves another of points because of a stale cross-alias ledger claim.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic
revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "chunk_dedup_ledger",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("collection", sa.String(128), nullable=False),
        sa.Column("text_sha256", sa.String(64), nullable=False),
        sa.Column("point_id", sa.String(64), nullable=False),
        sa.Column("primary_chunk_id", sa.String(64), nullable=False),
        sa.Column("primary_parsed_artifact_id", sa.String(64), nullable=False),
        sa.Column("primary_source_id", sa.String(64), nullable=True),
        sa.Column("primary_created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "contributors",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
        sa.Column(
            "contributor_count",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_unique_constraint(
        "uq_chunk_dedup_ledger_collection_text_sha256",
        "chunk_dedup_ledger",
        ["collection", "text_sha256"],
    )
    op.create_index(
        "ix_chunk_dedup_ledger_collection",
        "chunk_dedup_ledger",
        ["collection"],
    )


def downgrade() -> None:
    op.drop_index("ix_chunk_dedup_ledger_collection", table_name="chunk_dedup_ledger")
    op.drop_constraint(
        "uq_chunk_dedup_ledger_collection_text_sha256",
        "chunk_dedup_ledger",
        type_="unique",
    )
    op.drop_table("chunk_dedup_ledger")
