"""Dagster software-defined assets wrapping the Knowledge Lake pipeline (D-01).

These assets call the SAME plain pipeline functions as the CLI/API — they do not
re-implement logic (D-02). The Dagster layer adds:
  - Asset-level materialize triggers (from the Dagster UI or schedule)
  - Dependency ordering via ``deps`` (Pitfall 7: do NOT use IO managers for bytes)
  - Resource injection for connection config

Pipeline stages wrapped as assets:
  ingest_raw_document    — ingest_file/ingest_url    → raw_document artifact
  parsed_document        — parse()                   → parsed_document artifact
  clean_document         — clean()                   → cleaned_document artifact
  enrich_document        — enrich_document()          → enriched_document artifact
  curate_document_asset  — curate_document()          → curated_document artifact
  chunk_document         — chunk()                   → chunk artifact IDs
  embed_chunks           — embed()                   → vectors + dim
  index_chunks           — index()                   → indexed chunk IDs in Qdrant

Asset ordering (deps chain):
  ingest_raw_document → parsed_document → clean_document → enrich_document →
  curate_document_asset → chunk_document → embed_chunks → index_chunks

  KL-04/05/06 (2026-07-15): D-01 originally made enrich_document and
  curate_document_asset parallel branches off clean_document that "did not
  block" chunk_document. That was false parallelism — curate reads the
  enriched sibling for the 40% enrich term of its composite score and
  silently substitutes a hardcoded 0.5 when enrichment hasn't run yet, and
  index reads the enriched sibling at runtime for the payload. Whichever
  branch Dagster happened to schedule first changed the composite score by
  21% on the same document. The chain is now explicit and enforced via
  non-data ``deps=[...]`` edges (curate depends on enrich; chunk depends on
  curate) while keeping the existing DATA inputs unchanged — both
  chunk_document and curate_document_asset still take clean_document as
  their data input, preserving the in-memory ParsedDoc forwarding. Ordering
  is added purely via deps=, not by re-plumbing data flow.

NO IO managers for object bytes — each asset stores its output in the registry/S3/Qdrant
and passes only the minimal metadata (artifact IDs, vectors) to the next stage via the
Dagster metadata/output dict. This follows the explicit-storage pattern (Pitfall 7).

The CLI/API surface is NOT affected by adding these assets (D-02):
  - knowledge_lake.cli.app  — unchanged
  - knowledge_lake.api.app  — unchanged
  - knowledge_lake.pipeline — unchanged
  All three call the pipeline functions directly; Dagster is an additional execution path.
"""

from pathlib import Path
from typing import Any

import structlog
from dagster import AssetSelection, Backoff, Config, RetryPolicy, asset, define_asset_job

from knowledge_lake.dagster_defs.resources import (
    LiteLLMResource,
    MinIOResource,
    PostgresResource,
    QdrantResource,
)

log = structlog.get_logger(__name__)

# Default collection — same as the CLI default
DEFAULT_COLLECTION = "klake_chunks"

# ── Shared RetryPolicy constants ──────────────────────────────────────────────

# Pipeline assets: transient failures (network, DB lock) warrant 2 retries with
# exponential backoff (IFACE-03, RESEARCH.md Pattern 3).
_PIPELINE_RETRY = RetryPolicy(max_retries=2, delay=1, backoff=Backoff.EXPONENTIAL)

# Export assets: TrainEvalContaminationError is a business-logic failure — not
# transient. Only 1 retry with linear delay to surface persistent issues quickly
# (T-06-12 threat mitigation).
_EXPORT_RETRY = RetryPolicy(max_retries=1, delay=2)


# ── Asset configs ─────────────────────────────────────────────────────────────


class IngestConfig(Config):
    """Run-time configuration for the ingest_raw_document asset.

    Either ``fixture_path`` (for hermetic testing) or ``url`` (for live download)
    must be provided. When both are absent the asset raises ValueError.
    """

    fixture_path: str | None = None
    """Local file path for hermetic fixture testing (D-05)."""

    url: str | None = None
    """https:// URL to ingest (SSRF-checked inside pipeline.ingest.ingest_url)."""

    source_name: str | None = None
    """Human-readable name for the source registry entry."""

    collection: str = DEFAULT_COLLECTION
    """Qdrant collection to index into (flows through to index_chunks)."""

    mime_type: str = "application/pdf"
    """MIME type of the document."""

    robots_checked: bool = False
    """Set True only after verifying the target URL's robots.txt (Phase 2).
    When True the source registry entry reflects that robots.txt has been checked."""


# ── Assets ────────────────────────────────────────────────────────────────────


