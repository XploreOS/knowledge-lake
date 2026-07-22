---
phase: 24-flagship-domain-pack-foundation
plan: 06
subsystem: domain-packs
tags: [agent-security, enrich, gap-closure, pydantic, validation, keywords]

# Dependency graph
requires:
  - phase: 24-flagship-domain-pack-foundation
    provides: "Plan 24-05's two root-cause fixes — EnrichmentResult.document_type truncation (mode='before' field_validator) and cmd_enrich exiting non-zero on any skipped_* status"
provides:
  - "89 of the 90 agent-security cleaned_document artifacts that were missing an enriched_document sibling at 24-VERIFICATION.md gap #8's verification time now have one, produced via genuine post-Plan-24-05-fix klake enrich re-invocations"
  - "A corrected .planning/phases/24-flagship-domain-pack-foundation/24-02-SUMMARY.md — the factually-incorrect 'content-hash based artifact dedup' explanation for the original 110-vs-200 mismatch is replaced/annotated with the real root cause (document_type-length ValidationError, silently reported as success by the pre-fix cmd_enrich)"
  - "A newly discovered, genuinely different, out-of-scope Pydantic validation defect: EnrichmentResult.keywords Field(max_length=20) rejects a real 21-item keyword list this domain's LLM output legitimately produced — surfaced honestly, not fixed, not hidden, not silently retried"
affects: [26-quality-contract, 32-flagship-release]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Fresh live re-query of the exact parent-link (get_child_artifact_by_type) check a verifier used to prove a gap, executed at gap-closure execution time rather than trusting a planning-time ID/count snapshot — the corpus may have shifted"
    - "Honest partial-closure reporting: when a genuinely new, different failure mode is discovered mid-remediation, it is surfaced verbatim (exact error text, exact artifact ID) rather than retried into passing or silently patched to claim full success"

key-files:
  created: []
  modified:
    - .planning/phases/24-flagship-domain-pack-foundation/24-02-SUMMARY.md

key-decisions:
  - "Task 1 produced zero repository file changes (registry/vector-index state only), matching the plan's own empty <files> declaration — no per-task commit for Task 1, mirroring 24-02 Task 2/3's and 24-04 Task 2's same precedent for this class of task."
  - "The 1 residual EnrichmentResult.keywords max_length=20 failure was NOT fixed as part of this plan — per this plan's own explicit prohibition against treating a residual, non-document_type-length failure as acceptable or silently retrying it into passing. It is surfaced here as a new, out-of-scope gap for a future remediation round to address, exactly as it was found."

patterns-established: []

requirements-completed: []

coverage:
  - id: D1
    description: "Re-ran klake enrich for every real, currently-missing agent-security cleaned_document artifact (queried fresh at execution time, not assumed from planning context) — 89/90 succeeded via Plan 24-05's fix; enriched_document count is 199 (not 200) for agent-security Source IDs, with the 1 residual failure being a new, different, out-of-scope defect (EnrichmentResult.keywords max_length=20), honestly surfaced rather than hidden or silently retried"
    verification:
      - kind: other
        ref: "Live query (uv run python -c '...' against get_session()/get_child_artifact_by_type): cleaned=200, enriched=199, MISSING count=1 (doc_019f87ec-bcf0-7ce0-a426-e2242f090204). Full re-run log at scratchpad enrich_loop_2406.log: total=90, success=89, failed=1."
        status: fail
    human_judgment: true
    rationale: "Full count-equality (200/200) was NOT achieved — a genuinely new, different validation defect (not the document_type-length bug this plan targeted) blocks the last artifact. A human must decide whether to schedule a follow-up gap-closure round for this new defect or accept the corpus at 199/200 for now; this is a judgment call about scope and priority, not a fact an automated verifier alone should silently resolve."
  - id: D2
    description: "Corrected 24-02-SUMMARY.md's factually-incorrect content-hash-dedup explanation for the original 110-vs-200 mismatch, replacing/annotating it with the real root cause, and additionally documenting this plan's own new residual finding"
    verification:
      - kind: other
        ref: "grep -c CORRECTION .planning/phases/24-flagship-domain-pack-foundation/24-02-SUMMARY.md -> 6; grep -c CORRECTED -> 6; grep -c content-hash -> 5 (preserved, not deleted); grep -c document_type -> 3 (real root cause now named)"
        status: pass
    human_judgment: false

# Metrics
duration: ~16min
completed: 2026-07-22
status: complete
---

# Phase 24 Plan 06: Enrichment Gap Re-Run + 24-02-SUMMARY.md Correction Summary

**Re-ran `klake enrich` for all 90 agent-security cleaned_document artifacts that were missing an enriched_document sibling — 89 succeeded via Plan 24-05's document_type-truncation fix, 1 surfaced a new, different, out-of-scope `keywords` list-length validation defect (not fixed, not hidden) — and corrected 24-02-SUMMARY.md's factually-wrong content-hash-dedup explanation in place.**

## Performance

