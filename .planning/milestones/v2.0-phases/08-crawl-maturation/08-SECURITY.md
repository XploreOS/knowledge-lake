---
phase: 8
slug: crawl-maturation
status: verified
# threats_open = count of OPEN threats at or above workflow.security_block_on (high) severity
threats_open: 0
asvs_level: 1
created: 2026-07-12
---

# Phase 8 — Security

> Per-phase security contract: threat register, accepted risks, and audit trail.
> Crawl maturation — per-host rate limiting, adaptive backoff, per-source depth, partial enrichment recovery, linked-document following, batch crawl-all.

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| Source.config → rate-limit logic | Attacker-influenced config could set rate_limit_rps = 0 (divide-by-zero) | operator-controlled config |
| HTTP response status → backoff logic | Attacker-controlled server returns 429 to force aggressive backoff | untrusted network signal |
| Source.config crawl_config → crawl depth | Per-source depth override could be very large | operator-controlled config |
| crawl_all_sources source URL → fetch | Registry source URLs re-validated before any HTTP (SSRF) | trusted-registry URL |
| LLM response content → JSON prefix extraction | Adversarial document content could produce partial JSON | untrusted document content |
| Crawled HTML → linked URLs | HTML from untrusted sites may contain crafted hrefs to internal services (SSRF) | untrusted link targets |
| API caller / CLI operator → POST /crawl-all | External callers can trigger batch crawl of all registered sources | operator/API request |

---

## Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation | Status |
|-----------|----------|-----------|----------|-------------|------------|--------|
| T-08-01-01 | Tampering | test stubs | low | accept | xfail stubs are read-only; no production code modified | closed |
| T-08-02-01 | Tampering | resolve_delay rate_limit_rps path | medium | mitigate | `(1.0 / rps) if rps > 0 else global_default` zero-division guard — `crawl/ratelimit.py:95` | closed |
| T-08-02-02 | Denial of Service | PerHostLimiter backoff_extra | low | accept | `MAX_BACKOFF_SECONDS = 60` caps sleep; per-host; attacker must own target server | closed |
| T-08-02-03 | Tampering | CrawlPageResult http_status_code | low | accept | field informs backoff only; does not cross into auth/storage | closed |
| T-08-03-01 | Denial of Service | per-source depth override | low | mitigate | `int(depth_override)` validation raises ValueError on invalid; capped by max_pages — `crawl.py:306` | closed |
| T-08-03-02 | Denial of Service | crawl_all_sources sequential loop | low | accept | sequential; per-host adaptive backoff limits rate; no amplification | closed |
| T-08-03-03 | Spoofing | crawl_source source URL from registry | medium | mitigate | `validate_public_url(source_url)` as first step — `crawl.py:283` | closed |
| T-08-04-01 | Tampering | partial-prefix enrichment recovery | medium | mitigate | `EnrichmentResult.model_validate_json()` validates partial prefix against Pydantic schema — `pipeline/enrich.py:268` | closed |
| T-08-04-02 | Tampering | is_partial flag | low | accept | boolean set server-side from finish_reason; not attacker-controlled | closed |
| T-08-04-03 | Information Disclosure | partial enrichment stored under partial: key | low | accept | same access control as complete results; no new data exposed | closed |
| T-08-05-01 | Elevation of Privilege | SSRF via linked document URL | high | mitigate | `validate_public_url(link_url)` on every followed link before ingest_url (defense in depth) — `crawl.py:637` | closed |
| T-08-05-02 | Denial of Service | unbounded linked-doc frontier | medium | mitigate | `MAX_LINKED_DOCS_PER_PAGE = 10` + `_seen_urls` dedup; linked docs not re-crawled — `crawl.py:56,813` | closed |
| T-08-05-03 | Elevation of Privilege | SSRF via redirect in followed link | medium | mitigate | per-redirect-hop `validate_public_url` in `_fetch_with_retry` (auto-redirect disabled) — `ingest.py:159` | closed |
| T-08-05-04 | Denial of Service | event loop blocking from sync ingest_url | medium | mitigate | `loop.run_in_executor(...)` wraps ingest_url per followed link — `crawl.py:653` | closed |
| T-08-06-01 | Denial of Service | POST /crawl-all sequential crawl of all sources | medium | mitigate | sequential loop; per-host backoff; no concurrency amplification — `crawl.py:911` | closed |
| T-08-06-02 | Tampering | domain query param in POST /crawl-all | low | accept | Python-side string equality filter via SQLAlchemy ORM; no SQL injection | closed |
| T-08-06-03 | Information Disclosure | error details in CrawlAllSourceResult.error | low | accept | internal pipeline exceptions; no user data in error strings | closed |

*Status: open · closed · open — below high threshold (non-blocking)*
*Severity: critical > high > medium > low — only open threats at or above high count toward threats_open*

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|
| R-08-01 | T-08-01-01 | Test-only scaffolding; no production change | Jeevan J | 2026-07-12 |
| R-08-02 | T-08-02-02/03 | Backoff capped at 60s per-host; status code informs backoff only, no trust-boundary crossing | Jeevan J | 2026-07-12 |
| R-08-03 | T-08-03-02 | Sequential crawl bounded by per-host adaptive backoff; no rate amplification | Jeevan J | 2026-07-12 |
| R-08-04 | T-08-04-02/03 | is_partial is server-derived; partial results inherit complete-result access control | Jeevan J | 2026-07-12 |
| R-08-05 | T-08-06-02/03 | domain filter is ORM Python-side equality; error strings carry no user data | Jeevan J | 2026-07-12 |

*Accepted risks do not resurface in future audit runs.*

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-07-12 | 17 | 17 | 0 | gsd-secure-phase |

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-07-12
