"""
Typed pydantic-settings configuration source for Knowledge Lake (FOUND-02).

Single source of truth for all environment/config. No other module in this
codebase should call os.getenv() or read environment variables directly.

Usage:
    from knowledge_lake.config.settings import get_settings
    s = get_settings()
    print(s.database_url)

Environment variable pattern:
    Prefix:            KLAKE_
    Nested delimiter:  __
    Example:           KLAKE_STORAGE__ENDPOINT_URL → settings.storage.endpoint_url
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Annotated, Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class StorageSettings(BaseModel):
    """S3-compatible object storage configuration.

    This is a plain BaseModel (not BaseSettings) so it can be used as a nested
    model inside Settings without double-prefix resolution. Settings reads
    KLAKE_STORAGE__* env vars via env_nested_delimiter and passes the values in
    at construction time. (WR-02)
    """

    endpoint_url: str | None = None
    """S3-compatible endpoint. None = use AWS S3; set to MinIO URL for dev."""

    bucket: str = "klake-data"
    """Target bucket name."""

    region: str = "us-east-1"
    """AWS region (used for presigned URLs and AWS S3 path-style requests)."""

    access_key_id: str | None = None
    """AWS access key ID or MinIO root user. None = use instance/env credentials."""

    secret_access_key: str | None = None
    """AWS secret access key or MinIO root password. None = use instance credentials."""


class CrawlSettings(BaseModel):
    """Crawl-related configuration (INGEST-04, INGEST-09).

    Controls crawler behavior: depth, breadth, rate limiting, and scope.
    These are the global defaults; per-source overrides live in Source.config.
    """

    max_pages: int = 50
    """Maximum number of pages to crawl per job."""

    max_depth: int = 2
    """Maximum link-follow depth from the seed URL."""

    rate_limit_seconds: float = 1.0
    """Global default delay between requests to the same host (tier 3, D-12)."""

    same_domain_only: bool = True
    """If True, only follow links on the same registrable domain as the seed."""


class ParseSettings(BaseModel):
    """Parser chain and quality-scoring configuration (PARSE-01..05, D-01, D-02, D-04).

    Nested under Settings as settings.parse. Environment variable pattern:
    KLAKE_PARSE__CHAIN, KLAKE_PARSE__QUALITY_THRESHOLD, etc.
    """

    chain: list[str] = ["docling", "json_xml", "unstructured", "tika"]
    """Ordered parser names for the fallback chain (D-01, D-02)."""

    quality_threshold: float = 0.4
    """Minimum acceptable quality score before trying the next parser (D-01 gate)."""

    quality_gray_zone: tuple[float, float] = (0.3, 0.6)
    """Score band that triggers an optional LLM coherence spot-check (D-04)."""

    llm_spot_check: bool = True
    """Enable or disable the optional LLM quality spot-check in the gray zone."""

    max_file_bytes: int = 104857600
    """Hard file-size limit (100 MiB) before parsing — DoS guard (T-03-02)."""


class CleanSettings(BaseModel):
    """Cleaning and near-duplicate detection configuration (CLEAN-01..03).

    Nested under Settings as settings.clean. Environment variable pattern:
    KLAKE_CLEAN__MINHASH_NUM_PERM, etc.
    """

    minhash_num_perm: int = 128
    """MinHash permutations — DataTrove production default (CLEAN-03)."""

    minhash_threshold: float = 0.8
    """Jaccard similarity threshold for near-duplicate flagging (CLEAN-03)."""

    minhash_shingle_size: int = 5
    """Word-level shingle size for MinHash signatures (5-word shingles per research)."""


class ChunkSettings(BaseModel):
    """Token-aware chunking configuration (CHUNK-01..04, D-03).

    Nested under Settings as settings.chunk. Environment variable pattern:
    KLAKE_CHUNK__MAX_TOKENS, etc.
    """

    max_tokens: int = 512
    """Maximum tokens per chunk using cl100k_base encoding (D-03)."""

    overlap_tokens: int = 64
    """Token overlap between adjacent chunks from the same section."""

    tokenizer: str = "cl100k_base"
    """tiktoken encoding name (D-03 — not configurable per-model)."""

    heading_breadcrumb_depth: int = 2
    """Maximum heading levels to prepend as context prefix for retrieval."""


class EnrichSettings(BaseModel):
    """LLM-based metadata enrichment configuration (ENRICH-01..05).

    Nested under Settings as settings.enrich. Environment variable pattern:
    KLAKE_ENRICH__BUDGET_USD, KLAKE_ENRICH__PROMPT_VERSION, etc.
    """

    budget_usd: float = 5.0
    """Global spend cap in USD before the enrichment job halts gracefully
    (ENRICH-05, D-05)."""

    prompt_version: str = "v1"
    """Bumping this invalidates the enrichment cache (ENRICH-04, D-04)."""

    cache_enabled: bool = True
    """Enable or disable enrichment result caching keyed by prompt_version."""

    max_tokens: int = 4096
    """Maximum output tokens for the enrichment LLM call. Domain prompts with
    richer schemas (protocols, biomarkers, supplements) need more output budget."""

    model_alias: str = "cheap_model"
    """LiteLLM task alias for enrichment calls. Use 'strong_model' for domain
    prompts that require more output capacity or higher accuracy."""

    excerpt_chars: int = 4000
    """Bounds the cleaned-document excerpt sent to the LLM — cost and
    prompt-injection surface control (AI-SPEC Section 4)."""

    cheap_model_bedrock_id: str = "bedrock/us.anthropic.claude-haiku-4-5-20251001-v1:0"
    """Used ONLY by llm.pricing.bootstrap_llm_pricing()'s
    litellm.register_model() call so completion_cost() does not raise for
    this project's configured model IDs (RESEARCH.md Pitfall 1). NEVER
    passed as the `model=` argument to litellm.completion(), which always
    uses the "cheap_model" task alias — mirrors this default against
    infra/litellm/config.yaml's current cheap_model mapping."""

    strong_model_bedrock_id: str = "bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0"
    """Same rationale as cheap_model_bedrock_id, registered for
    forward-compatibility with Phase 5's strong_model/eval_model usage."""

    cheap_model_input_cost_per_token: float = 0.0000008
    """USD cost per input token for the cheap_model alias's registered price."""

    cheap_model_output_cost_per_token: float = 0.000004
    """USD cost per output token for the cheap_model alias's registered price."""

    strong_model_input_cost_per_token: float = 0.000003
    """USD cost per input token for the strong_model alias's registered price."""

    strong_model_output_cost_per_token: float = 0.000015
    """USD cost per output token for the strong_model alias's registered price."""

    fallback_cost_per_1k_input: float = 0.0005
    """Used only if completion_cost() itself raises even after registration."""

    fallback_cost_per_1k_output: float = 0.0015
    """Used only if completion_cost() itself raises even after registration."""