- **Duration:** ~16 min
- **Started:** 2026-07-22T15:21:27Z
- **Completed:** 2026-07-22T15:37:06Z
- **Tasks:** 2
- **Files modified:** 1

## Accomplishments

- **Task 1:** Queried live, fresh (not from planning-time assumptions) the exact set of agent-security `cleaned_document` artifacts still missing an `enriched_document` sibling, using the identical `get_child_artifact_by_type()` parent-link check 24-VERIFICATION.md's own verifier used to prove gap #8. Found 90 missing pairs (matching the planning-time count, confirmed independently rather than assumed) and wrote them to a scratchpad pairs file. Ran `KLAKE_DOMAIN__DOMAIN_NAME=agent-security uv run klake enrich <cleaned_id> <source_id>` for every one of the 90, as a real, non-truncating-piped background loop logging full stdout/stderr and exit codes per invocation.
  - **89/90 succeeded** with `status: enriched`, exit code 0 — direct, live proof that Plan 24-05's `EnrichmentResult.document_type` truncation fix resolves the real root cause of gap #8 in production against real LLM output.
  - **1/90 failed** (`doc_019f87ec-bcf0-7ce0-a426-e2242f090204`, source `src_019f87d4-1157-7272-a168-1774a4cfd588`) with a **genuinely new, different** Pydantic `ValidationError`: `EnrichmentResult.keywords` `Field(max_length=20)` rejected a real 21-item keyword list (`['MCP', 'Model Context Pr...ystem', 'authorization']`, `too_long`) — a sibling defect on the `keywords` list-length bound, not the `document_type` string-length bound Plan 24-05 fixed. Per this plan's own explicit prohibition, this residual failure was **not** retried, patched, or hidden — it is surfaced here verbatim.
  - Fresh post-run count-equality query: `cleaned_document`=200, `enriched_document`=199 for agent-security Source IDs. **Full parity (200/200) was NOT achieved.** The remaining gap is exactly 1 artifact, caused by the new keywords-length defect described above.
- **Task 2:** Added a `## CORRECTION (Phase 24 Gap Closure, Plans 24-05/24-06)` section to `24-02-SUMMARY.md`, placed immediately after the H1 title, stating plainly that the original "content-hash based artifact dedup" explanation for the 110-vs-200 mismatch was factually wrong (0 duplicate `content_hash` groups existed among the 200 cleaned documents), naming the real root cause (`EnrichmentResult.document_type` `Field(max_length=100)` ValidationError, silently reported as success by the pre-fix `cmd_enrich`), and honestly recording this plan's own partial-closure outcome (89/90, not 90/90, plus the new keywords-length finding). Added 5 inline `[CORRECTED ...]` annotations at every location that repeated the incorrect claim (frontmatter `key-decisions` bullet, frontmatter `coverage` D3 `rationale`, "## Decisions Made" item 3, "## Deviations from Plan" → "Process Deviations" item 3, "## Next Phase Readiness" bullet) — all original text preserved verbatim, none deleted.

## Task Commits

