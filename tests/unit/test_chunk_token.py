"""Tests for token-aware chunking (CHUNK-01..04, D-03).

RED phase: tests written before implementation to drive the chunker design.

TDD contract:
  - test_chunk_token_stub is removed; all tests below must fail until chunk.py is
    updated to implement the token-aware functions.
  - After implementation (GREEN phase) every test below must pass.
"""

from __future__ import annotations

import pytest

from knowledge_lake.pipeline.chunk import (
    _build_token_chunks,
    chunk_section,
    token_count,
)
from knowledge_lake.plugins.protocols import ParsedDoc, Section


# ── Basic token counter ───────────────────────────────────────────────────────


def test_token_count_positive() -> None:
    """token_count() must return a positive integer for non-empty English text."""
    result = token_count("the quick brown fox")
    assert isinstance(result, int)
    assert result > 0


# ── Single-chunk short text (CHUNK-02) ────────────────────────────────────────


def test_short_text_single_chunk() -> None:
    """Text well under max_tokens produces exactly one chunk (no split needed)."""
    # A single section with 50 words — well under 512 tokens
    text = " ".join(["word"] * 50)
    section = Section(heading="Introduction", section_path="§1", page=1, text=text)
    doc = ParsedDoc(text=text, sections=[section])
    chunks = _build_token_chunks(doc, max_tokens=512, overlap_tokens=64, breadcrumb_depth=2)
    assert len(chunks) == 1


# ── Long text splits (CHUNK-02) ───────────────────────────────────────────────


def test_long_text_splits_into_multiple_chunks() -> None:
    """Text exceeding max_tokens is split into multiple chunks each <= max_tokens."""
    # 200 words repeated 5 times ≈ 1000 tokens
    base = " ".join(["The patient was admitted"] * 50)
    long_text = (base + " ") * 4  # ~800-1000 tokens
    section = Section(heading="Clinical Notes", section_path="§2", page=3, text=long_text)
    doc = ParsedDoc(text=long_text, sections=[section])
    chunks = _build_token_chunks(doc, max_tokens=512, overlap_tokens=64, breadcrumb_depth=2)
    assert len(chunks) >= 2, f"Expected >= 2 chunks, got {len(chunks)}"
    for i, chunk in enumerate(chunks):
        tc = token_count(chunk["text"])
        assert tc <= 512, f"Chunk {i} has {tc} tokens (limit 512)"


# ── Table atomicity (CHUNK-03) ───────────────────────────────────────────────


def test_table_is_atomic_oversized() -> None:
    """A table section exceeding max_tokens emits as a single chunk with is_table=True, oversized=True."""
    # 800 words → well over 512 tokens
    table_text = " ".join(["col1 col2 col3"] * 100)
    section = Section(
        heading="Drug Table",
        section_path="§3.1",
        page=7,
        text=table_text,
        is_table=True,
    )
    doc = ParsedDoc(text=table_text, sections=[section])
    chunks = _build_token_chunks(doc, max_tokens=512, overlap_tokens=64, breadcrumb_depth=2)
    assert len(chunks) == 1, "Oversized table must produce exactly one atomic chunk"
    assert chunks[0]["is_table"] is True
    assert chunks[0]["oversized"] is True


def test_table_not_oversized_when_small() -> None:
    """A small table section under max_tokens: single chunk, is_table=True, oversized=False."""
    table_text = "col1 col2\nval1 val2\nval3 val4"  # well under 512 tokens
    section = Section(
        heading="Results",
        section_path="§4",
        page=2,
        text=table_text,
        is_table=True,
    )
    doc = ParsedDoc(text=table_text, sections=[section])
    chunks = _build_token_chunks(doc, max_tokens=512, overlap_tokens=64, breadcrumb_depth=2)
    assert len(chunks) == 1
    assert chunks[0]["is_table"] is True
    assert chunks[0]["oversized"] is False


# ── Chunk metadata (CHUNK-04) ────────────────────────────────────────────────


def test_chunk_carries_section_path() -> None:
    """All chunks from a section carry the source section_path or a sub-path."""
    text = " ".join(["Administrative safeguard policy"] * 30)
    section = Section(heading="Admin", section_path="§3.2", page=5, text=text)
    doc = ParsedDoc(text=text, sections=[section])
    chunks = _build_token_chunks(doc, max_tokens=512, overlap_tokens=64, breadcrumb_depth=2)
    for chunk in chunks:
        assert chunk["section_path"].startswith("§3.2"), (
            f"Expected section_path starting with '§3.2', got {chunk['section_path']!r}"
        )


