---
phase: 22-address-tech-debt-measure-garbage-junk-rates-end-to-end-reco
reviewed: 2026-07-17T19:52:54Z
depth: standard
files_reviewed: 5
files_reviewed_list:
  - src/knowledge_lake/cli/app.py
  - src/knowledge_lake/pipeline/export.py
  - src/knowledge_lake/pipeline/quality_audit.py
  - tests/unit/test_cli_quality_audit.py
  - tests/unit/test_quality_audit.py
findings:
  critical: 2
  warning: 3
  info: 2
  total: 7
status: issues_found
---

# Phase 22: Code Review Report

**Reviewed:** 2026-07-17T19:52:54Z
**Depth:** standard
**Files Reviewed:** 5
**Status:** issues_found

## Summary

This phase adds `run_full_pipeline_audit()` to `quality_audit.py` and wires it
through a new `klake quality-audit --full` flag. The section-level audit path
(`run_quality_audit()`, unchanged in this phase) has good, tested error
isolation: a per-document `try/except Exception` catches failures from
`parse()`/`clean()` and continues to the next document, so one bad document
never aborts the whole domain scan (`TestRunQualityAuditErrorIsolation`
locks this in).

The new `--full` path breaks that contract. Two pieces of newly-added code —
the real, persisting `chunk()` call inside the per-document loop, and the
real `export_rag_corpus()` call after the loop — execute completely outside
any exception handling, both in `quality_audit.py` and in the CLI command
that calls it. `export_rag_corpus()`'s first statement is a hard
train/eval-contamination gate that raises on any undocumented corpus-wide
overlap; that gate is reachable from a "measurement" command with zero
handling anywhere in the call chain, and it is not covered by any test in
this diff. This is a genuine regression from the error-isolation behavior
this same module already proved with tests for the non-`--full` path.

Additional lower-severity findings: repeated `--full` runs leave a growing
trail of gold-zone Parquet files + `Dataset` rows behind (a "measurement"
command with unbounded write side effects), the pre-existing near-dup
contamination check in `export.py` is broader than pairwise overlap would
require, and `export_pretrain_corpus()` reimplements S3-key parsing instead
of reusing the shared, safer `uri_to_key()` helper already imported into the
same file.

## Critical Issues

### CR-01: `run_full_pipeline_audit()`'s real `chunk()` call runs outside the per-document error-isolation `try/except`, unlike every other stage in the same loop

**File:** `src/knowledge_lake/pipeline/quality_audit.py:278-361`

**Issue:** The per-document loop wraps only `parse()`/`clean()` in
`try: ... except Exception: documents_errored += 1; ...; continue`
(lines 278-315). The newly-added in-memory chunk tally
(`_build_token_chunks()`/`_apply_substance_gate()`, lines 331-337) and,
critically, the **real persisting `chunk()` call** (lines 358-360) execute
*after* that `except` block, entirely unguarded:

```python
            except Exception:
                documents_errored += 1
                ...
                continue

            sections_considered += clean_result["sections_considered"]
            ...
            raw_chunks = _build_token_chunks(cleaned_doc, ...)
            _apply_substance_gate(raw_chunks, s, domain_filters, parsed_id)
            ...
            chunk_results = chunk(               # <-- real DB/S3 write, unguarded
                parsed_id, source_id, cleaned_doc, settings=s, domain_filters=domain_filters,
            )
            this_run_chunk_ids.update(r["chunk_id"] for r in chunk_results)
```

`chunk()` performs real I/O (registry writes, S3 puts). Any transient
failure there (S3 hiccup, DB constraint/commit error, or
`_assert_chunk_conservation_invariant` raising `RuntimeError` on an edge
case in `chunk.py`) propagates straight out of `run_full_pipeline_audit()`
for the **entire domain**, discarding every row already computed for every
other source, and crashing `klake quality-audit --full` with a raw
traceback. This directly contradicts the module's own documented and
tested contract — `run_quality_audit()`'s
`TestRunQualityAuditErrorIsolation.test_one_document_failure_does_not_abort_audit`
proves "one raw doc's ... failure is caught/counted; other docs and sources
still processed" for the base path, but no equivalent test or code exists
for `--full`, and the equivalent code path is demonstrably not covered.

**Fix:** Move the chunk-tally block and the real `chunk()` call inside the
existing `try` (or add a second `try/except Exception` around this block
that increments `documents_errored` and `continue`s, mirroring the existing
pattern):

```python
        for raw_id, mime, storage_uri in raw_docs:
            try:
                ... # existing parse/clean
                clean_result = clean(...)

                cleaned_doc = clean_result["cleaned_doc"]
                if cleaned_doc is not None:
                    raw_chunks = _build_token_chunks(cleaned_doc, ...)
                    _apply_substance_gate(raw_chunks, s, domain_filters, parsed_id)
                    ...
                    chunk_results = chunk(parsed_id, source_id, cleaned_doc,
                                           settings=s, domain_filters=domain_filters)
                    this_run_chunk_ids.update(r["chunk_id"] for r in chunk_results)
            except Exception:
                documents_errored += 1
                log.warning(..., exc_info=True)
                continue

            sections_considered += clean_result["sections_considered"]
            ...
```

