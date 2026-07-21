"""Add dataset_projects + dataset_specs tables, Dataset FK columns (PROJ-01..03, SPEC-01..03).

Revision ID: 0012
Revises: 0011
Create Date: 2026-07-21

This is the FK-dependency root for the entire v2.7 milestone (ARCHITECTURE.md
build-order #1): every later v2.7 table that scopes to a Dataset Project or a
specific Dataset Specification version FKs into the two tables created here.

Creates:
  - ``dataset_projects`` (PROJ-01..03) — the 11-state lifecycle project
    record, unique on ``name``.
  - ``dataset_specs`` (SPEC-01..03) — an insert-only, self-referencing-chain
    table. Immutability is by table design (no ``UPDATE``-capable function
    will ever exist for it), not a DB trigger — deliberately simpler than
    Phase 30's ``dataset_releases`` immutability trigger, which needs a
    post-hoc mutation exemption this table never needs. It has NO ``status``
    column: ``DatasetProject.status`` is the single source of truth.

Also adds, in this SAME migration file (Pitfall 5 — never split a new table +
FK columns on an existing table across two migrations):
  - ``datasets.dataset_project_id`` — NULLABLE, no server_default, no
    backfill (Pitfall 3). Every pre-v2.7 ``Dataset`` row keeps this NULL
    permanently; there is no correct backfill value for legacy rows.
  - ``datasets.dataset_spec_id`` — NULLABLE, same rationale.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic
revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── dataset_projects ──────────────────────────────────────────────────────
    op.create_table(
        "dataset_projects",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("purpose", sa.Text(), nullable=True),
        sa.Column("intended_uses", sa.JSON(), nullable=True),
        sa.Column("prohibited_uses", sa.JSON(), nullable=True),
        sa.Column("dataset_type", sa.String(64), nullable=False),
        sa.Column("domain", sa.String(64), nullable=True),
        sa.Column("owners", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
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
        "uq_dataset_projects_name", "dataset_projects", ["name"]
    )
    op.create_index(
        "ix_dataset_projects_domain", "dataset_projects", ["domain"]
    )

    # ── dataset_specs ─────────────────────────────────────────────────────────
    op.create_table(
        "dataset_specs",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "dataset_project_id",
            sa.String(64),
            sa.ForeignKey("dataset_projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "parent_spec_id",
            sa.String(64),
            sa.ForeignKey("dataset_specs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("spec", sa.JSON(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("schema_version", sa.String(16), nullable=False),
        sa.Column("author", sa.String(255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_dataset_specs_dataset_project_id",
        "dataset_specs",
        ["dataset_project_id"],
    )
    op.create_index(
        "ix_dataset_specs_content_hash", "dataset_specs", ["content_hash"]
    )

    # ── datasets: new nullable FK columns (Pitfall 3, Pitfall 5) ────────────────
    op.add_column(
        "datasets",
        sa.Column(
            "dataset_project_id",
            sa.String(64),
            sa.ForeignKey("dataset_projects.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "datasets",
        sa.Column(
            "dataset_spec_id",
            sa.String(64),
            sa.ForeignKey("dataset_specs.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    # Exact reverse order (Pitfall 5) — drop columns that FK into the new
    # tables before dropping the tables themselves, and drop dataset_specs
    # (which FKs into dataset_projects) before dropping dataset_projects.
    op.drop_column("datasets", "dataset_spec_id")
    op.drop_column("datasets", "dataset_project_id")

    op.drop_index("ix_dataset_specs_content_hash", table_name="dataset_specs")
    op.drop_index(
        "ix_dataset_specs_dataset_project_id", table_name="dataset_specs"
    )
    op.drop_table("dataset_specs")

    op.drop_index("ix_dataset_projects_domain", table_name="dataset_projects")
    op.drop_constraint(
        "uq_dataset_projects_name", "dataset_projects", type_="unique"
    )
    op.drop_table("dataset_projects")
