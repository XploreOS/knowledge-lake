"""Config-keyed plugin resolver for the Knowledge Lake (FOUND-08).

Resolves plugin implementations by name over Python entry-point groups.
This is the single seam the pipeline (plan 05) uses to obtain swappable tools.

No pluggy dependency in Phase 1 — a plain config-keyed resolver only.
(pluggy is the Phase 3 fallback-chain evolution when parser fallback chains
are needed; the Protocol seam is identical so the switch is non-breaking.)

Usage:
    from knowledge_lake.plugins.resolver import get_embedder
    embedder = get_embedder(settings)   # returns the EmbedderPlugin named by settings.embedder

Entry-point groups:
    knowledge_lake.parsers       — ParserPlugin implementations
    knowledge_lake.embedders     — EmbedderPlugin implementations
    knowledge_lake.vectorstores  — VectorStorePlugin implementations

Swap example:
    KLAKE_EMBEDDER=litellm  →  get_embedder(settings) returns the LiteLLMEmbedder
    (no resolver code change required — FOUND-08, D-11)
"""

from __future__ import annotations

from importlib.metadata import entry_points
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from knowledge_lake.config.settings import Settings
    from knowledge_lake.plugins.protocols import ParsedDoc

log = structlog.get_logger(__name__)

# Entry-point group constants — stable names consumers can import
GROUP_PARSERS = "knowledge_lake.parsers"
GROUP_EMBEDDERS = "knowledge_lake.embedders"
GROUP_VECTORSTORES = "knowledge_lake.vectorstores"
GROUP_CRAWLERS = "knowledge_lake.crawlers"
GROUP_DISCOVERY = "knowledge_lake.discovery"


def resolve(group: str, name: str) -> Any:
    """Load and instantiate the plugin registered under *group* with entry-point name *name*.

    Iterates all entry points in *group* (as declared in pyproject.toml or by any
    installed package), matches the first one whose .name == *name*, calls .load()
    to get the class/callable, and calls it with no arguments to obtain an instance.

    Args:
        group: Entry-point group (e.g. 'knowledge_lake.embedders').
        name:  Entry-point name within the group (e.g. 'local', 'litellm').

    Returns:
        An instantiated plugin satisfying the relevant Protocol.

    Raises:
        LookupError: If no entry point named *name* is registered in *group*.
                     The error message includes both group and name so the operator
                     can diagnose a misconfigured settings value immediately.
    """
    for ep in entry_points(group=group):
        if ep.name == name:
            factory = ep.load()
            return factory()
    raise LookupError(
        f"No plugin {name!r} registered in entry-point group {group!r}. "
        f"Check that the package declaring this plugin is installed and that "
        f"the name is spelled correctly in your settings."
    )


def parse_with_fallback(
    raw: bytes,
    mime_type: str,
    *,
    settings: "Settings",
) -> "tuple[ParsedDoc, str, float]":
    """Try parsers in settings.parse.chain order. Stop on first success (D-02).

    Fallback triggers on exception OR quality gate failure (D-01):
      - Exception during parse → log warning, continue to next parser
      - Quality score below settings.parse.quality_threshold → log warning, continue
      - LookupError (parser not installed) → log warning, continue
      - can_parse() returns False → continue silently (format mismatch)

    Returns (ParsedDoc, parser_name_used, quality_score) on first success.
    Raises ValueError when all parsers in the chain are exhausted.

    Args:
        raw:       Raw document bytes to parse.
        mime_type: MIME type of the document.
        settings:  Application settings (parse.chain, parse.quality_threshold, etc.).

    Returns:
        Tuple of (ParsedDoc, str parser_name, float quality_score).

    Raises:
        ValueError: If all parsers in chain are exhausted without success.
    """
    from knowledge_lake.quality.scorer import compute_quality_score, maybe_llm_spot_check

    tried: list[str] = []
    for parser_name in settings.parse.chain:
        tried.append(parser_name)

        # Step 1: Resolve the parser from entry-point registry.
        # Inject constructor args for parsers that require settings values so
        # no parser reads os.environ directly (CR-03 / WR-03).
        try:
            for ep in entry_points(group=GROUP_PARSERS):
                if ep.name == parser_name:
                    factory = ep.load()
                    if parser_name == "tika":
                        parser = factory(tika_server_url=settings.tika_server_url)
                    else:
                        parser = factory()
                    break
            else:
                raise LookupError(parser_name)
        except LookupError:
            log.warning(
                "parse_with_fallback.parser_not_available",
                parser_name=parser_name,
                mime_type=mime_type,
            )
            continue

        # Step 2: Check MIME type compatibility
        if not parser.can_parse(mime_type):
            continue

        # Step 3: Attempt parsing
        try:
            parsed_doc = parser.parse(raw, mime_type)
        except Exception as exc:
            log.warning(
                "parse_with_fallback.parser_failed",
                parser_name=parser_name,
                mime_type=mime_type,
                error=str(exc),
                exc_info=True,
            )
            continue

        # Step 4: Compute deterministic heuristic quality score
        score = compute_quality_score(parsed_doc, mime_type, settings)

        # Step 5: Optional LLM spot-check in gray zone (D-04)
        final_score = maybe_llm_spot_check(parsed_doc, score, settings)

        # Step 6: Quality gate (D-01)
        if final_score >= settings.parse.quality_threshold:
            log.info(
                "parse_with_fallback.success",
                parser_name=parser_name,
                mime_type=mime_type,
                quality_score=round(final_score, 3),
            )
            return parsed_doc, parser_name, final_score

        log.warning(
            "parse_with_fallback.parser_low_quality",
            parser_name=parser_name,
            mime_type=mime_type,
            quality_score=round(final_score, 3),
            threshold=settings.parse.quality_threshold,
        )

    raise ValueError(
        f"All parsers in chain exhausted for mime_type={mime_type!r}. "
        f"Chain: {settings.parse.chain}. Tried: {tried}"
    )


