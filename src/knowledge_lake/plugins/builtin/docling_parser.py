"""Docling-backed ParserPlugin for Knowledge Lake (D-11).

Wraps Docling 2.108 to parse multiple document formats into a ParsedDoc,
preserving headings, section paths, and page references for downstream
citations (D-07).

Phase 3 multi-format support (PARSE-01): PDF, HTML, DOCX, Markdown, CSV, XLSX.
JSON and XML are handled by JsonXmlParser (stdlib-only, no heavy deps).

Security: 100 MiB file-size guard before writing to temp dir (T-03-02).
Temp directory pattern ensures cleanup on SIGKILL (T-03-03, CR-08).

Registered as entry point:
    [project.entry-points."knowledge_lake.parsers"]
    docling = "knowledge_lake.plugins.builtin.docling_parser:DoclingParser"
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import structlog

from knowledge_lake.plugins.protocols import ParsedDoc, ParserPlugin, Section

log = structlog.get_logger(__name__)

# All MIME types natively supported by Docling 2.108 (Phase 3, PARSE-01)
_SUPPORTED_MIME_TYPES = frozenset({
    "application/pdf",
    "text/html",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",  # DOCX
    "text/markdown",
    "text/csv",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",  # XLSX
})

# 100 MiB hard limit before parsing — DoS guard (T-03-02)
_MAX_FILE_BYTES = 104857600


class DoclingParser:
    """ParserPlugin implementation backed by Docling 2.108.

    Supports six Docling-native formats: PDF, HTML, DOCX, Markdown, CSV, XLSX
    (PARSE-01). JSON and XML are out of scope for this parser; use JsonXmlParser.

    Parses raw bytes into a ParsedDoc with structured sections, section paths,
    and page references. Section metadata enables downstream citation rendering
    (D-07): 'Document X, §Y Administrative Safeguards, page Z'.

    Usage:
        parser = DoclingParser()
        if parser.can_parse("text/html"):
            doc = parser.parse(html_bytes, "text/html")
            print(doc.text[:200])
    """

    def can_parse(self, mime_type: str) -> bool:
        """Return True for the six Docling-native MIME types.

        Supported: application/pdf, text/html, DOCX, text/markdown, text/csv, XLSX.
        JSON and XML are NOT supported here — use JsonXmlParser for those.
        """
        return mime_type in _SUPPORTED_MIME_TYPES

    def parse(self, raw: bytes, mime_type: str) -> ParsedDoc:
        """Parse raw bytes into a ParsedDoc using Docling.

        Writes bytes to a temporary file (Docling requires a file path), calls
        DocumentConverter.convert(), then walks the DoclingDocument structure to
        extract headings, section paths, page references, and full text.

        Args:
            raw:       Raw document bytes (PDF, HTML, DOCX, Markdown, CSV, or XLSX).
            mime_type: MIME type. Must be one of the six supported Docling-native types.

        Returns:
            ParsedDoc with full markdown text and per-section Section objects.

        Raises:
            ValueError: If mime_type is not supported by this parser.
            ValueError: If the file exceeds the 100 MiB size limit (T-03-02).
        """
        if not self.can_parse(mime_type):
            raise ValueError(
                f"DoclingParser does not support mime_type {mime_type!r}. "
                f"Supported: {sorted(_SUPPORTED_MIME_TYPES)}"
            )

        # DoS guard: reject oversized files before any temp-file write (T-03-02)
        if len(raw) > _MAX_FILE_BYTES:
            raise ValueError(
                f"DoclingParser: file exceeds 100 MiB size limit "
                f"({len(raw)} bytes > {_MAX_FILE_BYTES} bytes)"
            )

        log.info("docling_parser.parse_start", mime_type=mime_type, size=len(raw))

        # Docling requires a file path — write to a temp directory so cleanup
        # is guaranteed even on SIGKILL (TemporaryDirectory uses shutil.rmtree
        # at context-manager exit rather than relying on a finalizer). (CR-08, T-03-03)
        # The suffix comes from a whitelist map — never constructed from user input (T-03-03).
        suffix = _mime_to_suffix(mime_type)
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir) / f"doc{suffix}"
            tmp_path.write_bytes(raw)
            return self._convert_file(tmp_path, mime_type)
        # Directory and all contents are removed at context exit, even on exception

    def _convert_file(self, path: Path, mime_type: str = "application/pdf") -> ParsedDoc:
        """Run Docling on *path* and assemble a ParsedDoc.

        PDF path: uses PdfPipelineOptions(do_ocr=False, do_table_structure=False)
        to avoid the RapidOCR/omegaconf PosixPath issue on Linux (Phase 1 legacy).

        Non-PDF path: uses plain DocumentConverter() with no format_options —
        Docling auto-detects format from file suffix for HTML/DOCX/MD/CSV/XLSX.
        """
        if mime_type == "application/pdf":
            from docling.document_converter import DocumentConverter, PdfFormatOption
            from docling.datamodel.pipeline_options import PdfPipelineOptions

            pipeline_options = PdfPipelineOptions(do_ocr=False, do_table_structure=False)
            converter = DocumentConverter(
                format_options={"pdf": PdfFormatOption(pipeline_options=pipeline_options)}
            )
        else:
            from docling.document_converter import DocumentConverter

            # Docling auto-detects format from file extension for non-PDF types.
            # No format_options needed — default converter handles HTML/DOCX/MD/CSV/XLSX.
            converter = DocumentConverter()

        result = converter.convert(str(path))
        doc = result.document

        # Export full text as markdown (preserves reading order + headings)
        full_text: str = doc.export_to_markdown()

        # Build Section list from DoclingDocument's element tree
        sections: list[Section] = _extract_sections(doc)

        metadata: dict = {
            "page_count": _get_page_count(doc),
            "source_path": str(path),
        }

        log.info(
            "docling_parser.parse_complete",
            mime_type=mime_type,
            pages=metadata["page_count"],
            sections=len(sections),
            text_len=len(full_text),
        )
        return ParsedDoc(text=full_text, sections=sections, metadata=metadata)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mime_to_suffix(mime_type: str) -> str:
    """Map a MIME type to the file suffix Docling needs for format detection.

    All values come from a whitelist — never constructed from user input (T-03-03).
    """
    return {
        "application/pdf": ".pdf",
        "text/html": ".html",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
        "text/markdown": ".md",
        "text/csv": ".csv",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    }.get(mime_type, ".bin")


def _get_page_count(doc: object) -> int:
    """Return the number of pages in a DoclingDocument, or 0 if unavailable."""
    try:
        # DoclingDocument exposes .pages as a dict or list
        pages = getattr(doc, "pages", None)
        if pages is not None:
            return len(pages)
    except Exception:
        pass
    return 0


def _extract_sections(doc: object) -> list[Section]:
    """Walk DoclingDocument body and extract Section metadata.

    Each section is anchored at a heading element. We accumulate text under
    each heading until the next heading of equal or lesser level.

    Returns a list of Sections ordered by appearance in the document.
    """
    sections: list[Section] = []
    try:
        # DoclingDocument has a .body with .children that are DocItem elements
        # Each has a .label (DocItemLabel.SECTION_HEADER, .TEXT, etc.)
        # and .prov list for page provenance
        from docling_core.types.doc.labels import DocItemLabel  # type: ignore[import-untyped]

        current_heading: str = ""
        current_path: str = ""
        current_page: int = 1
        current_text_parts: list[str] = []
        section_number = 0

        def _flush_section() -> None:
            nonlocal current_text_parts
            if current_heading:
                sections.append(
                    Section(
                        heading=current_heading,
                        section_path=current_path,
                        page=current_page,
                        text="\n".join(current_text_parts).strip(),
                    )
                )
            current_text_parts = []

        for item, _ in doc.iterate_items():  # type: ignore[union-attr]
            label = getattr(item, "label", None)
            text = getattr(item, "text", "")
            page = _item_page(item)

            if label in (
                DocItemLabel.SECTION_HEADER,
                DocItemLabel.TITLE,
            ):
                _flush_section()
                section_number += 1
                current_heading = text
                current_path = f"§{section_number}"
                current_page = page
                current_text_parts = []
            elif label == DocItemLabel.TEXT and text:
                current_text_parts.append(text)

        _flush_section()  # flush last section

    except Exception as exc:
        log.warning(
            "docling_parser.section_extraction_failed",
            error=str(exc),
            exc_info=True,
        )
        # Fall back to single-section document
        if not sections:
            sections = [
                Section(
                    heading="Document",
                    section_path="§1",
                    page=1,
                    text="",
                )
            ]

    return sections


def _item_page(item: object) -> int:
    """Extract page number from a DocItem's provenance list."""
    try:
        prov = getattr(item, "prov", None)
        if prov:
            first = prov[0]
            page_no = getattr(first, "page_no", None)
            if page_no is not None:
                return int(page_no)
    except Exception:
        pass
    return 1
