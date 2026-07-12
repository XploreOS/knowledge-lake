# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Open-source project scaffolding: `LICENSE` (Apache-2.0), `NOTICE`,
  `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`, this changelog.
- GitHub community health files: issue forms, pull request template,
  `CODEOWNERS`, Dependabot configuration, and a CI workflow (lint, type-check,
  unit tests).

## [0.1.0] - 2026-07-12

Initial public baseline of the Knowledge Lake framework.

### Added
- **Framework core**: domain-agnostic ingestion pipeline with full lineage from
  raw source through every transformation to AI-ready output.
- **Registries**: source, document, and artifact registries backed by
  PostgreSQL (SQLAlchemy + Alembic migrations) with content hashes and stable
  IDs.
- **Storage**: S3-compatible object storage (MinIO for dev, AWS S3 for
  production) with an immutable raw zone.
- **Orchestration**: Dagster asset graph mapping the ingest → parse → clean →
  chunk → enrich → curate → generate-dataset → index pipeline.
- **Plugin architecture**: entry-point-based plugins for parsers (Docling,
  JSON/XML, Unstructured, Tika), embedders (sentence-transformers, LiteLLM),
  vector stores (Qdrant), crawlers (Crawl4AI, Scrapy, Playwright), and source
  discovery (SearXNG).
- **Vector search**: Qdrant hybrid search (dense + sparse + RRF fusion) with
  zero-downtime alias reindex.
- **LLM gateway**: all model calls routed through LiteLLM with task-based model
  aliases (`cheap_model`, `strong_model`, `eval_model`, `embedding_model`).
- **Corpus curation**: DataTrove quality filters and corpus-wide MinHash
  deduplication.
- **Domain packs**: the reference `healthcare` pack (sources, taxonomy, prompts,
  and validators), plus a `domains/local/` convention for user-authored packs.
- **Interfaces**: `klake` Typer CLI, FastAPI REST API, and an MCP server.
- **Export contracts**: `rag-corpus`, `pretrain`, and `finetune` exports to the
  gold zone via DuckDB/Polars/PyArrow.

[Unreleased]: https://github.com/XploreOS/knowledge-lake/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/XploreOS/knowledge-lake/releases/tag/v0.1.0
