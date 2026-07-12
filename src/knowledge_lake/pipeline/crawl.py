"""Crawl orchestrator: drive a crawl job from seed URL to raw+bronze artifacts.

Implements the full crawl vertical slice (INGEST-04, INGEST-09, INGEST-10):
  - SSRF re-validation of every URL before fetch (T-02-09, Pitfall 2)
  - Two-artifact-per-page write: raw HTML + bronze markdown (D-01 lineage)
  - Resume from pending crawl_states on re-run (D-03)
  - Per-host rate limiting via three-tier resolver + PerHostLimiter
  - Robots-blocked recording (no artifact write for blocked URLs, D-13)
  - Same-domain scope enforcement via tldextract
  - Hash-second dedup at the artifact layer (INGEST-08)
  - Per-source crawl_config wiring (CRAWL-01): depth override + adaptive backoff
  - Adaptive backoff on HTTP 429/403 (CRAWL-03)
  - Batch crawl across all registered sources (CRAWL-02)
  - Linked-document ingestion (.pdf/.docx hrefs from HTML pages, INGEST-10)

Functions:
    crawl_source(source_url, *, crawler=None, settings=None, max_pages=None) -> dict
    crawl_all_sources(domain=None, settings=None) -> dict
    _extract_linked_docs(html, base_url) -> list[str]
"""

from __future__ import annotations

import asyncio
import datetime
import functools
import hashlib
import os.path as _osp
import re
from collections import deque
from typing import Any
from urllib.parse import urldefrag, urljoin, urlparse

import structlog
import tldextract

from knowledge_lake.config.settings import Settings, get_settings
from knowledge_lake.crawl.ratelimit import PerHostLimiter, resolve_delay
from knowledge_lake.crawl.robots import fetch_robots
from knowledge_lake.pipeline.clean import remove_boilerplate
from knowledge_lake.pipeline.ingest import (
    ingest_url,
    normalize_url,
    register_source,
    validate_public_url,
)
from knowledge_lake.plugins.resolver import get_crawler
from knowledge_lake.registry import repo as registry_repo
from knowledge_lake.registry.db import get_session
from knowledge_lake.registry.repo import (
    list_sources_for_crawl_all as _repo_list_sources_for_crawl_all,
)
from knowledge_lake.registry.repo import touch_source_crawl
from knowledge_lake.storage.s3 import _UNCLASSIFIED_DOMAIN, StorageBackend

log = structlog.get_logger(__name__)

_LINK_RE = re.compile(r'href=["\']([^"\']+)["\']', re.IGNORECASE)

# INGEST-10 (D-19/D-20): Linked-document ingestion constants.
# MAX_LINKED_DOCS_PER_PAGE caps the number of linked .pdf/.docx URLs followed per HTML page.
# LINKED_DOC_EXTENSIONS is the set of file extensions that trigger linked-doc ingestion.
MAX_LINKED_DOCS_PER_PAGE: int = 10
LINKED_DOC_EXTENSIONS: frozenset[str] = frozenset({".pdf", ".docx"})


# SCHED-02 (T-11-THRASH): gate-local volatile-token suppression. The change
# gate normalizes MORE aggressively than the silver-stage remove_boilerplate:
# it neutralizes volatile machine-generated tokens so a dynamically-rendered
# page whose only delta between crawls is a timestamp/nonce yields a stable
# signature and does not thrash the WORM raw zone every tick. This is
# deliberately GATE-ONLY — it must never alter remove_boilerplate, which the
# clean stage shares and which must preserve human-meaningful dates. The ISO
# pattern requires a TIME component so bare effective/publication dates are
# preserved; over-suppression is bounded by max_staleness_days.
_VOLATILE_PLACEHOLDER = "\x00KLAKE_VOLATILE\x00"
_VOLATILE_PATTERNS: list[re.Pattern] = [
    # ISO-8601 datetime (date + time; optional seconds, fraction, timezone)
    re.compile(
        r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2})?(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?"
    ),
    # Bare clock time HH:MM:SS
    re.compile(r"\b\d{2}:\d{2}:\d{2}\b"),
    # Canonical UUID
    re.compile(
        r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
    ),
    # Long hex nonce / token (>= 16 hex chars)
    re.compile(r"\b[0-9a-fA-F]{16,}\b"),
]


