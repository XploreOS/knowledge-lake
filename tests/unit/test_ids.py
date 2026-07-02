"""
Unit tests for knowledge_lake.ids — prefixed UUIDv7 ID generation (D-15, FOUND-05).

TDD: These tests define the expected behavior of new_id(kind).
"""

from __future__ import annotations

import re
import time

import pytest


UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
"""Regex for a canonical UUIDv7 string (version nibble == 7)."""


class TestNewIdPrefixes:
    """new_id returns correctly prefixed IDs for each supported kind."""

    def test_source_prefix(self) -> None:
        from knowledge_lake.ids import new_id

        id_ = new_id("source")
        assert id_.startswith("src_"), f"Expected src_ prefix, got: {id_}"

    def test_raw_document_prefix(self) -> None:
        from knowledge_lake.ids import new_id

        id_ = new_id("raw_document")
        assert id_.startswith("doc_"), f"Expected doc_ prefix, got: {id_}"

    def test_parsed_document_prefix(self) -> None:
        from knowledge_lake.ids import new_id

        id_ = new_id("parsed_document")
        assert id_.startswith("doc_"), f"Expected doc_ prefix, got: {id_}"

    def test_chunk_prefix(self) -> None:
        from knowledge_lake.ids import new_id

        id_ = new_id("chunk")
        assert id_.startswith("chk_"), f"Expected chk_ prefix, got: {id_}"

    def test_artifact_prefix(self) -> None:
        from knowledge_lake.ids import new_id

        id_ = new_id("artifact")
        assert id_.startswith("art_"), f"Expected art_ prefix, got: {id_}"


class TestNewIdUUIDv7Structure:
    """The UUID portion of new_id output is a valid UUIDv7."""

    def test_source_uuid_is_v7(self) -> None:
        from knowledge_lake.ids import new_id

        id_ = new_id("source")
        uuid_part = id_[len("src_"):]
        assert UUID_PATTERN.match(uuid_part), (
            f"UUID portion '{uuid_part}' is not a valid UUIDv7"
        )

    def test_chunk_uuid_is_v7(self) -> None:
        from knowledge_lake.ids import new_id

        id_ = new_id("chunk")
        uuid_part = id_[len("chk_"):]
        assert UUID_PATTERN.match(uuid_part), (
            f"UUID portion '{uuid_part}' is not a valid UUIDv7"
        )


class TestNewIdTimeSortable:
    """Two IDs generated in sequence sort in creation order (UUIDv7 time-ordering)."""

    def test_sequential_ids_are_time_sorted(self) -> None:
        from knowledge_lake.ids import new_id

        ids = []
        for _ in range(5):
            ids.append(new_id("source"))
            # Small sleep ensures timestamp granularity (milliseconds)
            time.sleep(0.002)

        uuid_parts = [id_[len("src_"):] for id_ in ids]
        assert uuid_parts == sorted(uuid_parts), (
            f"IDs are not time-sorted: {uuid_parts}"
        )

    def test_chunk_ids_are_time_sorted(self) -> None:
        from knowledge_lake.ids import new_id

        ids = []
        for _ in range(3):
            ids.append(new_id("chunk"))
            time.sleep(0.002)

        uuid_parts = [id_[len("chk_"):] for id_ in ids]
        assert uuid_parts == sorted(uuid_parts)


class TestNewIdUnknownKind:
    """new_id raises a clear error for unknown kinds."""

    def test_unknown_kind_raises_value_error(self) -> None:
        from knowledge_lake.ids import new_id

        with pytest.raises((KeyError, ValueError)):
            new_id("unknown_kind")

    def test_empty_kind_raises_error(self) -> None:
        from knowledge_lake.ids import new_id

        with pytest.raises((KeyError, ValueError)):
            new_id("")


class TestNewIdUniqueness:
    """Each call produces a unique ID."""

    def test_ids_are_unique(self) -> None:
        from knowledge_lake.ids import new_id

        generated = [new_id("source") for _ in range(20)]
        assert len(set(generated)) == 20, "Expected all IDs to be unique"
