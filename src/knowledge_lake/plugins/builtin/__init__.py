"""Built-in plugin implementations shipped with the core package (D-11).

These are registered via entry points in pyproject.toml just as a third-party
plugin would be, proving the seam works before any external plugins exist.

Built-ins:
    knowledge_lake.parsers:   docling → DoclingParser
    knowledge_lake.embedders: local   → SentenceTransformerEmbedder
                              litellm → LiteLLMEmbedder
    knowledge_lake.vectorstores: qdrant → QdrantVectorStore
    knowledge_lake.indexers  — pageindex (PageIndexIndexer: deterministic section tree)
"""
