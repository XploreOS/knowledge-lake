---
quick_id: 260715-chy
slug: fix-remaining-low-findings-ci-image-buil
description: Fix remaining low findings, CI image build guard, parse section persistence
date: 2026-07-15
status: complete
tasks_completed: 8
addresses: [KL-12, KL-13, KL-14, KL-15, KL-17, KL-19, "Dockerfile CI build guard", "parse section persistence (KL-09 follow-up)"]
commits:
  # Wave A (mechanical/docs/tests) — executed in a prior session, relayed by the user
  - 2940463  # KL-12 README enrich alias
  - 6ae70a2  # KL-13 CLI help regex rendering
  - d81c9f7  # KL-14 one dst_ ID per export
  - 9a10aec  # KL-17a put_raw docstring
  - 0c52c87  # KL-17 b/c/d drift
  - 1580f97  # KL-19 wrong mock target
  - 72b9413  # Dockerfile CI build guard
  # Wave B (structural) — executed and verified in this session
  - 50e9e1d  # KL-15 sources.domain column + backfill
  - 1c0159f  # parse section persistence (KL-09 follow-up)
tests:
  combined: 971 passed
  failed: 0
  errors: 0
  xpassed: 0
  xfailed: 6
  skipped: 2
  deselected: 2
  xfail_strict: true
  new_tests: 11  # 10 KL-15 (registry/migration) + 1 sidecar-hit CLI test
  baseline_before_this_task: 960
---

# Quick Task 260715-chy — Summary

Closed the last six low-severity findings from the E2E audit, added a CI
guard against the Dockerfile-never-builds landmine, and fixed the parse
persistence root cause that forced KL-09's re-parse workaround and silently
degraded `klake chunk` citations. Executed in two waves: Wave A (mechanical
fixes, Tasks 1-6) ran in a prior session; this session executed and verified
Wave B (structural, Tasks 7-8) against the real running stack and real
registry/S3 data.

## Wave A recap (Tasks 1-6, prior session — commits relayed, not re-verified here)

- **Task 1 (`2940463`) — KL-12:** README corrected to say enrich defaults to
  `cheap_model` (matching `settings.py`), documents the
  `KLAKE_ENRICH__MODEL_ALIAS` override to `strong_model`. Code default
  unchanged (would have raised costs ~9x).
- **Task 2 (`6ae70a2`) — KL-13:** `klake domain new --help` now renders the
  full literal regex `^[a-zA-Z][a-zA-Z0-9_-]{0,63}$` instead of Rich eating
  the character classes as markup. Regex de-duplicated to one definition in
  `domains/scaffold.py`, imported by `cli/app.py`.
- **Task 3 (`d81c9f7`) — KL-14:** Exports now mint one `dst_` ID and use it
  for both the row and the filename — `create_dataset()` gained an optional
  `id` parameter, threaded through all three export functions.
  `get_or_create_dataset()` unchanged.
- **Task 4 (`9a10aec`) — KL-17a:** `put_raw()`'s docstring corrected to the
  real key layout `raw/{domain}/{source_id}/{sha256}.{ext}`.
- **Task 5 (`0c52c87`) — KL-17b/c/d:** Architecture doc corrected to say the
  LLM gateway is LiteLLM by constraint (not a swappable plugin protocol) —
  decided to fix the doc, not build an `LLMGatewayPlugin` abstraction.
  `datasets.py`'s hardcoded `"openai/eval_model"`/`"openai/strong_model"`
  moved to settings fields mirroring `EnrichSettings.model_alias` (same
  defaults, no behavior change). `domains/models.py:78`'s
  "Result from HealthcareValidator" docstring made domain-neutral.
- **Task 6 (`1580f97`, `72b9413`) — KL-19 + Dockerfile CI guard:** The 4
  mode-forwarding tests now patch `knowledge_lake.pipeline.route.search`
  (the seam `routed_search` actually calls) instead of
  `knowledge_lake.pipeline.search.search` (never consulted — the classic
  KL-19 wrong-patch-target bug); xfail markers removed since the tests now
  genuinely pass. CI gained a `docker compose build api` step so an
  unbuildable Dockerfile fails the build instead of rotting unnoticed behind
  a green badge for 13 days (the exact KL-08 root cause) — build-only, no
  push, layer-cached.

