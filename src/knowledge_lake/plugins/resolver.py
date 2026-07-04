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

if TYPE_CHECKING:
    from knowledge_lake.config.settings import Settings

# Entry-point group constants — stable names consumers can import
GROUP_PARSERS = "knowledge_lake.parsers"
GROUP_EMBEDDERS = "knowledge_lake.embedders"
GROUP_VECTORSTORES = "knowledge_lake.vectorstores"
GROUP_CRAWLERS = "knowledge_lake.crawlers"


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
    for ep in entry_points(group=GROUP_EMBEDDERS):
        if ep.name == name:
            factory = ep.load()
            if name == "litellm":
                return factory(litellm_url=settings.litellm_url)
            return factory()
    raise LookupError(
        f"No plugin {name!r} registered in entry-point group {GROUP_EMBEDDERS!r}. "
        f"Check that the package declaring this plugin is installed and that "
        f"the name is spelled correctly in your settings."
    )


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
    for ep in entry_points(group=GROUP_VECTORSTORES):
        if ep.name == name:
            factory = ep.load()
            if name == "qdrant":
                return factory(qdrant_url=settings.qdrant_url)
            return factory()
    raise LookupError(
        f"No plugin {name!r} registered in entry-point group {GROUP_VECTORSTORES!r}. "
        f"Check that the package declaring this plugin is installed and that "
        f"the name is spelled correctly in your settings."
    )


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
