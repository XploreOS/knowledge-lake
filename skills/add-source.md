---
name: add-source
description: >-
  Bring new material into the knowledge lake. Register a source for later crawling
  with `add_source`, or fetch-and-ingest a single document in one shot with
  `ingest_url`. Use this when a user wants to "add a source", "register a site", or
  "ingest this URL/PDF right now".
---

# Add a source or ingest a document

This skill covers the two entry points for getting content into the lake, using
the Knowledge Lake MCP tools. Reference only registry tool names.

## Choose the path

- **Register now, crawl later** → `add_source`
- **Fetch and ingest one document immediately** → `ingest_url`

## Journey A — register a source (`add_source`)

1. Call `add_source` with:
   - `url` (required): the `https://` root of the source.
   - `name` (optional): human-readable name; defaults to the URL hostname.
   - `domain` (optional): domain classification, e.g. `"healthcare"`.
   - `license_type` (optional): SPDX identifier or `"unknown"`.
2. Deduplicates by normalized URL — an existing source is returned unchanged
   (`is_new: false`). The source is now available to `crawl` / `crawl_all`.

## Journey B — one-shot ingest (`ingest_url`)

1. Call `ingest_url` with:
   - `url` (required): the `https://` URL of the document to ingest.
   - `source_name` (required): name for the source registry entry.
   - `mime_type` (optional): override, e.g. `"application/pdf"`.
   - `license_type` (optional): SPDX identifier or `"unknown"`.
   - `robots_checked` (optional): set `true` only after confirming robots.txt
     allows fetching.
2. `ingest_url` fetches the document, stores it immutably in the raw zone, and
   returns the new artifact id (plus source id and content hash).

## Success

`add_source` returns a registered source ready to crawl, or `ingest_url` returns
an artifact id for a document now stored in the raw zone.