class CurateSettings(BaseModel):
    """DataTrove-style curation and composite quality scoring configuration (CURATE-01..03).

    Nested under Settings as settings.curate. Environment variable pattern:
    KLAKE_CURATE__GOPHER_MIN_DOC_WORDS, etc.
    """

    gopher_min_doc_words: int = 50
    """Minimum word count for GopherQualityFilter — FineWeb production default."""

    gopher_max_doc_words: int = 100_000
    """Maximum word count for GopherQualityFilter — FineWeb production default."""

    filter_no_terminal_punct: bool = False
    """If True, C4QualityFilter will reject lines without terminal punctuation."""

    filter_config_version: str = "v1"
    """Bumping this invalidates the curation cache (mirrors EnrichSettings.prompt_version)."""


class DatasetSettings(BaseModel):
    """Dataset-generation configuration (DATA-01..03).

    Nested under Settings as settings.dataset. Environment variable pattern:
    KLAKE_DATASET__BUDGET_USD, KLAKE_DATASET__PROMPT_VERSION, etc.
    """

    budget_usd: float = 5.0
    """Spend cap in USD before dataset generation halts gracefully (mirrors EnrichSettings)."""

    prompt_version: str = "v1"
    """Bumping this invalidates the dataset-generation cache (mirrors EnrichSettings)."""

    cache_enabled: bool = True
    """Enable or disable result caching keyed by prompt_version."""

    qa_excerpt_chars: int = 512
    """Defensive cap on chunk text sent to the LLM for QA generation — chunks are
    already CHUNK-01-bounded (512 tokens ≈ 2048 chars); this cap is a secondary guard."""

    instruction_excerpt_chars: int = 6000
    """Bounds the cleaned-document excerpt sent for instruction-tuning generation —
    larger than EnrichSettings.excerpt_chars=4000 because instruction-tuning benefits
    from more source context (AI-SPEC Section 4)."""