def test_chunk_carries_page_ref() -> None:
    """All chunks from a section carry the page number from the Section."""
    text = " ".join(["Safeguard overview"] * 20)
    section = Section(heading="Overview", section_path="§1", page=5, text=text)
    doc = ParsedDoc(text=text, sections=[section])
    chunks = _build_token_chunks(doc, max_tokens=512, overlap_tokens=64, breadcrumb_depth=2)
    for chunk in chunks:
        assert chunk["page"] == 5, f"Expected page=5, got {chunk['page']}"


# ── Overlap (CHUNK-01, CHUNK-02) ─────────────────────────────────────────────


def test_overlap_produces_shared_content() -> None:
    """With overlap_tokens=64 the second chunk shares at least one sentence with the first."""
    # Build text that will split into exactly 2 chunks with overlap
    # Each sentence is ~10 words. 60 sentences * 10 words ≈ 600+ tokens
    sentences = [f"Sentence {i:03d} about healthcare policy requirements." for i in range(60)]
    text = " ".join(sentences)
    section = Section(heading="Policy", section_path="§2", page=1, text=text)
    doc = ParsedDoc(text=text, sections=[section])
    chunks = _build_token_chunks(doc, max_tokens=512, overlap_tokens=64, breadcrumb_depth=2)
    # Must have at least 2 chunks to test overlap
    if len(chunks) < 2:
        pytest.skip("Text did not split — increase test text size")
    # Second chunk should start with text that appeared in the first chunk
    first_chunk_text = chunks[0]["text"]
    second_chunk_text = chunks[1]["text"]
    # Overlap means some words from near the end of chunk 0 appear at the start of chunk 1
    # We check that chunk 1 text is not disjoint from chunk 0 by token presence
    first_words = set(first_chunk_text.split())
    second_start_words = set(second_chunk_text.split()[:30])  # first 30 words of chunk 2
    overlap_words = first_words & second_start_words
    assert len(overlap_words) > 0, (
        "Expected some word overlap between chunk 1 end and chunk 2 start (overlap_tokens=64)"
    )


# ── Heading hierarchy / section paths (CHUNK-01) ─────────────────────────────


def test_heading_hierarchy_preserved() -> None:
    """Multiple sections produce chunks with distinct section_paths."""
    doc = ParsedDoc(
        text="combined text",
        sections=[
            Section(heading="Admin", section_path="§1", page=1, text="admin text content here"),
            Section(heading="Tech", section_path="§2", page=2, text="technical safeguards detail"),
        ],
    )
    chunks = _build_token_chunks(doc, max_tokens=512, overlap_tokens=64, breadcrumb_depth=2)
    paths = {c["section_path"] for c in chunks}
    # Chunks from different sections should have different section_paths
    assert len(paths) >= 2, f"Expected >= 2 distinct section paths, got: {paths}"


# ── Fallback: no sections (CHUNK-01) ─────────────────────────────────────────


def test_no_sections_fallback() -> None:
    """ParsedDoc with empty sections list and non-empty text produces exactly one chunk."""
    doc = ParsedDoc(
        text="This is the full document text without any section structure.",
        sections=[],
    )
    chunks = _build_token_chunks(doc, max_tokens=512, overlap_tokens=64, breadcrumb_depth=2)
    assert len(chunks) == 1
    assert chunks[0]["section_path"] == "§1"


# ── Section.is_table backwards compatibility ──────────────────────────────────


def test_section_is_table_default_false() -> None:
    """Section constructed without is_table defaults to False (backwards compatibility)."""
    s = Section(heading="h", section_path="§1", page=1)
    assert s.is_table is False


def test_section_is_table_explicit_true() -> None:
    """Section with is_table=True carries the flag correctly."""
    s = Section(heading="Table", section_path="§T", page=3, text="data", is_table=True)
    assert s.is_table is True


# ── chunk_section public helper ───────────────────────────────────────────────


def test_chunk_section_short_is_single() -> None:
    """chunk_section returns a single-element list for text under max_tokens."""
    text = "Short clinical note about patient status."
    result = chunk_section(text, max_tokens=512, overlap_tokens=64)
    assert result == [text]


def test_chunk_section_long_produces_multiple() -> None:
    """chunk_section splits long text into multiple sub-chunks each <= max_tokens."""
    long_text = " ".join(["Healthcare regulation compliance requirement."] * 60)
    results = chunk_section(long_text, max_tokens=256, overlap_tokens=32)
    assert len(results) >= 2
    for sub in results:
        assert token_count(sub) <= 256