def _suppress_volatile(text: str) -> str:
    """Neutralize volatile machine-generated tokens for the change gate only.

    Replaces ISO-8601 timestamps, clock times, UUIDs, and long hex nonces
    with a fixed placeholder so a page whose only inter-crawl delta is a
    dynamic timestamp/nonce yields a stable signature (SCHED-02 anti-thrash).
    Gate-local: does not touch remove_boilerplate or the clean stage.
    """
    for pattern in _VOLATILE_PATTERNS:
        text = pattern.sub(_VOLATILE_PLACEHOLDER, text)
    return text


def _signature(markdown: str) -> str:
    """Compute content signature: normalize, suppress volatile tokens, SHA256.

    Reuses the silver-stage ``remove_boilerplate`` so the gate and the clean
    stage agree on boilerplate (D-06), then applies gate-local volatile-token
    suppression (ISO timestamps, clock times, UUIDs, hex nonces) so
    dynamically-rendered pages do not thrash the WORM raw zone on every tick
    (SCHED-02, T-11-THRASH).
    """
    normalized = remove_boilerplate(markdown or "")
    return hashlib.sha256(
        _suppress_volatile(normalized).encode("utf-8")
    ).hexdigest()


def _get_source_for_recrawl(source_id: str) -> dict:
    """Load source metadata needed by the recrawl gate.

    Opens its own session so recrawl_source can call it without holding one.
    Returns a dict with id, url, last_content_hash, last_crawled_at,
    and crawl_config.
    """
    with get_session() as session:
        source = registry_repo.get_source(session, source_id)
        if source is None:
            raise ValueError(f"recrawl_source: source {source_id!r} not found")
        crawl_config = registry_repo.get_source_crawl_config(session, source_id)
        return {
            "id": source.id,
            "url": source.url,
            "last_content_hash": source.last_content_hash,
            "last_crawled_at": source.last_crawled_at,
            "crawl_config": crawl_config,
        }


async def recrawl_source(
    source_id: str,
    *,
    settings: Settings | None = None,
) -> dict:
    """Change-detection gate: probe the seed URL, compare signature, skip or crawl.

    SCHED-02: Probes the source's canonical URL, normalizes the markdown with
    remove_boilerplate, SHA256s, and compares to Source.last_content_hash. If
    unchanged within the staleness window, skips (no put_raw, no crawl_source).
    Otherwise triggers a full crawl_source() and records the new hash.

    Parameters
    ----------
    source_id:
        Primary key of the Source to re-crawl.
    settings:
        Settings override (uses get_settings() if None).

    Returns
    -------
    dict with source_id and status ('skipped_unchanged' or 'recrawled').
    """
    s = settings or get_settings()
    now = datetime.datetime.now(datetime.UTC)

    # Load source metadata (opens own session)
    src_data = _get_source_for_recrawl(source_id)
    url = src_data["url"]
    last_hash = src_data["last_content_hash"]
    last_at = src_data["last_crawled_at"]
    crawl_config = src_data.get("crawl_config") or {}

    # D-10: per-source staleness override
    max_days = crawl_config.get("max_staleness_days", s.crawl.max_staleness_days)
    stale = (
        last_at is not None
        and (now - last_at) > datetime.timedelta(days=max_days)
    )

    # SSRF guard BEFORE any outbound HTTP (T-11-SSRF)
    validate_public_url(url)

    # Build adapter and probe the seed page
    adapter = get_crawler(
        type("_S", (), {"crawler": s.crawler})()
    )
    probe = await adapter.fetch_page(url)
    sig = _signature(probe.markdown or "")

    # Decision: skip or crawl
    if last_hash is not None and sig == last_hash and not stale:
        # Skip path: bump last_crawled_at only (D-11)
        touch_source_crawl(source_id, last_crawled_at=now)
        log.info(
            "recrawl.skipped_unchanged",
            source_id=source_id,
            url=url,
        )
        return {"source_id": source_id, "status": "skipped_unchanged"}

    # Crawl path: NULL hash, changed signature, or stale
    crawl_result = await crawl_source(url, settings=s)
    touch_source_crawl(source_id, last_crawled_at=now, last_content_hash=sig)
    log.info(
        "recrawl.recrawled",
        source_id=source_id,
        url=url,
        reason="null_hash" if last_hash is None else ("stale" if stale else "changed"),
    )
    output: dict = {"source_id": source_id, "status": "recrawled"}
    if isinstance(crawl_result, dict):
        output.update(crawl_result)
    return output


