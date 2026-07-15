"""Add indexed sources.domain column, backfilled from config->>'domain' (KL-15).

Revision ID: 0010
Revises: 0009
Create Date: 2026-07-15

Domain is first-class in the CLI (``--domain``), the storage layout
(``raw/{domain}/…``), the pack system, and the export filter (KL-01) — but it
has always lived unindexed, unvalidated, and unconstrained inside
``sources.config`` (a JSON blob keyed by ``"domain"``).

This migration adds a nullable, indexed ``domain`` column and backfills it
from ``config->>'domain'`` for every existing row. The backfill is done
Python-side (SELECT id, config; per-row UPDATE) rather than a single dialect
SQL statement, so it works identically regardless of whether ``config`` is
stored as JSON or JSONB and needs no dialect branching.

The application-layer write sites (``pipeline/ingest.py``'s
``register_source`` and ``pipeline/domains.py``'s ``load_domain``) continue
to ALSO write ``config["domain"]`` for one release after this migration —
that dual-write is intentional (see ``registry/models.py``'s ``Source.domain``
docstring) and is not touched here; this migration only adds and backfills
the column.

downgrade() drops the column and its index — config["domain"] survives the
round-trip untouched since this migration never modifies or removes it.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic
revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("sources", sa.Column("domain", sa.String(64), nullable=True))
    op.create_index("ix_sources_domain", "sources", ["domain"])

    # Backfill existing rows from config->>'domain' (dialect-agnostic Python loop —
    # avoids JSON vs JSONB operator differences between SQLite and PostgreSQL).
    conn = op.get_bind()
    sources_tbl = sa.table(
        "sources",
        sa.column("id", sa.String),
        sa.column("config", sa.JSON),
        sa.column("domain", sa.String),
    )
    rows = conn.execute(sa.select(sources_tbl.c.id, sources_tbl.c.config)).fetchall()
    for row in rows:
        cfg = row.config
        if isinstance(cfg, dict) and cfg.get("domain"):
            conn.execute(
                sources_tbl.update()
                .where(sources_tbl.c.id == row.id)
                .values(domain=cfg["domain"])
            )


def downgrade() -> None:
    op.drop_index("ix_sources_domain", table_name="sources")
    op.drop_column("sources", "domain")
