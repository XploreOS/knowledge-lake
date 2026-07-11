"""
knowledge_lake.agent — MCP agent surfaces (stdio, Streamable HTTP, OpenAI tool defs).

Every tool in this package is a thin shim over an existing ``pipeline/*.py``
service function.  No lake business logic lives here — this is a pure
re-surfacing layer.

Surfaces:
  - stdio transport: :mod:`knowledge_lake.agent.stdio`
  - HTTP transport:  :mod:`knowledge_lake.agent.http`
  - Tool registry:   :mod:`knowledge_lake.agent.registry`
  - OpenAI defs:     :mod:`knowledge_lake.agent.openai_defs`
"""