## Wave B (Tasks 7-8, this session — executed and independently verified)

### Task 7 — KL-15: `sources.domain` first-class column (`50e9e1d`)

**What changed.** Added Alembic migration `0010_sources_domain_column.py`:
a nullable, indexed `sources.domain` column, backfilled from
`config->>'domain'` via a dialect-agnostic Python loop (SELECT id/config,
per-row UPDATE — avoids JSON-vs-JSONB operator differences between SQLite
unit tests and PostgreSQL). `Source.domain` added to the ORM model.
`get_domain_for_source()` now reads the column first, falling back to the
legacy `config['domain']` blob only as a defensive belt. Both write sites
(`pipeline/ingest.py`'s `register_source` and `pipeline/domains.py`'s
`load_domain`) dual-write the column **and** `config["domain"]` — the blob
write is a deliberate, documented one-release deprecation, not removed here
per the plan's explicit "out of scope."

**Migration round-trip + backfill evidence (real `klake` DB, not a fixture):**

```
$ docker exec ... psql -c "SELECT config->>'domain', count(*) FROM sources GROUP BY 1;"
  (before migration)          functional-medicine: 30   healthcare: 24   null: 14   aviation: 3

$ uv run alembic upgrade head     # 0009 -> 0010
$ docker exec ... psql -c "SELECT domain, count(*) FROM sources GROUP BY 1;"
  (after migration, column)   functional-medicine: 30   healthcare: 24   null: 14   aviation: 3   <- identical

$ docker exec ... psql -c "SELECT id FROM sources WHERE domain IS DISTINCT FROM (config->>'domain');"
  (0 rows — zero column/blob mismatches across all 71 real source rows)

$ uv run alembic downgrade -1     # 0010 -> 0009
  column + index dropped cleanly; config->>'domain' breakdown unchanged (blob untouched)

$ uv run alembic upgrade head     # re-upgrade, reproduced identical backfill
```

`tests/integration/test_migrations.py` (the project's own downgrade-then-
upgrade round-trip test against a wiped `klake_test` DB) also passed: 13
passed, 2 skipped.

**KL-01 non-regression** (domain-scoped export still filters, not just
labels): ran `export_rag_corpus(domain="aviation")` with the two documented
contamination overrides (`doc_019f5773-...`, `doc_019f6394-...`) —

```
{"domain": "aviation", "total": 133, "kept": 51, "filtered_out": 82}
dataset_id: dst_019f6523-63ba-7280-93e6-873acff81356
storage_uri: s3://klake-data/gold/aviation/rag_corpus/dst_019f6523-63ba-7280-93e6-873acff81356.parquet
```

Read the Parquet back with Polars: `(51, 9)` shape, `domain` column is
100% `aviation` — matches KL-01's fixed behavior exactly. `dataset_id`
also equals the ID embedded in `storage_uri` (KL-14 non-regression).

**`klake init --domain aviation` idempotency:** `0 registered, 3 already
registered (dedup), 1 requires manual upload` — matches the 3 real aviation
sources already in the registry.

**New tests (10):** `TestAlembic0010Migration` (3), `TestSourceDomainColumn`
(4), plus 3 added to the existing `get_domain_for_source` test class
(column-first read, config-blob fallback, dual-write). Also added `domain`
to `tests/integration/test_migrations.py`'s `TestSourcesSchema.REQUIRED_COLUMNS`.

### Task 8 — Parse section persistence, KL-09 follow-up (`1c0159f`)

**What changed.** `parse()` now serializes the full `ParsedDoc` (text +
sections + metadata) to a JSON sidecar in the **silver zone** alongside the
existing markdown (`{content_hash}.sections.json`), and records its URI on
the parsed_document artifact's `metadata_["sections_uri"]`. This is the
locked design from the plan: sidecar in S3, not Postgres `metadata_` —
`Section.text` carries the whole document body (Docling populates it), so
persisting sections in the registry's JSON column would duplicate every
document into Postgres. Raw-zone immutability is untouched; this is silver
only.

