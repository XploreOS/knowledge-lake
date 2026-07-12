"""Add llm_spend and vector_collections tables (ENRICH-05, INDEX-02).

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-05

This migration creates two new tables that give the Phase 4 enrichment and
index/search vertical slices a registry-queryable accounting mechanism:

1. llm_spend — accumulates LLM call cost in USD per scope (ENRICH-05's
   budget cap needs a concrete place to track spend against the cap). A
   UNIQUE constraint on `scope` lets record_llm_spend() safely get-or-create
   a single row per scope without racing (enrichment stays serial regardless
   for Phase 4 MVP, but the constraint prevents accidental duplicate rows).

2. vector_collections — tracks which physical Qdrant collection each stable
   alias currently resolves to (INDEX-02, D-06), independent of Qdrant's own
   alias listing, so zero-downtime reindexing can be driven and audited from
   the registry. A UNIQUE constraint on `physical_collection` prevents two
   alias rows from ever pointing at the same physical collection.

Note: Artifact.quality_score itself needs NO new column here — migration
0006 already added it physically to the artifacts table. This migration
only maps it as a real ORM attribute in models.py.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic
revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── Create llm_spend table ───────────────────────────────────────────────
    op.create_table(
        "llm_spend",
        sa.Column("id", sa.String(64), nullable=False, primary_key=True),
        sa.Column("scope", sa.String(64), nullable=False),
        sa.Column(
            "total_cost_usd",
            sa.Float(),
            nullable=False,
            server_default="0.0",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_unique_constraint(
        "uq_llm_spend_scope",
        "llm_spend",
        ["scope"],
    )

    # ── Create vector_collections table ──────────────────────────────────────
    op.create_table(
        "vector_collections",
        sa.Column("id", sa.String(64), nullable=False, primary_key=True),
        sa.Column("alias_name", sa.String(128), nullable=False),
        sa.Column("physical_collection", sa.String(128), nullable=False),
        sa.Column("dim", sa.Integer(), nullable=False),
        sa.Column(
            "is_current",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index(
        "ix_vector_collections_alias_name",
        "vector_collections",
        ["alias_name"],
    )
    op.create_unique_constraint(
        "uq_vector_collections_physical",
        "vector_collections",
        ["physical_collection"],
    )


def downgrade() -> None:
    # Drop vector_collections (reverse order)
    op.drop_constraint(
        "uq_vector_collections_physical", "vector_collections", type_="unique"
    )
    op.drop_index("ix_vector_collections_alias_name", table_name="vector_collections")
    op.drop_table("vector_collections")

    # Drop llm_spend (reverse order)
    op.drop_constraint("uq_llm_spend_scope", "llm_spend", type_="unique")
    op.drop_table("llm_spend")
