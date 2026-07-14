"""Wiki compilation stage: enriched_document artifacts → interlinked Markdown knowledge base.

Implements KB-01..KB-04 (wiki page generation, cross-linking, incremental rebuild).

Design decisions:
    D-01: Wiki pages stored as individual S3 objects in gold/{domain}/wiki/
    D-02: Slugs derived deterministically via lowercase + hyphen normalization; collision
          disambiguation via content-hash suffix
    D-03: Entity cross-linking uses IDF-filtered enrichment metadata (entities field from
          enrich.py); concept page threshold: min_entity_df >= 2 AND IDF >= min_entity_idf
    D-06: Manifest-based incremental rebuild — content-hash diff drives page writes
    D-07: First run is full build; subsequent runs diff against manifest
    D-08: Deterministic summaries from enrichment metadata (no LLM call by default)
    D-09: LLM summary mode is opt-in behind WikiSettings.use_llm_summaries and budget cap
    D-13: One S3 object per wiki page; never bundled archive (unless --archive flag)
    D-15: Optional .tar.gz archive for bulk download / Obsidian vault import

Security mitigations:
    T-16-01: slugify() strips all non-alphanumeric chars; keys composed from _GOLD_PREFIX +
             domain_seg + slugified strings only — no raw user input in S3 keys
    T-16-04: IDF threshold limits concept page explosion; large corpus warning at >1000 docs
    T-16-05: Manifest loaded via orjson.loads (safe parser); schema validated; malformed
             manifest triggers full rebuild with warning
"""

from __future__ import annotations

import hashlib
import io
import math
import re
import tarfile
import time
from typing import Any

import orjson
import structlog
from botocore.exceptions import ClientError

from knowledge_lake.config.settings import Settings, get_settings
from knowledge_lake.registry import repo as registry_repo
from knowledge_lake.registry.db import get_session
from knowledge_lake.storage.s3 import _UNCLASSIFIED_DOMAIN, StorageBackend

log = structlog.get_logger(__name__)

# ── Zone prefix ───────────────────────────────────────────────────────────────

_GOLD_PREFIX = "gold"
_WIKI_SEGMENT = "wiki"

# ── Security: non-alphanumeric sanitization for S3 keys ──────────────────────

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_MULTI_HYPHEN_RE = re.compile(r"-{2,}")


# ── Pure helper functions ─────────────────────────────────────────────────────


def _sanitize_wikilink_display(text: str) -> str:
    """Strip characters that break Obsidian wikilink display text.

    In ``[[target|display]]`` syntax:
    - A ``|`` inside *display* acts as a second separator, silently truncating.
    - A ``]]`` inside *display* prematurely closes the wikilink.
    - A newline inside a ``# heading`` breaks the Markdown heading.

    Parameters
    ----------
    text:
        Raw display text (entity name, document title, etc.) from LLM output.

    Returns
    -------
    str
        Sanitized display text safe for use in Obsidian wikilinks and headings.
    """
    return text.replace("|", "-").replace("]]", "").replace("\n", " ").replace("\r", " ")


def slugify(title: str) -> str:
    """Produce a deterministic ASCII slug from a title (D-02, T-16-01).

    Steps:
        1. Encode to ASCII, dropping non-ASCII characters.
        2. Lowercase.
        3. Replace any run of non-alphanumeric characters with a single hyphen.
        4. Strip leading/trailing hyphens.
        5. Collapse multiple hyphens.
        6. Fall back to "untitled" if the result is empty.

    Parameters
    ----------
    title:
        Human-readable page title (from enrichment metadata or entity name).

    Returns
    -------
    str
        URL-safe, S3-safe slug string.
    """
    # Drop non-ASCII
    ascii_title = title.encode("ascii", "ignore").decode("ascii")
    lowered = ascii_title.lower()
    slugged = _SLUG_RE.sub("-", lowered)
    slugged = _MULTI_HYPHEN_RE.sub("-", slugged).strip("-")
    return slugged or "untitled"


def disambiguate_slug(slug: str, content_hash: str) -> str:
    """Append the first 8 hex characters of content_hash to resolve slug collisions (D-02).

    Parameters
    ----------
    slug:
        Base slug (from slugify).
    content_hash:
        Content hash string (hex digits); first 8 chars appended as suffix.

    Returns
    -------
    str
        ``{slug}-{content_hash[:8]}``
    """
    return f"{slug}-{content_hash[:8]}"


