# Phase 16: OpenKB Export - Context

**Gathered:** 2026-07-14
**Status:** Ready for planning

> Captured in `--auto` mode: all gray areas auto-resolved to the recommended
> (deterministic-first, additive-surface, incremental-manifest, IDF-filtered-linking)
> option. Decisions are logged in `16-DISCUSSION-LOG.md`. Review before planning
> if any default is wrong.

<domain>
## Phase Boundary

Deliver a **compiled wiki knowledge base** that transforms ingested documents
into an interlinked set of Markdown pages with `[[wikilinks]]` in the gold zone
(KB-01..KB-05). The wiki consists of:

- **Per-document summary pages** — one page per ingested document, containing a
  title, summary, and key metadata drawn from enrichment output.
- **Cross-document concept pages** — one page per high-IDF entity, linking back
  to all documents that mention that entity.
- **A root index page** — the entry point listing all document pages and concept
  pages with navigation links.

All pages use `[[wikilinks]]` (`[[Page Title]]`) to cross-reference each other.
The result is a static, self-contained knowledge base that can be served,
browsed, or imported into wiki tools (Obsidian, Notion, etc.).

**In scope:** new `pipeline/wiki.py` module with wiki compilation logic;
`WikiSettings` config submodel; `klake export-wiki` CLI command; `/export-wiki`
API endpoint; incremental rebuild (only affected pages rewritten on new source
addition); IDF-based entity filtering for cross-link density control; gold-zone
storage as individual Markdown files under a wiki prefix.

**Out of scope (later phases / deferred):** watch mode / auto-update on raw
drop (KB-06); wiki lint for contradictions/orphans (KB-07); multi-turn chat
grounded in wiki content (KB-08); full-text search over wiki pages; GraphRAG
entity extraction; custom wiki templates/themes.

</domain>

<decisions>
## Implementation Decisions

### Wiki page structure — flat namespace with typed prefixes
- **D-01:** Wiki pages are stored as individual Markdown files in the gold zone
  under `gold/{domain}/wiki/`. Three page types live in a flat key namespace
  with prefixes:
  - `doc/{source_id}/{doc_slug}.md` — per-document summary pages
  - `concept/{entity_slug}.md` — cross-document concept pages
  - `index.md` — root index page
  This mirrors the existing `gold/{domain}/{dataset_type}/` segmentation
  pattern from STORE-03 (Phase 9).
- **D-02:** Page slugs are derived deterministically from titles via
  lowercase + hyphen-separated ASCII normalization (same slugification used
  for `phase_slug` in the planning system). Collisions are disambiguated by
  appending a content-hash suffix.

### Cross-linking strategy — IDF-filtered entity terms
- **D-03:** Entity cross-linking uses enrichment metadata `entities` field
  (already populated by Phase 4 `enrich.py`). An entity becomes a
  `[[wikilink]]` target (gets its own concept page) only if its
  **document frequency** is >= 2 (appears in at least 2 documents) AND its
  IDF score passes a configurable threshold (`WikiSettings.min_entity_idf`).
  This prevents common terms from generating noisy links while ensuring
  cross-document concepts are surfaced (KB-03).
- **D-04:** Each concept page lists all documents containing that entity with
  links back to their document summary pages — effectively an inverted index
  rendered as Markdown. Document summary pages link forward to concept pages
  for their qualifying entities.
- **D-05:** Link density is controlled by the IDF threshold (higher = fewer,
  more specific links). Default threshold should be empirically tuned to
  produce ~5-15 links per document page for a typical 28-source domain
  (healthcare). STATE.md already notes this as a concern ("Entity cross-link
  IDF threshold needs empirical tuning for useful link density").

### Incremental rebuild — manifest-based content-hash tracking
- **D-06:** A wiki manifest file (`gold/{domain}/wiki/_manifest.json`) tracks
  every page's content hash and its dependency list (which source documents
  and entities contribute to it). When a new source is added or an existing
  document is re-ingested:
  1. Identify which document pages are new or changed (content hash mismatch).
  2. Recompute the entity IDF scores corpus-wide (cheap: count query).
  3. Identify which concept pages gain/lose document links due to the changed
     IDF or new document.
  4. Rebuild only those pages. Update the manifest.
  This satisfies KB-04 (incremental, not full rebuild) using the same
  content-hash pattern from Phase 13 (TREE-02).
