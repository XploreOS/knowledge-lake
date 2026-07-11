---
name: search-knowledge
description: >-
  Retrieve grounded answers from the knowledge lake and trace their provenance.
  Run a filtered semantic `search` (by source, format, tags, domain, or quality),
  then use `lineage` to trace any returned chunk back to its original raw document.
  Use this when a user asks a question over ingested content and needs cited,
  auditable answers.
---

# Search the knowledge lake with provenance

This skill covers retrieval and citation tracing using the Knowledge Lake MCP
tools. Reference only registry tool names.

## Journey

1. **Search** — `search`
   - `q` (required): the natural-language query.
   - `top_k` (optional): number of ranked chunk hits to return.
   - `mode` (optional): `hybrid` (default), `dense`, or `sparse`.
   - **Metadata filters** narrow retrieval to exactly the right slice of the lake:
     - `source_name` — restrict to one registered source.
     - `format` — restrict by source format, e.g. `"pdf"` or `"html"`.
     - `tags` — only chunks whose tags contain all of the given tags.
     - `domain` — restrict to a domain, e.g. `"healthcare"`.
     - `document_type`, `min_quality_score`, `source_id` — further scoping.
   - Each hit carries a score plus citation metadata (including the chunk's
     artifact id) so answers can be grounded and cited.

2. **Trace provenance** — `lineage`
   - Take the artifact id from a `search` hit and call `lineage` with
     `artifact_id` (required).
   - Returns the ordered ancestry chain from that chunk back to the original raw
     document — the audit trail behind any cited answer.

## Success

`search` returns relevant, filtered hits with citation metadata, and `lineage`
resolves each cited chunk to its source document — the answer is grounded and
fully auditable.
