# Architecture Patterns

**Domain:** Knowledge Lake / Document Processing Pipeline Framework
**Researched:** 2026-07-02
**Overall Confidence:** MEDIUM (cross-referenced official docs from Dagster, FastAPI, Typer, pluggy; medallion architecture from Databricks reference; patterns verified across multiple sources)

## Recommended Architecture

### High-Level System Diagram

```
                         +------------------+
                         |   CLI (Typer)    |
                         |   klake command  |
                         +--------+---------+
                                  |
                         +--------v---------+
                         |  API (FastAPI)   |
                         |  REST + triggers |
                         +--------+---------+
                                  |
              +-------------------+-------------------+
              |                                       |
    +---------v----------+              +-------------v-----------+
    | Dagster Orchestrator|              | Plugin Manager (pluggy) |
    | Assets + Schedules  |              | hookspecs + hookimpls   |
    +---------+----------+              +-------------+-----------+
              |                                       |
    +---------v------------------------------------------v--------+
    |                     Core Services Layer                      |
    |  Registry | Storage | Lineage | Config | Domain Packs       |
    +-----+----------+----------+---------+----------+------------+
          |          |          |         |          |
    +-----v---+ +---v----+ +--v---+ +---v----+ +---v---------+
    |PostgreSQL| |S3/MinIO| |Qdrant| |LiteLLM | |Domain Packs |
    |Registries| |Objects | |Vector| |Gateway | |(Healthcare) |
    +----------+ +--------+ +------+ +--------+ +-------------+
```

### Data Flow Through Zones

```
Sources (web, files, APIs)
    |
    v
+-------------------------------------------+
| BRONZE (Raw Zone) - Immutable             |
| S3: bronze/{source_id}/{doc_id}/raw.*     |
| PG: documents table (raw metadata)        |
+-------------------------------------------+
    |
    v
+-------------------------------------------+
| SILVER (Processed Zone) - Cleaned         |
| S3: silver/{doc_id}/parsed.json           |
| S3: silver/{doc_id}/chunks/*.json         |
| PG: sections, chunks tables               |
+-------------------------------------------+
    |
    v
+-------------------------------------------+
| GOLD (AI-Ready Zone) - Enriched           |
| S3: gold/embeddings/{collection}/*.parquet|
| S3: gold/datasets/{dataset_id}/*.jsonl    |
| Qdrant: vector collections                |
| PG: artifacts, datasets tables            |
+-------------------------------------------+
```

## Component Boundaries

| Component | Responsibility | Communicates With | Build Phase |
|-----------|---------------|-------------------|-------------|
| **Core Config** | Settings loading, env management, path resolution | All components | Phase 1 |
| **Storage Abstraction** | S3-compatible read/write with zone routing | All data components | Phase 1 |
| **Registry (PostgreSQL)** | Source, document, chunk, artifact metadata; lineage graph | All pipeline stages | Phase 1 |
| **Plugin Manager** | Hook specs, plugin discovery, adapter loading | Parsers, crawlers, vector stores | Phase 1 |
| **Dagster Definitions** | Asset DAG, IO managers, resources, schedules | Storage, Registry, Plugins | Phase 2 |
| **Ingest Pipeline** | Crawling, file upload, raw storage | Storage (Bronze), Registry | Phase 2 |
| **Parse Pipeline** | Document parsing, section extraction | Storage (Silver), Registry, Parser plugins | Phase 2 |
| **Chunk Pipeline** | Section-aware/token-aware chunking | Storage (Silver), Registry | Phase 3 |
| **Enrich Pipeline** | LLM metadata, embeddings, quality scoring | LiteLLM, Storage (Gold), Registry | Phase 3 |
| **Export Pipeline** | Parquet/JSONL/DuckDB generation, vector indexing | Storage (Gold), Vector plugins | Phase 4 |
| **API Layer (FastAPI)** | REST CRUD, pipeline triggers, status queries | Dagster, Registry, Storage | Phase 2+ |
| **CLI Layer (Typer)** | User commands, rich output, batch operations | API Layer or direct service calls | Phase 2+ |
| **Domain Packs** | Source seeds, domain schemas, custom enrichment | Plugin Manager, Enrich Pipeline | Phase 4+ |

## Detailed Component Architecture

### 1. Plugin / Adapter Architecture (pluggy-based)

