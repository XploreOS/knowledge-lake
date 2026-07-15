---
quick_id: 260715-chy
slug: fix-remaining-low-findings-ci-image-buil
description: Fix remaining low findings, CI image build guard, parse section persistence
created: 2026-07-15
mode: quick
status: planned
addresses:
  - KL-12
  - KL-13
  - KL-14
  - KL-15
  - KL-17
  - KL-19
  - "Dockerfile landmine (CI never builds the image)"
  - "parse section persistence (root cause behind KL-09's re-parse workaround)"
---

# Quick Task 260715-chy: last low findings + Dockerfile landmine + parse persistence

## Goal

Close the final six low-severity findings, make the Dockerfile landmine
*impossible to repeat*, and fix the parse-persistence root cause that forced
KL-09's re-parse workaround and silently degrades `klake chunk` citations.

## Waves

```
Wave A (mechanical / docs / tests):  Tasks 1-6
Wave B (structural, data-shape):     Tasks 7-8
```

---

## Wave A

### Task 1 — KL-12: README documents the wrong enrich alias

- **files:** `README.md`
- **background:** README:208 says enrich "Calls LiteLLM (`strong_model` alias →
  Bedrock)". `settings.py:160` defaults `model_alias = "cheap_model"`, and the
  live run log confirms `model=cheap_model`. The **code** is right (cheap_model
  is the sensible default for metadata extraction, and `settings.py:161` documents
  strong_model as the opt-in for domain-heavy packs). The README is wrong.
- **action:** Correct README to say `cheap_model` by default, and mention the
  `KLAKE_ENRICH__MODEL_ALIAS` override to `strong_model`. Do NOT change the code
  default — that would silently raise everyone's costs ~9× (see KL-02).
- **verify:** README matches `settings.py`'s default.

### Task 2 — KL-13: Rich markup eats the regex in CLI help

- **files:** `src/knowledge_lake/cli/app.py`, `src/knowledge_lake/domains/scaffold.py`
- **background:** `klake domain new --help` renders *"must match `^{0,63}$`"* —
  Rich parses `[a-zA-Z]` as markup tags and strips them. Source is correct:
  `^[a-zA-Z][a-zA-Z0-9_-]{0,63}$`. The same regex is duplicated at
  `cli/app.py:1138` and `domains/scaffold.py:31`.
- **action:** Make the help text render the real pattern (escape the brackets for
  Rich, e.g. `\[`, or disable markup for that string — pick whichever works and
  prove it by capturing `--help` output). De-duplicate the regex: define it once
  (scaffold.py is the natural owner) and import it in the CLI.
- **verify:** `klake domain new --help` shows the full literal pattern
  `^[a-zA-Z][a-zA-Z0-9_-]{0,63}$`. One definition, one import.

### Task 3 — KL-14: two `dst_` IDs per export

- **files:** `src/knowledge_lake/pipeline/export.py`, `src/knowledge_lake/registry/repo.py`
- **background:** each export mints `export_id = new_id("dataset")` for the
  **filename**, then `create_dataset()` mints a **second** `dst_` id for the row —
  so `dataset_id=dst_…87d8` points at `…87ce.parquet`. Traceability survives via
  `name`/`storage_uri`, so this is confusion, not breakage — but "which `dst_` is
  this?" is a question a lineage-first framework shouldn't provoke.
- **action:** Use one ID for both. The key is built before the row exists, so add
  an optional `id` parameter to `create_dataset()` and pass the `export_id`
  through in all three export functions. Keep `get_or_create_dataset()`'s
  behavior unchanged (it does not take an id). Then the redundant
  `name=f"rag_corpus_{export_id}"` prefix is no longer carrying the linkage —
  leave the name format alone (changing it risks the unique-name constraint and
  existing rows); just make the IDs agree.
- **verify:** run a real export; `dataset_id` equals the ID in `storage_uri`.

### Task 4 — KL-17a: `put_raw` docstring is stale

- **files:** `src/knowledge_lake/storage/s3.py`
- **background:** the docstring documents `raw/{source_id}/{sha256}.{ext}`; actual
  keys are `raw/{domain}/{source_id}/{sha256}.{ext}` — the same `domain` kwarg
  whose absence from the test mocks caused KL-03.
- **action:** Correct the docstring to the real key layout.
- **verify:** docstring matches an actual key from the registry.

### Task 5 — KL-17b/c/d: remaining drift

