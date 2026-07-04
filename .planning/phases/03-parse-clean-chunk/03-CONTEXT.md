# Phase 3: Parse, Clean & Chunk - Context

**Gathered:** 2026-07-04
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 3 turns raw documents of any supported format (PDF, HTML, DOCX, Markdown, CSV, XLSX, JSON, XML) into clean, structure-preserving, citation-traceable chunks. It delivers a parser fallback chain (Docling → Unstructured → Tika) with quality scoring, boilerplate removal, language detection, near-duplicate flagging, and token-aware section-respecting chunking. Parser quality is proven against a torture-test corpus of real healthcare documents before any bulk processing. Every chunk records parent document, section path, and page reference for downstream citation.

Requirements: PARSE-01 through PARSE-05, CLEAN-01 through CLEAN-03, CHUNK-01 through CHUNK-04.

</domain>

<decisions>
## Implementation Decisions

### Parser fallback chain
- **D-01:** Fallback triggers on **exception OR quality gate failure** — if Docling succeeds but produces a quality score below the threshold, the next parser in the chain is attempted. This catches cases where a parser "succeeds" but produces garbage output.
- **D-02:** **Stop on first success** — when a parser passes both checks (no exception AND quality score above threshold), that result is used immediately. No redundant multi-parser comparison runs.
- **D-03:** Tokenizer for chunk sizing is **tiktoken (cl100k_base)** — widely used baseline, fast, lightweight dependency. Keeps chunks decoupled from any specific embedding model per the tool-agnostic principle.

### Quality scoring
- **D-04:** Quality scoring uses **heuristics + LLM spot-check** — a deterministic heuristic score is always computed (text length vs expected, section count, table extraction success, encoding errors, empty-section ratio). When the score falls in a gray zone (configurable band, e.g. 0.3–0.6), an optional LLM call (cheap_model via LiteLLM) assesses coherence. Satisfies "deterministic first" while catching subtle parser failures.

### Claude's Discretion
- Parser chain order is **configurable via settings** (list of parser names in priority order) vs fixed — Claude decides what fits the existing plugin resolver pattern best.
- Whether all 3 parsers (Docling, Unstructured, Tika) are required dependencies or optional extras with graceful skip — Claude decides based on dependency weight and practical concerns.
- Quality threshold: single global number vs per-format — Claude decides what's appropriate for MVP.
- What happens to low-quality documents (flag-only vs halt) — Claude decides based on the batch-first architecture.
- Torture-test corpus: checked into repo vs fetched from public URLs — Claude decides the tradeoff.
- Default chunk size and overlap — Claude decides defaults that work well with all-MiniLM-L6-v2 (current default embedder) and are configurable per domain pack.
- Table atomicity when tables exceed max chunk size — Claude decides based on typical healthcare table sizes.
- Chunk overlap style (heading breadcrumb prefix, raw text overlap, or both) — Claude picks the best approach for citation-traceable retrieval.
- MinHash near-dedup scope (corpus-wide vs per-source-then-corpus) — Claude decides what makes sense for the batch-first architecture.
- Boilerplate removal approach (heuristic patterns vs trafilatura-style extraction vs hybrid) — Claude decides based on the input mix (crawled HTML vs uploaded PDFs vs structured data).
- Near-duplicate action (flag only vs keep canonical + soft-delete rest) — Claude decides based on the lineage-preservation constraint.
- Language detection behavior (annotate only vs gate on supported languages) — Claude picks based on the healthcare-first domain (predominantly English public docs).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project planning docs
- `.planning/PROJECT.md` — Constraints table (deterministic-first, LLM-only gateway, immutability, lineage, task-based aliases), Key Decisions (plugin architecture validated Phase 1)
- `.planning/REQUIREMENTS.md` — PARSE-01..05, CLEAN-01..03, CHUNK-01..04 definitions this phase must satisfy
- `.planning/ROADMAP.md` — Phase 3 goal and 5 success criteria (the scope anchor)

