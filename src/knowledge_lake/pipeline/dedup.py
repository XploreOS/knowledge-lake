"""Index-time EXACT dedup (DEDUP-01/02/03).

This module defines the exact-dedup key derivation and deterministic point-ID
scheme used at index time to collapse identical chunk text into a single
Qdrant point while preserving full per-document contributor lineage (WR-05).

This is deliberately NOT a near-duplicate/MinHash module. Corpus-wide
near-dup detection already exists in ``pipeline/curate.py``'s pretrain path
(CLEAN-03, via ``compute_minhash`` in ``pipeline/clean.py``) and is a wholly
separate concern from this phase's exact-dedup key. Do not conflate this
module's tests (``tests/unit/test_index_dedup.py``) with
``tests/unit/test_dedup.py``, which already covers MinHash/
``remove_boilerplate`` and is unrelated to this phase.

This module's pure-function section (this file, as of Plan 21-02) has zero
dependencies on I/O, S3, Dagster, DB, or ``knowledge_lake.config.settings`` —
independently importable and testable with no infrastructure, mirroring
Phase 19's ``pipeline/quality/`` zero-I/O convention. Plan 21-04 (Wave 2)
adds the ledger-consuming ``dedup_chunks()`` router to this same file; that
router is permitted to import settings/DB, but the functions below must not.
"""

from __future__ import annotations

import datetime
import hashlib
import unicodedata
import uuid

import structlog

from knowledge_lake.config.settings import Settings, get_settings
from knowledge_lake.registry import repo as registry_repo
from knowledge_lake.registry.db import get_session

log = structlog.get_logger(__name__)

# Frozen namespace for uuid5 point-ID derivation (D-05). NEVER derive this
# from settings, an env var, or the collection name — changing it would
# silently orphan every previously-indexed point (a different namespace
# produces entirely different uuid5 outputs for the same text_sha256 input).
KLAKE_DEDUP_NAMESPACE = uuid.UUID("94eca03b-54f1-4438-a007-2f835b9d2c07")


def normalize_for_dedup(text: str) -> str:
    """Normalize chunk text into the exact-dedup key (D-01/D-02/D-03).

    Applies exactly three transformations, in order:
      1. Unicode NFKC normalization.
      2. Whitespace-run collapse (including newlines/tabs) to a single space.
      3. Strip leading/trailing whitespace.

    Deliberately does NOT casefold, strip punctuation, or remove stopwords
    (D-02) — this is EXACT dedup, not near-dup, so "WBC" and "wbc" must
    remain distinct.

    Deliberately does NOT reuse ``clean.py``'s ``_normalize_whitespace()``
    (D-03): that function is line-oriented (preserves single newlines,
    collapses 3+ blank lines to 2) and serves cleaned-text READABILITY, not
    exact-dedup-key equality. Coupling the two would let a future cosmetic
    cleaning tweak silently repartition the dedup space and desync ledger
    rows from what ``chunk()`` actually persisted.

    Empty and whitespace-only input normalize to the empty string without
    raising.
    """
    normalized = unicodedata.normalize("NFKC", text)
    collapsed = " ".join(normalized.split())
    return collapsed.strip()


def text_sha256_for(text: str) -> str:
    """Return the SHA-256 hex digest of the normalized dedup key (D-04).

    Computed from the chunk's text field only — never section_path/page/any
    per-document field, since those would defeat cross-document dedup.
    Equivalent to
    ``hashlib.sha256(normalize_for_dedup(text).encode("utf-8")).hexdigest()``.
    """
    return hashlib.sha256(normalize_for_dedup(text).encode("utf-8")).hexdigest()


def point_id_for_text(text: str) -> str:
    """Return a deterministic Qdrant point ID for the given text (D-06).

    The uuid5 name input is the 64-char hex digest STRING returned by
    ``text_sha256_for()``, matching DEDUP-02's literal formulation. Returns
    the bare-UUID string form Qdrant's point-ID validation requires — no
    ``_strip_prefix()``-style transformation needed.
    """
    return str(uuid.uuid5(KLAKE_DEDUP_NAMESPACE, text_sha256_for(text)))


