---
phase: 02-ingestion
reviewed: 2026-07-04T12:00:00Z
depth: standard
files_reviewed: 47
files_reviewed_list:
  - infra/searxng/settings.yml
  - src/knowledge_lake/api/app.py
  - src/knowledge_lake/api/schemas.py
  - src/knowledge_lake/cli/app.py
  - src/knowledge_lake/config/settings.py
  - src/knowledge_lake/crawl/__init__.py
  - src/knowledge_lake/crawl/ratelimit.py
  - src/knowledge_lake/crawl/robots.py
  - src/knowledge_lake/crawl/select.py
  - src/knowledge_lake/ids.py
  - src/knowledge_lake/pipeline/crawl.py
  - src/knowledge_lake/pipeline/discover.py
  - src/knowledge_lake/pipeline/ingest.py
  - src/knowledge_lake/plugins/builtin/crawl4ai_adapter.py
  - src/knowledge_lake/plugins/builtin/playwright_adapter.py
  - src/knowledge_lake/plugins/builtin/scrapy_adapter.py
  - src/knowledge_lake/plugins/builtin/scrapy_spider.py
  - src/knowledge_lake/plugins/builtin/searxng_discovery.py
  - src/knowledge_lake/plugins/protocols.py
  - src/knowledge_lake/plugins/resolver.py
  - src/knowledge_lake/registry/alembic/versions/0002_source_normalized_url.py
  - src/knowledge_lake/registry/alembic/versions/0003_crawl_jobs_states.py
  - src/knowledge_lake/registry/alembic/versions/0004_crawl_state_error_msg.py
  - src/knowledge_lake/registry/alembic/versions/0005_unique_sources_normalized_url.py
  - src/knowledge_lake/registry/models.py
  - src/knowledge_lake/registry/repo.py
  - src/knowledge_lake/storage/s3.py
  - tests/integration/test_crawl4ai_adapter.py
  - tests/integration/test_crawl_resume.py
  - tests/integration/test_crawl_robots_blocked.py
  - tests/integration/test_crawl_schema.py
  - tests/integration/test_dedup_noop.py
  - tests/integration/test_discovery_register.py
  - tests/integration/test_ingest_url_dedup.py
  - tests/integration/test_playwright_adapter.py
  - tests/integration/test_scrapy_subprocess.py
  - tests/integration/test_source_register.py
  - tests/integration/test_upload.py
  - tests/unit/test_crawler_select.py
  - tests/unit/test_discovery.py
  - tests/unit/test_fetch_redirect_ssrf.py
  - tests/unit/test_put_bronze.py
  - tests/unit/test_robots_ratelimit.py
  - tests/unit/test_url_normalize.py
findings:
  critical: 2
  warning: 3
  info: 3
  total: 8
status: issues_found
---

# Phase 02: Code Review Report

**Reviewed:** 2026-07-04T12:00:00Z
**Depth:** standard
**Files Reviewed:** 47
**Status:** issues_found

## Summary

All fixes from the previous review iterations have been applied and verified. The core SSRF
guard, redirect-hop re-validation, robots.txt enforcement, rate limiting, URL-first and hash-second
dedup, concurrent-write IntegrityError recovery, and the lifespan context manager migration all
look correct in the current code. Two critical security gaps remain: the SSRF guard does not block
IPv6 link-local addresses (`fe80::/10`), and the robots.txt HTTP fetch follows redirects without
re-validating their targets. Three warnings cover a fragile robots-policy URL construction, a
module-level import-time assertion, and a trailing-dot key in the rate limiter.

---

## Critical Issues

### CR-01: `_PRIVATE_NETS` missing `fe80::/10` — SSRF bypass via IPv6 link-local

**File:** `src/knowledge_lake/pipeline/ingest.py:51-59`

**Issue:** The SSRF guard blocks IPv4 link-local (`169.254.0.0/16`) for cloud IMDS endpoints, but
does not block the IPv6 link-local range `fe80::/10`. An attacker who controls DNS for a hostname
they own can return an `fe80::` address; `getaddrinfo` will resolve it, `ipaddress.ip_address`
will parse it, and the loop over `_PRIVATE_NETS` will find no matching network, allowing the
request to proceed to a link-local address on the machine's network interface. On Linux/macOS,
`fe80::1` is a valid loopback-equivalent on most network stacks.

The comment on line 55 reads `"link-local / cloud IMDS (AWS/GCP/Azure)"`, making the omission of
the IPv6 counterpart clearly an oversight rather than a deliberate design decision.

```python
# current — missing fe80::/10
_PRIVATE_NETS = [
    ...
    ipaddress.ip_network("169.254.0.0/16"),   # IPv4 link-local only
    ...
    ipaddress.ip_network("fc00::/7"),          # IPv6 ULA only
]
```