@asset(
    description=(
        "Ingest a raw document (URL or local file) into S3 and register a "
        "raw_document artifact in the registry. "
        "Calls pipeline.ingest.ingest_file / ingest_url — no logic duplicated."
    ),
    group_name="pipeline",
    retry_policy=_PIPELINE_RETRY,
)
def ingest_raw_document(
    config: IngestConfig,
    postgres: PostgresResource,
    minio: MinIOResource,
) -> dict[str, Any]:
    """Ingest stage: download/load raw bytes → raw_document artifact.

    Returns a dict with keys: source_id, raw_artifact_id, storage_uri,
    content_hash, collection (passed to downstream assets via deps).

    The asset calls pipeline.ingest functions and passes artifact IDs forward.
    Bytes are stored in S3 by StorageBackend — NOT via IO manager (Pitfall 7).

    Args:
        config:   Run-time config (fixture_path OR url, plus source_name, collection).
        postgres: PostgreSQL resource (provides database_url for get_session).
        minio:    MinIO/S3 resource (provides endpoint_url + credentials).
    """
    from knowledge_lake.config.settings import Settings, StorageSettings
    from knowledge_lake.pipeline.ingest import ingest_file, ingest_url

    # Build a Settings instance from the Dagster resource config values.
    # This lets the pipeline functions use their normal settings-based code path.
    storage_settings = StorageSettings(
        endpoint_url=minio.endpoint_url,
        bucket=minio.bucket,
        access_key_id=minio.access_key_id,
        secret_access_key=minio.secret_access_key,
        region=minio.region,
    )
    settings = Settings(
        database_url=postgres.database_url,
        storage=storage_settings,
        _env_file=None,  # type: ignore[call-arg]
    )

    log.info(
        "dagster.ingest_raw_document.start",
        fixture_path=config.fixture_path,
        url=config.url,
        source_name=config.source_name,
        collection=config.collection,
    )

    if config.fixture_path:
        result = ingest_file(
            Path(config.fixture_path),
            config.source_name or Path(config.fixture_path).stem,
            mime_type=config.mime_type,
            settings=settings,
        )
    elif config.url:
        result = ingest_url(
            config.url,
            config.source_name or config.url,
            mime_type=config.mime_type,
            robots_checked=config.robots_checked,
            settings=settings,
        )
    else:
        raise ValueError(
            "ingest_raw_document: exactly one of fixture_path or url must be set in config"
        )

    # Pass along the collection name for downstream assets
    result["collection"] = config.collection
    # Normalize key: ingest_file/ingest_url return "artifact_id"; alias as "raw_artifact_id"
    # for downstream assets to use a more descriptive key.
    result["raw_artifact_id"] = result["artifact_id"]
    # Pass mime_type so parsed_document uses the correct type instead of defaulting
    # to "application/pdf" for HTML, DOCX, Markdown, CSV, and XLSX documents (CR-02).
    result["mime_type"] = config.mime_type

    log.info(
        "dagster.ingest_raw_document.complete",
        raw_artifact_id=result["raw_artifact_id"],
        source_id=result["source_id"],
    )
    return result


@asset(
    description=(
        "Parse raw document bytes into a ParsedDoc using the configured parser plugin. "
        "Calls pipeline.parse.parse — no logic duplicated."
    ),
    group_name="pipeline",
    retry_policy=_PIPELINE_RETRY,
)
def parsed_document(
    ingest_raw_document: dict[str, Any],
    postgres: PostgresResource,
    minio: MinIOResource,
    litellm: LiteLLMResource,
) -> dict[str, Any]:
    """Parse stage: raw_document artifact → parsed_document artifact + ParsedDoc.

    Receives the ingest output dict and returns a dict with:
      artifact_id (parsed), parsed_doc (ParsedDoc object), collection, source_id.

    Bytes are retrieved from S3 by the parse function — NOT via IO manager (Pitfall 7).
    """
    from knowledge_lake.config.settings import Settings, StorageSettings
    from knowledge_lake.pipeline.parse import parse

    raw_artifact_id = ingest_raw_document["raw_artifact_id"]
    source_id = ingest_raw_document["source_id"]
    collection = ingest_raw_document.get("collection", DEFAULT_COLLECTION)
    mime_type = ingest_raw_document.get("mime_type", "application/pdf")

    storage_settings = StorageSettings(
        endpoint_url=minio.endpoint_url,
        bucket=minio.bucket,
        access_key_id=minio.access_key_id,
        secret_access_key=minio.secret_access_key,
        region=minio.region,
    )
    settings = Settings(
        database_url=postgres.database_url,
        storage=storage_settings,
        litellm_url=litellm.litellm_url,
        _env_file=None,  # type: ignore[call-arg]
    )

    log.info("dagster.parsed_document.start", raw_artifact_id=raw_artifact_id)

    parse_result, parsed_doc = parse(
        raw_artifact_id,
        source_id,
        mime_type=mime_type,
        settings=settings,
    )

    result = {
        "artifact_id": parse_result["artifact_id"],
        "parsed_doc": parsed_doc,  # in-memory ParsedDoc passed to chunk stage
        "source_id": source_id,
        "collection": collection,
    }

    log.info(
        "dagster.parsed_document.complete",
        parsed_artifact_id=result["artifact_id"],
        sections=len(parsed_doc.sections),
    )
    return result