def compute_entity_idf(
    entity_doc_freq: dict[str, int],
    total_docs: int,
    min_entity_df: int = 2,
) -> dict[str, float]:
    """Compute log-based IDF scores for entities meeting the minimum document-frequency (D-03, D-05).

    IDF formula: log(total_docs / df)

    Only entities with df >= min_entity_df are included. Entities with df < min_entity_df
    are filtered out before IDF computation to avoid noisy concept pages.

    Parameters
    ----------
    entity_doc_freq:
        Mapping of entity name → count of documents containing that entity.
    total_docs:
        Total number of documents in the corpus.
    min_entity_df:
        Minimum document frequency threshold (default 2 — KB-03, D-03).

    Returns
    -------
    dict[str, float]
        Mapping of entity name → IDF score for entities meeting the threshold.
        Empty dict if total_docs == 0 or no entities pass the filter.
    """
    if total_docs == 0 or not entity_doc_freq:
        return {}
    result: dict[str, float] = {}
    for entity, df in entity_doc_freq.items():
        if df >= min_entity_df:
            result[entity] = math.log(total_docs / df)
    return result


def _identify_changed_pages(
    current_docs: dict[str, str],
    manifest: dict[str, str],
) -> tuple[set[str], set[str], set[str]]:
    """Diff current page content hashes against the stored manifest (D-06).

    Parameters
    ----------
    current_docs:
        Mapping of S3 key → SHA256 content hash for all pages in the current build.
    manifest:
        Mapping of S3 key → SHA256 content hash from the stored manifest.

    Returns
    -------
    tuple[set[str], set[str], set[str]]
        (new_pages, changed_pages, removed_pages):
        - new_pages: keys in current_docs not in manifest
        - changed_pages: keys in both with different hashes
        - removed_pages: keys in manifest not in current_docs
    """
    new_pages: set[str] = set()
    changed_pages: set[str] = set()
    removed_pages: set[str] = set()

    for key, current_hash in current_docs.items():
        if key not in manifest:
            new_pages.add(key)
        elif manifest[key] != current_hash:
            changed_pages.add(key)

    for key in manifest:
        if key not in current_docs:
            removed_pages.add(key)

    return new_pages, changed_pages, removed_pages


# ── Rendering helpers ─────────────────────────────────────────────────────────


def _render_doc_page(
    title: str,
    document_type: str,
    keywords: list[str],
    entities_with_slugs: list[tuple[str, str]],  # (entity_name, concept_slug)
    lead_paragraph: str,
    source_name: str,
    source_url: str | None,
) -> str:
    """Render a Markdown document summary page (D-04, D-08, KB-01).

    Parameters
    ----------
    title:
        Document title.
    document_type:
        Enrichment document_type (e.g., 'article', 'guide').
    keywords:
        List of keyword strings from enrichment metadata.
    entities_with_slugs:
        List of (entity_name, concept_slug) tuples for qualifying entities.
        Each entity gets a [[concept-slug|Entity Name]] wikilink.
    lead_paragraph:
        Lead paragraph / excerpt from enrichment summary (D-08).
    source_name:
        Name of the originating source.
    source_url:
        URL of the originating source (may be None).

    Returns
    -------
    str
        Rendered Markdown page content.
    """
    lines: list[str] = []
    lines.append(f"# {title}")
    lines.append("")
    lines.append(f"**Type:** {document_type or 'unknown'}")
    if source_url:
        lines.append(f"**Source:** [{source_name}]({source_url})")
    else:
        lines.append(f"**Source:** {source_name}")
    lines.append("")

    if lead_paragraph:
        lines.append("## Summary")
        lines.append("")
        lines.append(lead_paragraph)
        lines.append("")

    if keywords:
        lines.append("## Keywords")
        lines.append("")
        lines.append(", ".join(f"`{kw}`" for kw in keywords))
        lines.append("")

    if entities_with_slugs:
        lines.append("## Related Concepts")
        lines.append("")
        for entity_name, concept_slug in entities_with_slugs:
            lines.append(f"- [[{concept_slug}|{_sanitize_wikilink_display(entity_name)}]]")
        lines.append("")

    return "\n".join(lines)