def list_sources_for_crawl_all(domain: str | None = None) -> list[Any]:
    """Session-aware wrapper: return all sources (optionally filtered by domain).

    This module-level wrapper exists so tests can patch
    ``knowledge_lake.pipeline.crawl.list_sources_for_crawl_all`` without
    needing to also inject a SQLAlchemy session.  Production callers should
    use this function (or call the underlying repo function directly with a
    session).

    Returns a list of ``_SourceRow`` namedtuple-like objects with ``url`` and
    ``id`` attributes, materialised inside the session to prevent
    ``DetachedInstanceError`` on lazy-loaded attributes after session close.

    Parameters
    ----------
    domain:
        Optional domain filter.  None returns all sources.

    Returns
    -------
    list
        Objects with ``.url`` and ``.id`` attributes, ready to iterate outside
        the session context.
    """
    from collections import namedtuple  # local import avoids module-level namespace pollution
    _SourceRow = namedtuple("_SourceRow", ["url", "id"])
    with get_session() as session:
        sources = _repo_list_sources_for_crawl_all(session, domain=domain)
        # Materialise url and id while the session is still open to prevent
        # DetachedInstanceError when SQLAlchemy lazy-loads after session close.
        return [_SourceRow(url=src.url, id=src.id) for src in sources]


async def crawl_source(
    source_url: str,
    *,
    crawler: str | None = None,
    settings: Settings | None = None,
    max_pages: int | None = None,
) -> dict[str, Any]:
    """Crawl a source URL end-to-end: fetch pages, write raw+bronze, track state.

    This is the main entry point called by the CLI (via asyncio.run) and the
    API (awaited directly from the async handler — CR-02).

    Orchestrates:
      1. Source registration
      2. Crawl job creation
      3. Robots.txt policy fetch
      4. Page-level iteration with SSRF validation, rate limiting, and dedup
      5. Two-artifact writes (raw + bronze) with lineage
      6. Resume from pending on re-run

    Args:
        source_url: The seed URL to crawl.
        crawler:    Override crawler adapter name (default: settings.crawler).
        settings:   Settings override (uses get_settings() if None).
        max_pages:  Override maximum pages to crawl (default: settings.crawl.max_pages).

    Returns:
        dict with:
          job_id, source_id, crawler, pages_complete, pages_robots_blocked,
          pages_failed, pages_total, linked_docs_failed
        linked_docs_failed (int): Count of linked .pdf/.docx URLs that were
          SSRF-rejected or raised an exception during ingest. Does not abort
          the crawl (D-24).
    """
    s = settings or get_settings()
    effective_max_pages = max_pages if max_pages is not None else s.crawl.max_pages
    crawler_name = crawler or s.crawler

    # Validate seed URL
    validate_public_url(source_url)

    # Get the seed domain for same-domain enforcement
    seed_domain = _registrable_domain(source_url)

    # Resolve the crawler adapter
    adapter = get_crawler(
        type("_S", (), {"crawler": crawler_name})()  # minimal settings-like obj
    )

    # Register or find the source
    source_result = register_source(
        url=source_url,
        name=_name_from_url(source_url),
    )
    source_id = source_result["source_id"]

    # CRAWL-01 (D-02): Read per-source crawl_config from registry.
    # get_source_crawl_config returns the inner crawl_config sub-dict (never None).
    with get_session() as session:
        source_crawl_config = registry_repo.get_source_crawl_config(session, source_id)

    # CRAWL-01 (D-04): Apply per-source depth override when present.
    # M-02 fix: validate that depth_override is a positive integer.
    # A value of 0 would silently make pages_total < max_pages (0 < 0 = False)
    # and exit immediately with zero pages crawled and no error.
    depth_override = source_crawl_config.get("depth")
    if depth_override is not None:
        try:
            parsed_depth = int(depth_override)
        except (ValueError, TypeError):
            log.warning(
                "crawl.depth_override_invalid",
                source_id=source_id,
                depth_override=depth_override,
                reason="non-integer value; using global default",
                effective_max_pages=effective_max_pages,
            )
            parsed_depth = None
        if parsed_depth is not None:
            if parsed_depth <= 0:
                log.warning(
                    "crawl.depth_override_invalid",
                    source_id=source_id,
                    depth_override=parsed_depth,
                    reason="depth must be > 0; using global default",
                    effective_max_pages=effective_max_pages,
                )
            else:
                effective_max_pages = parsed_depth

    # Find or create crawl job (resume support: reuse existing incomplete job)
    job_id = _find_or_create_job(source_id, crawler_name, effective_max_pages, source_url)

    # Fetch robots.txt for the seed host — offload the blocking HTTP call to a
    # thread so the event loop is not stalled (fetch_robots uses httpx.Client,
    # which is synchronous; WR-004).
    base_url = f"{urlparse(source_url).scheme}://{urlparse(source_url).netloc}"
    robots_policy = await asyncio.get_running_loop().run_in_executor(None, fetch_robots, base_url)
    robots_crawl_delay = robots_policy.crawl_delay()

    # Seed URLs: start with the source_url itself
    # On resume, we'll process pending states instead of re-seeding
    urls_to_process = _get_urls_to_process(
        job_id=job_id,
        seed_url=source_url,
        max_pages=effective_max_pages,
    )

    # Await the async crawl loop directly (no asyncio.run — CR-02)
    stats = await _crawl_loop(
        urls=urls_to_process,
        job_id=job_id,
        source_id=source_id,
        adapter=adapter,
        robots_policy=robots_policy,
        robots_crawl_delay=robots_crawl_delay,
        seed_domain=seed_domain,
        max_pages=effective_max_pages,
        settings=s,
        source_config=source_crawl_config,
    )

    # Update job status
    with get_session() as session:
        job_obj = session.get(registry_repo.Job, job_id)
        if job_obj:
            job_obj.status = "complete"
            job_obj.stats = stats
            job_obj.updated_at = datetime.datetime.now(datetime.UTC)

    return {
        "job_id": job_id,
        "source_id": source_id,
        "crawler": crawler_name,
        **stats,
    }


