"""Ingest stage: download or load raw bytes → raw_document artifact.

Functions:
    ingest_url(url, source)  — fetch via httpx, SSRF guard, size cap, registry write
    ingest_file(path, source) — load from local path (hermetic fixture testing)

Security (T-01-11, threat model):
    - ingest_url: validates scheme is https only (SSRF seam per Pitfall C)
    - ingest_url: blocks RFC-1918 private IPs and cloud IMDS (169.254.169.254)
    - ingest_url: caps download size at MAX_DOWNLOAD_BYTES (default 50 MB)
    - ingest_url: timeout enforced via httpx

Storage:
    - Bytes are written via StorageBackend.put_raw (content-addressed, WORM).
    - A raw_document artifact node is created in the registry.

Returns the raw_document Artifact ORM object.
"""

from __future__ import annotations

import contextlib
import ipaddress
import mimetypes
import socket
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlsplit, urlunsplit

import httpx
import structlog
from sqlalchemy.exc import IntegrityError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from knowledge_lake.config.settings import Settings, get_settings
from knowledge_lake.registry import repo as registry_repo
from knowledge_lake.registry.db import get_session
from knowledge_lake.storage.s3 import _UNCLASSIFIED_DOMAIN, StorageBackend

log = structlog.get_logger(__name__)

# Maximum download size — 50 MB cap (T-01-12, DoS protection)
MAX_DOWNLOAD_BYTES = 50 * 1024 * 1024

# HTTP timeout for URL fetches
FETCH_TIMEOUT_SECONDS = 30.0

# Maximum number of redirects to follow manually (SSRF redirect-hop cap)
_MAX_REDIRECTS = 10

# Notable private/reserved IP ranges blocked for SSRF prevention (T-01-11).
# Documentation only — the actual guard uses `not addr.is_global` (KL-07) so
# it also rejects the ranges a hand-rolled list tends to miss: 0.0.0.0/8
# ("this host", reaches localhost on Linux), 100.64.0.0/10 (CGNAT),
# 198.18.0.0/15 (benchmark), 192.0.0.0/24 (IETF protocol assignments),
# 240.0.0.0/4 (reserved), and IPv6 :: (unspecified).
_PRIVATE_NETS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),   # IPv4 link-local / cloud IMDS (AWS/GCP/Azure)
    ipaddress.ip_network("127.0.0.0/8"),       # IPv4 loopback
    ipaddress.ip_network("::1/128"),           # IPv6 loopback
    ipaddress.ip_network("fc00::/7"),          # IPv6 ULA
    ipaddress.ip_network("fe80::/10"),         # IPv6 link-local
]


# ── URL Normalization (D-06) ─────────────────────────────────────────────────


def normalize_url(url: str) -> str:
    """Conservative URL normalization per D-06.

    Transformations (stdlib only — no w3lib/courlan/url-normalize):
        - Lowercase scheme and host
        - Strip fragment (#...)
        - Strip trailing slash (but keep root "/")
        - Preserve explicit non-default port
        - Keep query string exactly as-is (NO reordering, NO tracking-param removal)

    This is idempotent: normalize_url(normalize_url(u)) == normalize_url(u).
    """
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    # netloc = host (lowered) + optional port (preserved)
    host = (parts.hostname or "").lower()
    port = parts.port
    netloc = f"{host}:{port}" if port else host
    path = parts.path
    # Strip trailing slash but keep root "/"
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    query = parts.query  # preserved verbatim
    fragment = ""  # always stripped
    return urlunsplit((scheme, netloc, path, query, fragment))


# ── Shared SSRF Guard (T-02-01) ─────────────────────────────────────────────


