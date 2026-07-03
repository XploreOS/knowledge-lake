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

import ipaddress
import mimetypes
import socket
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import httpx
import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

from knowledge_lake.config.settings import Settings, get_settings
from knowledge_lake.registry.db import get_session
from knowledge_lake.registry import repo as registry_repo
from knowledge_lake.storage.s3 import StorageBackend

log = structlog.get_logger(__name__)

# Maximum download size — 50 MB cap (T-01-12, DoS protection)
MAX_DOWNLOAD_BYTES = 50 * 1024 * 1024

# HTTP timeout for URL fetches
FETCH_TIMEOUT_SECONDS = 30.0

# Private/reserved IP ranges blocked for SSRF prevention (T-01-11)
_PRIVATE_NETS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),   # link-local / cloud IMDS (AWS/GCP/Azure)
    ipaddress.ip_network("127.0.0.0/8"),       # loopback
    ipaddress.ip_network("::1/128"),           # IPv6 loopback
    ipaddress.ip_network("fc00::/7"),          # IPv6 ULA
]


def _validate_url_scheme(url: str) -> None:
    """Raise ValueError if the URL scheme is not https or resolves to a private IP (SSRF guard, T-01-11).

    Blocks:
      - Non-https schemes
      - RFC-1918 private IP ranges (10.x, 172.16-31.x, 192.168.x)
      - Link-local/cloud IMDS (169.254.x — AWS/GCP/Azure metadata service)
      - Loopback (127.x, ::1)
      - IPv6 ULA (fc00::/7)
    """
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ValueError(
            f"ingest_url rejected URL with scheme {parsed.scheme!r}. "
            "Only https:// URLs are allowed (SSRF prevention, T-01-11). "
            "Use ingest_file() for local paths."
        )
    # Resolve hostname and block private/reserved ranges
    hostname = parsed.hostname or ""
    try:
        addr = ipaddress.ip_address(socket.gethostbyname(hostname))
    except Exception as exc:
        raise ValueError(
            f"Cannot resolve hostname {hostname!r}: {exc}"
        ) from exc
    for net in _PRIVATE_NETS:
        if addr in net:
            raise ValueError(
                f"URL {url!r} resolves to private/link-local address {addr} — "
                "SSRF prevention blocks requests to private networks (T-01-11)."
            )


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    reraise=True,
)
def _fetch_with_retry(url: str) -> bytes:
    """Fetch URL bytes with retry, timeout, and size cap enforcement."""
    with httpx.stream("GET", url, timeout=FETCH_TIMEOUT_SECONDS, follow_redirects=True) as resp:
        resp.raise_for_status()
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
        return b"".join(chunks)


def ingest_url(
    url: str,
    source_name: str,
    *,
    mime_type: str = "application/pdf",
    license_type: str = "unknown",
    robots_checked: bool = False,
    settings: Optional[Settings] = None,
) -> dict:
    """Download a URL and ingest as a raw_document artifact.

    Security:
        - Validates scheme is https (raises ValueError otherwise).
        - Blocks RFC-1918 private IPs and cloud IMDS addresses.
        - Caps download at 50 MB.
        - Tenacity retry (3 attempts, exponential back-off).

    Args:
        url:            https:// URL to fetch.
        source_name:    Human-readable name for the source registry entry.
        mime_type:      MIME type of the document (default: application/pdf).
        license_type:   License type of the source (default: "unknown" — caller must supply).
        robots_checked: Set to True only after actually checking robots.txt (Phase 2).
                        Default False = robots.txt not yet checked.
        settings:       Settings override (uses get_settings() if None).

    Returns:
        dict with source_id, artifact_id, storage_uri, content_hash.

    Raises:
        ValueError: If URL scheme is not https or resolves to a private IP.
        httpx.HTTPStatusError: If the server returns a non-2xx response.
        ValueError: If the download exceeds MAX_DOWNLOAD_BYTES.
    """
    _validate_url_scheme(url)
    s = settings or get_settings()
    storage = StorageBackend(s.storage)
    ext = _mime_to_ext(mime_type)

    log.info("ingest_url.start", url=url, source_name=source_name)
    data = _fetch_with_retry(url)
    log.info("ingest_url.downloaded", url=url, size=len(data))

    with get_session() as session:
        source = registry_repo.create_source(
            session,
            name=source_name,
            source_type="web",
            url=url,
            license_type=license_type,
            robots_checked=robots_checked,
        )
        session.flush()
        artifact = storage.put_raw(source.id, data, ext, session)
        session.flush()
        result = {
            "source_id": source.id,
            "artifact_id": artifact.id,
            "storage_uri": artifact.storage_uri,
            "content_hash": artifact.content_hash,
        }

    log.info("ingest_url.complete", **result)
    return result


def ingest_file(
    path: "Path | str",
    source_name: str,
    *,
    mime_type: str = "application/pdf",
    source_url: Optional[str] = None,
    license_type: str = "unknown",
    settings: Optional[Settings] = None,
) -> dict:
    """Load a local file and ingest as a raw_document artifact.

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

    with get_session() as session:
        source = registry_repo.create_source(
            session,
            name=source_name,
            source_type="upload",
            url=source_url or str(fpath),
            license_type=license_type,
            robots_checked=False,  # local uploads don't need robots.txt check
        )
        session.flush()
        artifact = storage.put_raw(source.id, data, ext, session)
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
        "application/json": "json",
    }
    return _MAP.get(mime_type, "bin")