def _render_concept_page(
    entity_name: str,
    entity_slug: str,
    doc_links: list[tuple[str, str]],  # (doc_slug, doc_title)
) -> str:
    """Render a Markdown concept (entity) page with backlinks to all containing documents (D-04, KB-03).

    Parameters
    ----------
    entity_name:
        Human-readable entity name.
    entity_slug:
        Slug for this concept page (used in [[wikilinks]]).
    doc_links:
        List of (doc_slug, doc_title) tuples for documents containing this entity.

    Returns
    -------
    str
        Rendered Markdown page content.
    """
    lines: list[str] = []
    lines.append(f"# {entity_name}")
    lines.append("")
    lines.append(f"*Concept page for entity: **{entity_name}***")
    lines.append("")

    if doc_links:
        lines.append("## Documents")
        lines.append("")
        for doc_slug, doc_title in doc_links:
            lines.append(f"- [[{doc_slug}|{_sanitize_wikilink_display(doc_title)}]]")
        lines.append("")

    return "\n".join(lines)


def _render_index_page(
    doc_entries: list[tuple[str, str, str]],   # (slug, title, source_name)
    concept_entries: list[tuple[str, str]],    # (slug, entity_name)
) -> str:
    """Render the root index page listing all document and concept pages (KB-02).

    Documents are grouped by source for navigability. Uses [[wikilinks]] for all
    page references so the archive is immediately usable as an Obsidian vault.

    Parameters
    ----------
    doc_entries:
        List of (slug, title, source_name) tuples for all document pages.
    concept_entries:
        List of (slug, entity_name) tuples for all concept pages.

    Returns
    -------
    str
        Rendered Markdown index page content.
    """
    lines: list[str] = []
    lines.append("# Knowledge Base Index")
    lines.append("")

    # Group document entries by source
    from collections import defaultdict
    by_source: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for slug, title, source_name in doc_entries:
        by_source[source_name].append((slug, title))

    lines.append("## Documents")
    lines.append("")
    for source_name in sorted(by_source):
        lines.append(f"### {source_name}")
        lines.append("")
        for slug, title in sorted(by_source[source_name], key=lambda x: x[1]):
            lines.append(f"- [[{slug}|{_sanitize_wikilink_display(title)}]]")
        lines.append("")

    if concept_entries:
        lines.append("## Concepts")
        lines.append("")
        for slug, entity_name in sorted(concept_entries, key=lambda x: x[1]):
            lines.append(f"- [[{slug}|{_sanitize_wikilink_display(entity_name)}]]")
        lines.append("")

    return "\n".join(lines)


# ── Storage factory ───────────────────────────────────────────────────────────


def _make_storage(s: Settings) -> StorageBackend:
    """Build the single StorageBackend from Settings.

    Extracted as a module-level function so tests can monkeypatch it without
    constructing a real boto3 client (mirrors export.py pattern).
    """
    return StorageBackend(s.storage)


# ── Main entry point ──────────────────────────────────────────────────────────


