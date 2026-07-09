"""Wave 0 xfail stubs for INGEST-10: linked-document ingestion from crawled HTML pages.

All tests are marked xfail(strict=False) — they will be implemented in Plan 3
when _extract_linked_docs, MAX_LINKED_DOCS_PER_PAGE, and SSRF handling are
added to knowledge_lake.pipeline.crawl.
"""

from __future__ import annotations

import pytest

# Guard imports so collection does not fail before Plan 3 adds these symbols.
try:
    from knowledge_lake.pipeline.crawl import (  # noqa: F401
        MAX_LINKED_DOCS_PER_PAGE,
        _extract_linked_docs,
    )
except ImportError:
    MAX_LINKED_DOCS_PER_PAGE = None  # type: ignore[assignment]
    _extract_linked_docs = None  # type: ignore[assignment]


def test_extract_linked_docs_pdf_only():
    """_extract_linked_docs with href to .pdf and .html returns only the .pdf link."""
    from knowledge_lake.pipeline.crawl import _extract_linked_docs as _eld

    html = (
        '<a href="/guide.pdf">PDF Guide</a>'
        '<a href="/other.html">HTML Page</a>'
    )
    base_url = "http://example.com"
    result = _eld(html, base_url)
    assert len(result) == 1
    assert result[0].endswith(".pdf")


def test_extract_linked_docs_docx():
    """href to .docx is also returned by _extract_linked_docs."""
    from knowledge_lake.pipeline.crawl import _extract_linked_docs as _eld

    html = (
        '<a href="/report.docx">DOCX Report</a>'
        '<a href="/other.html">HTML Page</a>'
    )
    base_url = "http://example.com"
    result = _eld(html, base_url)
    assert len(result) == 1
    assert result[0].endswith(".docx")


def test_max_linked_docs_cap():
    """When HTML has more than MAX_LINKED_DOCS_PER_PAGE pdf links, only
    MAX_LINKED_DOCS_PER_PAGE are returned.
    """
    from knowledge_lake.pipeline.crawl import MAX_LINKED_DOCS_PER_PAGE as cap
    from knowledge_lake.pipeline.crawl import _extract_linked_docs as _eld

    # Build HTML with cap + 5 pdf links
    links = "".join(
        f'<a href="/doc{i}.pdf">Doc {i}</a>' for i in range(cap + 5)
    )
    result = _eld(links, "http://example.com")
    assert len(result) <= cap


@pytest.mark.xfail(strict=False, reason="Phase 8 INGEST-10 — not yet implemented")
def test_ssrf_blocked_link_counted_as_failed():
    """When validate_public_url raises ValueError for a linked URL,
    linked_docs_failed is incremented and the parent crawl continues.
    """
    from unittest.mock import patch

    from knowledge_lake.pipeline.crawl import _extract_linked_docs as _eld

    html = '<a href="http://169.254.169.254/metadata/doc.pdf">SSRF doc</a>'
    base_url = "http://example.com"

    # Patch validate_public_url to raise for SSRF addresses.
    def _mock_validate(url: str) -> None:
        if "169.254" in url:
            raise ValueError(f"SSRF blocked: {url}")

    with patch("knowledge_lake.pipeline.crawl.validate_public_url", side_effect=_mock_validate):
        # The function should not raise; SSRF-blocked links are silently excluded
        # (or a separate linked_docs_failed counter is incremented by the caller).
        result = _eld(html, base_url)

    # SSRF-blocked link must not appear in the returned list
    assert not any("169.254" in link for link in result)
