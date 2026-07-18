---
phase: 22
slug: address-tech-debt-measure-garbage-junk-rates-end-to-end-reco
status: verified
# threats_open = count of OPEN threats at or above workflow.security_block_on severity (the blocking gate)
threats_open: 0
asvs_level: 1
created: 2026-07-18
---

# Phase 22 — Security

> Per-phase security contract: threat register, accepted risks, and audit trail.

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| Caller (CLI/future scripts) → `run_quality_audit()`/`run_full_pipeline_audit()` | `domain` string parameter flows into a `Source.domain` registry filter | Operator-supplied string, never remote/network input |
| `run_full_pipeline_audit()` → Qdrant-free pipeline reuse | No new trust boundary — reuses `clean()`/`chunk()`/`export_rag_corpus()` unmodified, inheriting their existing, already-audited boundaries | Internal function calls only |
| `run_full_pipeline_audit()` → gold-zone Parquet read-back | Internally-generated chunk IDs (never user input) flow into a Polars in-memory filter, not a query string | Content-addressed artifact IDs |
| Operator terminal → `klake quality-audit --full` CLI | `--domain`/`--full`/`--json` flags are operator-supplied, not remote/network input | CLI flags |
| CLI → `run_full_pipeline_audit()` | Straight pass-through of the already-mitigated `domain` string | Parameterized query input |
| Executor terminal → live dev stack | Real `export_rag_corpus()` write during the Plan 22-03 measurement run — expected, pre-existing write path, no new surface | Real S3/MinIO + Postgres writes |

---

## Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation | Status |
|-----------|----------|-----------|----------|-------------|------------|--------|
| T-22-01 | Tampering | `domain` param → `Source.domain` filter (both functions) | low | mitigate | Parameterized SQLAlchemy `.where(Source.domain == domain)` — confirmed at `quality_audit.py:103,251`, no string interpolation | closed |
| T-22-02 | Information Disclosure | `summary`/row dict construction in `run_full_pipeline_audit()` | medium | mitigate | Dicts built key-by-key from a fixed, named field set (`rows.append({...})` at `quality_audit.py:181,394`) — confirmed zero `**meta`/`dataclasses.asdict()` usage in the file | closed |
| T-22-03 | Tampering | Export-scoping filter `pl.col("chunk_id").is_in(this_run_chunk_ids)` | low | accept | `this_run_chunk_ids` built exclusively from `chunk()`'s own return value (internally-generated artifact IDs); no external/user-controlled string reaches this filter | closed (accepted) |
| T-22-04 | Tampering | DuckDB f-string SET-statement injection class of risk | low | accept | This phase deliberately uses Polars `read_parquet(io.BytesIO(...))` instead of DuckDB — sidesteps the injection risk class entirely; confirmed no new DuckDB usage introduced | closed (accepted) |
| T-22-05-SC | Tampering | npm/pip/cargo installs | n/a | accept | Zero new package installs in Plan 22-01 | closed (accepted) |
| T-22-06 | Information Disclosure | New `--full`/`--json` CLI output surface | medium | mitigate | `--full --json` dumps exactly the already allow-listed dict returned by `run_full_pipeline_audit()` (confirmed `json.dumps(result)` at `cli/app.py:1027`) — mirrors the existing `--json` command's pattern verbatim | closed |
| T-22-07 | Tampering | `--domain` CLI option | low | mitigate | Passed straight through to `run_full_pipeline_audit(domain=domain)`'s parameterized query — no new parsing/interpolation added at the CLI layer | closed |
| T-22-08-SC | Tampering | npm/pip/cargo installs | n/a | accept | Zero new package installs in Plan 22-02 — Typer/`json` already project dependencies | closed (accepted) |
| T-22-09 | Repudiation | Real `export_rag_corpus()` write during the Plan 22-03 measurement run (writes a new gold Parquet + dataset row every invocation) | low | accept | Expected/documented behavior, unchanged from the pre-existing `export_rag_corpus()` contract — Plan 22-03 does not introduce a new write path, it invokes the existing one once as designed | closed (accepted) |
| T-22-10-SC | Tampering | npm/pip/cargo installs | n/a | accept | No package installs — Plan 22-03 only runs the already-shipped `klake` CLI | closed (accepted) |

*Status: open · closed · open — below `high` threshold (non-blocking)*
*Severity: critical > high > medium > low — only open threats at or above `workflow.security_block_on` (high) count toward `threats_open`*
*Disposition: mitigate (implementation required) · accept (documented risk) · transfer (third-party)*

All 10 threats registered across Plans 22-01/22-02/22-03's `<threat_model>` blocks are closed. Code-review findings CR-01/CR-02 (fixed in commits `7cc8040`/`6a54df1`) additionally hardened error isolation and unhandled-exception surfaces beyond what the original threat register anticipated — see Accepted Risks Log note below.

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|
| AR-22-01 | T-22-03 | Export-scoping filter operates only on internally-generated chunk IDs (never user input) — Polars in-memory filtering, no query language involved | Phase 22 threat model (22-01-PLAN.md) | 2026-07-18 |
| AR-22-02 | T-22-04 | DuckDB f-string injection risk class sidestepped entirely by using Polars `read_parquet` instead — no DuckDB usage introduced by this phase | Phase 22 threat model (22-01-PLAN.md) | 2026-07-18 |
| AR-22-03 | T-22-05-SC, T-22-08-SC, T-22-10-SC | Zero new package installs across all 3 plans in this phase | Phase 22 threat models | 2026-07-18 |
| AR-22-04 | T-22-09 | Real `export_rag_corpus()` write during the Plan 22-03 live measurement run is the existing, unmodified write path's normal behavior — not a new surface introduced by this phase | Phase 22 threat model (22-03-PLAN.md) | 2026-07-18 |

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-07-18 | 10 | 10 | 0 | Claude (gsd-secure-phase, L1 grep-depth short-circuit — ASVS level 1, register authored at plan time, threats_open confirmed 0 via direct source grep) |

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-07-18
