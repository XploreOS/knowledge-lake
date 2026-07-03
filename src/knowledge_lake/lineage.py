"""Lineage resolver for the Knowledge Lake registry (FOUND-07).

resolve_ancestry(artifact_id) walks the parent_artifact_id chain from any artifact
up to the root (source) using a recursive CTE over the artifacts table.  It returns
all ancestor nodes in order (leaf first, root last), each node carrying all six
FOUND-06 lineage fields:

  id, artifact_type, content_hash, created_at, pipeline_version, storage_uri

plus citation fields (section_path, page) where available.

Security (T-01-13):
  The recursive CTE uses SQLAlchemy text() with bound parameters — no string
  interpolation of user-supplied artifact IDs into SQL.

Rendering:
  render_tree(nodes)  — human-readable ancestry tree (default for CLI)
  nodes_to_json(nodes) — machine-readable JSON (--json flag)

ID prefix expansion:
  resolve_ancestry accepts unambiguous ID prefixes (D-15).  If the supplied ID
  uniquely matches one artifact by prefix, it is accepted.  If ambiguous, raises
  ValueError listing the candidates.
"""

from __future__ import annotations

import datetime
import json
from typing import Any

import structlog
from sqlalchemy import text

from knowledge_lake.registry.db import get_session

log = structlog.get_logger(__name__)

# All six FOUND-06 fields required on every lineage node
FOUND_06_FIELDS = frozenset(
    {"id", "artifact_type", "content_hash", "created_at", "pipeline_version", "storage_uri"}
)

# Recursive CTE query — walks parent_artifact_id upward (parameterised, T-01-13)
_ANCESTRY_CTE_SQL = text("""
WITH RECURSIVE ancestry(
    id,
    source_id,
    parent_artifact_id,
    artifact_type,
    content_hash,
    pipeline_version,
    storage_uri,
    mime_type,
    page_ref,
    section_path,
    created_at,
    depth
) AS (
    -- Anchor: start from the given artifact
    SELECT
        id, source_id, parent_artifact_id, artifact_type,
        content_hash, pipeline_version, storage_uri,
        mime_type, page_ref, section_path, created_at,
        0 AS depth
    FROM artifacts
    WHERE id = :artifact_id

    UNION ALL

    -- Recursive step: walk up to parent
    SELECT
        a.id, a.source_id, a.parent_artifact_id, a.artifact_type,
        a.content_hash, a.pipeline_version, a.storage_uri,
        a.mime_type, a.page_ref, a.section_path, a.created_at,
        anc.depth + 1
    FROM artifacts a
    JOIN ancestry anc ON a.id = anc.parent_artifact_id
    WHERE anc.depth < 50  -- guard against cycles (max 50 hops)
)
SELECT
    id, source_id, parent_artifact_id, artifact_type,
    content_hash, pipeline_version, storage_uri,
    mime_type, page_ref, section_path, created_at,
    depth
FROM ancestry
ORDER BY depth ASC
""")

# Prefix expansion query — find artifacts where id starts with a prefix.
# ESCAPE clause is required to safely handle user-supplied prefixes that may
# contain SQL LIKE wildcards (% or _). (CR-06)
_PREFIX_LOOKUP_SQL = text("""
SELECT id FROM artifacts
WHERE id LIKE :prefix_pattern ESCAPE :escape_char
LIMIT 10
""")


def resolve_ancestry(artifact_id: str) -> list[dict[str, Any]]:
    """Resolve the full ancestry of an artifact via recursive CTE.

    Accepts both full IDs (e.g. 'chk_019f...') and unambiguous ID prefixes
    (D-15): if artifact_id does not contain a '-', it is treated as a prefix
    and expanded to a full ID if unique.

    Args:
        artifact_id: Full artifact ID or unambiguous prefix.

    Returns:
        List of node dicts, ordered leaf-first (depth 0 = the queried artifact).
        Each dict carries all FOUND-06 fields plus section_path and page.

    Raises:
        ValueError: If the artifact ID is not found, or if a prefix matches
                    multiple artifacts (ambiguous prefix).
        LookupError: If the artifact does not exist in the registry.
    """
    # Expand prefix if needed (D-15)
    full_id = _expand_prefix(artifact_id)

    log.info("lineage.resolve_ancestry", artifact_id=full_id)

    with get_session() as session:
        # Use parameterised query — no string interpolation (T-01-13)
        rows = session.execute(
            _ANCESTRY_CTE_SQL,
            {"artifact_id": full_id},
        ).fetchall()

    if not rows:
        raise LookupError(
            f"resolve_ancestry: artifact {full_id!r} not found in registry. "
            "Ensure the artifact was created by the pipeline and the registry is up."
        )

    nodes: list[dict[str, Any]] = []
    for row in rows:
        node: dict[str, Any] = {
            "id": row.id,
            "source_id": row.source_id,
            "parent_artifact_id": row.parent_artifact_id,
            "artifact_type": row.artifact_type,
            "content_hash": row.content_hash,
            "pipeline_version": row.pipeline_version,
            "storage_uri": row.storage_uri,
            "mime_type": row.mime_type,
            "page": row.page_ref,
            "section_path": row.section_path,
            "created_at": (
                row.created_at.isoformat()
                if isinstance(row.created_at, datetime.datetime)
                else str(row.created_at)
            ),
            "depth": row.depth,
        }
        nodes.append(node)

    log.info("lineage.resolved", artifact_id=full_id, depth=len(nodes))
    return nodes


