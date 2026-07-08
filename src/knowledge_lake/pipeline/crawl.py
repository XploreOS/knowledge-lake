"""Crawl orchestrator: drive a crawl job from seed URL to raw+bronze artifacts.

Implements the full crawl vertical slice (INGEST-04, INGEST-09):
  - SSRF re-validation of every URL before fetch (T-02-09, Pitfall 2)
  - Two-artifact-per-page write: raw HTML + bronze markdown (D-01 lineage)
  - Resume from pending crawl_states on re-run (D-03)
  - Per-host rate limiting via three-tier resolver + PerHostLimiter
  - Robots-blocked recording (no artifact write for blocked URLs, D-13)
  - Same-domain scope enforcement via tldextract
  - Hash-second dedup at the artifact layer (INGEST-08)

Functions:
    crawl_source(source_url, *, crawler=None, settings=None, max_pages=None) -> dict
"""

from __future__ import annotations

import asyncio
import datetime
import re
from collections import deque
from typing import Any, Optional
from urllib.parse import urljoin, urlparse, urldefrag

import structlog
import tldextract

from knowledge_lake.config.settings import Settings, get_settings
from knowledge_lake.crawl.ratelimit import PerHostLimiter, resolve_delay
from knowledge_lake.crawl.robots import fetch_robots
from knowledge_lake.pipeline.ingest import normalize_url, register_source, validate_public_url
from knowledge_lake.plugins.resolver import get_crawler
from knowledge_lake.registry.db import get_session
from knowledge_lake.registry import repo as registry_repo
from knowledge_lake.storage.s3 import StorageBackend

log = structlog.get_logger(__name__)

_LINK_RE = re.compile(r'href=["\']([^"\']+)["\']', re.IGNORECASE)


async def crawl_source(
    source_url: str,
    *,
    crawler: Optional[str] = None,
    settings: Optional[Settings] = None,
    max_pages: Optional[int] = None,
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
          pages_failed, pages_total
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
    )

    # Update job status
    with get_session() as session:
        job_obj = session.get(registry_repo.Job, job_id)
        if job_obj:
            job_obj.status = "complete"
            job_obj.stats = stats
            job_obj.updated_at = datetime.datetime.now(datetime.timezone.utc)

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
    robots_crawl_delay: Optional[float],
    seed_domain: str,
    max_pages: int,
    settings: Settings,
) -> dict[str, int]:
    """BFS crawl loop: fetch pages, extract links, expand queue up to max_pages.

    Returns stats dict with page counts.
    """
    limiter = PerHostLimiter()
    pages_complete = 0
    pages_robots_blocked = 0
    pages_failed = 0
    pages_total = 0

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

        # Rate limit — resolve delay and wait
        source_config = None
        delay = resolve_delay(source_config, robots_crawl_delay, settings.crawl.rate_limit_seconds)
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

        # Extract and enqueue discovered links (BFS link-following)
        if result.html and pages_total < max_pages:
            discovered = _extract_links(result.html, url, seed_domain)
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
    }


def _extract_links(html: bytes, base_url: str, seed_domain: str) -> list[str]:
    """Extract same-domain HTTP(S) links from raw HTML.

    Filters out fragments, non-http schemes, and cross-domain links.
    Returns deduplicated absolute URLs.
    """
    try:
        text = html.decode("utf-8", errors="replace")
    except Exception:
        return []

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


def _write_artifacts(
    source_id: str,
    url: str,
    html: Optional[bytes],
    markdown: Optional[str],
    storage: StorageBackend,
) -> tuple[Optional[str], Optional[str]]:
    """Write raw HTML and bronze markdown artifacts with lineage.

    Returns (raw_artifact_id, bronze_artifact_id). Both may be None if
    content is missing.
    """
    if html is None:
        return None, None

    with get_session() as session:
        # Write raw HTML artifact with correct mime_type
        raw_artifact = storage.put_raw(source_id, html, "html", session, mime_type="text/html")
        session.flush()
        raw_id = raw_artifact.id

        # Write bronze markdown artifact with parent linkage (D-01)
        bronze_id = None
        if markdown:
            md_bytes = markdown.encode("utf-8")
            bronze_artifact = storage.put_bronze(
                source_id, md_bytes, "md", session,
                parent_artifact_id=raw_id,
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
    raw_artifact_id: Optional[str] = None,
    bronze_artifact_id: Optional[str] = None,
    error: Optional[str] = None,
) -> None:
    """Upsert a crawl_state row for the given URL."""
    norm_url = normalize_url(url)
    fetched_at = (
        datetime.datetime.now(datetime.timezone.utc)
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
