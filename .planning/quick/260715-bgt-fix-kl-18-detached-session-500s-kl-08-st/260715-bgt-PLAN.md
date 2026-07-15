---
quick_id: 260715-bgt
slug: fix-kl-18-detached-session-500s-kl-08-st
description: Fix KL-18 detached-session 500s, KL-08 stale container, KL-09 tree-index CLI
created: 2026-07-15
mode: quick
status: planned
addresses:
  - KL-18
  - KL-08
  - KL-09
---

# Quick Task 260715-bgt: KL-18, KL-08, KL-09

## Goal

Close the last high-severity finding (KL-18) and the two remaining mediums from
the original audit (KL-08, KL-09).

---

## Task 1 — KL-18: three endpoints return 500 (detached ORM instances)

### Investigation (established; do not re-derive)

`registry/db.py:82` opens `Session(get_engine())` — default
`expire_on_commit=True` — and `get_session()` **commits on clean exit**. The
commit expires every attribute on every instance. Three endpoints build their
response objects **after** the `with get_session()` block has closed, so the
first attribute access on a detached+expired instance triggers a refresh with no
session → `DetachedInstanceError` → 500.

The shape is identical in all three (query inside the block, `return [...]`
comprehension outside it):

| Route | Endpoint | app.py |
|---|---|---|
| `GET /documents` | `list_documents_endpoint` | ~1405 (`with` at 1436, `return [` at 1445) |
| `GET /datasets` | `list_datasets_endpoint` | ~1496 |
| `GET /curated-documents` | (curated list endpoint) | `with` at 1098, `return [` at 1105 |

**Measured — every GET route probed against the real app + real registry:**

```
/health                  200
/search                  422   (missing required q — correct)
/crawl-jobs/{job_id}     404   (correct)
/curated-documents       500   <<< BROKEN
/lineage/{artifact_id}   200
/sources                 200
/sources/{source_id}     200
/documents               500   <<< BROKEN
/documents/{artifact_id} 200
/datasets                500   <<< BROKEN
/datasets/{dataset_id}   200
/domains/{name}/sources  200
```

Note the pattern: every **list** endpoint that builds outside the session is
broken; every **single-item** endpoint happens to work. `/curated-documents` was
**not** part of the original KL-18 finding — it has no test at all, so nothing was
even pretending to cover it. The other two had tests that carried
`xfail(reason="…not yet added")`, which was false: the endpoints exist and are
broken.

### Action

- **files:** `src/knowledge_lake/api/app.py`,
  `tests/integration/test_api_new_endpoints.py`
- Move the response-object construction **inside** the `with get_session()` block
  in all three endpoints, so attributes are read while the instances are still
  live. Do not disable `expire_on_commit` globally — that is a broad behavioral
  change to every session in the codebase; fix the three call sites.
- Remove the now-false `xfail` markers from `test_get_documents_returns_200` and
  `test_get_datasets_returns_200`. **`xfail_strict = true` is active**, so leaving
  them would fail the build once the endpoints work — that is the flag doing its
  job, not a problem to work around.
- Add a test for `GET /curated-documents` — it currently has none, which is why
  it was invisible.
- **verify:** re-probe all GET routes; `/documents`, `/datasets`,
  `/curated-documents` return 200 against the real registry.
- **done:** No GET route 5xxs.

---

## Task 2 — KL-08: stale container serving 2 of 29 routes, reporting healthy

### Investigation (established)

`Dockerfile` does `COPY src/ ./src/` then `uv sync --no-dev`; compose declares no
volume for the api service. `docker compose up -d` — exactly what the README
prescribes — does **not** rebuild an existing image, so the container silently
runs whatever source was baked at build time. Measured: the running container's
`app.py` is 1,296 bytes / 2 routes dated Jul 2, against a repo file of 60,750
bytes / 29 routes — 13 days stale. The healthcheck probes only `/health`, which
happens to be one of the two surviving routes, so compose reports
`Up (healthy)` while 27 of 29 endpoints 404. This is also **why KL-18 hid**:
nobody could hit `/documents` locally to see the 500.

### Action