def validate_public_url(url: str) -> None:
    """Raise ValueError if the URL scheme is not https or resolves to a non-global IP.

    This is the shared SSRF guard consumed by every crawler and discovery plan
    (02-02..02-06). Renamed from _validate_url_scheme to be module-public.

    Blocks:
      - Non-https schemes (http URLs rejected by design — conservative SSRF posture)
      - Every non-globally-routable address, via `not addr.is_global` (KL-07).
        This covers RFC-1918 private ranges, link-local/cloud IMDS (169.254.x),
        loopback (127.x, ::1), IPv6 ULA (fc00::/7), and reserved ranges a
        hand-rolled blocklist tends to miss: 0.0.0.0/8 ("this host", reaches
        localhost on Linux), 100.64.0.0/10 (CGNAT), 198.18.0.0/15 (benchmark),
        192.0.0.0/24 (IETF protocol assignments), 240.0.0.0/4 (reserved), and
        the IPv6 unspecified address ::.
      - IPv4-mapped IPv6 addresses (::ffff:10.x.x.x etc.) — unwrapped before
        the is_global check so the IPv4 semantics apply.

    Uses getaddrinfo() rather than gethostbyname() to check ALL resolved addresses
    (both IPv4 and IPv6) — gethostbyname() only returns a single IPv4 address and
    does not detect IPv6-only hostnames or OS-dependent IPv6 behaviour (T-01-11).

    Known limitation, deliberately left alone (KL-07): this resolves the
    hostname once here; the HTTP client resolves it again on connect. A
    DNS-rebinding TOCTOU exists between the two resolutions. Pinning the
    validated IP (connect-by-IP with a Host header) would close it but is a
    separate change.
    """
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ValueError(
            f"ingest_url rejected URL with scheme {parsed.scheme!r}. "
            "Only https:// URLs are allowed (SSRF prevention, T-01-11). "
            "Use ingest_file() for local paths."
        )
    # Resolve ALL addresses (IPv4 + IPv6) and block every private/reserved range.
    hostname = parsed.hostname or ""
    try:
        infos = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError(
            f"Cannot resolve hostname {hostname!r}: {exc}"
        ) from exc
    if not infos:
        raise ValueError(f"No addresses resolved for hostname {hostname!r}")
    for (_family, _type, _proto, _canonname, sockaddr) in infos:
        raw_addr = sockaddr[0]
        addr = ipaddress.ip_address(raw_addr)
        # Unwrap IPv4-mapped IPv6 (e.g. ::ffff:10.0.0.1 → 10.0.0.1) so the
        # IPv4 private-range check below catches it (CR-01).
        if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
            addr = addr.ipv4_mapped
        # `is_global` is stdlib's authoritative classification of globally
        # routable addresses — it rejects every reserved/private/link-local
        # range, including ones a hand-rolled list misses (KL-07). See
        # _PRIVATE_NETS above for the documented notable ranges this covers.
        if not addr.is_global:
            raise ValueError(
                f"URL {url!r} resolves to private/reserved address {addr} — "
                "SSRF prevention blocks requests to non-global networks (T-01-11, KL-07)."
            )


# Keep backward compat alias for any existing internal callers
_validate_url_scheme = validate_public_url


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
    reraise=True,
)
def _fetch_with_retry(url: str) -> tuple[bytes, str]:
    """Fetch URL bytes with retry, timeout, size cap, and per-redirect-hop SSRF validation.

    Security (T-02-01b): httpx auto-redirect is DISABLED. Each 3xx redirect hop
    is followed manually: the Location header is resolved against the current URL,
    then validate_public_url() is called on the resolved target BEFORE issuing the
    next request. This closes the redirect-hop / DNS-rebinding SSRF gap where a
    public URL 302-redirects to 169.254.169.254 or an RFC-1918 host.

    The redirect chain is capped at _MAX_REDIRECTS to prevent infinite loops.

    Returns:
        Tuple of (body_bytes, content_type). The content_type is the MIME type
        extracted from the server's Content-Type response header (stripped of
        parameters like charset). Falls back to 'application/octet-stream' if
        the header is absent. (WR-08)
    """
    current_url = url
    with httpx.Client(timeout=FETCH_TIMEOUT_SECONDS, follow_redirects=False) as client:
        for _hop in range(_MAX_REDIRECTS + 1):
            resp = client.send(client.build_request("GET", current_url), stream=True)

            if resp.status_code in (301, 302, 303, 307, 308):
                resp.close()
                location = resp.headers.get("location")
                if not location:
                    raise ValueError(
                        f"Redirect from {current_url!r} has no Location header."
                    )
                # Resolve relative Location against current URL
                resolved = urljoin(current_url, location)
                # SSRF re-validation on the redirect target (T-02-01b)
                validate_public_url(resolved)
                current_url = resolved
                continue

            # Non-redirect response — read body with size cap.
            # Wrap in try/finally so the streaming response is always closed,
            # even when raise_for_status() raises on 4xx/5xx (WR-05).
            # An unclosed streaming response leaks an HTTP connection on every
            # failed attempt, multiplied by the tenacity retry count.
            try:
                resp.raise_for_status()
                content_type = resp.headers.get(
                    "content-type", "application/octet-stream"
                ).split(";")[0].strip()
                chunks: list[bytes] = []
                total = 0
                for chunk in resp.iter_bytes():
                    total += len(chunk)
                    if total > MAX_DOWNLOAD_BYTES:
                        raise ValueError(
                            f"Download from {url!r} exceeded size cap of "
                            f"{MAX_DOWNLOAD_BYTES // (1024 * 1024)} MB (T-01-12). "
                            "Increase MAX_DOWNLOAD_BYTES or reject oversized documents."
                        )
                    chunks.append(chunk)
            finally:
                # never mask the original exception (WR-03)
                with contextlib.suppress(Exception):
                    resp.close()
            return b"".join(chunks), content_type

        # Exceeded redirect cap
        raise ValueError(
            f"URL {url!r} exceeded maximum redirect chain of {_MAX_REDIRECTS} hops — "
            "possible redirect loop or too many hops."
        )