### CR-02: `export_rag_corpus()` call in `run_full_pipeline_audit()` (and the CLI `--full` branch that invokes it) has no exception handling — `TrainEvalContaminationError` crashes the whole audit

**File:** `src/knowledge_lake/pipeline/quality_audit.py:427` and `src/knowledge_lake/cli/app.py:1004-1060`

**Issue:** After the per-source loop, `run_full_pipeline_audit()` calls the
real export path directly:

```python
    if this_run_chunk_ids:
        ...
        export_result = export_rag_corpus(domain=domain, settings=s)   # no try/except
```

`export_rag_corpus()`'s **first statement** is
`_enforce_no_contamination(s)`, which raises `TrainEvalContaminationError`
(a `RuntimeError` subclass) whenever `check_train_eval_contamination()`
finds any undocumented corpus-wide overlap between eval-shaped and
train-shaped dataset examples (`export.py:232-247`). This check is
corpus-wide, not scoped to the audited domain or to this run — a normal,
expected state for any corpus that has accumulated `generate-dataset qa`
and `generate-dataset instruction` examples over time.

Nothing in the call chain handles this exception:
- `run_full_pipeline_audit()` itself has no try/except around the export
  call (`quality_audit.py:419-443`).
- `cmd_quality_audit`'s `--full` branch calls
  `run_full_pipeline_audit(domain=domain)` with **no try/except at all**
  (`cli/app.py:1004-1060`) — unlike almost every other command in this
  file (including `cmd_export`, which explicitly catches
  `TrainEvalContaminationError` and prints a clean `Error: ...` message).

The practical effect: running `klake quality-audit --full` on a corpus with
any undocumented train/eval overlap crashes with an unhandled exception and
a raw Python traceback, after having already spent the time/cost of
re-running parse→clean→chunk across the whole domain — instead of the
"read/measurement-only, safe to re-run" behavior the module's own docstring
promises. No test in this diff exercises this path.

**Fix:** Wrap the export call (or the whole `--full` invocation) in a
try/except, and propagate a clean error the same way `cmd_export` does:

```python
    # quality_audit.py
    if this_run_chunk_ids:
        try:
            export_result = export_rag_corpus(domain=domain, settings=s)
        except TrainEvalContaminationError:
            log.warning("quality_audit.export_scoping_skipped_contamination", domain=domain)
            export_kept = export_junk = 0
            export_junk_rate = None
        else:
            ...
```
```python
    # cli/app.py
    if full:
        from knowledge_lake.pipeline.export import TrainEvalContaminationError
        from knowledge_lake.pipeline.quality_audit import run_full_pipeline_audit
        try:
            result = run_full_pipeline_audit(domain=domain)
        except (TrainEvalContaminationError, ValueError, LookupError) as exc:
            typer.echo(f"Error: {exc}", err=True)
            raise typer.Exit(code=1) from exc
        ...
```

## Warnings

### WR-01: `--full` writes a new gold-zone export file + `Dataset` row on every invocation, with no cleanup, contradicting the module's "read/measurement-only" framing

**File:** `src/knowledge_lake/pipeline/quality_audit.py:419-443`

