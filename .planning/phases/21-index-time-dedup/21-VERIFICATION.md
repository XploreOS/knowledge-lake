---
phase: 21-index-time-dedup
verified: 2026-07-17T14:24:07Z
status: passed
score: 8/8 must-haves verified (all 8 plans' truths substantively confirmed)
behavior_unverified: 0
overrides_applied: 0
---

# Phase 21: Index-Time Dedup Verification Report

**Phase Goal:** Duplicate text is embedded and indexed exactly once while preserving per-document chunk lineage
**Verified:** 2026-07-17T14:24:07Z
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths (ROADMAP Success Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Processing two documents containing identical boilerplate text produces one Qdrant point (not two); chunk registry retains both chunk artifacts with per-document lineage (WR-05 intact) | ✓ VERIFIED | `tests/integration/test_dedup_cli_dagster_parity.py::TestDedupCliDagsterPointIdLedgerParity` passes against live Postgres+Qdrant: second document's chunk routes to `duplicates`, ledger row `contributor_count == 2`, single Qdrant point exists. `dedup_chunks()` (`pipeline/dedup.py`) partitions per-batch and cross-call duplicates into `new`/`duplicates` via atomic `claim_dedup_ledger_entry` (repo.py:1152). |
| 2 | Re-processing the same document produces the same point ID — re-index idempotent via `uuid5(NAMESPACE, sha256(normalized_text))` | ✓ VERIFIED | `point_id_for_text()` (`pipeline/dedup.py`) is a pure function of normalized text; `tests/unit/test_index_dedup.py` proves determinism and NFKC-equivalence (precomposed vs decomposed accented chars yield identical point_id). `tests/integration/test_dedup_reindex_survival.py` proves the ledger's `point_id` continues to resolve correctly across `reindex_collection()`. |
| 3 | A deduplicated point is filterable by source_id, domain, format; `contributors[]` lists all source documents, primary = earliest `created_at` | ✓ VERIFIED | `index()`'s duplicate-routing branch (`pipeline/index.py:272-319`) calls the SAME `_resolve_document_payload_fields()` used for ordinary chunks (D-22) — PAYLOAD-01/02 filters unchanged. `append_dedup_contributor` + `_build_capped_contributors_mirror` (index.py:392-419) guarantee `contributors[0]` is always the primary (D-23). `claim_dedup_ledger_entry` fixes the primary as the first successful claimant (first `created_at`, D-21). |

**Score:** 3/3 ROADMAP success criteria verified. All 8 plans' PLAN-frontmatter `must_haves.truths` (DEDUP ledger schema/atomicity, pure normalize/hash/point-id functions, `set_payload` protocol, `dedup_chunks()` router, `index()` wiring, CLI/Dagster call-site wiring, CLI/Dagster parity + reindex-survival integration proof) were individually spot-checked against source and pass — see Requirements Coverage and Behavioral Spot-Checks below.

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/knowledge_lake/registry/models.py` | `ChunkDedupLedger` model | ✓ VERIFIED | Present, `__table_args__` has `UniqueConstraint("collection", "text_sha256", ...)` per D-12. `primary_created_at` docstring includes D-24 self-heal carve-out (code-review IN-01 fix applied). |
| `src/knowledge_lake/registry/alembic/versions/0011_chunk_dedup_ledger.py` | migration, revision 0011, down_revision 0010 | ✓ VERIFIED | Present; unique constraint + index created; applied to dev Postgres (integration tests write/read the live table). |
| `src/knowledge_lake/registry/repo.py` | `claim_dedup_ledger_entry`, `get_dedup_ledger_entry`, `append_dedup_contributor` | ✓ VERIFIED | All three present. `claim_dedup_ledger_entry` uses `pg_insert(...).returning()`, never `.rowcount` (D-14). `append_dedup_contributor` derives `contributor_count` from `len(contributors)` and is now `chunk_id`-idempotent (WR-01 fix, commit `7d05aab`). |
| `src/knowledge_lake/config/settings.py` | `DedupSettings` + `Settings.dedup` | ✓ VERIFIED | `contributor_cap: int = 50` present. |
| `src/knowledge_lake/pipeline/dedup.py` | `KLAKE_DEDUP_NAMESPACE`, `normalize_for_dedup`, `text_sha256_for`, `point_id_for_text`, `dedup_chunks()` | ✓ VERIFIED | All present; `dedup_chunks()` asserts conservation invariant, commits ledger session before returning (D-14 ordering). |
| `src/knowledge_lake/plugins/protocols.py` | `VectorStorePlugin.set_payload` | ✓ VERIFIED | Declared, minimal signature per D-26. |
| `src/knowledge_lake/plugins/builtin/qdrant_store.py` | `QdrantVectorStore.set_payload` | ✓ VERIFIED | Catches `UnexpectedResponse` 404 → `False`; re-raises other status codes. |
| `src/knowledge_lake/pipeline/index.py` | `duplicate_chunks` kwarg, contributor append + capped mirror, self-heal branch, `reindex_collection()` D-08 note | ✓ VERIFIED | All present at lines 142, 272-419, 459-500ish (D-08 dual-ID-scheme docstring confirmed). |
| `src/knowledge_lake/pipeline/process.py` | `dedup_chunks()` wired between `chunk()` and `embed()`/`index()` | ✓ VERIFIED | Line 137-140: `dedup_result = dedup_chunks(...)`; `embed(dedup_result["new"])`; `index(..., duplicate_chunks=dedup_result["duplicates"])`. |
| `src/knowledge_lake/dagster_defs/assets.py` | `dedup_chunks` asset, `embed_chunks`/`index_chunks` rewired, job selection updated | ✓ VERIFIED | `dedup_chunks` asset at line 562, `embed_chunks(dedup_chunks: ...)` at line 610 (param-name dependency edge), `core_pipeline_e2e_job` selection includes `dedup_chunks` (line ~1084). |
| `tests/unit/test_repo_dedup_ledger.py` | SQLite-harness proof | ✓ VERIFIED | 13 tests pass, incl. new WR-01 regression test. |
| `tests/unit/test_index_dedup.py` | pure-function + router proof | ✓ VERIFIED | 29 tests pass. |
| `tests/unit/test_qdrant_store_set_payload.py` | mocked success/404 proof | ✓ VERIFIED | 3 tests pass. |
| `tests/unit/test_process_crawled_dedup.py` | call-order/argument proof | ✓ VERIFIED | 5 tests pass. |
| `tests/unit/test_asset_ordering.py` | selection-membership guard | ✓ VERIFIED | Extended with `AssetKey("dedup_chunks")` assertions; 16 tests pass. |
| `tests/integration/test_dedup_cli_dagster_parity.py` | D-18 CLI/Dagster point-ID parity | ✓ VERIFIED | 3 tests pass against live dev Postgres+Qdrant. |
| `tests/integration/test_dedup_reindex_survival.py` | reindex-survives-dedup proof | ✓ VERIFIED | 2 tests pass against live dev Postgres+Qdrant. |

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| `claim_dedup_ledger_entry()` | `dedup_chunks()` | `(row, is_new_primary)` tuple routes chunks new/duplicates | ✓ WIRED | `pipeline/dedup.py:184-193` |
| `append_dedup_contributor()`/`get_dedup_ledger_entry()` | `index()` duplicate-routing branch | ledger contributor append + capped Qdrant mirror | ✓ WIRED | `pipeline/index.py:281-314` |
| `dedup_chunks()` output | `process_crawled()` | `embed(dedup_result["new"])`, `index(..., duplicate_chunks=dedup_result["duplicates"])` | ✓ WIRED | `pipeline/process.py:137-140` |
| `dedup_chunks` asset | `embed_chunks`/`index_chunks` assets | parameter-name dependency edge (Dagster convention) | ✓ WIRED | `dagster_defs/assets.py:562-655`; regression-guarded by `test_asset_ordering.py` |
| `vstore.set_payload()` | `index()` self-heal branch | `False` return triggers demote-to-new-path re-embed + ledger repair | ✓ WIRED | `pipeline/index.py:310-385` |

### Data-Flow Trace (Level 4)

Not applicable in the traditional UI-rendering sense — this phase is a backend pipeline stage. Data-flow equivalent: `dedup_chunks()`'s ledger claim is proven to persist real rows in the live Postgres `chunk_dedup_ledger` table (integration tests query the table directly and assert `contributor_count`/`contributors` content), and `index()`'s `set_payload()` calls are proven to land in the live Qdrant collection (integration tests scroll/retrieve the point and assert payload fields). No static/hardcoded stand-ins found.

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Unit suite for this phase (repo, dedup, qdrant set_payload, process wiring, asset ordering) | `uv run pytest tests/unit/test_repo_dedup_ledger.py tests/unit/test_index_dedup.py tests/unit/test_qdrant_store_set_payload.py tests/unit/test_process_crawled_dedup.py tests/unit/test_asset_ordering.py -q` | 66 passed | ✓ PASS |
| Live-stack integration tests for D-18 parity and reindex survival | `uv run pytest tests/integration/test_dedup_cli_dagster_parity.py tests/integration/test_dedup_reindex_survival.py -q` | 5 passed (against live dev Postgres 16 + Qdrant 1.18.2 containers, confirmed running) | ✓ PASS |
| Full project test suite (regression check, run once) | `uv run pytest -q` | 1176 passed, 3 skipped, 6 xfailed, 0 failed | ✓ PASS |
| WR-01 regression test specifically | `test_append_dedup_contributor_is_idempotent_for_repeated_chunk_id` (included in the 13-test `test_repo_dedup_ledger.py` run above) | passed; asserts genuine second-document contribution increments `contributor_count` to 2, and re-appending `chk_1` (reprocessed primary) or `chk_2` (reprocessed second contributor) is a no-op — count and list length stay unchanged, each `chunk_id` appears exactly once | ✓ PASS |

### Code Review Fix Verification (WR-01 / IN-01)

The phase's code review (`21-REVIEW.md`) found one real correctness bug: `append_dedup_contributor()` had no guard against re-appending a `chunk_id` already present in `contributors[]`, so reprocessing an already-indexed document (whose `chunk()` output is itself content-hash idempotent, reusing the same `chunk_id`) inflated `contributor_count` and duplicated the document's own entry in `contributors[]`.

**Fix verified sound.** The fix (commit `7d05aab`, `registry/repo.py:1246-1285`) adds a single guard at the top of `append_dedup_contributor()`: `if any(c.get("chunk_id") == chunk_id for c in new_contributors): return ledger_row` — a no-op keyed strictly on `chunk_id`, applied at the shared call site so every current/future caller is protected.

**Confirmed this does NOT regress the genuine two-different-documents case:** two different documents that happen to contribute byte-identical (post-NFKC) text produce DIFFERENT `chunk_id`s (chunk IDs are content-hash-derived from `parsed_artifact_id` + text — different `parsed_artifact_id` yields a different chunk artifact and therefore a different `chunk_id` even when text matches). The guard only short-circuits on an EXACT `chunk_id` match, so this case is untouched — `contributor_count` still increments to 2. This is explicitly proven by the new regression test `test_append_dedup_contributor_is_idempotent_for_repeated_chunk_id` (`tests/unit/test_repo_dedup_ledger.py:281-350`), which appends a distinct `chunk_id="chk_2"` (genuine second contributor, count → 2) BEFORE testing the reprocess-idempotency no-op paths (re-appending `chk_1` and then `chk_2`, count stays at 2 both times). Also confirmed against the live stack: `test_dedup_cli_dagster_parity.py`'s parity test independently exercises the genuine-two-documents path end-to-end and asserts `contributor_count == 2`.

The companion IN-01 finding (stale docstring on `primary_created_at`) was also fixed — verified the docstring at `registry/models.py:533-537` now includes the D-24 self-heal carve-out.

### Requirements Coverage

| Requirement | Source Plan(s) | Description | Status | Evidence |
|-------------|----------------|--------------|--------|----------|
| DEDUP-01 | 21-01, 21-02, 21-04, 21-06, 21-07, 21-08 | Index-time exact deduplication (corpus-wide, Postgres ledger, `sha256(normalized_text)`) | ✓ SATISFIED | `dedup_chunks()` router + ledger + both call sites wired and integration-proven |
| DEDUP-02 | 21-01, 21-02, 21-04, 21-05, 21-08 | Point ID determinism (`uuid5(NAMESPACE, sha256(normalized_text))`) | ✓ SATISFIED | `point_id_for_text()` pure + deterministic; `index()` prefers it over `_strip_prefix`; reindex-survival test proves resolution across reindex |
| DEDUP-03 | 21-01, 21-03, 21-05, 21-08 | Payload preservation (primary metadata + additive `contributors[]`, PAYLOAD-01/02 intact) | ✓ SATISFIED | `set_payload()` protocol/impl, capped-mirror + uncapped `contributor_count`, `_resolve_document_payload_fields()` reuse (D-22) |

**REQUIREMENTS.md cross-reference:** All three phase-21 requirement IDs (DEDUP-01, DEDUP-02, DEDUP-03) declared across the 8 plans' `requirements:` frontmatter match exactly against REQUIREMENTS.md's Phase 21 mapping (lines 186, 219-221), each already marked "Complete." No orphaned requirements — REQUIREMENTS.md maps no additional IDs to Phase 21 beyond these three.

### Anti-Patterns Found

None. Scanned all 10 phase-modified source files (`registry/models.py`, `0011_chunk_dedup_ledger.py`, `registry/repo.py`, `config/settings.py`, `pipeline/dedup.py`, `plugins/protocols.py`, `plugins/builtin/qdrant_store.py`, `pipeline/index.py`, `pipeline/process.py`, `dagster_defs/assets.py`) for `TBD`/`FIXME`/`XXX`/`TODO`/`HACK`/`PLACEHOLDER` markers, empty implementations, and hardcoded stub returns — zero matches. No debt markers requiring a blocker gate.

### Human Verification Required

None. All must-haves are backend/pipeline-level and were verified programmatically against the live dev Postgres + Qdrant stack plus the full test suite (no visual, real-time, or subjective-UX aspects in this phase).

### Gaps Summary

No gaps. All 3 ROADMAP success criteria, all 3 requirement IDs (DEDUP-01/02/03), and all 8 plans' `must_haves.truths`/`artifacts`/`key_links` are verified present, substantive, and wired, with live-stack integration test evidence (not just unit/mocked evidence) for the corpus-wide dedup, point-ID determinism, and reindex-survival claims. The one real bug found by code review (WR-01) has a verified-sound fix with a regression test that explicitly proves the fix does not regress the genuine two-different-documents-contribute-same-text case. Full test suite: 1176 passed, 0 failed.

---

_Verified: 2026-07-17T14:24:07Z_
_Verifier: Claude (gsd-verifier)_
