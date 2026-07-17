"""Unit tests for QdrantVectorStore.set_payload (D-24, D-25, D-26, DEDUP-03).

Covers 21-03-PLAN.md acceptance criteria:
- set_payload() returns True on a successful merge against an existing point
- set_payload() returns False (never raises) when the underlying client raises
  UnexpectedResponse(status_code=404) for a missing point ID
- set_payload() re-raises UnexpectedResponse for any non-404 status code (a
  genuine server error must never be swallowed as a "point missing" False)

Fixture pattern mirrors tests/unit/test_qdrant_payload_indexes.py's mock_store
fixture: uses QdrantVectorStore.__new__ to bypass __init__ and assigns a
MagicMock() to store._client so no real Qdrant server connection is made.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from qdrant_client.http.exceptions import UnexpectedResponse

from knowledge_lake.plugins.builtin.qdrant_store import QdrantVectorStore


# ── Shared fixture ──────────────────────────────────────────────────────────────


@pytest.fixture()
def mock_store():
    """Return a QdrantVectorStore with a fully-mocked _client (no real connection).

    Uses __new__ to bypass __init__ so no QdrantClient() is ever constructed.
    """
    store = QdrantVectorStore.__new__(QdrantVectorStore)
    store._client = MagicMock()
    return store


# ── TestSetPayload ───────────────────────────────────────────────────────────────


class TestSetPayload:
    def test_set_payload_success_returns_true(self, mock_store) -> None:
        """A successful merge against an existing point returns True and calls
        the underlying client's set_payload exactly once with the expected args.
        """
        mock_store._client.set_payload.return_value = None

        result = mock_store.set_payload(
            "klake_chunks_v1", "abc-123", {"contributors": []}
        )

        assert result is True
        mock_store._client.set_payload.assert_called_once_with(
            collection_name="klake_chunks_v1",
            payload={"contributors": []},
            points=["abc-123"],
        )

    def test_set_payload_missing_point_returns_false(self, mock_store) -> None:
        """A missing point ID (UnexpectedResponse 404) returns False and does
        not propagate the exception.
        """
        mock_store._client.set_payload.side_effect = UnexpectedResponse(
            status_code=404,
            reason_phrase="Not Found",
            content=b"{}",
            headers={},
        )

        result = mock_store.set_payload(
            "klake_chunks_v1", "missing-id", {"contributors": []}
        )

        assert result is False

    def test_set_payload_non_404_error_propagates(self, mock_store) -> None:
        """A genuine server error (non-404 UnexpectedResponse) must never be
        silently swallowed as a "point missing" False — it must re-raise.
        """
        mock_store._client.set_payload.side_effect = UnexpectedResponse(
            status_code=500,
            reason_phrase="Internal Server Error",
            content=b"{}",
            headers={},
        )

        with pytest.raises(UnexpectedResponse):
            mock_store.set_payload(
                "klake_chunks_v1", "some-id", {"contributors": []}
            )