def _assert_dedup_conservation_invariant(
    *,
    new_count: int,
    duplicate_count: int,
    total: int,
    parsed_artifact_id: str,
) -> None:
    """DEDUP-01 conservation invariant: new + duplicates == total.

    Mirrors chunk.py's ``_assert_chunk_conservation_invariant`` log-then-raise
    shape exactly — never a bare assert. Asserted unconditionally at the end
    of every ``dedup_chunks()`` call (T-21-08 mitigation): a partial
    ledger-claim failure must never silently vanish a chunk from both
    buckets.
    """
    if new_count + duplicate_count != total:
        log.error(
            "dedup.conservation_invariant_violated",
            parsed_artifact_id=parsed_artifact_id,
            total=total,
            new=new_count,
            duplicates=duplicate_count,
        )
        raise RuntimeError(
            f"dedup_chunks: conservation invariant violated for "
            f"{parsed_artifact_id!r}: {new_count} + {duplicate_count} != {total}"
        )


def dedup_chunks(
    chunks: list[dict],
    parsed_artifact_id: str,
    source_id: str,
    *,
    collection: str,
    settings: Settings | None = None,
) -> dict:
    """Partition chunks into first-seen (``new``) and already-seen
    (``duplicates``) via an atomic, corpus-wide ledger claim (DEDUP-01/02).

    Every chunk dict is annotated IN PLACE with ``text_sha256``/``point_id``
    keys regardless of which bucket it lands in. ``parsed_artifact_id`` and
    ``source_id`` describe the CURRENT document being processed (shared by
    every chunk in this call) — matching ``chunk()``/``embed()``/``index()``'s
    own positional-parameter convention, extended here since the ledger's
    ``primary_parsed_artifact_id``/``primary_source_id`` columns need a value
    to write on a first claim.

    Returns ``{"new": [...], "duplicates": [...], "stats": {...}}``, where
    ``stats`` carries ``total``/``unique``/``duplicates``/``collection``/
    ``embed_calls_saved`` for structured logging and caller-side metrics.

    By construction, this function's ledger-claim session commits (auto-
    commit on ``get_session()``'s clean exit) before this function returns —
    the caller's subsequent ``embed()``/``index()`` calls always see
    already-durable ledger state (D-14 ORDERING INVARIANT), since no Qdrant
    write ever happens inside ``dedup_chunks()`` itself.
    """
    if not chunks:
        return {
            "new": [],
            "duplicates": [],
            "stats": {
                "total": 0,
                "unique": 0,
                "duplicates": 0,
                "collection": collection,
                "embed_calls_saved": 0,
            },
        }

    _ = settings or get_settings()  # resolves settings for parity with embed()'s
    # idiom; not yet consumed inside this function (no settings-driven
    # branching in this plan's scope)
    now = datetime.datetime.now(datetime.UTC)

    new_chunks: list[dict] = []
    duplicate_chunks: list[dict] = []

    with get_session() as session:
        for chunk in chunks:
            text_sha256 = text_sha256_for(chunk["text"])
            point_id = point_id_for_text(chunk["text"])
            chunk["text_sha256"] = text_sha256
            chunk["point_id"] = point_id

            _ledger_row, is_new_primary = registry_repo.claim_dedup_ledger_entry(
                session,
                collection=collection,
                text_sha256=text_sha256,
                point_id=point_id,
                chunk_id=chunk["chunk_id"],
                parsed_artifact_id=parsed_artifact_id,
                source_id=source_id,
                created_at=now,
            )

            if is_new_primary:
                new_chunks.append(chunk)
            else:
                duplicate_chunks.append(chunk)

        _assert_dedup_conservation_invariant(
            new_count=len(new_chunks),
            duplicate_count=len(duplicate_chunks),
            total=len(chunks),
            parsed_artifact_id=parsed_artifact_id,
        )

    stats = {
        "total": len(chunks),
        "unique": len(new_chunks),
        "duplicates": len(duplicate_chunks),
        "collection": collection,
        "embed_calls_saved": len(duplicate_chunks),
    }
    log.info("dedup.complete", parsed_artifact_id=parsed_artifact_id, **stats)

    return {"new": new_chunks, "duplicates": duplicate_chunks, "stats": stats}
