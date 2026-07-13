---
phase: quick-260713-1yf
plan: 01
subsystem: pipeline
status: complete
tags: [datasets, discover, crawl, quality, chunk-storage, domain-inheritance, challenge-gate]
requires:
  - artifacts.storage_uri (existing column)
  - Source.config['domain'] (existing config key)
  - StorageBackend (S3-compatible)
provides:
  - grounded QA excerpt read-back from chunk storage_uri
  - domain propagation through discover/crawl to registered sources
  - deterministic anti-bot/CAPTCHA parse-gate rejection
affects:
  - src/knowledge_lake/pipeline/chunk.py
  - src/knowledge_lake/pipeline/datasets.py
  - src/knowledge_lake/pipeline/discover.py
  - src/knowledge_lake/pipeline/crawl.py
  - src/knowledge_lake/cli/app.py
  - src/knowledge_lake/plugins/resolver.py
  - src/knowledge_lake/quality/challenge.py
tech-stack:
  added: []
  patterns:
    - "chunk text persisted as derived (silver-tier) artifact via storage_uri pointer (no new column)"
    - "active-domain reuse: settings.domain.domain_name / --domain → register_source(domain=...)"
    - "deterministic phrase gate with single extensible regex list (no LLM)"
key-files:
  created:
    - src/knowledge_lake/quality/challenge.py
    - tests/unit/test_chunk_storage.py
    - tests/unit/test_discover_domain.py
    - tests/unit/test_challenge_detection.py
  modified:
    - src/knowledge_lake/pipeline/chunk.py
    - src/knowledge_lake/pipeline/datasets.py
    - src/knowledge_lake/pipeline/discover.py
    - src/knowledge_lake/pipeline/crawl.py
    - src/knowledge_lake/cli/app.py
    - src/knowledge_lake/plugins/resolver.py
    - tests/unit/test_datasets.py
decisions:
  - "Finding 1: chunk text stored at chunks/{domain}/{source_id}/{content_hash}.txt and pointed to via existing artifacts.storage_uri — no Alembic migration; QA read-back falls back to metadata text then empty string for pre-fix chunks"
  - "Finding 2: reuse the existing active-domain concept (settings.domain.domain_name) and register_source's existing domain kwarg (Source.config['domain']) — pure plumbing, no schema change"
  - "Finding 3: deterministic regex phrase gate fires BEFORE quality scoring and raises (not fallback) so challenge pages are rejected regardless of score"
metrics:
  duration: ~20m
  completed: 2026-07-13
  tasks: 3
  files: 11
---

# Quick Task 260713-1yf: Fix Three Pipeline Findings Summary

Fixed three independent findings from the functional-medicine end-to-end test as
self-contained atomic commits: QA generation now reads grounded chunk text from
object storage, discover/crawl now inherit the active domain, and anti-bot/CAPTCHA
challenge pages are deterministically rejected by the parse quality gate.

## Findings Fixed

### Finding 1 — QA generation was ungrounded (empty chunk excerpt)

**Root cause:** `chunk()` never persisted the chunk text and stored no `text` key
in `metadata_`, so `generate_qa_example()` (which read `metadata_["text"]`) always
sent an empty excerpt to the eval_model — Q&A was hallucinated, not grounded.

**Fix (storage-uri approach, no migration):**
- `chunk.py` now instantiates a `StorageBackend`, resolves the domain segment once
  via `get_domain_for_source(session, source_id)` (falling back to the shared
  `_UNCLASSIFIED_DOMAIN` literal), and for each **newly created** chunk writes the
  text to `chunks/{domain}/{source_id}/{content_hash}.txt` with tags mirroring
  `parse.py`, then passes `storage_uri=object_uri(key)` into `create_chunk_artifact`.
  The `get_artifact_by_hash` no-op branch is untouched (no rewrite of existing text).
- `datasets.py generate_qa_example` now reads the excerpt back from `storage_uri`
  (`get_object(_uri_to_key(...)).decode`) inside a try/except that degrades to the
  metadata text then empty string — pre-fix chunks (storage_uri=None) still work.
