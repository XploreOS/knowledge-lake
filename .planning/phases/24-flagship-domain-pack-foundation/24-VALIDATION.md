---
phase: 24
slug: flagship-domain-pack-foundation
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-21
---

# Phase 24 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x + pytest-asyncio (`asyncio_mode = "auto"`), configured in `pyproject.toml` |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` (`testpaths = ["tests"]`, `xfail_strict = true`) |
| **Quick run command** | `uv run pytest tests/unit/test_domain_scaffold.py tests/unit/test_domain_loader.py tests/unit/test_project.py -x` |
| **Full suite command** | `uv run pytest tests/unit tests/integration -x` |
| **Estimated runtime** | ~90 seconds (quick) / ~10 minutes (full) |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/unit/test_domain_scaffold.py tests/unit/test_domain_loader.py tests/unit/test_project.py -x`
- **After every plan wave:** Run `uv run pytest tests/unit tests/integration -x`
- **Before `/gsd-verify-work`:** Full suite must be green, PLUS the 4 manual/smoke verifications below
- **Max feedback latency:** 90 seconds

---

## Per-Task Verification Map

This phase owns no formal REQUIREMENTS.md IDs (infrastructure/enabling phase — FLAGSHIP-01/02 formally trace to Phase 32). Mapped to the 4 ROADMAP.md Success Criteria instead:

| Success Criterion | Behavior | Test Type | Automated Command | File Exists | Status |
|--------------------|----------|-----------|--------------------|-------------|--------|
| SC1: pack registered/loadable via `klake init --domain agent-security` | `DomainLoader.from_name("agent-security")` loads without error; `klake init` reports non-zero `loaded_count` | unit (generic) + smoke (real invocation) | `uv run pytest tests/unit/test_domain_loader.py tests/unit/test_domain_scaffold.py -x` + manual `uv run klake init --domain agent-security` | ✅ generic tests exist | ⬜ pending |
| SC2: real sources ingested end-to-end parse→clean→chunk→enrich→embed→index | Registry contains parsed/cleaned/chunk/enriched artifacts for the new domain; Qdrant collection contains new points | integration/manual (real network + real LLM calls) | Manual `klake quality-audit --domain agent-security` (row counts) + `klake search "<term>" --collection klake_chunks` sanity check | ❌ W0 — no automated test exists for domain-specific corpus non-emptiness (inherently operational) | ⬜ pending |
| SC3: gate runs in report-only mode + human-reviewed findings doc | `24-GATE-REVIEW-FINDINGS.md` exists, non-empty, cites real rejection counts/samples | manual (human-authored document, per D-04) | N/A — document existence/content is the artifact | N/A by design | ⬜ pending |
| SC4: Dataset Project reaches `sources_pending`/`ready` | `klake project show <id>` reports `status: ready` | unit (existing, generic) + smoke (real project) | `uv run pytest tests/unit/test_project.py -x` + manual `uv run klake project show <project_id>` | ✅ generic tests exist | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

*None — `tests/unit/test_domain_scaffold.py`, `test_domain_loader.py`, `test_project.py`, `test_quality_audit.py`, and `test_cli_quality_audit.py` already provide generic, domain-name-agnostic regression coverage for every mechanism this phase reuses.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Real end-to-end ingestion produces a non-empty, enriched, indexed corpus for `agent-security` | SC2 | Depends on live external network egress and real LLM spend — not unit-testable without live fixtures | Run `klake init --domain agent-security`, then the ingestion/enrich/embed/index sequence per RESEARCH.md; confirm via `klake quality-audit --domain agent-security --full` that row counts are non-zero across parsed/cleaned/chunk/enriched artifacts and Qdrant has new points |
| Report-only gate rejection-list human review | SC3 | Requires human judgment on whether short/structured domain content (permission scopes, tool identifiers, CVSS-style scores) is being wrongly dropped — not automatable | Set `gate_mode="report"` for the ingestion run, run `klake quality-audit --domain agent-security --full`, sample rejected chunks, author `24-GATE-REVIEW-FINDINGS.md` per CONTEXT.md D-04 |
| Dataset Project real lifecycle transition to `ready` | SC4 | Confirms the actual CLI/DB path works end-to-end for this specific project, not just the generic state machine | `klake project new agent-security-flagship --dataset-type rag_corpus --domain agent-security ...`, `klake dataset spec create`, then `klake project transition` through `configured→sources_pending→ready`; `klake project show <id>` confirms `status: ready` |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references (none required this phase)
- [ ] No watch-mode flags
- [ ] Feedback latency < 90s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
