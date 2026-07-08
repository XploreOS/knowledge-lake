# Phase 1: Foundation & End-to-End Spike - Research

**Researched:** 2026-07-02
**Domain:** Data-lake foundation — typed config, S3 storage abstraction, content-addressed immutable raw zone, PostgreSQL registry + lineage (Alembic), plugin protocol interfaces, and a one-document ingest→parse→chunk→embed→index→search spike
**Confidence:** HIGH (stack versions verified against PyPI today; patterns cross-referenced with the project's own `.planning/research/` docs and current official-source facts)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Spike shape & Dagster timing**
- **D-01:** Pipeline stages (ingest, parse, chunk, embed, index) are plain functions behind the plugin protocol interfaces first; they get wrapped as Dagster software-defined assets **before the phase closes**. Dagster ships in docker-compose from the first commit either way. Satisfies "Dagster from day 1" while avoiding Pitfall #1 (over-engineering Dagster before proving flow).
- **D-02:** CLI/API execute the pipeline via **direct in-process calls** in Phase 1. Switching them to submit Dagster runs is a later-phase change behind the same commands — the user-facing surface must not change when that swap happens.
- **D-03:** Ship a **scripted one-command demo** (e.g., `klake demo` or `make spike`) that ingests the test document, runs the fixed search query, and prints results with citations plus the lineage chain. It doubles as a smoke test for all later phases.
- **D-04:** `pipeline_version` on every artifact = **package version + git SHA** (e.g., `0.1.0+abc1234`); falls back to package version alone when not running from a git checkout.

**Spike test document**
- **D-05:** The spike document is **one real healthcare PDF**: an HHS/OCR HIPAA guidance PDF (e.g., "Summary of the HIPAA Security Rule") — US-federal public domain, stable hhs.gov URL, real headings and moderate structure. No synthetic fixture.
- **D-06:** It enters the raw zone via a **minimal URL-download path** (`klake ingest-url <url>` style): fetch from the public URL, record SHA256, MIME type, source URL, timestamp, and license metadata. Phase 2 broadens this into the full INGEST-02 command; do not build crawlers/uploads/discovery in Phase 1.
- **D-07:** Search success bar: a **fixed demo query** (e.g., "what are administrative safeguards") must return chunks from the right section of the document, each with score and citation (document, section path, page). The demo asserts citation fields are present and lineage resolves; relevance is human-checked once. No golden-query eval harness in Phase 1.

**Repo & package layout**
- **D-08:** **Grow-as-needed scaffolding.** Phase 1 creates only the subpackages the spike touches. The target `src/knowledge_lake/` structure is the map — each phase adds directories when it builds them. No empty placeholder modules.
- **D-09:** Naming: import package **`knowledge_lake`**, distribution **`knowledge-lake`**, CLI entry point **`klake`**.
- **D-10:** The pre-existing empty `configs/`, `services/`, `workspace/` dirs are **removed**; adopt: `infra/` for service configs (litellm/, postgres/, qdrant/, minio/, dagster/), `data/` kept but **gitignored** as local dev zone storage (MinIO is the real store), plus `scripts/`, `tests/`.
- **D-11:** Built-in plugin implementations (Docling parser, Qdrant store, embedders, crawlers) live **inside the core package**, registering via the same entry-point/hook mechanism third-party plugins would use. Split into separate packages only if a real need appears later.

**Dev models & lineage UX**
- **D-12:** LiteLLM dev alias mapping (in `infra/litellm/config.yaml`, never in code): `cheap_model` → Claude Haiku 4.5 on Bedrock, `strong_model` and `eval_model` → Claude Sonnet on Bedrock, `embedding_model` → Amazon Titan Text Embeddings V2 on Bedrock. Aliases are fixed; only the config maps them.
- **D-13:** Spike default embedding provider is **local sentence-transformers** (e.g., all-MiniLM or bge-small) so `docker compose up` + demo runs with **zero AWS credentials**. Bedrock embeddings via LiteLLM remain a pure config switch (ENRICH-06 configurability starts here).
- **D-14:** `klake lineage <artifact-id>` prints a **human-readable ancestry tree** by default (chunk → parsed doc → raw doc → source; each node shows ID, type, content hash, timestamp, pipeline version, storage URI), with `--json` for the full machine-readable graph. The API returns the JSON form.
- **D-15:** Registry entity IDs are **UUIDv7 with short type prefixes** (`src_`, `doc_`, `chk_`, `art_`, ...): self-describing in logs/CLI, time-sortable in PostgreSQL indexes. CLI accepts unambiguous ID prefixes for convenience.

### Claude's Discretion
Registry schema details (table/column design within the 17-registry blueprint), SQLAlchemy/psycopg specifics, Alembic layout, compose service wiring, exact local embedding model choice, chunking parameters for the spike, error handling and logging design — planner/executor decide, consistent with PROJECT.md constraints.

### Deferred Ideas (OUT OF SCOPE)
None — discussion stayed within phase scope. (Ingestion breadth = Phase 2, parsing breadth = Phase 3, enrichment/eval = Phase 4. Do not research eval frameworks.)
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| FOUND-01 | Full stack up via single `docker compose up` (PostgreSQL, Qdrant, MinIO, LiteLLM, Dagster, API) | Compose service topology + healthchecks (Architecture Patterns §Compose). LiteLLM proxy `/health/liveliness` is healthy without AWS creds; spike stays off its critical path (D-13). |
| FOUND-02 | Config from env/.env via typed pydantic-settings with validated defaults | pydantic-settings 2.14.2 nested `BaseSettings` + `SettingsConfigDict(env_nested_delimiter=...)` (Code Examples §Config). |
| FOUND-03 | Storage layer read/write to any S3-compatible backend through one abstraction | Single `boto3` S3 client, `endpoint_url` = MinIO dev / None = AWS prod (Don't Hand-Roll; Code Examples §Storage). |
| FOUND-04 | Raw zone content-addressed (SHA256), never modified/deleted; re-ingest identical = registry no-op | Content-addressed keys + registry hash-lookup no-op + `head_object` guard + MinIO object-lock/versioning (Architecture Patterns §Immutable Raw Zone). **Note: MinIO does not support `IfNoneMatch:'*'`; do not rely on S3 conditional-write wildcard.** |
| FOUND-05 | Registry stores sources, documents, artifacts, chunks, jobs, datasets, lineage events with stable IDs + hashes | Unified-artifact registry backbone + `sources` + `lineage_events`; create the full core table set in Alembic migration #1, populate only the spike's slice (Architecture Patterns §Registry). |
| FOUND-06 | Every artifact records source ID, parent artifact ID, content hash, timestamp, pipeline version, storage URI | These six are non-null columns on the artifact node; `pipeline_version` per D-04 (Code Examples §pipeline_version). |
| FOUND-07 | Query full lineage of any artifact back to raw source via CLI/API | Recursive CTE over self-referencing `parent_artifact_id`; `klake lineage` tree render + `--json` (D-14). |
| FOUND-08 | Parsers, crawlers, embedders, vector stores pluggable behind protocol interfaces, swappable via config | `typing.Protocol` contracts + config-keyed resolver over entry points (Architecture Patterns §Plugins). Swap = change a settings value. |
| FOUND-09 | Registry schema versioned with Alembic from the first table | Alembic + SQLAlchemy 2.0 async; migration #1 creates the whole core schema; no manual DDL ever (Pitfall #10). |
</phase_requirements>

## Project Constraints (from CLAUDE.md)

These carry the same authority as locked decisions. Research must not contradict them.

- **LLM Gateway:** all model calls through LiteLLM only — no direct provider SDK calls in business logic. (Spike embeds locally per D-13; the embedder *plugin* still exposes a `litellm` implementation as the config switch.)
- **Storage:** S3-compatible only (MinIO dev, AWS S3 prod) — no local filesystem as production store. (`data/` is gitignored dev scratch, not the store — D-10.)
- **Orchestration:** Dagster from day 1 — no ad-hoc script pipelines. (Compose service from commit 1; assets wrap the functions before phase close — D-01.)
- **Immutability:** raw zone never modified after write.
- **Lineage:** every artifact traces to source with stable IDs, content hashes, timestamps.
- **Models:** task-based aliases only (`cheap_model`, `strong_model`, `eval_model`, `embedding_model`) — no hardcoded provider IDs in code (D-12 maps them in `infra/litellm/config.yaml`).
- **Deterministic first:** regex/heuristic before LLM enrichment. (No LLM enrichment in Phase 1 at all.)
- **Pinned stack:** Python 3.12+, uv, Pydantic 2.13, Dagster 1.13.x, Docling 2.108.x, Qdrant client 1.18.x, MinIO/boto3, LiteLLM 1.90.x, PostgreSQL 16 + SQLAlchemy 2.0 + Alembic + psycopg3, FastAPI 0.139.x, Typer 0.26.x, sentence-transformers 5.6.x. Respect versions and the "alternatives considered / why not" rationale.

## Summary

Phase 1 is a **walking skeleton**: the thinnest working ingest→parse→chunk→embed→index→search path, standing on the foundation every later phase reuses (typed config, S3 abstraction, content-addressed immutable raw zone, PostgreSQL registry with Alembic-managed lineage, and plugin protocol interfaces). The heavy analysis was already done in `.planning/research/` (STACK/ARCHITECTURE/PITFALLS/SUMMARY) and the versions there are re-verified current below. This document narrows that to Phase 1's exact slice and resolves the decisions the planner must make.

**Sequence that respects Pitfall #1 (do not over-build Dagster first):** (1) scaffold `uv` project + compose stack; (2) config + storage + registry/Alembic foundation; (3) plain-function pipeline behind `Protocol` plugins wired by `klake demo` in-process (D-01/D-02); (4) prove the one document flows and lineage resolves; (5) *then* wrap the same functions as Dagster assets and confirm they materialize from the Dagster UI. The demo script (D-03) is the phase's executable acceptance test and the smoke test all later phases inherit.

Two facts changed since generic training knowledge and shape the plan: **(a)** MinIO does **not** implement the S3 `If-None-Match: '*'` conditional-write wildcard, so "refuse overwrite" must be enforced by content-addressing + a registry hash no-op + a `head_object` existence guard + MinIO object-lock/versioning + a delete-denying bucket policy — not by the S3 conditional-write feature. **(b)** `uuid.uuid7` is stdlib only from **Python 3.14**; on 3.12 use the Rust-backed `uuid-utils` behind a one-line helper so the switch to stdlib is trivial later.

**Primary recommendation:** Build in the order above; model the registry as a **single self-referencing `artifacts` node table** (+ `sources` + `lineage_events`) so FOUND-06's "parent artifact ID" and the D-14 ancestry tree are a one-table recursive CTE; enforce raw-zone immutability with content-addressed keys + registry no-op + object-lock, never with S3 wildcard conditional writes; define plugins as `typing.Protocol` contracts resolved by a config value over entry points.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Typed configuration | Core library (`knowledge_lake.config`) | — | pydantic-settings loads once at process start; injected everywhere, no env reads scattered in code |
| Object persistence (all zones) | Storage abstraction (boto3) → MinIO/S3 | — | One S3 client; zone is a key prefix; bronze/raw is immutable |
| Metadata + lineage of record | PostgreSQL registry | Core library repo layer | Registry is the source of truth; storage holds bytes, DB holds identity/lineage |
| Raw-zone immutability enforcement | Application (content-addressing + registry no-op) | MinIO (object-lock/versioning, delete-deny policy) | App layer makes overwrite impossible by construction; MinIO adds defense-in-depth |
| Parse / embed / vector index | Plugin implementations behind Protocols | LiteLLM (embedding config switch only) | Swappable per FOUND-08; spike uses in-package built-ins (Docling, local ST, Qdrant) |
| Pipeline execution (Phase 1) | Core functions called in-process by CLI/API | Dagster assets (wrap same funcs before close) | D-01/D-02: prove flow first, orchestrate second; user surface unchanged when swapped |
| Semantic search | Qdrant (via VectorStore plugin) | — | Dense vectors, cosine; payload carries citation fields |
| User surface | CLI (Typer `klake`) + API (FastAPI) | — | Thin subset of the full command/endpoint lists; grows each phase |
| Model gateway | LiteLLM proxy (compose service) | — | Up & healthy for FOUND-01; off the spike's critical path (local embeddings, D-13) |

## Standard Stack

### Core (Phase 1 installs these)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python | 3.12.3 (present) | Runtime | Pinned; note stdlib `uuid.uuid7` is 3.14+ (use `uuid-utils` now) |
| uv | 0.11.26 (present) | Packaging + lockfile | Pinned; `uv init`/`uv lock`/`uv run` |
| pydantic | 2.13.4 | Data models | Pinned; underpins settings + API schemas |
| pydantic-settings | 2.14.2 | Typed env/.env config (FOUND-02) | Split-out settings package; nested `BaseSettings`, `env_nested_delimiter` |
| SQLAlchemy | 2.0.51 | ORM/registry (FOUND-05) | Pinned; 2.0 typed style + async engine |
| Alembic | 1.18.5 | Migrations from table 1 (FOUND-09) | Pairs with SQLAlchemy; autogenerate |
| psycopg (v3) | 3.3.4 | PostgreSQL driver | Pinned; async-capable; `postgresql+psycopg://` |
| boto3 | 1.43.39 | S3 abstraction (FOUND-03) | One client for MinIO + AWS |
| docling | 2.108.0 | PDF parse (built-in parser plugin) | Pinned; DoclingDocument gives headings/pages for citations (D-07) |
| sentence-transformers | 5.6.0 | Local embeddings (default, D-13) | Pinned; zero AWS creds; 384-dim MiniLM/bge-small |
| qdrant-client | 1.18.0 | Vector index + search (built-in store plugin) | Pinned; single container; cosine + payload filter |
| litellm | 1.90.2 | LLM gateway service (FOUND-01) | Pinned; proxy up/healthy; embedder config switch |
| dagster + dagster-webserver | 1.13.11 | Orchestration service + asset wrap (D-01) | Pinned; assets wrap the pipeline functions before close |
| fastapi | 0.139.0 | REST surface (FOUND-07 API) | Pinned; OpenAPI, pydantic |
| uvicorn | 0.49.0 | ASGI server | Pinned; runs the API container |
| typer | 0.26.8 | `klake` CLI (FOUND-07 CLI, D-14) | Pinned; rich lineage-tree output |
| uuid-utils | 0.16.2 | UUIDv7 generation on 3.12 (D-15) | Rust-backed, maintained; wrap behind helper, swap to stdlib on 3.14 |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| structlog | 26.1.0 | Structured logging | All app logging from commit 1 |
| tenacity | 9.1.4 | Retry (URL download, S3, Qdrant) | The one URL fetch (D-06) + external calls |
| httpx | 0.28.1 | Async HTTP | URL-download path (D-06) |
| xxhash | 3.8.0 | Fast non-crypto hashing | Cache/dedup keys where crypto strength not needed (raw-zone identity uses **SHA256**, not xxhash) |
| orjson | 3.11.9 | Fast JSON | JSON storage of parsed artifacts, API responses |
| pluggy | 1.6.0 | (Optional) hook dispatch | Only if you prefer pluggy over a plain resolver; **not required** for Phase 1 (see §Plugins) |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `uuid-utils` (UUIDv7) | `uuid6` (2025.0.1, pure-Python) | Pure-Python, no build step; slower. `uuid-utils` is Rust-backed and broadly used. Either is legitimate; both `[ASSUMED]` until confirmed against official/Context7. Stdlib `uuid.uuid7` supersedes both at Py 3.14. |
| `typing.Protocol` + config resolver | `pluggy` hookspecs (in ARCHITECTURE.md) | pluggy shines for *multi-implementation dispatch / fallback chains* (Phase 3 parser fallback). For Phase 1's single-impl "swap by config," a plain resolver is less machinery and easier to type-check. Keep pluggy as the Phase 3 evolution; the seam is identical. |
| LiteLLM proxy (compose service) | LiteLLM as library | FOUND-01 explicitly lists LiteLLM as a stack service that must come up healthy → run the proxy. Library mode is a later option; proxy also gives central cost/rate control for Phases 4+. |
| Unified `artifacts` node table | Separate `documents`/`sections`/`chunks` tables (ARCHITECTURE.md) | Separate tables read more "domain-natural" but make the ancestry tree a multi-table union. Unified self-referencing node makes FOUND-07 a single recursive CTE and matches "every artifact records parent artifact ID" (FOUND-06). Recommended; see §Registry. |

**Installation (Phase 1 subset):**
```bash
uv init --package --name knowledge-lake        # import pkg knowledge_lake, dist knowledge-lake (D-09)
uv add pydantic pydantic-settings sqlalchemy alembic "psycopg[binary]" boto3 \
       docling sentence-transformers qdrant-client litellm \
       dagster dagster-webserver fastapi uvicorn typer uuid-utils \
       structlog tenacity httpx xxhash orjson
uv add --dev pytest pytest-asyncio pytest-cov ruff mypy
```

**Version verification:** every package above was fetched from the PyPI JSON API on 2026-07-02 (version + upload date + repo). All match the pinned versions in `.planning/research/STACK.md`. See §Package Legitimacy Audit.

## Package Legitimacy Audit

All Phase 1 packages verified against the PyPI JSON API (`https://pypi.org/pypi/<pkg>/json`) on 2026-07-02, confirming version, upload date, and source repository. Every one resolves to a well-known, high-download project with an established source repo. **Provenance note:** versions originate from `.planning/research/STACK.md` (project research) and were re-confirmed on the registry today; they are treated as **verified-current**. The two UUIDv7 helper libraries were discovered during this session and are tagged `[ASSUMED]` pending confirmation against official docs/Context7 (registry existence alone does not confer VERIFIED).

| Package | Registry | Released | Source Repo | Verdict | Disposition |
|---------|----------|----------|-------------|---------|-------------|
| pydantic-settings 2.14.2 | PyPI | 2026-06-19 | github.com/pydantic/pydantic-settings | OK | Approved |
| pluggy 1.6.0 | PyPI | 2025-05-15 | github.com/pytest-dev/pluggy | OK | Approved (optional) |
| uuid-utils 0.16.2 | PyPI | 2026-06-18 | github.com/aminalaee/uuid-utils | OK | Approved — `[ASSUMED]`, confirm before install |
| uuid6 2025.0.1 | PyPI | — | github.com/oittaa/uuid6-python | OK | Alternative — `[ASSUMED]` |
| dagster 1.13.11 | PyPI | 2026-06-25 | dagster.io / github.com/dagster-io/dagster | OK | Approved |
| docling 2.108.0 | PyPI | 2026-07-01 | github.com/docling-project/docling | OK | Approved |
| qdrant-client 1.18.0 | PyPI | 2026-05-11 | github.com/qdrant/qdrant-client | OK | Approved |
| sentence-transformers 5.6.0 | PyPI | 2026-06-16 | sbert.net / github.com/UKPLab/sentence-transformers | OK | Approved |
| SQLAlchemy 2.0.51 | PyPI | 2026-06-15 | sqlalchemy.org | OK | Approved |
| alembic 1.18.5 | PyPI | 2026-06-25 | github.com/sqlalchemy/alembic | OK | Approved |
| psycopg 3.3.4 | PyPI | 2026-05-01 | psycopg.org | OK | Approved |
| boto3 1.43.39 | PyPI | 2026-07-01 | github.com/boto/boto3 | OK | Approved |
| fastapi 0.139.0 | PyPI | 2026-07-01 | github.com/fastapi/fastapi | OK | Approved |
| typer 0.26.8 | PyPI | 2026-06-26 | github.com/fastapi/typer | OK | Approved |
| uvicorn 0.49.0 | PyPI | 2026-06-03 | github.com/Kludex/uvicorn | OK | Approved |
| pydantic 2.13.4 | PyPI | 2026-05-06 | github.com/pydantic/pydantic | OK | Approved |
| litellm 1.90.2 | PyPI | 2026-07-01 | litellm.ai / github.com/BerriAI/litellm | OK | Approved |
| structlog 26.1.0 | PyPI | 2026-06-06 | github.com/hynek/structlog | OK | Approved |
| tenacity 9.1.4 | PyPI | 2026-02-07 | github.com/jd/tenacity | OK | Approved |
| httpx 0.28.1 | PyPI | 2024-12-06 | github.com/encode/httpx | OK | Approved |
| xxhash 3.8.0 | PyPI | 2026-06-27 | github.com/ifduyue/python-xxhash | OK | Approved |
| orjson 3.11.9 | PyPI | 2026-05-06 | github.com/ijl/orjson | OK | Approved |

**Packages removed due to [SLOP] verdict:** none.
**Packages flagged as suspicious [SUS]:** none.
**Note:** `uuid-utils`/`uuid6` were surfaced this session — planner should keep them `[ASSUMED]` and confirm the chosen one against official docs before pinning. `structlog` here (26.1.0) is CalVer; STACK.md said "latest" — pin `>=26,<27`.

## Architecture Patterns

### System Architecture Diagram

```
                 operator
                    |
        +-----------+-----------+
        |                       |
   klake CLI (Typer)      FastAPI (uvicorn)
        |  D-02: direct in-process calls   |
        +-----------+-----------+
                    |
             pipeline functions           <-- plain funcs behind Protocols (D-01)
   ingest --> parse --> chunk --> embed --> index --> search
     |          |         |         |         |         |
     |     ParserPlugin   |   EmbedderPlugin  VectorStorePlugin
     |     (Docling)      |   (local ST)      (Qdrant)          [FOUND-08]
     |                    |
     v                    v
 Storage abstraction (boto3, one client)         Registry (PostgreSQL)
   raw/ (immutable, SHA256 key) ---------------->  sources, artifacts (self-ref
   silver/ parsed+chunks                           parent_artifact_id), lineage_events
        |                                                  ^
        +--- every write pairs bytes(S3) + node(DB) -------+   [Pattern: Registry-First]

 (before phase close, D-01)  the same pipeline functions are wrapped as
 Dagster assets  --->  Dagster webserver+daemon (compose) materialize from UI

 Compose stack [FOUND-01]:  postgres | minio | qdrant | litellm | dagster(web+daemon) | api
 LiteLLM up & healthy but OFF the spike path (local embeddings, zero AWS creds) [D-13]
```

Data flow to trace for the acceptance test: `klake demo` → download HHS PDF (httpx) → SHA256 → raw-zone put (content-addressed) + `documents`/raw artifact node → Docling parse → parsed artifact (silver) → section-aware chunks → local ST embeddings → Qdrant upsert with citation payload → fixed query embed → Qdrant search → results with score + citation → `klake lineage <chunk-id>` resolves chunk→parsed→raw→source.

### Recommended Project Structure (grow-as-needed, D-08/D-10)

Create only what the spike touches; this is the slice of the target map:

```
knowledge-lake/
├── pyproject.toml            # uv; [project.scripts] klake = "knowledge_lake.cli.app:app"
├── uv.lock
├── docker-compose.yml        # postgres, minio, qdrant, litellm, dagster(web+daemon), api  [FOUND-01]
├── .env.example              # KLAKE_* vars (never commit real .env)
├── alembic.ini
├── Makefile / scripts/       # `make spike` / demo entrypoint (D-03)
├── infra/                    # service configs (D-10)
│   ├── litellm/config.yaml   # alias→Bedrock map (D-12), no creds needed to boot
│   ├── postgres/  minio/  qdrant/  dagster/
├── data/                     # gitignored local dev scratch (MinIO is the store) (D-10)
├── src/knowledge_lake/
│   ├── config/settings.py    # pydantic-settings (FOUND-02)
│   ├── ids.py                # UUIDv7 + type-prefix helper (D-15)
│   ├── version.py            # pipeline_version = pkg version + git SHA (D-04)
│   ├── storage/s3.py         # boto3 abstraction + immutable raw zone (FOUND-03/04)
│   ├── registry/             # SQLAlchemy models + repo; alembic/ env + versions (FOUND-05/09)
│   ├── plugins/
│   │   ├── protocols.py      # Parser/Embedder/VectorStore Protocols (FOUND-08)
│   │   ├── resolver.py       # config-keyed resolution over entry points (D-11)
│   │   └── builtin/          # docling_parser.py, st_embedder.py, qdrant_store.py
│   ├── pipeline/             # ingest/parse/chunk/embed/index/search plain funcs (D-01)
│   ├── lineage.py            # recursive-CTE ancestry (FOUND-07, D-14)
│   ├── dagster_defs/         # assets wrapping pipeline funcs (added before close, D-01)
│   ├── cli/app.py            # Typer: ingest-url, search, lineage, demo (thin subset)
│   └── api/app.py            # FastAPI: health, search, lineage endpoints (thin subset)
└── tests/                    # unit + one integration/smoke (the demo)
```

### Pattern 1: Content-Addressed Immutable Raw Zone (FOUND-04)

**What:** Raw-zone object key is derived from the SHA256 of the bytes; identity == content. Same content → same key → natural dedup. Different content → different key → an overwrite is structurally impossible.

**Enforcement layers (do all four — belt and braces):**
1. **Content-addressed key:** `raw/{source_id}/{sha256}.{ext}`. Compute SHA256 on the downloaded bytes.
2. **Registry no-op:** before writing, look up the hash in the registry. If present, return the existing artifact — *re-ingesting identical content is a registry-level no-op* (FOUND-04 verbatim). No S3 write, no new node.
3. **`head_object` guard:** if the hash is new but the key already exists (should not happen for SHA256), refuse the write and raise — never `put` over an existing raw key.
4. **Bucket-level WORM:** enable **versioning + object lock** (GOVERNANCE/COMPLIANCE retention) on the raw bucket at creation, and attach a bucket policy denying `s3:DeleteObject` for the app role. MinIO supports object locking (requires versioning enabled at bucket creation).

**Do NOT** rely on the S3 `PutObject` `If-None-Match: '*'` conditional-write feature for portability: AWS S3 supports the `*` wildcard, but **MinIO does not** — MinIO expects an exact ETag and rejects `*` (minio/minio#20346). Since dev runs on MinIO, the wildcard path would behave differently dev vs prod. Content-addressing + registry no-op + object-lock is backend-portable and is the enforcement of record.

**Warning sign:** any code path that calls `put_object` into `raw/` without first checking the registry by hash, or any use of `delete_object`/overwrite on the raw prefix.

### Pattern 2: Plugin Protocols + Config-Driven Resolution (FOUND-08, D-11)

**What:** Each swappable tool is a `typing.Protocol` (structural contract). Concrete built-ins live in `plugins/builtin/` and register under entry-point groups (`knowledge_lake.parsers`, `.embedders`, `.vectorstores`). A resolver picks the implementation named in config.

**When to use:** For the parser, embedder, and vector store the spike exercises. Swapping = changing a settings value (e.g., `KLAKE_EMBEDDER=litellm`), no core edits — exactly FOUND-08.

**Why config-resolver over pluggy for Phase 1:** the requirement is single-implementation *swap by configuration*, not multi-implementation dispatch. A dict/entry-point resolver is fully typed and minimal. pluggy (already available) is the right tool when Phase 3 needs *fallback chains* (Docling → Unstructured → Tika with `firstresult`); adopt it there behind the same Protocols. This is a discretion area — flagged for the planner; recommendation is the plain resolver now.

```python
# plugins/protocols.py
from typing import Protocol, runtime_checkable

@runtime_checkable
class EmbedderPlugin(Protocol):
    name: str
    dim: int
    def embed(self, texts: list[str]) -> list[list[float]]: ...

@runtime_checkable
class ParserPlugin(Protocol):
    def can_parse(self, mime_type: str) -> bool: ...
    def parse(self, raw: bytes, mime_type: str) -> "ParsedDoc": ...   # headings + page refs

@runtime_checkable
class VectorStorePlugin(Protocol):
    def ensure_collection(self, name: str, dim: int, distance: str = "Cosine") -> None: ...
    def upsert(self, collection: str, points: list["VectorPoint"]) -> None: ...
    def search(self, collection: str, query: list[float], top_k: int) -> list["Hit"]: ...
```
```python
# plugins/resolver.py
from importlib.metadata import entry_points
def resolve(group: str, name: str):
    for ep in entry_points(group=group):
        if ep.name == name:
            return ep.load()()
    raise LookupError(f"No plugin {name!r} in group {group!r}")
# built-ins registered in pyproject: [project.entry-points."knowledge_lake.embedders"] local = "..."
```

### Pattern 3: Registry-First Writes + Unified Artifact Lineage Node (FOUND-05/06/07)

**What:** Every byte written to storage is paired with a registry node in the same logical operation (write bytes → write node; on node failure the orphan is swept later). Model the lineage backbone as **one self-referencing `artifacts` table** whose rows are raw-document, parsed-document, and chunk nodes.

**Recommended core schema (Alembic migration #1 — create the full set, populate the spike's slice):**

```
sources(id PK 'src_…', name, source_type, url, license_type, license_url,
        robots_checked bool, config jsonb, created_at)

artifacts(                                   -- the lineage backbone
        id PK 'art_'/'doc_'/'chk_'…,         -- type-prefixed UUIDv7 (D-15)
        source_id FK -> sources,             -- FOUND-06
        parent_artifact_id FK -> artifacts,  -- self-ref; NULL for raw  FOUND-06/07
        artifact_type text,                  -- raw_document | parsed_document | chunk
        content_hash text NOT NULL,          -- SHA256                    FOUND-06
        pipeline_version text NOT NULL,      -- pkg+git SHA (D-04)        FOUND-06
        storage_uri text,                    -- s3://bucket/zone/key      FOUND-06
        mime_type, page_ref int, section_path text,  -- citation (D-07/D-14)
        metadata jsonb DEFAULT '{}',
        created_at timestamptz NOT NULL DEFAULT now(),  -- FOUND-06
        UNIQUE(content_hash, artifact_type))            -- dedup / no-op

lineage_events(id, artifact_id FK, parent_artifact_id FK, relationship,
        pipeline_version, created_at)        -- explicit edge log (FOUND-05 "lineage events")

-- created empty in migration #1 to satisfy FOUND-05's enumerated set,
-- exercised in later phases:  jobs(...)   datasets(...)
```

FOUND-05 literally enumerates "sources, documents, artifacts, chunks, jobs, datasets, lineage events." Reconciliation: the unified `artifacts` node covers *documents + artifacts + chunks* (distinguished by `artifact_type`); expose `documents`/`chunks` as SQL views if a named surface is wanted. Create `jobs` and `datasets` as empty tables in migration #1 so "Alembic from the first table" covers the whole core schema and no later migration has to retrofit them. This is a discretion call (schema design) — the alternative (separate `documents`/`sections`/`chunks` tables from ARCHITECTURE.md) is valid but makes FOUND-07 a multi-table union instead of one recursive CTE.

**Lineage query (FOUND-07, powers D-14 tree):** recursive CTE walking `parent_artifact_id` up to `sources`. Chunk → parsed doc → raw doc → source in one query; render as a tree by default, `--json` for the graph.

### Pattern 4: Prove-Then-Orchestrate (D-01/D-02, Pitfall #1)

Pipeline stages are plain functions first, wired by `klake demo`/CLI in-process. Only after the one document demonstrably flows and lineage resolves do you add `dagster_defs/` assets that *call the same functions*. Dagster webserver+daemon run in compose from commit 1 (FOUND-01) but do not drive the spike until the wrap step. When later phases switch CLI/API to submit Dagster runs, command names and outputs stay identical (D-02).

### Anti-Patterns to Avoid
- **Building the Dagster asset graph before a document flows** (Pitfall #1) — the single biggest Phase-1 trap. Functions first, assets second.
- **`put_object` into `raw/` without a registry hash check** — breaks FOUND-04 idempotency/immutability.
- **S3 `If-None-Match:'*'` as the immutability mechanism** — silently diverges MinIO (dev) vs S3 (prod).
- **Reading env vars anywhere but `config/settings.py`** — defeats FOUND-02's single typed source.
- **Direct provider SDK calls / hardcoded model IDs** — violates the LiteLLM-only + task-alias constraints (even though the spike embeds locally, the embedder's `litellm` impl must go through the gateway).
- **Manual `ALTER TABLE` / `create_all()` instead of Alembic** — violates FOUND-09 (Pitfall #10).
- **Over-normalized schema** (Pitfall #8) — keep the core to the node table + sources + lineage_events + JSONB; do not spawn a table per attribute.
- **Dagster IO managers for object bytes** (Pitfall #7) — use `deps` + explicit storage calls; IO managers assume in-memory objects.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Typed layered config | Custom env parser / `os.getenv` sprinkles | pydantic-settings 2.14.2 | Validation, nesting, `.env`, precedence for free (FOUND-02) |
| S3 access for MinIO + AWS | Two clients / raw HTTP | single `boto3` client, `endpoint_url` toggle | MinIO is S3-compatible; one code path (FOUND-03) |
| Schema migrations | Hand-written SQL / `Base.metadata.create_all` | Alembic 1.18.5 | Versioned, reversible, from table 1 (FOUND-09, Pitfall #10) |
| Time-sortable IDs | Custom counter / random+timestamp | `uuid-utils` UUIDv7 + prefix helper | RFC 9562, index-friendly, self-describing (D-15) |
| PDF layout/heading/page extraction | Regex over `pdftotext` | Docling 2.108.0 | Reading order, headings, page refs → citations (D-07) |
| Embeddings | Custom model code | sentence-transformers (local) / LiteLLM (switch) | MTEB models off-the-shelf; zero creds default (D-13) |
| Vector search + filtering | pgvector hand-roll / brute force | qdrant-client 1.18.0 | Cosine + payload filter + upsert dedup |
| Lineage graph store | Bespoke graph tables | self-ref `artifacts` + recursive CTE | One-table ancestry query (FOUND-07) |
| Content hashing | Custom digest | `hashlib.sha256` (stdlib) for raw identity | SHA256 is the addressing scheme (FOUND-04); `xxhash` only for non-crypto caches |
| Retry/backoff | Hand loops | tenacity 9.1.4 | URL fetch + S3 + Qdrant resilience |

**Key insight:** Phase 1 is composition, not invention — the framework's value is lineage + tool-agnosticism, so every stage must be a thin adapter over a mature tool behind a Protocol. The only genuinely bespoke code is the registry/lineage model and the immutability enforcement.

## Runtime State Inventory

Not a rename/refactor/migration phase — greenfield. **None applicable.** The only pre-existing state is four empty directories (`configs/`, `services/`, `workspace/`, `data/`); per D-10 the first three are removed and `data/` becomes gitignored dev scratch. No stored data, live-service config, OS-registered state, secrets, or build artifacts exist yet.

## Common Pitfalls

### Pitfall 1: Over-engineering Dagster before proving end-to-end flow
**What goes wrong:** Elaborate asset graphs/IO managers built before one document has flowed; when real input hits, the shapes are wrong and the orchestration is reworked.
**Why:** Dagster's asset model + "Dagster from day 1" tempt a full graph up front.
**How to avoid:** D-01/D-02 — plain functions + `klake demo` first; wrap as assets only after the demo passes; use `deps`, not IO managers.
**Warning signs:** More Dagster definitions than passing integration tests.

### Pitfall 6: Mutable raw zone / missing content hashing
**What goes wrong:** Re-ingest overwrites the original; dedup fails; lineage breaks.
**How to avoid:** Pattern 1 — content-addressed keys + registry no-op + `head_object` guard + object-lock + delete-deny policy. Never `IfNoneMatch:'*'` (MinIO gap).
**Warning signs:** A raw `put` with no prior hash lookup; any `delete_object` on `raw/`.

### Pitfall 8: Registry over-normalization
**What goes wrong:** 5-table JOINs for a simple status lookup.
**How to avoid:** Core = `sources` + unified `artifacts` node + `lineage_events` + JSONB metadata; index `content_hash`, `source_id`, `parent_artifact_id`, `created_at`. Normalize only under proven contention.
**Warning signs:** A new table per attribute; simple queries needing >2 JOINs.

### Pitfall 10: Schema evolution without migrations
**How to avoid:** Alembic from migration #1; new columns NULLABLE/defaulted; never manual DDL; store schema version. (FOUND-09.)

### Pitfall 7: Dagster IO managers for object bytes
**How to avoid:** Use `deps` for asset ordering and call the StorageBackend explicitly inside assets. IO managers only for small metadata, if at all.

### Pitfall (new) A: MinIO conditional-write divergence
**What goes wrong:** Using S3 `If-None-Match:'*'` for refuse-overwrite works on AWS but errors/behaves differently on MinIO (dev).
**How to avoid:** Enforce immutability at the app + bucket-policy layer (Pattern 1), not via the S3 conditional-write wildcard.

### Pitfall (new) B: UUIDv7 not in stdlib on 3.12
**What goes wrong:** `from uuid import uuid7` fails on 3.12 (stdlib only from 3.14).
**How to avoid:** `ids.py` wraps `uuid_utils.uuid7()`; the prefix + generation live in one module so the 3.14 switch is a one-line change.

### Pitfall 14: Dagster resource config drift across environments
**How to avoid:** Define MinIO/Postgres/LiteLLM/Qdrant as Dagster resources with `EnvVar` config from the first connection; no hardcoded URLs.

### Pitfall (SSRF) C: URL-download path is an SSRF surface
**What goes wrong:** `klake ingest-url` fetches an arbitrary URL (D-06); an attacker-supplied URL could target internal services/metadata endpoints.
**How to avoid (Phase 1 is thin but establish the seam):** Phase 1's demo uses one fixed public hhs.gov URL, but the `ingest-url` command should validate scheme (`https` only), and the planner should note allow-listing / private-IP blocking as it broadens in Phase 2 (INGEST-02). See §Security Domain.

## Code Examples

### pydantic-settings nested config (FOUND-02)
```python
# config/settings.py  — single typed source; env precedence over .env over defaults
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class StorageSettings(BaseSettings):
    endpoint_url: str | None = None            # None = AWS S3; set for MinIO dev
    bucket: str = "klake-data"
    region: str = "us-east-1"
    access_key_id: str | None = None
    secret_access_key: str | None = None

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="KLAKE_", env_nested_delimiter="__",
        env_file=".env", extra="ignore",
    )
    database_url: str = "postgresql+psycopg://klake:klake@localhost:5432/klake"
    qdrant_url: str = "http://localhost:6333"
    litellm_url: str = "http://localhost:4000"
    embedder: str = "local"                    # FOUND-08 swap key: local | litellm
    parser: str = "docling"
    vectorstore: str = "qdrant"
    storage: StorageSettings = Field(default_factory=StorageSettings)
# env: KLAKE_STORAGE__ENDPOINT_URL=http://minio:9000 ; KLAKE_EMBEDDER=litellm
```

### pipeline_version = package version + git SHA (D-04, FOUND-06)
```python
# version.py
import subprocess
from importlib.metadata import version, PackageNotFoundError

def pipeline_version() -> str:
    try: base = version("knowledge-lake")
    except PackageNotFoundError: base = "0.0.0"
    try:
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, timeout=2).stdout.strip()
        return f"{base}+{sha}" if sha else base
    except Exception:
        return base                            # falls back to package version alone
```

### UUIDv7 + type prefix (D-15)
```python
# ids.py  — swap to `from uuid import uuid7` when the project moves to Python 3.14
import uuid_utils
_PREFIX = {"source": "src", "raw_document": "doc", "parsed_document": "doc", "chunk": "chk"}
def new_id(kind: str) -> str:
    return f"{_PREFIX[kind]}_{uuid_utils.uuid7()}"
```

### Immutable raw-zone put (FOUND-04)
```python
# storage/s3.py (excerpt)
import hashlib
def put_raw(self, source_id: str, data: bytes, ext: str, registry) -> "Artifact":
    h = hashlib.sha256(data).hexdigest()
    existing = registry.get_artifact_by_hash(h, "raw_document")
    if existing:
        return existing                                   # registry-level no-op (FOUND-04)
    key = f"raw/{source_id}/{h}.{ext}"
    if self._exists(key):                                  # defense-in-depth guard
        raise RuntimeError(f"raw key already exists, refusing overwrite: {key}")
    self._client.put_object(Bucket=self._bucket, Key=key, Body=data)  # NO IfNoneMatch='*'
    return registry.create_raw_artifact(source_id=source_id, content_hash=h,
                                        storage_uri=f"s3://{self._bucket}/{key}")
# raw bucket created with versioning + object-lock; bucket policy denies s3:DeleteObject
```

### Qdrant collection + citation payload (INDEX/search slice for D-07)
```python
# plugins/builtin/qdrant_store.py (excerpt)
from qdrant_client import QdrantClient, models
def ensure_collection(self, name, dim, distance="Cosine"):
    if not self.c.collection_exists(name):
        self.c.create_collection(name,
            vectors_config=models.VectorParams(size=dim, distance=models.Distance.COSINE))
# each point payload carries: document, section_path, page, chunk_id  -> citation (D-07/D-14)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `uuid4` random PKs | UUIDv7 (time-sortable, RFC 9562) | stdlib `uuid.uuid7` in **Python 3.14**; `uuid-utils`/`uuid6` on 3.12 | Index-friendly + self-describing prefixes (D-15); use library now, stdlib later |
| Check-then-put race / app-lock for no-overwrite | S3 `If-None-Match:'*'` conditional writes | AWS S3, Aug 2024 | Real on AWS, **not on MinIO** (no `*` wildcard) — use content-addressing + object-lock for portability |
| pydantic v1 `BaseSettings` in `pydantic` | `pydantic-settings` (separate package) | Pydantic v2 split | Install `pydantic-settings` explicitly (2.14.2) |
| SQLAlchemy 1.x `Query`, psycopg2 | SQLAlchemy 2.0 typed + psycopg 3 async | 2.0 GA / psycopg3 | `postgresql+psycopg://`; 2.0-style `select()` |
| Dagster ops/graphs | Software-defined assets | Dagster 1.x | Assets map to zones; wrap functions as assets (D-01) |

**Deprecated/outdated for this phase:**
- `from pydantic import BaseSettings` — moved to `pydantic-settings`.
- psycopg2 — use psycopg 3 (`psycopg[binary]`).
- `Base.metadata.create_all()` for schema — replaced by Alembic (FOUND-09).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | The exact HHS "Summary of the HIPAA Security Rule" PDF URL (hhs.gov) is live and stable | D-05/D-06 | Demo download fails; executor must verify the live URL at build time and, if moved, pick another HHS/OCR public-domain PDF (low risk — many stable candidates) |
| A2 | `uuid-utils` (vs `uuid6`) is the UUIDv7 lib of choice | Standard Stack | Cosmetic; both RFC 9562. Confirm chosen package against official docs before pinning; either works |
| A3 | Local embedding model = all-MiniLM-L6-v2 or bge-small (384-dim) | D-13 | Discretion area; affects Qdrant `dim`. Any 384-dim ST model is fine; larger models cost more RAM in the container |
| A4 | MinIO object-lock requires versioning enabled at bucket creation and supports GOVERNANCE/COMPLIANCE retention | Pattern 1 | If misconfigured, WORM guarantee weakens but app-level content-addressing + delete-deny policy still enforce immutability |
| A5 | LiteLLM proxy `/health/liveliness` returns healthy without valid Bedrock creds (so FOUND-01 passes with zero AWS creds) | FOUND-01, D-13 | If the proxy refuses to boot without creds, use a minimal config / dummy model or run LiteLLM in a mode that defers model validation; verify at compose bring-up |
| A6 | Bedrock alias targets in `infra/litellm/config.yaml` (Haiku 4.5 / Sonnet / Titan v2) are current Bedrock model IDs | D-12 | Not on the spike path (local embeddings); only matters when someone flips `KLAKE_EMBEDDER=litellm`. Verify IDs against Bedrock when Phase 4 activates them |
| A7 | pydantic-settings 2.14.2 is compatible with the pinned pydantic 2.13.x | Stack | Compatible (requires pydantic ≥2.7); confirm on `uv lock` |

**These are LOW-confidence items needing confirmation before they become locked plan decisions.** Everything else is verified against PyPI (today) or current official-source facts.

## Open Questions

1. **Exact spike PDF URL (A1).** Know: HHS/OCR HIPAA Security Rule summary is public domain and stable. Unclear: the precise current URL. Recommendation: executor verifies the live URL during the ingest task; store it in config/fixture, not hardcoded in logic; fall back to another HHS/OCR PDF if 404.
2. **Registry shape — unified node vs enumerated tables.** Know: unified self-ref `artifacts` makes FOUND-07 trivial and matches FOUND-06 wording; FOUND-05 enumerates named tables. Recommendation: unified backbone + `jobs`/`datasets` empty tables in migration #1 + optional `documents`/`chunks` views. Planner to confirm (discretion area).
3. **pluggy vs plain resolver for FOUND-08.** Know: plain resolver satisfies Phase 1 "swap by config"; pluggy pays off at Phase 3 fallback chains. Recommendation: plain resolver now, same Protocols, pluggy later.
4. **Does the API run its own uvicorn container or share the Dagster image?** Recommendation: separate `api` service (uvicorn) in compose for a clean FOUND-01 topology; both import the same package.
5. **Dagster storage DB.** Dagster needs its own Postgres tables. Recommendation: a separate database (or schema) in the same Postgres container to keep the registry schema clean.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python | Runtime | ✓ | 3.12.3 | — (note: `uuid.uuid7` stdlib needs 3.14; use `uuid-utils`) |
| uv | Packaging | ✓ | 0.11.26 | — |
| Docker | Compose stack (FOUND-01) | ✓ | 29.6.1 | — |
| Docker Compose | Compose stack (FOUND-01) | ✓ | v5.2.0 | — |
| Network → PyPI | `uv add`/`uv lock` | ✓ | — | — |
| Network → hhs.gov | Spike doc download (D-06) | assumed ✓ | — | Bundle a cached copy of the PDF as a test fixture if egress is blocked |
| AWS Bedrock creds | LiteLLM alias calls (D-12) | not needed | — | Spike embeds locally (D-13); Bedrock is a later config switch |

**Missing dependencies with no fallback:** none.
**Missing dependencies with fallback:** hhs.gov egress (fallback: cached PDF fixture committed under `tests/`).

## Validation Architecture

`workflow.nyquist_validation` is enabled. Greenfield repo → all test infrastructure is Wave 0.

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest + pytest-asyncio (+ pytest-cov) — install in Wave 0 |
| Config file | none yet — add `[tool.pytest.ini_options]` to `pyproject.toml` (Wave 0) |
| Quick run command | `uv run pytest -x -q` |
| Full suite command | `uv run pytest --cov=knowledge_lake` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| FOUND-01 | Stack comes up healthy | integration/smoke | `uv run pytest tests/integration/test_compose_health.py` (compose up + poll healthchecks) | ❌ Wave 0 |
| FOUND-02 | Config loads from env/.env, validated | unit | `uv run pytest tests/unit/test_settings.py` | ❌ Wave 0 |
| FOUND-03 | S3 read/write round-trips (MinIO) | integration | `uv run pytest tests/integration/test_storage.py` | ❌ Wave 0 |
| FOUND-04 | Content-addressed; re-ingest = no-op; overwrite refused | unit+integration | `uv run pytest tests/integration/test_raw_immutable.py` | ❌ Wave 0 |
| FOUND-05 | Registry stores core entities with hashes/IDs | unit | `uv run pytest tests/unit/test_registry.py` | ❌ Wave 0 |
| FOUND-06 | Every artifact has the six lineage fields | unit | `uv run pytest tests/unit/test_artifact_fields.py` | ❌ Wave 0 |
| FOUND-07 | Lineage resolves chunk→…→source | integration | `uv run pytest tests/integration/test_lineage.py` | ❌ Wave 0 |
| FOUND-08 | Swap embedder/parser/store via config | unit | `uv run pytest tests/unit/test_plugin_resolver.py` | ❌ Wave 0 |
| FOUND-09 | `alembic upgrade head` builds schema clean | integration | `uv run pytest tests/integration/test_migrations.py` | ❌ Wave 0 |
| (spike) | End-to-end demo returns cited results + lineage | smoke | `uv run pytest tests/integration/test_demo_spike.py` (wraps `klake demo`, D-03) | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `uv run pytest -x -q` (unit tests; sub-30s).
- **Per wave merge:** full suite incl. integration (requires compose stack up).
- **Phase gate:** full suite green + `klake demo` prints cited results and a resolved lineage tree, before `/gsd-verify-work`.

### Wave 0 Gaps
- [ ] Install framework: `uv add --dev pytest pytest-asyncio pytest-cov` + `[tool.pytest.ini_options]` in `pyproject.toml`
- [ ] `tests/conftest.py` — fixtures: settings override, ephemeral Postgres (compose or testcontainers), MinIO bucket, Qdrant collection, cached spike PDF
- [ ] `tests/integration/` harness that brings the compose stack (or testcontainers) up/down
- [ ] The demo smoke test (`test_demo_spike.py`) doubles as the later-phase regression smoke (D-03)

## Security Domain

`security_enforcement` enabled, ASVS Level 1, block-on: high. Phase 1 is single-user infra with no auth (multi-tenant auth/RBAC is explicitly out of scope in PROJECT.md), so V2/V3/V4 are largely N/A — but three areas apply.

### Applicable ASVS Categories
| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no (MVP single-user) | Deferred — not in Phase 1 scope |
| V3 Session Management | no | Deferred |
| V4 Access Control | partial | MinIO bucket policy denying `s3:DeleteObject` on raw zone (enforces immutability boundary) |
| V5 Input Validation | **yes** | pydantic models on FastAPI inputs; validate `ingest-url` scheme (`https` only); parameterized SQL via SQLAlchemy |
| V6 Cryptography | partial | SHA256 for content addressing (integrity, not secrecy — never hand-roll digests) |
| V7 Error/Logging | yes | structlog structured logs; never log secrets (MinIO keys, LiteLLM key) |
| V10/V12 SSRF & Outbound | **yes** | `ingest-url` fetches arbitrary URLs — validate scheme, plan private-IP/allow-list blocking (grows in Phase 2) |
| V14 Config/Secrets | **yes** | Secrets only via env/`.env` (gitignored); `.env.example` has placeholders; no creds in code or `infra/litellm/config.yaml` committed |

### Known Threat Patterns for this stack
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| SSRF via `klake ingest-url` arbitrary URL | Info disclosure / Elevation | Scheme allow-list (`https`), block link-local/private ranges, timeout + size cap on download (Phase 2 hardens) |
| SQL injection into registry | Tampering | SQLAlchemy parameterized queries / ORM — never string-format SQL |
| Secret leakage (MinIO/LiteLLM keys) | Info disclosure | Env-only secrets, `.env` gitignored, structlog redaction, never commit `infra/litellm/config.yaml` with real keys |
| Raw-zone tampering/deletion | Tampering / Repudiation | Content-addressed keys + object-lock/versioning + delete-deny bucket policy (FOUND-04) |
| Malicious/oversized PDF (zip-bomb-style) | DoS | Cap download size and Docling memory (Pitfall #2 territory); Phase 1 uses one trusted HHS PDF, but set the limits now |
| Dependency/supply-chain (slopsquat) | Tampering | `uv.lock` pinned + PyPI-verified packages (see Legitimacy Audit); keep `uuid-utils` `[ASSUMED]` until confirmed |

## Sources

### Primary (HIGH confidence)
- PyPI JSON API (`pypi.org/pypi/<pkg>/json`) — version, upload date, repo for all 22 Phase-1 packages, fetched 2026-07-02
- `.planning/research/STACK.md`, `ARCHITECTURE.md`, `PITFALLS.md`, `SUMMARY.md` — project research (pluggy/Dagster/registry/medallion patterns, pitfalls), 2026-07-02
- `.planning/PROJECT.md`, `REQUIREMENTS.md`, `ROADMAP.md`, phase `01-CONTEXT.md` — constraints, FOUND-01..09, locked decisions
- Local environment probe — Python 3.12.3, uv 0.11.26, Docker 29.6.1, Compose v5.2.0

### Secondary (MEDIUM confidence)
- AWS S3 conditional-writes docs + "S3 now supports conditional writes" (Aug 2024) — `If-None-Match:'*'` semantics
- minio/minio#20346 — MinIO does not support the `If-None-Match:'*'` wildcard (informs the immutability approach)
- Python docs + discuss.python.org / cpython#102461, PR#121119 — `uuid.uuid7` added in Python 3.14

### Tertiary (LOW confidence / to confirm)
- Exact hhs.gov spike-PDF URL (A1) — verify live at build time
- `uuid-utils` vs `uuid6` selection (A2) — confirm against official docs before pin
- LiteLLM proxy boots healthy without Bedrock creds (A5) — verify at compose bring-up

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — every version re-verified against PyPI today; matches project STACK.md
- Architecture: HIGH — patterns cross-referenced with the project's own ARCHITECTURE.md and current official facts; registry-shape choice flagged as discretion
- Immutable raw zone: HIGH — MinIO wildcard gap and content-addressing approach confirmed via current sources
- Pitfalls: HIGH — inherited from project PITFALLS.md + two net-new (MinIO conditional-write, UUIDv7 stdlib version)
- Assumptions (A1–A7): LOW — listed for confirmation before locking

**Research date:** 2026-07-02
**Valid until:** ~2026-08-01 (30 days; fast-moving deps — re-check dagster/docling/litellm/fastapi patch versions at plan time)