- **files:** `docs/architecture.md` (or wherever the plugin claim lives),
  `src/knowledge_lake/pipeline/datasets.py`, `src/knowledge_lake/domains/models.py`
- **b) LLM gateway is not a plugin.** The architecture doc lists LLM gateways
  alongside parsers/crawlers/vector stores as replaceable plugins, but there is no
  `LLMGatewayPlugin` protocol — LiteLLM is imported directly in `enrich`,
  `datasets`, `tree_index`, `scorer`.
  **Decision: fix the doc, not the code.** LiteLLM *is already* the gateway
  abstraction (100+ providers behind one interface); wrapping an abstraction in a
  second plugin protocol is over-engineering for zero gain. Correct the doc to
  state that the gateway is LiteLLM by constraint, and that provider swapping
  happens in `infra/litellm/config.yaml`, not via an entry point. Grep for every
  place making the plugin claim.
- **c) Alias configurability is inconsistent.** `datasets.py:189,227` hardcode
  `"openai/eval_model"` / `"openai/strong_model"`; `enrich.py` reads
  `settings.enrich.model_alias`. Add settings fields for the dataset aliases
  (mirroring `EnrichSettings.model_alias`) and read them. Keep the current
  aliases as the defaults — no behavior change.
- **d)** `domains/models.py:78` — a framework-core dataclass documented as
  *"Result from HealthcareValidator"*. Make it domain-neutral.
- **verify:** no `healthcare` in `src/` outside genuinely domain-example strings;
  `grep -rn '"openai/' src/` returns nothing hardcoded outside settings.

### Task 6 — KL-19 + the Dockerfile landmine

**6a — KL-19: tests patch a target that is never consulted.**

- **files:** `tests/unit/test_api_search_mode.py`, `tests/unit/test_cli_search_mode.py`
- **background:** 4 tests patch `knowledge_lake.pipeline.search.search`, but
  `pipeline/route.py:18` does `from knowledge_lake.pipeline.search import search`
  at import time, binding its own module-level name. `routed_search` calls
  `route.search`, so the patch never applies and the tests can never pass. The
  feature works — `?mode=` and `--mode` are fully wired.
- **action:** Patch `knowledge_lake.pipeline.route.search` instead. Then **remove
  the 4 xfail markers** — with `xfail_strict = true` active, a now-passing test
  that keeps its marker fails the build. That is the flag working.
- **verify:** the 4 tests pass with markers gone; suite has 0 xpassed.

**6b — the Dockerfile landmine: make it impossible to repeat.**

- **files:** `.github/workflows/ci.yml`
- **background:** the base image had been bumped to `python:3.14-slim`, which
  cannot build (greenlet has no CPython 3.14 support), and `COPY` omitted
  `LICENSE`/`NOTICE`. Both were fixed in `260715-bgt` — the base is already back
  to `python:3.12-slim`, so **there is nothing left to revert**. The real gap is
  that **nothing would have caught it**: CI's integration job runs
  `docker compose up -d postgres minio qdrant` — all pre-built public images. The
  api image with the `build:` stanza is **never built in CI**, so the Dockerfile
  could rot unbuildable for 13 days behind a green badge. Identical in shape to
  KL-03 (tests that never ran).
- **action:** Add a CI step/job that builds the api image (e.g.
  `docker compose build api`) so an unbuildable Dockerfile fails the build. Keep
  it cheap — build only, no push, and let it use layer caching if straightforward.
  Consider asserting the base matches `.python-version` if that is cheap and not
  brittle; the build itself is the real guard.
- **verify:** `docker compose build api` succeeds locally; the workflow YAML
  parses and the job graph is coherent. State plainly that you cannot execute
  GitHub Actions — do not claim CI passed.

---

## Wave B — structural

### Task 7 — KL-15: domain is untyped JSON on `sources.config`

- **files:** new Alembic migration, `src/knowledge_lake/registry/models.py`,
  `src/knowledge_lake/registry/repo.py`, `src/knowledge_lake/pipeline/ingest.py`,
  `src/knowledge_lake/pipeline/domains.py`
- **background:** `sources` has no `domain` column; domain lives in the `config`
  JSON blob. It is first-class in the CLI (`--domain`), the storage layout
  (`raw/{domain}/…`), the pack system, and — since KL-01 — the export filter. But
  it is unindexed, unvalidated, and unconstrained.
  **Blast radius is small:** every read goes through
  `registry_repo.get_domain_for_source()` (repo.py:861). Writes are
  `ingest.py:301` (`config_dict["domain"]`) and `domains.py:114` (pack registration).