Added `pipeline.parse.load_parsed_doc()` (rehydrate from the sidecar,
returns `None` — never raises — if no sidecar exists) and
`pipeline.parse.reparse_from_raw()` (the fallback: re-parse the raw parent
through the same parser-fallback chain `klake parse` uses). `cli/app.py`'s
`cmd_chunk` and `cmd_tree_index` both now try the sidecar first and fall
back to re-parsing, echoing which path was taken — never crashes, never
silently drops `section_path`.

**Healing on dedup (Rule 2 — missing critical functionality):** the plan's
own headline proof requires "re-parse the aviation PDF; a sections sidecar
exists" to be demonstrable on real, already-ingested data — but re-parsing
identical raw bytes produces an identical `content_hash`, which hits
`parse()`'s pre-existing registry no-op/dedup branch. Without a fix, that
branch would return early and *never* write a sidecar, permanently stranding
every already-parsed document on the expensive `reparse_from_raw` fallback
forever, defeating the feature for all pre-existing content. Since
`parse()` already re-ran the full parser chain before the hash check, the
in-memory `parsed_doc` is available for free — the dedup branch now
opportunistically writes the sidecar for the existing artifact
(best-effort; a healing failure never turns a successful no-op into an
error). This is the mechanism that made the real before/after proof below
possible without ingesting synthetic data.

**Headline proof — real aviation FAA PDF (`doc_019f6393-6ad3-...`, 19pp, 38
sections, pre-Task-8 artifact confirmed to have no `sections_uri`):**

1. **Before healing — both commands fall back and are slow, but work:**
   ```
   $ time klake chunk doc_019f6393-6ad3-... src_019f6392-54c1-...
     "No sections sidecar found ... re-parsing raw document to recover sections..."
     chunk_count: 51        real 0m43.986s

   $ time klake tree-index doc_019f6393-6ad3-... src_019f6392-54c1-...
     "No sections sidecar found ... re-parsing raw document..."
     status: cached          real 0m43.431s
   ```

2. **Heal via `klake parse` (dedup hit + sidecar backfill):**
   ```
   $ time klake parse doc_019f6392-ce6b-... src_019f6392-54c1-...
     "parse.no_op" existing_artifact_id=doc_019f6393-6ad3-...
     "parse.healed_sections_sidecar"
       sections_uri=s3://klake-data/silver/aviation/.../f0d528da....sections.json
     real 0m42.263s (Docling re-parse cost is unavoidable to obtain
                     the in-memory ParsedDoc for healing)
   ```
   Verified directly: Postgres `artifacts.metadata` now includes
   `"sections_uri"`; the S3 object exists (98,990 bytes, 38 sections,
   confirmed via `storage.exists()` + `orjson.loads()`).

3. **After healing — same artifact, same commands, sidecar fast path:**
   ```
   $ time klake chunk doc_019f6393-6ad3-... src_019f6392-54c1-...
     "Using persisted sections sidecar (38 sections)."
     chunk_count: 51 (identical chunk IDs — dedup preserved)   real 0m1.453s

   $ time klake tree-index doc_019f6393-6ad3-... src_019f6392-54c1-...
     "Using persisted sections sidecar (38 sections) — no re-parse needed."
     status: cached                                             real 0m1.429s
   ```
   **~43s -> ~1.4s**, ~30x faster, identical correctness.

4. **`klake tree-search "energy management"`** still returns real,
   section-aware hits (5 results, real `section_path`/`node_path` values
   like "§16 Two Energy Management Scenarios").

5. **Clean in-memory before/after on the exact same document** (no registry
   writes, isolates the citation-quality claim from dedup mechanics): built
   raw chunks from the literal pre-Task-8 `cmd_chunk` reconstruction
   (`ParsedDoc(text=parsed_text, sections=[])`) vs the Task-8
   sidecar-rehydrated `ParsedDoc`, both fed through the same
   `_build_token_chunks()`:
   ```
   BEFORE (old cmd_chunk, section-less ParsedDoc):
     chunk_count: 1          distinct section_path values: ['§1']
   AFTER (Task 8, sidecar-rehydrated real sections):
     chunk_count: 51         distinct section_path count: 51
   ```
   The old CLI path didn't just leave `section_path` empty — it collapsed
   the entire 19-page, 38-section document into **one monolithic chunk**
   under a single degenerate `§1` tag, losing all citation granularity.

