---
phase: 7
slug: metadata-foundation
status: verified
# threats_open = count of OPEN threats at or above workflow.security_block_on (high) severity
threats_open: 0
asvs_level: 1
created: 2026-07-12
---

# Phase 7 — Security

> Per-phase security contract: threat register, accepted risks, and audit trail.
> Metadata foundation — source metadata into Qdrant payload, filtered search, API/CLI surfaces.

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| caller → register_source() | tags/organization are caller-supplied, stored into Source.config JSON column via ORM | operator-controlled list[str]/str |
| index() session → Qdrant payload | source metadata read from trusted registry DB, written to Qdrant payload | public registry fields |
| HTTP client → search_endpoint | source_name, format, source_id, tags arrive as FastAPI Query params; Pydantic validates types | untrusted filter strings |
| CLI user → cmd_search | flags arrive as typer-parsed Optional[str]/list[str] | operator-supplied filter strings |
| search() → Qdrant filter | filter values passed as parameterized FieldCondition/MatchValue/MatchAny | typed filter model objects |

---

## Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation | Status |
|-----------|----------|-----------|----------|-------------|------------|--------|
| T-07-01-SC | Tampering | test file — no new packages | low | accept | No new pip installs; stdlib unittest.mock + existing qdrant-client | closed |
| T-07-02-01 | Information Disclosure | index.py payload | low | accept | source_url/organization are already public registry fields | closed |
| T-07-02-02 | Tampering | register_source() tags | low | accept | tags written to Source.config via SQLAlchemy ORM, no raw SQL; input from operator-controlled sources.yaml | closed |
| T-07-02-03 | Denial of Service | register_source() oversized tags list | low | accept | tags sourced from operator-controlled sources.yaml/crawl.py; no external user path | closed |
| T-07-03-01 | Information Disclosure | ensure_payload_indexes collection name | low | accept | collection_name validated by `_COLLECTION_NAME_RE` guard in api/app.py before this layer | closed |
| T-07-03-02 | Denial of Service | search() tags list | medium | mitigate | `max_length=64` per-element bound on tags Query param — `api/app.py:212` | closed |
| T-07-03-03 | Injection | search() filter kwargs → Qdrant | low | accept | Qdrant FieldCondition/MatchValue/MatchAny are strongly-typed objects; no string concatenation | closed |
| T-07-04-01 | Denial of Service | search_endpoint tags Query param | medium | mitigate | `max_length=64` on tags Query param + top_k [1,100] bound — `api/app.py:212` | closed |
| T-07-04-02 | Information Disclosure | SearchHit new fields | low | accept | source_url/organization/tags already in public Source registry; source_id not a secret | closed |
| T-07-04-03 | Tampering | CLI/API filter params → Qdrant | low | accept | passed as parameterized FieldCondition match values; Qdrant handles escaping | closed |
| T-07-04-04 | Tampering | collection name | low | accept | existing `_COLLECTION_NAME_RE` guard in app.py validates before search() | closed |

*Status: open · closed · open — below high threshold (non-blocking)*
*Severity: critical > high > medium > low — only open threats at or above high count toward threats_open*

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|
| R-07-01 | T-07-01-SC | No new dependencies added in this phase | Jeevan J | 2026-07-12 |
| R-07-02 | T-07-02-01/02/03 | Metadata fields are public registry data written via ORM; input paths are operator-controlled (sources.yaml) | Jeevan J | 2026-07-12 |
| R-07-03 | T-07-03-01/03, T-07-04-02/03/04 | Collection name validated upstream by `_COLLECTION_NAME_RE`; filters are parameterized (no injection surface); result fields are non-secret registry data | Jeevan J | 2026-07-12 |

*Accepted risks do not resurface in future audit runs.*

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-07-12 | 11 | 11 | 0 | gsd-secure-phase |

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-07-12
