"""Tests for domain propagation through discover/crawl (Finding 2).

discover_sources and crawl_source accept an optional ``domain`` and forward it
into register_source so discovered/crawled sources land under {domain}/ instead
of _unclassified/. None stays backward-compatible.

register_source is patched with a MagicMock so these tests assert only the
plumbing contract (domain forwarded), not the registry write itself — which is
already covered by ingest/register_source tests.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from knowledge_lake.config.settings import Settings
from knowledge_lake.plugins.protocols import DiscoveryResult


def _settings() -> Settings:
    return Settings(_env_file=None)  # type: ignore[call-arg]


def test_discover_forwards_domain_to_register_source() -> None:
    """discover_sources(domain='healthcare') forwards domain='healthcare'."""
    import knowledge_lake.pipeline.discover as discover_module

    stub_plugin = MagicMock()
    stub_plugin.name = "stub"
    stub_plugin.search.return_value = [
        DiscoveryResult(url="https://example.com/a", title="A")
    ]
    mock_register = MagicMock(
        return_value={"source_id": "src_1", "is_new": True}
    )

    with (
        patch.object(discover_module, "get_discovery", lambda _s: stub_plugin),
        patch.object(discover_module, "validate_public_url", lambda _u: None),
        patch.object(discover_module, "register_source", mock_register),
    ):
        discover_module.discover_sources(
            "healthcare query", domain="healthcare", settings=_settings()
        )

    assert mock_register.call_count == 1
    assert mock_register.call_args.kwargs["domain"] == "healthcare"


def test_discover_none_domain_is_backward_compatible() -> None:
    """discover_sources with no domain forwards domain=None (stays _unclassified)."""
    import knowledge_lake.pipeline.discover as discover_module

    stub_plugin = MagicMock()
    stub_plugin.name = "stub"
    stub_plugin.search.return_value = [
        DiscoveryResult(url="https://example.com/b", title="B")
    ]
    mock_register = MagicMock(
        return_value={"source_id": "src_2", "is_new": True}
    )

    with (
        patch.object(discover_module, "get_discovery", lambda _s: stub_plugin),
        patch.object(discover_module, "validate_public_url", lambda _u: None),
        patch.object(discover_module, "register_source", mock_register),
    ):
        discover_module.discover_sources("generic query", settings=_settings())

    assert mock_register.call_count == 1
    assert mock_register.call_args.kwargs["domain"] is None