@asset(
    description=(
        "Clean a parsed document: remove boilerplate, detect language, near-dup flag. "
        "Calls pipeline.clean.clean — no logic duplicated. "
        "Resolves settings.domain.domain_name via DomainLoader and threads its "
        ".filters into clean() so section-level boilerplate classification can "
        "exempt domain-specific clinical codes before chunk() ever runs (QUAL-03 CR-01)."
    ),
    group_name="pipeline",
    retry_policy=_PIPELINE_RETRY,
)
def clean_document(
    parsed_document: dict[str, Any],
    postgres: PostgresResource,
    minio: MinIOResource,
) -> dict[str, Any]:
    """Clean stage: parsed_document artifact → cleaned_document artifact.

    Receives the parsed_document output dict and returns a dict with:
      artifact_id (cleaned), source_id, collection, parsed_artifact_id,
      parsed_doc (the CLEANED ParsedDoc, forwarded in-memory for chunk/tree/enrich
      stages — CLEAN-01), language, dedup_status.

    The cleaned parsed_doc object is forwarded in-memory (not via S3 / IO manager)
    to avoid re-parsing in chunk_document (Pitfall 7: no IO managers for bytes).

    Args:
        parsed_document: Output dict from the parsed_document asset.
        postgres:        PostgreSQL resource.
        minio:           MinIO/S3 resource.
    """
    from knowledge_lake.config.settings import Settings, StorageSettings
    from knowledge_lake.pipeline.clean import clean

    parsed_artifact_id = parsed_document["artifact_id"]
    source_id = parsed_document["source_id"]
    collection = parsed_document.get("collection", DEFAULT_COLLECTION)
    parsed_doc = parsed_document["parsed_doc"]

    storage_settings = StorageSettings(
        endpoint_url=minio.endpoint_url,
        bucket=minio.bucket,
        access_key_id=minio.access_key_id,
        secret_access_key=minio.secret_access_key,
        region=minio.region,
    )
    settings = Settings(
        database_url=postgres.database_url,
        storage=storage_settings,
        _env_file=None,  # type: ignore[call-arg]
    )

    log.info("dagster.clean_document.start", parsed_artifact_id=parsed_artifact_id)

    domain_filters = None
    if settings.domain.domain_name:
        from knowledge_lake.domains.loader import DomainLoader
        domain_filters = DomainLoader.from_name(settings.domain.domain_name).filters

    clean_result = clean(
        parsed_artifact_id,
        source_id,
        parsed_doc=parsed_doc,
        settings=settings,
        domain_filters=domain_filters,
    )

    result = {
        "artifact_id": clean_result["artifact_id"],
        "source_id": source_id,
        "collection": collection,
        "parsed_artifact_id": parsed_artifact_id,
        "parsed_doc": clean_result["cleaned_doc"],  # CLEANED parsed_doc forwarded in-memory to chunk_document/tree_index_document/enrich_document (CLEAN-01, Pitfall 7)
        "language": clean_result["language"],
        "dedup_status": clean_result["dedup_status"],
    }

    log.info(
        "dagster.clean_document.complete",
        artifact_id=result["artifact_id"],
        dedup_status=clean_result["dedup_status"],
    )
    return result


@asset(
    description=(
        "Split ParsedDoc into section-aware chunk artifacts. "
        "Calls pipeline.chunk.chunk — no logic duplicated. "
        "Ordered after curate_document_asset via a non-data deps= edge (KL-06) — "
        "curate's composite score must be settled before chunks are produced. "
        "Resolves settings.domain.domain_name via DomainLoader and threads its "
        ".filters into chunk() so the substance gate can exempt domain-specific "
        "clinical codes (QUAL-03)."
    ),
    group_name="pipeline",
    retry_policy=_PIPELINE_RETRY,
    deps=["curate_document_asset"],
)
def chunk_document(
    clean_document: dict[str, Any],
    postgres: PostgresResource,
) -> dict[str, Any]:
    """Chunk stage: cleaned_document → list of chunk dicts.

    Receives the clean_document output dict and returns a dict with:
      chunks (list of chunk dicts), parsed_artifact_id, source_id, collection.

    Uses the in-memory ParsedDoc forwarded through clean_document to avoid re-parsing.

    KL-06 (2026-07-15): ordered AFTER curate_document_asset via a non-data
    ``deps=["curate_document_asset"]`` edge (a string name is used rather than
    a direct function reference because curate_document_asset is defined
    later in this module — Dagster resolves deps by AssetKey/name, not import
    order). The DATA input stays clean_document, unchanged — only ordering
    was added, not a new data dependency (locked design, see PLAN.md).
    """
    from knowledge_lake.config.settings import Settings
    from knowledge_lake.pipeline.chunk import chunk

    parsed_artifact_id = clean_document["parsed_artifact_id"]
    source_id = clean_document["source_id"]
    doc = clean_document["parsed_doc"]
    collection = clean_document.get("collection", DEFAULT_COLLECTION)

    settings = Settings(
        database_url=postgres.database_url,
        _env_file=None,  # type: ignore[call-arg]
    )

    log.info("dagster.chunk_document.start", parsed_artifact_id=parsed_artifact_id)

    domain_filters = None
    if settings.domain.domain_name:
        from knowledge_lake.domains.loader import DomainLoader
        domain_filters = DomainLoader.from_name(settings.domain.domain_name).filters

    chunks = chunk(parsed_artifact_id, source_id, doc, settings=settings, domain_filters=domain_filters)

    result = {
        "chunks": chunks,
        "parsed_artifact_id": parsed_artifact_id,
        "source_id": source_id,
        "collection": collection,
    }

    log.info("dagster.chunk_document.complete", chunk_count=len(chunks))
    return result


