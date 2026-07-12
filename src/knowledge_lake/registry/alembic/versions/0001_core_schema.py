"""Create the full core schema.

Revision ID: 0001
Revises:
Create Date: 2026-07-02

This migration creates the complete core table set (FOUND-05, FOUND-09):
  - sources            — document origins
  - artifacts          — self-referencing lineage node (raw/parsed/chunk)
  - lineage_events     — explicit edge log for provenance
  - jobs               — pipeline job records (empty; exercised in later phases)
  - datasets           — curated dataset records (empty; exercised in Phase 5)

Indexes on artifacts:
  - content_hash       (dedup lookup / FOUND-04)
  - source_id          (query by source)
  - parent_artifact_id (lineage tree walk)
  - created_at         (time-range queries)

UNIQUE(content_hash, artifact_type) on artifacts prevents duplicate nodes of
the same content type (FOUND-04 dedup constraint).

No Base.metadata.create_all() is ever called — Alembic is the sole DDL
authority (FOUND-09, Pitfall 10).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic
revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── sources ──────────────────────────────────────────────────────────────
    op.create_table(
        "sources",
        sa.Column("id", sa.String(64), nullable=False, primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("source_type", sa.String(64), nullable=False),
        sa.Column("url", sa.Text, nullable=True),
        sa.Column("license_type", sa.String(64), nullable=True),
        sa.Column("license_url", sa.Text, nullable=True),
        sa.Column("robots_checked", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("config", sa.JSON, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )

    # ── artifacts ─────────────────────────────────────────────────────────────
    op.create_table(
        "artifacts",
        sa.Column("id", sa.String(64), nullable=False, primary_key=True),
        sa.Column(
            "source_id",
            sa.String(64),
            sa.ForeignKey("sources.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "parent_artifact_id",
            sa.String(64),
            sa.ForeignKey("artifacts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("artifact_type", sa.String(64), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("pipeline_version", sa.String(64), nullable=False),
        sa.Column("storage_uri", sa.Text, nullable=True),
        sa.Column("mime_type", sa.String(128), nullable=True),
        sa.Column("page_ref", sa.Integer, nullable=True),
        sa.Column("section_path", sa.Text, nullable=True),
        sa.Column("metadata", sa.JSON, nullable=True, server_default=sa.text("'{}'")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )

    # UNIQUE(content_hash, artifact_type) — FOUND-04 dedup constraint
    op.create_unique_constraint(
        "uq_artifacts_hash_type",
        "artifacts",
        ["content_hash", "artifact_type"],
    )

    # Indexes on artifacts for common query patterns
    op.create_index("ix_artifacts_content_hash", "artifacts", ["content_hash"])
    op.create_index("ix_artifacts_source_id", "artifacts", ["source_id"])
    op.create_index("ix_artifacts_parent_artifact_id", "artifacts", ["parent_artifact_id"])
    op.create_index("ix_artifacts_created_at", "artifacts", ["created_at"])

    # ── lineage_events ────────────────────────────────────────────────────────
    op.create_table(
        "lineage_events",
        sa.Column("id", sa.String(64), nullable=False, primary_key=True),
        sa.Column(
            "artifact_id",
            sa.String(64),
            sa.ForeignKey("artifacts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "parent_artifact_id",
            sa.String(64),
            sa.ForeignKey("artifacts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("relationship", sa.String(64), nullable=False),
        sa.Column("pipeline_version", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index("ix_lineage_events_artifact_id", "lineage_events", ["artifact_id"])
    op.create_index(
        "ix_lineage_events_parent_artifact_id",
        "lineage_events",
        ["parent_artifact_id"],
    )

    # ── jobs (empty, satisfies FOUND-05 enumerated set) ──────────────────────
    op.create_table(
        "jobs",
        sa.Column("id", sa.String(64), nullable=False, primary_key=True),
        sa.Column("status", sa.String(32), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )

    # ── datasets (empty, satisfies FOUND-05 enumerated set) ──────────────────
    op.create_table(
        "datasets",
        sa.Column("id", sa.String(64), nullable=False, primary_key=True),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )


def downgrade() -> None:
    # Drop in reverse dependency order
    op.drop_table("datasets")
    op.drop_table("jobs")
    op.drop_index("ix_lineage_events_parent_artifact_id", table_name="lineage_events")
    op.drop_index("ix_lineage_events_artifact_id", table_name="lineage_events")
    op.drop_table("lineage_events")
    op.drop_index("ix_artifacts_created_at", table_name="artifacts")
    op.drop_index("ix_artifacts_parent_artifact_id", table_name="artifacts")
    op.drop_index("ix_artifacts_source_id", table_name="artifacts")
    op.drop_index("ix_artifacts_content_hash", table_name="artifacts")
    op.drop_constraint("uq_artifacts_hash_type", "artifacts", type_="unique")
    op.drop_table("artifacts")
    op.drop_table("sources")