Use pluggy for the plugin system because it provides decoupled hook specifications, setuptools entry_point discovery, and is battle-tested (pytest's plugin system). The framework defines hookspecs; plugins provide hookimpls.

**Hook Specification Design:**

```python
# klake/plugins/hookspecs.py
import pluggy

hookspec = pluggy.HookspecMarker("klake")
hookimpl = pluggy.HookimplMarker("klake")

class ParserSpec:
    @hookspec(firstresult=True)
    def can_parse(self, mime_type: str, file_ext: str) -> bool:
        """Return True if this parser handles the given type."""

    @hookspec(firstresult=True)
    def parse_document(self, raw_path: str, options: dict) -> "ParseResult":
        """Parse raw document into structured sections."""

class CrawlerSpec:
    @hookspec(firstresult=True)
    def can_crawl(self, url: str, source_type: str) -> bool:
        """Return True if this crawler handles the given source."""

    @hookspec
    def crawl_source(self, source_config: dict) -> "Iterator[RawDocument]":
        """Yield raw documents from a source."""

class VectorStoreSpec:
    @hookspec
    def index_chunks(self, collection: str, chunks: "list[ChunkWithEmbedding]") -> None:
        """Index chunks into vector store."""

    @hookspec(firstresult=True)
    def search(self, collection: str, query_vector: list, top_k: int) -> "list[SearchResult]":
        """Search for similar chunks."""

class EmbeddingSpec:
    @hookspec(firstresult=True)
    def embed_texts(self, texts: list[str], model_alias: str) -> "list[list[float]]":
        """Generate embeddings for text list."""
```

**Plugin Discovery:**

```python
# klake/plugins/manager.py
import pluggy

def create_plugin_manager() -> pluggy.PluginManager:
    pm = pluggy.PluginManager("klake")
    pm.add_hookspecs(ParserSpec)
    pm.add_hookspecs(CrawlerSpec)
    pm.add_hookspecs(VectorStoreSpec)
    pm.add_hookspecs(EmbeddingSpec)

    # Load built-in plugins
    from klake.plugins.builtin import docling_parser, crawl4ai_crawler, qdrant_store
    pm.register(docling_parser)
    pm.register(crawl4ai_crawler)
    pm.register(qdrant_store)

    # Load external plugins via entry_points
    pm.load_setuptools_entrypoints("klake")

    return pm
```

**Entry point registration (pyproject.toml for external plugins):**

```toml
[project.entry-points.klake]
my_custom_parser = "my_package.parser:MyParserPlugin"
```

**Why pluggy over ABC + registry:**
- Pluggy supports multiple implementations per hook (e.g., multiple parsers registered, `firstresult` picks the right one)
- Entry_points enable pip-installable third-party plugins without modifying core code
- LIFO ordering and `tryfirst`/`trylast` control priority
- No import-time coupling between host and plugins

### 2. Data Lake Zone Architecture

Adapted medallion pattern for document processing:

| Zone | S3 Prefix | Contents | Immutability | Registry Table |
|------|-----------|----------|--------------|----------------|
| **Bronze** | `bronze/` | Raw files exactly as received | IMMUTABLE - never modified | `documents` (status=raw) |
| **Silver** | `silver/` | Parsed JSON, extracted sections, chunks | APPEND-ONLY per version | `sections`, `chunks` |
| **Gold** | `gold/` | Embeddings, datasets, exports | VERSIONED outputs | `artifacts`, `datasets` |

**Zone transition rules:**
- Bronze -> Silver: Parse + clean. Original raw file stays in Bronze forever.
- Silver -> Gold: Enrich + export. Silver data remains as intermediate for reprocessing.
- Each transition records lineage edges in the registry.

**Storage path conventions:**

```
bronze/{source_id}/{document_id}/{content_hash}.{ext}
silver/{document_id}/v{version}/parsed.json
silver/{document_id}/v{version}/sections/{section_id}.json
silver/{document_id}/v{version}/chunks/{chunk_id}.json
gold/embeddings/{collection_id}/{batch_id}.parquet
gold/datasets/{dataset_id}/v{version}/{split}.jsonl
gold/exports/{export_id}/{filename}
```

### 3. Registry Design (PostgreSQL)

**Core schema pattern:**

```sql
-- Source registry: where content comes from
CREATE TABLE sources (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    source_type TEXT NOT NULL,  -- 'web', 'file_upload', 'api', 'sitemap'
    url TEXT,
    config JSONB NOT NULL DEFAULT '{}',
    domain_pack TEXT,  -- NULL = generic
    schedule TEXT,  -- cron expression or NULL
    last_crawled_at TIMESTAMPTZ,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Document registry: individual documents
CREATE TABLE documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id UUID REFERENCES sources(id),
    content_hash TEXT NOT NULL,  -- SHA-256 of raw content
    mime_type TEXT,
    file_extension TEXT,
    title TEXT,
    url TEXT,  -- original URL if web-sourced
    raw_storage_path TEXT NOT NULL,  -- S3 key in bronze zone
    file_size_bytes BIGINT,
    language TEXT,
    zone TEXT NOT NULL DEFAULT 'bronze',  -- current highest zone
    quality_score FLOAT,
    metadata JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(content_hash)  -- deduplication
);

-- Section registry: structural units within documents
CREATE TABLE sections (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID REFERENCES documents(id) ON DELETE CASCADE,
    section_index INTEGER NOT NULL,
    heading TEXT,
    section_type TEXT,  -- 'paragraph', 'table', 'list', 'code', 'image_caption'
    content TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    token_count INTEGER,
    storage_path TEXT NOT NULL,  -- S3 key in silver zone
    metadata JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Chunk registry: embedding-ready units
CREATE TABLE chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID REFERENCES documents(id) ON DELETE CASCADE,
    section_id UUID REFERENCES sections(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    content TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    token_count INTEGER NOT NULL,
    overlap_prev INTEGER DEFAULT 0,  -- overlap tokens with previous chunk
    strategy TEXT NOT NULL,  -- 'fixed_token', 'section_aware', 'semantic'
    storage_path TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(content_hash, strategy)  -- no duplicate chunks per strategy
);

-- Artifact registry: gold-zone outputs
CREATE TABLE artifacts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    artifact_type TEXT NOT NULL,  -- 'embedding_batch', 'dataset', 'export'
    name TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    storage_path TEXT NOT NULL,
    format TEXT NOT NULL,  -- 'parquet', 'jsonl', 'duckdb'
    record_count INTEGER,
    config JSONB NOT NULL DEFAULT '{}',  -- generation parameters
    metadata JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Lineage tracking: edges between entities
CREATE TABLE lineage_edges (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_entity_type TEXT NOT NULL,  -- 'document', 'section', 'chunk', 'artifact'
    source_entity_id UUID NOT NULL,
    target_entity_type TEXT NOT NULL,
    target_entity_id UUID NOT NULL,
    relationship TEXT NOT NULL,  -- 'parsed_from', 'chunked_from', 'embedded_in', 'exported_to'
    pipeline_run_id UUID,
    transform_config JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_lineage_source ON lineage_edges(source_entity_type, source_entity_id);
CREATE INDEX idx_lineage_target ON lineage_edges(target_entity_type, target_entity_id);

-- Pipeline job tracking
CREATE TABLE pipeline_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    dagster_run_id TEXT,
    pipeline_name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',  -- pending, running, completed, failed
    config JSONB NOT NULL DEFAULT '{}',
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    error_message TEXT,
    stats JSONB DEFAULT '{}',  -- documents_processed, chunks_created, etc.
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

**Key design decisions:**
- `content_hash` on documents AND chunks for deduplication at both levels
- JSONB `metadata` columns for extensibility without schema migrations
- `lineage_edges` table as a generic graph enabling arbitrary relationship queries
- `zone` field on documents tracks progression through the pipeline
- UUID primary keys for distributed generation without coordination

### 4. Lineage Tracking Approach

**Chunk lineage chain:** Every chunk traces back to its source:

```
chunk -> section -> document -> source
  |         |          |          |
  +--- lineage_edges ---+--- lineage_edges ---+
```

**Query: "Where did this chunk come from?"**

```sql
WITH RECURSIVE lineage AS (
    SELECT source_entity_type, source_entity_id, relationship, 0 as depth
    FROM lineage_edges
    WHERE target_entity_type = 'chunk' AND target_entity_id = :chunk_id
    UNION ALL
    SELECT e.source_entity_type, e.source_entity_id, e.relationship, l.depth + 1
    FROM lineage_edges e
    JOIN lineage l ON e.target_entity_type = l.source_entity_type
                  AND e.target_entity_id = l.source_entity_id
    WHERE l.depth < 5
)
SELECT * FROM lineage ORDER BY depth;
```

**Lineage metadata includes:**
- Pipeline run ID (which Dagster run produced this edge)
- Transform config (chunking strategy, model used, parameters)
- Timestamps for temporal queries

### 5. Pipeline DAG Structure (Dagster Assets)

Use Dagster's **software-defined assets** model. Each zone transition is an asset or asset group.

**Asset hierarchy:**

```python
# klake/pipelines/assets/ingest.py
@dg.asset(group_name="bronze", key_prefix=["bronze"])
def crawled_documents(
    context: dg.AssetExecutionContext,
    plugin_manager: PluginManagerResource,
    storage: StorageResource,
    registry: RegistryResource,
) -> dg.MaterializeResult:
    """Crawl sources and store raw documents in bronze zone."""
    ...

@dg.asset(group_name="bronze", key_prefix=["bronze"])
def uploaded_documents(
    context: dg.AssetExecutionContext,
    storage: StorageResource,
    registry: RegistryResource,
) -> dg.MaterializeResult:
    """Process manually uploaded files into bronze zone."""
    ...

# klake/pipelines/assets/parse.py
@dg.asset(
    group_name="silver",
    key_prefix=["silver"],
    deps=[crawled_documents, uploaded_documents],
)
def parsed_documents(
    context: dg.AssetExecutionContext,
    plugin_manager: PluginManagerResource,
    storage: StorageResource,
    registry: RegistryResource,
) -> dg.MaterializeResult:
    """Parse raw documents into structured sections."""
    ...

# klake/pipelines/assets/chunk.py
@dg.asset(
    group_name="silver",
    key_prefix=["silver"],
    deps=[parsed_documents],
)
def document_chunks(
    context: dg.AssetExecutionContext,
    storage: StorageResource,
    registry: RegistryResource,
    config: ChunkingConfigResource,
) -> dg.MaterializeResult:
    """Chunk parsed sections into embedding-ready units."""
    ...

# klake/pipelines/assets/enrich.py
@dg.asset(
    group_name="gold",
    key_prefix=["gold"],
    deps=[document_chunks],
)
def enriched_chunks(
    context: dg.AssetExecutionContext,
    litellm: LiteLLMResource,
    registry: RegistryResource,
) -> dg.MaterializeResult:
    """Add LLM-generated metadata to chunks."""
    ...

@dg.asset(
    group_name="gold",
    key_prefix=["gold"],
    deps=[document_chunks],
)
def chunk_embeddings(
    context: dg.AssetExecutionContext,
    plugin_manager: PluginManagerResource,
    storage: StorageResource,
    registry: RegistryResource,
) -> dg.MaterializeResult:
    """Generate embeddings and index in vector store."""
    ...
```

**Why assets over ops/graphs:**
- Assets model "what data exists" rather than "what steps to run" - fits the zone architecture naturally
- Each asset corresponds to a data zone transition (bronze documents, silver chunks, gold embeddings)
- Dagster tracks staleness via `code_version` - if chunking logic changes, downstream assets know they need refresh
- IO managers handle storage abstraction per-environment (MinIO dev, S3 prod)
- Asset checks provide data quality gates between zones

**Asset checks for zone transitions:**

```python
@dg.asset_check(asset=parsed_documents, blocking=True)
def parsed_documents_have_sections(registry: RegistryResource):
    """Every parsed document must have at least one section."""
    count = registry.count_documents_without_sections()
    return dg.AssetCheckResult(
        passed=count == 0,
        metadata={"documents_without_sections": count}
    )
```

**Partitioning strategy:**
- Source-based partitions: Each source can be processed independently
- Time-based partitions for incremental crawls (daily/weekly)
- Enables backfills when parsing logic improves

### 6. Storage Abstraction Pattern

Abstract S3-compatible storage to work with both MinIO (dev) and AWS S3 (prod).

```python
# klake/storage/backend.py
from pydantic import BaseModel
import boto3
from botocore.config import Config

class StorageConfig(BaseModel):
    endpoint_url: str | None = None  # None = AWS S3, set for MinIO
    bucket: str = "klake-data"
    region: str = "us-east-1"
    access_key_id: str | None = None
    secret_access_key: str | None = None

class StorageBackend:
    """S3-compatible storage abstraction for all zones."""

    def __init__(self, config: StorageConfig):
        self._client = boto3.client(
            "s3",
            endpoint_url=config.endpoint_url,
            region_name=config.region,
            aws_access_key_id=config.access_key_id,
            aws_secret_access_key=config.secret_access_key,
        )
        self._bucket = config.bucket

    def put_object(self, zone: str, key: str, data: bytes, metadata: dict = None) -> str:
        """Write object to zone. Returns full S3 key."""
        full_key = f"{zone}/{key}"
        self._client.put_object(
            Bucket=self._bucket,
            Key=full_key,
            Body=data,
            Metadata=metadata or {},
        )
        return full_key

    def get_object(self, zone: str, key: str) -> bytes:
        """Read object from zone."""
        full_key = f"{zone}/{key}"
        response = self._client.get_object(Bucket=self._bucket, Key=full_key)
        return response["Body"].read()

    def exists(self, zone: str, key: str) -> bool:
        """Check if object exists (for idempotency)."""
        ...

    def list_objects(self, zone: str, prefix: str) -> list[str]:
        """List objects with prefix in zone."""
        ...
```

**Zone enforcement:**
- Bronze zone: `put_object` only, no `delete_object` or `overwrite`. Immutability enforced at application layer.
- Silver/Gold zones: Versioned paths prevent overwrites (`v{version}/` prefix).

**Dagster IO Manager integration:**

```python
class KlakeIOManager(dg.ConfigurableIOManager):
    storage: StorageBackend

    def handle_output(self, context, obj):
        zone = context.asset_key.path[0]  # key_prefix determines zone
        key = "/".join(context.asset_key.path[1:])
        self.storage.put_object(zone, key, serialize(obj))

    def load_input(self, context):
        zone = context.asset_key.path[0]
        key = "/".join(context.asset_key.path[1:])
        return deserialize(self.storage.get_object(zone, key))
```

### 7. API Layer Design (FastAPI)

**Router organization:**

```python
# klake/api/app.py
from fastapi import FastAPI
from klake.api.routers import sources, documents, pipelines, artifacts, health

app = FastAPI(title="Knowledge Lake API", version="0.1.0")
app.include_router(health.router, tags=["health"])
app.include_router(sources.router, prefix="/api/v1/sources", tags=["sources"])
app.include_router(documents.router, prefix="/api/v1/documents", tags=["documents"])
app.include_router(pipelines.router, prefix="/api/v1/pipelines", tags=["pipelines"])
app.include_router(artifacts.router, prefix="/api/v1/artifacts", tags=["artifacts"])
```

**Pipeline trigger pattern (FastAPI + Dagster):**

```python
# klake/api/routers/pipelines.py
from fastapi import APIRouter, BackgroundTasks
from dagster_graphql import DagsterGraphQLClient

router = APIRouter()

@router.post("/trigger/{pipeline_name}")
async def trigger_pipeline(
    pipeline_name: str,
    config: PipelineRunConfig,
    background_tasks: BackgroundTasks,
    dagster_client: DagsterGraphQLClient = Depends(get_dagster_client),
    registry: Registry = Depends(get_registry),
):
    """Trigger a pipeline run. Returns immediately with run ID."""
    run_id = registry.create_pipeline_run(pipeline_name, config)
    background_tasks.add_task(
        _submit_dagster_job, dagster_client, pipeline_name, config, run_id
    )
    return {"run_id": run_id, "status": "submitted"}

@router.get("/runs/{run_id}/status")
async def get_run_status(run_id: str, registry: Registry = Depends(get_registry)):
    """Poll pipeline run status."""
    return registry.get_pipeline_run(run_id)
```

**Key patterns:**
- FastAPI triggers Dagster runs via GraphQL client, does NOT orchestrate itself
- Background tasks only for lightweight submission, not for pipeline execution
- Status polling via registry (Dagster run status synced back)
- Dependency injection for all services (registry, storage, dagster client)

### 8. CLI Design (Typer)

**Hierarchical command structure:**

```
klake
  source
    add       -- Register a new source
    list      -- List all sources
    crawl     -- Trigger crawl for a source
    remove    -- Remove a source
  document
    list      -- List documents (with filters)
    show      -- Show document details + lineage
    upload    -- Upload a file manually
    reprocess -- Re-run pipeline on document
  pipeline
    run       -- Trigger a named pipeline
    status    -- Show pipeline run status
    list      -- List recent runs
  artifact
    list      -- List generated artifacts
    export    -- Export dataset to file
  config
    show      -- Display current config
    set       -- Set config value
  domain
    list      -- List available domain packs
    install   -- Install a domain pack
```

**Implementation pattern:**

```python
# klake/cli/app.py
import typer
from rich.console import Console
from klake.cli import source, document, pipeline, artifact, config, domain

app = typer.Typer(name="klake", help="Knowledge Lake Framework")
console = Console()

app.add_typer(source.app, name="source")
app.add_typer(document.app, name="document")
app.add_typer(pipeline.app, name="pipeline")
app.add_typer(artifact.app, name="artifact")
app.add_typer(config.app, name="config")
app.add_typer(domain.app, name="domain")

# klake/cli/source.py
app = typer.Typer(help="Manage data sources")

@app.command()
def add(
    name: str = typer.Argument(..., help="Source name"),
    url: str = typer.Option(..., help="Source URL"),
    source_type: str = typer.Option("web", help="Source type"),
):
    """Register a new source for crawling."""
    ...
```

### 9. Domain Pack / Plugin Loading

Domain packs are specialized plugin bundles that configure sources, schemas, and enrichment logic for a specific domain.

**Domain pack structure:**

```
klake-healthcare/
  pyproject.toml          # entry_points for klake
  klake_healthcare/
    __init__.py           # Plugin registration
    sources.py            # Pre-configured source seeds
    schemas.py            # Domain-specific metadata schemas
    enrichment.py         # Custom LLM prompts for healthcare
    quality.py            # Domain-specific quality rules
    config.yaml           # Default configuration
```

**Loading mechanism:**

```python
# Domain packs register via entry_points
[project.entry-points."klake.domain_packs"]
healthcare = "klake_healthcare:HealthcareDomainPack"

# Core discovers and loads them
class DomainPackManager:
    def __init__(self, plugin_manager: pluggy.PluginManager):
        self._packs: dict[str, DomainPack] = {}
        # Discover via entry_points
        for ep in importlib.metadata.entry_points(group="klake.domain_packs"):
            pack = ep.load()()
            self._packs[ep.name] = pack
            plugin_manager.register(pack)  # Register hooks
```

### 10. Configuration Management

Use pydantic-settings (BaseSettings) with layered sources.

**Priority order (highest wins):**
1. Environment variables (12-factor app compliance)
2. `.env` file (local overrides)
3. `klake.yaml` config file (project settings)
4. Default values in code

**Configuration structure:**

```python
# klake/config/settings.py
from pydantic_settings import BaseSettings
from pydantic import Field

class StorageSettings(BaseSettings):
    endpoint_url: str | None = None
    bucket: str = "klake-data"
    region: str = "us-east-1"
    access_key_id: str | None = None
    secret_access_key: str | None = None

    model_config = {"env_prefix": "KLAKE_STORAGE_"}

class DatabaseSettings(BaseSettings):
    url: str = "postgresql://localhost:5432/klake"
    pool_size: int = 5

    model_config = {"env_prefix": "KLAKE_DB_"}

class LLMSettings(BaseSettings):
    gateway_url: str = "http://localhost:4000"  # LiteLLM proxy
    cheap_model: str = "bedrock/anthropic.claude-3-haiku-20240307-v1:0"
    strong_model: str = "bedrock/anthropic.claude-sonnet-4-20250514"
    embedding_model: str = "bedrock/amazon.titan-embed-text-v2:0"
    max_retries: int = 3
    timeout: int = 60

    model_config = {"env_prefix": "KLAKE_LLM_"}

class PipelineSettings(BaseSettings):
    chunk_size_tokens: int = 512
    chunk_overlap_tokens: int = 64
    max_concurrent_crawls: int = 5
    rate_limit_seconds: float = 1.0
    batch_size: int = 100

    model_config = {"env_prefix": "KLAKE_PIPELINE_"}

class Settings(BaseSettings):
    storage: StorageSettings = StorageSettings()
    database: DatabaseSettings = DatabaseSettings()
    llm: LLMSettings = LLMSettings()
    pipeline: PipelineSettings = PipelineSettings()
    domain_packs: list[str] = []
    debug: bool = False

    model_config = {"env_prefix": "KLAKE_"}
```

**YAML config file (`klake.yaml`):**

```yaml
storage:
  endpoint_url: "http://localhost:9000"
  bucket: "klake-dev"

database:
  url: "postgresql://klake:klake@localhost:5432/klake"

llm:
  gateway_url: "http://localhost:4000"
  cheap_model: "bedrock/anthropic.claude-3-haiku-20240307-v1:0"

pipeline:
  chunk_size_tokens: 512
  max_concurrent_crawls: 3

domain_packs:
  - healthcare
```

### 11. Idempotent Pipeline Patterns

**Content hashing for deduplication:**

```python
import hashlib

def compute_content_hash(content: bytes) -> str:
    """SHA-256 hash for deduplication. Same content = same hash = skip."""
    return hashlib.sha256(content).hexdigest()

# In ingest pipeline:
def ingest_document(raw_content: bytes, source_id: str, registry: Registry, storage: StorageBackend):
    content_hash = compute_content_hash(raw_content)

    # Check if already ingested
    existing = registry.get_document_by_hash(content_hash)
    if existing:
        return existing  # Idempotent: same content already processed

    # New document - store and register
    doc_id = uuid4()
    storage_path = storage.put_object("bronze", f"{source_id}/{doc_id}/{content_hash}.bin", raw_content)
    return registry.create_document(doc_id, source_id, content_hash, storage_path)
```

**Resumable jobs:**
- Each pipeline stage checks registry status before processing
- Documents track `zone` field (bronze/silver/gold) - only process if not yet in target zone
- Failed documents marked `status='failed'` with error, skipped on retry, manually retriggerable
- Pipeline runs record progress in `pipeline_runs.stats` JSONB for resumption

**Dagster materialization metadata:**

```python
@dg.asset
def parsed_documents(...) -> dg.MaterializeResult:
    stats = {"processed": 0, "skipped": 0, "failed": 0}
    for doc in registry.get_documents(zone="bronze"):
        if registry.has_sections(doc.id):
            stats["skipped"] += 1
            continue  # Already parsed - idempotent
        try:
            sections = parse(doc)
            registry.store_sections(doc.id, sections)
            stats["processed"] += 1
        except Exception as e:
            registry.mark_failed(doc.id, str(e))
            stats["failed"] += 1

    return dg.MaterializeResult(metadata=stats)
```

## Patterns to Follow

### Pattern 1: Registry-First Design

**What:** Every mutation goes through the registry. Storage writes are paired with registry records.

**When:** Always. No orphaned files in S3, no registry entries without backing data.

**Example:**

```python
# CORRECT: atomic registry + storage
async def store_document(content: bytes, metadata: dict):
    content_hash = compute_content_hash(content)
    storage_path = storage.put_object("bronze", key, content)
    registry.create_document(content_hash=content_hash, storage_path=storage_path, **metadata)
    # If registry fails, storage has orphan - cleaned up by periodic job

# WRONG: storage without registry
async def store_document(content: bytes):
    storage.put_object("bronze", key, content)  # No lineage!
```

### Pattern 2: Resource Injection via Dagster

**What:** All external dependencies (storage, registry, LiteLLM, plugin manager) are Dagster resources injected into assets.

**When:** For all pipeline assets. Enables test mocking and environment switching.

```python
class RegistryResource(dg.ConfigurableResource):
    database_url: str

    def get_client(self) -> Registry:
        return Registry(self.database_url)

# In Definitions:
defs = dg.Definitions(
    assets=[crawled_documents, parsed_documents, ...],
    resources={
        "registry": RegistryResource(database_url=dg.EnvVar("KLAKE_DB_URL")),
        "storage": StorageResource(endpoint_url=dg.EnvVar("KLAKE_STORAGE_ENDPOINT")),
    }
)
```

### Pattern 3: Content Hash as Deduplication Key

**What:** SHA-256 of raw content determines identity. Same content = same document regardless of source.

**When:** At every zone boundary. Prevents reprocessing identical content.

### Pattern 4: Explicit Zone Boundaries

**What:** Data moves through zones only via defined pipeline assets. No direct zone-to-zone copies.

**When:** Always. Each zone transition is a traceable, auditable event with lineage.

## Anti-Patterns to Avoid

### Anti-Pattern 1: Monolithic Pipeline Functions

**What:** Single function that crawls, parses, chunks, and embeds in one go.

**Why bad:** Cannot resume from middle, no intermediate quality checks, no parallel processing of stages, violates zone architecture.

**Instead:** One Dagster asset per zone transition. Each asset reads from upstream zone, writes to target zone, records lineage.

### Anti-Pattern 2: IO Managers for Everything

**What:** Using Dagster IO managers to handle all storage reads/writes.

**Why bad:** IO managers assume data fits in memory and follows simple serialize/deserialize patterns. Document pipelines process thousands of documents that should NOT all be loaded at once.

**Instead:** Use `deps` for asset dependencies. Handle storage explicitly via the StorageBackend resource. IO managers only for small metadata objects if at all.

### Anti-Pattern 3: Direct Provider Calls

**What:** Importing `anthropic` or `openai` SDK directly in pipeline code.

**Why bad:** Vendor lock-in, no unified rate limiting, no cost tracking, no model aliasing.

**Instead:** ALL LLM calls through LiteLLM resource with task-based aliases (`cheap_model`, `strong_model`).

### Anti-Pattern 4: Schema-Per-Domain in Core

**What:** Adding healthcare-specific columns to core tables.

**Why bad:** Core becomes coupled to domain concerns. Adding a new domain requires core schema changes.

**Instead:** Domain-specific metadata goes in JSONB `metadata` columns. Domain packs define their own validation schemas applied at the application layer.

## Scalability Considerations

| Concern | Dev (single user) | Production (team) | Scale (1M+ docs) |
|---------|-------------------|-------------------|-------------------|
| Storage | MinIO single-node | AWS S3 | S3 with lifecycle policies |
| Database | PostgreSQL single | PostgreSQL with read replicas | Partitioned tables by source/date |
| Orchestration | Dagster single-process | Dagster with dagster-daemon | Dagster with K8s executor |
| Vector store | Qdrant single-node | Qdrant cluster | Qdrant sharded collections |
| LLM calls | Sequential, rate-limited | Batched, concurrent | Queue-based with backpressure |
| Chunking | In-process | Dagster parallelism | Distributed via Dagster K8s |

## Build Order Implications

Based on component dependencies, the recommended build order is:

```
Phase 1: Foundation (no dependencies)
  - Core Config (pydantic-settings)
  - Storage Abstraction (boto3 + zone logic)
  - Registry Schema (PostgreSQL + SQLAlchemy/asyncpg)
  - Plugin Manager skeleton (pluggy hookspecs)
  - Basic Dagster definitions structure

Phase 2: Ingest Pipeline (depends on Phase 1)
  - Crawler plugins (Crawl4AI hookimpl)
  - File upload handling
  - Bronze zone storage
  - Basic CLI (source add/list, document upload)
  - Basic API (source CRUD, upload endpoint)
  - Dagster ingest assets

Phase 3: Processing Pipeline (depends on Phase 2)
  - Parser plugins (Docling hookimpl)
  - Section extraction
  - Chunking strategies
  - Silver zone storage
  - Lineage edge recording
  - Pipeline status tracking

Phase 4: Enrichment + Export (depends on Phase 3)
  - LiteLLM integration resource
  - Metadata enrichment
  - Embedding generation
  - Vector store plugin (Qdrant)
  - Export formats (Parquet, JSONL)
  - Gold zone completion
  - Dataset generation

Phase 5: Domain Packs + Polish (depends on Phase 4)
  - Healthcare domain pack
  - Quality scoring
  - Domain-specific enrichment prompts
  - Source discovery (SearXNG)
  - Corpus curation
```

**Dependency rationale:**
- Config + Storage + Registry are the foundation everything else touches
- Plugin Manager must exist before any plugins can be implemented
- Ingest must work before you can parse (need documents in bronze)
- Parsing must work before chunking (need sections in silver)
- Chunks must exist before embeddings (need text units for vectors)
- Domain packs build on top of working core (customization layer)

## Sources

- Dagster official documentation: Software-Defined Assets, IO Managers, Resources, Asset Checks, Partitions, Pipes (docs.dagster.io) — fetched 2026-07-02
- FastAPI official documentation: Background Tasks, Dependency Injection (fastapi.tiangolo.com) — fetched 2026-07-02
- Typer official documentation: Subcommands and App Groups (typer.tiangolo.com) — fetched 2026-07-02
- pluggy official documentation: Hook Specifications, Plugin Manager, Entry Points (pluggy.readthedocs.io) — fetched 2026-07-02
- Databricks Medallion Architecture reference (databricks.com/glossary/medallion-architecture) — fetched 2026-07-02
- pydantic-settings documentation (pydantic-settings.readthedocs.io) — fetched 2026-07-02 (older version; BaseSettings patterns from training knowledge, marked MEDIUM confidence)