@asset(
    description=(
        "Enrich a cleaned document with LLM-judged metadata (summary, document_type, "
        "organization, jurisdiction, keywords, entities, quality_score). Data input "
        "is clean_document; curate_document_asset and (transitively) chunk_document "
        "are now ordered AFTER this asset via non-data deps= edges (KL-06) so the "
        "enrich quality_score is always settled before curate reads it. Calls "
        "pipeline.enrich.enrich_document — no logic duplicated."
    ),
    group_name="pipeline",
    retry_policy=_PIPELINE_RETRY,
)
def enrich_document(
    clean_document: dict[str, Any],
    postgres: PostgresResource,
    minio: MinIOResource,
    litellm: LiteLLMResource,
) -> dict[str, Any]:
    """Enrich stage: cleaned_document artifact → enriched_document artifact.

    Receives the clean_document output dict and returns the enrich_document()
    result dict (artifact_id, cached, status, quality_score, cost_usd).

    KL-06 (2026-07-15): data input is clean_document (unchanged), but this is
    NO LONGER a parallel branch that "does not block" the rest of the chain —
    curate_document_asset declares a non-data ``deps=["enrich_document"]``
    edge, so Dagster now schedules enrich strictly before curate (and,
    transitively, before chunk_document/embed_chunks/index_chunks). This
    closes the scheduling race documented in KL-06: curate's composite score
    read the enriched sibling's quality_score at runtime and silently
    defaulted to 0.5 when enrichment hadn't run yet, producing a 21% swing in
    the same document's composite score purely from scheduling order.
    """
    from knowledge_lake.config.settings import Settings, StorageSettings
    from knowledge_lake.pipeline.enrich import enrich_document as enrich_fn

    cleaned_artifact_id = clean_document["artifact_id"]
    source_id = clean_document["source_id"]
    parsed_doc = clean_document["parsed_doc"]

    storage_settings = StorageSettings(
        endpoint_url=minio.endpoint_url,
        bucket=minio.bucket,
        access_key_id=minio.access_key_id,
        secret_access_key=minio.secret_access_key,
        region=minio.region,
    )
    settings = Settings(
        database_url=postgres.database_url,
        storage=storage_settings,
        litellm_url=litellm.litellm_url,
        _env_file=None,  # type: ignore[call-arg]
    )

    log.info("dagster.enrich_document.start", cleaned_artifact_id=cleaned_artifact_id)

    domain_system_prompt: str | None = None
    if settings.domain.domain_name:
        from knowledge_lake.domains.loader import DomainLoader
        domain_system_prompt = DomainLoader.from_name(settings.domain.domain_name).render_prompt("enrich.j2")

    result = enrich_fn(
        cleaned_artifact_id, source_id, parsed_doc=parsed_doc, settings=settings,
        domain_system_prompt=domain_system_prompt,
    )

    log.info(
        "dagster.enrich_document.complete",
        status=result.get("status"),
        quality_score=result.get("quality_score"),
    )
    return result