- **files:** `docker-compose.yml`, `src/knowledge_lake/api/app.py`, `README.md`
- **Kill the staleness at the source:** mount the working tree into the api
  service (`./src:/app/src:ro`). `uv sync` installs the project editable, so
  `/app/src` is the import path — verify that assumption before relying on it
  (check for a `.pth`/editable finder in the container's site-packages). If the
  install is NOT editable, say so and fall back to documenting `--build` plus the
  fingerprint below, rather than shipping a mount that silently does nothing.
  Consider the same mount for `dagster-webserver`/`dagster-daemon`, which have a
  known equivalent staleness problem.
- **Make any remaining drift observable:** have `/health` report the running
  code's `pipeline_version()` (already exists in `version.py`, formats as
  `0.1.0+<git-sha>`), so a stale container is visible in one curl instead of
  invisible behind a green healthcheck. Keep the existing `status` key —
  `{"status": "ok"}` is documented in the README and asserted by the compose
  healthcheck (`curl -fsS .../health`); add to it, don't reshape it. Update the
  README's documented response and any test asserting exact equality.
- **README:** document `docker compose up -d --build` for picking up code changes.
- **verify:** with the mount, an edit to `src/` is visible to the container after
  `docker compose restart api` with no rebuild; `/health` reports a version.
- **done:** Stale code is either impossible (mount) or immediately visible (version).

> Out of scope: a healthcheck that asserts an expected route count/fingerprint —
> it has no trustworthy source of truth for "expected" and would be brittle.

---

## Task 3 — KL-09: tree-search is unreachable from the CLI

### Investigation (established)

The CLI ships the consumer (`klake tree-search`) but not the producer. Building a
tree index is only possible via the `tree_index_document` Dagster asset — there is
no `klake tree-index`. The registry holds **0** `tree_index` artifacts, and
`tree-search` answers `No results` as though the query merely missed.

**The constraint that shapes the design:** `tree_index(parsed_artifact_id,
source_id, parsed_doc, ...)` needs an in-memory `ParsedDoc`, and parse persists
only `{quality_score, parser_used, title}` in `metadata_` — **sections are not
persisted**; the silver zone holds markdown text only.

`cmd_chunk` handles this by reconstructing a *minimal ParsedDoc with no section
metadata*. **That precedent does not transfer**: `_build_deterministic_tree()`
builds the tree *from sections*, so a section-less ParsedDoc yields a degenerate,
useless tree. The command must re-parse the raw parent to recover real sections.

### Action

- **files:** `src/knowledge_lake/cli/app.py`
- Add `klake tree-index <parsed_artifact_id> <source_id>`: resolve the parsed
  artifact's `raw_document` parent, load its bytes from the raw zone, re-parse via
  the existing parser-fallback chain to obtain a ParsedDoc **with sections**, then
  call `pipeline.tree_index.tree_index(...)`. Print `artifact_id`, `status`,
  `cached`, `cost_usd`. Document in the help text that this re-parses (Docling
  took ~40s on a 19-page PDF) and why — no cheaper path exists while sections are
  unpersisted.
- Fix the silent-empty UX: `tree-search` must distinguish **"no tree index has
  been built"** from **"no matches"**. Check whether any `tree_index` artifact
  exists for the shortlisted documents and say so explicitly, pointing at
  `klake tree-index`.
- **verify:** `klake tree-index doc_019f6393-6ad3-7d22-93cc-19d88b133027
  src_019f6392-54c1-7d73-9442-b02df7d22b9d` creates a tree_index artifact;
  `klake tree-search "energy management"` then returns real hits (it returned
  nothing in the audit). Before indexing, it must say "no tree index", not
  "No results".
- **done:** The tree-retrieval feature is reachable and honest from the CLI.

> Noted, not fixed (record in SUMMARY): parse not persisting sections also means
> `klake chunk` produces chunks with no `section_path`, degrading citations on the
> CLI path. Persisting sections would fix both properly — larger change.

---

## Must haves

- **truths:**
  - No GET route returns 5xx against the real registry.
  - The api container cannot silently serve stale code, or the drift is visible.
  - `klake tree-index` exists and `tree-search` returns hits after it runs.
  - `tree-search` never reports "No results" when the real cause is "no index".
- **artifacts:**
  - `src/knowledge_lake/api/app.py`, `docker-compose.yml`,
    `src/knowledge_lake/cli/app.py`
- **key_links:**
  - `.planning/E2E-GAP-ANALYSIS.md` (KL-18, KL-08, KL-09)
  - `src/knowledge_lake/registry/db.py:82` (session/expire_on_commit)

## Out of scope

- KL-19 (wrong mock target in 4 mode-forwarding tests).
- KL-12, KL-13, KL-14, KL-15, KL-17.
- Persisting parse sections (would fix KL-09 more cheaply and repair `klake chunk`
  citations — larger change, record as follow-up).
- The pack-contributed-jobs extension point (KL-16's deferred gap).
