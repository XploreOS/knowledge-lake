"""Shared utilities for Knowledge Lake pipeline stages.

Functions here are small, dependency-free helpers shared across pipeline
modules (parse.py, clean.py, api/app.py, cli/app.py) to avoid duplication
without introducing circular imports.
"""

from __future__ import annotations


def uri_to_key(uri: str) -> str:
    """Extract the S3 object key from an ``s3://bucket/key`` URI.

    Raises :class:`ValueError` for URIs that do not start with ``s3://``
    or whose path component is empty — surfaces misconfigured storage_uri
    values early with a descriptive error.

    Args:
        uri: An S3 URI in the form ``s3://bucket/path/to/object``.

    Returns:
        The object key portion (everything after the bucket name), e.g.
        ``"silver/src_abc/abc123.md"``.

    Raises:
        ValueError: If the URI does not start with ``s3://`` or the key
                    portion is absent.
    """
    if not uri.startswith("s3://"):
        raise ValueError(f"Expected s3:// URI, got: {uri!r}")
    parts = uri.split("/", 3)
    if len(parts) < 4 or not parts[3]:
        raise ValueError(f"Cannot extract key from URI: {uri!r}")
    return parts[3]
