# Phase 1: Foundation & End-to-End Spike - Context

**Gathered:** 2026-07-02
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 1 delivers the framework skeleton — typed pydantic-settings config, S3 storage abstraction (MinIO dev / AWS S3 prod via one boto3 client), content-addressed immutable raw zone, PostgreSQL registries with Alembic migrations, and plugin protocol interfaces — proven by one real document flowing ingest → parse → chunk → embed → index → search on a single `docker compose up` stack. Thin vertical slice: one path, no breadth. Ingestion breadth is Phase 2, parsing breadth is Phase 3, enrichment is Phase 4.

Requirements: FOUND-01 through FOUND-09.

</domain>

<decisions>
## Implementation Decisions

### Spike shape & Dagster timing
- **D-01:** Pipeline stages (ingest, parse, chunk, embed, index) are plain functions behind the plugin protocol interfaces first; they get wrapped as Dagster software-defined assets **before the phase closes**. Dagster ships in docker-compose from the first commit either way. This satisfies "Dagster from day 1" while avoiding research Pitfall #1 (over-engineering Dagster before proving flow).
- **D-02:** CLI/API execute the pipeline via **direct in-process calls** in Phase 1. Switching them to submit Dagster runs is a later-phase change behind the same commands — the user-facing surface must not change when that swap happens.
- **D-03:** Ship a **scripted one-command demo** (e.g., `klake demo` or `make spike`) that ingests the test document, runs the fixed search query, and prints results with citations plus the lineage chain. It doubles as a smoke test for all later phases.
- **D-04:** `pipeline_version` on every artifact = **package version + git SHA** (e.g., `0.1.0+abc1234`); falls back to package version alone when not running from a git checkout.

### Spike test document
- **D-05:** The spike document is **one real healthcare PDF**: an HHS/OCR HIPAA guidance PDF (e.g., "Summary of the HIPAA Security Rule") — US-federal public domain, stable hhs.gov URL, real headings and moderate structure. No synthetic fixture.
- **D-06:** It enters the raw zone via a **minimal URL-download path** (`klake ingest-url <url>` style): fetch from the public URL, record SHA256, MIME type, source URL, timestamp, and license metadata. Phase 2 broadens this into the full INGEST-02 command; do not build crawlers/uploads/discovery in Phase 1.
- **D-07:** Search success bar: a **fixed demo query** (e.g., "what are administrative safeguards") must return chunks from the right section of the document, each with score and citation (document, section path, page). The demo asserts citation fields are present and lineage resolves; relevance is human-checked once. No golden-query eval harness in Phase 1.

### Repo & package layout
- **D-08:** **Grow-as-needed scaffolding.** Phase 1 creates only the subpackages the spike touches. The user's proposed `src/knowledge_lake/` structure (see Canonical References) is the target map — each phase adds its directories when it builds them. No empty placeholder modules.
- **D-09:** Naming: import package **`knowledge_lake`**, distribution **`knowledge-lake`**, CLI entry point **`klake`**.
- **D-10:** The pre-existing empty `configs/`, `services/`, `workspace/` dirs are **removed**; adopt the proposed layout: `infra/` for service configs (litellm/, postgres/, qdrant/, minio/, dagster/), `data/` kept but **gitignored** as local dev zone storage (MinIO is the real store), plus `scripts/`, `tests/`.
- **D-11:** Built-in plugin implementations (Docling parser, Qdrant store, embedders, crawlers) live **inside the core package**, registering via the same entry-point/hook mechanism third-party plugins would use. Split into separate packages only if a real need appears later.

