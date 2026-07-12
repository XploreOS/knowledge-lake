"""Pipeline service function: load_domain (D-05, MCP-01).

Promoted from ``api/app.py:_register_domain_sources`` so the REST endpoint,
CLI ``init`` command, and MCP ``init_domain`` tool all call one implementation
(one function, many callers — D-03, A4).

Security: ``name`` is validated against the path-traversal guard
``^[a-zA-Z][a-zA-Z0-9_-]{0,63}$`` at function entry (T-12-06, ASVS V5).
"""
from __future__ import annotations

import re

# Path-traversal guard (T-12-06): kept in sync with cli/app.py and schemas.py:710.
_DOMAIN_NAME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]{0,63}$")


def load_domain(name: str) -> dict:
    """Load a domain pack and register its crawl-type sources.

    Reads ``domains/<name>/sources.yaml`` (via ``DomainLoader.from_name``),
    registers every crawl-type entry into the registry, validates cron
    schedules before persisting (D-05a, T-11-CRON), and returns summary counts.
    Upload-type entries are counted but not auto-registered.

    Args:
        name: Domain pack name, e.g. ``"healthcare"``.  Must match
              ``^[a-zA-Z][a-zA-Z0-9_-]{0,63}$`` (path-traversal guard,
              T-12-06).

    Returns:
        A dict with integer counts::

            {
                "name":                 <str>,
                "loaded_count":         <int>,
                "skipped_count":        <int>,
                "upload_required_count": <int>,
            }

    Raises:
        ValueError:      If ``name`` fails the domain-name guard (T-12-06).
        FileNotFoundError: If the domain pack directory does not exist.
    """
    # Defence-in-depth path-traversal guard (T-12-06) — re-validate even when
    # the caller (Pydantic schema, CLI guard) already checked.
    if not _DOMAIN_NAME_RE.fullmatch(name):
        raise ValueError(
            f"Invalid domain name {name!r}: must match "
            r"^[a-zA-Z][a-zA-Z0-9_-]{0,63}$ (path traversal guard)"
        )

    from pathlib import Path

    from sqlalchemy.exc import IntegrityError

    from knowledge_lake.config.settings import get_settings
    from knowledge_lake.domains.loader import DomainLoader
    from knowledge_lake.pipeline.ingest import normalize_url
    from knowledge_lake.registry import repo as registry_repo
    from knowledge_lake.registry.db import get_session
    from knowledge_lake.registry.repo import get_source_by_normalized_url

    settings = get_settings()
    _domains_path = Path(settings.domain.domains_root).resolve()
    root = _domains_path.parent if _domains_path.name == "domains" else _domains_path

    loader = DomainLoader.from_name(name, root=root)

    loaded_count = 0
    skipped_count = 0
    upload_required_count = 0

    for entry in loader.sources:
        if entry.ingest_type == "upload":
            upload_required_count += 1
            continue

        # Validate crawl_schedule before persisting (D-05a, T-11-CRON).
        # Preserved from cli/app.py:~1105-1116 (A4 — shared path).
        validated_schedule = entry.crawl_schedule
        if validated_schedule is not None:
            try:
                from dagster._utils.schedules import is_valid_cron_string

                if not is_valid_cron_string(validated_schedule):
                    validated_schedule = None
            except Exception:
                # Dagster not available or schedule module not importable —
                # treat schedule as invalid and omit it rather than crashing.
                validated_schedule = None

        try:
            with get_session() as session:
                try:
                    norm_url = normalize_url(entry.url)
                except Exception:
                    norm_url = entry.url

                existing = get_source_by_normalized_url(session, norm_url)
                if existing is not None:
                    skipped_count += 1
                    continue

                registry_repo.create_source(
                    session,
                    name=entry.name,
                    source_type=entry.source_type,
                    url=entry.url,
                    normalized_url=norm_url,
                    license_type=entry.license,
                    crawl_schedule=validated_schedule,
                    config={
                        "domain": name,
                        "tags": entry.tags,
                        "crawl_config": entry.crawl_config,
                        "ingest_type": entry.ingest_type,
                    },
                )
                session.commit()
                loaded_count += 1
        except IntegrityError:
            skipped_count += 1

    return {
        "name": name,
        "loaded_count": loaded_count,
        "skipped_count": skipped_count,
        "upload_required_count": upload_required_count,
    }
