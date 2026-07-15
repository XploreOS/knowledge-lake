---
phase: 16-openkb-export
fixed_at: 2026-07-14T00:00:00Z
review_path: .planning/phases/16-openkb-export/16-REVIEW.md
iteration: 1
findings_in_scope: 6
fixed: 6
skipped: 0
status: all_fixed
---

# Phase 16: Code Review Fix Report

**Fixed at:** 2026-07-14T00:00:00Z
**Source review:** .planning/phases/16-openkb-export/16-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 6 (2 critical, 4 warning)
- Fixed: 6
- Skipped: 0

## Fixed Issues

### CR-01: Removed pages computed but never acted upon — stale S3 objects accumulate indefinitely

**Files modified:** `src/knowledge_lake/storage/s3.py`, `src/knowledge_lake/pipeline/wiki.py`
**Commit:** d4fd8df
**Applied fix:** Added `StorageBackend.delete_object()` method to `s3.py` (idempotent — NoSuchKey treated as success). In `compile_wiki()`, added step 9b that iterates `removed_pages` and calls `storage.delete_object(key)` with per-key warning logging on `ClientError`. Added `pages_removed` to the return dict on both the dry-run and live code paths, and updated the docstring.

---

### CR-02: Slug disambiguation does not detect secondary collisions — silent S3 page overwrite

**Files modified:** `src/knowledge_lake/pipeline/wiki.py`
**Commit:** eae60c0
**Applied fix:** Rewrote the doc slug loop to check whether the disambiguated slug is also already registered: if the primary disambiguated slug (base + content_hash[:8]) collides, falls back to a secondary disambiguation using a SHA256 of `artifact_id`. Applied the identical two-tier check to the concept slug loop (base + entity_hash[:8], then entity_hash[8:16] as fallback). Both loops now guarantee no silent overwrites.

---

### WR-01: API `/export-wiki` silently omits `dry_run` and `archive` parameters — CLI/API capability gap

**Files modified:** `src/knowledge_lake/api/schemas.py`, `src/knowledge_lake/api/app.py`
**Commit:** da8d49f
**Applied fix:** Added `dry_run: bool = Field(default=False)` and `archive: bool = Field(default=False)` to `WikiExportRequest`. Updated the `wiki_export_endpoint` handler to forward both to `compile_wiki()` so the REST API has feature parity with the CLI (D-02).

---

### WR-02: CLI `cmd_export_wiki` does not catch `botocore.ClientError` — S3 failures produce unhandled tracebacks

**Files modified:** `src/knowledge_lake/cli/app.py`
**Commit:** bda86ac
**Applied fix:** Added a local `from botocore.exceptions import ClientError as BotocoreClientError` import inside the command function and included `BotocoreClientError` in the `except` tuple. S3 failures now produce a clean `Error: ...` message and exit code 1.

---

### WR-03: Entity names and document titles in wikilinks are not sanitized — Markdown/wikilink formatting corrupted by `|` or `]]`

**Files modified:** `src/knowledge_lake/pipeline/wiki.py`
**Commit:** eb1c79a
**Applied fix:** Added `_sanitize_wikilink_display(text)` helper that replaces `|` with `-`, removes `]]`, and normalizes newlines to spaces. Applied the sanitizer at all four wikilink construction sites: the entity link in `_render_doc_page`, the backlink in `_render_concept_page`, and both wikilinks in `_render_index_page` (document and concept loops).

---

### WR-04: `tarfile.TarInfo` mtime not set — all files in archive have epoch-0 timestamps

**Files modified:** `src/knowledge_lake/pipeline/wiki.py`
**Commit:** 34f4554
**Applied fix:** Added `import time` to the module imports. Before the archive loop, captures `_archive_mtime = int(time.time())` once and sets `info.mtime = _archive_mtime` on each `TarInfo` object so all entries share a consistent, correct modification time.

---

_Fixed: 2026-07-14T00:00:00Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
