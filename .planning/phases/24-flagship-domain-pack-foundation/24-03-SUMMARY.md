---
phase: 24-flagship-domain-pack-foundation
plan: 03
subsystem: domain-packs
tags: [agent-security, quality-gate, chunk-substance-gate, gate-review, pitfall-9, phase-26-handoff]

# Dependency graph
requires:
  - phase: 24-flagship-domain-pack-foundation
    provides: "Real agent-security corpus (978/2163 rejected chunks, gate_mode=report) — 24-02"
provides:
  - "24-GATE-REVIEW-FINDINGS.md — real chunk_garbage_rate (45.21%), rejection-reason breakdown, per-source breakdown, 31 real quoted rejected-chunk samples, an explicit grounded yes/no judgment, and a named Phase 26 handoff"
affects: [26-quality-contract, 32-flagship-release]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Verify-command substitution for expensive re-derivation CLIs: direct SQLAlchemy queries against already-persisted Artifact.metadata_ rows instead of re-running a full parse+clean+chunk CLI command, when the underlying facts are already durable state (same pattern 24-02-SUMMARY.md established for its own verification)"
    - "Stratified + targeted-regex sampling for gate-review evidence: sample across every source (not DB insertion order, which was source-clustered) plus a corpus-wide regex scan for the literal named exemplars, to avoid both source bias and confirmation bias in the human-reviewed sample"

key-files:
  created:
    - .planning/phases/24-flagship-domain-pack-foundation/24-GATE-REVIEW-FINDINGS.md
  modified: []

key-decisions:
  - "klake quality-audit --domain agent-security --full --json was NOT run — confirmed via source inspection of run_full_pipeline_audit() that it re-derives parse->clean->chunk from scratch rather than reading persisted state; direct registry queries against Plan 24-02's already-persisted chunk Artifact rows produced the identical underlying facts in seconds instead of over an hour, mirroring 24-02's own identical substitution."
  - "Sampling strategy widened beyond the plan's literal 'first N rejected rows' framing: initial DB-order sampling of the first 25 rejected chunks returned only IETF RFC 6749 rows (an artifact of DB insertion/source ordering, not evidence of anything), so the final sample was stratified across all 7 sources (up to 4 each) plus a full-978-row targeted regex scan for the D-04-named exemplar shapes (permission scopes, mcp__ tool identifiers, CVSS/severity strings) to avoid both source-clustering bias and confirmation bias."
  - "Judgment nuance: the literal named exemplars (mcp__filesystem__read-style tool identifiers, read:documents-style permission scopes) were NOT found being wrongly rejected anywhere in the 978-row corpus (7 regex hits, all confirmed false positives on XML/CSS/JSON markup) — but real, structurally analogous domain content (OWASP vulnerability-taxonomy IDs, NIST AI RMF GOVERN/MAP/MEASURE/MANAGE subcategory nodes, NIST action-ID table rows) IS being wrongly rejected by the same thresholds, which is the actual, sample-grounded finding handed to Phase 26."

patterns-established: []

requirements-completed: []

coverage:
  - id: D1
    description: "Task 1: measured real chunk_garbage_rate (45.21%, 978/2163), rejection-reason breakdown, and per-source breakdown for the agent-security corpus via direct registry queries (quality-audit --full CLI substituted per documented deviation), plus a real, inspectable 31-row rejected-chunk sample with verbatim stored text read via storage.get_object()"
    verification:
      - kind: other
        ref: "Direct SQLAlchemy query against Source/Artifact rows (domain='agent-security'): 2163 total chunks, 978 rejected (substance_passed==False), rejection_reason breakdown captured verbatim in 24-GATE-REVIEW-FINDINGS.md Section 1"
        status: pass
    human_judgment: false
  - id: D2
    description: "Task 2: authored 24-GATE-REVIEW-FINDINGS.md containing the measurement, the real quoted sample, an explicit grounded yes/no judgment on whether agent-security domain content is wrongly dropped, and a named Phase 26 handoff — with no domains/agent-security/filters.yaml fix authored (Phase Boundary)"
    verification:
      - kind: other
        ref: "test -s 24-GATE-REVIEW-FINDINGS.md (non-empty); grep -c 'Phase 26' -> 6 hits; grep -c 'agent-security' -> 9 hits; test ! -f domains/agent-security/filters.yaml -> confirmed absent"
        status: pass
    human_judgment: true
    rationale: "Per the plan's own <verify><human-check> requirement, a human reviewer must confirm the judgment in Section 3 is genuinely grounded in the quoted sample (not a generic restatement of the question) before Phase 26 treats this as authoritative input. The document is written to be independently checkable against its own quoted evidence, but the judgment call itself is exactly the kind of finding PITFALLS.md Pitfall 9 requires a human, not just an agent, to sign off on."

# Metrics
duration: "~25min"
completed: 2026-07-22
status: complete
---

# Phase 24 Plan 03: Flagship Domain Pack Foundation — Gate Review Findings Summary