### Prior phase context (decisions that carry forward)
- `.planning/phases/01-foundation-end-to-end-spike/01-CONTEXT.md` — D-01 (plain functions → Dagster wrap), D-08 (grow-as-needed scaffolding), D-11 (built-in plugins register via entry-points), D-13 (all-MiniLM-L6-v2 default embedder)
- `.planning/phases/02-ingestion/02-CONTEXT.md` — D-01 (two artifacts per page: raw + bronze), D-04 (unified crawler system with auto-selection), D-05/06 (URL-first hash-second dedup pattern)

### Existing implementation (extend, don't rewrite)
- `src/knowledge_lake/plugins/protocols.py` — ParserPlugin protocol (can_parse + parse methods), ParsedDoc/Section dataclasses
- `src/knowledge_lake/plugins/resolver.py` — Entry-point group resolution pattern; extend for fallback chain
- `src/knowledge_lake/plugins/builtin/docling_parser.py` — Existing Docling implementation (PDF only, no OCR, no table structure); extend for multi-format
- `src/knowledge_lake/pipeline/parse.py` — Existing parse stage (single parser, silver zone storage, dedup by content hash); extend with fallback chain + quality scoring
- `src/knowledge_lake/pipeline/chunk.py` — Existing chunking (section-aware, char-based MAX_CHUNK_CHARS=1200, sentence splitting); replace with token-aware strategy
- `src/knowledge_lake/registry/models.py` — Artifact model (needs quality_score, language columns); Source model
- `src/knowledge_lake/config/settings.py` — Settings pattern for new parser chain config, quality thresholds, chunk parameters

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `DoclingParser` — working PDF parser implementation. Needs extension for multi-format (HTML, DOCX, etc.) and enabling table_structure/OCR options.
- `parse()` function — registry writes, silver zone storage, content-hash dedup pattern. Extend with fallback loop and quality scoring, don't rewrite.
- `chunk()` function — section iteration, registry artifact creation per chunk, sentence splitting. Replace internals with token-aware logic but keep the registry/artifact creation shell.
- `StorageBackend.put_object()` / `get_object()` — used by parse stage for silver zone. Same pattern for cleaned outputs.
- Phase 2 `normalize_url()` and dedup patterns — exact-hash dedup already works for raw artifacts; extend to parsed documents.

### Established Patterns
- Plugin Protocol + entry-point resolution: every external tool behind a `@runtime_checkable` Protocol, registered via pyproject.toml entry points, resolved by a settings key.
- Content-addressed storage: SHA256 key, never modified after write. Silver zone follows this pattern.
- Registry-first writes: every operation creates registry records (Artifact, LineageEvent) within the same session.
- UUIDv7 with type prefixes (`src_`, `doc_`, `chk_`, `art_`).
- pydantic-settings with `KLAKE_` prefix and `__` nesting for sub-models.
- `get_session()` context manager for DB transactions.

### Integration Points
- New Alembic migration(s) for: quality_score column on Artifact, language column on Artifact/Document, dedup_status column
- New entry-point groups or chain resolver for parser fallback
- New pipeline functions: `clean()`, and extended `parse()` / `chunk()`
- CLI expansion: `klake parse`, `klake clean`, `klake chunk` commands (or unified `klake process`)
- API expansion: parse/clean/chunk trigger endpoints
- Dagster: parse/clean/chunk as software-defined assets with retry

</code_context>

<specifics>
## Specific Ideas

- The existing `parse()` stores parsed output in the silver zone as markdown. The fallback chain should use the same silver zone pattern — whichever parser wins writes to silver.
- Quality score heuristics should be fast enough to run synchronously after every parse (no async/background). The LLM spot-check is the expensive path and should be optional/configurable.
- The torture-test corpus should cover the format spread: at least 1 PDF (complex layout), 1 HTML (crawled healthcare page), 1 DOCX, 1 CSV/XLSX, and 1 structured JSON/XML. Healthcare-specific content preferred.
- MinHash parameters (num_perm, threshold) should be configurable in settings with sensible defaults from DataTrove's production values.
- The existing `MAX_CHUNK_CHARS = 1200` in chunk.py should be replaced by a token-based limit with the configurable default decided by Claude.

</specifics>

<deferred>
## Deferred Ideas

- None — discussion stayed within phase scope.

</deferred>

---

*Phase: 3-Parse, Clean & Chunk*
*Context gathered: 2026-07-04*
