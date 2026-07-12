"""Add dataset_examples table and real columns to datasets (DATA-01, DATA-02, DATA-03).

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-06

This migration extends the Phase 1 placeholder `datasets` table with real columns
for dataset type, format, example count, and storage URI, adds a UNIQUE constraint
on dataset name (so get_or_create_dataset() works safely), and creates a new
`dataset_examples` join table that records per-example lineage back to the source
chunk or enriched_document artifact.

Design decisions this migration implements:
  D-08: dataset_examples are NOT individual Artifact/lineage-tree nodes —
        they live in their own join table with a nullable FK to artifacts.id
        (source_artifact_id), so per-example lineage is queryable without
        exploding the artifacts table at QA-pair granularity.
  DATA-03: every generated example records non-null source_artifact_id resolving
           back to its originating chunk (DATA-01) or enriched_document (DATA-02).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic
revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── Extend datasets table with real columns ──────────────────────────────
    op.add_column("datasets", sa.Column("dataset_type", sa.String(64), nullable=True))
    op.add_column("datasets", sa.Column("format", sa.String(32), nullable=True))
    op.add_column("datasets", sa.Column("example_count", sa.Integer(), nullable=True))
    op.add_column("datasets", sa.Column("storage_uri", sa.Text(), nullable=True))

    # Unique constraint on name so get_or_create_dataset() is race-safe
    op.create_unique_constraint("uq_datasets_name", "datasets", ["name"])

    # ── Create dataset_examples table ────────────────────────────────────────
    op.create_table(
        "dataset_examples",
        sa.Column("id", sa.String(64), nullable=False, primary_key=True),
        sa.Column(
            "dataset_id",
            sa.String(64),
            sa.ForeignKey("datasets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_artifact_id",
            sa.String(64),
            sa.ForeignKey("artifacts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("example_index", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index(
        "ix_dataset_examples_dataset_id",
        "dataset_examples",
        ["dataset_id"],
    )
    op.create_index(
        "ix_dataset_examples_source_artifact_id",
        "dataset_examples",
        ["source_artifact_id"],
    )


def downgrade() -> None:
    # Drop dataset_examples (reverse order)
    op.drop_index("ix_dataset_examples_source_artifact_id", table_name="dataset_examples")
    op.drop_index("ix_dataset_examples_dataset_id", table_name="dataset_examples")
    op.drop_table("dataset_examples")

    # Remove unique constraint and columns from datasets (reverse order)
    op.drop_constraint("uq_datasets_name", "datasets", type_="unique")
    op.drop_column("datasets", "storage_uri")
    op.drop_column("datasets", "example_count")
    op.drop_column("datasets", "format")
    op.drop_column("datasets", "dataset_type")
