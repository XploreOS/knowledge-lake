"""
Knowledge Lake Dagster definitions — software-defined assets wrapping the pipeline (D-01).

This file provides the Dagster code location (loaded by the dagster-webserver and
dagster-daemon compose services). It registers:

  Assets (pipeline stages):
    ingest_raw_document → parsed_document → clean_document → chunk_document → embed_chunks → index_chunks

  Resources (connection config, read via EnvVar — Pitfall 14):
    postgres  — PostgreSQL registry database URL
    minio     — S3-compatible object storage credentials + endpoint
    qdrant    — Qdrant vector-store URL
    litellm   — LiteLLM proxy URL (model gateway)

Architecture decision D-01/D-02:
    Assets call the same plain pipeline functions as the CLI/API — no logic
    is duplicated. The CLI/API surface (klake CLI commands, FastAPI endpoints)
    is unchanged; Dagster is an additional execution path, not a replacement.

Pitfall 7 (Dagster IO managers for object bytes):
    Assets use ``deps`` for ordering and call StorageBackend/registry explicitly.
    No IO managers are used for object bytes — only Dagster's default in-memory
    IO manager passes the minimal metadata dicts between stages.

Pitfall 14 (Dagster resource config drift):
    All connection URLs and credentials come from EnvVar — no hardcoded defaults
    in this file. The docker-compose.yml sets these env vars for the dagster
    container; local dev uses the KLAKE_* vars from .env.
"""

from __future__ import annotations

import structlog
from dagster import Definitions, EnvVar

from knowledge_lake.dagster_defs.assets import (
    chunk_document,
    clean_document,
    curate_document_asset,
    embed_chunks,
    enrich_document,
    export_finetune_dataset,
    export_pretrain_corpus,
    export_rag_corpus,
    generate_dataset,
    healthcare_e2e_job,
    index_chunks,
    ingest_raw_document,
    parsed_document,
)
from knowledge_lake.dagster_defs.resources import (
    LiteLLMResource,
    MinIOResource,
    PostgresResource,
    QdrantResource,
)

logger = structlog.get_logger(__name__)

# ── Definitions ───────────────────────────────────────────────────────────────
# All pipeline stage assets + resources using EnvVar config (Pitfall 14).
# EnvVar reads from the environment at run time — not at import time — so the
# dagster-webserver container can load Definitions without all vars set in
# the web process, while the daemon/executor process has them when jobs run.

defs = Definitions(
    assets=[
        ingest_raw_document,
        parsed_document,
        clean_document,
        chunk_document,
        enrich_document,
        curate_document_asset,
        generate_dataset,
        embed_chunks,
        index_chunks,
        export_rag_corpus,
        export_pretrain_corpus,
        export_finetune_dataset,
    ],
    jobs=[healthcare_e2e_job],
    resources={
        "postgres": PostgresResource(
            database_url=EnvVar("KLAKE_DATABASE_URL"),
        ),
        "minio": MinIOResource(
            endpoint_url=EnvVar("KLAKE_STORAGE__ENDPOINT_URL"),
            bucket=EnvVar("KLAKE_STORAGE__BUCKET"),
            access_key_id=EnvVar("KLAKE_STORAGE__ACCESS_KEY_ID"),
            secret_access_key=EnvVar("KLAKE_STORAGE__SECRET_ACCESS_KEY"),
        ),
        "qdrant": QdrantResource(
            qdrant_url=EnvVar("KLAKE_QDRANT_URL"),
        ),
        "litellm": LiteLLMResource(
            litellm_url=EnvVar("KLAKE_LITELLM_URL"),
        ),
    },
)