@asset(
    group_name="pipeline",
    retry_policy=_PIPELINE_RETRY,
    description=(
        "Generate a hierarchical tree index from a cleaned document (TREE-01/TREE-05). "
        "Fan-out branch off clean_document parallel to chunk_document. "
        "Thin shell over pipeline.tree_index.tree_index(). "
        "Requires Dagster code-location reload to appear in live daemon."
    ),
)
def tree_index_document(
    clean_document: dict[str, Any],
    postgres: PostgresResource,
    minio: MinIOResource,
    litellm: LiteLLMResource,
) -> dict[str, Any]:
    """Tree-index stage: cleaned_document → tree index artifact.

    Receives the clean_document output dict and returns the tree_index()
    result dict (artifact_id, cached, status).

    Parallel fan-out branch off clean_document (TREE-05) — this asset itself
    has no deps= edge to enrich_document/curate_document_asset/chunk_document
    and is not blocked by (or blocking) any of them. KL-06 (2026-07-15) only
    reordered the enrich → curate → chunk chain; tree_index_document was not
    part of that scheduling race and is unaffected.
    """
    from knowledge_lake.config.settings import Settings, StorageSettings
    from knowledge_lake.pipeline.tree_index import tree_index

    parsed_artifact_id = clean_document["parsed_artifact_id"]
    source_id = clean_document["source_id"]
    doc = clean_document["parsed_doc"]

    settings = Settings(
        database_url=postgres.database_url,
        storage=StorageSettings(
            endpoint_url=minio.endpoint_url,
            bucket=minio.bucket,
            access_key_id=minio.access_key_id,
            secret_access_key=minio.secret_access_key,
            region=minio.region,
        ),
        litellm_url=litellm.litellm_url,
        _env_file=None,  # type: ignore[call-arg]
    )

    log.info("dagster.tree_index_document.start", parsed_artifact_id=parsed_artifact_id)

    result = tree_index(parsed_artifact_id, source_id, doc, settings=settings)

    log.info(
        "dagster.tree_index_document.complete",
        status=result.get("status"),
        cached=result.get("cached"),
    )
    return result


@asset(
    description=(
        "Embed chunk texts into dense vectors using the configured embedder plugin. "
        "Calls pipeline.embed.embed — no logic duplicated."
    ),
    group_name="pipeline",
    retry_policy=_PIPELINE_RETRY,
)
def embed_chunks(chunk_document: dict[str, Any]) -> dict[str, Any]:
    """Embed stage: chunk texts → dense vectors.

    Stateless transformation — reads chunks dict from chunk_document output,
    returns a dict with vectors, dim, chunks, parsed_artifact_id, collection.

    Note: This asset takes no Dagster resources — the embedder plugin is
    resolved from the environment settings (the default local sentence-transformers
    embedder requires no API credentials, D-13).
    """
    from knowledge_lake.pipeline.embed import embed

    chunks = chunk_document["chunks"]
    parsed_artifact_id = chunk_document["parsed_artifact_id"]
    source_id = chunk_document["source_id"]
    collection = chunk_document.get("collection", DEFAULT_COLLECTION)

    log.info("dagster.embed_chunks.start", chunk_count=len(chunks))

    vectors, dim = embed(chunks)

    result = {
        "vectors": vectors,
        "dim": dim,
        "chunks": chunks,
        "parsed_artifact_id": parsed_artifact_id,
        "source_id": source_id,
        "collection": collection,
    }

    log.info("dagster.embed_chunks.complete", vectors=len(vectors), dim=dim)
    return result


@asset(
    description=(
        "Upsert chunk vectors with citation payload into Qdrant. "
        "Calls pipeline.index.index — no logic duplicated."
    ),
    group_name="pipeline",
    retry_policy=_PIPELINE_RETRY,
)
def index_chunks(
    embed_chunks: dict[str, Any],
    qdrant: QdrantResource,
) -> dict[str, Any]:
    """Index stage: vectors → Qdrant upsert.

    Receives embed output and upserts into Qdrant. Returns dict with
    chunk_artifact_ids (list), collection, chunk_count.
    """
    from knowledge_lake.config.settings import Settings
    from knowledge_lake.pipeline.index import index

    vectors = embed_chunks["vectors"]
    dim = embed_chunks["dim"]
    chunks = embed_chunks["chunks"]
    parsed_artifact_id = embed_chunks["parsed_artifact_id"]
    collection = embed_chunks.get("collection", DEFAULT_COLLECTION)

    settings = Settings(
        qdrant_url=qdrant.qdrant_url,
        _env_file=None,  # type: ignore[call-arg]
    )

    log.info(
        "dagster.index_chunks.start",
        chunk_count=len(chunks),
        collection=collection,
        dim=dim,
    )

    indexed_ids = index(
        chunks,
        vectors,
        dim,
        parsed_artifact_id,
        collection=collection,
        settings=settings,
    )

    result = {
        "chunk_artifact_ids": indexed_ids,
        "collection": collection,
        "chunk_count": len(indexed_ids),
    }

    log.info(
        "dagster.index_chunks.complete",
        indexed=len(indexed_ids),
        collection=collection,
    )
    return result