- **D-07:** First-time wiki compilation is a full build (no manifest exists).
  Subsequent runs diff against the manifest. The manifest itself is stored in
  S3 alongside the wiki pages.

### Summary generation — deterministic-first from enrichment metadata
- **D-08:** Per-document summaries on wiki pages are assembled from the
  existing enrichment metadata: `document_type`, `keywords`, `entities`, and
  the first N tokens of the cleaned document text (a lead paragraph). No LLM
  call is made for summary generation in the default mode — deterministic-first
  constraint.
- **D-09:** An opt-in LLM summary mode (gated by `WikiSettings.use_llm_summaries`
  and the existing `LlmSpend` budget cap) can generate richer document
  summaries via LiteLLM. This mirrors the Phase 13 pattern where deterministic
  mode is default and LLM mode is opt-in behind budget control.

### CLI/API surface — additive commands/endpoints
- **D-10:** Add `klake export-wiki` CLI command (Typer) with options:
  `--domain` (required — wiki is per-domain), `--force` (ignore manifest,
  full rebuild), `--dry-run` (show what would change without writing).
  Follows the existing `klake export-*` pattern.
- **D-11:** Add `/export-wiki` POST endpoint to the FastAPI app. Parameters:
  `domain` (required), `force` (bool, default false). Returns a summary of
  pages created/updated/unchanged. Mirrors the existing export endpoints.
- **D-12:** No MCP tool for wiki export in this phase. Export is an operator
  action (like existing export commands), not an agent search operation.
  Agent tools are for querying the lake, not mutating gold-zone outputs.

### Storage and output format
- **D-13:** Each wiki page is stored as a separate S3 object (not a bundled
  archive) so individual pages can be read, linked, and updated independently.
  This enables incremental rebuild (D-06) and allows direct S3-hosted browsing.
- **D-14:** The gold-zone wiki key pattern is:
  `gold/{domain}/wiki/{page_type}/{slug}.md` — e.g.,
  `gold/healthcare/wiki/doc/mayo-clinic-diabetes/overview.md`,
  `gold/healthcare/wiki/concept/insulin-resistance.md`,
  `gold/healthcare/wiki/index.md`.
- **D-15:** A downloadable archive (`.tar.gz` of the wiki directory) is
  available via a CLI flag (`klake export-wiki --archive`) for bulk download /
  Obsidian vault import. The archive is written as an additional gold-zone
  artifact alongside the individual pages.

### Claude's Discretion
- Exact module structure within `pipeline/wiki.py` (single file vs. package)
- Specific Markdown formatting of document and concept pages (headings, frontmatter)
- The exact IDF computation method (standard log-based IDF vs. simpler frequency ratio)
- Whether concept pages include a brief inline summary or only document links
- The archive format details (flat vs. preserving the type-prefix directory structure)
- Executor model: sub-agent executors run on `sonnet` (already pinned via
  `model_overrides.gsd-executor` in `.planning/config.json`)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & roadmap
- `.planning/ROADMAP.md` § "Phase 16: OpenKB Export" — goal + 5 success criteria
- `.planning/REQUIREMENTS.md` § "OpenKB Export" — KB-01…KB-05 (locked);
  "OpenKB Advanced" Future Requirements — KB-06/07/08 (explicitly deferred,
  do not build)

### Upstream contracts this phase consumes
- `.planning/phases/13-tree-index-foundation/13-CONTEXT.md` — D-01/D-02
  (TreeNode/TreeIndex schema; not directly consumed by wiki but shares the
  silver-zone artifact + lineage pattern)
- `src/knowledge_lake/pipeline/enrich.py` — enrichment output schema
  (EnrichmentResult: document_type, keywords, entities fields at lines ~83-95)
  — these are the source data for wiki page content and cross-linking

### Source files to mirror / integrate (existing patterns)
- `src/knowledge_lake/pipeline/export.py` — existing gold-zone export pattern
  (StorageBackend, BytesIO buffer, gold_prefix, domain segmentation, registry
  dataset creation, contamination check structure — D-10 follows this model)
- `src/knowledge_lake/config/settings.py` — `ExportSettings` (~L314) as the
  template for `WikiSettings` submodel (nested under Settings, env-var pattern)
- `src/knowledge_lake/storage/s3.py` — `StorageBackend.put_object()` and
  `object_uri()` for wiki page writes; `_UNCLASSIFIED_DOMAIN` fallback
- `src/knowledge_lake/cli/app.py` — existing export CLI commands as the template
  for `klake export-wiki`