**Fix:** Add the IPv6 link-local range:

```python
_PRIVATE_NETS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),    # IPv4 link-local / cloud IMDS
    ipaddress.ip_network("127.0.0.0/8"),       # IPv4 loopback
    ipaddress.ip_network("::1/128"),           # IPv6 loopback
    ipaddress.ip_network("fc00::/7"),          # IPv6 ULA
    ipaddress.ip_network("fe80::/10"),         # IPv6 link-local  ← ADD THIS
]
```

---

### CR-02: `_fetch_robots_text` follows redirects without SSRF re-validation

**File:** `src/knowledge_lake/crawl/robots.py:106`

**Issue:** `_fetch_robots_text` constructs the robots URL from a caller-validated `base_url` and
then fetches it with `follow_redirects=True`:

```python
with httpx.Client(timeout=10.0, follow_redirects=True) as client:
    resp = client.get(url)
```

A crawl target can serve a `302 Location: http://169.254.169.254/latest/meta-data/iam/security-credentials/`
from its `/robots.txt` endpoint. The initial SSRF guard accepted the base URL because it is a
public IP. The httpx client then follows the redirect to the cloud IMDS endpoint — making a
credentialed HTTP request to AWS/GCP/Azure metadata service from within the cloud environment —
without any SSRF check on the redirect target.

This is the exact gap that `_fetch_with_retry` in `pipeline/ingest.py` and `_safe_get` in
`crawl/select.py` were both hardened against. The robots fetch was missed.

**Fix:** Replace `follow_redirects=True` with manual hop-by-hop following that calls
`validate_public_url` on each Location header before following it:

```python
def _fetch_robots_text(base_url: str) -> str:
    from knowledge_lake.pipeline.ingest import validate_public_url
    from urllib.parse import urljoin

    url = f"{base_url.rstrip('/')}/robots.txt"
    _MAX_HOPS = 10
    with httpx.Client(timeout=10.0, follow_redirects=False) as client:
        for _ in range(_MAX_HOPS):
            resp = client.get(url)
            if resp.status_code in (301, 302, 303, 307, 308):
                location = resp.headers.get("location", "")
                if not location:
                    break
                resolved = urljoin(url, location)
                validate_public_url(resolved)  # raises on private IP
                url = resolved
                continue
            if resp.status_code == 404:
                return ""
            resp.raise_for_status()
            return resp.text
    raise ValueError("Too many redirects fetching robots.txt")
```

---

## Warnings

### WR-01: `RobotsPolicy.is_allowed` constructs a malformed URL when `path` lacks a leading slash

**File:** `src/knowledge_lake/crawl/robots.py:76`

**Issue:** `is_allowed` builds a dummy URL for Protego with:

```python
url = f"http://example.com{path}"
```

If `path` is an empty string (`""`), the URL becomes `"http://example.com"` — which Protego
accepts but matches the root, not an explicit path. If `path` is `"noslash"` (no leading `/`),
the URL becomes `"http://example.comnoslash"` — a completely different hostname that Protego will
not recognise as belonging to `example.com`, causing `can_fetch` to return `True` (allow-all
fallback for unknown domains), silently bypassing the disallow rule.

Current callers use `urlparse(url).path or "/"` so the bug is masked in practice. But the
public method signature accepts any string, and future callers may forget the guard.

**Fix:** Validate and normalise `path` inside the method:

```python
def is_allowed(self, path: str, user_agent: str = "*") -> bool:
    if not path.startswith("/"):
        path = "/" + path
    url = f"http://example.com{path}"
    return self._parser.can_fetch(url, user_agent)
```

---

### WR-02: Module-level `assert isinstance(ScrapyAdapter(), CrawlerPlugin)` is a side-effectful import-time assertion

**File:** `src/knowledge_lake/plugins/builtin/scrapy_adapter.py:316-318`

**Issue:**

```python
assert isinstance(ScrapyAdapter(), CrawlerPlugin), (
    "ScrapyAdapter does not satisfy CrawlerPlugin protocol ..."
)
```

This code runs at module import time and has two problems:

1. **Optimised builds:** Python skips `assert` statements when running with `-O` (optimise), which
   is the default in some production Docker builds and CI configurations. The protocol check then
   silently disappears rather than serving as a gate.

2. **Import-time side effects:** The assertion instantiates `ScrapyAdapter()`, initialising its
   `dict` fields, on every import. If `ScrapyAdapter.__init__` is ever extended (e.g., to acquire
   a resource or spawn a background thread), this becomes a hidden cost on each import. It also
   makes import errors harder to debug — a protocol mismatch surfaces as an `AssertionError` during
   `import`, not a clear test failure.

