---
phase: 9
slug: storage-segmentation
status: verified
# threats_open = count of OPEN threats at or above workflow.security_block_on (high) severity
threats_open: 0
asvs_level: 1
created: 2026-07-12
---

# Phase 9 — Security

> Per-phase security contract: threat register, accepted risks, and audit trail.
> Storage segmentation — domain-partitioned S3 keys and best-effort object tagging across raw/bronze/silver/gold zones.

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| pipeline caller → StorageBackend.put_* | domain value flows from caller into S3 key construction; s3.py never calls the registry | resolved-from-DB domain label |
| parse()/clean()/ingest()/crawl() → registry | domain resolved from Source.config inside an active DB session, then passed down | trusted registry value |
| StorageBackend.put_object → boto3 S3 | tags dict URL-encoded and passed as Tagging=; ClientError falls back to tagless write | short registry labels |
| export_* callers → gold zone | domain kwarg from export caller; "_unclassified" fallback prevents None key segments | pipeline/CLI-supplied label |

---

## Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation | Status |
|-----------|----------|-----------|----------|-------------|------------|--------|
| T-09-01 | Denial of Service | `_format_tags` / S3 Tagging parameter | medium | mitigate | tag value truncation `v[:256]` prevents InvalidTagValue overflow — `storage/s3.py:52` | closed |
| T-09-02 | Tampering | put_object best-effort fallback | low | accept | tagging failure triggers tagless retry; object always lands; registry is source of truth | closed |
| T-09-03 | Tampering | S3 key domain segment + session boundary | medium | mitigate | `_UNCLASSIFIED_DOMAIN = "_unclassified"` guards None/empty segments (`s3.py:43`); `get_domain_for_source` called inside active session (`pipeline/index.py:114`, `pipeline/export.py:282`) — no DetachedInstanceError | closed |
| T-09-04 | Information Disclosure | source_name fallback to "unknown" | low | accept | tag carries "unknown" rather than omitting; registry remains source of truth | closed |
| T-09-05 | Information Disclosure | source_name fallback "unknown" in crawl.py | low | accept | only fires on registry inconsistency (get_source None for a registered id); acceptable degradation | closed |
| T-09-06 | Information Disclosure | gold key exposes domain name in S3 path | low | accept | domain is a non-secret label (e.g. "healthcare"); S3 access controlled by IAM/MinIO ACLs | closed |
| T-09-SC | Tampering | npm/pip/cargo installs | low | accept | no new packages installed in this phase | closed |

*Status: open · closed · open — below high threshold (non-blocking)*
*Severity: critical > high > medium > low — only open threats at or above high count toward threats_open*

*Note: threat IDs T-09-01 / T-09-03 recur across plans 09-03…09-06; consolidated here to their highest-severity representative. T-09-03 carries a "mitigate" disposition (session boundary, plan 09-04) and an "accept" disposition (domain segment, plans 09-03/05/06); both controls are verified present.*

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|
| R-09-01 | T-09-02 | Tagless fallback guarantees the object always lands; tags are convenience metadata, registry is source of truth | Jeevan J | 2026-07-12 |
| R-09-02 | T-09-04/05 | "unknown" source_name fallback only fires on registry inconsistency; graceful degradation | Jeevan J | 2026-07-12 |
| R-09-03 | T-09-06 | Domain is a non-secret label already in Source.config; S3 bucket access governed by IAM/MinIO ACLs | Jeevan J | 2026-07-12 |
| R-09-04 | T-09-SC | No new dependencies added in this phase | Jeevan J | 2026-07-12 |

*Accepted risks do not resurface in future audit runs.*

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-07-12 | 7 | 7 | 0 | gsd-secure-phase |

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-07-12
