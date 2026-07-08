"""Qdrant-backed VectorStorePlugin for Knowledge Lake (D-11).

Wraps qdrant-client 1.18 to provide:
  - ensure_collection(): idempotently create a named collection with cosine distance
  - ensure_aliased_collection(): idempotently bootstrap the first versioned
    collection behind a stable alias (D-06, INDEX-02)
  - ensure_payload_indexes(): create KEYWORD payload indexes for the 7 filterable
    fields (domain, document_type, source_name, format, source_id, tags, keywords)
    so filtered searches never trigger a full-collection scan (D-07, D-09, PAYLOAD-02)
  - reindex(): zero-downtime reindex — new physical collection, populate, then
    atomically repoint the alias in a single update_collection_aliases() call
  - copy_all_points(): scroll+upsert all points between two collections
  - get_collection_dim(): read back a collection's configured vector size
  - upsert(): batch-upsert VectorPoints with citation payload fields (D-07)
  - search(): ANN search returning Hits with score and citation payload,
    optionally narrowed by a Qdrant Filter (query_filter, INDEX-03)

Citation payload fields preserved in each Qdrant point (D-07, D-14):
  document     — parsed document artifact ID this chunk came from
  section_path — section path string (e.g. '§3.2 Administrative Safeguards')
  page         — 1-indexed page number
  chunk_id     — chunk artifact ID (matches VectorPoint.id)

Registered as entry point:
    [project.entry-points."knowledge_lake.vectorstores"]
    qdrant = "knowledge_lake.plugins.builtin.qdrant_store:QdrantVectorStore"
"""
from __future__ import annotations

from typing import Any, Optional

import structlog

from knowledge_lake.plugins.protocols import Hit, VectorPoint, VectorStorePlugin

log = structlog.get_logger(__name__)