def _find_or_create_job(
    source_id: str,
    crawler_name: str,
    max_pages: int,
    source_url: str,
) -> str:
    """Find an existing incomplete crawl job for the source, or create a new one.

    Resume logic: if a job with status 'running' or 'pending' exists for this
    source_id and crawler, reuse it. Otherwise, create a new one.

    Uses a single session for lookup + conditional insert to eliminate the
    TOCTOU race where two concurrent workers both see no existing job and
    both attempt to insert a new one. The partial UNIQUE index on
    (source_id, crawler) WHERE status IN ('running', 'pending') makes the
    second insert raise IntegrityError; we catch it and return the winner's
    job ID (CR-004).
    """
    from sqlalchemy import select as sa_select
    from sqlalchemy.exc import IntegrityError

    from knowledge_lake.registry.models import Job

    with get_session() as session:
        stmt = (
            sa_select(Job)
            .where(Job.source_id == source_id)
            .where(Job.crawler == crawler_name)
            .where(Job.status.in_(["running", "pending"]))
            .order_by(Job.created_at.desc())
            .limit(1)
        )
        existing = session.execute(stmt).scalar_one_or_none()
        if existing:
            log.info("crawl.resume_job", job_id=existing.id)
            return existing.id

        # No existing job — attempt to create one.
        # Catch IntegrityError from the partial unique index in case a
        # concurrent worker inserts the same (source_id, crawler/running) row.
        try:
            job = registry_repo.create_crawl_job(
                session,
                source_id=source_id,
                crawler=crawler_name,
                config={"max_pages": max_pages, "source_url": source_url},
                status="running",
            )
            session.flush()
            return job.id
        except IntegrityError:
            session.rollback()
            # Another worker created the job between our SELECT and INSERT.
            # Re-query on a FRESH session so we always see the concurrent
            # winner's committed row, regardless of isolation level (WR-006).
            with get_session() as fresh:
                winner = fresh.execute(stmt).scalar_one_or_none()
            if winner is not None:
                log.info("crawl.resume_job_concurrent", job_id=winner.id)
                return winner.id
            raise  # unexpected — re-raise if still not found


