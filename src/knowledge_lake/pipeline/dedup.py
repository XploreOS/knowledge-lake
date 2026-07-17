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

import hashlib
import unicodedata
import uuid

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
