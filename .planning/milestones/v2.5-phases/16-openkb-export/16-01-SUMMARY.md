---
phase: 16-openkb-export
plan: "01"
subsystem: pipeline
tags: [wiki, markdown, knowledge-base, idf, incremental-rebuild]
status: complete

dependency_graph:
  requires:
    - "13-01 (tree_index artifact pattern)"
    - "04-xx (enrich.py EnrichmentResult: entities, keywords, summary fields)"
    - "09-xx (gold-zone export pattern)"
  provides:
    - "WikiSettings config submodel (KB-01..KB-05)"
    - "pipeline/wiki.py: compile_wiki() entry point"
    - "pipeline/wiki.py: slugify(), disambiguate_slug(), compute_entity_idf()"
    - "pipeline/wiki.py: _render_doc_page(), _render_concept_page(), _render_index_page()"
    - "pipeline/wiki.py: _identify_changed_pages()"
  affects:
    - "config/settings.py (WikiSettings added)"
    - "gold/{domain}/wiki/ S3 prefix (new)"

tech_stack:
  added:
    - "tarfile (stdlib) — in-memory .tar.gz archive generation"
    - "orjson — manifest JSON serialization"
    - "hashlib.sha256 — content-hash manifest diffing"
  patterns:
    - "Deterministic-first (D-08): summaries from enrichment metadata; LLM mode opt-in"
    - "IDF filtering (D-03/D-05): log(N/df) with min_entity_df + min_entity_idf thresholds"
    - "Manifest-based incremental rebuild (D-06): SHA256 hash diffing"
    - "BytesIO + put_object (FOUND-03): never local filesystem writes"
    - "Settings submodel pattern: WikiSettings nested under Settings.wiki"
    - "TDD execution: RED (test commit d4cc3fc) → GREEN (feat commit 7a498be)"

key_files:
  created:
    - "src/knowledge_lake/pipeline/wiki.py"
    - "tests/unit/test_wiki.py"
  modified:
    - "src/knowledge_lake/config/settings.py"

decisions:
  - "WikiSettings.min_entity_idf=1.5 default; operator-tunable via KLAKE_WIKI__MIN_ENTITY_IDF"
  - "compile_wiki() reads enrichment metadata_ JSON (entities, keywords, summary, document_type, title) from enriched_document artifacts"
  - "Domain filtered via get_domain_for_source() / Source.config['domain'] (Pitfall 4 pattern)"
  - "No new IDs/registry rows created (wiki pages are gold-zone exports, not registry artifacts)"
  - "Malformed manifest triggers full rebuild with structured warning (T-16-05)"

metrics:
  duration: "~5m"
  completed: "2026-07-14"
  tasks_completed: 2
  files_changed: 3
---

# Phase 16 Plan 01: Wiki Compilation Core Summary

Wiki compilation pipeline that transforms enriched documents into an IDF-filtered, manifest-diffed interlinked Markdown knowledge base stored in the S3 gold zone.

## What Was Built

### Task 1: WikiSettings submodel

Added `WikiSettings` Pydantic BaseModel to `config/settings.py` with 6 fields:

- `min_entity_idf: float = 1.5` — IDF threshold for concept page promotion
- `min_entity_df: int = 2` — minimum document frequency for concept pages
- `use_llm_summaries: bool = False` — deterministic-first, LLM mode opt-in
- `summary_excerpt_chars: int = 500` — lead paragraph length cap
- `budget_usd: float = 5.0` — LLM spend cap
- `model_alias: str = "cheap_model"` — LiteLLM task alias

Added `wiki: WikiSettings = Field(default_factory=WikiSettings)` to `Settings` class after the `router` field.

### Task 2: pipeline/wiki.py (TDD)

Full wiki compilation module with:

**Pure helper functions:**
- `slugify(title)` — deterministic ASCII slug via regex normalization; falls back to "untitled"
- `disambiguate_slug(slug, content_hash)` — appends first 8 hex chars for collision avoidance
- `compute_entity_idf(entity_doc_freq, total_docs, min_entity_df)` — log(N/df) IDF scores for qualifying entities
- `_identify_changed_pages(current_docs, manifest)` — returns (new, changed, removed) tuple

**Rendering functions:**
- `_render_doc_page(...)` — Markdown with heading, metadata, summary, keywords, Related Concepts with `[[concept-slug|Entity Name]]` wikilinks
- `_render_concept_page(...)` — Markdown with entity heading and `[[doc-slug|Doc Title]]` backlinks
- `_render_index_page(...)` — root index grouped by source with wikilinks to all pages

**Main entry point:**
- `compile_wiki(domain, force, dry_run, archive, settings)` — reads all `enriched_document` artifacts for the domain, computes IDF, renders all pages, diffs against S3 manifest, writes only changed pages, optionally generates `.tar.gz` archive

**Returns dict with:** `pages_created`, `pages_updated`, `pages_unchanged`, `concept_pages`, `manifest_uri`, `archive_uri`

## Verification

All 33 unit tests pass:

```
tests/unit/test_wiki.py  33 passed in 1.74s
```

Tests cover:
- `TestSlugify` (7 tests): typical title, punctuation, empty, spaces, unicode
- `TestDisambiguateSlug` (3 tests): suffix length, uniqueness, prefix preservation
- `TestComputeEntityIdf` (5 tests): df filtering, formula, empty corpus
- `TestIdentifyChangedPages` (4 tests): new/changed/removed detection
- `TestCompileWiki` (14 tests): page counts, S3 writes, wikilinks, concept pages, index, IDF filtering, dry_run, incremental rebuild, force rebuild, archive, manifest

## Deviations from Plan

None — plan executed exactly as written.

The test fixture needed API correction (`parent_artifact_id` not `parent_id`, `metadata` not `metadata_`) — caught during RED phase test writing, resolved before committing.

## Security Mitigations Applied

| Threat ID | Status | Implementation |
|-----------|--------|----------------|
| T-16-01 | Mitigated | slugify() strips all non-alphanumeric chars; S3 keys composed only from _GOLD_PREFIX + domain_seg + slugified strings |
| T-16-04 | Mitigated | IDF threshold limits concept page explosion; structured log warning at >1000 docs |
| T-16-05 | Mitigated | Manifest loaded via orjson.loads; non-dict or parse error triggers full rebuild with warning |

T-16-02: domain validation deferred to CLI/API layer (Plan 02 will wire `klake export-wiki --domain` with Typer validation).
T-16-03: accepted — content bounded by EnrichmentResult max_length validators.

## TDD Gate Compliance

- RED gate commit: `d4cc3fc` — `test(16-01): add failing tests for pipeline/wiki.py compilation`
- GREEN gate commit: `7a498be` — `feat(16-01): implement pipeline/wiki.py core compilation module`

## Self-Check: PASSED

- [x] `src/knowledge_lake/pipeline/wiki.py` exists
- [x] `tests/unit/test_wiki.py` exists
- [x] `src/knowledge_lake/config/settings.py` has WikiSettings
- [x] All commits exist: 1dab69e, d4cc3fc, 7a498be
- [x] 33 tests pass
