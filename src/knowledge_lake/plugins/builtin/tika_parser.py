"""Optional Tika-backed last-resort ParserPlugin for Knowledge Lake (PARSE-02).

Tika is format-agnostic and handles virtually any document type, but requires
a running Tika server (Docker: apache/tika). Uses lazy imports so deployments
without tika installed skip this parser gracefully (Pitfall 5).

Registered as entry point:
    [project.entry-points."knowledge_lake.parsers"]
    tika = "knowledge_lake.plugins.builtin.tika_parser:TikaParser"
"""

from __future__ import annotations

import structlog

from knowledge_lake.plugins.protocols import ParsedDoc, Section

log = structlog.get_logger(__name__)

# 100 MiB hard limit (T-03-02)
_MAX_FILE_BYTES = 104857600


class TikaParser:
    """Optional last-resort parser backed by Apache Tika (PARSE-02).

    Tika is format-agnostic: can_parse() returns True for any MIME type when the
    tika Python client is installed. Falls back gracefully (returns False) when
    tika is absent.

    Requires a running Tika server. If the server is unavailable or returns
    no content, raises RuntimeError to trigger D-01 chain continuation.

    The server URL is injected via constructor so it is configurable through
    ``settings.tika_server_url`` without modifying source code (WR-03).

    Usage:
        parser = TikaParser()  # uses default http://localhost:9998
        parser = TikaParser(tika_server_url=settings.tika_server_url)
        if parser.can_parse("application/pdf"):
            doc = parser.parse(pdf_bytes, "application/pdf")
    """

    def __init__(self, tika_server_url: str = "http://localhost:9998") -> None:
        self._endpoint = tika_server_url

    def can_parse(self, mime_type: str) -> bool:
        """Return True for any MIME type when the tika package is installed.

        Returns False (with a debug warning) if tika is not installed.
        """
        try:
            import tika  # noqa: F401 — lazy availability check
        except ImportError:
            log.debug(
                "tika_parser.not_installed",
                detail="tika package not available; skipping in fallback chain",
            )
            return False
        # Tika is format-agnostic — it handles any binary document
        return True

    def parse(self, raw: bytes, mime_type: str) -> ParsedDoc:
        """Parse raw bytes using Apache Tika server.

        Args:
            raw:       Raw document bytes.
            mime_type: MIME type hint passed to Tika (informational).

        Returns:
            ParsedDoc with extracted text as a single section.

        Raises:
            ValueError:   If the file exceeds the 100 MiB limit (T-03-02).
            RuntimeError: If tika is not installed, server is unavailable,
                          or no content is extracted — allows D-01 fallback.
        """
        if len(raw) > _MAX_FILE_BYTES:
            raise ValueError(
                f"TikaParser: file exceeds 100 MiB size limit "
                f"({len(raw)} bytes > {_MAX_FILE_BYTES} bytes)"
            )

        try:
            from tika import parser as tika_parser  # type: ignore[import-untyped]
        except ImportError as exc:
            raise RuntimeError(
                f"TikaParser: tika package not available: {exc}"
            ) from exc

        try:
            result = tika_parser.from_buffer(raw, serverEndpoint=self._endpoint)
        except Exception as exc:
            raise RuntimeError(
                f"TikaParser: Tika server call failed for mime_type={mime_type!r}: {exc}"
            ) from exc

        if not isinstance(result, dict) or not result.get("content"):
            raise RuntimeError(
                "TikaParser returned no content — server may be unavailable "
                f"at {self._endpoint}"
            )

        full_text = (result["content"] or "").strip()
        section = Section(
            heading="Document",
            section_path="§1",
            page=1,
            text=full_text,
        )
        return ParsedDoc(
            text=full_text,
            sections=[section],
            metadata={"format": mime_type, "source": "tika_parser"},
        )
