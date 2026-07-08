# Feature Research — v2.0 Agent-Ready Lake

**Domain:** Knowledge Lake / AI-ready document pipeline framework (subsequent milestone: agent access, richer search, self-maintenance)
**Researched:** 2026-07-08
**Confidence:** HIGH (MCP + Qdrant hybrid grounded in current official docs/best-practice writeups; crawl/storage/robustness grounded in established v1.0 stack and standard patterns)

> Scope note: This milestone adds v2.0 features to a shipped framework. v1.0 capabilities (full ingest→export pipeline, dense Qdrant search, Crawl4AI/Scrapy crawling, LiteLLM enrichment, MinIO storage, Postgres registries+lineage, Dagster, FastAPI+Typer, healthcare pack) are **not** re-scoped here. Every feature below is analysed only for its *new* behaviour and its dependency on existing v1.0 pieces.

---

## Feature Landscape

### Table Stakes (Expected — absence makes v2.0 feel half-built)

| Feature | Why Expected | Complexity | Depends on (v1.0) | Notes |
|---------|--------------|------------|-------------------|-------|
| **Richer chunk payload** (source_id, source_name, source_url, format, tags, title, organization) — PAYLOAD-01 | Agents and humans both need to know *what* a hit is and *where it came from*; a bare text+score result is unusable for citation. Every RAG framework attaches provenance to nodes. | LOW | Qdrant plugin, chunker, source/document registries (all payload fields already exist as registry columns) | Payload is the join point between vector hits and lineage. Denormalise registry fields into the payload at index time so search needs no DB round-trip. |
| **Search filters** on source_name, format, tags (array-contains), source_id — PAYLOAD-02 | Filtered retrieval is standard in Qdrant/every vector DB; without it you cannot scope a query to one source or one format. | LOW–MEDIUM | Depends on PAYLOAD-01 (fields must be indexed payload keys), search API + CLI | Create Qdrant **payload indexes** on filtered fields (keyword index for source_id/source_name/format, keyword index for tags with array semantics) — unindexed filters silently degrade to full scans. Filters must be exposed identically in API and CLI. |
| **Hybrid BM25 + dense with RRF** — RETR-01 | Dense-only misses exact terms (drug codes, ICD/CPT codes, acronyms, product names) — a critical failure mode in healthcare. Hybrid is now the expected default in production RAG. | MEDIUM | Qdrant plugin (must add a **named sparse vector** to the collection), embed stage, reindex path | Use Qdrant's native **Query API with `prefetch` + `FusionQuery(RRF)`** — do not fuse client-side. Requires a sparse encoder (BM25/BM42 or SPLADE) added to the embed stage. See "When each mode wins" below. |
| **Configurable search mode** (hybrid \| dense \| sparse) — RETR-02 | Operators need an escape hatch (debugging relevance, cost, or when a sparse index isn't populated). | LOW | RETR-01 | Single enum param threaded through API + CLI. **Default = hybrid.** Dense/sparse are fallbacks. |
| **`crawl-all` batch command** with `--domain` filter — CRAWL-02 | Once you have many sources, per-source crawl invocation doesn't scale operationally. Batch-over-registry is expected. | LOW–MEDIUM | Source registry, existing crawl job runner, Dagster | Iterate registry sources (optionally filtered by domain), enqueue crawl jobs. Must be **resumable/idempotent** and respect per-source config (CRAWL-01). |
| **Per-source crawl_config** (depth, rate_limit_rps) — CRAWL-01 | Different sites need different depth and politeness; one global setting is wrong for a 28-source (soon multi-domain) lake. | LOW | sources.yaml / DomainLoader, crawler plugin | Config lives in sources.yaml, validated by Pydantic, passed to the crawler per job. Sensible defaults so existing sources keep working with no config. |
| **Adaptive rate limiting** (backoff on 429/403, per-host cooldown) — CRAWL-03 | Polite crawling is a legal/operational baseline; hammering a host gets you blocked and violates the project's compliance constraint. | MEDIUM | crawler plugin, per-host state | Exponential backoff + jitter on 429/403, honour `Retry-After`, per-host token bucket. Crawl4AI has rate-limit primitives; wrap rather than reinvent. |
| **Partial-JSON recovery** on truncated LLM enrichment — ENRICH-01 | Truncated/invalid JSON from an LLM is a *when-not-if* event (token cap, stop sequence, provider hiccup). Dropping the whole document is data loss. | LOW–MEDIUM | enrich stage, LiteLLM gateway | Recover the largest valid prefix (balance braces/brackets, salvage complete fields), tag the doc as partially-enriched, keep deterministic fields. Do **not** silently accept junk — record recovery in lineage. |
| **Static OpenAPI export** (`klake openapi` → docs/openapi.json) — SKILL-02 | FastAPI already generates the schema; exporting it as a committed artifact is the trivially-expected way to let external tools/agents consume the API contract. | LOW | Existing FastAPI app | Just serialise `app.openapi()` to a file + a CLI command. Near-free given v1.0. |
| **Domain/source-scoped S3 keys** with `_unclassified` fallback — STORE-01 | Flat keyspaces become unnavigable and un-lifecyclable at scale; scoping by domain/source is the standard data-lake layout. | LOW–MEDIUM | S3/MinIO storage layer, registries (domain/source known at write) | Key template `{zone}/{domain}/{source}/...`; unknown domain → `_unclassified`. **Migration concern:** existing v1.0 objects use old keys — decide read-compat vs. one-time re-key (see Pitfalls linkage). |

### Differentiators (Set this framework apart)

| Feature | Value Proposition | Complexity | Depends on (v1.0) | Notes |
|---------|-------------------|------------|-------------------|-------|
| **MCP server exposing lake operations** (stdio + SSE), `klake mcp` — MCP-01/02 | Turns the lake into a first-class tool for AI agents (Claude Code, IDE agents, custom orchestrators). Very few data-lake/RAG frameworks ship a native MCP surface. This is the headline v2.0 differentiator. | MEDIUM–HIGH | FastAPI service layer (reuse business logic, not HTTP), search, ingest, export, registries | Expose a *small, curated* toolset (search_knowledge, add_source, build_corpus, export_dataset, get_lineage) — **not** a 1:1 dump of 26 endpoints. See "Agent-facing tool contract" section — this is where quality is won or lost. |
| **Claude Code skills** (build-corpus, search-knowledge, add-source, export-dataset) — SKILL-01 | Skills give agents guided, opinionated workflows over raw tools — the difference between "here are 20 endpoints" and "here's how to build a corpus." Aligns with the framework's "AI-ready assets" core value. | LOW–MEDIUM | MCP-01 tools (skills orchestrate tools) | Each skill = a SKILL.md with a workflow + which MCP tools to call. Keep verbs matching user intent, not internal stage names. |
| **OpenAI-format tool definitions from Pydantic** — SKILL-03 | Lets non-MCP agent frameworks (OpenAI tool-calling, LangChain, LlamaIndex) consume the lake with zero hand-authoring. Generated from the same Pydantic schemas → one source of truth. | LOW | Pydantic request models (already exist), SKILL-02 | Emit `{type: function, function: {name, description, parameters(JSON Schema)}}`. Derive from the same models the MCP tools use so the three surfaces (OpenAPI, MCP, OpenAI-tools) never drift. |
| **Self-maintaining lake: scheduled re-crawl sensor** — SCHED-01 | A knowledge lake that goes stale is a liability. Dagster sensor-driven re-crawl on a per-source schedule keeps corpora fresh automatically — a genuine "lake" behaviour vs. one-shot scrapers. | MEDIUM | Dagster (v1.0 has sensors/assets), crawl runner, source registry (needs crawl_schedule + last_crawled fields) | Sensor evaluates which sources are due (schedule vs. last_crawled) and materialises crawl assets. Must not stampede — stagger/limit concurrency. |
| **Content-hash change detection** (skip unchanged pages) — SCHED-02 | Re-crawling is cheap only if you skip unchanged content. Content-hash comparison avoids re-parsing/re-embedding identical pages — huge cost saver at scale, and preserves lineage stability (same hash → same artifact IDs). | MEDIUM | Existing SHA256/xxhash content hashing, document registry, raw-zone immutability (WORM) | Compare fetched-page hash to last-known hash per URL; unchanged → no new raw write, no downstream work, just update last_seen. Changed → new immutable raw version, full pipeline. This is the mechanism that makes SCHED-01 affordable. |
| **PDF/doc ingest by following links** to .pdf/.docx on crawled pages — INGEST-01 | Domain knowledge (esp. healthcare: CMS/ONC/FDA guidance) lives in linked PDFs, not just HTML. Auto-harvesting linked documents dramatically expands corpus coverage without manual upload. | MEDIUM | Crawler (link extraction), Docling parser (already handles PDF/DOCX), ingest + dedup | Detect binary-doc links during crawl, enqueue them as ingest jobs (respect same-domain/allowlist + robots + dedup). Reuse the existing parse path — no new parser. Guard against unbounded fan-out. |
| **Gold-zone segmentation** into rag_corpus / pretrain / finetune per domain — STORE-03 | The framework's dual/triple-output identity (RAG + pretraining + fine-tuning) becomes physically legible in storage, per domain. Makes exports addressable and lifecycle-manageable. | LOW–MEDIUM | Gold-zone export (v1.0), dataset generation | Key layout `gold/{domain}/{rag_corpus\|pretrain\|finetune}/...`. Aligns storage with the three existing output branches. |
| **S3 object tags on every write** (domain, source_name, format, artifact_type) — STORE-02 | Enables lifecycle rules, cost attribution, and metadata-driven queries at the object-store layer without touching Postgres. Complements (does not replace) the registry. | LOW | Storage write path | Tag on every `put`. Keep tags to S3 limits (10 tags, key/value length caps). Tags mirror a subset of registry metadata — treat registry as source of truth, tags as convenience/lifecycle hooks. |

### Anti-Features (Tempting but wrong — exclude explicitly)

| Feature | Why Requested | Why Problematic | Do Instead |
|---------|---------------|-----------------|------------|
| **Expose all 26 REST endpoints 1:1 as MCP tools** | "We already have the API, just wrap it." | Overwhelms the agent's tool-selection: too many tools, overlapping verbs, internal-stage naming (`materialize_silver_zone`) the model can't map to intent. Degrades accuracy — the #1 documented cause of failing MCP agents. | Curate ~5–8 intent-level tools (search_knowledge, add_source, build_corpus, export_dataset, get_lineage, list_sources). Hide pipeline internals behind them. |
| **Return full result sets / full documents from MCP tools** | "The agent might need everything." | Blows the context window, loses earlier tool context, slows the agent. | Enforce result-size limits: default small `limit`, snippets not full bodies, return **URIs/IDs** to fetch full artifacts on demand. Add pagination (`limit`+`cursor`, `has_more`). |
| **Deeply nested / free-form object args on agent tools** | Mirrors the rich REST request bodies. | LLMs hallucinate and mis-serialise nested objects; raises tool-call failure rate. | Flat primitives + enums (`mode: hybrid\|dense\|sparse`), <5 params per tool, `Literal` types over free strings. |
| **Client-side fusion of dense+sparse scores** (or fixed-weight linear blend) | Seems simple; "just add the scores." | Dense and sparse scores live on different, query-dependent scales — fixed weights get dominated by whichever retriever has larger magnitudes. | Use Qdrant's native RRF fusion (rank-based, scale-free) via the Query API `prefetch`. |
| **Re-crawl everything on every schedule tick** | Simplest scheduler logic. | Wastes crawl budget, re-parses/re-embeds unchanged pages, hammers hosts, churns lineage IDs. | Content-hash change detection (SCHED-02) + per-source due-check; only changed pages flow downstream. |
| **Mutate existing raw objects when a page changes** | "Update the page in place." | Violates the hard raw-zone immutability/WORM constraint and breaks lineage stability. | Write a new immutable raw version keyed by new content hash; keep prior version. |
| **Re-key / rewrite all existing v1.0 objects to new scoped layout eagerly** | "Make storage consistent." | Bulk mutation risk, breaks existing lineage pointers, expensive, error-prone during a live migration. | Apply scoped keys to *new* writes; read-compat for old keys; migrate lazily/optionally. Treat as a flagged migration decision, not an implicit side effect. |
| **Full-text LLM re-summarisation to detect page changes** | "Semantic change detection is smarter." | Expensive, non-deterministic, defeats the point of a cheap skip check. Violates deterministic-first constraint. | Cheap content-hash comparison first; LLM only on confirmed-changed content. |
| **Adaptive rate limiting that ignores `Retry-After` / robots** | "Backoff heuristics are enough." | Legal/compliance breach and gets you IP-banned; robots + Retry-After are authoritative. | Honour robots.txt (already v1.0) and `Retry-After`; use adaptive backoff *on top of*, never instead of, those signals. |
| **Unbounded link-following for PDF/doc ingest** | "Grab every linked document." | Crawl explosion, off-domain leakage, license/robots violations, dedup blowup. | Bound by same-domain/allowlist, max depth, robots, SHA256 dedup, and per-source crawl_config. |
| **Second metadata store via S3 object tags** | "Query metadata straight from the bucket." | Two sources of truth drift; S3 tag limits (10 tags) can't hold full metadata; querying tags at scale is slow. | Postgres registry stays source of truth; tags are lifecycle/cost-attribution convenience only. |

---

## Agent-Facing Tool Contract (MCP / OpenAI-tools) — Concrete Expectations

This section answers the milestone's explicit question: *what do good agent-facing tool contracts look like?* Grounded in current MCP best-practice guidance.

**Naming**
- `snake_case`, pattern `action_resource` (`search_knowledge`, `add_source`, `export_dataset`, `build_corpus`, `get_lineage`, `list_sources`).
- Names express intent, not internal pipeline stages. No version numbers, no abbreviations. The MCP server name disambiguates, so avoid heavy prefixes.
- Keep the toolset small (~5–8). Fewer, well-described tools beat many overlapping ones for selection accuracy.

**Argument shape**
- Flat primitives + enums only. Target **<5 params per tool**.
- Constrain choices with `Literal`/enum (e.g. `mode: "hybrid"|"dense"|"sparse"`, `format: "html"|"pdf"|...`), never free-text where a set is known.
- Avoid nested objects/dicts (raise hallucination + serialisation errors).
- Rich, example-bearing descriptions per tool and per param (the model reads these to decide).

**Idempotency**
- Mutating tools (`add_source`, `build_corpus`, `export_dataset`) should be idempotent by natural key (source URL/id, corpus name) — re-calling with same args returns the existing entity, not a duplicate. Reuse v1.0 SHA256/dedup + registry upserts.
- Long-running ops (crawl, build_corpus) should return a **job id + status** immediately (async), with a `get_job_status`/lineage lookup, rather than blocking the agent.

**Result size / shape**
- Default small `limit` (e.g. 5–10 hits). Return **snippets + metadata + IDs/URIs**, not full document bodies.
- Pagination: `limit` + `cursor`/`offset`, plus `has_more`/`next_cursor` in the response.
- For large artifacts (datasets, corpora, full docs), return a **reference (S3 URI / artifact id / lineage id)** the agent can fetch on demand, not the payload.
- Stable, typed, minimal JSON — same Pydantic models that back OpenAPI (SKILL-02) and OpenAI-tools (SKILL-03) so all three surfaces stay in lockstep.

**Transports**
- `stdio` for local agent embedding (Claude Code), `SSE`/HTTP for networked agents. Same tool implementations behind both.

---

## When Each Search Mode Wins (RETR-01/02)

| Mode | Wins when | Loses when | Healthcare-specific note |
|------|-----------|------------|--------------------------|
| **Hybrid (default)** | General queries; mix of concepts + exact terms; unknown query style | Marginal extra latency/index cost vs. dense-only | Best default: catches both "how is sepsis managed" (semantic) and "CPT 99213" (exact code) |
| **Dense** | Pure conceptual/paraphrase queries; short vague natural-language | Exact codes, acronyms, rare tokens, product/drug names | Misses ICD/CPT/NDC codes and abbreviations — a real failure mode here |
| **Sparse (BM25)** | Exact keyword/code lookups; known-item search; when sparse index populated | Paraphrase/synonym queries; semantic intent | Great for code/identifier lookup; brittle for clinical concept queries |

**Recommendation:** default **hybrid** with Qdrant native RRF fusion (rank-based, scale-free). Expose `dense`/`sparse` as explicit overrides. RRF chosen over weighted fusion because dense/sparse scores are on incomparable, query-shifting scales.

---

## Feature Dependencies

```
PAYLOAD-01 (richer payload)
    └──requires──> PAYLOAD-02 (search filters need indexed payload fields)

RETR-01 (hybrid: add sparse named vector + encoder)
    └──requires──> RETR-02 (mode switch)
    └──enhances──> PAYLOAD-02 (filtered hybrid search)
    └──touches───> reindex path (collection schema change → alias-based reindex from v1.0)

MCP-01 (MCP server / curated tools)
    ├──requires──> search (PAYLOAD/RETR for search_knowledge)
    ├──requires──> ingest/registry (add_source), export (export_dataset)
    ├──enables───> SKILL-01 (Claude Code skills orchestrate MCP tools)
    └──shares schemas──> SKILL-03 (OpenAI-tools) & SKILL-02 (OpenAPI)  ← one Pydantic source of truth

SKILL-02 (OpenAPI export) ──feeds──> SKILL-03 (OpenAI-tools generation)

CRAWL-01 (per-source config)
    └──required-by──> CRAWL-02 (crawl-all uses per-source config)
    └──required-by──> CRAWL-03 (rate_limit_rps seeds adaptive limiter)
    └──required-by──> SCHED-01 (crawl_schedule is per-source config)

SCHED-02 (content-hash change detection)
    └──makes-affordable──> SCHED-01 (scheduled re-crawl)
    └──requires──> raw-zone immutability (new version on change, never mutate)

INGEST-01 (linked PDF/doc ingest)
    └──requires──> crawler link extraction + Docling parse path + dedup
    └──bounded-by──> CRAWL-01 (depth/allowlist) + robots (v1.0)

STORE-01 (scoped keys) ──requires──> registries (domain/source at write time)
STORE-02 (object tags) ──enhances──> STORE-01
STORE-03 (gold segmentation) ──requires──> gold-zone export + dataset gen (v1.0)
```

### Dependency Notes

- **PAYLOAD-02 requires PAYLOAD-01 + Qdrant payload indexes:** filters on unindexed fields fall back to slow full scans; create keyword indexes on source_id/source_name/format and array-keyword index on tags.
- **RETR-01 forces a collection schema change:** adding a named sparse vector means existing points need re-indexing — reuse v1.0's alias-based zero-downtime reindex, and add a sparse encoder to the embed stage.
- **MCP-01 should reuse the service layer, not HTTP:** call business logic directly; sharing Pydantic models keeps OpenAPI/MCP/OpenAI-tools from drifting.
- **SCHED-02 is the enabler for SCHED-01:** without cheap change detection, scheduled re-crawl is prohibitively expensive and churns lineage.
- **STORE-01 raises a migration decision:** new writes use scoped keys; old objects keep working via read-compat — do not eagerly rewrite (anti-feature above).

---

## MVP Definition (for this milestone)

### Must land (core v2.0 value)

- [ ] PAYLOAD-01 + PAYLOAD-02 — searchable metadata is the foundation everything else cites; low cost, high leverage.
- [ ] RETR-01 + RETR-02 — hybrid retrieval; the correctness upgrade (codes/acronyms) that matters most for the domain.
- [ ] MCP-01 + MCP-02 — the headline "agent-ready" capability; curated tools.
- [ ] SKILL-02 + SKILL-03 — near-free given FastAPI+Pydantic; unlocks non-MCP agents and keeps contracts in sync.
- [ ] CRAWL-01 + CRAWL-02 + CRAWL-03 — crawl maturation so the self-maintaining loop is safe and batchable.
- [ ] STORE-01 — scoped keys; needed before storage grows further.

### Add once core works

- [ ] SKILL-01 — Claude Code skills (depend on stable MCP tools).
- [ ] SCHED-01 + SCHED-02 — self-maintenance loop (depends on crawl maturation + change detection).
- [ ] INGEST-01 — linked-doc harvesting (depends on crawl + dedup guards).
- [ ] STORE-02 + STORE-03 — object tags + gold segmentation (polish on the storage layer).
- [ ] ENRICH-01 — partial-JSON recovery (robustness; can ship anytime, low coupling).

### Explicitly deferred (per PROJECT.md v2.1)

- [ ] Eval harness (RAGAS/Promptfoo), observability (Langfuse/Arize) — separate milestone.
- [ ] klake-client SDK, multi-domain conflict resolution, pack registry/versioning, discovery scheduling, admin UI, lakeFS/DVC versioning, sitemap-first crawl, quality-score search propagation.

---

## Feature Prioritization Matrix

| Feature | User Value | Impl. Cost | Priority |
|---------|-----------|-----------|----------|
| PAYLOAD-01 richer payload | HIGH | LOW | P1 |
| PAYLOAD-02 search filters | HIGH | LOW | P1 |
| RETR-01 hybrid RRF | HIGH | MEDIUM | P1 |
| RETR-02 mode switch | MEDIUM | LOW | P1 |
| MCP-01 MCP server | HIGH | MEDIUM-HIGH | P1 |
| MCP-02 klake mcp transports | HIGH | LOW | P1 |
| SKILL-02 OpenAPI export | MEDIUM | LOW | P1 |
| SKILL-03 OpenAI-tools gen | MEDIUM | LOW | P1 |
| CRAWL-01 per-source config | HIGH | LOW | P1 |
| CRAWL-02 crawl-all | HIGH | LOW-MEDIUM | P1 |
| CRAWL-03 adaptive rate limit | HIGH | MEDIUM | P1 |
| STORE-01 scoped keys | MEDIUM | LOW-MEDIUM | P1 |
| SKILL-01 Claude Code skills | MEDIUM | LOW-MEDIUM | P2 |
| SCHED-02 content-hash detect | HIGH | MEDIUM | P2 |
| SCHED-01 re-crawl sensor | HIGH | MEDIUM | P2 |
| INGEST-01 linked-doc ingest | HIGH | MEDIUM | P2 |
| ENRICH-01 partial-JSON recovery | MEDIUM | LOW-MEDIUM | P2 |
| STORE-02 object tags | LOW | LOW | P2 |
| STORE-03 gold segmentation | MEDIUM | LOW-MEDIUM | P2 |

**Priority key:** P1 = core milestone value / low-risk enablers; P2 = builds on P1, add once core is stable.

---

## Commonly-Expected-But-Easy-To-Miss Behaviours

- **Qdrant payload indexes**, not just payload fields — filters silently do full scans without them.
- **Reindex/backfill path** for the new payload fields *and* the new sparse vector — existing points won't have them; reuse alias-based reindex.
- **Sensible crawl_config defaults** so all 28 existing sources keep crawling with zero config change.
- **Honour `Retry-After` and robots** inside adaptive rate limiting — backoff heuristics are additive, not a replacement.
- **Idempotent crawl-all and MCP mutations** — re-running must not duplicate sources/jobs.
- **Change detection must not mutate raw** — changed page → new immutable version, preserving WORM + lineage.
- **Bounded link-following** for INGEST-01 — same-domain/allowlist + depth + dedup or you get crawl explosion.
- **One Pydantic source of truth** for OpenAPI + MCP + OpenAI-tools so the three agent surfaces never drift.
- **Result-size discipline on MCP** — snippets + IDs/URIs + pagination, never full bodies.
- **Storage key migration is a decision, not a side effect** — read-compat for old keys; don't eagerly rewrite.
- **Partial-enrichment must be recorded in lineage** — a partially-enriched doc should be traceable, not silently equal to a fully-enriched one.

---

## Competitor / Prior-Art Feature Analysis

| Feature | Prior art | Our approach |
|---------|-----------|--------------|
| Hybrid search | Qdrant native Query API (prefetch + RRF); RAGFlow, Haystack, LlamaIndex all offer hybrid | Use Qdrant native RRF fusion server-side; default hybrid, mode-switchable |
| MCP for data/RAG | Growing set of MCP servers (DBs, search); few RAG/lake frameworks ship curated MCP + skills | Curated ~5–8 intent tools + Claude Code skills + generated OpenAI-tools |
| Scheduled re-crawl + change detection | Scrapy/crawlers support recrawl; content-hash skip is common in ETL; sitemap-based freshness | Dagster sensor + content-hash skip, per-source schedule, immutable versioning |
| Domain-scoped object layout | Medallion/lakehouse layouts scope by domain/dataset | Scope by domain/source; gold split into rag_corpus/pretrain/finetune |
| Agent tool contracts | MCP best-practice guidance (flat primitives, small toolset, pagination, URIs) | Applied directly (see contract section) |

---

## Sources

- [MCP tool descriptions: overview, examples, and best practices — Merge](https://www.merge.dev/blog/mcp-tool-description) — naming, descriptions, arg shape
- [MCP server tool design — Workato Docs](https://docs.workato.com/en/mcp/mcp-server-tool-design.html) — service_action_resource naming, primitives/enums, pagination
- [15 Best Practices for Building MCP Servers in Production — The New Stack](https://thenewstack.io/15-best-practices-for-building-mcp-servers-in-production/) — result size, curated toolsets
- [Client Best Practices — Model Context Protocol](https://modelcontextprotocol.io/docs/develop/clients/client-best-practices) — transport + client expectations
- [MCP is Not the Problem, It's your Server — philschmid](https://www.philschmid.de/mcp-best-practices) — <5 params, Literal types, small toolset
- [MCP Tool Design: Why Your AI Agent Is Failing — DEV](https://dev.to/aws-heroes/mcp-tool-design-why-your-ai-agent-is-failing-and-how-to-fix-it-40fc) — over-exposure as top failure cause
- [Hybrid Search Revamped — Building with Qdrant's Query API](https://qdrant.tech/articles/hybrid-search/) — prefetch + FusionQuery(RRF)
- [Hybrid Queries — Qdrant](https://qdrant.tech/documentation/search/hybrid-queries/) — RRF vs weighted fusion, sparse+dense
- [Hybrid Search with Reranking — Qdrant](https://qdrant.tech/documentation/tutorials-basics/reranking-hybrid-search/) — dense fills sparse gaps; scale-free ranking rationale
- v1.0 project artifacts: `.planning/PROJECT.md`, `.planning/milestones/v1.0-research/FEATURES.md` — existing stack, constraints, dependencies

---
*Feature research for: Knowledge Lake Framework v2.0 (Agent-Ready Lake)*
*Researched: 2026-07-08*