def _get_urls_to_process(
    job_id: str,
    seed_url: str,
    max_pages: int,
) -> list[str]:
    """Get URLs to process: pending states from a prior run, or seed the first URL.

    Resume logic (D-03): if there are pending crawl_states for this job,
    return only those URLs. Otherwise, seed with the source_url.
    """
    with get_session() as session:
        pending = registry_repo.pending_states(session, job_id)
        if pending:
            # Resume: return pending URLs (already seeded from a prior run)
            log.info(
                "crawl.resume",
                job_id=job_id,
                pending_count=len(pending),
            )
            return [state.url for state in pending]

    # First run: seed with the source URL
    norm_url = normalize_url(seed_url)
    with get_session() as session:
        registry_repo.upsert_crawl_state(
            session,
            job_id=job_id,
            url=seed_url,
            normalized_url=norm_url,
            status="pending",
        )

    return [seed_url]


async def _crawl_loop(
    urls: list[str],
    job_id: str,
    source_id: str,
    adapter: Any,
    robots_policy: Any,
    robots_crawl_delay: float | None,
    seed_domain: str,
    max_pages: int,
    settings: Settings,
    source_config: dict | None = None,
) -> dict[str, int]:
    """BFS crawl loop: fetch pages, extract links, expand queue up to max_pages.

    Returns stats dict with page counts.
    """
    limiter = PerHostLimiter()
    pages_complete = 0
    pages_robots_blocked = 0
    pages_failed = 0
    pages_total = 0
    # INGEST-10 (D-24): Count of linked-doc follows that fail (SSRF-rejected or ingest error).
    # Failed link follows do not abort the parent HTML crawl.
    linked_docs_failed = 0

    storage = StorageBackend(settings.storage)

    # BFS queue and visited set for link-following
    queue: deque[str] = deque(urls)
    seen: set[str] = {normalize_url(u) for u in urls}

    while queue and pages_total < max_pages:
        url = queue.popleft()
        pages_total += 1

        # SSRF re-validation on every URL (T-02-09, Pitfall 2)
        try:
            validate_public_url(url)
        except ValueError as exc:
            log.warning("crawl.ssrf_blocked", url=url, error=str(exc))
            _record_state(job_id, url, "failed", error=str(exc))
            pages_failed += 1
            continue

        # Same-domain enforcement
        if settings.crawl.same_domain_only:
            url_domain = _registrable_domain(url)
            if url_domain != seed_domain:
                log.info("crawl.cross_domain_skip", url=url, domain=url_domain)
                pages_total -= 1
                continue

        # Check robots.txt locally (our own Protego policy)
        url_path = urlparse(url).path or "/"
        if not robots_policy.is_allowed(url_path):
            log.info("crawl.robots_blocked_local", url=url)
            _record_state(job_id, url, "robots_blocked")
            pages_robots_blocked += 1
            continue

        # Rate limit — resolve delay and wait.
        # source_config is the per-source crawl_config sub-dict passed into _crawl_loop.
        # It is never None here (crawl_source always passes the looked-up dict, which
        # defaults to {} when absent — CRAWL-01 D-02 fix; see Pitfall 4 in RESEARCH.md).
        # CRAWL-03 (D-12): backoff_extra is computed from the limiter BEFORE resolve_delay
        # so any cooldown/error state from the previous response is applied to this fetch.
        backoff_extra = limiter.backoff_extra(url, settings.crawl.rate_limit_seconds)
        delay = resolve_delay(
            source_config,
            robots_crawl_delay,
            settings.crawl.rate_limit_seconds,
            backoff_extra=backoff_extra,
        )
        await limiter.wait(url, delay)

        # Fetch via adapter
        try:
            result = await adapter.fetch_page(url)
        except ValueError as exc:
            log.warning("crawl.adapter_ssrf_blocked", url=url, error=str(exc))
            _record_state(job_id, url, "failed", error=str(exc))
            pages_failed += 1
            continue
        except Exception as exc:
            log.error("crawl.adapter_error", url=url, error=str(exc))
            _record_state(job_id, url, "failed", error=str(exc))
            pages_failed += 1
            continue

        if result.status == "robots_blocked":
            _record_state(job_id, url, "robots_blocked")
            pages_robots_blocked += 1
            continue

        if result.status == "failed":
            _record_state(job_id, url, "failed", error=result.error)
            pages_failed += 1
            # CRAWL-03 (D-10/D-11): Update adaptive backoff state based on HTTP status.
            # 429 Too Many Requests or 403 Forbidden → record error for exponential backoff.
            # M-03 fix: do NOT reset_errors on other failures (e.g. 404, connection
            # timeout, DNS error).  A single 404 from a host that has accumulated
            # 429-based backoff state would wipe the error count and zero the delay,
            # causing the next request to proceed without backoff despite ongoing
            # rate-limiting.  Only genuine success (result.status == "complete")
            # resets backoff state — that branch calls limiter.reset_errors(url) below.
            if result.http_status_code in (429, 403):
                limiter.record_error(url)
                log.warning(
                    "crawl.backoff_applied",
                    url=url,
                    http_status_code=result.http_status_code,
                    backoff_extra=limiter.backoff_extra(url, settings.crawl.rate_limit_seconds),
                )
            continue

        # Success: write raw + bronze artifacts with lineage (D-01)
        raw_id, bronze_id = _write_artifacts(
            source_id=source_id,
            url=url,
            html=result.html,
            markdown=result.markdown,
            storage=storage,
        )

        # Record complete state
        _record_state(
            job_id,
            url,
            "complete",
            raw_artifact_id=raw_id,
            bronze_artifact_id=bronze_id,
        )
        pages_complete += 1
        # CRAWL-03: Reset backoff error state on successful fetch.
        limiter.reset_errors(url)

        # INGEST-10 (D-19): Linked-document ingestion runs AFTER _write_artifacts and
        # _record_state("complete") so the parent HTML bronze artifact is always committed
        # before any linked document is followed.
        #
        # L-04 fix: decode HTML bytes once here and share the string with both
        # _extract_linked_docs and _extract_links, avoiding a double decode per page.
        html_text: str | None = None
        if result.html is not None:
            html_text = result.html.decode("utf-8", errors="replace")
            linked_links = _extract_linked_docs(html_text, url)
            # _extract_linked_docs already applies MAX_LINKED_DOCS_PER_PAGE cap (D-20).
            loop = asyncio.get_running_loop()
            for link_url in linked_links:
                # D-20/D-23: Deduplicate against the crawl job's seen set.
                norm_link = normalize_url(link_url)
                if norm_link in seen:
                    continue
                seen.add(norm_link)

                # D-21 (T-08-05-01): SSRF guard on every followed link — defense in depth
                # even though ingest_url calls validate_public_url internally.
                try:
                    validate_public_url(link_url)
                except ValueError as exc:
                    log.warning(
                        "crawl.linked_doc_ssrf_blocked",
                        url=link_url,
                        error=str(exc),
                    )
                    linked_docs_failed += 1
                    continue

                # D-22 (Path B — tech debt): ingest_url() does not accept source_id or
                # job_id; linked artifact receives its own source row. The resulting
                # artifact is NOT directly linked to the parent HTML page's source_id.
                # Tracked as tech debt: extend ingest_url() to accept optional source_id
                # and job_id kwargs so linked docs can share the parent source's lineage.
                try:
                    await loop.run_in_executor(
                        None,
                        functools.partial(
                            ingest_url,
                            link_url,
                            source_name=_name_from_url(link_url),
                            settings=settings,
                        ),
                    )
                except Exception as exc:
                    log.warning(
                        "crawl.linked_doc_ingest_failed",
                        url=link_url,
                        error=str(exc),
                    )
                    linked_docs_failed += 1

        # Extract and enqueue discovered links (BFS link-following).
        # Re-uses html_text decoded above — no second decode (L-04 fix).
        if html_text is not None and pages_total < max_pages:
            discovered = _extract_links(html_text, url, seed_domain)
            for link in discovered:
                norm = normalize_url(link)
                if norm not in seen:
                    seen.add(norm)
                    queue.append(link)

    return {
        "pages_complete": pages_complete,
        "pages_robots_blocked": pages_robots_blocked,
        "pages_failed": pages_failed,
        "pages_total": pages_total,
        # INGEST-10 (D-24): Count of linked-doc follows that were SSRF-rejected or
        # raised an exception during ingest_url. Does not abort the parent crawl.
        "linked_docs_failed": linked_docs_failed,
    }