- Reuses the existing `artifacts.storage_uri` column → **no Alembic migration**.
- `generate_instruction_example` is byte-for-byte unchanged.

**Commit:** `2a800d3`

### Finding 2 — discover/crawl did not inherit the active domain

**Root cause:** `discover_sources`/`crawl_source` called `register_source` without a
domain, so discovered/crawled data landed under `_unclassified/` even when a domain
was active.

**Fix (active-domain reuse, no schema change):**
- `discover_sources` and `crawl_source` gained an optional `domain: str | None = None`
  param, forwarded into the existing `register_source(domain=...)` kwarg (stored in
  `Source.config['domain']`). None stays backward-compatible.
- `klake discover` and `klake crawl` gained a `--domain`/`-d` option; each resolves
  the effective domain as the explicit option or, when omitted,
  `get_settings().domain.domain_name` — the same session-domain the enrich CLI uses.
- Same-domain crawl-scope logic (`seed_domain`/`_registrable_domain`) is untouched —
  that is URL host scoping, unrelated to the classification domain.

**Commit:** `aa606f1`

### Finding 3 — anti-bot/CAPTCHA pages passed the quality gate

**Root cause:** challenge interstitials (Cloudflare "Just a moment", CAPTCHA,
Akamai/Incapsula blocks) have clean text and scored above the heuristic threshold
(observed 0.867 PASSED), so they were indexed and poisoned the vector store (T-QF-01).

**Fix (deterministic challenge-phrase gate):**
- New `quality/challenge.py` exposes `is_challenge_page(text) -> str | None`, a pure,
  LLM-free, network-free scan over a single, clearly-documented, extensible regex list
  (`_CHALLENGE_PATTERNS`) covering Cloudflare (`cf-browser-verification`, `cf-challenge`,
  "just a moment", "checking your browser", "attention required"), Akamai
  (`AkamaiGHost`, access-denied reference), Incapsula/Imperva (`incapsula incident id`,
  `_incapsula_resource`), and generic human-verification markers.
- `parse_with_fallback` calls it immediately after a parser returns `parsed_doc` and
  **before** computing the quality score. On a match it logs
  `parse_with_fallback.challenge_page_rejected` and raises `ValueError` — the page is
  rejected regardless of score and never reaches chunk/embed/index.

**Commit:** `bd99cc1`

## Deviations from Plan

None — plan executed exactly as written. No architectural changes, no auto-fixes
required beyond the specified work.

## Constraints Honored

- LiteLLM-only model routing untouched (`openai/eval_model` / `openai/strong_model`).
- Chunk text persisted only through `StorageBackend.put_object` (S3-compatible); no
  local filesystem; raw zone untouched (chunk text is a derived silver-tier artifact).
- Lineage preserved: chunk `storage_uri` traces to its parent via the existing
  content_hash (WR-05 parent-in-hash rule unchanged).
- Finding 3 is a deterministic regex/heuristic filter — no LLM call.
- No Alembic migration; no DB column added (grep of `alembic/` diff over the three
  commits is empty).
- `instruction` dataset kind path is unchanged.

## Verification

Per-task `<verify>` blocks (ruff + targeted tests) all passed. Final full run:

```
uv run ruff check src/    → All checks passed!
uv run pytest tests/unit -m "not browser" -q
  → 547 passed, 1 xfailed, 39 xpassed
```

New tests: `test_chunk_storage.py` (2), QA-grounding regression in
`test_datasets.py` (1), `test_discover_domain.py` (2), `test_challenge_detection.py`
(13).

## Commits

| Task | Finding | Commit  |
|------|---------|---------|
| 1    | QA grounding via chunk storage_uri | `2a800d3` |
| 2    | domain propagation to discover/crawl | `aa606f1` |
| 3    | challenge-page parse gate | `bd99cc1` |

## Self-Check: PASSED

- src/knowledge_lake/quality/challenge.py — FOUND
- tests/unit/test_chunk_storage.py — FOUND
- tests/unit/test_discover_domain.py — FOUND
- tests/unit/test_challenge_detection.py — FOUND
- Commit 2a800d3 — FOUND
- Commit aa606f1 — FOUND
- Commit bd99cc1 — FOUND