Task 1 produced zero repository file changes (registry/vector-index state only, matching the plan's own empty `<files>` declaration for this task) — no per-task commit exists for Task 1, mirroring Plan 24-02 Task 2/3's and Plan 24-04 Task 2's identical precedent for this class of task.

1. **Task 2: Correct 24-02-SUMMARY.md's factually-incorrect content-hash-dedup explanation** — `0fd700c` (docs)

**Plan metadata:** (this commit)

## Files Created/Modified

- `.planning/phases/24-flagship-domain-pack-foundation/24-02-SUMMARY.md` - Added `## CORRECTION` section (naming the real root cause and this plan's own partial-closure outcome) plus 5 inline `[CORRECTED ...]` annotations at every location that repeated the incorrect content-hash-dedup explanation; all original text preserved.

No other repository files were modified — Task 1's output is registry/vector-index state only (89 new `enriched_document` Artifact rows for the agent-security corpus), per the plan's own objective ("no new repository files").

## Decisions Made

1. **Task 1 gets no per-task commit** — its entire output is database state (89 new `enriched_document` rows), not repository files, matching the plan's own empty `<files>` declaration and the precedent set by Plan 24-02 Task 2/3 and Plan 24-04 Task 2 for this exact class of task.
2. **The 1 residual `keywords`-length failure was left unfixed, by design.** This plan's own explicit prohibition states: "MUST NOT treat a residual `klake enrich` failure during the re-run (one NOT explained by the document_type-length root cause Plan 24-05 fixed) as acceptable or silently retried into passing — any such failure is a new, out-of-scope gap that MUST be surfaced verbatim in this plan's SUMMARY, not hidden." This is exactly that case: a new, different Pydantic bound (`EnrichmentResult.keywords` `Field(max_length=20)`) rejected legitimate LLM output for this one document. Fixing it would require the same category of code change Plan 24-05 made for `document_type` (truncate vs. raise vs. retry) — an architectural-adjacent decision squarely out of this plan's declared scope. It is documented here, not patched.

## Deviations from Plan

### Auto-fixed Issues

None — no code changes were made or needed. This plan's Task 1 work is purely operational (re-running a CLI command against real, currently-missing artifacts); Task 2's work is a documentation correction. Neither triggers Rules 1-3's auto-fix machinery.

### Process Deviations

**1. Full count-equality (200/200) was not achieved — 1 residual, genuinely new failure surfaced instead of hidden.**
- **Found during:** Task 1's post-loop verification step.
- **What happened:** 89 of the 90 missing `cleaned_document` artifacts were successfully re-enriched. The 90th (`doc_019f87ec-bcf0-7ce0-a426-e2242f090204`) failed with a Pydantic `ValidationError` on `EnrichmentResult.keywords` (`Field(max_length=20)`, actual LLM output had 21 items) — a different field, a different bound, and a different failure mode than the `document_type`-length defect this plan (and Plan 24-05's fix) targeted.
- **Resolution:** Per this plan's own explicit prohibition, this failure was NOT retried, NOT silently patched, and NOT reported as success. It is documented here verbatim, with the exact artifact ID, exact error text, and exact post-run count (199 enriched vs. 200 cleaned) recorded both here and in the corrected 24-02-SUMMARY.md.
- **Impact:** ROADMAP.md Success Criterion 2's "enrich" stage for the agent-security corpus is now at 199/200 (99.5%), a decisive improvement over the pre-fix 110/200 (55%), but is not fully, literally complete. A follow-up gap-closure round (or a note carried into a future phase) is recommended to address the `EnrichmentResult.keywords` max_length bound — see "Next Phase Readiness" below.

---

**Total deviations:** 1 process-level deviation (residual new failure honestly surfaced, not remediated), 0 code auto-fixes.
**Impact on plan:** The plan's core objective — re-running enrichment against every currently-missing artifact using Plan 24-05's fix, and correcting the historical record — is fully achieved. The plan's aspirational full-parity outcome (200/200) is not, because a second, previously-unknown defect exists in the same validation schema. This is documented honestly, exactly as the plan's own prohibitions require, rather than glossed over.

## Issues Encountered

- **A second, previously-undetected Pydantic validation bound defect exists in `EnrichmentResult`** (`keywords: list[str] = Field(default_factory=list, max_length=20)`), sibling to the `document_type` bound Plan 24-05 fixed. This domain's LLM output legitimately produces keyword lists longer than 20 items for at least 1 real document in the corpus. Not fixed in this plan (explicitly out of scope per the plan's own prohibitions) — recorded here and in 24-02-SUMMARY.md's CORRECTION section as a known, tracked residual gap.

## User Setup Required

None - no external service configuration required. PostgreSQL, Qdrant, MinIO, and the LiteLLM proxy were already running and used directly.

## Next Phase Readiness

- The agent-security corpus's enrichment coverage is now 199/200 (99.5%), up from the pre-Plan-24-05/24-06 measured 110/200 (55%). This is a decisive, real improvement, directly attributable to Plan 24-05's `document_type` truncation fix — 89 live re-invocations against real previously-failing documents all succeeded.
- **One artifact remains unenriched**: `doc_019f87ec-bcf0-7ce0-a426-e2242f090204` (source `src_019f87d4-1157-7272-a168-1774a4cfd588`), blocked by `EnrichmentResult.keywords` `Field(max_length=20)` rejecting a real, legitimate 21-item keyword list. **Recommendation:** schedule a small follow-up gap-closure round (mirroring this plan's own shape: truncate/bound the `keywords` list before Pydantic validation, analogous to Plan 24-05's `document_type` fix, then re-run `klake enrich` once for this single artifact) — or explicitly accept 199/200 as the corpus's enrichment-completeness baseline for Phase 26/32 if the 1-document gap is judged immaterial. This is a human/product decision, not one this plan's own scope authorizes resolving unilaterally.
- 24-02-SUMMARY.md's historical record is now accurate: the content-hash-dedup explanation is corrected in place (annotated, not deleted), and the document now honestly reflects both Plan 24-05's real fix and this plan's own partial-closure outcome.
- No blocker for Phase 26 (quality-contract) or Phase 32 (flagship release) — both should be aware the agent-security corpus is at 199/200 enriched artifacts, not the full 200, when scoping any enrichment-completeness-dependent work.

---
*Phase: 24-flagship-domain-pack-foundation*
*Completed: 2026-07-22*

## Self-Check: PASSED

`.planning/phases/24-flagship-domain-pack-foundation/24-02-SUMMARY.md` confirmed present on disk with the CORRECTION section and 5 inline annotations. Commit `0fd700c` confirmed present in `git log --oneline --all`. Live registry re-query at write time reconfirmed: cleaned=200, enriched=199, 1 missing pair (`doc_019f87ec-bcf0-7ce0-a426-e2242f090204`), matching every count claimed in this SUMMARY.