def _extract_links(html: bytes | str, base_url: str, seed_domain: str) -> list[str]:
    """Extract same-domain HTTP(S) links from raw HTML.

    Accepts bytes or str so the caller can decode once and share the
    string with _extract_linked_docs (L-04 fix — avoids double decode).
    Filters out fragments, non-http schemes, and cross-domain links.
    Returns deduplicated absolute URLs.
    """
    if isinstance(html, bytes):
        try:
            text = html.decode("utf-8", errors="replace")
        except Exception:
            return []
    else:
        text = html

    links: list[str] = []
    seen_in_page: set[str] = set()

    for match in _LINK_RE.finditer(text):
        href = match.group(1).strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue

        # Resolve relative URLs
        absolute = urljoin(base_url, href)
        # Strip fragment
        absolute, _ = urldefrag(absolute)

        # Only http/https
        parsed = urlparse(absolute)
        if parsed.scheme not in ("http", "https"):
            continue

        # Same-domain check
        link_domain = _registrable_domain(absolute)
        if link_domain != seed_domain:
            continue

        # Skip common non-content extensions
        path_lower = parsed.path.lower()
        if path_lower.endswith((".png", ".jpg", ".jpeg", ".gif", ".svg", ".css", ".js",
                                ".ico", ".woff", ".woff2", ".ttf", ".eot", ".mp4",
                                ".mp3", ".zip", ".gz", ".tar", ".exe")):
            continue

        if absolute not in seen_in_page:
            seen_in_page.add(absolute)
            links.append(absolute)

    return links


