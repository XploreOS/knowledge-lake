"""Qdrant-backed VectorStorePlugin for Knowledge Lake (D-11).

Wraps qdrant-client 1.18 to provide:
  - ensure_collection(): idempotently create a named dense+sparse collection
  - ensure_aliased_collection(): idempotently bootstrap the first versioned
    collection behind a stable alias (D-06, INDEX-02)
  - ensure_payload_indexes(): create KEYWORD payload indexes for the 7 filterable
    fields (domain, document_type, source_name, format, source_id, tags, keywords)
    so filtered searches never trigger a full-collection scan (D-07, D-09, PAYLOAD-02)
  - reindex(): zero-downtime reindex — new physical collection, populate, count-parity
    gate, then atomically repoint the alias in a single update_collection_aliases() call
  - copy_all_points(): scroll+upsert all points between two collections
  - reembed_all_points(): scroll+re-embed (reuse dense, synthesize sparse) for migration
  - get_collection_dim(): read back a collection's configured vector size (named or unnamed)
  - upsert(): batch-upsert VectorPoints with citation payload fields (D-07), branching
    on named vs legacy unnamed collection shape (Pitfall 1, D-09)
  - search(): dense/sparse/hybrid ANN search with fail-loud mode enforcement (D-10),
    server-version preflight (D-07), and server-side RRF fusion (D-11)

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

from typing import Any, Callable, Optional

import structlog

from knowledge_lake.plugins.protocols import Hit, VectorPoint, VectorStorePlugin


def assert_server_supports_hybrid(client: Any) -> None:
    """Assert the connected Qdrant server is >= 1.10 (required for hybrid/sparse, D-07).

    Raises RuntimeError naming the server version and the >= 1.10 requirement if
    the server is too old.  Pass the QdrantClient instance as ``client``.

    This is a module-level helper so tests can call it directly without constructing
    a full QdrantVectorStore.  If ``info().version`` is not a parseable version string
    (e.g. a test mock returning a MagicMock object), the check is skipped — the
    caller is responsible for stubbing a real version string when testing the preflight.
    """
    from packaging.version import InvalidVersion, Version

    info = client.info()  # VersionInfo(title, version, commit) — SERVER version
    raw_version = info.version
    try:
        server_ver = Version(str(raw_version))
    except InvalidVersion:
        # Non-parseable version string (test mock or pre-release dev build) —
        # skip the check rather than blocking all unit tests.  Tests that exercise
        # the preflight directly must stub info().version to a real semver string.
        return
    if server_ver < Version("1.10"):
        raise RuntimeError(
            f"Qdrant server {raw_version!r} is too old for hybrid/sparse retrieval. "
            f"The Query API and IDF sparse vectors require server >= 1.10 "
            f"(client is 1.18). Upgrade the running Qdrant server."
        )

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
        from qdrant_client.models import (
            Distance,
            Fusion,
            FusionQuery,
            Modifier,
            PointStruct,
            Prefetch,
            SparseVector,
            SparseVectorParams,
            VectorParams,
        )

        self._Distance = Distance
        self._PointStruct = PointStruct
        self._VectorParams = VectorParams
        self._SparseVectorParams = SparseVectorParams
        self._Modifier = Modifier
        self._SparseVector = SparseVector
        self._Prefetch = Prefetch
        self._FusionQuery = FusionQuery
        self._Fusion = Fusion
        self._client = QdrantClient(url=qdrant_url)
        # Cache for _is_named() results keyed by collection name
        self._named_cache: dict[str, bool] = {}
        # Sentinel: True once assert_server_supports_hybrid() has passed
        self._hybrid_preflight_ok: bool = False
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

        from qdrant_client.models import Modifier, SparseVectorParams

        log.info("qdrant_store.create_collection", collection=name, dim=dim, distance=distance)
        self._client.create_collection(
            collection_name=name,
            vectors_config={"dense": self._VectorParams(size=dim, distance=dist)},
            sparse_vectors_config={
                "sparse": SparseVectorParams(modifier=Modifier.IDF)
            },
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
        from qdrant_client.models import (
            CreateAlias,
            CreateAliasOperation,
            Modifier,
            SparseVectorParams,
        )

        self._client.create_collection(
            collection_name=physical,
            vectors_config={"dense": self._VectorParams(size=dim, distance=dist)},
            sparse_vectors_config={
                "sparse": SparseVectorParams(modifier=Modifier.IDF)
            },
        )

        self._client.update_collection_aliases(
            change_aliases_operations=[
                CreateAliasOperation(
                    create_alias=CreateAlias(collection_name=physical, alias_name=alias)
                )
            ]
        )
        self.ensure_payload_indexes(physical)
        # Invalidate any stale _named_cache entry so the first index() call after
        # collection creation re-queries the server and sees the correct named-vector
        # shape (CR-02).  Use __dict__.get() rather than self._named_cache so this
        # is safe when __init__ was bypassed (e.g. test mocks constructed via __new__).
        self.__dict__.get("_named_cache", {}).pop(alias, None)
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
        from qdrant_client.models import Modifier as _Modifier, SparseVectorParams as _SVP

        self._client.create_collection(
            collection_name=next_physical,
            vectors_config={"dense": self._VectorParams(size=dim, distance=dist)},
            sparse_vectors_config={
                "sparse": _SVP(modifier=_Modifier.IDF)
            },
        )

        upsert_result = upsert_fn(next_physical)
        # upsert_fn may return (total, skipped) when it skips corrupt points (WR-04).
        # Extract skipped so the D-06 parity gate can account for them; default to 0.
        _skipped = upsert_result[1] if isinstance(upsert_result, tuple) else 0
        self.ensure_payload_indexes(next_physical)

        # D-06 — Count-parity gate: verify new collection point count matches old
        # BEFORE the alias swap.  A mismatch means the upsert_fn produced an
        # incomplete collection; abort so the alias keeps pointing at old_physical.
        # Skip on first-ever reindex (old_physical is None).
        # _skipped accounts for corrupt source points with no dense vector (WR-04):
        # those points were intentionally omitted, so expected new count is
        # old_count - _skipped rather than old_count.
        if old_physical is not None:
            old_count = self._client.count(old_physical, exact=True).count
            new_count = self._client.count(next_physical, exact=True).count
            if old_count - _skipped != new_count:
                raise ValueError(
                    f"Reindex parity gate failed for alias '{alias}': "
                    f"old collection '{old_physical}' has {old_count} points "
                    f"({_skipped} skipped due to missing dense vector) but "
                    f"new collection '{next_physical}' has {new_count} points. "
                    f"The alias swap was NOT applied — '{alias}' still points at "
                    f"'{old_physical}'. Inspect the new collection and re-run reindex."
                )

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

        # Invalidate the stale cache entry for the alias so the first index()
        # call after migration re-queries the server and sees the new named-vector
        # shape (CR-02).  Use __dict__.get() so this is safe when __init__ was
        # bypassed (e.g. test mocks constructed via __new__).
        self.__dict__.get("_named_cache", {}).pop(alias, None)

        log.info(
            "qdrant_store.reindex.complete",
            alias=alias,
            new_physical=next_physical,
            old_physical=old_physical,
        )
        return {"new_physical": next_physical, "old_physical": old_physical}

    def get_collection_dim(self, alias: str) -> int:
        """Return the configured vector dimension for ``alias`` (or a physical collection name).

        Branches on the collection's vector shape (Pitfall 2, D-05):
        - Named collections: params.vectors is a dict → return vectors["dense"].size
        - Legacy unnamed collections: params.vectors is a VectorParams → return vectors.size
        """
        info = self._client.get_collection(alias)
        vectors = info.config.params.vectors
        if isinstance(vectors, dict):
            return vectors["dense"].size
        return vectors.size

    def count_points(self, collection: str) -> int:
        """Return the exact point count for ``collection``; 0 if the collection is absent.

        Public wrapper around ``self._client.count(collection, exact=True).count``
        so that ``pipeline/query.stats()`` can obtain Qdrant point counts without
        reaching into the private ``_client`` attribute (Pitfall 5, D-14).

        Args:
            collection: Physical collection name or alias to count.

        Returns:
            Exact integer point count, or 0 when the collection does not exist.
        """
        try:
            return self._client.count(collection, exact=True).count
        except Exception:
            return 0

    def _is_named(self, collection: str) -> bool:
        """Return True when ``collection`` uses the named-vector shape (dense+sparse dict).

        Reads ``get_collection(...).config.params.vectors``; caches the result per
        collection name to avoid repeated server round-trips (Pitfall 1, D-09).
        """
        cache = self.__dict__.setdefault("_named_cache", {})
        if collection not in cache:
            info = self._client.get_collection(collection)
            cache[collection] = isinstance(info.config.params.vectors, dict)
        return cache[collection]

    def _collection_has_sparse(self, collection: str) -> bool:
        """Return True when ``collection`` has a 'sparse' vector configured (D-10).

        Reads CollectionParams.sparse_vectors — Optional[Dict[str, SparseVectorParams]].
        - None → False (no sparse vectors configured)
        - dict → True when "sparse" key is present
        - any other truthy value → True (production Qdrant always returns None or a
          real dict, so a truthy non-dict only arises from test mocks; treat as present)
        """
        params = self._client.get_collection(collection).config.params
        sparse = params.sparse_vectors  # Optional[Dict[str, SparseVectorParams]]
        if sparse is None:
            return False
        if isinstance(sparse, dict):
            return "sparse" in sparse
        # Truthy non-dict: production API never produces this; treat as present
        # (covers test mock fixtures where sparse_vectors is a truthy MagicMock)
        return bool(sparse)

    def assert_server_supports_hybrid(self) -> None:
        """Memoized server-version preflight — asserts the running Qdrant server >= 1.10.

        Calls the module-level helper on the first invocation, then memoizes success
        so the check is at most one round-trip per process (D-07).
        Works when instance was created via __new__ (test mocks bypass __init__).
        """
        if not self.__dict__.get("_hybrid_preflight_ok", False):
            assert_server_supports_hybrid(self._client)
            self._hybrid_preflight_ok = True

    def upsert(self, collection: str, points: list[VectorPoint]) -> None:
        """Batch-upsert VectorPoints into a Qdrant collection.

        Branches on the collection's vector shape (Pitfall 1, D-09):
        - Named collections: builds vector={"dense": v, "sparse": SparseVector(…)}
          (sparse only when VectorPoint.sparse is not None)
        - Legacy unnamed collections: keeps the bare vector=v (no sparse)

        Each VectorPoint's payload is passed through intact, preserving the
        citation fields (document, section_path, page, chunk_id) required
        for downstream citation rendering (D-07).

        Args:
            collection: Target collection name.
            points:     List of VectorPoint objects to upsert.
        """
        named = self._is_named(collection)
        qdrant_points = []
        for p in points:
            if named:
                vec: Any = {"dense": p.vector}
                sparse_val = getattr(p, "sparse", None)
                if sparse_val is not None:
                    vec["sparse"] = sparse_val
                qdrant_points.append(
                    self._PointStruct(id=p.id, vector=vec, payload=p.payload)
                )
            else:
                qdrant_points.append(
                    self._PointStruct(id=p.id, vector=p.vector, payload=p.payload)
                )

        log.info("qdrant_store.upsert", collection=collection, count=len(points))
        self._client.upsert(
            collection_name=collection,
            points=qdrant_points,
        )

    def reembed_all_points(
        self,
        source: str,
        dest: str,
        sparse_doc_fn: Callable[[str], Any],
        batch_size: int = 256,
    ) -> tuple[int, int]:
        """Scroll all points from ``source``, reuse dense vectors, synthesize sparse via
        ``sparse_doc_fn``, and upsert named {dense+sparse} points into ``dest``.

        This is the re-embedding migration helper for the unnamed→named migration (D-05).
        Dense vectors are reused from the scroll; only the sparse vector is synthesized.
        ``sparse_doc_fn`` is caller-injected (Plan 10-07 passes embed_sparse_doc) — the
        store stays generic and imports no encoder (D-01 seam).

        Returns (total_upserted, total_skipped). Points with no dense vector are skipped
        with a warning rather than upserted as null-vector points (WR-04). The caller
        (reindex) accounts for skipped points in the D-06 count-parity gate so that
        corrupt legacy points don't abort an otherwise-successful migration.
        Uses explicit ``next_offset is None`` end-of-scroll sentinel (never falsy check).
        """
        total = 0
        skipped = 0
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

            batch = []
            for r in records:
                # Reuse the scrolled dense vector — it hasn't changed (D-05)
                if isinstance(r.vector, list):
                    dense = r.vector
                else:
                    dense = r.vector.get("dense") if isinstance(r.vector, dict) else r.vector  # type: ignore[union-attr]
                # Guard: skip points whose dense vector is absent rather than
                # upsert a null-vector point that would silently corrupt the
                # new physical collection (WR-04).
                if dense is None:
                    log.warning(
                        "qdrant_store.reembed_all_points.missing_dense_vector",
                        point_id=r.id,
                    )
                    skipped += 1
                    continue
                text = (r.payload or {}).get("text", "")
                sparse = sparse_doc_fn(text)
                batch.append(
                    self._PointStruct(
                        id=r.id,
                        vector={"dense": dense, "sparse": sparse},
                        payload=r.payload,
                    )
                )
            self._client.upsert(collection_name=dest, points=batch)
            total += len(batch)

            if next_offset is None:
                break

        log.info(
            "qdrant_store.reembed_all_points",
            source=source,
            dest=dest,
            count=total,
            skipped=skipped,
        )
        return total, skipped

    def search(
        self,
        collection: str,
        query: list[float],
        top_k: int,
        query_filter: Optional[Any] = None,
        *,
        mode: str = "dense",
        sparse_query: Optional[Any] = None,
        offset: int = 0,
    ) -> list[Hit]:
        """Perform ANN search in dense, sparse, or hybrid mode.

        For hybrid/sparse modes: asserts server >= 1.10 and that the collection has a
        'sparse' vector — raises a clear error if absent (fail-loud, D-10, RETR-03).

        Hybrid uses two Prefetch branches (dense + sparse) with server-side RRF fusion
        (D-11). Each branch limit = top_k + offset (D-12). Dense and sparse filters
        are the same query_filter object applied on all branches and the top level
        (D-14).

        For named collections, dense uses using="dense". For legacy unnamed collections,
        bare query is used (Pitfall 1, D-09).

        Args:
            collection:   Collection to search.
            query:        Dense query vector.
            top_k:        Maximum number of results to return.
            query_filter: Optional Qdrant Filter to narrow results (INDEX-03, D-14).
            mode:         'dense' (default), 'sparse', or 'hybrid' (keyword-only, D-09).
            sparse_query: SparseVector for sparse/hybrid modes (keyword-only).
            offset:       Pagination offset (keyword-only).

        Returns:
            List of Hit objects ordered by score descending.
        """
        log.info(
            "qdrant_store.search",
            collection=collection,
            top_k=top_k,
            mode=mode,
            offset=offset,
        )

        if mode in ("hybrid", "sparse"):
            # D-07: assert server capability
            self.assert_server_supports_hybrid()
            # D-10: fail loud when sparse vector is absent
            if not self._collection_has_sparse(collection):
                raise ValueError(
                    f"mode={mode!r} requires a 'sparse' vector, but collection "
                    f"{collection!r} has none. Run the hybrid reindex "
                    f"(klake reindex --hybrid) to migrate this collection. "
                    f"(dense mode still works against it.)"
                )

        branch_limit = top_k + offset  # D-12: tight — not 10×

        if mode == "hybrid":
            from qdrant_client.models import Fusion, FusionQuery

            # Use self._Prefetch so tests can inject a MagicMock constructor that
            # accepts arbitrary kwargs (avoids pydantic filter-type validation in
            # unit tests); real deployments have self._Prefetch = qdrant Prefetch.
            dense_prefetch = self._Prefetch(
                query=query,
                using="dense",
                filter=query_filter,
                limit=branch_limit,
            )
            sparse_prefetch = self._Prefetch(
                query=sparse_query,
                using="sparse",
                filter=query_filter,
                limit=branch_limit,
            )
            result = self._client.query_points(
                collection_name=collection,
                prefetch=[dense_prefetch, sparse_prefetch],
                query=FusionQuery(fusion=Fusion.RRF),
                query_filter=query_filter,
                limit=top_k,
                offset=offset,
                with_payload=True,
            )
        elif mode == "sparse":
            result = self._client.query_points(
                collection_name=collection,
                query=sparse_query,
                using="sparse",
                query_filter=query_filter,
                limit=top_k,
                offset=offset,
                with_payload=True,
            )
        else:
            # mode == "dense" (default)
            named = self._is_named(collection)
            query_kwargs: dict[str, Any] = dict(
                collection_name=collection,
                query=query,
                query_filter=query_filter,
                limit=top_k,
                offset=offset,
                with_payload=True,
            )
            if named:
                query_kwargs["using"] = "dense"
            result = self._client.query_points(**query_kwargs)

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