class QdrantVectorStore:
    """VectorStorePlugin implementation backed by qdrant-client 1.18.

    Connects to the Qdrant server at the URL injected via the constructor
    (from Settings.qdrant_url via the resolver — CR-03 fix). This ensures
    the URL is Pydantic-validated and test-overridable via the settings fixture.

    Usage:
        store = QdrantVectorStore(qdrant_url="http://localhost:6333")
        store.ensure_collection("klake_chunks", dim=384)
        store.upsert("klake_chunks", [VectorPoint(...)])
        hits = store.search("klake_chunks", query_vector, top_k=5)
    """

    def __init__(self, qdrant_url: str = "http://localhost:6333") -> None:
        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, PointStruct, VectorParams

        self._Distance = Distance
        self._PointStruct = PointStruct
        self._VectorParams = VectorParams
        self._client = QdrantClient(url=qdrant_url)
        log.debug("qdrant_store.connect", url=qdrant_url)

    def _distance_from_name(self, distance: str):
        """Resolve a distance-metric name string to the qdrant_client Distance enum.

        Shared by ensure_collection/ensure_aliased_collection/reindex so all
        collection-creation paths use the same Cosine/Euclid/Dot mapping.
        """
        Distance = self._Distance
        distance_map = {
            "Cosine": Distance.COSINE,
            "Euclid": Distance.EUCLID,
            "Dot": Distance.DOT,
        }
        return distance_map.get(distance, Distance.COSINE)

    def ensure_collection(
        self, name: str, dim: int, distance: str = "Cosine"
    ) -> None:
        """Create a Qdrant collection if it does not already exist (idempotent).

        Uses cosine distance by default — appropriate for sentence-transformer
        and LiteLLM embedding models (normalised vectors).

        Args:
            name:     Collection name.
            dim:      Vector dimension (must match the embedder's .dim).
            distance: Distance metric ('Cosine', 'Euclid', or 'Dot').
        """
        if self._client.collection_exists(name):
            log.debug("qdrant_store.collection_exists", collection=name)
            return

        dist = self._distance_from_name(distance)

        log.info("qdrant_store.create_collection", collection=name, dim=dim, distance=distance)
        self._client.create_collection(
            collection_name=name,
            vectors_config=self._VectorParams(size=dim, distance=dist),
        )
        self.ensure_payload_indexes(name)

    def ensure_aliased_collection(
        self, alias: str, dim: int, distance: str = "Cosine"
    ) -> tuple[str, bool]:
        """Idempotently bootstrap the first versioned collection behind ``alias`` (D-06).

        No-op (returns ``(alias, False)``) when the alias already resolves to a
        collection. Otherwise creates ``f"{alias}_v1"`` and points ``alias`` at it,
        returning ``(physical, True)``.
        """
        if self._client.collection_exists(alias):
            log.debug("qdrant_store.alias_exists", alias=alias)
            return (alias, False)

        physical = f"{alias}_v1"
        dist = self._distance_from_name(distance)

        log.info(
            "qdrant_store.ensure_aliased_collection.create",
            alias=alias,
            physical=physical,
            dim=dim,
            distance=distance,
        )
        self._client.create_collection(
            collection_name=physical,
            vectors_config=self._VectorParams(size=dim, distance=dist),
        )

        from qdrant_client.models import CreateAlias, CreateAliasOperation

        self._client.update_collection_aliases(
            change_aliases_operations=[
                CreateAliasOperation(
                    create_alias=CreateAlias(collection_name=physical, alias_name=alias)
                )
            ]
        )
        self.ensure_payload_indexes(physical)
        return (physical, True)

    def ensure_payload_indexes(self, collection: str) -> None:
        """Create KEYWORD payload indexes for all filterable metadata fields (D-07, D-09, PAYLOAD-02).

        Indexes the 7 fields that support filtered searches so Qdrant can use an
        index rather than a full-collection scan. Safe to call multiple times —
        Qdrant is idempotent on existing indexes.

        CRITICAL: always pass the physical collection name (e.g. "klake_chunks_v1"),
        never the alias (Pitfall 1 from RESEARCH.md).

        Args:
            collection: Physical collection name to index (never the alias).
        """
        from qdrant_client.models import PayloadSchemaType

        _KEYWORD_FIELDS = [
            "domain",
            "document_type",
            "source_name",
            "format",
            "source_id",
            "tags",
            "keywords",
        ]

        for field in _KEYWORD_FIELDS:
            self._client.create_payload_index(
                collection_name=collection,
                field_name=field,
                field_schema=PayloadSchemaType.KEYWORD,
            )

        log.info("qdrant_store.ensure_payload_indexes", collection=collection)

    def _next_version_name(self, alias: str) -> str:
        """Return the next ``f"{alias}_vN"`` name after the highest existing version."""
        collections = self._client.get_collections().collections
        prefix = f"{alias}_v"
        versions: list[int] = []
        for c in collections:
            if c.name.startswith(prefix):
                suffix = c.name[len(prefix):]
                if suffix.isdigit():
                    versions.append(int(suffix))
        next_version = (max(versions) + 1) if versions else 1
        return f"{prefix}{next_version}"

    def _resolve_alias_target(self, alias: str) -> Optional[str]:
        """Return the physical collection name ``alias`` currently resolves to, or None."""
        aliases = self._client.get_aliases().aliases
        for a in aliases:
            if a.alias_name == alias:
                return a.collection_name
        return None

    def copy_all_points(self, source: str, dest: str, batch_size: int = 256) -> int:
        """Scroll all points (vectors + payload) out of ``source`` and upsert into ``dest``.

        Returns the total count copied (0 for an empty source collection).
        """
        total = 0
        next_offset: Any = None
        while True:
            records, next_offset = self._client.scroll(
                collection_name=source,
                limit=batch_size,
                offset=next_offset,
                with_vectors=True,
                with_payload=True,
            )
            if not records:
                break

            batch = [
                self._PointStruct(id=r.id, vector=r.vector, payload=r.payload)
                for r in records
            ]
            self._client.upsert(collection_name=dest, points=batch)
            total += len(batch)

            # Break only when Qdrant returns None as the explicit end-of-scroll
            # sentinel.  Do NOT use a falsy check (`if not next_offset`) — integer
            # 0 is a valid offset for integer-ID collections and would cause the
            # loop to terminate after the first batch.  IDs are currently UUIDs
            # (strings) so 0 cannot appear, but explicit None comparison future-
            # proofs the loop against an ID-type change.
            if next_offset is None:
                break

        log.info("qdrant_store.copy_all_points", source=source, dest=dest, count=total)
        return total

    def reindex(
        self,
        alias: str,
        dim: int,
        upsert_fn: Any,
        distance: str = "Cosine",
    ) -> dict:
        """Zero-downtime reindex: build the next versioned collection, populate it via
        ``upsert_fn``, then atomically repoint ``alias`` at it in one call (D-06, INDEX-02).
        """
        old_physical = self._resolve_alias_target(alias)
        next_physical = self._next_version_name(alias)
        dist = self._distance_from_name(distance)

        log.info(
            "qdrant_store.reindex.create",
            alias=alias,
            old_physical=old_physical,
            next_physical=next_physical,
        )
        self._client.create_collection(
            collection_name=next_physical,
            vectors_config=self._VectorParams(size=dim, distance=dist),
        )

        upsert_fn(next_physical)
        self.ensure_payload_indexes(next_physical)

        from qdrant_client.models import (
            CreateAlias,
            CreateAliasOperation,
            DeleteAlias,
            DeleteAliasOperation,
        )

        change_aliases_operations: list[Any] = []
        if old_physical is not None:
            change_aliases_operations.append(
                DeleteAliasOperation(delete_alias=DeleteAlias(alias_name=alias))
            )
        change_aliases_operations.append(
            CreateAliasOperation(
                create_alias=CreateAlias(collection_name=next_physical, alias_name=alias)
            )
        )

        self._client.update_collection_aliases(
            change_aliases_operations=change_aliases_operations
        )

        log.info(
            "qdrant_store.reindex.complete",
            alias=alias,
            new_physical=next_physical,
            old_physical=old_physical,
        )
        return {"new_physical": next_physical, "old_physical": old_physical}

    def get_collection_dim(self, alias: str) -> int:
        """Return the configured vector dimension for ``alias`` (or a physical collection name)."""
        info = self._client.get_collection(alias)
        return info.config.params.vectors.size

    def upsert(self, collection: str, points: list[VectorPoint]) -> None:
        """Batch-upsert VectorPoints into a Qdrant collection.

        Each VectorPoint's payload is passed through intact, preserving the
        citation fields (document, section_path, page, chunk_id) required
        for downstream citation rendering (D-07).

        Args:
            collection: Target collection name.
            points:     List of VectorPoint objects to upsert.
        """
        qdrant_points = [
            self._PointStruct(
                id=p.id,
                vector=p.vector,
                payload=p.payload,
            )
            for p in points
        ]

        log.info("qdrant_store.upsert", collection=collection, count=len(points))
        self._client.upsert(
            collection_name=collection,
            points=qdrant_points,
        )

    def search(
        self,
        collection: str,
        query: list[float],
        top_k: int,
        query_filter: Optional[Any] = None,
    ) -> list[Hit]:
        """Perform approximate nearest-neighbour search.

        Uses the Qdrant query_points API (qdrant-client 1.18 preferred method).
        Returns a list of Hit objects ordered by score descending, carrying the
        citation payload from the matched VectorPoint.

        Args:
            collection:   Collection to search.
            query:        Query vector (must have the same dimension as the collection).
            top_k:        Maximum number of results to return.
            query_filter: Optional Qdrant Filter to narrow results (INDEX-03).

        Returns:
            List of Hit objects ordered by score descending.
        """
        log.info("qdrant_store.search", collection=collection, top_k=top_k)

        result = self._client.query_points(
            collection_name=collection,
            query=query,
            limit=top_k,
            query_filter=query_filter,
        )

        hits: list[Hit] = [
            Hit(
                id=str(scored.id),
                score=float(scored.score),
                payload=dict(scored.payload or {}),
            )
            for scored in result.points
        ]

        log.debug("qdrant_store.search_complete", hits=len(hits))
        return hits