- **action:** Add a nullable `domain` column (indexed) to `sources` via a new
  Alembic migration that **backfills from `config->>'domain'`**, and give it a
  working `downgrade()` (the project's migration tests round-trip). Point
  `get_domain_for_source()` at the column. Write the column at both write sites.
  Keep writing `config["domain"]` too for one release so nothing that reads the
  blob directly breaks — call that out in the SUMMARY as a deprecation to remove
  later. Do not attempt to make export filtering a SQL WHERE clause in this task;
  correctness first, the accessor swap is enough.
- **verify:** migration up/down round-trips; existing rows keep their domain
  (aviation/functional-medicine rows already exist — check them);
  `klake export --domain aviation` still yields 51 aviation-only rows (KL-01
  regression); `klake init --domain aviation` still idempotent.

### Task 8 — parse persistence (root cause behind KL-09)

- **files:** `src/knowledge_lake/pipeline/parse.py`,
  `src/knowledge_lake/pipeline/chunk.py`, `src/knowledge_lake/cli/app.py`
- **background:** parse persists only `{quality_score, parser_used, title}` and
  the silver zone holds **markdown only**. Sections are lost, which forces two bad
  outcomes:
  1. `klake tree-index` must **re-parse the raw document** (~40s of Docling on a
     19-page PDF) just to recover sections.
  2. `klake chunk` reconstructs a **section-less minimal ParsedDoc**, so
     CLI-path chunks carry no `section_path` — silently degrading citations in a
     framework whose entire promise is traceability.
- **Design decision — sidecar in the silver zone, NOT Postgres.** `Section` carries
  `text` (Docling populates it — `docling_parser.py:220`), so the sections list
  contains the whole document body. Persisting it in `metadata_` would duplicate
  every document into the registry. Write a JSON sidecar next to the existing
  markdown in the silver zone instead (e.g. `<same-key>.sections.json` or a
  `parsed_doc` JSON), which matches the existing zone split — S3 for bytes,
  Postgres for lineage/metadata — and CLAUDE.md's storage constraint.
- **action:**
  - In `parse`, serialize the ParsedDoc (text + sections + metadata) to a
    silver-zone JSON sidecar alongside the `.md`, and record its URI on the parsed
    artifact so it is discoverable. **Raw-zone immutability is untouched** — this
    is silver.
  - Add a helper to rehydrate a `ParsedDoc` from a parsed artifact.
  - Use it in `cmd_chunk` (so CLI chunks regain `section_path`) and in
    `cmd_tree_index` (so it no longer re-parses). **Keep the re-parse as a
    fallback** for artifacts parsed before this change — degrade, never crash, and
    log which path was taken.
- **verify:**
  - Re-parse the aviation PDF; a sections sidecar exists in the silver zone.
  - `klake chunk` on the new artifact produces chunks **with** `section_path`
    (currently empty) — show before/after.
  - `klake tree-index` on it completes **without** re-parsing (much faster) and
    still yields a real tree; `tree-search` still returns section-aware hits.
  - An OLD artifact with no sidecar still works via the fallback.
- **done:** sections survive parse; chunk citations are whole; tree-index is cheap.

---

## Must haves

- **truths:**
  - `klake domain new --help` shows the real regex; one definition of it.
  - `dataset_id` matches the ID in its `storage_uri`.
  - No hardcoded model aliases outside settings; no domain-specific naming in framework core.
  - CI builds the api image, so an unbuildable Dockerfile fails the build.
  - `sources.domain` is a real indexed column, backfilled, with a working downgrade.
  - Sections survive parse; `klake chunk` emits `section_path`; `tree-index` does not re-parse.
  - Earlier fixes do NOT regress: KL-01 (domain filtering), KL-02 (proxy cost),
    KL-03, KL-04/05/06 (ordering chain), KL-07, KL-10 (xfail_strict), KL-18 (no 5xx).
- **artifacts:** new Alembic migration; `parse.py` sidecar; `.github/workflows/ci.yml`
- **key_links:** `.planning/E2E-GAP-ANALYSIS.md`; `src/knowledge_lake/registry/repo.py:861`

## Out of scope

- Building an `LLMGatewayPlugin` protocol (decided: fix the doc instead).
- Changing the `enrich` model-alias default (KL-12 is a doc fix; changing the
  default would raise costs ~9×).
- Rewriting export filtering into a SQL WHERE clause using the new column.
- Removing the transitional `config["domain"]` dual-write.
