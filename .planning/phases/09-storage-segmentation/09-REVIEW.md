---
phase: 09-storage-segmentation
review_date: 2026-07-09
status: issues
effort: high
findings_total: 10
findings_confirmed: 5
findings_plausible: 5
findings_refuted: 0
---

# Phase 9: Storage Segmentation — Code Review

**Effort:** high | **Date:** 2026-07-09 | **Status:** issues found

## Summary

10 findings (5 CONFIRMED, 5 PLAUSIBLE). Two correctness/lineage issues, one latent brittleness bug, plus a set of efficiency and simplification candidates. The most severe finding (Dagster domain bypass) is a silent functional regression for all pipeline-path exports.

---

## Findings

### [CONFIRMED] BLOCKER — Dagster export assets bypass STORE-03

**File:** `src/knowledge_lake/dagster_defs/assets.py` lines 726, 768, 822
**Severity:** High

All three Dagster export asset callsites (`export_rag_fn`, `export_pretrain_fn`, `export_finetune_fn`) call the pipeline functions without `domain=`. Every Dagster-triggered gold-zone export writes to `gold/_unclassified/{type}/` regardless of which domain was ingested. The CLI/API path works correctly; the Dagster orchestration path silently ignores all STORE-03 domain segmentation. No `ExportConfig` class provides domain at materialize time.

**Fix:** Add `domain: str = ""` to `ExportConfig` classes (or add separate domain config) and pass it to the export function calls in `assets.py`.

---

### [CONFIRMED] WARNING — Linked-doc ingest has no lineage to parent source

**File:** `src/knowledge_lake/pipeline/crawl.py:499`

`ingest_url(link_url, source_name=_name_from_url(link_url), settings=settings)` for linked PDFs/DOCXs creates an independent source row with no `source_id` or `job_id` connecting it to the parent HTML page's crawl job. Violates CLAUDE.md: "Every artifact must trace back to source document with stable IDs, content hashes, and timestamps." The code itself labels this "Path B — tech debt: NOT directly linked to the parent HTML page's source_id."

**Fix (tracked as D-22 tech debt):** Extend `ingest_url()` to accept optional `source_id` and `job_id` kwargs and pass the parent crawl job's values at the callsite.

---

### [CONFIRMED] WARNING — `"_unclassified"` literal appears 5× with no shared constant

**File:** `src/knowledge_lake/storage/s3.py:257,365` + `src/knowledge_lake/pipeline/export.py:325,417,537`

The fallback segment string `"_unclassified"` is an inline literal in all five key-construction sites. A rename silently splits the storage zone — objects from the storage layer and export layer land under different prefixes.

**Fix:** Define `_UNCLASSIFIED_DOMAIN = "_unclassified"` in `s3.py` or a shared constants module and import it everywhere.

---

### [CONFIRMED] WARNING — Redundant `get_domain_for_source` call when Source ORM already in scope

**File:** `src/knowledge_lake/pipeline/ingest.py:430,539`

`source` is already the full `Source` ORM object at both `put_raw` call sites. `get_domain_for_source(session, source.id)` re-fetches it from the SQLAlchemy identity map unnecessarily. Direct access via `(source.config or {}).get("domain")` is equivalent, but the `or {}` None-guard is required — `source.config` is `None` for newly created sources without a domain, so a bare `source.config.get("domain")` raises `AttributeError`.

**Fix:** Replace `get_domain_for_source(session, source.id)` with `(source.config or {}).get("domain")` at both call sites in `ingest.py`.

---

### [CONFIRMED] CLEANUP — Triple copy-paste `domain_seg` block in export.py

**File:** `src/knowledge_lake/pipeline/export.py:325,417,537`

`domain_seg = domain or "_unclassified"` + the gold key f-string are copy-pasted verbatim in all three export functions. Updating the gold key template requires three coordinated edits.

**Fix:** Extract a `_gold_key(prefix, domain, subtype, export_id, ext)` helper or at minimum a `_domain_seg(domain)` one-liner used by all three functions.

---

### [PLAUSIBLE] CLEANUP — Two repo calls where one `get_source()` suffices

**File:** `src/knowledge_lake/pipeline/parse.py:113`, `clean.py:301`, `crawl.py:678`

`get_domain_for_source(session, source_id)` + `get_source(session, source_id)` are called back-to-back in three places. A single `get_source()` call returns the `Source` object from which both `(source.config or {}).get("domain")` and `source.name` can be derived. SQLAlchemy identity map prevents a second DB hit within the session today, but the pattern is fragile under async sessions with `expire_on_commit=True`.

---

### [PLAUSIBLE] CLEANUP — Tagless retry hardcodes positional call, silently drops future kwargs

**File:** `src/knowledge_lake/storage/s3.py:126`

The best-effort retry (`self._client.put_object(Bucket=..., Key=..., Body=data)`) duplicates the primary call manually rather than removing the `Tagging` key from `kwargs`. Any future parameter added to `kwargs` (e.g. `ContentType`, `ServerSideEncryption`) is silently dropped on the retry path.

**Fix:** `kwargs.pop("Tagging", None); self._client.put_object(**kwargs)` in the except block.

---

### [PLAUSIBLE] CLEANUP — `isinstance(src, dict)` dead production branch from test concern

**File:** `src/knowledge_lake/pipeline/crawl.py:793`

`list_sources_for_crawl_all` materialises `_SourceRow` namedtuples (line 87) specifically to prevent `DetachedInstanceError`. The `isinstance(src, dict)` guard in `crawl_all_sources` is therefore unreachable in production but exists only to support tests that patch the function to return dicts. This couples production control-flow to test infrastructure.

---

### [PLAUSIBLE] EFFICIENCY — Full table scan in `list_sources_for_crawl_all` when domain filter active

**File:** `src/knowledge_lake/registry/repo.py:897`

All `Source` rows are loaded into memory before Python-side domain filtering. The SQL `WHERE` clause is never pushed to the database. Degrades linearly with source count.

**Fix:** Apply `WHERE config->>'domain' = :domain` at the SQL layer via SQLAlchemy's JSON operator.

---

### [PLAUSIBLE] CLEANUP — Non-obvious `max(tier_result, tier_result + backoff_extra)` idiom ×4

**File:** `src/knowledge_lake/crawl/ratelimit.py:91`

Equivalent to `tier_result + max(0.0, backoff_extra)` but expressed as a double-max per tier (appears four times). A future tier written as `tier_result + backoff_extra` without the guard would violate the floor-raiser contract if any caller ever passes a negative value.

---

## Refuted

- **Double HTML regex scan per page** — `_extract_linked_docs` and `_extract_links` are distinct consumers of the same decoded string. The two-function pattern is intentional (L-04 fix explicitly shared the decode). Not a wasted scan.
