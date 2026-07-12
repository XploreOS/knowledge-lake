---
phase: 09-storage-segmentation
reviewed: 2026-07-10T00:00:00Z
depth: standard
files_reviewed: 8
files_reviewed_list:
  - src/knowledge_lake/pipeline/clean.py
  - src/knowledge_lake/pipeline/crawl.py
  - src/knowledge_lake/pipeline/export.py
  - src/knowledge_lake/pipeline/ingest.py
  - src/knowledge_lake/pipeline/parse.py
  - src/knowledge_lake/storage/s3.py
  - tests/unit/test_export.py
  - tests/unit/test_put_raw_domain.py
findings:
  critical: 0
  warning: 0
  info: 4
  total: 4
status: issues_found
---

# Phase 09: Code Review Report (re-review after iteration 2 fixes)

**Reviewed:** 2026-07-10
**Depth:** standard
**Files Reviewed:** 8
**Status:** issues_found (info only — no Critical, no Warning)

## Summary

Both Warning findings from the iter2 review are fully resolved. No Critical findings remain.
No new bugs or security issues were introduced by the iteration 2 fixes.

**WR-01 resolved.** All three previously unpatched modules — `clean.py`, `parse.py`, and
`crawl._write_artifacts` — now import `_UNCLASSIFIED_DOMAIN` from `storage.s3` (confirmed at
`clean.py:35`, `parse.py:24`, `crawl.py:44`) and derive domain from `source_obj.config` using the
same `(source_obj.config or {}).get("domain") or _UNCLASSIFIED_DOMAIN` guard pattern introduced by
the `ingest.py` fix. No hardcoded `"_unclassified"` string literal remains in any pipeline module.
The `get_domain_for_source` redundant DB call is eliminated from all three sites. The
cross-module storage namespace split risk is gone.

**WR-02 resolved.** `verify_export()` now validates `export_uri` against the module-level
`_S3_URI_RE = re.compile(r"^s3://[a-zA-Z0-9_./()\-]+$")` regex (`export.py:58`, `export.py:614`)
before any query construction. It also rejects any config value containing a single-quote character
for `endpoint_url`, `access_key_id`, and `secret_access_key` (`export.py:616-625`) before any
`SET` statement is executed. Both guards run before any f-string interpolation into DuckDB SQL.

The four Info findings reported in iter2 are unchanged (they were not in scope for iter2 fixes and
remain valid cleanup candidates).

---

## Narrative Findings (AI reviewer)

## Info

### IN-01: `_UNCLASSIFIED_DOMAIN` uses `_` privacy prefix but is imported across five module boundaries

**File:** `src/knowledge_lake/storage/s3.py:43`; imported at `clean.py:35`, `parse.py:24`,
`crawl.py:44`, `ingest.py:37`, `export.py:43`

**Issue:** Python convention reserves a leading `_` for module-private names. Five pipeline modules
now import `_UNCLASSIFIED_DOMAIN` from `storage.s3`. Static analysis tools (ruff rule PLC2401,
pylint W0212) will flag every import. Library consumers receive incorrect signals about intended
visibility.

**Fix:** Rename to `UNCLASSIFIED_DOMAIN` in `s3.py` and update all five import sites.

---

### IN-02: Stale module docstrings in two test files describe the domain fix as "future" when it is now live

**Files:** `tests/unit/test_clean_silver_key.py`, `tests/unit/test_parse_silver_key.py`
(outside this review scope but confirmed stale from iter2)

**Issue:** Both module docstrings describe the domain-scoped silver key format as a pending change
("After Plan 09-04 it will be…") when the implementation is complete. The tests already assert the
implemented format.

**Fix:** Rewrite both module docstrings to describe the implemented behavior and drop the
"RED-state / xfail" framing.

---

### IN-03: Four `TestGoldZone*` test classes carry stale "TypeError expected" comments

**File:** `tests/unit/test_export.py` — block comment at lines 953-956; inline comments before
`domain=` calls in `TestGoldZoneDomainKey`, `TestGoldZoneUnclassified`, `TestGoldZonePretrain`,
`TestGoldZoneFinetune`

**Issue:** Each class contains a comment of the form:
```python
# TypeError expected until Plan 09-06 adds domain kwarg
export_module.export_rag_corpus(domain="healthcare", settings=settings)
```
All three export functions already accept `domain: Optional[str] = None` as a keyword argument
(`export.py:245`, `export.py:358`, `export.py:451`). No `TypeError` will be raised; the
scaffolding comment from the RED-state phase was never removed.

**Fix:** Remove the stale "TypeError expected" comments and the Wave 0 xfail scaffold block at
lines 953-956. Confirm no `@pytest.mark.xfail` decorators remain on these methods.

---

### IN-04: Integration test module docstring claims live PostgreSQL; fixture uses SQLite

**File:** `tests/integration/test_raw_immutable.py` (outside this review scope, confirmed from iter2)

**Issue:** The module docstring states the tests run against "Live PostgreSQL (klake_test database,
Alembic-migrated by test fixture)." The `engine` fixture uses `sqlite:///:memory:`. The concurrent
write / IntegrityError recovery path in `put_raw` (lines 283-297 of `s3.py`) is never exercised
because SQLite serialises all writers.

**Fix:** Update the module docstring to state "in-memory SQLite for unit isolation." Add a separate
`@pytest.mark.integration` test class gated on `TEST_DB_URL` to exercise the PostgreSQL-specific
constraint paths.

---

_Reviewed: 2026-07-10_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
