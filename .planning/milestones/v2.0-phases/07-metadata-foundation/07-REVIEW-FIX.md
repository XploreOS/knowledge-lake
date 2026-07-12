---
phase: 07-metadata-foundation
fixed_at: 2026-07-08T09:22:38Z
review_path: .planning/phases/07-metadata-foundation/07-REVIEW.md
iteration: 1
findings_in_scope: 8
fixed: 8
skipped: 0
status: all_fixed
---

# Phase 07: Code Review Fix Report

**Fixed at:** 2026-07-08T09:22:38Z
**Source review:** .planning/phases/07-metadata-foundation/07-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 8 (3 Critical, 5 Warning)
- Fixed: 8
- Skipped: 0

All 8 in-scope findings were fixed. Each fix was verified with `uv run pytest tests/unit/ -x -q --tb=short` (339 passed, 20 xpassed after each change).

## Fixed Issues

### CR-01: `re.match` instead of `re.fullmatch` in CLI domain-name guard

**Files modified:** `src/knowledge_lake/cli/app.py`
**Commit:** `0bc5e90`
**Applied fix:** Changed `_DOMAIN_NAME_RE.match(domain)` to `_DOMAIN_NAME_RE.fullmatch(domain)` at line 986. The `re.match` anchor only checks the start of the string, allowing path-traversal inputs like `healthcare/../etc` to bypass the guard. `fullmatch` enforces the full pattern match, consistent with the API counterpart at `app.py:107`.

---

### CR-02: `int(payload.get("page", 1))` crashes on non-integer stored values

**Files modified:** `src/knowledge_lake/api/app.py`
**Commit:** `1e081ec`
**Applied fix:** Changed `int(payload.get("page", 1))` to `int(payload.get("page") or 1)` at line 272. The original code only used the default `1` when the key was absent. If the stored value was `None` (chunk with no page set), `int(None)` raised `TypeError`. The `or 1` pattern handles both absent key and explicit `None` value.

---

### CR-03: JSON path cache-key query is SQLite-incompatible and always returns empty on SQLite

**Files modified:** `src/knowledge_lake/registry/repo.py`
**Commit:** `d410fb6`
**Applied fix:** Replaced the `cast(DatasetExample.payload["_cache_key"], String) == f'"{cache_key}"'` SQLAlchemy JSON path query with a Python-side filter matching the project's established pattern in `list_curated_documents_by_dedup_status`. On SQLite, `JSON_EXTRACT` returns values without outer quotes, so the `== '"key"'` comparison was always false, silently breaking idempotency and accumulating duplicate dataset examples. The new implementation fetches all rows and filters with `(e.payload or {}).get("_cache_key") == cache_key`.

---

### WR-01: `list_sources_endpoint` applies domain filter after `LIMIT`/`OFFSET` — breaks pagination semantics

**Files modified:** `src/knowledge_lake/api/app.py`
**Commit:** `28e1aba`
**Applied fix:** When a domain filter is active, the handler now fetches all matching rows first (Python-side filter for DB-agnosticism) and then applies LIMIT/OFFSET to the filtered set. Without a domain filter, LIMIT/OFFSET are pushed to the DB for efficiency. This ensures pagination counts are correct regardless of data distribution across domains.

---

### WR-02: `ensure_aliased_collection` calls `ensure_payload_indexes` but `ensure_collection` does not

**Files modified:** `src/knowledge_lake/plugins/builtin/qdrant_store.py`
**Commit:** `77c5d74`
**Applied fix:** Added `self.ensure_payload_indexes(name)` call at the end of `ensure_collection`, immediately after `create_collection` returns. This ensures collections created via the non-alias code path also receive payload indexes, preventing silent degradation to full-collection scans on filtered searches.

---

### WR-03: Alias registration ordering invariant not documented in `index.py`

**Files modified:** `src/knowledge_lake/pipeline/index.py`
**Commit:** `6083bfc`
**Applied fix:** Replaced `session.flush()` with `session.commit()` and added an explicit comment documenting the ordering invariant: the alias row must be committed before `vstore.upsert` runs in the subsequent session block. The comment explains why a future refactor must not move `vstore.upsert` inside this session block — doing so would silently break the invariant by rolling back the alias registration on any Qdrant failure.

---

### WR-04: `copy_all_points` scroll condition should be documented against falsy integer 0 offset

**Files modified:** `src/knowledge_lake/plugins/builtin/qdrant_store.py`
**Commit:** `d5f1ce0`
**Applied fix:** Added a comment before `if next_offset is None: break` in `copy_all_points` explaining that the `None` check must remain explicit (not falsy) because integer 0 is a valid Qdrant scroll offset for integer-ID collections. No code change was needed; the comment makes the invariant explicit and prevents a future `if not next_offset` regression.

---

### WR-05: `tags` Query parameter `max_length=64` bounds list size not element length

**Files modified:** `src/knowledge_lake/api/app.py`
**Commit:** `cf0482c`
**Applied fix:** Added an explicit per-element guard in the search endpoint handler: `if tags and any(len(t) > 64 for t in tags): raise HTTPException(status_code=422, ...)`. Updated the Query description to clarify "Each tag max 64 chars, max 64 tags" and corrected the docstring security note that had incorrectly claimed `max_length=64` bound element string length.

---

_Fixed: 2026-07-08T09:22:38Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
