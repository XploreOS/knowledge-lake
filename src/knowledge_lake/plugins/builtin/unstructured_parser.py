"""Optional Unstructured-backed fallback ParserPlugin for Knowledge Lake (PARSE-02).

Covers all eight required MIME types as a second-tier fallback when DoclingParser
or JsonXmlParser fail or produce low-quality output. Uses lazy imports so the
fallback chain degrades gracefully when unstructured is not installed (Pitfall 5).

Registered as entry point:
    [project.entry-points."knowledge_lake.parsers"]
    unstructured = "knowledge_lake.plugins.builtin.unstructured_parser:UnstructuredParser"
"""

from __future__ import annotations

import io

import structlog

from knowledge_lake.plugins.protocols import ParsedDoc, Section

log = structlog.get_logger(__name__)

# Covers all eight required formats — unstructured is a format-agnostic fallback
_SUPPORTED_MIME_TYPES = frozenset({
    "application/pdf",
    "text/html",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/markdown",
    "text/csv",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/json",
    "application/xml",
    "text/xml",
})

# 100 MiB hard limit (T-03-02)
_MAX_FILE_BYTES = 104857600


class UnstructuredParser:
    """Optional fallback parser backed by unstructured (PARSE-02).

    Uses lazy imports so deployments without unstructured installed still work —
    can_parse() returns False when unstructured is absent, and the fallback chain
    skips this parser gracefully (D-01, Pitfall 5).

    Usage:
        parser = UnstructuredParser()
        if parser.can_parse("application/pdf"):
            doc = parser.parse(pdf_bytes, "application/pdf")
    """

    def can_parse(self, mime_type: str) -> bool:
        """Return True if unstructured is installed and the MIME type is supported.

        Returns False (with a debug warning) if unstructured is not installed.
        """
        try:
            import unstructured  # noqa: F401 — lazy availability check
        except ImportError:
            log.debug(
                "unstructured_parser.not_installed",
                detail="unstructured package not available; skipping in fallback chain",
            )
            return False
        return mime_type in _SUPPORTED_MIME_TYPES

    def parse(self, raw: bytes, mime_type: str) -> ParsedDoc:
        """Parse raw bytes using unstructured.partition.auto.

        Args:
            raw:       Raw document bytes.
            mime_type: MIME type of the document.

        Returns:
            ParsedDoc with full text and sections derived from Title/NarrativeText elements.

        Raises:
            ValueError:   If the file exceeds the 100 MiB limit (T-03-02).
            RuntimeError: On import error or partition failure — allows D-01 fallback.
        """
        if len(raw) > _MAX_FILE_BYTES:
            raise ValueError(
                f"UnstructuredParser: file exceeds 100 MiB size limit "
                f"({len(raw)} bytes > {_MAX_FILE_BYTES} bytes)"
            )

        try:
            from unstructured.partition.auto import partition  # type: ignore[import-untyped]
        except ImportError as exc:
            raise RuntimeError(
                f"UnstructuredParser: unstructured package not available: {exc}"
            ) from exc

        try:
            elements = partition(file=io.BytesIO(raw), content_type=mime_type)
        except Exception as exc:
            raise RuntimeError(
                f"UnstructuredParser: partition() failed for mime_type={mime_type!r}: {exc}"
            ) from exc

        # Concatenate all element text with paragraph spacing
        full_text = "\n\n".join(
            el.text for el in elements if hasattr(el, "text") and el.text
        )

        # Build sections from Title and NarrativeText elements
        sections: list[Section] = []
        section_number = 0
        current_heading = ""
        current_path = ""
        current_text_parts: list[str] = []

        def _flush() -> None:
            nonlocal current_text_parts
            if current_heading:
                sections.append(
                    Section(
                        heading=current_heading,
                        section_path=current_path,
                        page=1,
                        text="\n".join(current_text_parts).strip(),
                    )
                )
            current_text_parts = []

        for el in elements:
            category = getattr(el, "category", "") or ""
            text = (el.text or "").strip() if hasattr(el, "text") else ""
            if not text:
                continue
            if category == "Title":
                _flush()
                section_number += 1
                current_heading = text
                current_path = f"§{section_number}"
                current_text_parts = []
            elif category in ("NarrativeText", "Text", "ListItem"):
                current_text_parts.append(text)

        _flush()

        if not sections and full_text:
            sections = [Section(heading="Document", section_path="§1", page=1, text=full_text)]

        return ParsedDoc(
            text=full_text,
            sections=sections,
            metadata={"format": mime_type, "source": "unstructured_parser"},
        )
