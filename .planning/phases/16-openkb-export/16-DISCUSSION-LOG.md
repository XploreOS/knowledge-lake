# Phase 16: OpenKB Export - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-14
**Phase:** 16-openkb-export
**Areas discussed:** Wiki page structure, Cross-linking strategy, Incremental rebuild, CLI/API surface, Summary generation
**Mode:** `--auto` (all decisions auto-selected to recommended defaults)

---

## Wiki Page Structure

| Option | Description | Selected |
|--------|-------------|----------|
| Flat key namespace with typed prefixes | `gold/{domain}/wiki/{type}/{slug}.md` — mirrors STORE-03 segmentation | ✓ |
| Nested by source | `gold/{domain}/wiki/{source_name}/{doc}.md` — groups by origin | |
| Single bundled JSON | All pages in one JSON file — simpler but no individual access | |

**User's choice:** [auto] Flat key namespace with typed prefixes (recommended default)
**Notes:** Mirrors existing gold-zone segmentation from Phase 9 (STORE-03). Enables incremental page updates and direct S3 browsing.

---

## Cross-Linking Strategy

| Option | Description | Selected |
|--------|-------------|----------|
| IDF-based document-frequency threshold | Only entities appearing in >=2 docs with IDF above threshold get concept pages | ✓ |
| All entities get pages | Every enrichment entity becomes a concept page — potentially noisy | |
| Manual entity whitelist | Domain pack defines which entities are linkable — precise but high maintenance | |

**User's choice:** [auto] IDF-based document-frequency threshold (recommended default)
**Notes:** KB-03 explicitly specifies "IDF-filtered entities from enrichment metadata (only link on specific terms)" — this is the most direct implementation of the requirement.

---

## Incremental Rebuild

| Option | Description | Selected |
|--------|-------------|----------|
| Manifest-based content-hash comparison | JSON manifest tracks page hashes + dependency graph; diff on rebuild | ✓ |
| Timestamp-based last-modified check | Compare source last_crawled_at vs. wiki page write time | |
| Full rebuild always | Simpler but violates KB-04 requirement | |

**User's choice:** [auto] Manifest-based content-hash comparison (recommended default)
**Notes:** Content-hash pattern proven in Phase 13 (TREE-02). Timestamps are unreliable across S3 object stores. Manifest enables precise affected-page identification.

---

## CLI/API Surface

| Option | Description | Selected |
|--------|-------------|----------|
| Additive surface: new CLI command + API endpoint | `klake export-wiki` + `/export-wiki` POST — matches KB-05 | ✓ |
| Extend existing export commands | Add wiki as a new export type to existing `klake export` — shared surface | |
| CLI only (no API) | Simpler but violates KB-05 ("available via CLI and API endpoint") | |

**User's choice:** [auto] Additive surface: new CLI command + API endpoint (recommended default)
**Notes:** KB-05 requires both CLI and API. Additive-only convention from Phases 13-15 means new commands, not modified existing ones.

---

## Summary Generation

| Option | Description | Selected |
|--------|-------------|----------|
| Deterministic-first: reuse enrichment metadata | Assemble from document_type + keywords + entities + lead text; no LLM | ✓ |
| LLM-only summaries | Always call LLM for document summaries — richer but costly | |
| Hybrid: deterministic with LLM opt-in | Default deterministic + configurable LLM mode behind budget cap | |

**User's choice:** [auto] Deterministic-first: reuse enrichment metadata (recommended default)
**Notes:** Project constraint "Deterministic first: Use regex/heuristic extraction before LLM enrichment." Phase 13 set the precedent with deterministic tree builder + opt-in LLM mode. D-08/D-09 capture both tiers.

---

## Claude's Discretion

- Exact module structure (single file vs. package)
- Markdown page formatting details (headings, frontmatter, YAML metadata)
- IDF computation method (log-based vs. frequency ratio)
- Concept page internal structure (just links vs. links + inline summary)
- Archive directory structure

## Deferred Ideas

- Watch mode / auto-update (KB-06)
- Wiki lint command (KB-07)
- Chat grounded in wiki (KB-08)
- Full-text search over wiki pages
- Custom wiki templates/themes
- Corpus-level meta-tree (TREE-07)