**Fix:** Remove the module-level assertion and add a dedicated unit test:

```python
# tests/unit/test_scrapy_adapter_protocol.py
from knowledge_lake.plugins.builtin.scrapy_adapter import ScrapyAdapter
from knowledge_lake.plugins.protocols import CrawlerPlugin

def test_scrapy_adapter_satisfies_protocol():
    assert isinstance(ScrapyAdapter(), CrawlerPlugin)
```

---

### WR-03: `_domain_key` returns a trailing-dot key for raw IPs and internal hostnames

**File:** `src/knowledge_lake/crawl/ratelimit.py:85-86`

**Issue:**

```python
extracted = tldextract.extract(url)
return f"{extracted.domain}.{extracted.suffix}"
```

For `https://localhost/page`, `tldextract.extract` returns `ExtractResult(subdomain='', domain='localhost', suffix='')`, producing the key `"localhost."` (trailing dot). For raw IPv4 addresses like `https://10.0.0.1/`, the result is `".".join(['10', ''])` through the same pattern, producing `"10."`.

In production, `validate_public_url` blocks both patterns before they reach `_domain_key`. However,
the rate-limiter is also called with attacker-controlled URLs during crawl (the URL from a page's
`href` attribute), and if any code path reaches `_domain_key` before validation, the malformed key
causes incorrect per-host bucketing — all requests with a trailing-dot key would be rate-limited
together, potentially defeating per-host isolation.

**Fix:**

```python
def _domain_key(url: str) -> str:
    extracted = tldextract.extract(url)
    if extracted.domain and extracted.suffix:
        return f"{extracted.domain}.{extracted.suffix}"
    # Raw IP or bare hostname — use the full hostname as the key
    from urllib.parse import urlparse
    return urlparse(url).hostname or url
```

---

## Info

### IN-01: `raw_document`, `parsed_document`, and `bronze_document` share the `"doc_"` ID prefix

**File:** `src/knowledge_lake/ids.py:34-39`

**Issue:** Three distinct artifact kinds all generate IDs with the `"doc_"` prefix:

```python
"raw_document":    "doc",
"parsed_document": "doc",
"bronze_document": "doc",
```

A bare `doc_XXXX` in a log line, error message, or API response is ambiguous without a registry
lookup to determine whether the artifact is a raw HTML download, a Docling-parsed document, or a
bronze markdown conversion. The stated goal of self-describing prefixed IDs (D-15) is not met for
these three types.

**Fix:** Assign distinct prefixes (`raw_`, `par_`, `brz_`) or add a comment explicitly documenting
why sharing the prefix is intentional. Note this is a breaking schema change for any existing rows.

---

### IN-02: `crawl_source` uses an anonymous type to construct a settings-like object

**File:** `src/knowledge_lake/pipeline/crawl.py:81`

**Issue:**

```python
adapter = get_crawler(
    type("_S", (), {"crawler": crawler_name})()  # minimal settings-like obj
)
```

`get_crawler` only reads `settings.crawler`, but the caller constructs a throwaway anonymous class
just to satisfy the interface. This pattern is opaque to readers, cannot be type-checked, and will
break silently if `get_crawler` ever reads a second attribute from the settings object.

**Fix:** Pass `crawler_name` directly and update `get_crawler` to accept either a string or a
settings object, or use a named dataclass:

```python
from dataclasses import dataclass

@dataclass
class _CrawlerOverride:
    crawler: str

adapter = get_crawler(_CrawlerOverride(crawler=crawler_name))
```

---

### IN-03: `scrapy_spider._registrable_domain` returns full hostname, inconsistent with `tldextract` usage elsewhere

**File:** `src/knowledge_lake/plugins/builtin/scrapy_spider.py:64-67`

**Issue:**

```python
def _registrable_domain(url: str) -> str:
    parsed = urlparse(url)
    return parsed.hostname or ""
```

This returns the full hostname including subdomain (e.g., `www.example.com`), while `crawl.py`
and `ratelimit.py` both use `tldextract` to extract the registrable domain (`example.com`). A site
that rotates crawl-blocking responses across subdomains (`sub1.example.com`, `sub2.example.com`)
would be treated as different domains in the Scrapy spider's same-domain scope filter, allowing
cross-registrable-domain link following that the orchestrator would reject. This inconsistency
can cause the Scrapy spider to skip or follow different links than the orchestrator expects.

**Fix:** Use `tldextract` consistently:

```python
import tldextract

def _registrable_domain(url: str) -> str:
    ext = tldextract.extract(url)
    if ext.domain and ext.suffix:
        return f"{ext.domain}.{ext.suffix}"
    return urlparse(url).hostname or ""
```

---

_Reviewed: 2026-07-04T12:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