**Measured a real 45.21% chunk_garbage_rate (978/2163) against the live agent-security corpus and authored 24-GATE-REVIEW-FINDINGS.md: the bulk of rejections are genuine boilerplate (RFC footers, WordPress RSS feeds, CSS, cookie banners) correctly dropped, but a real minority of domain-specific taxonomy/framework content (OWASP vulnerability IDs, NIST AI RMF GOVERN/MAP/MEASURE/MANAGE subcategories, NIST action-ID table rows) is wrongly rejected by healthcare-tuned thresholds with no agent-security filters.yaml to protect it — handed off to Phase 26 by name.**

## Performance

- **Duration:** ~25 min
- **Started:** 2026-07-22T14:32:00Z (approx, per prior session STATE.md handoff)
- **Completed:** 2026-07-22T14:37:30Z
- **Tasks:** 2
- **Files modified:** 1 (created)

## Accomplishments

- **Task 1:** Measured the real, domain-scoped chunk-substance-gate rejection rate against Plan 24-02's already-persisted `agent-security` corpus via direct SQLAlchemy queries (not the plan's literal `klake quality-audit --full --json` command — see Deviations). Found 978/2163 chunks (45.21%) rejected, broken down by rejection reason (`line_punct_ratio`: 500, `short_line_ratio`: 400, `char_dup_ratio`: 51, plus smaller stopword/terminal-punct buckets) and by per-source rate (15.09% for NIST AI 600-1 up to 73.08% for IETF RFC 6749). Pulled a stratified, cross-source real rejected-chunk sample (up to 4 per source across all 7 sources) plus a targeted regex scan of all 978 rejected rows for the literal domain-specific exemplars CONTEXT.md D-04 names (permission scopes, `mcp__` tool identifiers, CVSS/severity strings), reading each sampled chunk's actual stored text via `storage.get_object()`/`uri_to_key()`.
- **Task 2:** Authored `.planning/phases/24-flagship-domain-pack-foundation/24-GATE-REVIEW-FINDINGS.md` — a four-section findings document: (1) the measurement with full breakdowns and the verify-command-substitution rationale, (2) 31 real, verbatim-quoted rejected-chunk rows split into "genuine boilerplate, correctly rejected" (rows 1-22) and "domain-specific content, plausibly wrongly rejected" (rows 23-28), each with its real `rejection_reason`, (3) an explicit, sample-grounded yes/no judgment — yes, with the specific qualification that the literal named exemplars weren't found being dropped, but structurally analogous real domain taxonomy/framework content was — and (4) a handoff to Phase 26 (Quality Contract) by name, describing in prose the shape a future `domains/agent-security/filters.yaml` allowlist should take (mirroring `domains/healthcare/filters.yaml`'s narrow-pattern convention per `DomainFilters`'s docstring warning against broad `.*` patterns), without creating that file.
- Confirmed `domains/agent-security/filters.yaml` does not exist — no fix was authored this phase, satisfying the Phase Boundary.

## Task Commits