class GenerateDatasetConfig(Config):
    """Dagster run config for the generate_dataset asset (DATA-01/02).

    Specifies which source artifact to generate an example from, what kind
    of dataset to generate, and which logical dataset to accumulate into.
    """

    kind: str = "qa"
    """Dataset kind: 'qa' (eval_model) or 'instruction' (strong_model)."""

    source_artifact_id: str = ""
    """Source artifact ID: chunk ID for 'qa', enriched_document ID for 'instruction'."""

    dataset_name: str = "default-dataset"
    """Logical dataset name (get-or-create)."""


@asset(
    description=(
        "Generate a dataset training/eval example from a chunk (qa) or enriched_document "
        "(instruction) artifact. Calls pipeline.datasets.generate_qa_example or "
        "pipeline.datasets.generate_instruction_example — no logic duplicated (D-02)."
    ),
    group_name="pipeline",
    retry_policy=_PIPELINE_RETRY,
)
def generate_dataset(
    config: GenerateDatasetConfig,
    postgres: PostgresResource,
    minio: MinIOResource,
    litellm: LiteLLMResource,
) -> dict[str, Any]:
    """Dataset generation stage: source artifact → DatasetExample registry row.

    Receives run config specifying kind, source_artifact_id, and dataset_name.
    Returns the generate_qa_example() / generate_instruction_example() result dict
    (status, example_id, dataset_id, cost_usd).

    Resources: postgres (for the registry get_session() calls),
               minio (for instruction-tuning's parent cleaned_document S3 fetch),
               litellm (for the LLM completion call via eval_model/strong_model).
    """
    from knowledge_lake.config.settings import Settings, StorageSettings
    from knowledge_lake.pipeline.datasets import (
        generate_instruction_example,
        generate_qa_example,
    )

    storage_settings = StorageSettings(
        endpoint_url=minio.endpoint_url,
        bucket=minio.bucket,
        access_key_id=minio.access_key_id,
        secret_access_key=minio.secret_access_key,
        region=minio.region,
    )
    settings = Settings(
        database_url=postgres.database_url,
        storage=storage_settings,
        litellm_url=litellm.litellm_url,
        _env_file=None,  # type: ignore[call-arg]
    )

    log.info(
        "dagster.generate_dataset.start",
        kind=config.kind,
        source_artifact_id=config.source_artifact_id,
        dataset_name=config.dataset_name,
    )

    if config.kind == "qa":
        result = generate_qa_example(
            config.source_artifact_id, config.dataset_name, settings=settings
        )
    elif config.kind == "instruction":
        result = generate_instruction_example(
            config.source_artifact_id, config.dataset_name, settings=settings
        )
    else:
        raise ValueError(
            f"generate_dataset: unknown kind={config.kind!r}. "
            "Valid values: 'qa', 'instruction'."
        )

    log.info(
        "dagster.generate_dataset.complete",
        status=result.get("status"),
        example_id=result.get("example_id"),
    )
    return result


@asset(
    name="curate_document_asset",
    description=(
        "Run DataTrove-style quality filters on a cleaned_document artifact and compute "
        "a composite quality score spanning parse + enrich + curation stages (CURATE-01..03). "
        "Ordered after enrich_document via a non-data deps= edge (KL-06) so the enrich "
        "term of the composite is always the real score, never the 0.5 default. "
        "Calls pipeline.curate.curate_document — no logic duplicated."
    ),
    group_name="pipeline",
    retry_policy=_PIPELINE_RETRY,
    deps=["enrich_document"],
)
def curate_document_asset(
    clean_document: dict[str, Any],
    postgres: PostgresResource,
    minio: MinIOResource,
) -> dict[str, Any]:
    """Curate stage: cleaned_document artifact → curated_document artifact.

    Receives the clean_document output dict, runs DataTrove-style filters and
    composite scoring, and returns the curate_document() result dict
    (artifact_id, cached, status, quality_score).

    KL-06 (2026-07-15): data input is clean_document (unchanged — the DATA
    dependency was never re-plumbed), but this is NO LONGER a parallel
    branch off clean_document alongside enrich_document/chunk_document
    (D-01's original claim). A non-data ``deps=["enrich_document"]`` edge
    enforces that enrich runs first, so ``curate_fn``'s internal read of the
    enriched sibling's quality_score (pipeline/curate.py) always sees the
    real LLM-judged score rather than silently defaulting to 0.5. This asset
    is, in turn, a hard dependency of chunk_document (see its deps=), which
    makes index_chunks depend on curate transitively.
    """
    from knowledge_lake.config.settings import Settings, StorageSettings
    from knowledge_lake.pipeline.curate import curate_document as curate_fn

    cleaned_artifact_id = clean_document["artifact_id"]
    source_id = clean_document["source_id"]

    storage_settings = StorageSettings(
        endpoint_url=minio.endpoint_url,
        bucket=minio.bucket,
        access_key_id=minio.access_key_id,
        secret_access_key=minio.secret_access_key,
        region=minio.region,
    )
    settings = Settings(
        database_url=postgres.database_url,
        storage=storage_settings,
        _env_file=None,  # type: ignore[call-arg]
    )

    log.info("dagster.curate_document_asset.start", cleaned_artifact_id=cleaned_artifact_id)

    result = curate_fn(cleaned_artifact_id, source_id, settings=settings)

    log.info(
        "dagster.curate_document_asset.complete",
        status=result.get("status"),
        quality_score=result.get("quality_score"),
    )
    return result


