---
quick_id: 260715-bgt
slug: fix-kl-18-detached-session-500s-kl-08-st
description: Fix KL-18 detached-session 500s, KL-08 stale container, KL-09 tree-index CLI
date: 2026-07-15
status: complete
tasks_completed: 3
addresses: [KL-18, KL-08, KL-09]
commits:
  - fa7d8df  # KL-18 session-scope fix + curated-documents test
  - b5d584e  # KL-08 bind mount, /health version, Dockerfile fixes
  - 7a5c30f  # KL-09 klake tree-index + honest tree-search empty state
  - b974337  # docs/openapi.json regeneration (Rule 3, /health description drift)
tests:
  combined: 956 passed
  failed: 0
  errors: 0
  xpassed: 0
  xfailed: 10
  xfail_strict: true
  new_tests: 11  # 1 curated-documents + 4 tree_index_coverage + 6 cli tree-index/tree-search
---

# Quick Task 260715-bgt — Summary

Closed the last high-severity finding (KL-18) and the two remaining mediums
(KL-08, KL-09) from the original E2E audit. All three verified against the
real running stack and real registry data, not mocks.

## Task 1 — KL-18: three endpoints returning 500 (`fa7d8df`)

`list_documents_endpoint`, `list_datasets_endpoint`, and the curated-documents
list endpoint all built their response DTOs **after** `with get_session()`
closed. `get_session()` commits on clean exit with the SQLAlchemy default
`expire_on_commit=True`, so the first lazy-attribute access on the
now-detached instances raised `DetachedInstanceError` → 500. Moved the
list-comprehension construction inside the session block for all three call
sites — no global `expire_on_commit` change, per the plan's constraint.

Removed the two now-false `xfail(reason="...not yet added")` markers (the
endpoints existed; they were broken, not missing) and added
`test_get_curated_documents_returns_200`, which had **zero** prior coverage
despite failing with the identical bug shape.

**Verified — real app + real registry, before → after:**
```
/documents           500 -> 200
/datasets             500 -> 200
/curated-documents    500 -> 200
```
Re-confirmed against the live containerized API after Task 2's rebuild (not
just the in-process TestClient probe):
```
$ curl localhost:8000/documents          -> 200, real artifacts
$ curl localhost:8000/datasets           -> 200, real artifacts
$ curl localhost:8000/curated-documents  -> 200, real artifacts
```

## Task 2 — KL-08: stale container, invisible drift (`b5d584e`)

**Verified the editable-install assumption before relying on it**, per the
plan's requirement: `uv pip show knowledge-lake` inside the running
container reported `Editable project location: /app` with
`knowledge_lake.pth` containing `/app/src` — so a bind mount over that exact
path is not theatre.

- Added `./src:/app/src:ro` to `api`, `dagster-webserver`, and
  `dagster-daemon` in `docker-compose.yml`.
- `/health` now returns `{"status": "ok", "version": "<pkg>+<git_sha>"}`
  (falls back to bare `<pkg>` when `.git` isn't available inside the image,
  e.g. no git metadata baked into the build — matches `version.py`'s
  documented fallback). `status` unchanged; `version` is additive. Updated
  the two tests that asserted exact dict equality
  (`test_api_lineage.py`, `test_compose_health.py`) and the README's
  documented response.
- README documents `docker compose restart <service>` for src/ edits and
  `docker compose up -d --build` for dependency/Dockerfile changes.

**Mount proof (live, no rebuild):**
```
$ docker compose exec api grep -c "MOUNT VERIFY" /app/src/.../app.py   -> not present
$ <add a marker comment to app.py on the host>
$ docker compose exec api grep -c "MOUNT VERIFY" /app/src/.../app.py   -> present immediately (live bind mount)
$ docker compose restart api          # NO --build
$ curl localhost:8000/health          -> {"status":"ok","version":"0.1.0"}   # process picked it up
$ <removed marker, restarted again to confirm clean state>
```