1. **Task 1 + Task 2 (combined — Task 1 produced no repository files, only registry-query output consumed by Task 2's write):** `098a59b` (docs) — `.planning/phases/24-flagship-domain-pack-foundation/24-GATE-REVIEW-FINDINGS.md`

**Plan metadata:** (this commit, following SUMMARY.md/STATE.md/ROADMAP.md updates)

_Note: Task 1's action (direct registry queries + storage reads) is pure measurement with no repository file output — its evidence flows directly into Task 2's single committed file, so both tasks landed in one commit rather than two, matching how 24-02's task-boundary note handled its own no-repo-file tasks._

## Files Created/Modified

- `.planning/phases/24-flagship-domain-pack-foundation/24-GATE-REVIEW-FINDINGS.md` - Real gate-review findings: measurement, 31-row verbatim rejected-chunk sample, explicit judgment, Phase 26 handoff

## Decisions Made

1. **`klake quality-audit --domain agent-security --full --json` was not run.** Source inspection of `run_full_pipeline_audit()` (`pipeline/quality_audit.py`) confirmed it re-derives the corpus from `parse()` → `clean()` → `chunk()` from scratch rather than reading persisted state — a redundant, over-an-hour re-computation of work Plan 24-02 already did and persisted. Direct SQLAlchemy queries against `Source`/`Artifact` rows (scoped to `domain='agent-security'`, `artifact_type='chunk'`, filtered client-side on `metadata_.get('substance_passed') is False`) produced the identical underlying facts in seconds. This mirrors the exact substitution 24-02-SUMMARY.md documents for its own Task 2 verification.
2. **Sampling strategy widened beyond a naive "first N rejected rows" read.** An initial DB-order sample of the first 25 rejected chunks returned only IETF RFC 6749 rows — an artifact of insertion/source ordering in the database, not a representative or meaningful signal. The final sample was rebuilt as a stratified cross-source sample (up to 4 rejected rows per source, across all 7 sources) plus a full corpus-wide regex scan of all 978 rejected rows for the literal exemplar shapes CONTEXT.md D-04 names, to avoid both source-clustering bias and any temptation to cherry-pick a convenient sample.
3. **The judgment is "yes, with a qualification," not a flat yes or no.** The literal named exemplars (`mcp__filesystem__read`-style tool identifiers, `read:documents`-style permission scopes, CVSS strings) were searched for across every one of the 978 rejected rows and found zero genuine matches — the 7 regex hits were confirmed, by reading their full text, to be false positives on XML namespace declarations, CSS selectors, and WordPress REST JSON field names. But real, structurally analogous domain content — OWASP vulnerability-taxonomy IDs (`LLM05:2023`), NIST AI RMF's `GOVERN`/`MAP`/`MEASURE`/`MANAGE` subcategory nodes, and NIST action-ID table rows (`GV-1.1-001`) — genuinely is being wrongly rejected by the same thresholds. This is reported honestly as the actual finding rather than forcing a binary answer that doesn't match the evidence.

## Deviations from Plan

### Auto-fixed Issues

None — this plan's work is measurement and documentation, not code; Rules 1-3's auto-fix machinery does not apply.

### Process Deviations (documented per Rule 4-adjacent judgment, not code)

**1. Verify-command substitution — `klake quality-audit --domain agent-security --full --json` swapped for direct registry queries + a targeted regex scan (see Decision 1 above).**
- **Found during:** Task 1's action step, before execution began (flagged explicitly in this plan's own efficiency note, and independently confirmed by reading `run_full_pipeline_audit()`'s source).
- **Resolution:** Ran direct SQLAlchemy queries against already-persisted `Artifact` rows plus `storage.get_object()` reads of real chunk text, instead of the plan's literal CLI command.
- **Impact:** None on correctness — the same underlying facts (real `chunk_garbage_rate`, real rejection reasons, real chunk text) were gathered, in seconds instead of over an hour. Documented here (and again in the findings document itself, per the plan's own instruction) so a future auditor understands why the literal command's `/tmp/agent-security-audit.json` output described in the plan's Task 1 `<verify>` block does not exist as a standalone file — its facts are instead embedded directly in 24-GATE-REVIEW-FINDINGS.md Section 1.

**2. Sample construction widened beyond the plan's literal wording (see Decision 2 above) — stratified cross-source sampling + a full-corpus regex scan, not a simple first-N-rows read.**
- **Found during:** Task 1, immediately after the first DB-order sample returned single-source (IETF RFC 6749) results.
- **Resolution:** Rebuilt the sample to be stratified across all 7 sources and added a targeted regex scan across the full 978-row rejected population for the literal domain-specific shapes named in D-04, to make the eventual judgment genuinely evidence-grounded rather than an artifact of query ordering.
- **Impact:** Strengthens the finding's credibility — the plan's acceptance criterion ("at least 10-20 real rejected chunks... to judge whether the content is domain-specific short/structured material") is better served by a deliberately diverse sample than by whatever the database happened to return first.

---

**Total deviations:** 2 process-level deviations (verify-command substitution, sample-construction widening), 0 code auto-fixes.
**Impact on plan:** Neither represents a failure of the plan's actual goal — a real, evidence-grounded, honestly-qualified gate-review judgment was produced and handed off to Phase 26 exactly as CONTEXT.md D-04 and PITFALLS.md Pitfall 9 require. Both deviations are documented rather than hidden.

## Issues Encountered

None beyond the sampling-bias discovery documented as Decision 2 / Deviation 2 above, which was corrected within Task 1 before Task 2 consumed the sample.

## User Setup Required

None - no external service configuration required. PostgreSQL, Qdrant, MinIO, and the LiteLLM proxy were already running; this plan only read already-persisted registry/storage state (no writes to any of them).

## Next Phase Readiness

- `.planning/phases/24-flagship-domain-pack-foundation/24-GATE-REVIEW-FINDINGS.md` is the direct, real, evidence-backed input Phase 26 (Quality Contract) should consume when scoping and authoring `domains/agent-security/filters.yaml` — it names the specific real content shapes (OWASP taxonomy IDs, NIST AI RMF subcategory nodes, NIST action-ID table rows) that need normative-allowlist protection, plus the literal D-03 exemplars that should still be proactively included even though this specific corpus snapshot didn't surface a live rejected instance of them.
- No blockers for Plan 24-04 (Dataset Project scoping) — this plan's output is purely a documentation artifact with no registry/storage state changes, so it does not affect the corpus state 24-04 will scope its Dataset Project against.
- `domains/agent-security/filters.yaml` remains intentionally absent, confirming the Phase Boundary held.

---
*Phase: 24-flagship-domain-pack-foundation*
*Completed: 2026-07-22*

## Self-Check: PASSED

Verified `24-GATE-REVIEW-FINDINGS.md` exists on disk (`test -s` passed), contains 6 occurrences of "Phase 26" and 9 occurrences of "agent-security" (both grep counts re-confirmed at write time), and that `domains/agent-security/filters.yaml` does not exist. Verified commit `098a59b` exists in `git log --oneline` and contains exactly the one created file. No other file-existence or commit-hash claims made in this SUMMARY beyond what was directly re-checked.