# ── Export assets (EXPORT-01..03) ─────────────────────────────────────────────


class ExportRagConfig(Config):
    """Dagster run config for the export_rag_corpus asset (EXPORT-01).

    Pass domain at materialize time so gold-zone exports land under the correct
    domain segment (STORE-03).  Leave empty to fall back to ``_unclassified``.
    """

    domain: str = ""
    """Domain classification for the export (e.g. ``healthcare``).  Empty string
    falls back to the ``_unclassified`` segment — matches CLI/API default behaviour."""


@asset(
    description=(
        "Export all chunk artifacts as a Parquet file to the gold zone (EXPORT-01). "
        "Uses Polars for columnar write + DuckDB httpfs for verification. "
        "Calls pipeline.export.export_rag_corpus — no logic duplicated (D-02)."
    ),
    group_name="export",
    retry_policy=_EXPORT_RETRY,
)
def export_rag_corpus(
    config: ExportRagConfig,
    postgres: PostgresResource,
    minio: MinIOResource,
) -> dict[str, Any]:
    """Export stage: chunk artifacts → gold-zone Parquet (EXPORT-01).

    Joins each chunk's citation fields with enrichment metadata via the same
    join helper as pipeline.index.index(). Writes only _RAG_CORPUS_FIELDS columns
    (T-05-08 information-disclosure mitigation).

    Fails closed with TrainEvalContaminationError on any undocumented train/eval
    overlap (05-AI-SPEC Section 6/7 hard gate).
    """
    from knowledge_lake.config.settings import Settings, StorageSettings
    from knowledge_lake.pipeline.export import export_rag_corpus as export_rag_fn

    storage_settings = StorageSettings(
        endpoint_url=minio.endpoint_url,
        bucket=minio.bucket,
        access_key_id=minio.access_key_id,
        secret_access_key=minio.secret_access_key,
        region=minio.region,
    )
    settings = Settings(
        database_url=postgres.database_url,
        storage=storage_settings,
        _env_file=None,  # type: ignore[call-arg]
    )

    log.info("dagster.export_rag_corpus.start", domain=config.domain or "_unclassified")
    result = export_rag_fn(domain=config.domain or None, settings=settings)
    log.info("dagster.export_rag_corpus.complete", row_count=result.get("row_count"))
    return result


class ExportPretrainConfig(Config):
    """Dagster run config for the export_pretrain_corpus asset (EXPORT-02).

    Pass domain at materialize time so gold-zone exports land under the correct
    domain segment (STORE-03).  Leave empty to fall back to ``_unclassified``.
    """

    domain: str = ""
    """Domain classification for the export (e.g. ``healthcare``).  Empty string
    falls back to the ``_unclassified`` segment — matches CLI/API default behaviour."""


@asset(
    description=(
        "Export quality-filtered curated_document text as JSONL to the gold zone (EXPORT-02). "
        "Applies ExportSettings.min_quality_score_for_pretrain at export time. "
        "Calls pipeline.export.export_pretrain_corpus — no logic duplicated (D-02)."
    ),
    group_name="export",
    retry_policy=_EXPORT_RETRY,
)
def export_pretrain_corpus(
    config: ExportPretrainConfig,
    postgres: PostgresResource,
    minio: MinIOResource,
) -> dict[str, Any]:
    """Export stage: curated_document artifacts → gold-zone JSONL (EXPORT-02).

    Only includes documents whose composite_quality_score >= min_quality_score_for_pretrain.

    Fails closed with TrainEvalContaminationError on any undocumented train/eval
    overlap (05-AI-SPEC Section 6/7 hard gate).
    """
    from knowledge_lake.config.settings import Settings, StorageSettings
    from knowledge_lake.pipeline.export import export_pretrain_corpus as export_pretrain_fn

    storage_settings = StorageSettings(
        endpoint_url=minio.endpoint_url,
        bucket=minio.bucket,
        access_key_id=minio.access_key_id,
        secret_access_key=minio.secret_access_key,
        region=minio.region,
    )
    settings = Settings(
        database_url=postgres.database_url,
        storage=storage_settings,
        _env_file=None,  # type: ignore[call-arg]
    )

    log.info("dagster.export_pretrain_corpus.start", domain=config.domain or "_unclassified")
    result = export_pretrain_fn(domain=config.domain or None, settings=settings)
    log.info("dagster.export_pretrain_corpus.complete", row_count=result.get("row_count"))
    return result


