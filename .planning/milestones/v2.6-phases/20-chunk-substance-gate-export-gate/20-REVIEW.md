---
phase: 20
depth: standard
files_reviewed: 13
files_reviewed_list:
  - domains/healthcare/filters.yaml
  - src/knowledge_lake/config/settings.py
  - src/knowledge_lake/dagster_defs/assets.py
  - src/knowledge_lake/pipeline/chunk.py
  - src/knowledge_lake/pipeline/datasets.py
  - src/knowledge_lake/pipeline/export.py
  - src/knowledge_lake/pipeline/process.py
  - tests/fixtures/must_not_reject.yaml
  - tests/unit/test_chunk_storage.py
  - tests/unit/test_chunk_substance_gate.py
  - tests/unit/test_datasets.py
  - tests/unit/test_export.py
  - tests/unit/test_must_not_reject.py
  - tests/unit/test_process_crawled_clean.py
findings:
  critical: 2
  warning: 0
  info: 0
  total: 2
status: issues_found
---

# Phase 20: Code Review Report

**Reviewed:** 2026-07-17
**Depth:** standard
**Files Reviewed:** 14 (13 requested + `src/knowledge_lake/pipeline/quality/predicates.py` read as call-graph context only, not separately findable — not counted in totals)
**Status:** issues_found

## Summary

Phase 20 wires Phase 19's predicate module and DataTrove's `FineWebQualityFilter` into `chunk()` as a composite substance gate, extends `export_rag_corpus()` to pre-filter on chunk-level `substance_passed`, and tags newly-generated eval/instruction dataset examples with a `version` field. The mechanics inside `chunk.py` (`_apply_substance_gate`, the WR-05/PIPE-01 hash-versioning fix, the conservation invariant, the exemption-predicate identity discipline) are implemented exactly as `chunk.py`'s own design docs specify, and are well covered by `test_chunk_substance_gate.py`/`test_chunk_storage.py`. `export.py`'s `substance_passed` pre-filter correctly excludes-by-default-True-missing / excludes-on-None, matches `test_export.py`'s assertions, and never leaks the field into `_RAG_CORPUS_FIELDS`. `datasets.py`'s `version` tagging is additive and doesn't touch the existing cache key, as designed.

Two critical issues survive verification, both in the domain-allowlist protection this phase is built around — the mechanism meant to keep clinical codes (ICD-10, dosages, LOINC, HIPAA section refs) out of the garbage-chunk cull:

1. `clean()` — which runs **before** `chunk()` in every production path — never actually receives `domain_filters`, so it can drop a clinical-code section before `chunk()`'s newly-wired protection ever sees it.
2. The new `domains/healthcare/filters.yaml` cardinality pattern is broad enough to unconditionally exempt ordinary pagination/boilerplate text (empirically verified against the exact "Page N of M" pattern `clean.py` already special-cases as boilerplate).