def compile_wiki(
    domain: str,
    force: bool = False,
    dry_run: bool = False,
    archive: bool = False,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Compile an interlinked Markdown wiki knowledge base for the given domain (KB-01..KB-04).

    Reads all enriched_document artifacts for the domain from the registry, then:
    - Renders per-document summary pages with [[wikilinks]] to concept pages (KB-01)
    - Renders a root index page (KB-02)
    - Renders cross-document concept pages for IDF-filtered entities (KB-03)
    - Writes only changed pages (manifest-based incremental rebuild, KB-04)

    Parameters
    ----------
    domain:
        Domain to compile the wiki for (e.g. 'healthcare'). Must match the
        domain field in Source.config.
    force:
        If True, ignore the manifest and rebuild all pages (full rebuild).
    dry_run:
        If True, compute what would change but write no pages to S3.
    archive:
        If True, create an in-memory .tar.gz of all wiki pages and write to S3.
    settings:
        Optional Settings override (useful for testing). Defaults to get_settings().

    Returns
    -------
    dict
        Summary dict with keys:
        - pages_created: int — new pages written
        - pages_updated: int — changed pages rewritten
        - pages_unchanged: int — pages skipped (content unchanged)
        - pages_removed: int — stale S3 pages deleted (incremental cleanup)
        - concept_pages: int — number of concept pages in this build
        - manifest_uri: str — S3 URI of the updated manifest
        - archive_uri: str | None — S3 URI of the .tar.gz archive, or None
    """
    s = settings or get_settings()
    wiki_cfg = s.wiki
    storage = _make_storage(s)
    domain_seg = domain or _UNCLASSIFIED_DOMAIN

    log.info("wiki.compile.start", domain=domain_seg)

    # ── 1. Gather enriched documents ──────────────────────────────────────────

    with get_session() as session:
        all_enriched = registry_repo.list_artifacts_by_type(session, "enriched_document")

        # Filter to the requested domain via source.config["domain"]
        domain_docs: list[dict[str, Any]] = []
        for artifact in all_enriched:
            source_domain = registry_repo.get_domain_for_source(session, artifact.source_id)
            if source_domain != domain:
                continue
            source = registry_repo.get_source(session, artifact.source_id)
            meta = artifact.metadata_ or {}
            domain_docs.append({
                "artifact_id": artifact.id,
                "source_id": artifact.source_id,
                "source_name": source.name if source else "Unknown",
                "source_url": source.url if source else None,
                "title": meta.get("title", ""),
                "summary": meta.get("summary", ""),
                "document_type": meta.get("document_type", ""),
                "keywords": meta.get("keywords", [])[:20],  # bound per EnrichmentResult
                "entities": meta.get("entities", [])[:50],
                "content_hash": artifact.content_hash,
            })

    total_docs = len(domain_docs)
    if total_docs > 1000:
        log.warning(
            "wiki.compile.large_corpus",
            domain=domain_seg,
            doc_count=total_docs,
            message="Large corpus — IDF threshold tuning recommended to limit concept page count",
        )

    log.info("wiki.compile.building", domain=domain_seg, doc_count=total_docs)

    # ── 2. Compute entity IDF ─────────────────────────────────────────────────

    entity_doc_freq: dict[str, int] = {}
    for doc in domain_docs:
        seen_in_doc: set[str] = set()
        for entity in doc["entities"]:
            if entity not in seen_in_doc:
                entity_doc_freq[entity] = entity_doc_freq.get(entity, 0) + 1
                seen_in_doc.add(entity)

    idf_scores = compute_entity_idf(
        entity_doc_freq,
        total_docs=total_docs,
        min_entity_df=wiki_cfg.min_entity_df,
    )

    # Apply IDF threshold — only entities above min_entity_idf get concept pages
    qualifying_entities: set[str] = {
        entity for entity, idf in idf_scores.items()
        if idf >= wiki_cfg.min_entity_idf
    }

    # ── 3. Build slug registry ────────────────────────────────────────────────

    # Document slugs: keyed by artifact_id → (slug, S3 key)
    doc_slug_map: dict[str, tuple[str, str]] = {}  # artifact_id -> (slug, key)
    used_doc_slugs: dict[str, str] = {}  # slug -> artifact_id (for collision detection)

    for doc in domain_docs:
        title = doc["title"] or f"document-{doc['artifact_id']}"
        base_slug = slugify(title)
        if base_slug not in used_doc_slugs:
            slug = base_slug
        else:
            # Primary disambiguation: append first 8 chars of content hash.
            slug = disambiguate_slug(base_slug, doc["content_hash"])
            if slug in used_doc_slugs:
                # Secondary collision: fall back to artifact_id hash suffix.
                artifact_hash = hashlib.sha256(doc["artifact_id"].encode()).hexdigest()
                slug = disambiguate_slug(base_slug, artifact_hash)
        used_doc_slugs[slug] = doc["artifact_id"]
        key = f"{_GOLD_PREFIX}/{domain_seg}/{_WIKI_SEGMENT}/doc/{slug}.md"
        doc_slug_map[doc["artifact_id"]] = (slug, key)

    # Concept slugs: entity_name → (slug, S3 key)
    concept_slug_map: dict[str, tuple[str, str]] = {}
    used_concept_slugs: dict[str, str] = {}

    for entity in sorted(qualifying_entities):
        base_slug = slugify(entity)
        if base_slug not in used_concept_slugs:
            slug = base_slug
        else:
            # Primary disambiguation: use entity name hash suffix.
            entity_hash = hashlib.sha256(entity.encode("utf-8")).hexdigest()
            slug = disambiguate_slug(base_slug, entity_hash)
            if slug in used_concept_slugs:
                # Secondary collision: use full entity hash (next 8 chars) as suffix.
                slug = disambiguate_slug(base_slug, entity_hash[8:16])
        used_concept_slugs[slug] = entity
        key = f"{_GOLD_PREFIX}/{domain_seg}/{_WIKI_SEGMENT}/concept/{slug}.md"
        concept_slug_map[entity] = (slug, key)

    # ── 4. Render all pages ───────────────────────────────────────────────────

    pages: dict[str, bytes] = {}  # S3 key → encoded page bytes

    # 4a. Document pages
    for doc in domain_docs:
        artifact_id = doc["artifact_id"]
        doc_slug, doc_key = doc_slug_map[artifact_id]

        # Gather qualifying entities for this document with their concept slugs
        entities_with_slugs: list[tuple[str, str]] = []
        for entity in doc["entities"]:
            if entity in qualifying_entities and entity in concept_slug_map:
                concept_slug, _ = concept_slug_map[entity]
                entities_with_slugs.append((entity, concept_slug))

        lead = (doc["summary"] or "")[:wiki_cfg.summary_excerpt_chars]

        content = _render_doc_page(
            title=doc["title"] or doc_slug,
            document_type=doc["document_type"],
            keywords=doc["keywords"],
            entities_with_slugs=entities_with_slugs,
            lead_paragraph=lead,
            source_name=doc["source_name"],
            source_url=doc["source_url"],
        )
        pages[doc_key] = content.encode("utf-8")

    # 4b. Concept pages (inverted index: entity -> documents containing it)
    entity_doc_links: dict[str, list[tuple[str, str]]] = {}  # entity -> [(doc_slug, doc_title)]
    for doc in domain_docs:
        artifact_id = doc["artifact_id"]
        doc_slug, _ = doc_slug_map[artifact_id]
        doc_title = doc["title"] or doc_slug
        for entity in doc["entities"]:
            if entity in qualifying_entities:
                entity_doc_links.setdefault(entity, []).append((doc_slug, doc_title))

    for entity, (concept_slug, concept_key) in concept_slug_map.items():
        doc_links = entity_doc_links.get(entity, [])
        content = _render_concept_page(
            entity_name=entity,
            entity_slug=concept_slug,
            doc_links=doc_links,
        )
        pages[concept_key] = content.encode("utf-8")

    # 4c. Root index page
    doc_entries = [
        (doc_slug_map[doc["artifact_id"]][0], doc["title"] or doc_slug_map[doc["artifact_id"]][0], doc["source_name"])
        for doc in domain_docs
    ]
    concept_entries = [
        (concept_slug, entity)
        for entity, (concept_slug, _) in concept_slug_map.items()
    ]
    index_key = f"{_GOLD_PREFIX}/{domain_seg}/{_WIKI_SEGMENT}/index.md"
    index_content = _render_index_page(doc_entries, concept_entries)
    pages[index_key] = index_content.encode("utf-8")

    # ── 5. Compute content hashes for manifest diff ───────────────────────────

    current_hashes: dict[str, str] = {
        key: hashlib.sha256(data).hexdigest()
        for key, data in pages.items()
    }

    # ── 6. Load existing manifest (or start fresh) ────────────────────────────

    manifest_key = f"{_GOLD_PREFIX}/{domain_seg}/{_WIKI_SEGMENT}/_manifest.json"
    existing_manifest: dict[str, str] = {}

    if not force:
        try:
            manifest_bytes = storage.get_object(manifest_key)
            try:
                raw_manifest = orjson.loads(manifest_bytes)
                if isinstance(raw_manifest, dict):
                    existing_manifest = raw_manifest
                else:
                    log.warning(
                        "wiki.compile.manifest_invalid",
                        domain=domain_seg,
                        reason="not a dict — triggering full rebuild",
                    )
            except (orjson.JSONDecodeError, ValueError) as exc:
                log.warning(
                    "wiki.compile.manifest_parse_error",
                    domain=domain_seg,
                    error=str(exc),
                    action="triggering full rebuild",
                )
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code", "")
            if error_code in ("NoSuchKey", "404"):
                log.info("wiki.compile.no_manifest", domain=domain_seg, action="full build")
            else:
                log.warning(
                    "wiki.compile.manifest_fetch_error",
                    domain=domain_seg,
                    error=str(exc),
                    action="triggering full rebuild",
                )

    # ── 7. Identify changed pages ─────────────────────────────────────────────

    new_pages, changed_pages, removed_pages = _identify_changed_pages(
        current_hashes, existing_manifest
    )
    pages_to_write = new_pages | changed_pages
    pages_unchanged = set(current_hashes.keys()) - pages_to_write

    pages_created = len(new_pages)
    pages_updated = len(changed_pages)
    pages_unchanged_count = len(pages_unchanged)

    # ── 8. Dry run — return counts without writing ────────────────────────────

    if dry_run:
        log.info(
            "wiki.compile.dry_run",
            domain=domain_seg,
            pages_created=pages_created,
            pages_updated=pages_updated,
            pages_unchanged=pages_unchanged_count,
            pages_removed=len(removed_pages),
        )
        return {
            "pages_created": pages_created,
            "pages_updated": pages_updated,
            "pages_unchanged": pages_unchanged_count,
            "pages_removed": len(removed_pages),
            "concept_pages": len(concept_slug_map),
            "manifest_uri": storage.object_uri(manifest_key),
            "archive_uri": None,
        }

    # ── 9. Write changed pages to S3 ─────────────────────────────────────────

    for key in pages_to_write:
        data = pages[key]
        # Determine page type from key for tagging (T-16-01: keys composed from safe slugs only)
        if "/doc/" in key:
            page_type = "doc"
        elif "/concept/" in key:
            page_type = "concept"
        else:
            page_type = "index"
        storage.put_object(
            key,
            data,
            tags={
                "domain": domain_seg,
                "format": "markdown",
                "artifact_type": f"wiki_{page_type}",
            },
        )

    # ── 9b. Delete removed pages from S3 ─────────────────────────────────────

    for key in removed_pages:
        try:
            storage.delete_object(key)
        except ClientError as exc:
            log.warning(
                "wiki.compile.delete_failed",
                key=key,
                error=str(exc),
            )

    # ── 10. Write updated manifest ────────────────────────────────────────────

    updated_manifest = dict(current_hashes)
    manifest_data = orjson.dumps(updated_manifest)
    storage.put_object(
        manifest_key,
        manifest_data,
        tags={"domain": domain_seg, "format": "json", "artifact_type": "wiki_manifest"},
    )
    manifest_uri = storage.object_uri(manifest_key)

    # ── 11. Optional archive ──────────────────────────────────────────────────

    archive_uri: str | None = None
    if archive:
        buf = io.BytesIO()
        _archive_mtime = int(time.time())  # single timestamp for all entries (consistent sort)
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            for key, data in pages.items():
                # Preserve directory structure within the tar
                # Strip gold/{domain}/wiki/ prefix for relative paths in archive
                prefix = f"{_GOLD_PREFIX}/{domain_seg}/{_WIKI_SEGMENT}/"
                arc_name = key[len(prefix):] if key.startswith(prefix) else key
                info = tarfile.TarInfo(name=arc_name)
                info.size = len(data)
                info.mtime = _archive_mtime
                tar.addfile(info, io.BytesIO(data))
        buf.seek(0)
        archive_hash = hashlib.sha256(buf.getvalue()).hexdigest()[:12]
        archive_key = f"{_GOLD_PREFIX}/{domain_seg}/{_WIKI_SEGMENT}/wiki-{archive_hash}.tar.gz"
        storage.put_object(
            archive_key,
            buf.getvalue(),
            tags={"domain": domain_seg, "format": "tar.gz", "artifact_type": "wiki_archive"},
        )
        archive_uri = storage.object_uri(archive_key)

    log.info(
        "wiki.compile.complete",
        domain=domain_seg,
        pages_created=pages_created,
        pages_updated=pages_updated,
        pages_unchanged=pages_unchanged_count,
        pages_removed=len(removed_pages),
        concept_pages=len(concept_slug_map),
        manifest_uri=manifest_uri,
        archive_uri=archive_uri,
    )

    return {
        "pages_created": pages_created,
        "pages_updated": pages_updated,
        "pages_unchanged": pages_unchanged_count,
        "pages_removed": len(removed_pages),
        "concept_pages": len(concept_slug_map),
        "manifest_uri": manifest_uri,
        "archive_uri": archive_uri,
    }
