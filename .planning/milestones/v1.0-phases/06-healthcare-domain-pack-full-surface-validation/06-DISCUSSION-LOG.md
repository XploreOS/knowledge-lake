# Phase 6: Healthcare Domain Pack & Full-Surface Validation - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-07
**Phase:** 6-Healthcare Domain Pack & Full-Surface Validation
**Mode:** `--auto` (fully autonomous — no interactive session; all selections are recommended defaults)
**Areas discussed:** Domain pack loading mechanism, Healthcare seed sources, Healthcare prompts/taxonomy/validator, End-to-end validation scope, CLI surface gaps, API surface completeness, Dagster observability completeness

---

## Domain pack loading mechanism (DOMAIN-01)

| Option | Description | Selected |
|--------|-------------|----------|
| Directory convention at project root | `domains/{name}/` co-located with `src/`; loaded by `klake init --domain` | ✓ |
| Embedded in `src/` as Python packages | Domain packs as installable Python packages | |
| Plugin entry-point registration | Extend existing `resolver.py` entry-point system to discover domain packs | |

**Auto-selected:** Directory convention at project root (recommended default — zero core code changes, discoverable by convention, DOMAIN-01 explicit requirement).
**Notes:** Only core-code touch point is `pipeline/enrich.py` prompt override (additive-only).

---

## Healthcare seed sources (DOMAIN-02)

| Option | Description | Selected |
|--------|-------------|----------|
| 25+ curated entries across all required categories | HL7, CMS, HIPAA/OCR, ONC, CDC, FDA, NLM, NPPES, LOINC, RxNorm | ✓ |
| Minimal 25 sources, 1 per domain category | Only top-level source per category | |

**Auto-selected:** 28 entries covering all required category groups from DOMAIN-02.
**Notes:** Bulk-download sources (NPPES, ICD-10-CM, NDC) tagged `ingest_type: upload` not crawl. All sources are public domain or open license.

---

## Healthcare enrichment prompts, taxonomy & validator (DOMAIN-03)

| Option | Description | Selected |
|--------|-------------|----------|
| Prompt overrides + taxonomy + validator in `domains/healthcare/` | Full DOMAIN-03 set: enrich.j2, qa_generation.j2, taxonomy.yaml, validators/validate.py | ✓ |
| Prompts only (no taxonomy or validator) | Minimal approach | |

**Auto-selected:** Full set per DOMAIN-03 requirement.
**Notes:** PHI guard is keyword-heuristic only per PROJECT.md constraint.

---

## End-to-end validation scope (DOMAIN-04)

| Option | Description | Selected |
|--------|-------------|----------|
| 5-source Dagster job + integration test | healthcare_e2e_job; 2 HTML + 2 PDF + 1 CSV; live local stack | ✓ |
| 10-source mock-based test | Larger coverage but mocked stack | |
| Ad-hoc script (not Dagster) | Faster to write, less representative | |

**Auto-selected:** 5-source Dagster job with live local stack (no mocks, consistent with prior E2E patterns).
**Notes:** Sources chosen: CMS CoP (HTML), CDC ICD overview (HTML), HIPAA Security Rule (PDF), US Core IG (PDF), NPPES NPI sample (CSV).

---

## CLI surface gaps (IFACE-01)

| Option | Description | Selected |
|--------|-------------|----------|
| Add `init` + `index` (two new commands) | `init --domain <name>` for pack loading; `index` as primary name per IFACE-01 | ✓ |
| Rename `reindex` to `index` | Breaking change to existing command name | |
| Add only `init` (skip `index` gap) | Leaves IFACE-01 incomplete | |

**Auto-selected:** Add both `init` and `index`; keep `reindex` as alias.

---

## API surface completeness (IFACE-02)

| Option | Description | Selected |
|--------|-------------|----------|
| Gap audit during research + additive additions | Researcher enumerates missing endpoints; planner adds them | ✓ |
| Full API redesign | Overkill — existing surface is functional | |

**Auto-selected:** Gap audit + additive additions only.

---

## Dagster observability completeness (IFACE-03)

| Option | Description | Selected |
|--------|-------------|----------|
| Audit existing assets for RetryPolicy + add healthcare_e2e_job | Targeted fix for IFACE-03 | ✓ |
| Add Dagster sensors/schedules | Over-scope for Phase 6 MVP | |

**Auto-selected:** RetryPolicy audit + healthcare_e2e_job definition.

---

## Claude's Discretion

- Jinja2 template variable names and prompt phrasing for `enrich.j2` / `qa_generation.j2`
- Whether domain prompt override uses per-call kwargs or `DomainSettings` model
- `DomainValidator` protocol location (separate `protocols.py` entry vs inline)
- Exact `RetryPolicy` parameters (retry count, delay strategy)
- `healthcare_e2e_job` composition style
- Full API endpoint gap list (researcher produces; planner names)

## Deferred Ideas

- RAGAS/Promptfoo/Arize eval harness — already deferred from Phase 5, still deferred
- Multi-domain pack support — future milestone
- Domain pack registry/catalog — future milestone
- Hybrid BM25 search (RETR-01) — v2 requirement
- Admin UI — out of scope (PROJECT.md)