Both were verified against the actual regex/predicate code in this repo (not just read from the diff), and both are outside what `tests/unit/test_must_not_reject.py` (the phase's own CI proof) exercises, because that test calls `chunk()` directly with a hand-built `ParsedDoc`, never through `clean()`.

## Critical Issues

### CR-01: `clean()` never receives `domain_filters` in production — clinical-code sections can be dropped before `chunk()`'s gate ever runs

**File:** `src/knowledge_lake/pipeline/process.py:123` and `src/knowledge_lake/dagster_defs/assets.py:319`
**Issue:**

`clean()` (`src/knowledge_lake/pipeline/clean.py:435`) has accepted a `domain_filters: DomainFilters | None = None` parameter since Phase 19-04, and its internal `classify_sections()`/`_clean_sections()` (`clean.py:219-420`) can outright **drop** a section (not just annotate it) when `run_predicates()` on the base threshold predicates fails — this phase's own `20-RESEARCH.md` documents that `check_alpha_ratio` rejects the bare string `"ICD-10 E11.9"` (alpha ratio 0.36 < 0.5) with no domain-allowlist exemption in play.

Both production call sites in this diff resolve `domain_filters` and thread it into `chunk()`, but neither threads it into the preceding `clean()` call:

```python
# process.py:120-126 (process_crawled)
clean_result = clean(parsed_id, src_id, parsed_doc=parsed_doc)   # <- no domain_filters
cleaned_doc = clean_result["cleaned_doc"]
chunks_list = chunk(parsed_id, src_id, cleaned_doc, domain_filters=domain_filters)  # <- gets it
```

```python
# assets.py:319 (clean_document asset)
clean_result = clean(parsed_artifact_id, source_id, parsed_doc=parsed_doc, settings=settings)  # <- no domain_filters
```

`chunk_document`/`process_crawled` DO resolve `domain_filters = DomainLoader.from_name(settings.domain.domain_name).filters` (`process.py:104-107`, `assets.py:386-389`) — but only pass it to `chunk()`. Since `clean()` runs first and can already have removed a section before `chunk()` executes, a document whose section is nothing but a short clinical code (or a short structured field, common in EHR/HTML-table exports not marked `is_table`) is silently dropped upstream, and `chunk()`'s correctly-wired exemption never gets a chance to run on it — the protection Phase 20 built is real, but arrives one pipeline stage too late for this input shape.

`20-RESEARCH.md`'s own "State of the Art" table (line 449) frames the prior state as "`domain_filters` parameter exists on `clean()` but is never resolved/passed by any production call site" and only claims the fix for `chunk()`, not for `clean()` — i.e. `clean()`'s copy of the exact same gap that this phase set out to close for `chunk()` was left open.

**Test-coverage gap:** `tests/unit/test_must_not_reject.py`'s own docstring claims to close "RESEARCH.md Pitfall 1's explicitly-flagged gap: a fixture test that only calls `run_predicates()`/`check_domain_allowlist()` directly can pass while the real pipeline still drops the same text" — but the test calls `chunk()` directly with a hand-built `ParsedDoc` (bypassing `clean()` entirely), so it does not actually exercise the real `parse → clean → chunk` production path and would not catch this.

**Failure scenario:** A crawled healthcare page has a short section/field consisting only of `"ICD-10 E11.9"` (e.g. a structured diagnosis-code line docling doesn't mark as a table). `process_crawled()`/`clean_document` call `clean()` with `domain_filters=None` (implicit default) → `classify_sections()` runs `check_alpha_ratio` on the raw section text (0.36 < 0.5) → `is_boilerplate=True` → `_clean_sections()` drops the section (`"below_alpha_ratio:..."`) before `cleaned_doc` is even built → `chunk()` never sees this text at all, so its `domain_filters` exemption is moot. The clinical code never reaches the gold RAG corpus, despite `chunk()`'s gate being wired correctly.

**Fix:** Resolve `domain_filters` once (as already done) in both `process_crawled()` and the `clean_document` asset, and thread it into the `clean()` call too, mirroring the pattern already used for `chunk()`:

```python
# process.py
clean_result = clean(parsed_id, src_id, parsed_doc=parsed_doc, domain_filters=domain_filters)
```

```python
# assets.py (clean_document) — resolve domain_filters before calling clean(), same guard
# already used in chunk_document/enrich_document:
domain_filters = None
if settings.domain.domain_name:
    from knowledge_lake.domains.loader import DomainLoader
    domain_filters = DomainLoader.from_name(settings.domain.domain_name).filters
clean_result = clean(parsed_artifact_id, source_id, parsed_doc=parsed_doc, settings=settings, domain_filters=domain_filters)
```

And extend `tests/unit/test_must_not_reject.py` (or a sibling test) to run fixtures through the real `clean() → chunk()` sequence, not `chunk()` alone, so the CI proof actually matches its own docstring's claim.

---

### CR-02: New cardinality-constraint allowlist pattern unconditionally exempts ordinary pagination/boilerplate text, directly defeating `clean.py`'s existing "Page N of M" boilerplate detector

**File:** `domains/healthcare/filters.yaml:18`
**Issue:**

The new `normative_allowlists` entry `"\\d+\\s*(?:of|/)\\s*\\d+"` (added to protect fixtures like `"Meets 2 of 4 SIRS criteria"`) is unanchored and matches any `<digits> (of|/) <digits>` substring, not just clinical cardinality phrasing. `check_domain_allowlist()` uses `re.search` (not `re.fullmatch`), so it matches anywhere in the text, and — being an EXEMPTION predicate — a single match unconditionally short-circuits the entire substance gate (`run_predicates()`, both in `chunk.py`'s chunk-level gate and `clean.py`'s `classify_sections()` at the section level, since both consume the same `domain_filters.normative_allowlists`).

Verified empirically against the actual patterns in this file:

```python
>>> re.search(r'\d+\s*(?:of|/)\s*\d+', "Page 1 of 5")
<re.Match object; span=(5, 11), match='1 of 5'>
>>> re.search(r'\d+\s*(?:of|/)\s*\d+', "Showing 1 of 20 results")
<re.Match object; span=(8, 15), match='1 of 20'>
>>> re.search(r'\d+\s*(?:of|/)\s*\d+', "Home About Contact Sitemap Search Page 2 of 8")
<re.Match object; span=(39, 46), match='2 of 8'>
```

`src/knowledge_lake/pipeline/clean.py:70` already carries a dedicated `BOILERPLATE_PATTERNS` entry specifically for this exact shape:

```python
# Page headers/footers: "Page 1 of 5" or a bare page number on its own line
re.compile(r"^(?:Page \d+ of \d+|\d+)\s*$", re.MULTILINE),
```

Because the allowlist check runs *before* the boilerplate-pattern check in `classify_sections()`'s precedence (`clean.py:283-297`, "unconditional override... skip all further checks"), any section/chunk containing an "N of M" or "N/M" substring anywhere — including a genuine nav-junk block with an incidental page-footer fragment, as in the third example above — now bypasses both the dedicated page-footer pattern and every substance threshold (token floor, alpha ratio, link density, stopword ratio, FineWebQualityFilter) entirely. This directly works against `20-03-PLAN.md`'s own stated goal ("the milestone's '<2% junk in gold' success criterion") for every document processed under the (currently only) healthcare domain pack.

**Test-coverage gap:** No "must-reject" / negative fixture set exists alongside `tests/fixtures/must_not_reject.yaml` to pin that known-boilerplate shapes (e.g. pagination footers) are still rejected once domain_filters is active, so this regression is not caught by the new test suite.

**Fix:** Narrow the pattern to require adjacency to actual clinical-scoring vocabulary, e.g.:

```yaml
- "\\d+\\s*(?:of|/)\\s*\\d+\\s+(?:SIRS|Duke|Ranson|SOFA|criteria|metabolic syndrome)"
```

or scope it more tightly (e.g. require a preceding "Meets"/"met"/score-name token). Add a negative fixture test asserting that known boilerplate shapes like `"Page 1 of 5"` and `"Showing 1 of 20 results"` are still classified as boilerplate / fail the substance gate even with the healthcare `domain_filters` active, to guard against this class of regression going forward.

---

_Reviewed: 2026-07-17_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