def _extract_linked_docs(
    html: bytes | str,
    base_url: str,
) -> list[str]:
    """Extract .pdf and .docx hrefs from raw HTML, returning absolute URLs.

    INGEST-10 (D-19/D-20): Linked-document extraction runs after the parent HTML
    page has been written as a bronze artifact. Only LINKED_DOC_EXTENSIONS are
    returned; .html and all other extensions are excluded.

    Key differences from _extract_links:
      - Does NOT apply a same-domain filter (.pdf/.docx on external domains are
        valid follows — RESEARCH.md anti-pattern note, D-19).
      - Returns LINKED_DOC_EXTENSIONS only (.pdf, .docx).
      - Applies the MAX_LINKED_DOCS_PER_PAGE cap on the returned list.
      - Handles both bytes and str input for flexibility.

    SSRF validation is NOT applied here — the caller must call validate_public_url
    on every URL before issuing any HTTP request (D-21, T-08-05-01).

    Args:
        html:      Raw HTML content (bytes or str). Bytes are decoded utf-8
                   with errors='replace'.
        base_url:  Absolute base URL of the page (used to resolve relative hrefs).

    Returns:
        List of absolute URLs (deduplicated within the page, capped at
        MAX_LINKED_DOCS_PER_PAGE).
    """
    if not html:
        return []

    if isinstance(html, bytes):
        try:
            text = html.decode("utf-8", errors="replace")
        except Exception:
            return []
    else:
        text = html

    links: list[str] = []
    seen_in_page: set[str] = set()

    for match in _LINK_RE.finditer(text):
        href = match.group(1).strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue

        # Resolve relative URLs against base_url
        absolute = urljoin(base_url, href)
        # Strip fragment
        absolute, _ = urldefrag(absolute)

        # Only http/https
        parsed = urlparse(absolute)
        if parsed.scheme not in ("http", "https"):
            continue

        # Only LINKED_DOC_EXTENSIONS — no same-domain filter (D-19)
        path_lower = parsed.path.lower()
        ext = _osp.splitext(path_lower)[1]  # L-03 fix: _osp imported at module level
        if ext not in LINKED_DOC_EXTENSIONS:
            continue

        if absolute not in seen_in_page:
            seen_in_page.add(absolute)
            links.append(absolute)

    # Apply cap here so callers always get a bounded list (D-20)
    return links[:MAX_LINKED_DOCS_PER_PAGE]


def _write_artifacts(
    source_id: str,
    url: str,
    html: bytes | None,
    markdown: str | None,
    storage: StorageBackend,
) -> tuple[str | None, str | None]:
    """Write raw HTML and bronze markdown artifacts with lineage.

    Returns (raw_artifact_id, bronze_artifact_id). Both may be None if
    content is missing.
    """
    if html is None:
        return None, None

    with get_session() as session:
        source_obj = registry_repo.get_source(session, source_id)
        source_name = source_obj.name if source_obj else "unknown"
        domain = (source_obj.config or {}).get("domain") or _UNCLASSIFIED_DOMAIN if source_obj else _UNCLASSIFIED_DOMAIN

        # Write raw HTML artifact with correct mime_type
        raw_artifact = storage.put_raw(
            source_id, html, "html", session,
            mime_type="text/html",
            domain=domain,
            tags={"domain": domain, "source_name": source_name, "format": "html", "artifact_type": "raw_document"},
        )
        session.flush()
        raw_id = raw_artifact.id

        # Write bronze markdown artifact with parent linkage (D-01)
        bronze_id = None
        if markdown:
            md_bytes = markdown.encode("utf-8")
            bronze_artifact = storage.put_bronze(
                source_id, md_bytes, "md", session,
                parent_artifact_id=raw_id,
                domain=domain,
                tags={"domain": domain, "source_name": source_name, "format": "md", "artifact_type": "bronze_document"},
            )
            session.flush()
            bronze_id = bronze_artifact.id

    log.info(
        "crawl.artifacts_written",
        url=url,
        raw_id=raw_id,
        bronze_id=bronze_id,
    )
    return raw_id, bronze_id