6. **Old-artifact fallback proof, second real document:** the HHS Security
   Rule fixture (`doc_019f5bdb-74b3-...`, already parsed pre-Task-8, no
   sidecar) went through the identical heal-then-fast-path sequence — 11s
   heal, then 1.4s chunk with sidecar hit, 4/4 real sections — confirming
   the healing mechanism generalizes beyond the one document used for the
   detailed proof above.

**KL-01/KL-04/05/06/KL-18 non-regression (re-checked after Task 8):**
`klake search "energy management" --min-quality-score 0.5` still returns
scored hits (0.797 composite quality). The provided route probe
(`all_routes_probe.py`) shows `BROKEN ROUTES: none` across every GET route
against the real registry.

**New/modified tests:** `tests/unit/test_parse_silver_key.py`'s two domain-
segment tests updated for 2 `put_object` calls (markdown + sidecar) instead
of 1. `tests/unit/test_cli_tree_index.py`'s `test_reparse_recovers_sections_...`
updated to patch `knowledge_lake.pipeline.parse.StorageBackend`/
`.parse_with_fallback` (not the defining modules) — the exact KL-19 lesson:
`reparse_from_raw()` binds both names at `pipeline.parse`'s own
module-import time, so patching the defining module never takes effect.
Added `test_sidecar_hit_skips_reparse` (new) proving the fast path is
actually taken when a sidecar exists.

## Verification (full suite, both waves combined)

```
uv run pytest -m "not browser" -q
  -> 971 passed, 2 skipped, 2 deselected, 6 xfailed, 0 xpassed, 0 failed, 0 errors
  (baseline 960 + 11 new tests, all from Task 7/8 — Wave A's own new tests
   are already folded into the 960 baseline from the prior session)

uv run ruff check src/
  -> All checks passed!
```

