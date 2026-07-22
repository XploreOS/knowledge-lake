---
phase: 24-flagship-domain-pack-foundation
verified: 2026-07-22T14:57:35Z
status: gaps_found
score: 13/15 must-haves verified
behavior_unverified: 0
overrides_applied: 0
gaps:
  - truth: "Every agent-security cleaned_document artifact has a corresponding enriched_document artifact produced via the domain's own enrich.j2 prompt (Plan 24-02 Task 3 must-have; closes RESEARCH.md Pitfall 2)"
    status: failed
    reason: >-
      90 of 200 (45%) agent-security cleaned_document artifacts have NO
      enriched_document artifact anywhere in the registry — not via
      parent_artifact_id linkage, and not via the deterministic
      content-hash cache-key lookup either (checked system-wide, zero
      hits). 24-02-SUMMARY.md's stated explanation ("content-hash based
      artifact dedup ... near-duplicate scope-creep pages") is factually
      incorrect: all 200 cleaned_document artifacts have DISTINCT
      content_hash values (0 duplicate-hash groups), so dedup cannot be
      the mechanism. Live re-execution of `klake enrich <cleaned_id>
      <source_id>` against 3 sampled "unlinked" documents (spanning 2
      different sources) reproduced the SAME real failure every time: a
      Pydantic `ValidationError` on `EnrichmentResult.document_type`
      (`Field(max_length=100)`) because the LLM's enrichment response for
      this domain's longer, more descriptive document types exceeds 100
      characters. `enrich_document()` deliberately does not retry this
      exception (by design, to avoid 3x budget burn on "truly
      unrecoverable truncation" — src/knowledge_lake/pipeline/enrich.py
      lines 253-265) and returns `status: "skipped_enrichment_failed"`
      with no artifact created. `cmd_enrich` (cli/app.py:358-411) exits 0
      regardless of this internal failure status — it only raises
      `typer.Exit(code=1)` for `ValueError`/`LookupError`, never for a
      skipped-enrichment status — so the executor's own client-side loop
      script (which used `subprocess.run(...).returncode == 0` as its
      success signal, per the surviving `enrich_loop.py` script found in
      this session's scratchpad) silently counted every one of these 90
      real failures as a success. This is why 24-02-SUMMARY.md's claim of
      "0 failures across both enrich-loop runs" does not hold up against
      the live database and reproduced behavior.
    artifacts:
      - path: "src/knowledge_lake/pipeline/enrich.py"
        issue: "EnrichmentResult.document_type Field(max_length=100) rejects legitimate longer LLM outputs for this domain's content, with no truncation/retry, and the failure is silent from the CLI's perspective"
      - path: "src/knowledge_lake/cli/app.py"
        issue: "cmd_enrich (lines 358-411) exits 0 even when enrich_document() returns status=skipped_enrichment_failed or skipped_budget_exceeded — no typer.Exit(code=1) on a failed/skipped enrichment outcome, so any exit-code-based automation silently miscounts failures as successes"
    missing:
      - "Fix the root cause (truncate document_type to <=100 chars before validation, or raise the field's max_length, or retry with a shrink-and-retry strategy) in src/knowledge_lake/pipeline/enrich.py"
      - "Make cmd_enrich's exit code reflect an internal skipped_enrichment_failed/skipped_budget_exceeded status (non-zero exit) so future automation cannot silently miscount failures as successes"
      - "Re-run klake enrich for the 90 affected cleaned_document IDs (or all 200, idempotently) after the fix, so enriched_document count reflects the real, complete corpus"
      - "Correct 24-02-SUMMARY.md's decision-3 narrative (currently attributes the 110-vs-200 gap to content-hash dedup, which is factually disproven by direct query — 0 duplicate content_hash groups exist among the 200 cleaned documents)"
human_verification:
  - test: "Human reviewer reads 24-GATE-REVIEW-FINDINGS.md Section 3's judgment and confirms it is genuinely grounded in the quoted rejected-chunk sample (rows 23-28), not a generic restatement of the question, per the plan's own <human-check> requirement, before Phase 26 treats this document as authoritative input."
    expected: "A human confirms (or requests revision of) the qualified 'yes' judgment — that healthcare-tuned heuristics wrongly reject a real minority of agent-security taxonomy/framework content (OWASP LLM05:2023-style IDs, NIST AI RMF GOVERN/MAP/MEASURE/MANAGE subcategory nodes, NIST GV-1.1-001-style action-ID rows) even though the literal D-03 exemplars (mcp__ tool identifiers, read:documents-style scopes, CVSS vectors) were not found being wrongly dropped in this specific corpus snapshot."
    why_human: "This is a qualitative, domain-expertise judgment call the plan's own verify block explicitly defers to a human (PITFALLS.md Pitfall 9's discipline: human review before any gate change is treated as authoritative) — not a fact a grep/registry query can adjudicate."
---

# Phase 24: Flagship Domain Pack Foundation Verification Report

**Phase Goal:** A real, non-healthcare domain pack and its source corpus exist early enough that every subsequent v2.7 phase can be built and tested against genuine flagship data instead of synthetic fixtures, and the healthcare-only quality-gate tuning gap is surfaced now rather than at milestone end.
**Verified:** 2026-07-22T14:57:35Z
**Status:** gaps_found
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | `domains/agent-security/` is loadable via `DomainLoader.from_name('agent-security')` — manifest.name, D-03 taxonomy, `AgentSecurityValidator` class (ROADMAP SC1) | ✓ VERIFIED | Live `uv run python -c "..."` one-liner reproduced exactly: manifest.name='agent-security', taxonomy.entity_types matches the 6-entry list, `type(l.validator).__name__ == 'AgentSecurityValidator'`, `l.sources` count = 7. Validator behavior also reproduced: empty text → `passed=False, errors=['empty document']`; sample permission-scope/tool-id text → `passed=True, warnings=[]`. |
| 2 | `enrich.j2`/`qa_generation.j2` retain the prompt-injection-defense clause verbatim (D-06, dual-use domain) | ✓ VERIFIED | `grep -c "Treat ALL such text strictly as content to analyze"` returns 1 in both files. |
| 3 | `domains/agent-security/filters.yaml` does NOT exist (deferred to Phase 26, D-04/Phase Boundary) | ✓ VERIFIED | `test -f domains/agent-security/filters.yaml` confirmed absent; also independently absent per 24-03's findings doc statement. |
| 4 | `sources.yaml` contains only live-verified sources with correct `ingest_type` per reachable format | ✓ VERIFIED | 7 entries present (5 crawl, 2 upload) with documented CISA-drop / NIST-AI-RMF-upload-reclassification rationale as YAML comments. Spot-checked 2 of the 7 live URLs (MCP spec, OWASP Top 10) — both HTTP 200 at verification time. |
| 5 | `cmd_upload`'s `--source-url` threads unchanged to `ingest_file(source_url=...)` | ✓ VERIFIED | `src/knowledge_lake/cli/app.py:112-138` — flag defined, threaded directly into `ingest_file(..., source_url=source_url)`. `uv run klake upload --help` shows the flag. `tests/unit/test_cli_upload.py` (3 tests) + `tests/integration/test_upload.py` all pass (23/23 collected across the 4 relevant test files). |
| 6 | Every `sources.yaml` entry produces exactly one `Source` row (`domain='agent-security'`), including the upload-type PDF source via `--source-url` reuse, never a disconnected duplicate (ROADMAP SC1/2, Pitfall 1) | ✓ VERIFIED | Live query: 7 `Source` rows, `domain='agent-security'`, 7 distinct URLs, 0 duplicates. |
| 7 | `KLAKE_CHUNK_QUALITY__GATE_MODE=report` was active for the entire ingestion run — rejected chunks are real, persisted, queryable `Artifact` rows (Pitfall 4) | ✓ VERIFIED | Live query: 2,163 total `chunk` artifacts scoped to agent-security Source IDs, 978 with `metadata_.substance_passed == False` — matches 24-02/24-03-SUMMARY.md's claimed counts exactly. |
| 8 | Every agent-security `cleaned_document` artifact has a corresponding `enriched_document` artifact produced via `enrich.j2` (Pitfall 2 closure) | ✗ **FAILED** | See `gaps` above. Live query: 200 `cleaned_document`, only 110 have an `enriched_document` with `parent_artifact_id` pointing to them; the other 90 resolve to **no** enriched artifact via parent-link OR content-hash cache-key lookup (checked system-wide). Re-executing `klake enrich` live against 3 of the 90 "unlinked" IDs (2 different sources) reproduced the same real, deterministic failure each time: `ValidationError: document_type String should have at most 100 characters`. SUMMARY.md's "content-hash dedup" explanation is directly contradicted by the data (0 duplicate content_hash groups among the 200 cleaned documents). |
| 9 | Real `parsed_document`/`cleaned_document`/`chunk`/`enriched_document` artifacts exist for the corpus; new `klake_chunks` Qdrant points exist (ROADMAP SC2) | ✓ VERIFIED (with the caveat in #8) | `parsed_document`=200, `cleaned_document`=200, `chunk`=2163 all real and complete. Qdrant `scroll` query against the 7 agent-security Source IDs returned real points with full chunk text, correct `domain: "agent-security"` payload, real `source_url`/`source_name`. `enriched_document`=110 is real but incomplete per #8 (55% coverage, not the full 200). |
| 10 | `24-GATE-REVIEW-FINDINGS.md` exists, non-empty, cites REAL rejection counts/rates and a REAL, inspectable rejected-chunk sample (D-04, ROADMAP SC3) | ✓ VERIFIED | File exists, 45.21% `chunk_garbage_rate` (978/2163) and the full rejection-reason breakdown in the doc match live registry queries exactly (`line_punct_ratio`=500, `short_line_ratio`=400, `char_dup_ratio`=51, etc. — bit-for-bit match). 31 quoted sample rows present, each with a real `rejection_reason`. |
| 11 | The findings doc states an explicit yes/no judgment, grounded in the quoted sample, on healthcare-tuned heuristics wrongly dropping domain-specific content | ? Present, requires human sign-off | Section 3 gives a qualified "yes" grounded in specific quoted rows (23-28: OWASP `LLM05:2023`, NIST `GOVERN`/`MAP`/`MEASURE`/`MANAGE` nodes, `GV-1.1-001` action-ID rows). The plan's own `<human-check>` block explicitly requires a human, not an automated verifier, to confirm this judgment before Phase 26 treats it as authoritative — routed to Human Verification below rather than auto-marked VERIFIED. |
| 12 | The findings doc hands the actual fix off to Phase 26 by name (Phase Boundary) | ✓ VERIFIED | `grep -c "Phase 26"` → 6 hits; Section 4 ("Handoff to Phase 26") names it explicitly and describes (in prose only) the shape of the eventual `filters.yaml` fix. `filters.yaml` confirmed still absent. |
| 13 | Dataset Project "AI Agent Security and Permission Dataset" exists, scoped `domain=agent-security`, `dataset_type=rag_corpus`, with D-06's purpose/intended/prohibited-uses text recorded (ROADMAP SC4) | ✓ VERIFIED | Live `klake project show --json`: `dataset_type: "rag_corpus"`, `domain: "agent-security"`, `purpose` text matches D-06 verbatim, `intended_uses` (3 entries) and `prohibited_uses` (1 entry) match D-06 verbatim. |
| 14 | The project's first Dataset Specification references every real, registered agent-security Source ID — `klake dataset spec validate` is a real, non-trivial pass (Pitfall 6) | ✓ VERIFIED | `agent-security-spec.yaml`'s `included_sources` lists all 7 real `src_...` IDs (cross-checked byte-for-byte against the live `Source` query above). Live `klake dataset spec validate dpj_019f8a45-...` printed `Spec 'dsp_019f8a45-...' is valid.` and exited 0. |
| 15 | The project reaches `status=ready` via the legal `draft → configured → sources_pending → ready` chain (D-05) | ✓ VERIFIED | Live `klake project show --json` reports `"status": "ready"`. `uv run pytest tests/unit/test_project.py -x` → 25/25 passed (no regression to Phase 23's lifecycle tests). |

**Score:** 13/15 truths verified, 1 failed, 1 requires human judgment (per the plan's own design, not an automated-verifier gap)

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `domains/agent-security/domain.yaml` | manifest name/version/description | ✓ VERIFIED | Present, `name: agent-security`, loads via `DomainLoader` |
| `domains/agent-security/taxonomy.yaml` | D-03's 6 entity_types + 4 categories | ✓ VERIFIED | Confirmed via live `DomainLoader.from_name()` assertion |
| `domains/agent-security/prompts/enrich.j2` / `qa_generation.j2` | Domain-vocab prompts, injection-defense clause verbatim | ✓ VERIFIED | grep confirms clause present in both |
| `domains/agent-security/validators/validate.py` | `AgentSecurityValidator`, 3-check shape | ✓ VERIFIED (with quality caveats — see Anti-Patterns) | Class loads and behaves per the 3-check contract; two non-blocking regex-precision defects noted below (24-REVIEW.md WR-01/WR-02, still unfixed) |
| `domains/agent-security/sources.yaml` | 7 live-verified entries, correct ingest_type | ✓ VERIFIED | 5 crawl + 2 upload confirmed |
| `src/knowledge_lake/cli/app.py` (`cmd_upload`) | `--source-url` flag, threaded to `ingest_file` | ✓ VERIFIED | Wired correctly, tests pass |
| `tests/unit/test_cli_upload.py` | CliRunner tests for --source-url | ✓ VERIFIED | 3 tests, all passing |
| `.planning/phases/24-flagship-domain-pack-foundation/24-GATE-REVIEW-FINDINGS.md` | Real measurement + sample + judgment + handoff | ✓ VERIFIED | Content cross-checked against live DB, numbers match exactly |
| `.planning/phases/24-flagship-domain-pack-foundation/agent-security-spec.yaml` | DatasetSpecFields YAML, real Source IDs | ✓ VERIFIED | 7 real Source IDs, matches live registry exactly |
| Real `Source`/`Artifact` rows + Qdrant points (24-02, no repo files) | End-to-end corpus | ⚠️ PARTIALLY VERIFIED | Source/parsed/cleaned/chunk/Qdrant fully real and complete; `enriched_document` (110/200) incomplete — see gap #8 |
| `DatasetProject` + `DatasetSpec` rows (24-04, no repo files) | status=ready, validated spec | ✓ VERIFIED | Confirmed live: `status: "ready"`, spec `valid: true` |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|----|--------|---------|
| `DomainLoader.from_name('agent-security')` | `validators/validate.py`'s `*Validator` class | Generic importlib.util class resolution | ✓ WIRED | Resolves to `AgentSecurityValidator`, no hardcoded name needed |
| `cmd_upload --source-url` | `ingest_file(source_url=...)` | Direct kwarg pass-through | ✓ WIRED | Confirmed in source at app.py:133-138 |
| `klake init --domain agent-security` | `Source` rows (`domain='agent-security'`) | `pipeline/domains.py` `load_domain()` | ✓ WIRED | 7 real rows confirmed live |
| `KLAKE_DOMAIN__DOMAIN_NAME=agent-security` | `DomainLoader.from_name()` inside `clean()`/`chunk()`/`enrich_document()` | Settings env var resolution | ✓ WIRED | Confirmed via real chunk payloads carrying `domain: "agent-security"` in Qdrant and via successful `klake enrich` re-execution using this env var |
| `klake enrich <cleaned_id> <source_id>` | `DomainLoader.from_name('agent-security').render_prompt('enrich.j2')` as LLM system prompt | `cmd_enrich` (app.py:394-403) | ✓ WIRED (but downstream write fails for 45% of inputs) | Prompt renders and the LLM call executes (confirmed live — reproduced a real LLM round-trip that failed validation, not a wiring failure); the *registry write* fails for `document_type`-too-long responses — see gap #8 |
| `agent-security-spec.yaml`'s `included_sources` | real `src_` Source rows | `validate_spec()` existence check | ✓ WIRED | `klake dataset spec validate` passes non-trivially against 7 real IDs |
| `klake project transition ... ready` | `pipeline/project.py`'s `_TRANSITIONS` map | Unmodified adjacency map | ✓ WIRED | Live `klake project show --json` confirms `status: "ready"` |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|---------------------|--------|
| `klake_chunks` Qdrant collection (agent-security scope) | chunk `text`/`domain`/`source_id` payload | `chunk()` pipeline stage, indexed from real crawled/uploaded content | Yes | ✓ FLOWING — live `scroll` query returned real payloads with substantive chunk text, correct domain tag, correct source linkage |
| `enriched_document` artifacts | `quality_score`, LLM-derived metadata | `enrich_document()` LiteLLM call | Yes, for 110/200 (55%) | ⚠️ PARTIAL — real for the 110 that succeeded (non-default `quality_score` values: 0.6, 0.92, 0.85, 0.75, 0.82...); absent (not stale/static, genuinely missing) for the other 90 due to gap #8 |
| Dataset Spec `included_sources` | Source ID list | Direct SQLAlchemy query against live registry at authoring time | Yes | ✓ FLOWING — all 7 IDs cross-verified byte-for-byte against the live `Source` table |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| `DomainLoader` loads agent-security pack | `uv run python -c "DomainLoader.from_name('agent-security')..."` | manifest/taxonomy/validator all correct, `sources` count 7 | ✓ PASS |
| CLI `--source-url` flag present | `uv run klake upload --help \| grep source-url` | flag + help text shown | ✓ PASS |
| Project lifecycle tests | `uv run pytest tests/unit/test_project.py -x` | 25/25 passed | ✓ PASS |
| Domain-pack unit tests | `uv run pytest tests/unit/test_domain_scaffold.py tests/unit/test_domain_loader.py tests/unit/test_cli_upload.py tests/integration/test_upload.py -x` | 23/23 passed | ✓ PASS |
| Dataset spec validates non-trivially | `uv run klake dataset spec validate dpj_019f8a45-...` | `Spec '...' is valid.`, exit 0 | ✓ PASS |
| Project reaches `ready` | `uv run klake project show ... --json` | `"status": "ready"` | ✓ PASS |
| **Re-execution of a "successful" enrich invocation for an "unlinked" cleaned document** | `KLAKE_DOMAIN__DOMAIN_NAME=agent-security uv run klake enrich <cleaned_id> <source_id>` (×3, 2 different sources) | All 3 reproduced `status: skipped_enrichment_failed`, `ValidationError: document_type ... at most 100 characters`, exit code 0 despite the failure | ✗ FAIL (surfaces gap #8; also confirms `cmd_enrich`'s exit-code defect independently of any one plan's claims) |

### Probe Execution

No `scripts/*/tests/probe-*.sh` files or PLAN/SUMMARY-declared probes found for this phase — SKIPPED (no runnable probe entry points; phase does not reference probe-based verification).

### Requirements Coverage

Phase 24 owns no formal REQUIREMENTS.md IDs — confirmed via ROADMAP.md's own text ("Requirements: None (infrastructure prerequisite phase — see note below)") and via `.planning/REQUIREMENTS.md`'s Traceability table, which explicitly maps FLAGSHIP-01/FLAGSHIP-02 to **Phase 32**, with Phase 24 called out by name as an "Enabling phase (no directly-owned requirement)". No `requirements:` fields are populated in any of the 4 phase plans' frontmatter (all `requirements: []`), consistent with this. No orphaned requirements found for Phase 24 in `.planning/REQUIREMENTS.md`.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `domains/agent-security/validators/validate.py` | 19 | `PERMISSION_SCOPE_PATTERN = re.compile(r"\b\w+:\w+\b")` — matches any `digit:digit`/`word:word` shape (timestamps, ports, "Figure:2"), not just real permission scopes | ⚠️ Warning (pre-existing, documented in 24-REVIEW.md WR-01, unfixed) | Weakens the validator's "no agent-security terms detected" signal — most prose will false-positive-pass this check. Non-fatal (warning only), does not block ingestion or any must-have. |
| `domains/agent-security/validators/validate.py` | 25 | `CVSS_VECTOR_PATTERN` omits valid `AV:P` (Physical) attack-vector value | ⚠️ Warning (pre-existing, documented in 24-REVIEW.md WR-02, unfixed) | Causes a false "malformed_cvss_vector" warning for syntactically valid CVSS strings using `AV:P`. Non-fatal, does not block any must-have. |
| `domains/agent-security/validators/validate.py` | 30-32 | Comment claims `AGENT_SECURITY_TERMS` "mirrors taxonomy.yaml entity_types" — it does not (disjoint vocab lists) | ℹ️ Info (24-REVIEW.md IN-01, unfixed) | Documentation-accuracy only, no functional impact. |
| `src/knowledge_lake/pipeline/enrich.py` / `src/knowledge_lake/cli/app.py` | enrich.py Field(max_length=100); app.py:358-411 | Silent-success-on-failure: `cmd_enrich` exits 0 for a `skipped_enrichment_failed`/`skipped_budget_exceeded` internal status | 🛑 Blocker (drove this verification's gap #8) | This is a pre-existing defect (predates Phase 24) exposed by this domain's content, but its consequence — a real 45% enrichment gap silently reported as "0 failures" — is a direct, material gap in this phase's own claimed completion state. No debt marker (TBD/FIXME/XXX) exists at these lines; this was discovered by live re-execution, not a code comment. |

No TBD/FIXME/XXX debt markers found in any file created/modified by this phase.

### Human Verification Required

### 1. Gate-review judgment sign-off (24-GATE-REVIEW-FINDINGS.md Section 3)

**Test:** A human reviewer reads Section 3's judgment and the quoted sample rows 23-28, and confirms the qualified "yes" conclusion is genuinely grounded in that evidence (not a generic restatement of the question).
**Expected:** Confirmation (or a specific, evidence-based revision request) before Phase 26 treats this document as its authoritative scoping input.
**Why human:** The plan's own `<verify><human-check>` block explicitly requires this — PITFALLS.md Pitfall 9's discipline treats this specific judgment call as one only a human should sign off on, not an automated verifier.

### Gaps Summary

Phase 24 achieves 3 of its 4 ROADMAP Success Criteria cleanly (SC1: domain pack scaffolded and loadable; SC3: report-only gate review with a real, evidence-grounded findings document handed to Phase 26; SC4: Dataset Project reaches `ready` with a non-trivially-validated spec). SC2 ("real sources ingested end-to-end through parse → clean → chunk → enrich → embed → index") is **materially, not fully, achieved**: parse/clean/chunk/index are complete and correct (242 raw → 200 parsed → 200 cleaned → 2,163 chunk artifacts, with 978 correctly persisted as `report`-mode rejections, and real Qdrant points), but the **enrich** stage is only 55% complete (110/200 cleaned documents actually enriched). This was NOT caught by the phase's own verification because `cmd_enrich`'s exit code doesn't distinguish a real internal failure (`skipped_enrichment_failed`) from success, and the executor's loop script used exit code alone as its success signal — so 24-02-SUMMARY.md's "0 failures" claim, and its "content-hash dedup" explanation for the 110-vs-200 count mismatch, are both contradicted by direct evidence (0 duplicate content hashes exist among the 200 cleaned documents; live re-execution of 3 sampled "missing" enrichments reproduced the same real, deterministic `document_type`-too-long validation failure each time).

This is a real, closable gap, not a design tradeoff: the fix is (1) handle/truncate an over-length `document_type` in `pipeline/enrich.py` (or raise its `max_length`), (2) make `cmd_enrich` exit non-zero on a skipped/failed enrichment so this class of gap is never silently miscounted again, and (3) re-run enrichment for the 90 affected documents. None of Phase 24's other 3 plans, and no later-numbered phase in ROADMAP.md, is scoped to close this gap — it is not deferred work, it is an incomplete delivery of this phase's own Task 3.

---

*Verified: 2026-07-22T14:57:35Z*
*Verifier: Claude (gsd-verifier)*