**Issue:** `export_rag_corpus()` always mints a fresh `new_id("dataset")`,
writes a new Parquet object to `gold/<domain>/rag_corpus/<id>.parquet`, and
inserts a new `Dataset` row (`export.py:384-406`). Because
`run_full_pipeline_audit()` calls the real `export_rag_corpus()` every time
it is invoked (whenever `this_run_chunk_ids` is non-empty — i.e. on every
normal run), each `--full` invocation leaves behind a permanent S3 object
and DB row purely as a side effect of measurement. A tool meant to be
re-run periodically (CI, scheduled quality checks, or just repeated manual
runs while iterating on a domain pack) will accumulate an unbounded number
of throwaway gold-zone exports and dataset rows over time. The module's own
docstring still frames this as "read/measurement-only" even after this
phase's edit acknowledges the new scope is `parse -> clean -> chunk (->
export)` — the "read-only" framing is misleading for anyone deciding it's
safe to run `--full` frequently/in CI.

**Fix:** Either (a) tag these audit-generated datasets distinctly (e.g. a
`purpose="quality_audit"` tag/metadata field) and document/automate their
cleanup, or (b) read back an *existing* export instead of writing a fresh
one when one from this run already exists, or (c) at minimum call this out
explicitly in the CLI help/docstring so operators know `--full` is not a
side-effect-free measurement.

### WR-02: `check_train_eval_contamination()`'s near-dup overlap is a wholesale union, not a pairwise match — can over-flag unrelated documents

**File:** `src/knowledge_lake/pipeline/export.py:206-217`

**Issue:**

```python
eval_near_dup = eval_cleaned_doc_ids & near_dup_cleaned_doc_ids
train_near_dup = train_cleaned_doc_ids & near_dup_cleaned_doc_ids
near_dup_overlap: set[str] = (eval_near_dup | train_near_dup) if (eval_near_dup and train_near_dup) else set()
```

When there is at least one near-dup-flagged document on the eval side AND
at least one on the train side, `near_dup_overlap` is the **union** of
*every* near-dup document on both sides — not the (unknowable, given the
binary flag) actual overlapping pair. In a corpus where near-dup flags are
common (which is exactly the corpus this phase's `--full` audit measures —
`batch_dedup_corpus()` runs corpus-wide), this can flag large numbers of
documents as "contaminated" that have no real relationship to each other,
because they merely happen to both carry a `near_dup=True` flag against
*some* other document. This is called "conservative by design" in the
docstring, but the blast radius is unbounded (scales with the number of
near-dup documents on each side, not with actual overlap), which can make
every export command (`rag-corpus`, `pretrain`, `finetune`) fail closed far
more often than a real leakage risk would justify — directly relevant now
that `quality_audit.run_full_pipeline_audit()` calls this same gated
`export_rag_corpus()` path on every `--full` run.

**Fix:** At minimum, cap/report the size of `near_dup_overlap` distinctly
from `direct_overlap` so operators can see when the conservative branch is
firing broadly; ideally compute pairwise cluster membership (or intersect
with a doc-similarity check) instead of a flat union of both flagged sets.

### WR-03: `export_pretrain_corpus()` re-implements S3-key parsing instead of reusing the shared `uri_to_key()` helper, with weaker error handling

**File:** `src/knowledge_lake/pipeline/export.py:477-487`

**Issue:** This same file already imports and uses
`uri_to_key()`/`_uri_to_key()` for extracting the object key from an
`s3://bucket/key` URI (`export.py:49`, used at line 337 in
`export_rag_corpus()`, which raises `ValueError` on malformed URIs).
`export_pretrain_corpus()` instead reimplements the same logic manually:

```python
            if cleaned.storage_uri:
                parts = cleaned.storage_uri.split("/", 3)
                key = parts[3] if len(parts) == 4 else cleaned.storage_uri
                try:
                    text_bytes = storage.get_object(key)
                    text = text_bytes.decode("utf-8", errors="replace")
                except Exception:
                    text = ""
```

If `storage_uri` is malformed (fewer than 4 `/`-delimited segments), this
silently falls back to passing the *entire* `s3://...` URI as the object
key to `storage.get_object()`, which will fail and be swallowed by the
bare `except Exception: text = ""` with **no logging** — producing a
silently-empty-text row in the exported pretraining corpus instead of a
clear, debuggable failure the way `uri_to_key()`'s explicit `ValueError`
would surface.

**Fix:** Reuse `_uri_to_key(cleaned.storage_uri)` (already imported) and
log a warning on the `except Exception` fallback, matching the pattern
used elsewhere in this file.

## Info

### IN-01: Unused `Settings` import retained via `# noqa: F401` in both audit functions

**File:** `src/knowledge_lake/pipeline/quality_audit.py:82, 226`

**Issue:** Both `run_quality_audit()` and `run_full_pipeline_audit()`
contain `from knowledge_lake.config.settings import Settings, get_settings  # noqa: F401`.
`Settings` is never referenced in either function body (no type
annotations use it); only `get_settings` is used. The `noqa` suppresses
the lint warning but the import is genuinely dead weight.

**Fix:** Drop `Settings` from the import, or use it as the return-type
annotation for the `settings` parameter if that was the intent
(`settings: Settings | None = None`).

### IN-02: ~90-line near-duplicate per-document processing loop between `run_quality_audit()` and `run_full_pipeline_audit()`

**File:** `src/knowledge_lake/pipeline/quality_audit.py:93-183` and `241-365`

**Issue:** The source-listing query, raw-document listing query, and the
entire parse→clean per-document loop (including the `try/except
Exception` error-isolation block) are duplicated near-verbatim between the
two functions. This phase's own commit history shows the cost of that
duplication first-hand: the `domain_filters` threading fix
("Pitfall 1") had to be applied to `run_quality_audit()`'s existing loop
and then re-authored again when `run_full_pipeline_audit()` was added —
any future fix to this shared logic (error handling, session handling,
domain filtering) must be made in two places or will silently drift, as
already nearly happened here (see CR-01/CR-02, which is exactly this kind
of drift: the error-isolation `try/except` pattern from the first copy
was not extended to cover the new code added to the second copy).

**Fix:** Extract the per-source/per-document parse→clean loop into a
shared helper (e.g. `_run_parse_clean_for_source(...)`) that both
`run_quality_audit()` and `run_full_pipeline_audit()` call, with
`run_full_pipeline_audit()` layering the chunk-tally/export-scoping logic
on top via a callback or an optional extension point.

---

_Reviewed: 2026-07-17T19:52:54Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