def register_source(
    url: str,
    name: str,
    *,
    domain: str | None = None,
    license_type: str = "unknown",
    source_type_override: str | None = None,
    tags: list[str] | None = None,
    organization: str | None = None,
    settings: Settings | None = None,
) -> dict:
    """Register a source URL with URL-first dedup (INGEST-01).

    Normalizes the URL, looks up get_source_by_normalized_url; if found,
    returns the existing source (no new row). Otherwise creates a new source
    with normalized_url set and domain stored in Source.config.

    Args:
        url:                  The source URL to register.
        name:                 Human-readable name for the source.
        domain:               Optional domain classification (stored in config).
        license_type:         SPDX license identifier.
        source_type_override: Override the default source_type ('web'). Used by
                              discover_sources to set 'discovered' (D-08).
        tags:                 Optional list of curated source tags (D-05).
                              Stored in Source.config["tags"] alongside domain.
        organization:         Optional organization name (D-05, D-06).
                              Stored in Source.config["organization"] if provided.
        settings:             Settings override.

    Returns:
        dict with source_id, name, url, normalized_url, domain, is_new.
    """
    norm_url = normalize_url(url)
    log.info("register_source.start", url=url, normalized_url=norm_url, name=name)

    with get_session() as session:
        existing = registry_repo.get_source_by_normalized_url(session, norm_url)
        if existing:
            log.info(
                "register_source.dedup_hit",
                source_id=existing.id,
                normalized_url=norm_url,
            )
            return {
                "source_id": existing.id,
                "name": existing.name,
                "url": existing.url,
                "normalized_url": existing.normalized_url,
                "domain": (existing.config or {}).get("domain"),
                "is_new": False,
            }

        # Build config dict from non-None values (D-05): domain, tags, organization.
        # Backward-compatible: callers without tags/organization produce identical behavior.
        # KL-15: domain is ALSO written to the first-class Source.domain column
        # below — config["domain"] is kept for one release as a transitional
        # dual-write so code still reading the blob directly does not break.
        config_dict: dict = {}
        if domain:
            config_dict["domain"] = domain
        if tags:
            config_dict["tags"] = tags
        if organization:
            config_dict["organization"] = organization
        config = config_dict if config_dict else None
        try:
            source = registry_repo.create_source(
                session,
                name=name,
                source_type=source_type_override or "web",
                url=url,
                normalized_url=norm_url,
                license_type=license_type,
                config=config,
                domain=domain,
            )
            session.flush()
        except IntegrityError:
            # Concurrent worker inserted the same normalized_url — roll back and
            # return the winner's row (WR-005, uq_sources_normalized_url).
            session.rollback()
            source = registry_repo.get_source_by_normalized_url(session, norm_url)
            if source is None:
                raise  # unexpected
            log.info(
                "register_source.dedup_hit_concurrent",
                source_id=source.id,
                normalized_url=norm_url,
            )
            return {
                "source_id": source.id,
                "name": source.name,
                "url": source.url,
                "normalized_url": source.normalized_url,
                "domain": (source.config or {}).get("domain"),
                "is_new": False,
            }
        result = {
            "source_id": source.id,
            "name": source.name,
            "url": source.url,
            "normalized_url": source.normalized_url,
            "domain": domain,
            "is_new": True,
        }

    log.info("register_source.complete", **result)
    return result


