---
quick_id: 260715-5pb
slug: fix-kl-07-kl-04-05-06-kl-11-kl-16-kl-10
description: Fix KL-07, KL-04/05/06, KL-11, KL-16, KL-10
date: 2026-07-15
status: complete
tasks_completed: 6
addresses: [KL-07, KL-04, KL-05, KL-06, KL-11, KL-16, KL-10]
discovered: [KL-18, KL-19]
commits:
  - 5b5bcd7  # KL-07 SSRF is_global
  - 8ee9082  # KL-11 wiki boundary truncation
  - dbd8abd  # KL-16 rename core_pipeline_e2e_job
  - 6a1e9b4  # KL-04/05/06 ordering chain + payload precedence + refresh
  - 8b9e27b  # KL-04/05/06 regression coverage
  - 76963c2  # KL-06 job-selection gap + vacuous-guard fix
  - 9d3f98b  # KL-10 remove 42 stale xfail markers
  - bf8b6ac  # KL-10 enable xfail_strict
tests:
  combined: 943 passed
  failed: 0
  errors: 0
  xpassed: 0
  xfailed: 12
  xfail_strict: true
---

# Quick Task 260715-5pb — Summary

Seven findings closed across three waves. The ordering was load-bearing and held:
KL-10 ran last and re-measured rather than reusing the audit's numbers.

## Wave 1

- **KL-07** (`5b5bcd7`) — `_PRIVATE_NETS` membership → `not addr.is_global`.
  Verified through the real `validate_public_url()` in both directions: 6 reserved
  ranges now blocked (incl. `0.0.0.0`, which reaches localhost on Linux), 3
  controls still blocked, public IPv4/IPv6 and a live `www.faa.gov` resolution
  still allowed. Over-blocking would have broken crawling; it doesn't.
- **KL-11** (`8ee9082`) — boundary-aware truncation with an ellipsis.
- **KL-16** (`dbd8abd`) — `healthcare_e2e_job` → `core_pipeline_e2e_job`.
  Rename only, by decision; the pack-jobs extension point stays on the roadmap.

## Wave 2 — KL-04/05/06 (one design change)

D-01's "parallel branches that do not block" was **false parallelism**. Curate
reads the enriched sibling for the 40% enrich term of its composite and
substitutes 0.5 when it's missing; index reads it for the payload. Measured on
the real aviation document: **0.797 vs 0.965 — a 21% swing on the same document
from scheduling order alone.**

Fixed by making the chain explicit (`clean → enrich → curate → chunk → embed →
index`) via non-data `deps=` edges, payload precedence `curated ?? enriched ??
None`, and an opt-in `klake index --refresh-payload` to repair chunks indexed
before enrichment (reindex previously copied points verbatim).

**Two things nearly slipped through, both caught:**

1. `core_pipeline_e2e_job`'s selection excluded `curate_document_asset`. Dagster
   drops a `deps=` edge whose target is outside the selection, so the race was
   **still live in the main E2E job** — a fix that holds in the abstract graph but
   not in the job people run. The executor flagged it as out-of-scope; it wasn't.
   Fixed in `76963c2`. The old exclusion cited Pitfall 6, but that rationale is
   about `generate_dataset` needing run config — `curate_document_asset` takes no
   Config, so it never applied.
2. The guard for it was **vacuous**. `job.asset_layer.asset_graph` *is* job-scoped
   (8 keys vs the global 13), but still contains curate as a NON-EXECUTABLE node
   pulled in by the `deps=` edge — so a pure ancestry assertion passed while the
   job never materialized curate. The test now intersects ancestry with
   `executable_asset_keys`. Mutation-verified: removing curate from the selection
   fails 2 tests; before the fix it failed only 1.

## Wave 3 — KL-10 (last, deliberately)

42 stale markers removed, 12 genuine xfails kept, `xfail_strict = true`.
Mutation-verified: marking a passing test xfail now fails the run with
`XPASS(strict)`. Per-test, never per-file — three files contained both kinds.

**The markers were hiding real bugs.** Removing them surfaced two new findings,
both recorded in `.planning/E2E-GAP-ANALYSIS.md`:

- **KL-18 (HIGH, open)** — `GET /documents` and `GET /datasets` return **500**.
  Responses are built outside the `get_session()` scope → `DetachedInstanceError`.
  Confirmed against the real app + real data. Two tests covered these endpoints
  but carried `xfail(reason="…not yet added")` — the reason was false; the
  endpoints exist and are broken. KL-08 compounded it: the stale container serves
  only 2 of 29 routes, so nobody hits them locally either.
- **KL-19 (LOW, open)** — 4 mode-forwarding tests patch
  `pipeline.search.search`, but `route.py` imports the name at module load, so
  the patch never applies and the tests can never pass. Test bug, not a
  production gap; `?mode=`/`--mode` are fully wired.

Neither was fixed here — both are outside this task's agreed scope. Marker reason
texts were corrected so they no longer lie.

## Verification (independently re-run by the orchestrator)

```
uv run pytest -m "not browser" -q      → 943 passed, 0 xpassed, 0 failed, 0 errors, 12 xfailed
uv run pytest tests/unit ...            → 739 passed
uv run pytest tests/integration ...     → 200 passed, 0 failed, 0 errors
uv run ruff check src/                  → All checks passed!
```

No regression to KL-01 (domain filtering), KL-02 (proxy cost), KL-03 (integration
tests in CI).

## Follow-ups

- **KL-18 is now the highest-priority open item** — real 500s, small fix, tests exist.
- KL-08, KL-09 remain from the original audit's mediums (not selected for this pass).
- KL-16's real gap (packs contributing Dagster jobs) → roadmap.
- DNS-rebinding TOCTOU in the SSRF guard → separate change.
- `ruff check tests/` has pre-existing lint debt (I001/F401/UP037), untouched — CI
  only lints `src/`.
