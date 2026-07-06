"""
Prefixed UUIDv7 ID generation for Knowledge Lake entities (D-15, FOUND-05).

Every entity in the registry gets a stable, time-sortable, self-describing ID
of the form ``<prefix>_<uuidv7>``, e.g. ``src_0196a2c1-6780-7000-8000-...``.

The UUIDv7 library is isolated to this one module.  When the project upgrades
to Python 3.14 the only change required is replacing the import line:

    # Python 3.14+:
    from uuid import uuid7 as _uuid7

Usage::

    from knowledge_lake.ids import new_id

    source_id = new_id("source")            # "src_<uuidv7>"
    doc_id    = new_id("raw_document")      # "doc_<uuidv7>"
    chunk_id  = new_id("chunk")             # "chk_<uuidv7>"
    enr_id    = new_id("enriched_document") # "doc_<uuidv7>"
"""

from __future__ import annotations

# NOTE: Swap this single import to `from uuid import uuid7 as _uuid7` at Python 3.14.
import uuid_utils as _uuid_utils

# ── Kind → prefix mapping ─────────────────────────────────────────────────────
#
# All known entity kinds and their short type prefixes.  The prefix appears
# before the underscore in every ID so logs and CLI output are self-describing.
_PREFIX: dict[str, str] = {
    "source": "src",
    "raw_document": "doc",
    "parsed_document": "doc",
    "cleaned_document": "doc",
    "enriched_document": "doc",
    "chunk": "chk",
    "artifact": "art",
    "crawl_job": "job",
    "crawl_state": "cst",
    "bronze_document": "doc",
    "curated_document": "doc",
}


def new_id(kind: str) -> str:
    """Return a prefixed UUIDv7 string for the given entity kind.

    Parameters
    ----------
    kind:
        One of the supported entity kinds: ``source``, ``raw_document``,
        ``parsed_document``, ``cleaned_document``, ``enriched_document``,
        ``chunk``, ``artifact``.

    Returns
    -------
    str
        A string of the form ``<prefix>_<uuidv7>``, e.g.
        ``src_0196a2c1-6780-7000-8000-abcdef012345``.

    Raises
    ------
    ValueError
        If ``kind`` is not in the supported set.
    """
    if kind not in _PREFIX:
        raise ValueError(
            f"Unknown entity kind {kind!r}. "
            f"Supported kinds: {sorted(_PREFIX)}"
        )
    # NOTE: Replace _uuid_utils.uuid7() with uuid7() when upgrading to Python 3.14.
    return f"{_PREFIX[kind]}_{_uuid_utils.uuid7()}"