### Dev models & lineage UX
- **D-12:** LiteLLM dev alias mapping (in `infra/litellm/config.yaml`, never in code): `cheap_model` → Claude Haiku 4.5 on Bedrock, `strong_model` and `eval_model` → Claude Sonnet on Bedrock, `embedding_model` → Amazon Titan Text Embeddings V2 on Bedrock. Aliases are fixed; only the config maps them.
- **D-13:** Spike default embedding provider is **local sentence-transformers** (e.g., all-MiniLM or bge-small) so `docker compose up` + demo runs with **zero AWS credentials**. Bedrock embeddings via LiteLLM remain a pure config switch (ENRICH-06 configurability starts here).
- **D-14:** `klake lineage <artifact-id>` prints a **human-readable ancestry tree** by default (chunk → parsed doc → raw doc → source; each node shows ID, type, content hash, timestamp, pipeline version, storage URI), with `--json` for the full machine-readable graph. The API returns the JSON form.
- **D-15:** Registry entity IDs are **UUIDv7 with short type prefixes** (`src_`, `doc_`, `chk_`, `art_`, ...): self-describing in logs/CLI, time-sortable in PostgreSQL indexes. CLI accepts unambiguous ID prefixes for convenience.

### Claude's Discretion
- Registry schema details (table/column design within the 17-registry blueprint), SQLAlchemy/psycopg specifics, Alembic layout, compose service wiring, exact local embedding model choice, chunking parameters for the spike, error handling and logging design — planner/executor decide, consistent with PROJECT.md constraints.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project planning docs
- `.planning/PROJECT.md` — Constraints table (LiteLLM-only gateway, S3-compatible storage, Dagster day 1, immutability, lineage, task-based aliases, deterministic-first) and Key Decisions
- `.planning/REQUIREMENTS.md` — FOUND-01..09 definitions this phase must satisfy
- `.planning/ROADMAP.md` — Phase 1 goal and success criteria (the scope anchor)

### Research
- `.planning/research/SUMMARY.md` — recommended stack with verified versions, Phase 1 guidance ("registry-first development", spike-before-Dagster), Pitfalls 1/6/8
- `.planning/research/ARCHITECTURE.md` — pluggy hookspec pattern, Dagster resource injection, registry table sketch
- `.planning/research/STACK.md` — pinned library versions (Python 3.12+/uv, Dagster 1.13.x, Docling 2.108.x, Qdrant 1.18.x, LiteLLM 1.90.x, FastAPI 0.139.x, Typer 0.26.x, psycopg 3.3.x, Polars 1.42.x, DuckDB 1.5.x)
- `.planning/research/PITFALLS.md` — Pitfall #1 (over-engineering Dagster), #6 (mutable raw zone), #8 (schema over-normalization)

### User's target structure (from project brief, reflected in PROJECT.md)
- The user's proposed `src/knowledge_lake/` module map, 17 PostgreSQL registries, klake CLI command list, and FastAPI endpoint list are recorded in the conversation brief and summarized in `.planning/PROJECT.md` Active requirements. Phase 1 implements only the spike's slice of it (per D-08).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- None — greenfield repo. Only `.planning/` docs and four empty directories (`configs/`, `data/`, `services/`, `workspace/`) exist; per D-10 three of them are removed and `data/` becomes gitignored dev storage.

### Established Patterns
- None yet — Phase 1 establishes them (plugin protocols, registry-first writes, content-addressed storage keys).

### Integration Points
- Docker services to wire: PostgreSQL, Qdrant, MinIO, LiteLLM, Dagster (webserver+daemon), FastAPI app.

</code_context>

<specifics>
## Specific Ideas

- Demo query example the user approved: "what are administrative safeguards" against the HHS Security Rule summary PDF.
- Lineage tree rendering: chunk → parsed doc → raw doc → source with per-node metadata (D-14) — this is the phase's showpiece; FOUND-07 verification runs through it.
- The `klake` CLI and FastAPI surface built in Phase 1 should be the thin start of the full command/endpoint lists in the project brief — same names, minimal subset.

</specifics>

<deferred>
## Deferred Ideas

- None — discussion stayed within phase scope.

</deferred>

---

*Phase: 1-Foundation & End-to-End Spike*
*Context gathered: 2026-07-02*