class ExportSettings(BaseModel):
    """Gold-zone export configuration (EXPORT-01..03).

    Nested under Settings as settings.export. Environment variable pattern:
    KLAKE_EXPORT__GOLD_PREFIX, KLAKE_EXPORT__MIN_QUALITY_SCORE_FOR_PRETRAIN, etc.
    """

    gold_prefix: str = "gold"
    """S3 key prefix for gold-zone exports (raw -> bronze -> silver -> gold)."""

    default_finetune_format: str = "openai_chat"
    """Fine-tuning JSONL format: 'openai_chat' (chat-messages shape) is the default."""

    min_quality_score_for_pretrain: float = 0.4
    """Minimum composite_quality_score for a curated_document to be included in the
    pretraining corpus export. Applied only at export time — curation itself stays
    annotate-only (CONTEXT.md Open Question #1 resolution, D-10)."""

    contamination_override_artifact_ids: list[str] = Field(default_factory=list)
    """cleaned_document artifact IDs for documented, accepted train/eval overlaps.
    Any cleaned_document ID listed here is excluded from the contamination check result
    — the operator takes explicit responsibility for the accepted overlap.
    This is the ONLY sanctioned bypass of the Section 6/7 hard-block guardrail
    (05-AI-SPEC.md Section 6: 'unless overlap is deliberate and documented')."""


class DomainSettings(BaseModel):
    """Domain pack configuration (DOMAIN-01).

    Nested under Settings as settings.domain. Environment variable pattern:
    KLAKE_DOMAIN__DOMAIN_NAME, KLAKE_DOMAIN__DOMAINS_ROOT.
    """

    domain_name: Optional[str] = None
    """Active domain pack name (e.g. 'healthcare'). None = no domain pack loaded.
    Set via KLAKE_DOMAIN__DOMAIN_NAME env var. (D-01, D-02)"""

    domains_root: str = "domains"
    """Path to the domains/ directory relative to the working directory,
    or an absolute path. Override via KLAKE_DOMAIN__DOMAINS_ROOT env var
    for containerised deployments (Pitfall 1)."""


class IndexSettings(BaseModel):
    """Vector index / alias configuration (INDEX-02, D-06).

    Nested under Settings as settings.index. Environment variable pattern:
    KLAKE_INDEX__COLLECTION_ALIAS, etc.
    """

    collection_alias: str = "klake_chunks"
    """The stable alias name; matches the existing collection: str =
    "klake_chunks" parameter already threaded through embed()/index()/search()."""

    keep_old_collections: bool = True
    """If True, reindex() never auto-drops the prior physical collection —
    an operator/CLI step drops it after confirming the swap (D-06)."""


class SearchSettings(BaseModel):
    """Hybrid-retrieval mode configuration (RETR-03, D-08).

    Nested under Settings as settings.search. Environment variable pattern:
    KLAKE_SEARCH__MODE=hybrid|dense|sparse

    Defaults to 'hybrid' per RETR-03 / D-08. The Literal constraint is the
    fail-closed input-validation boundary (T-10-02): unknown values raise a
    pydantic ValidationError at config load time, never reaching the store.
    """

    mode: Literal["hybrid", "dense", "sparse"] = "hybrid"
    """Retrieval mode.

    - 'hybrid'  — server-side RRF fusion of dense + sparse branches (default, D-08).
    - 'dense'   — ANN search on the named dense vector only (works on pre-migration
                  collections; no sparse vector required).
    - 'sparse'  — BM25-style search on the named sparse vector only (requires
                  named-vector collection after the hybrid reindex, D-05).

    Override via KLAKE_SEARCH__MODE env var (no custom parsing needed — the
    existing env_nested_delimiter='__' resolves it automatically).
    """


# Regex for swap key validation (ASVS V5 — alphanumeric + hyphen/underscore, 1-64 chars)
_SWAP_KEY_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]{0,63}$")


