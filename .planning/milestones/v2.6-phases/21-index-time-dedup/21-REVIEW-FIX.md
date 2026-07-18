---
phase: 21
fixed_at: 2026-07-17T14:00:00Z
review_path: .planning/phases/21-index-time-dedup/21-REVIEW.md
iteration: 1
findings_in_scope: 2
fixed: 2
skipped: 0
status: all_fixed
---

# Phase 21: Code Review Fix Report

**Fixed at:** 2026-07-17T14:00:00Z
**Source review:** .planning/phases/21-index-time-dedup/21-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 2
- Fixed: 2
- Skipped: 0

## Fixed Issues

### WR-01: Reprocessing an already-indexed document double-counts its own chunk as a new ledger contributor

**Files modified:** `src/knowledge_lake/registry/repo.py`, `tests/unit/test_repo_dedup_ledger.py`
**Commit:** `7d05aab`
**Applied fix:** Added a `chunk_id`-idempotency guard at the top of `append_dedup_contributor()` — if an entry with the same `chunk_id` already exists in `ledger_row.contributors`, the call is a no-op rather than appending a duplicate entry and inflating `contributor_count`. Fixed at the single shared call site so every current and future caller is protected, not just `index()`'s duplicate-routing loop. Added `test_append_dedup_contributor_is_idempotent_for_repeated_chunk_id`, covering both the reprocessed-primary (`chk_1` re-appended) and reprocessed-second-contributor (`chk_2` re-appended) cases — asserts `contributor_count`/`len(contributors)` stay unchanged and each `chunk_id` appears exactly once.

### IN-01: `primary_created_at` docstring's "never reassigned" claim doesn't mention the D-24 self-heal exception

**Files modified:** `src/knowledge_lake/registry/models.py`
**Commit:** `7d05aab`
**Applied fix:** Appended a clause to `ChunkDedupLedger.primary_created_at`'s docstring noting the D-24 self-heal exception: "...permanent, except during D-24 self-heal repair, which reassigns all primary_* fields when the point was lost out-of-band and re-created under the same point_id."

## Skipped Issues

None — all findings were fixed.

---

_Fixed: 2026-07-17T14:00:00Z_
_Fixer: Claude (orchestrator, direct fix — applied inline following the same intelligent-fix-with-verification protocol as gsd-code-fixer: full suite re-run (1176 passed, 0 failed), targeted regression test added, ruff/mypy diff-checked against pre-existing baseline)_
_Iteration: 1_