- `src/knowledge_lake/api/app.py` — existing export API endpoints as the template
  for `/export-wiki`
- `src/knowledge_lake/registry/repo.py` — artifact/source queries for building
  wiki content (list_artifacts_by_type, get_enriched_artifact_for_parsed, etc.)
- `src/knowledge_lake/ids.py` — `new_id()` for wiki manifest/dataset IDs

### Project-level constraints
- `.planning/PROJECT.md` — "Storage: S3-compatible (MinIO for dev, AWS S3
  for large-scale) — no local filesystem as production store" (all wiki pages
  stored in S3, never local files)
- `.planning/PROJECT.md` — "Deterministic first: Use regex/heuristic extraction
  before LLM enrichment" (D-08 deterministic summaries before opt-in LLM mode)
- `.planning/PROJECT.md` — "Immutability: Raw zone must never be modified after
  write" (wiki is gold zone, separate from raw — not a constraint here, but
  context for zone awareness)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`pipeline/export.py`** — complete template for gold-zone writes: uses
  `_make_storage()`, `_GOLD_PREFIX`, domain segmentation, `StorageBackend.put_object()`
  with tags, `registry_repo.create_dataset()`. Wiki export follows this exact
  pattern for the manifest and archive artifacts.
- **`pipeline/enrich.py:EnrichmentResult`** — Pydantic model with `keywords`
  (list[str], max 20) and `entities` (list[str], max 50) — these are the
  raw materials for wiki cross-linking.
- **`registry/repo.py`** — `list_artifacts_by_type()`, `get_enriched_artifact_for_parsed()`,
  `list_sources()` — needed for gathering all documents and their enrichment data
  for wiki compilation.
- **`pipeline/utils.py:uri_to_key()`** — S3 URI → key extraction utility.

### Established Patterns
- **Gold-zone domain segmentation** (`gold/{domain}/{type}/`) — from Phase 9
  (STORE-03). Wiki fits as `gold/{domain}/wiki/`.
- **Additive-only new-module convention** — Phases 13/14/15 all added new
  pipeline modules without modifying existing ones. `pipeline/wiki.py` continues this.
- **Content-hash dedup** — from Phase 13 (TREE-02); wiki manifest reuses same
  SHA256-based change detection for incremental builds.
- **Settings submodel pattern** — `ExportSettings`, `SearchSettings`,
  `TreeSearchSettings`, `RouterSettings` all follow the same Pydantic BaseModel
  pattern with env-var override via `KLAKE_{SECTION}__{FIELD}`.
- **BytesIO → put_object() never local-file** — enforced across all storage writes.

### Integration Points
- New module `src/knowledge_lake/pipeline/wiki.py` (wiki compilation logic).
- New `WikiSettings` in `src/knowledge_lake/config/settings.py`.
- New `export-wiki` command in `src/knowledge_lake/cli/app.py`.
- New `/export-wiki` endpoint in `src/knowledge_lake/api/app.py`.
- Registry queries for source list, enrichment metadata, document artifacts.
- S3 writes to `gold/{domain}/wiki/` prefix.

</code_context>

<specifics>
## Specific Ideas

- The wiki should be immediately usable as an Obsidian vault if downloaded via
  `--archive` — this means `[[wikilinks]]` must use the page title as-is
  (Obsidian resolves by filename match, so slug = filename without extension).
- The root index should group documents by source for navigability (matching
  the domain pack's source organization).
- Concept pages could include a "Related concepts" section linking to other
  concept pages that frequently co-occur in the same documents — but this is
  Claude's discretion, not required.

</specifics>

<deferred>
## Deferred Ideas

- **Watch mode / auto-update on raw drop** — KB-06, deferred to future release.
- **Wiki lint command** (contradictions, orphaned pages, stale content) — KB-07,
  deferred to future release.
- **Multi-turn chat grounded in wiki content** — KB-08, deferred to future release.
- **Full-text search over wiki pages** — could be added by indexing wiki pages
  into Qdrant, but not in scope for this phase.
- **Custom wiki templates/themes** — Markdown-only for now; theming is a
  presentation concern outside the framework's responsibility.
- **Corpus-level meta-tree (TREE-07)** — a tree-of-trees that could navigate
  across all wiki pages; deferred to v2.6+.

### Reviewed Todos (not folded)
None — `todo.match-phase 16` returned zero matches.

</deferred>

---

*Phase: 16-openkb-export*
*Context gathered: 2026-07-14*