class Settings(BaseSettings):
    """Top-level application settings.

    All configuration is loaded from:
      1. Environment variables (highest precedence)
      2. .env file (if present)
      3. Defaults defined here

    Configuration keys use the KLAKE_ prefix. Nested models (storage) use
    the __ delimiter: KLAKE_STORAGE__ENDPOINT_URL maps to settings.storage.endpoint_url.
    """

    model_config = SettingsConfigDict(
        env_prefix="KLAKE_",
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Core service URLs ─────────────────────────────────────────────────────
    database_url: str = "postgresql+psycopg://klake:klake@localhost:5432/klake"
    """PostgreSQL connection string (SQLAlchemy async driver)."""

    qdrant_url: str = "http://localhost:6333"
    """Qdrant vector-store URL."""

    litellm_url: str = "http://localhost:4000"
    """LiteLLM proxy URL for all model calls."""

    litellm_api_key: str = "sk-local-noauth"
    """API key sent to the LiteLLM proxy. The litellm SDK requires a non-empty
    value for any api_base call even when the proxy has no LITELLM_MASTER_KEY
    configured (dev default) — this is a client-side SDK requirement, not
    proxy-side auth enforcement. Override via KLAKE_LITELLM_API_KEY when the
    proxy's LITELLM_MASTER_KEY is set."""

    searxng_url: str = "http://localhost:8888"
    """SearXNG meta-search engine URL for source discovery (INGEST-07)."""

    tika_server_url: str = "http://localhost:9998"
    """Apache Tika server URL for last-resort document parsing (PARSE-02).
    Override via KLAKE_TIKA_SERVER_URL env var. Mirrors the pattern used by
    qdrant_url, litellm_url, and searxng_url (WR-03)."""

    # ── Plugin swap keys ──────────────────────────────────────────────────────
    embedder: str = "local"
    """Embedder plugin name. 'local' = sentence-transformers; 'litellm' = gateway."""

    parser: str = "docling"
    """Parser plugin name. 'docling' = Docling PDF/document parser."""

    vectorstore: str = "qdrant"
    """Vector-store plugin name. 'qdrant' = Qdrant client."""

    crawler: str = "crawl4ai"
    """Crawler plugin name. 'crawl4ai' = Crawl4AI async crawler; 'scrapy' = Scrapy."""

    discovery: str = "searxng"
    """Discovery plugin name. 'searxng' = SearXNG meta-search engine (D-10)."""

    # ── Upload root ───────────────────────────────────────────────────────────
    upload_root: str = "/data/uploads"
    """Directory under which all uploaded file paths must reside.

    Override via KLAKE_UPLOAD_ROOT env var. The _safe_upload_path guard in
    api/app.py resolves this at request time so the running server always
    uses the current value (CR-004).
    """

    # ── Nested settings ───────────────────────────────────────────────────────
    storage: StorageSettings = Field(default_factory=StorageSettings)
    """S3-compatible object storage configuration."""

    crawl: CrawlSettings = Field(default_factory=CrawlSettings)
    """Crawl-related configuration (depth, rate limiting, scope)."""

    parse: ParseSettings = Field(default_factory=ParseSettings)
    """Parser chain and quality-scoring configuration (PARSE-01..05)."""

    clean: CleanSettings = Field(default_factory=CleanSettings)
    """Cleaning and near-duplicate detection configuration (CLEAN-01..03)."""

    chunk: ChunkSettings = Field(default_factory=ChunkSettings)
    """Token-aware chunking configuration (CHUNK-01..04)."""

    enrich: EnrichSettings = Field(default_factory=EnrichSettings)
    """LLM-based metadata enrichment configuration (ENRICH-01..05)."""

    curate: CurateSettings = Field(default_factory=CurateSettings)
    """DataTrove-style curation and composite quality scoring configuration (CURATE-01..03)."""

    dataset: DatasetSettings = Field(default_factory=DatasetSettings)
    """Dataset-generation configuration (DATA-01..03)."""

    index: IndexSettings = Field(default_factory=IndexSettings)
    """Vector index / alias configuration (INDEX-02)."""

    search: SearchSettings = Field(default_factory=SearchSettings)
    """Hybrid-retrieval mode configuration (RETR-03, D-08).

    Resolved via KLAKE_SEARCH__MODE=hybrid|dense|sparse (env_nested_delimiter='__').
    """

    export: ExportSettings = Field(default_factory=ExportSettings)
    """Gold-zone export configuration (EXPORT-01..03)."""

    domain: DomainSettings = Field(default_factory=DomainSettings)
    """Domain pack configuration (DOMAIN-01)."""

    # ── Validators ────────────────────────────────────────────────────────────

    @field_validator("crawler", "discovery", "embedder", "parser", "vectorstore", mode="after")
    @classmethod
    def _validate_swap_key(cls, v: str) -> str:
        """Validate swap keys against ASVS V5 (input validation).

        Swap keys must be alphanumeric (+ hyphen/underscore), starting with a
        letter, max 64 chars.  This prevents path traversal, injection, and
        arbitrary code-loading via malicious entry-point names.
        """
        if not _SWAP_KEY_RE.match(v):
            raise ValueError(
                f"Invalid swap key {v!r}: must match ^[a-zA-Z][a-zA-Z0-9_-]{{0,63}}$"
            )
        return v

    def __init__(self, **data: Any) -> None:
        # If _env_file is explicitly passed as None (e.g. in tests), suppress .env loading.
        # pydantic-settings accepts _env_file as an init-time override.
        super().__init__(**data)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached, validated Settings instance.

    Call this from anywhere in the application. Do not instantiate Settings
    directly — use this accessor so the app always reads from one validated source.
    """
    return Settings()