def _record_state(
    job_id: str,
    url: str,
    status: str,
    *,
    raw_artifact_id: str | None = None,
    bronze_artifact_id: str | None = None,
    error: str | None = None,
) -> None:
    """Upsert a crawl_state row for the given URL."""
    norm_url = normalize_url(url)
    fetched_at = (
        datetime.datetime.now(datetime.UTC)
        if status == "complete"
        else None
    )

    with get_session() as session:
        registry_repo.upsert_crawl_state(
            session,
            job_id=job_id,
            url=url,
            normalized_url=norm_url,
            status=status,
            raw_artifact_id=raw_artifact_id,
            bronze_artifact_id=bronze_artifact_id,
            fetched_at=fetched_at,
            error_msg=error,
        )


def _registrable_domain(url: str) -> str:
    """Extract the registrable domain from a URL."""
    extracted = tldextract.extract(url)
    return f"{extracted.domain}.{extracted.suffix}"


def _name_from_url(url: str) -> str:
    """Derive a human-readable source name from a URL."""
    parsed = urlparse(url)
    return parsed.netloc or "crawl-source"


async def crawl_all_sources(
    domain: str | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Crawl all registered sources sequentially, optionally filtered by domain.

    Implements CRAWL-02 (D-06/D-07/D-09):
      - Sequential loop, no parallelism for v2.0 (D-06)
      - Each source failure is caught, logged, and counted without aborting the batch (D-09)
      - Returns a summary dict with total, succeeded, failed, and per-source results

    Parameters
    ----------
    domain:
        Optional domain filter (e.g. 'healthcare'). If None, all sources are crawled.
    settings:
        Settings override. Uses get_settings() if None.

    Returns
    -------
    dict with keys:
        total (int): number of sources attempted
        succeeded (int): number of sources crawled successfully
        failed (int): number of sources that raised an exception
        results (list): per-source result dicts with at least source_id and status
    """
    s = settings or get_settings()

    # Fetch all sources (optionally filtered by domain) from the registry.
    # list_sources_for_crawl_all is a module-level wrapper so tests can patch it
    # without needing to inject a SQLAlchemy session (CRAWL-02, D-06).
    # It returns Source ORM objects in production; tests may return dicts.
    raw_sources = list_sources_for_crawl_all(domain=domain)

    # Materialise (url, id) pairs from whatever the source list returns.
    # Production: Source ORM objects with .url and .id attributes.
    # Tests: plain dicts (patched mock return value) — handled via isinstance check.
    source_pairs: list[tuple[Any, Any]] = []
    for src in raw_sources:
        if isinstance(src, dict):
            source_pairs.append((src["url"], src["id"]))
        else:
            source_pairs.append((src.url, src.id))

    total = len(source_pairs)
    succeeded = 0
    failed = 0
    results: list[dict[str, Any]] = []

    for source_url, source_id_val in source_pairs:
        try:
            result = await crawl_source(source_url, settings=s)
            # M-04 fix: spread result first, then explicitly override source_id and
            # status so the caller-supplied source_id_val wins over any 'source_id'
            # key that crawl_source() returns (which can differ when register_source
            # URL-deduplicates to a pre-existing source with a different ID).
            results.append({**result, "source_id": source_id_val, "status": "ok"})
            succeeded += 1
        except Exception as exc:
            log.warning(
                "crawl_all.source_failed",
                source_id=source_id_val,
                error=str(exc),
            )
            results.append(
                {"source_id": source_id_val, "status": "failed", "error": str(exc)}
            )
            failed += 1

    return {
        "total": total,
        "succeeded": succeeded,
        "failed": failed,
        "results": results,
    }
