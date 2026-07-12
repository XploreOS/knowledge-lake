"""Discovery pipeline: search → SSRF-validate → auto-register candidate sources.

The main entry point is discover_sources(query, limit, settings) which:
  1. Resolves the active DiscoveryPlugin via get_discovery(settings)
  2. Calls plugin.search(query, limit) to get candidate results
  3. For each result URL: validate_public_url() (SSRF guard, T-02-22)
  4. URL-first dedup: register_source() only creates a new row if the
     normalized URL does not already exist (D-08)
  5. Returns a list of per-result status dicts

Security (T-02-22):
    Every discovered URL passes through validate_public_url before being
    auto-registered. Private IPs, loopback, link-local, and non-https URLs
    are skipped + logged (not registered, not failed).

Dedup (D-08):
    Re-running the same query does not create duplicate source rows because
    register_source uses URL-first dedup (normalize_url → lookup → skip if exists).
"""

from __future__ import annotations

import structlog

from knowledge_lake.config.settings import Settings, get_settings
from knowledge_lake.pipeline.ingest import register_source, validate_public_url
from knowledge_lake.plugins.resolver import get_discovery

log = structlog.get_logger(__name__)


def discover_sources(
    query: str,
    *,
    limit: int = 20,
    settings: Settings | None = None,
) -> list[dict]:
    """Run a discovery query and auto-register valid results as candidate sources.

    Each discovered URL is SSRF-validated before registration. URLs that fail
    validation (private IPs, non-https) are skipped and logged. URLs already
    in the registry are returned with is_new=False (dedup, D-08).

    Registered sources have source_type='discovered' and store only URL + title
    (D-09: minimal metadata for discovered candidates).

    Args:
        query:    Natural-language search query for the discovery engine.
        limit:    Maximum number of results to request from the engine.
        settings: Settings override (uses get_settings() if None).

    Returns:
        List of dicts, one per discovery result, with keys:
          - url: The discovered URL
          - title: Title from the search result
          - source_id: Registry source ID (if registered)
          - status: 'registered' | 'existing' | 'skipped_ssrf'
    """
    s = settings or get_settings()
    plugin = get_discovery(s)

    log.info("discover_sources.start", query=query[:80], limit=limit, plugin=plugin.name)

    results = plugin.search(query, limit=limit)

    output: list[dict] = []
    registered_count = 0
    skipped_count = 0

    for item in results:
        # T-02-22: SSRF-validate every result URL before auto-registering
        try:
            validate_public_url(item.url)
        except ValueError as exc:
            log.warning(
                "discover_sources.ssrf_skip",
                url=item.url,
                reason=str(exc),
            )
            output.append({
                "url": item.url,
                "title": item.title,
                "source_id": None,
                "status": "skipped_ssrf",
            })
            skipped_count += 1
            continue

        # D-08: Auto-register with source_type='discovered', D-09: URL + title only
        # register_source handles URL-first dedup (normalize → lookup → skip if exists)
        reg_result = register_source(
            url=item.url,
            name=item.title or item.url,
            source_type_override="discovered",
        )

        status = "existing" if not reg_result["is_new"] else "registered"
        if reg_result["is_new"]:
            registered_count += 1

        output.append({
            "url": item.url,
            "title": item.title,
            "source_id": reg_result["source_id"],
            "status": status,
        })

    log.info(
        "discover_sources.complete",
        query=query[:80],
        total=len(results),
        registered=registered_count,
        skipped_ssrf=skipped_count,
    )
    return output
