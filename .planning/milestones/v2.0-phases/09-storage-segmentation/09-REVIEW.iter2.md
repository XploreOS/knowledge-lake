---
phase: 09-storage-segmentation
reviewed: 2026-07-10T00:00:00Z
depth: standard
files_reviewed: 14
files_reviewed_list:
  - src/knowledge_lake/pipeline/clean.py
  - src/knowledge_lake/pipeline/crawl.py
  - src/knowledge_lake/pipeline/export.py
  - src/knowledge_lake/pipeline/ingest.py
  - src/knowledge_lake/pipeline/parse.py
  - src/knowledge_lake/storage/s3.py
  - tests/integration/test_raw_immutable.py
  - tests/unit/test_clean_silver_key.py
  - tests/unit/test_export.py
  - tests/unit/test_format_tags.py
  - tests/unit/test_parse_silver_key.py
  - tests/unit/test_put_bronze.py
  - tests/unit/test_put_object_tags.py
  - tests/unit/test_put_raw_domain.py
findings:
  critical: 0
  warning: 2
  info: 4
  total: 6
status: issues_found
---

# Phase 09: Code Review Report (re-review after fix iteration)

**Reviewed:** 2026-07-10
**Depth:** standard
**Files Reviewed:** 14
**Status:** issues_found

## Summary

The three targeted fix areas landed correctly where they were applied:

- `_UNCLASSIFIED_DOMAIN = "_unclassified"` is defined in `s3.py:43` and used in both `put_raw` (line 262) and `put_bronze` (line 370). ✓
- `ingest.py` imports `_UNCLASSIFIED_DOMAIN` and replaces both `get_domain_for_source` call sites with `(source.config or {}).get("domain") or _UNCLASSIFIED_DOMAIN` (lines 430, 539). ✓
- `export.py` imports and uses `_UNCLASSIFIED_DOMAIN` in all three key-construction sites (lines 325, 417, 537). ✓

No new bugs were introduced by the above changes.

However, the fix was applied to only two of the five pipeline modules that write domain-scoped storage keys. Three modules — `clean.py`, `parse.py`, and `crawl._write_artifacts` — were not updated. All three still carry the hardcoded `"_unclassified"` literal and still call the legacy `get_domain_for_source()` DB query rather than reading from `source.config`. The constant created to eliminate the split namespace already has three modules that bypass it.

A pre-existing SQL injection pattern in `verify_export()` was not introduced by this iteration but was previously classified only as a plausible cleanup; it warrants a proper security finding.

Note: `src/knowledge_lake/dagster_defs/assets.py` was not included in the review file list. The Dagster domain fix (CONFIRMED BLOCKER from iter1) cannot be verified from the files reviewed.

---

## Warnings

### WR-01: Fix incomplete — three pipeline modules bypass `_UNCLASSIFIED_DOMAIN` with hardcoded literals

**Files:**
- `src/knowledge_lake/pipeline/clean.py:301`
- `src/knowledge_lake/pipeline/parse.py:113`
- `src/knowledge_lake/pipeline/crawl.py:678`

**Issue:** The stated purpose of `_UNCLASSIFIED_DOMAIN` is documented in `s3.py:42`: "a rename never silently splits the storage namespace across modules." That guarantee is violated immediately: the three pipeline modules that write silver-zone keys (`clean.py`, `parse.py`) and raw/bronze crawl artifacts (`crawl.py`) all still contain:

```python
domain = registry_repo.get_domain_for_source(session, source_id) or "_unclassified"
```

None of these files imports the constant. If the constant value is ever changed or the constant is renamed, the silver-zone objects written by `parse.py` and `clean.py` and the crawl artifacts written via `crawl._write_artifacts` will use a different segment string than the raw/bronze/gold objects written by `ingest.py`, `s3.py`, and `export.py`. Objects that should be addressable under the same `_unclassified` segment will silently live under a different prefix — the exact storage namespace split the constant was designed to prevent.

Separately, all three modules already call `get_source(session, source_id)` on the immediately following line to fetch `source_name`. The domain can be read from that same ORM object via `(source_obj.config or {}).get("domain")`, making the prior `get_domain_for_source` call a redundant second DB round-trip (a pattern the `ingest.py` fix already eliminated).

**Fix:** Import `_UNCLASSIFIED_DOMAIN` in each file and eliminate the redundant DB call. The pattern is identical in all three:

```python
# At top of each file — add to existing storage.s3 import:
from knowledge_lake.storage.s3 import StorageBackend, _UNCLASSIFIED_DOMAIN

# clean.py lines 301-304 — replace:
#   domain = registry_repo.get_domain_for_source(session, source_id) or "_unclassified"
#   source_obj = registry_repo.get_source(session, source_id)
# with:
source_obj = registry_repo.get_source(session, source_id)
source_name = source_obj.name if source_obj else "unknown"
domain = (source_obj.config or {}).get("domain") or _UNCLASSIFIED_DOMAIN if source_obj else _UNCLASSIFIED_DOMAIN
cleaned_key = f"{_SILVER_PREFIX}/{domain}/{source_id}/cleaned/{content_hash}.md"
```

Apply the same substitution to `parse.py:112-116` and `crawl.py:677-680`.

---

### WR-02: SQL injection via unvalidated f-string interpolation in `verify_export()`

**File:** `src/knowledge_lake/pipeline/export.py:621-631`

**Issue:** `verify_export()` constructs DuckDB SQL statements by directly interpolating caller-supplied and configuration strings without validation:

```python
con.execute(f"SET s3_endpoint='{endpoint}';")           # line 621
con.execute(f"SET s3_access_key_id='{st.access_key_id}';")   # line 624
con.execute(f"SET s3_secret_access_key='{st.secret_access_key}';")  # line 626
# ...
query = f"SELECT COUNT(*) FROM read_parquet('{export_uri}')"  # line 629
con.execute(query)
```

`export_uri` is a public function parameter. A value containing a single-quote character (e.g., a legitimate S3 path component, or a value passed from user-facing CLI/API) terminates the string literal early and injects arbitrary DuckDB SQL. The credential `SET` statements carry the same risk if a configuration value ever contains a single quote. While the DuckDB instance is ephemeral and in-process, this is a textbook injection pattern on a public function.

**Fix:** Validate `export_uri` format before use and strip or reject single-quote characters from all interpolated values:

```python
import re
_S3_URI_RE = re.compile(r"^s3://[a-zA-Z0-9_./()\-]+$")
if not _S3_URI_RE.match(export_uri):
    raise ValueError(f"verify_export: invalid export_uri format: {export_uri!r}")

for value, name in [
    (endpoint, "s3_endpoint"),
    (st.access_key_id or "", "s3_access_key_id"),
    (st.secret_access_key or "", "s3_secret_access_key"),
]:
    if "'" in value:
        raise ValueError(f"Storage setting {name!r} contains a single-quote — cannot safely construct DuckDB SET statement")
```

---

## Info

### IN-01: `_UNCLASSIFIED_DOMAIN` uses `_` privacy prefix but is imported across module boundaries

**Files:** `src/knowledge_lake/pipeline/ingest.py:37`, `src/knowledge_lake/pipeline/export.py:42`

**Issue:** Python convention reserves a leading `_` for module-private names. Both `ingest.py` and `export.py` import `_UNCLASSIFIED_DOMAIN` from `storage.s3`, creating cross-module use of a symbol that signals it should not be. This is a minor but concrete convention violation: static analysis tools (pylint, ruff) will flag it, and library consumers will receive incorrect signals about the symbol's intended visibility.

**Fix:** Rename to `UNCLASSIFIED_DOMAIN` in `s3.py` and update all import sites (currently `ingest.py` and `export.py`; also add to `clean.py`, `parse.py`, `crawl.py` per WR-01).

---

### IN-02: Stale module docstrings in two test files describe the domain fix as "future" when it is now live

**Files:** `tests/unit/test_clean_silver_key.py:6-11`, `tests/unit/test_parse_silver_key.py:6-11`

**Issue:** Both module docstrings still say: "Currently… `silver_key = f"…/{source_id}/…"` … After Plan 09-04 it will be: `domain = registry_repo.get_domain_for_source(…) or "_unclassified"`." The implementation is in fact complete: `clean.py:304` builds `f"{_SILVER_PREFIX}/{domain}/{source_id}/cleaned/{content_hash}.md"` and `parse.py:116` builds `f"{_SILVER_PREFIX}/{domain}/{source_id}/{content_hash}.md"`. The tests assert the new format correctly and should pass. The docstrings are wrong about what the current state is.

**Fix:** Rewrite both module docstrings to describe the implemented behavior, drop the "RED-state / xfail" framing, and state clearly what each test class is verifying.

---

### IN-03: Four `TestGoldZone*` test classes carry stale "TypeError expected" comments

**File:** `tests/unit/test_export.py:953-956, 997, 1046, 1102, 1167`

**Issue:** Each of the four `TestGoldZone*` classes contains a comment:

```python
# TypeError expected until Plan 09-06 adds domain kwarg
export_module.export_rag_corpus(domain="healthcare", settings=settings)
```

All three export functions already accept `domain: Optional[str] = None` as a keyword argument (declared at `export_rag_corpus:239`, `export_pretrain_corpus:353`, `export_finetune_dataset:446`). No `TypeError` will be raised; these are valid calls. The scaffolding comment from the RED-state phase was never cleaned up.

**Fix:** Remove the "TypeError expected" comments and the Wave 0 xfail scaffold block comment at lines 953-956. If these tests were previously marked `xfail`, remove those marks too.

---

### IN-04: Integration test module docstring claims live PostgreSQL; fixture actually uses SQLite

**File:** `tests/integration/test_raw_immutable.py:1-21, 116-125`

**Issue:** The module docstring states the tests "run against: … Live PostgreSQL (klake_test database, Alembic-migrated by test fixture)." The `engine` fixture (line 116-125) uses `sqlite:///:memory:` with its own inline comment acknowledging the substitution. A developer reading the module header sets up PostgreSQL unnecessarily, and the comment inside the fixture explains why — but the mismatch between header and fixture is a real maintenance trap.

More substantively: PostgreSQL-specific constraint behaviour (the `uq_artifacts_hash_type` unique constraint enforcement, the IntegrityError → rollback → re-query race-condition path in `put_raw`) is not exercised by SQLite. SQLite's single-writer serialisation means the concurrent write scenario in `put_raw:283-297` is never reached by this test suite.

**Fix:** Update the module docstring to say "registry layer uses in-memory SQLite for unit isolation." Add a separate integration-marked test class gated behind `pytest.mark.integration` and `TEST_DB_URL` that exercises the PostgreSQL-specific constraint paths.

---

_Reviewed: 2026-07-10_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