def render_tree(nodes: list[dict[str, Any]]) -> str:
    """Render a human-readable ancestry tree from a list of lineage nodes.

    Output format (leaf first, root last):
        [chunk] chk_019f... (§2 Administrative Safeguards, page 1)
          ↑ ingested from
        [parsed_document] doc_019f... (SHA256: 9082aa...)
          ↑ parsed from
        [raw_document] doc_019e... (SHA256: 2f22dc...)
          ↑ ingested from
        [source] src_019e... (klake-data/raw/...)

    Each node shows id, type, content_hash, timestamp, pipeline_version, storage_uri
    (the six FOUND-06 fields).
    """
    if not nodes:
        return "(no lineage nodes)"

    lines: list[str] = []
    for i, node in enumerate(nodes):
        artifact_type = node.get("artifact_type", "unknown")
        node_id = node.get("id", "?")
        content_hash = node.get("content_hash", "?")
        created_at = node.get("created_at", "?")
        pipeline_version = node.get("pipeline_version", "?")
        storage_uri = node.get("storage_uri") or "(no storage)"
        section_path = node.get("section_path") or ""
        page = node.get("page")

        # Main line: type + ID
        type_label = f"[{artifact_type}]"
        id_label = node_id

        # Optional citation fields
        citation_parts = []
        if section_path:
            citation_parts.append(section_path)
        if page is not None:
            citation_parts.append(f"page {page}")
        citation = f" ({', '.join(citation_parts)})" if citation_parts else ""

        lines.append(f"{type_label} {id_label}{citation}")
        hash_display = content_hash[:16] + "..." if len(content_hash) > 16 else content_hash
        lines.append(f"  hash:     {hash_display}  (sha256, truncated — use --json for full hash)")
        lines.append(f"  version:  {pipeline_version}")
        lines.append(f"  created:  {created_at}")
        lines.append(f"  uri:      {storage_uri}")

        if i < len(nodes) - 1:
            lines.append("  ↑")

    return "\n".join(lines)


def nodes_to_json(nodes: list[dict[str, Any]]) -> str:
    """Serialize lineage nodes to a JSON string (--json flag, D-14).

    Returns a JSON array of node objects, each carrying all six FOUND-06 fields.
    """
    return json.dumps(nodes, indent=2, default=str)


# ── Private helpers ────────────────────────────────────────────────────────────


def _escape_like(value: str) -> str:
    """Escape SQL LIKE wildcard characters in a user-supplied string (CR-06).

    Escapes backslash, percent (%), and underscore (_) so they are treated
    as literal characters in a LIKE pattern rather than wildcards.
    """
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _expand_prefix(artifact_id: str) -> str:
    """Expand an unambiguous ID prefix to a full artifact ID (D-15).

    A full prefixed ID looks like 'chk_019f261f-2887-72e2-82db-bf2bf1aa6fbb'
    — a type prefix (3 chars) + '_' + 36-char UUIDv7 string = ~40 chars total.

    If the artifact_id is >= 40 chars (full ID length), treat it as a full ID
    and return it as-is.  Shorter values are treated as prefixes and expanded.

    Raises ValueError if the prefix is shorter than 4 characters (CR-06: prevent
    full-table scans on empty or single-char inputs).
    """
    # Full ID: type_prefix (2-3 chars) + '_' + 36-char UUID = ~40 chars
    FULL_ID_MIN_LENGTH = 40
    if len(artifact_id) >= FULL_ID_MIN_LENGTH:
        return artifact_id

    # Enforce minimum prefix length to prevent unbounded scans (CR-06)
    if len(artifact_id) < 4:
        raise ValueError(
            f"Artifact ID prefix {artifact_id!r} is too short (minimum 4 characters). "
            "Provide at least the type prefix and first UUID character (e.g. 'chk_0')."
        )

    # Prefix lookup — escape LIKE wildcards in the user-supplied prefix (CR-06)
    with get_session() as session:
        rows = session.execute(
            _PREFIX_LOOKUP_SQL,
            {"prefix_pattern": f"{_escape_like(artifact_id)}%", "escape_char": "\\"},
        ).fetchall()

    matched = [r.id for r in rows]

    if not matched:
        raise ValueError(
            f"No artifact found with ID prefix {artifact_id!r}. "
            "Check the ID or use the full artifact ID."
        )
    if len(matched) > 1:
        raise ValueError(
            f"Ambiguous ID prefix {artifact_id!r} matches multiple artifacts:\n"
            + "\n".join(f"  {m}" for m in matched[:5])
            + ("\n  ..." if len(matched) > 5 else "")
            + "\nProvide a longer prefix or the full ID."
        )
    return matched[0]