No regression to KL-01 (domain filtering — re-verified live), KL-02 (proxy
cost, untouched), KL-03 (CI integration tests, untouched), KL-04/05/06
(ordering chain — re-verified live via `--min-quality-score`), KL-07 (SSRF,
untouched), KL-10 (`xfail_strict = true` — 0 xpassed confirms it's still
enforcing), KL-18 (no 5xx — re-probed with the provided script, `BROKEN
ROUTES: none`).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Dedup no-op path now heals pre-Task-8
parsed artifacts missing a sections sidecar**
- **Found during:** Task 8, attempting to produce the plan's own required
  proof ("re-parse the aviation PDF; a sections sidecar exists in the
  silver zone") against the real, already-parsed aviation document.
- **Issue:** `parse()`'s content-hash dedup branch returns early on
  identical content without ever reaching the sidecar-write code —
  meaning every already-parsed document in the registry (all of them, pre-
  Task-8) would be permanently stuck on the expensive `reparse_from_raw`
  fallback forever, since re-running `klake parse` on them is the
  documented recovery path and it would be a silent no-op.
- **Fix:** The dedup branch now writes the sidecar for the existing
  artifact (using the `parsed_doc` already produced by the re-run above the
  dedup check) when its `metadata_` lacks `sections_uri`. Best-effort —
  wrapped in `try/except`, never turns a successful no-op into an error.
- **Files modified:** `src/knowledge_lake/pipeline/parse.py`
- **Verification:** real `klake parse` re-run on the aviation PDF and the
  HHS fixture both healed correctly (see Task 8 proof above); registry
  `metadata_` and S3 sidecar object confirmed for both.
- **Commit:** `1c0159f` (part of the Task 8 commit)

**2. [Rule 1 - Bug] Pre-existing tests patched a target `parse_with_fallback`/
`StorageBackend` reference that Task 8's refactor made unreachable**
- **Found during:** Task 8, running the existing test suite after moving
  `cmd_tree_index`'s re-parse logic into `pipeline.parse.reparse_from_raw()`.
- **Issue:** `test_reparse_recovers_sections_and_calls_tree_index` patched
  `knowledge_lake.plugins.resolver.parse_with_fallback` and
  `knowledge_lake.storage.s3.StorageBackend` — worked before because
  `cli/app.py` did local (call-time) imports of both names, but
  `pipeline.parse` imports both at module-import time, so the patch target
  never took effect once the logic moved (the exact KL-19 wrong-seam
  pattern, this time self-inflicted by the refactor rather than pre-
  existing).
- **Fix:** Repointed both patches to `knowledge_lake.pipeline.parse.*`.
- **Files modified:** `tests/unit/test_cli_tree_index.py`
- **Verification:** test passes; added a second test
  (`test_sidecar_hit_skips_reparse`) proving the opposite path is also
  exercised correctly.
- **Commit:** `1c0159f` (part of the Task 8 commit)

**3. [Rule 1 - Bug] Domain-segment silver-key tests asserted exactly 1
`put_object` call**
- **Found during:** Task 8, running the existing test suite after adding
  the sections sidecar write.
- **Issue:** `parse()` now writes 2 objects (markdown + sidecar) per call;
  `TestParseSilverKeyDomain`'s two tests asserted `len(captured_keys) == 1`.
- **Fix:** Updated both tests to expect 2 calls, split into `.md` and
  `.sections.json` keys, and assert the domain segment appears in both.
- **Files modified:** `tests/unit/test_parse_silver_key.py`
- **Verification:** both tests pass.
- **Commit:** `1c0159f` (part of the Task 8 commit)

---

**Total deviations (Wave B):** 3 auto-fixed (1 missing critical, 2 bug
fixes to keep the existing suite honest about the new behavior).
**Impact on plan:** All three were necessary either for the feature to
actually help pre-existing data (deviation 1) or to keep the test suite
truthful about the refactor (deviations 2-3). No scope creep — the locked
sidecar-in-S3 design was followed exactly; `config["domain"]` dual-write was
kept per the plan; export filtering was not rewritten into SQL.

## Known Stubs

None.

## Follow-ups (noted, not fixed — out of scope per the plan)

- **`config["domain"]` dual-write deprecation** — both write sites
  (`register_source`, `load_domain`) still write `config["domain"]`
  alongside the new `sources.domain` column, as the plan explicitly
  requires ("keep writing `config["domain"]` for one release"). A future
  quick task should remove the blob write once nothing reads it directly
  (only `get_domain_for_source()`'s defensive fallback and
  `list_sources_for_crawl_all()` still read the blob).
- **`list_sources_for_crawl_all()`** still filters `Source.config` in
  Python rather than using the new indexed column — explicitly out of scope
  per the plan ("Do not attempt to make export filtering a SQL WHERE
  clause in this task").
- **Sidecar healing is best-effort only on re-parse** — a document that is
  never re-parsed (no one calls `klake parse` on it again) stays on the
  `reparse_from_raw` fallback forever. A one-off backfill script that walks
  all parsed_document artifacts missing `sections_uri` and heals them in
  bulk would remove the fallback path's cost entirely; not built here
  (would require re-parsing dozens of documents at ~10-45s each, well
  beyond this task's scope).

## Self-Check: PASSED

All referenced files found on disk (`src/knowledge_lake/registry/alembic/versions/0010_sources_domain_column.py`,
`src/knowledge_lake/pipeline/parse.py`, `src/knowledge_lake/cli/app.py`,
`src/knowledge_lake/registry/models.py`, `src/knowledge_lake/registry/repo.py`).
All Wave B commit hashes (`50e9e1d`, `1c0159f`) found in `git log --all`.
Wave A commit hashes (`2940463`, `6ae70a2`, `d81c9f7`, `9a10aec`, `0c52c87`,
`1580f97`, `72b9413`) relayed by the user as already committed — not
independently re-verified in this session per the task instructions, but
all appear in `git log --oneline` at the expected position preceding this
session's work.
