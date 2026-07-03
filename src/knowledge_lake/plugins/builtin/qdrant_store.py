"""Qdrant-backed VectorStorePlugin for Knowledge Lake (D-11).

Wraps qdrant-client 1.18 to provide:
  - ensure_collection(): idempotently create a named collection with cosine distance
  - upsert(): batch-upsert VectorPoints with citation payload fields (D-07)
  - search(): ANN search returning Hits with score and citation payload

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

        Distance = self._Distance
        distance_map = {
            "Cosine": Distance.COSINE,
            "Euclid": Distance.EUCLID,
            "Dot": Distance.DOT,
        }
        dist = distance_map.get(distance, Distance.COSINE)

        log.info("qdrant_store.create_collection", collection=name, dim=dim, distance=distance)
        self._client.create_collection(
            collection_name=name,
            vectors_config=self._VectorParams(size=dim, distance=dist),
        )

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
        self, collection: str, query: list[float], top_k: int
    ) -> list[Hit]:
        """Perform approximate nearest-neighbour search.

        Uses the Qdrant query_points API (qdrant-client 1.18 preferred method).
        Returns a list of Hit objects ordered by score descending, carrying the
        citation payload from the matched VectorPoint.

        Args:
            collection: Collection to search.
            query:      Query vector (must have the same dimension as the collection).
            top_k:      Maximum number of results to return.

        Returns:
            List of Hit objects ordered by score descending.
        """
        log.info("qdrant_store.search", collection=collection, top_k=top_k)

        result = self._client.query_points(
            collection_name=collection,
            query=query,
            limit=top_k,
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