**Two pre-existing Dockerfile bugs discovered while getting a build to
succeed** (Rule 3 — blocking; needed a successful build to verify the mount
at all):
1. `LICENSE`/`NOTICE` were never `COPY`'d into the image even though
   `pyproject.toml` declares `license-files = ["LICENSE", "NOTICE"]` — `uv
   sync` failed the build outright. Added both to the `COPY` line.
2. A prior drift bump to `python:3.14-slim` (`88116e7`) left the image
   **unbuildable**: greenlet 3.1.1 (transitive via SQLAlchemy) uses CPython
   internals (`_PyInterpreterFrame` layout, `c_recursion_remaining`) that
   changed in 3.14 — a genuine incompatibility, not a missing-wheel problem
   (confirmed: adding `g++`/build tools did not fix it, the C source itself
   doesn't compile against 3.14 headers). Reverted to `python:3.12-slim`,
   matching the project's own `.python-version` and `requires-python
   ">=3.12"`. This explains part of why nobody had rebuilt in 13 days.

After the fix, `api`, `dagster-webserver`, and `dagster-daemon` all rebuilt
and came up healthy; `docker compose ps` shows all 8 services healthy.

## Task 3 — KL-09: tree-search had no producer (`7a5c30f`)

Added `klake tree-index <parsed_artifact_id> <source_id>`. It does **not**
reuse `cmd_chunk`'s minimal-`ParsedDoc` shortcut: `parse()` persists only
`{quality_score, parser_used, title}` into `metadata_` — sections never
survive to the registry — and `_build_deterministic_tree()` builds the tree
**from sections**, so a section-less `ParsedDoc` would yield one degenerate
root node instead of a real tree. The command resolves the parsed
artifact's `raw_document` parent, reloads its bytes from the raw zone, and
re-parses via the same `parse_with_fallback()` chain `klake parse` uses.

Also fixed the silent-empty UX: added `tree_index_coverage()` to
`pipeline/tree_search.py` (factored the stage-1 shortlist logic out of
`tree_search()` into a shared `_shortlist_documents()` helper so the
diagnostic sees the identical candidate set), wired into the CLI's empty-hit
path so "no tree index has been built yet" is reported separately from "the
tree search genuinely found nothing."

**Verified against the real registry, which held zero `tree_index`
artifacts before this task:**
```
$ klake tree-search "energy management"
No tree index has been built yet for query: 'energy management'
  1 document(s) matched but none have a tree_index artifact.
  Run `klake tree-index <parsed_artifact_id> <source_id>` ...

$ klake tree-index doc_019f6393-6ad3-7d22-93cc-19d88b133027 \
                    src_019f6392-54c1-7d73-9442-b02df7d22b9d
Re-parsing raw document to recover sections...
  re-parsed: 38 sections via 'docling' (quality=0.989...)
Tree-indexed:
  status:        tree_indexed
  artifact_id:   idx_019f64ed-6540-7741-8e24-e428e36bcc0e
  cached:        False
real  0m41.9s   # Docling re-parse cost, as the plan anticipated (~40s/19pp)

$ klake tree-search "energy management"
Results for: 'energy management'
  [1] score=2.0000  document: doc_019f6393...  node_path: Chapter 4: Energy
      Management: Mastering Altitude and Airspeed Control
  [2..5] 4 more real hits (Aircraft Energy Management, Importance of Energy
      Management, Primary Energy Role of the Throttle and Elevator, ...)

$ curl localhost:8000/documents?artifact_type=tree_index
[{"id": "idx_019f64ed-...", "artifact_type": "tree_index", ...}]   # was []

# Re-running tree-index is a content-hash no-op:
$ klake tree-index doc_019f6393... src_019f6392...
  status: cached, artifact_id: idx_019f64ed-... (same ID, ~42s re-parse cost
  paid again since sections aren't cached — a known limitation, see below)
```

## Verification (full suite)

```
uv run pytest -m "not browser" -q
  -> 956 passed, 2 skipped, 2 deselected, 10 xfailed, 0 xpassed, 0 failed, 0 errors
  (baseline 945 [943 + 2 markers removed] + 11 new tests added by this task)

uv run ruff check src/
  -> All checks passed!
```

No regression to KL-01 (domain filtering), KL-02 (proxy cost), KL-03
(integration tests in CI), KL-04/05/06 (ordering chain), KL-07 (SSRF
is_global), KL-10 (`xfail_strict = true`, still on, mutation-verified
previously).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] `docs/openapi.json` went stale from the /health
docstring change**
- **Found during:** Task 2, running the full test suite for final verification.
- **Issue:** `test_openapi_json_matches_deterministic_dump` failed —
  the committed OpenAPI spec no longer matched a fresh dump after the
  `/health` endpoint's docstring gained the `version` field description.
- **Fix:** Ran `klake openapi` to regenerate `docs/openapi.json` (the
  project's documented no-op-diff workflow).
- **Files modified:** `docs/openapi.json`
- **Commit:** `b974337`

**2. [Rule 3 - Blocking] Dockerfile never copied LICENSE/NOTICE, breaking
every build**
- **Found during:** Task 2, rebuilding to verify the KL-08 bind mount.
- **Issue:** `pyproject.toml` declares `license-files = ["LICENSE",
  "NOTICE"]`; the Dockerfile's `COPY pyproject.toml uv.lock README.md ./`
  never copied those two files, so `uv sync --no-dev` failed the build with
  "license-files glob ... did not match any files" on every invocation.
- **Fix:** Added `LICENSE NOTICE` to the `COPY` line.
- **Files modified:** `Dockerfile`
- **Commit:** `b5d584e`

**3. [Rule 3 - Blocking] `python:3.14-slim` base image was unbuildable**
- **Found during:** Task 2, same rebuild attempt (after fix #2 above).
- **Issue:** A prior drift commit (`88116e7`) bumped the base image from
  `python:3.12-slim` to `python:3.14-slim`. `greenlet` 3.1.1 (pulled in
  transitively by SQLAlchemy) has no wheel for 3.14 and its C extension
  fails to compile against 3.14's changed internals
  (`_PyInterpreterFrame`, `c_recursion_remaining`/`py_recursion_remaining`
  rename) — a real incompatibility, confirmed by trying `gcc`/`g++`
  toolchain additions first and watching the compile itself fail on the
  API mismatch, not a missing-tool error.
- **Fix:** Reverted to `python:3.12-slim`, matching the repo's own
  `.python-version` (`3.12`) and `pyproject.toml`'s
  `requires-python = ">=3.12"`.
- **Files modified:** `Dockerfile`
- **Commit:** `b5d584e`

No other deviations — Tasks 1 and 3 executed as the plan specified.

## Follow-ups (noted, not fixed — matches plan's "Out of scope")

- **Persisting parse sections** would let `klake tree-index` skip the
  ~40s re-parse (and repair `klake chunk`'s missing `section_path`
  citations too) — larger change, deliberately deferred by the plan.
- KL-19 (wrong mock target, 4 mode-forwarding tests) — untouched, as scoped.
- KL-12, KL-13, KL-14, KL-15, KL-17 — untouched, as scoped.
- The pack-contributed-jobs extension point (KL-16 follow-up) — roadmap.
- `docker compose up -d --build` for `dagster-webserver`/`dagster-daemon`
  now also picks up the same `./src` mount fix as `api` — verified all
  three came up healthy after the rebuild forced by the Dockerfile fixes
  above.

## Known Stubs

None.

## Self-Check: PASSED

All 11 referenced files found on disk; all 4 commit hashes
(`fa7d8df`, `b5d584e`, `7a5c30f`, `b974337`) found in `git log --all`.