def ingest_url(
    url: str,
    source_name: str,
    *,
    mime_type: str | None = None,
    license_type: str = "unknown",
    robots_checked: bool = False,
    settings: Settings | None = None,
) -> dict:
    """Download a URL and ingest as a raw_document artifact.

    Implements URL-first dedup (D-05): normalizes the URL and checks
    sources.normalized_url. If the URL was already ingested, returns the
    existing source_id + artifact_id without re-fetching (D-07 silent success).

    Security:
        - Validates scheme is https (raises ValueError otherwise).
        - Blocks RFC-1918 private IPs and cloud IMDS addresses.
        - Caps download at 50 MB.
        - Tenacity retry (3 attempts, exponential back-off).

    Args:
        url:            https:// URL to fetch.
        source_name:    Human-readable name for the source registry entry.
        mime_type:      MIME type override. If None (default), the MIME type is
                        taken from the server's Content-Type response header. (WR-08)
        license_type:   License type of the source (default: "unknown" — caller must supply).
        robots_checked: Set to True only after actually checking robots.txt (Phase 2).
                        Default False = robots.txt not yet checked.
        settings:       Settings override (uses get_settings() if None).

    Returns:
        dict with source_id, artifact_id, storage_uri, content_hash, mime_type.

    Raises:
        ValueError: If URL scheme is not https or resolves to a private IP.
        httpx.HTTPStatusError: If the server returns a non-2xx response.
        ValueError: If the download exceeds MAX_DOWNLOAD_BYTES.
    """
    validate_public_url(url)
    s = settings or get_settings()
    storage = StorageBackend(s.storage)

    log.info("ingest_url.start", url=url, source_name=source_name)

    # URL-first dedup (D-05): check if we already have this normalized URL
    norm_url = normalize_url(url)
    with get_session() as session:
        existing_source = registry_repo.get_source_by_normalized_url(session, norm_url)
        if existing_source:
            existing_artifact = registry_repo.get_raw_artifact_for_source(
                session, existing_source.id
            )
            if existing_artifact:
                stored_mime = existing_artifact.mime_type
                if not stored_mime or stored_mime == "application/octet-stream":
                    stored_mime = _detect_mime_from_uri(existing_artifact.storage_uri)
                result = {
                    "source_id": existing_source.id,
                    "artifact_id": existing_artifact.id,
                    "storage_uri": existing_artifact.storage_uri,
                    "content_hash": existing_artifact.content_hash,
                    "mime_type": stored_mime,
                }
                log.info("ingest_url.dedup_hit", **result)
                return result

    # No dedup hit — proceed with fetch
    data, server_content_type = _fetch_with_retry(url)
    # Use caller-supplied MIME type if provided, otherwise trust the server (WR-08)
    effective_mime = mime_type or server_content_type
    ext = _mime_to_ext(effective_mime)
    log.info("ingest_url.downloaded", url=url, size=len(data), mime_type=effective_mime)

    with get_session() as session:
        try:
            source = registry_repo.create_source(
                session,
                name=source_name,
                source_type="web",
                url=url,
                normalized_url=norm_url,
                license_type=license_type,
                robots_checked=robots_checked,
            )
            session.flush()
        except IntegrityError:
            # Concurrent worker inserted the same normalized_url — roll back and
            # reuse the winner's source row (WR-005, uq_sources_normalized_url).
            session.rollback()
            source = registry_repo.get_source_by_normalized_url(session, norm_url)
            if source is None:
                raise  # unexpected
        domain = (source.config or {}).get("domain") or _UNCLASSIFIED_DOMAIN
        artifact = storage.put_raw(
            source.id, data, ext, session,
            mime_type=effective_mime,
            domain=domain,
            tags={"domain": domain, "source_name": source_name, "format": ext, "artifact_type": "raw_document"},
        )
        session.flush()
        result = {
            "source_id": source.id,
            "artifact_id": artifact.id,
            "storage_uri": artifact.storage_uri,
            "content_hash": artifact.content_hash,
            "mime_type": effective_mime,
        }

    log.info("ingest_url.complete", **result)
    return result


