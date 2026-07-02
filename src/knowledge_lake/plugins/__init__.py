"""Plugin system for Knowledge Lake (FOUND-08).

Provides Protocol contracts (protocols.py), config-keyed resolver (resolver.py),
and built-in implementations (builtin/).

Usage:
    from knowledge_lake.plugins.resolver import get_embedder
    embedder = get_embedder(settings)
    vectors = embedder.embed(["text"])
"""
