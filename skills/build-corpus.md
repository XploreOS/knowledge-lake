---
name: build-corpus
description: >-
  Build a searchable knowledge-lake corpus from the open web end to end: register
  a source, crawl its pages, process the crawled documents through parse → chunk →
  embed → index, then verify with a search. Use this when a user wants to "ingest a
  site", "crawl and index", or "add a website to the lake and make it searchable".
---

# Build a searchable corpus

This skill drives the full ingestion journey using the Knowledge Lake MCP tools.
Every step names a tool from the single tool registry — never invent tool names.

## Journey

1. **Register the source** — `add_source`
   - `url` (required): the `https://` root of the site to ingest.
   - `name` (optional): human-readable source name; defaults to the URL hostname.
   - `domain` (optional): domain classification, e.g. `"healthcare"`.
   - `license_type` (optional): SPDX identifier or `"unknown"`.
   - `add_source` deduplicates by normalized URL — re-registering an existing
     source returns the existing entry (`is_new: false`).

2. **Crawl the pages** — `crawl` (one seed) or `crawl_all` (every registered source)
   - Single site: call `crawl` with `source_url` (required), optional `max_pages`
     to bound the frontier, and optional `crawler` to override the adapter.
   - Whole lake / a domain: call `crawl_all` with an optional `domain` filter to
     crawl every registered source at once. Failures on one source do not abort
     the others.
   - Crawling only stores raw HTML artifacts — it does not index anything yet.

3. **Process crawled documents** — `process_crawled`
   - Runs unprocessed `raw_document` artifacts through parse → chunk → embed → index.
   - `source_id` (optional): restrict to one source's raw docs.
   - `limit` (optional): cap how many raw documents to process this pass.
   - `collection` (optional): Qdrant collection to index chunks into.
   - Re-run until the returned `processed` count reaches zero (idempotent — already
     processed docs are skipped).

4. **Verify** — `search`
   - Call `search` with a representative `q` (natural-language query) and a small
     `top_k`. Non-empty, on-topic hits with citation metadata confirm the corpus
     is live and searchable.

## Success

A source is registered, its pages are crawled, `process_crawled` reports the
documents indexed, and `search` returns relevant chunks — the corpus is ready for
retrieval.