def get_parser(settings: "Settings") -> Any:
    """Return the ParserPlugin named by settings.parser.

    Reads the 'parser' swap key from the provided Settings instance and
    resolves it via the 'knowledge_lake.parsers' entry-point group.

    Args:
        settings: Application Settings instance (from get_settings() or test fixture).

    Returns:
        An instantiated ParserPlugin (satisfies ParserPlugin Protocol).
    """
    return resolve(GROUP_PARSERS, settings.parser)


def _resolve_with_kwargs(group: str, name: str, **kwargs: Any) -> Any:
    """Load and instantiate a plugin, injecting constructor kwargs.

    Extends :func:`resolve` for plugins that require constructor arguments
    (e.g. ``litellm_url``, ``qdrant_url``, ``tika_server_url``) without
    duplicating the entry-point iteration loop. Any future change to the
    lookup semantics need only be applied here and in :func:`resolve` (WR-06).

    Args:
        group:   Entry-point group (e.g. 'knowledge_lake.embedders').
        name:    Entry-point name within the group (e.g. 'litellm').
        **kwargs: Constructor keyword arguments forwarded to the plugin factory.

    Returns:
        An instantiated plugin satisfying the relevant Protocol.

    Raises:
        LookupError: If no entry point named *name* is registered in *group*.
    """
    for ep in entry_points(group=group):
        if ep.name == name:
            factory = ep.load()
            return factory(**kwargs)
    raise LookupError(
        f"No plugin {name!r} registered in entry-point group {group!r}. "
        f"Check that the package declaring this plugin is installed and that "
        f"the name is spelled correctly in your settings."
    )


def get_embedder(settings: "Settings") -> Any:
    """Return the EmbedderPlugin named by settings.embedder.

    Reads the 'embedder' swap key from the provided Settings instance and
    resolves it via the 'knowledge_lake.embedders' entry-point group.

    Default: 'local' → SentenceTransformerEmbedder (zero AWS creds, D-13).
    Switch:  'litellm' → LiteLLMEmbedder (gateway via embedding_model alias).

    For the 'litellm' embedder, the proxy URL is injected from settings.litellm_url
    rather than read from env directly (CR-03: no os.environ.get in plugin builtins).

    Args:
        settings: Application Settings instance.

    Returns:
        An instantiated EmbedderPlugin (satisfies EmbedderPlugin Protocol).
    """
    name = settings.embedder
    kwargs = {"litellm_url": settings.litellm_url} if name == "litellm" else {}
    return _resolve_with_kwargs(GROUP_EMBEDDERS, name, **kwargs)


def get_vectorstore(settings: "Settings") -> Any:
    """Return the VectorStorePlugin named by settings.vectorstore.

    Reads the 'vectorstore' swap key from the provided Settings instance and
    resolves it via the 'knowledge_lake.vectorstores' entry-point group.

    The Qdrant URL is injected from settings.qdrant_url rather than read from
    env directly (CR-03: no os.environ.get in plugin builtins).

    Args:
        settings: Application Settings instance.

    Returns:
        An instantiated VectorStorePlugin (satisfies VectorStorePlugin Protocol).
    """
    name = settings.vectorstore
    kwargs = {"qdrant_url": settings.qdrant_url} if name == "qdrant" else {}
    return _resolve_with_kwargs(GROUP_VECTORSTORES, name, **kwargs)


def get_discovery(settings: "Settings") -> Any:
    """Return the DiscoveryPlugin named by settings.discovery.

    Reads the 'discovery' swap key from the provided Settings instance and
    resolves it via the 'knowledge_lake.discovery' entry-point group.

    Default: 'searxng' → SearXNGDiscovery (self-hosted meta-search, JSON API).

    The SearXNG URL is injected from settings.searxng_url rather than read
    from env directly (CR-03: no os.environ.get in plugin builtins).

    Args:
        settings: Application Settings instance.

    Returns:
        An instantiated DiscoveryPlugin (satisfies DiscoveryPlugin Protocol).
    """
    name = settings.discovery
    kwargs = {"searxng_url": settings.searxng_url} if name == "searxng" else {}
    return _resolve_with_kwargs(GROUP_DISCOVERY, name, **kwargs)


def get_crawler(settings: "Settings") -> Any:
    """Return the CrawlerPlugin named by settings.crawler.

    Reads the 'crawler' swap key from the provided Settings instance and
    resolves it via the 'knowledge_lake.crawlers' entry-point group.

    Default: 'crawl4ai' -> Crawl4AIAdapter (async-first, JS-rendered, markdown output).
    Switch:  'scrapy'   -> ScrapyAdapter (high-volume structured crawling).

    No os.environ reads in builtins (CR-03); service URLs/config are injected
    from Settings where needed by the adapter factory.

    Args:
        settings: Application Settings instance.

    Returns:
        An instantiated CrawlerPlugin (satisfies CrawlerPlugin Protocol).
    """
    return resolve(GROUP_CRAWLERS, settings.crawler)
