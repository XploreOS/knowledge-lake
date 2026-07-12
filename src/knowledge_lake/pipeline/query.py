"""Pipeline service functions: list_sources + stats (D-05, MCP-01).

Read-only aggregate functions extracted from inline API/CLI logic so CLI, API,
and MCP tool handlers are thin callers over these shared implementations (D-03).

Session-safe contract: every ORM row is materialized to a plain dict *inside*
the ``with get_session()`` block before returning (DetachedInstanceError guard,
PAYLOAD-01, mirrors ``pipeline/crawl.py:237-241``).
"""
from __future__ import annotations


def list_sources(
    domain: str | None = None,
    *,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """Return a page of registered sources as plain dicts.

    When ``domain`` is supplied, the Python-side filter is applied first so
    that ``limit``/``offset`` operate on the filtered set (WR-01 pagination
    correctness, mirrors ``api/app.py:1261-1273``).

    Args:
        domain: Optional domain classification to filter by (e.g. 'healthcare').
        limit:  Maximum results per page (default 50).
        offset: Zero-based pagination offset (default 0).

    Returns:
        A list of plain dicts — each with keys::

            source_id, name, url, source_type, license_type, domain, created_at

        All values are JSON-serialisable (str or None).  ``created_at`` is an
        ISO-8601 UTC string.

    Security (T-06-11 / ASVS V5):
        - All queries use ORM ``select()`` — no raw SQL.
        - ``domain``/``limit``/``offset`` are validated by callers (Pydantic in
          the REST layer, query-param defaults here); this function trusts them.
    """
    from sqlalchemy import select

    from knowledge_lake.registry.db import get_session
    from knowledge_lake.registry.models import Source

    with get_session() as session:
        if domain is not None:
            # Fetch all rows matching the query and filter in Python so
            # LIMIT/OFFSET apply to the filtered result set (WR-01).
            all_sources = list(
                session.execute(
                    select(Source).order_by(Source.created_at.desc())
                ).scalars()
            )
            rows = [
                s for s in all_sources
                if (s.config or {}).get("domain") == domain
            ][offset: offset + limit]
        else:
            stmt = (
                select(Source)
                .order_by(Source.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
            rows = list(session.execute(stmt).scalars())

        # Materialize inside the session — DetachedInstanceError guard (PAYLOAD-01).
        return [
            {
                "source_id": s.id,
                "name": s.name,
                "url": s.url,
                "source_type": s.source_type,
                "license_type": s.license_type,
                "domain": (s.config or {}).get("domain"),
                "created_at": s.created_at.isoformat() if s.created_at else "",
            }
            for s in rows
        ]


def stats(
    *,
    collection: str = "klake_chunks",
    domain: str | None = None,
) -> dict:
    """Return an aggregate summary of the knowledge lake state.

    Counts registry rows and Qdrant points.  When ``domain`` is supplied,
    source and artifact counts are scoped to that domain (Python-side filter
    on ``Source.config["domain"]``).

    ``stats()`` never reaches into ``QdrantVectorStore._client`` directly.
    Point counts are obtained via the public ``count_points()`` wrapper
    (Pitfall 5, added in ``plugins/builtin/qdrant_store.py``).

    Args:
        collection: Qdrant collection name to count points in (default
                    ``klake_chunks``).
        domain:     Optional domain to scope source/artifact counts.

    Returns:
        A dict::

            {
                "sources":          <int>,
                "documents":        <int>,   # raw_document artifact count
                "artifacts_by_type": {
                    "raw_document":      <int>,
                    "parsed_document":   <int>,
                    "chunk":             <int>,
                    # ... any other artifact_type values present
                },
                "qdrant_points":    <int>,
                "collection":       <str>,
            }
    """
    from sqlalchemy import func, select

    from knowledge_lake.config.settings import get_settings
    from knowledge_lake.plugins.resolver import get_vectorstore
    from knowledge_lake.registry.db import get_session
    from knowledge_lake.registry.models import Artifact, Source

    with get_session() as session:
        # Source count (optionally scoped by domain)
        all_sources = list(session.execute(select(Source)).scalars())
        if domain is not None:
            sources_list = [
                s for s in all_sources
                if (s.config or {}).get("domain") == domain
            ]
            source_ids = {s.id for s in sources_list}
            sources_count = len(sources_list)
        else:
            sources_count = len(all_sources)
            source_ids = None

        # Artifact counts grouped by artifact_type
        artifact_rows = session.execute(
            select(Artifact.artifact_type, func.count(Artifact.id).label("cnt"))
            .group_by(Artifact.artifact_type)
        ).all()

        if source_ids is not None:
            # Domain-scoped: count only artifacts belonging to scoped sources
            artifact_rows_all = session.execute(
                select(Artifact.artifact_type, Artifact.source_id)
            ).all()
            from collections import Counter
            scoped_counter: Counter[str] = Counter()
            for art_type, src_id in artifact_rows_all:
                if src_id in source_ids:
                    scoped_counter[art_type] += 1
            artifacts_by_type = dict(scoped_counter)
        else:
            artifacts_by_type = {row.artifact_type: row.cnt for row in artifact_rows}

    documents_count = artifacts_by_type.get("raw_document", 0)

    # Qdrant point count via public API — must NOT reach into _client (Pitfall 5)
    settings = get_settings()
    vectorstore = get_vectorstore(settings)
    qdrant_points = vectorstore.count_points(collection)

    return {
        "sources": sources_count,
        "documents": documents_count,
        "artifacts_by_type": artifacts_by_type,
        "qdrant_points": qdrant_points,
        "collection": collection,
    }