def ingest_file(
    path: Path | str,
    source_name: str,
    *,
    mime_type: str = "application/pdf",
    source_url: str | None = None,
    license_type: str = "unknown",
    settings: Settings | None = None,
) -> dict:
    """Load a local file and ingest as a raw_document artifact.

    Implements hash-second dedup (D-07): computes SHA256 of the file and checks
    get_artifact_by_hash. If an identical raw artifact already exists, returns
    the existing IDs without creating a new source row.

    Used for hermetic fixture testing (D-05) and for the demo fallback when
    egress is blocked.

    Args:
        path:         Path to the local file (str or Path).
        source_name:  Human-readable name for the source registry entry.
        mime_type:    MIME type override (inferred from suffix if not given).
        source_url:   Optional canonical URL to record in the source registry.
        license_type: License type of the source (default: "unknown" — caller must supply).
        settings:     Settings override.

    Returns:
        dict with source_id, artifact_id, storage_uri, content_hash.
    """
    import hashlib as _hashlib

    fpath = Path(path)
    if not fpath.exists():
        raise FileNotFoundError(f"ingest_file: path does not exist: {fpath}")

    # Infer MIME from suffix if not specified
    inferred_mime, _ = mimetypes.guess_type(str(fpath))
    effective_mime = inferred_mime or mime_type

    s = settings or get_settings()
    storage = StorageBackend(s.storage)
    ext = _mime_to_ext(effective_mime)

    log.info("ingest_file.start", path=str(fpath), source_name=source_name)
    data = fpath.read_bytes()
    log.info("ingest_file.loaded", path=str(fpath), size=len(data))

    # Hash-second dedup (D-07): check if identical content already exists
    content_hash = _hashlib.sha256(data).hexdigest()
    with get_session() as session:
        existing_artifact = registry_repo.get_artifact_by_hash(
            session, content_hash, "raw_document"
        )
        if existing_artifact:
            result = {
                "source_id": existing_artifact.source_id,
                "artifact_id": existing_artifact.id,
                "storage_uri": existing_artifact.storage_uri,
                "content_hash": existing_artifact.content_hash,
            }
            log.info("ingest_file.dedup_hit", **result)
            return result

    # URL-first dedup (WR-004): if source_url is provided, check for an
    # existing source with the same normalized URL before creating a new one.
    # Without this check, repeated calls with the same source_url would attempt
    # to INSERT duplicate source rows, raising IntegrityError from the
    # uq_sources_normalized_url constraint added in migration 0005.
    norm_url = normalize_url(source_url) if source_url else None
    with get_session() as session:
        if norm_url:
            existing_source = registry_repo.get_source_by_normalized_url(session, norm_url)
        else:
            existing_source = None

        if existing_source is not None:
            source = existing_source
            log.info("ingest_file.source_url_dedup_hit", source_id=source.id, norm_url=norm_url)
        else:
            source = registry_repo.create_source(
                session,
                name=source_name,
                source_type="upload",
                url=source_url or str(fpath),
                normalized_url=norm_url,
                license_type=license_type,
                robots_checked=False,  # local uploads don't need robots.txt check
            )
        session.flush()
        domain = (source.config or {}).get("domain") or _UNCLASSIFIED_DOMAIN
        artifact = storage.put_raw(
            source.id, data, ext, session,
            mime_type=effective_mime,
            domain=domain,
            tags={"domain": domain, "source_name": source_name, "format": ext, "artifact_type": "raw_document"},
        )
        session.flush()
        result = {
            "source_id": source.id,
            "artifact_id": artifact.id,
            "storage_uri": artifact.storage_uri,
            "content_hash": artifact.content_hash,
        }

    log.info("ingest_file.complete", **result)
    return result


def _mime_to_ext(mime_type: str) -> str:
    """Map a MIME type to a file extension (without leading dot)."""
    _MAP = {
        "application/pdf": "pdf",
        "text/html": "html",
        "text/plain": "txt",
        "text/markdown": "md",
        "application/json": "json",
        "application/xml": "xml",
        "text/xml": "xml",
    }
    return _MAP.get(mime_type, "bin")


_EXT_TO_MIME = {
    "html": "text/html",
    "htm": "text/html",
    "pdf": "application/pdf",
    "txt": "text/plain",
    "md": "text/markdown",
    "json": "application/json",
    "xml": "application/xml",
    "csv": "text/csv",
}


def _detect_mime_from_uri(storage_uri: str) -> str:
    """Detect MIME type from the file extension in a storage URI."""
    ext = storage_uri.rsplit(".", 1)[-1].lower() if "." in storage_uri else ""
    return _EXT_TO_MIME.get(ext, "application/octet-stream")