class ExportFinetuneConfig(Config):
    """Dagster run config for the export_finetune_dataset asset (EXPORT-03).

    Specifies which logical Dataset to export as OpenAI chat-messages JSONL.
    """

    dataset_name: str = ""
    """Name of the logical Dataset row to export (must already exist in the registry)."""

    domain: str = ""
    """Domain classification for the export (e.g. ``healthcare``).  Empty string
    falls back to the ``_unclassified`` segment — matches CLI/API default behaviour."""


@asset(
    description=(
        "Export a logical Dataset's examples as OpenAI chat-messages JSONL to the gold zone (EXPORT-03). "
        "Skips examples with dangling source_artifact_id (DATA-03 lineage integrity). "
        "Calls pipeline.export.export_finetune_dataset — no logic duplicated (D-02)."
    ),
    group_name="export",
    retry_policy=_EXPORT_RETRY,
)
def export_finetune_dataset(
    config: ExportFinetuneConfig,
    postgres: PostgresResource,
    minio: MinIOResource,
) -> dict[str, Any]:
    """Export stage: DatasetExample rows → gold-zone chat-messages JSONL (EXPORT-03).

    Branches on payload shape (QA-shaped vs instruction-shaped) to produce the
    appropriate OpenAI chat-messages format.

    Fails closed with TrainEvalContaminationError on any undocumented train/eval
    overlap (05-AI-SPEC Section 6/7 hard gate).
    """
    from knowledge_lake.config.settings import Settings, StorageSettings
    from knowledge_lake.pipeline.export import export_finetune_dataset as export_finetune_fn

    storage_settings = StorageSettings(
        endpoint_url=minio.endpoint_url,
        bucket=minio.bucket,
        access_key_id=minio.access_key_id,
        secret_access_key=minio.secret_access_key,
        region=minio.region,
    )
    settings = Settings(
        database_url=postgres.database_url,
        storage=storage_settings,
        _env_file=None,  # type: ignore[call-arg]
    )

    log.info("dagster.export_finetune_dataset.start", dataset_name=config.dataset_name, domain=config.domain or "_unclassified")
    result = export_finetune_fn(config.dataset_name, domain=config.domain or None, settings=settings)
    log.info(
        "dagster.export_finetune_dataset.complete",
        row_count=result.get("row_count"),
        skipped_dangling=result.get("skipped_dangling_lineage"),
    )
    return result


# ── Core Pipeline E2E Job (DOMAIN-04) ─────────────────────────────────────────

# Selects exactly the 8 core pipeline assets for the E2E validation job.
#
# generate_dataset is NOT included — see Pitfall 6 (RESEARCH.md): it declares a
# GenerateDatasetConfig (kind / source_artifact_id / dataset_name), so including
# it would require valid source_artifact_id run config that is separate from the
# ingest-to-index pipeline being validated. T-06-14 mitigation.
#
# KL-06 (2026-07-15): curate_document_asset IS included, and its exclusion was a
# bug, not a decision. The Pitfall 6 / T-06-14 rationale above is specifically
# about assets that need run config — curate_document_asset(clean_document,
# postgres, minio) declares NO Config, so it needs no run config and that
# rationale never applied to it. Leaving it out actively defeated the KL-06 fix:
# Dagster drops a deps= edge whose target is outside the selection, so with
# curate excluded, chunk_document's deps=[curate_document_asset] edge vanished
# for THIS job and chunk regained its unordered relationship with enrich — the
# exact scheduling race KL-06 closed, alive again in the main E2E job people
# actually run. The selection must contain every asset the ordering chain
# depends on, or the chain is not enforced where it matters.
# test_asset_ordering.py pins this so the selection cannot be re-narrowed
# silently.
#
# KL-16: this job was previously named for one specific domain, even though
# the asset selection is fully domain-generic (these core assets run
# identically for any domain pack) — a domain-specific name in framework
# core was misleading, not accurate. The real gap this doesn't solve —
# domain packs cannot contribute their own Dagster jobs without editing
# framework source — is deliberately deferred to the roadmap (see
# E2E-GAP-ANALYSIS.md KL-16).
core_pipeline_e2e_job = define_asset_job(
    name="core_pipeline_e2e_job",
    selection=AssetSelection.assets(
        ingest_raw_document,
        parsed_document,
        clean_document,
        enrich_document,
        curate_document_asset,
        chunk_document,
        embed_chunks,
        index_chunks,
    ),
    description=(
        "Full pipeline job for core E2E validation (DOMAIN-04). "
        "Materializes the core ingest-to-index chain "
        "(ingest → parse → clean → enrich → curate → chunk → embed → index); "
        "domain-agnostic — the asset selection is the same regardless of which "
        "domain pack is active."
    ),
)
