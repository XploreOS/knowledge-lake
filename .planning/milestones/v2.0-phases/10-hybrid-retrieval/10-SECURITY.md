---
phase: 10
slug: hybrid-retrieval
status: verified
# threats_open = count of OPEN threats at or above workflow.security_block_on (high) severity
threats_open: 0
asvs_level: 1
created: 2026-07-12
---

# Phase 10 — Security

> Per-phase security contract: threat register, accepted risks, and audit trail.
> Hybrid retrieval — dense+sparse search with server-side RRF, bounded prefetch, fail-loud mode enforcement, zero-downtime reindex, fastembed supply chain.

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| client → API/CLI | untrusted `mode`, `top_k`, `tags` query params validated at the boundary | request params |
| client → config/env | `KLAKE_SEARCH__MODE` crosses the pydantic validation boundary | env-supplied mode |
| operator → CLI | migration (`reindex --hybrid`) is operator-triggered; parity gate + rollback are the safety contract | migration trigger |
| app → Qdrant server | collection lifecycle, hybrid query, and migration alias swap | ANN query / alias ops |
| app → PyPI / HuggingFace | fastembed install + first-use ONNX model download (Qdrant/bm25) | third-party package + model |

---

## Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation | Status |
|-----------|----------|-----------|----------|-------------|------------|--------|
| T-10-01 | Denial of Service | search prefetch branches | high | mitigate | `branch_limit = top_k + offset` (D-12, tight — not 10×); top_k bounded [1,100] upstream — `plugins/builtin/qdrant_store.py:640` | closed |
| T-10-02 | Tampering | mode param (CLI/API/settings/env) | medium | mitigate | `pattern=r"^(hybrid\|dense\|sparse)$"` + `Literal["hybrid","dense","sparse"]` fail-closed at the boundary — `api/schemas.py:67`, `api/app.py:216`, `config/settings.py:346` | closed |
| T-10-03 | Repudiation / Integrity | search mode enforcement (no dense substitution) | high | mitigate | D-10 fail-loud probe raises when sparse absent for hybrid/sparse; never silently substitutes dense — `plugins/builtin/qdrant_store.py:631` | closed |
| T-10-04 | Denial of Service / Integrity | reindex re-embed migration / alias swap | high | mitigate | D-06 count-parity gate before `update_collection_aliases`; mismatch aborts and alias stays on old collection (reversible) — `plugins/builtin/qdrant_store.py:341,379` | closed |
| T-10-05 | Tampering (supply chain) | Qdrant/bm25 model load | medium | mitigate | model pinned to `Qdrant/bm25` (Qdrant HF org) via fastembed pin; CPU-only, no GPU/torch; loaded from verified local cache | closed |
| T-10-SC | Tampering (supply chain) | fastembed install + server capability | high | mitigate | `fastembed>=0.8,<0.9` pinned (Qdrant-official, qdrant-client's declared extra) — `pyproject.toml:20`; D-07 `assert_server_supports_hybrid` preflight requires server >= 1.10 before any hybrid/sparse op — `plugins/builtin/qdrant_store.py:39` | closed |

*Status: open · closed · open — below high threshold (non-blocking)*
*Severity: critical > high > medium > low — only open threats at or above high count toward threats_open*

*Note: threat IDs recur across plans 10-01…10-08 (test plans assert the mitigations that consumer plans implement); consolidated here to their highest-severity representative.*

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|

No accepted risks — every threat in this phase carries a verified `mitigate` disposition.

*Accepted risks do not resurface in future audit runs.*

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-07-12 | 6 | 6 | 0 | gsd-secure-phase |

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-07-12
