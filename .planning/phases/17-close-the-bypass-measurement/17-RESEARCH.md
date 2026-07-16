# Phase 17: Close the Bypass + Measurement - Research

**Researched:** 2026-07-16
**Domain:** Retrofitting a lineage-tracked cleaning stage onto an already-shipped Dagster + CLI RAG pipeline; forward-only content-hash convention repair; measurement-harness design under a "no separate frozen classifier" constraint.
**Confidence:** HIGH on mechanism (every claim below is grounded to file:line in this repo, read fresh this session, or inherited from `.planning/research/SUMMARY.md`'s HIGH-confidence, code-executed findings). LOW on the numeric baseline this phase's audit will print (see Open Questions — the original 28% figure was measured at chunk granularity across categories this phase does not yet gate).

## Summary

This phase's job is narrower and higher-risk than "wire cleaning in." The clean stage runs (`clean()`) and already produces a correct `cleaned_document` artifact — but three consumers (`chunk_document`, `tree_index_document`, `enrich_document`) all destructure the **same dict key**, `clean_document["parsed_doc"]`, and today that key holds the original, uncleaned in-memory `ParsedDoc` forwarded verbatim from the `parsed_document` asset (`assets.py:325`). `klake process` (`pipeline/process.py::process_crawled`) is worse: it has no clean stage at all — `parse → chunk → embed → index` (`process.py:103-112`) — so the 28%-garbage audit that motivated this milestone measured a code path that never called `clean()`. Both paths must change in this phase, not just the Dagster asset (CLEAN-01, CLEAN-02).

The mechanical fix is a **single-value swap**, not a rewire: because all three downstream Dagster assets already read `clean_document["parsed_doc"]`, replacing what that key holds — from the raw `ParsedDoc` to a cleaned `ParsedDoc` — requires editing only `clean_document` itself. Zero changes to `chunk_document`, `tree_index_document`, or `enrich_document`. This is the concrete answer to CONTEXT.md's D-01 (threading approach): **replace-in-dict**, not a new key.

The harder problem is that `clean()` today cleans a *flat markdown blob* (`parsed_doc.text`, read back from S3), while `chunk()` and `tree_index()` consume **`ParsedDoc.sections`** (a structured list read from a separate JSON sidecar `parse()` already writes). These are two different representations of the same document. To satisfy CLEAN-01's acceptance criterion ("`chunk_document` receives sections with boilerplate removed"), `clean()` must apply `remove_boilerplate()` **per-section**, not just to the flattened blob — but it must do this without duplicating CLEAN-04's full section-classifier/annotation work, which is explicitly scoped to Phase 19. The correct Phase-17-sized cut: mutate each `Section.text` in place with the existing (today: 4, this phase: still 4 — pattern strengthening is Phase 19's CLEAN-05) `BOILERPLATE_PATTERNS`, but **do not drop sections from the list**. Section removal (`CLEAN-04`: "retains only clinical sections") is explicitly a Phase 19 deliverable; doing it now would (a) scope-creep into Phase 19's acceptance criteria and (b) silently degrade `tree_index_document`, which shares the identical section list and needs heading-only sections for its outline even when their body text is empty.

CLEAN-03 (the WR-05 hash fix) is not cosmetic — it closes a **dormant, activating** lineage-corruption bug. `clean.py:232` today hashes `sha256(cleaned_bytes)` with no parent scoping, behind a `UNIQUE(content_hash, artifact_type)` constraint (`models.py:153`). `chunk.py:317` already fixed this exact class of bug for chunks (`f"{parsed_artifact_id}:{text}"`) with an explicit WR-05 comment — `clean.py` was left on the old, dangerous convention. Today this is harmless because nothing on the RAG path reads the cleaned artifact's content. The moment CLEAN-01 ships, it stops being harmless: two thin documents that reduce to identical cleaned text (a very real case — many of the audit's worst sources are landing pages whose only content is nav+title) will collide, and `clean()`'s existing exact-dup short-circuit (`clean.py:305-320`) will hand one document a **different document's artifact**. CLEAN-01 and CLEAN-03 must ship in the same phase, non-negotiably — this is already reflected in the phase's requirement bundle.

MEAS-01's "quality-audit" sits on top of a genuine tension the user has explicitly resolved: `.planning/research/SUMMARY.md` (this project's own prior researcher output, HIGH confidence) argued strongly for a **frozen classifier independent of the gate**, warning that using "the pipeline IS the measurement" makes the metric definitionally circular as gates improve. CONTEXT.md's D-07 locks the opposite choice: **no separate classifier, the real pipeline's own kept/rejected counts are the measurement**, with D-10 explicitly accepting the consequence ("what counts as rejected evolves as gates improve — that's the point; the FORMULA doesn't"). This is a user decision already made — research does not re-litigate it — but it means this phase's own quality-audit will legitimately show close to **zero rejections** for every source, because Phase 17 intentionally does not drop any sections. That is not a bug in the audit; it is what "establish the measurement baseline before the gates arrive" looks like when the gate itself is a no-op by design. Flagged explicitly in Open Questions so the acceptance-criteria wording ("28% baseline is reproducible," borrowed from a QUAL-04/MEAS-01 acceptance line that is *milestone*-level, not *phase-17*-level) doesn't get misread as a Phase 17 gate requirement.

**Primary recommendation:** Give `clean()` an optional in-memory `parsed_doc: ParsedDoc | None` parameter (populated by both callers, who already hold it in memory — zero new S3 reads), have it return a `cleaned_doc: ParsedDoc` in its result dict (sections boilerplate-stripped in place, list untouched), swap `clean_document["parsed_doc"]` to that value, insert one `clean()` call into `process_crawled` between `parse()` and `chunk()`, switch `clean.py`'s hash computation to the WR-05 `f"{parsed_artifact_id}:{cleaned_text}"` convention, and stamp `sections_considered/kept/rejected/rejection_reasons` onto the cleaned artifact's `metadata_` (no new table, no migration) computed unconditionally on every call (including the exact-dup short-circuit) so a CLI `quality-audit` command can recompute them live and print a per-source table without needing persisted history to be complete.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Boilerplate text removal (CLEAN-01/02) | API/Backend (pipeline module `clean.py`) | Orchestration (Dagster asset wrapper) | `clean()` is a pure backend pipeline function; Dagster and the CLI are both thin callers — logic must not duplicate into either caller (existing project convention, every asset docstring says "no logic duplicated"). |
| In-memory cleaned-doc forwarding (CLEAN-01) | Orchestration (Dagster asset graph) | API/Backend | The *value* forwarded between assets is an orchestration-graph concern; the *content* of that value is computed by the backend. |
| CLI parity for `klake process` (CLEAN-02) | API/Backend (`pipeline/process.py`) | — | `process_crawled` is the single implementation shared by CLI/API/MCP (D-05, MCP-01 per module docstring) — fixing it here fixes all three surfaces at once. |
| Content-hash / lineage identity (CLEAN-03) | Database/Storage (registry `content_hash` column + `UNIQUE` constraint) | API/Backend (hash computation in `clean.py`) | The hash is a database-integrity concern (prevents cross-row corruption under a UNIQUE constraint); the *computation* lives in the backend pipeline module, matching the existing WR-05 precedent in `chunk.py`. |
| Rejection recording (QUAL-04) | Database/Storage (artifact `metadata_` JSON) | API/Backend | Recommendation: reuse the existing `cleaned_document.metadata_` JSON column (already the idiom for `language`/`dedup_status`) rather than a new table — see Architecture Patterns. |
| Conservation invariant (QUAL-05) | API/Backend (`clean.py`, in-process) | Orchestration (structured log surfaced via Dagster/CLI output) | A per-call arithmetic check computed where the counts already exist; no new infrastructure tier needed. |
| Quality-audit harness (MEAS-01) | API/Backend (new pipeline function) + CLI (Typer command) | Database/Storage (reads `Source.domain`, `Artifact.metadata_`) | Matches the existing `klake lineage` / `klake reindex` idiom: a CLI command that does read-heavy DB+S3 work and prints a table — no new API/service tier required for a phase-17-sized deliverable. |

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| CLEAN-01 | Close the Dagster bypass — forward cleaned ParsedDoc | Replace-in-dict design at `assets.py:276-335`; per-section (not flat-text) cleaning required because `chunk()`/`tree_index()` consume `.sections`, not `.text`. See Architecture Patterns Pattern 1. |
| CLEAN-02 | Close the `process_crawled` bypass — add clean stage | Insert `clean()` call at `process.py:103` between `parse()` and `chunk()`; `clean()` needs the in-memory `parsed_doc` threaded the same way as the Dagster caller for parity (D-02). See Architecture Patterns Pattern 1 and Code Examples. |
| CLEAN-03 | Parent-scoped content hash in `clean()` | Direct WR-05 precedent at `chunk.py:317` (`f"{parsed_artifact_id}:{text}"`); `clean.py:232` currently unscoped. See Common Pitfalls #1 and Code Examples. |
| QUAL-04 | Rejection recording and garbage-rate metric | Recommend `cleaned_document.metadata_` additive keys (no migration) computed unconditionally (including on the exact-dup short-circuit path) so the audit never reads stale/missing data. See Architecture Patterns Pattern 2. |
| QUAL-05 | Conservation invariant | `rejected + kept == sections_considered` computed where section iteration already happens in `clean()`; must separately flag `sections_considered == 0` as a distinct anomaly (broken parser) per the acceptance criterion. See Code Examples. |
| MEAS-01 | Quality audit harness | New `klake quality-audit` Typer command; source count must be read from `Source.domain` (first-class column, KL-15), not `domains/healthcare/sources.yaml` (28 entries) or the legacy `Source.config["domain"]` scan — see Open Questions on the 28-vs-34 discrepancy. |

## Standard Stack

### Core

No new libraries. This phase is a pure retrofit against libraries already installed and pinned in `.claude/CLAUDE.md`'s stack table — `hashlib` (stdlib) for the hash-convention fix, the existing `pipeline.clean`/`pipeline.chunk`/`pipeline.parse` modules, SQLAlchemy/Alembic if a new table is chosen (not recommended — see below), and Typer for the CLI command. `.planning/research/SUMMARY.md` (HIGH confidence, executed against pinned versions) independently reached the same "add nothing, wire what exists" verdict for the whole v2.6 milestone; Phase 17 is the layer where that verdict is strongest.

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `dataclasses.replace` (stdlib) | 3.12 | Build a cleaned `Section`/`ParsedDoc` copy without mutating the original in-memory object the caller still holds | If the planner decides sections must not be mutated in place (e.g. to keep the original `parsed_doc` available for tree_index's future weaker filter). In-place mutation is simpler and sufficient for Phase 17 since `Section`/`ParsedDoc` are plain (non-frozen) dataclasses — either works; prefer whichever the planner's chosen threading design (D-01) makes more natural. |
| `structlog` | (pinned, already used throughout `clean.py`) | Structured logging for the conservation invariant and rejection reasons | Already the established pattern (`log = structlog.get_logger(__name__)` at `clean.py:36`) — reuse, do not introduce a second logging convention. |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Reuse `cleaned_document.metadata_` JSON for rejection counts (QUAL-04) | A new Postgres table (e.g. `quality_rejection_events`, following the `LlmSpend` model precedent at `models.py:420-450`) | A new table gives you queryable per-section rejection *rows* (useful once Phase 19/20 add real per-section reasons with volume). For Phase 17's near-zero rejection counts, a table is premature infrastructure — `metadata_` is free, requires no Alembic migration (next revision would be `0011`), and matches how `language`/`dedup_status` are already recorded on the same artifact. Revisit in Phase 19/20 if per-section audit granularity is needed beyond aggregate counts. |
| Single parent-scoped hash for both S3 key and registry identity (mirrors `chunk.py:317`/`339` exactly) | Two-hash split: content-only hash for the S3 key (dedupe storage bytes across documents), parent-scoped hash for the registry `content_hash` column (dedupe identity) | The two-hash split (suggested in `.planning/research/SUMMARY.md` Pitfall 1) saves S3 storage bytes when many documents reduce to byte-identical cleaned text, at the cost of diverging from the one established, working precedent in this codebase (`chunk.py`) and adding a second hash to reason about in an already-declared "highest-risk" phase. Recommend the single-hash approach for Phase 17 (matches D-04's literal wording, matches `chunk.py`) and leave storage-level dedup as a documented future refinement, not a Phase 17 requirement. |

**Installation:** None required.

**Version verification:** N/A — no new packages.

## Package Legitimacy Audit

Not applicable — this phase installs no new external packages. All work is against already-pinned, already-installed libraries (`hashlib` stdlib, existing `structlog`/SQLAlchemy/Typer/Dagster already in the project's dependency tree).

## Architecture Patterns

### System Architecture Diagram

```
                    ┌─────────────────────────────────────────────┐
                    │              BEFORE (the bypass)             │
                    └─────────────────────────────────────────────┘

  parsed_document ──parsed_doc (uncleaned)──┬──────────────────────────────┐
  (Dagster asset)                           │                              │
        │                                   ▼                              ▼
        │                          clean_document              chunk_document /
        │                          (S3 side-effect only:        tree_index_document /
        │                           writes cleaned_document      enrich_document
        │                           artifact + silver blob;      (read parsed_doc — the
        │                           result discarded by caller)   UNCLEANED object)
        │
        ▼
  process_crawled (CLI/API/MCP) ──parse()──▶ chunk() ──▶ embed() ──▶ index()
                                   (no clean() call at all)


                    ┌─────────────────────────────────────────────┐
                    │           AFTER (Phase 17 target)            │
                    └─────────────────────────────────────────────┘

  parsed_document ──parsed_doc (in-memory)──▶ clean_document
  (Dagster asset)                                  │
                                                    │ clean(parsed_artifact_id, source_id,
                                                    │       parsed_doc=parsed_doc, ...)
                                                    │   1. per-section remove_boilerplate()
                                                    │   2. WR-05 parent-scoped content_hash
                                                    │   3. kept/rejected/considered counted
                                                    │      + stamped on metadata_
                                                    ▼
                                     clean_document["parsed_doc"] = cleaned_doc
                                     (SAME dict key, cleaned VALUE — no downstream
                                      asset code changes required)
                                                    │
                        ┌───────────────────────────┼───────────────────────────┐
                        ▼                           ▼                           ▼
                 chunk_document            tree_index_document           enrich_document
             (sections boilerplate-      (same sections — heading      (already reads cleaned
              stripped; chunk artifacts   outline preserved even        text via cleaned_artifact_id;
              still parent to              for emptied-text sections)   unaffected, verify only)
              parsed_artifact_id,
              never re-parent to
              cleaned_artifact_id)

  process_crawled: parse() ──▶ clean(parsed_id, src_id, parsed_doc=parsed_doc) ──▶
                    chunk(parsed_id, src_id, cleaned_doc) ──▶ embed() ──▶ index()
                    (full parity with the Dagster graph — same clean() call,
                     same cleaned_doc threaded to chunk())

  klake quality-audit (new CLI command):
    for source in sources where Source.domain == "healthcare":
      for raw_document in source's raw docs:
        parse_result, parsed_doc = parse(...)        # idempotent no-op if already parsed
        clean_result = clean(..., parsed_doc=parsed_doc)  # idempotent; ALWAYS recomputes
                                                            # kept/rejected/considered fresh,
                                                            # even on the exact-dup short-circuit
        accumulate clean_result["sections_kept"/"rejected"/"considered"/"rejection_reasons"]
    print per-source table: sections_considered, kept, rejected, reasons, garbage_rate
```

### Recommended Project Structure

No new files required for CLEAN-01/02/03/QUAL-04/QUAL-05. One new CLI command function for MEAS-01:

```
src/knowledge_lake/
├── pipeline/
│   ├── clean.py            # MODIFY: add parsed_doc param, cleaned_doc return,
│   │                        #         WR-05 hash, kept/rejected/considered counting
│   ├── process.py           # MODIFY: thread clean() between parse() and chunk()
│   └── quality_audit.py     # NEW (optional): extracted audit-aggregation function,
│                             #    following the process.py precedent of "one function,
│                             #    many callers" if the audit needs to be reachable from
│                             #    CLI + API later. For Phase 17, inlining in cli/app.py's
│                             #    new command is also acceptable (D-05 discretion) — but
│                             #    a separate module keeps parity with process.py's D-03
│                             #    precedent if API/MCP exposure is anticipated soon.
├── dagster_defs/
│   └── assets.py             # MODIFY: clean_document's result dict — one value swap
└── cli/
    └── app.py                # MODIFY: new @app.command(name="quality-audit")
```

### Pattern 1: Replace-in-dict threading (D-01 resolution)

**What:** `clean_document["parsed_doc"]` is read by three separate Dagster assets (`chunk_document` at `assets.py:372`, `tree_index_document` at `assets.py:501`, `enrich_document` at `assets.py:433`) via the exact same dict access. Swapping the *value* stored under that key from the raw to the cleaned `ParsedDoc` requires editing only the `clean_document` asset function — none of its three consumers need to change.

**When to use:** Any time an existing dict key already fans out to multiple consumers and the fix is "consumers should see different content," not "consumers should see additional content."

**Example:**
```python
# Source: src/knowledge_lake/dagster_defs/assets.py:276-335 (read this session)
def clean_document(
    parsed_document: dict[str, Any],
    postgres: PostgresResource,
    minio: MinIOResource,
) -> dict[str, Any]:
    from knowledge_lake.pipeline.clean import clean

    parsed_artifact_id = parsed_document["artifact_id"]
    source_id = parsed_document["source_id"]
    collection = parsed_document.get("collection", DEFAULT_COLLECTION)
    parsed_doc = parsed_document["parsed_doc"]   # in-memory, already available

    settings = Settings(...)  # unchanged

    # CHANGED: thread the in-memory doc in, get a cleaned doc back
    clean_result = clean(
        parsed_artifact_id, source_id,
        parsed_doc=parsed_doc,      # NEW kwarg — avoids re-fetching from S3
        settings=settings,
    )

    result = {
        "artifact_id": clean_result["artifact_id"],
        "source_id": source_id,
        "collection": collection,
        "parsed_artifact_id": parsed_artifact_id,
        "parsed_doc": clean_result["cleaned_doc"],  # CHANGED: was `parsed_doc` (uncleaned)
        "language": clean_result["language"],
        "dedup_status": clean_result["dedup_status"],
    }
    return result
```
No changes needed to `chunk_document`, `tree_index_document`, or `enrich_document` — they already do `doc = clean_document["parsed_doc"]`.

### Pattern 2: Metadata-column rejection recording (no migration)

**What:** `create_cleaned_artifact()` already accepts a `metadata` dict persisted to `Artifact.metadata_` (JSON column) — currently populated with `language`, `dedup_status`, `minhash_num_perm` (`clean.py:340-344`). Add `sections_considered`, `sections_kept`, `sections_rejected`, `rejection_reasons` (a `dict[str, int]`) to that same dict. No Alembic migration required.

**When to use:** Per-document aggregate counts that need to survive a process restart and be queryable per-source, but do not need per-section row-level detail (that's a Phase 19/20 decision once real substance-gate volume exists).

**Example:**
```python
# Illustrative — follows the existing create_cleaned_artifact() call shape
# at clean.py:333-345
artifact = registry_repo.create_cleaned_artifact(
    session,
    source_id=source_id,
    parent_artifact_id=parsed_artifact_id,
    content_hash=content_hash,
    storage_uri=cleaned_uri,
    mime_type="text/markdown",
    metadata={
        "language": language,
        "dedup_status": dedup_status,
        "minhash_num_perm": s.clean.minhash_num_perm,
        # NEW (QUAL-04, QUAL-05):
        "sections_considered": sections_considered,
        "sections_kept": sections_kept,
        "sections_rejected": sections_rejected,
        "rejection_reasons": rejection_reasons,  # e.g. {"empty_after_boilerplate_removal": 2}
    },
)
```

Critically, **compute these counts unconditionally** — including on the exact-dup early-return path (`clean.py:305-320`) — from the in-memory `parsed_doc`/`cleaned_doc`, not from what happens to already be persisted on the existing artifact. Otherwise a `quality-audit` re-run against already-cleaned documents (the common case — clean() is idempotent) would read stale or absent counts for anything cleaned before this phase's code shipped.

### Anti-Patterns to Avoid

- **Dropping sections whose text goes empty after boilerplate stripping:** This is CLEAN-04's job (Phase 19, explicit acceptance criterion: "retains only clinical sections"). Doing it in Phase 17 double-books that acceptance criterion into this phase and silently starves `tree_index_document`, which shares the exact same section list and wants heading-only sections preserved for its outline.
- **Re-parenting chunks to the cleaned artifact:** `chunk()` must keep parenting to `parsed_artifact_id` (unchanged). Re-parenting breaks `index.py`'s `get_enriched_artifact_for_parsed` walk (parsed→cleaned→enriched), `export.py`'s equivalent walk, and the fail-closed contamination gate — all of which resolve ancestry starting from `parsed_artifact_id`. `.planning/research/SUMMARY.md`'s Architecture section already grounded this exhaustively (HIGH confidence); this phase's design (in-memory dict-value swap) doesn't touch parentage at all, which is the point.
- **Re-reading the cleaned blob from S3 to recover sections:** `clean()`'s exact-dup early return can hand back a *different document's* artifact today (the CLEAN-03 bug). Re-reading that artifact's S3 blob to reconstruct sections would convert a dedup optimization into silent cross-document content substitution. Always thread the caller's own in-memory `parsed_doc` through instead.
- **Bare `assert` for the QUAL-05 conservation invariant:** `python -O` strips bare `assert` statements at the interpreter level; this codebase's `pipeline/*.py` modules contain zero bare `assert` statements today (verified by grep this session) — the established idiom is `structlog` + an explicit raised exception. Match that convention; do not introduce the first bare `assert` in pipeline code for a check this important.
- **Hardcoding "34" as the expected row count in `quality-audit`:** See Open Questions — the domain pack's `sources.yaml` currently defines 28 entries, not 34. The audit must count and report whatever is actually registered under `Source.domain == "healthcare"` at run time, not assert a fixed row count.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Recovering section structure for a `parsed_document` artifact | A new S3-sidecar reader | `load_parsed_doc()` / `reparse_from_raw()` (`pipeline/parse.py:265-395`) — already handle the "no sidecar" fallback | Already built, already used by `cli/app.py`'s `klake chunk`/`klake tree-index` commands. `clean()` does not need this if the caller already has `parsed_doc` in memory (the load-bearing-path case); it's the fallback for a `parsed_doc`-less caller only. |
| Per-source domain filtering for the audit | A third parallel "read `Source.config['domain']`" implementation | `Source.domain` first-class indexed column (migration `0010`) | Two domain-filter code paths already exist and disagree in freshness (`get_domain_for_source` checks the new column first with a JSON fallback; `list_sources_for_crawl_all` only reads the legacy JSON field). Don't add a third variant — query `Source.domain` directly for new code, matching `get_domain_for_source`'s precedence. |
| Idempotent re-processing safety for the audit's repeated `parse()`/`clean()`/`chunk()` calls | A "skip if already processed" check in the new audit command | The existing content-hash dedup built into `parse()`, `clean()`, `chunk()` (all check `get_artifact_by_hash()` before writing) | Re-running the real pipeline for the audit (D-07's locked decision) is only safe/cheap *because* every stage already short-circuits on hash match. No new caching layer needed — this is a designed property of the existing dedup pattern, not something Phase 17 introduces. |

**Key insight:** Every piece of infrastructure this phase needs to reference (section rehydration, domain filtering, idempotent dedup) already exists in the codebase in a working, tested form. The entire phase is genuinely "make three call sites read/write the right values," not "build new machinery" — which is exactly why `.planning/research/SUMMARY.md` independently reached "add nothing, wire what exists" for this whole milestone, and why this phase in particular is flagged as the highest-*risk*, lowest-*build* phase: the risk is entirely in getting the wiring precisely right (parentage, hash scoping, unconditional counting), not in writing new code.

## Common Pitfalls

### Pitfall 1: The WR-05 hash fix and the bypass fix are two variables that must ship together, but must not be conflated in testing
**What goes wrong:** A plan that fixes CLEAN-01/02 (forward cleaned text) without CLEAN-03 (parent-scope the hash) activates a **dormant lineage-corruption bug**: `clean.py:232`'s unscoped `sha256(cleaned_bytes)` behind `UNIQUE(content_hash, artifact_type)` means two documents whose cleaned text happens to collide (very plausible — thin landing pages that reduce to near-nothing after boilerplate stripping) will make `clean()`'s exact-dup path (`clean.py:305-320`) return one document's artifact to the other caller. Once the RAG path actually reads that artifact's content (post-CLEAN-01), the corruption becomes visible in the wrong place.
**Why it happens:** The bug already exists in `clean.py` today; it's inert only because nothing on the load-bearing path reads cleaned content yet. CLEAN-01 is precisely the change that makes it live.
**How to avoid:** Ship CLEAN-01/02 and CLEAN-03 in the same commit/plan-wave, not sequenced. A test asserting "two documents with identical cleaned text get distinct `content_hash` values" (CLEAN-03's literal acceptance criterion) should exist and pass *before* CLEAN-01's forwarding change is considered done, since CLEAN-01's own correctness (each document gets its own cleaned artifact) depends on it.
**Warning signs:** Any test fixture using near-identical or trivially-short "boilerplate-heavy" source documents (a common test-authoring shortcut) will silently share one `cleaned_document` artifact across documents unless CLEAN-03 lands first — producing tests that pass for the wrong reason (identical text was returned, but it was the *other* fixture's artifact).

### Pitfall 2: `clean()`'s current test contract mocks a single `storage.get_object()` call — a naive section-sidecar read would break it
**What goes wrong:** `tests/unit/test_clean_silver_key.py` patches `StorageBackend` with `mock_storage_instance.get_object.return_value = <fixed bytes>` (uniform across all calls) and asserts exactly one `put_object` call. If `clean()` is changed to *always* call `load_parsed_doc()`/`reparse_from_raw()` to recover sections (as `.planning/research/SUMMARY.md` describes for the *general* case), these existing tests break: the mocked bytes aren't valid sidecar JSON, `load_parsed_doc()` returns `None`, and the fallback `reparse_from_raw()` tries to actually run the parser plugin against garbage bytes with no such mocking present in that test file.
**Why it happens:** `SUMMARY.md`'s described flow (`load_parsed_doc()` → `reparse_from_raw()` fallback) is correct for a caller that does *not* already have `parsed_doc` in memory (e.g. a hypothetical standalone `klake clean` re-run) — but both of Phase 17's actual load-bearing callers (`clean_document` asset, `process_crawled`) already hold `parsed_doc` in memory from their own `parse()`/upstream-asset call. Making the *load-bearing path* pay for a sidecar re-read it doesn't need is both wasteful and what breaks the existing test contract.
**How to avoid:** Give `clean()` an **optional** `parsed_doc: ParsedDoc | None = None` parameter. Both load-bearing callers pass it in (zero new S3 reads, existing test contracts for the S3-driven flat-text path untouched). Only fall back to `load_parsed_doc()`/`reparse_from_raw()` when `parsed_doc` is `None` — and even then, only if the planner decides the standalone `klake clean` CLI command needs cleaned-sections output at all (today it doesn't consume its own return value beyond `artifact_id`/`language`/`dedup_status`/`content_hash` — see `cli/app.py:214-234`).
**Warning signs:** Any new test that fails with a JSON decode error or an unexpected call into the real Docling parser plugin when it was only trying to test hash/key construction.

### Pitfall 3: A shared cleaned `ParsedDoc` object across three Dagster consumers is a mutation-aliasing hazard
**What goes wrong:** If `clean_document` builds one cleaned `ParsedDoc` and all three downstream assets receive the *same in-memory object* (true today via the dict-value-swap design, and true before this phase for the uncleaned object too), any one consumer mutating a `Section.text` in place (e.g. a future Phase-19/20 gate that "strips further" at chunk time) would silently corrupt what `tree_index_document` or `enrich_document` sees, depending on Dagster's execution order for parallel fan-out assets — which is not guaranteed to run `chunk_document` before or after `tree_index_document`.
**Why it happens:** `Section` and `ParsedDoc` are plain (non-frozen) dataclasses (`plugins/protocols.py:34-79`) — nothing prevents in-place mutation, and Dagster assets in the same run share Python process memory (no serialization boundary for in-memory-forwarded values, per the existing `Pitfall 7` comment already in `assets.py:287-288`).
**How to avoid:** `clean()` itself should be the *only* place that mutates section text (once, at clean time) — every downstream consumer should treat the `ParsedDoc` it receives as read-only. This is already implicitly the existing convention (chunk/tree_index/enrich all read, never write, `parsed_doc`); Phase 17 does not change this, but the plan should not introduce a mutation into any of the three downstream assets while implementing this phase, and should note the read-only convention explicitly if a plan touches `chunk_document` or `tree_index_document` for any reason.
**Warning signs:** A test that runs `chunk_document` then `tree_index_document` (or vice versa) against the same materialized `clean_document` output and gets different section text depending on call order.

### Pitfall 4: The `Source.domain`-filtered source count for the audit will very likely not be exactly 34 at plan/build time
**What goes wrong:** `domains/healthcare/sources.yaml` (the domain pack's seed catalog) defines **28** source entries today, not 34 (counted this session: `python3 -c "import yaml; print(len(yaml.safe_load(open('domains/healthcare/sources.yaml'))))"` → 28). The original audit's "34 healthcare sources" almost certainly reflects the actual *registered* `Source` rows in a running Postgres instance at audit time (which can exceed the pack's seed catalog via `klake add-source`, crawl discovery, or manual uploads) — not the pack file. A `quality-audit` implementation that reads `sources.yaml` directly, or that asserts `len(sources) == 34`, will not match either the pack (28) or a fresh/different environment's registered count.
**Why it happens:** Domain packs (`sources.yaml`) are a *seed catalog*, not a live inventory. `DomainLoader` (`domains/loader.py`) is the pack-reading path; it is not the same thing as "what's actually in this Postgres instance's `sources` table."
**How to avoid:** Query `Source` rows filtered by `Source.domain == "healthcare"` (the first-class indexed column) at run time; print whatever count is actually returned, and don't hardcode 34 anywhere in code or tests. If the environment the plan will execute against does not yet have 34 registered healthcare sources, that's an environment-setup fact for the plan to surface, not something the audit command should paper over.
**Warning signs:** A test or assertion anywhere with a literal `34` in it tied to source count.

### Pitfall 5: "The pipeline IS the measurement" (D-07) means Phase 17's own quality-audit will show a near-zero garbage rate — this is correct, not a bug
**What goes wrong:** If the acceptance-criteria language "the audit's 28% baseline is reproducible" (from QUAL-04's requirement text, which maps to Phase 17 in the traceability table) is read as "Phase 17's quality-audit command must print ~28% garbage," the plan will chase a number that this phase's own design cannot and should not produce — Phase 17 does not drop any sections (see Anti-Patterns), so `rejected` will be at or near 0 for nearly every source.
**Why it happens:** The original ~28% figure was measured by a one-off, ad-hoc audit script against **chunk-level** categories (too-short, no-real-sentences, exact-dup, boilerplate, marketing — none of which Phase 17's `clean()` gates on; those are QUAL-01/02/03's job in Phases 19/20). Phase 17's contribution is the **harness and the baseline snapshot**, not the fix.
**How to avoid:** Treat "34-row table, reproducible across runs, independent of any gate's heuristic" (this phase's own success criterion #4, verbatim from the phase description) as the actual Phase 17 bar — not the milestone-level 28% number. Document in the plan that Phase 17's baseline numbers are *expected* to be near-zero-rejection, and that meaningful improvement is Phase 19/20's job, measured against this phase's own frozen harness.
**Warning signs:** A plan task phrased as "verify quality-audit shows ~28% garbage" — this will not be true after Phase 17 alone and should not be a Phase 17 acceptance check.

## Code Examples

### Conservation invariant + kept/rejected counting inside `clean()`
```python
# Illustrative — the section-iteration loop clean() needs to add, using the
# existing remove_boilerplate() helper (clean.py:81-90) applied per-section
# instead of only to the flattened parsed_text (clean.py:228 today).
from dataclasses import replace

sections_considered = len(parsed_doc.sections)
cleaned_sections: list[Section] = []
rejection_reasons: dict[str, int] = {}
sections_kept = 0
sections_rejected = 0

for section in parsed_doc.sections:
    cleaned_section_text = remove_boilerplate(section.text)
    cleaned_sections.append(replace(section, text=cleaned_section_text))
    if cleaned_section_text.strip():
        sections_kept += 1
    else:
        sections_rejected += 1
        reason = "empty_after_boilerplate_removal"
        rejection_reasons[reason] = rejection_reasons.get(reason, 0) + 1

# QUAL-05: explicit, non-assert invariant (matches the codebase's zero-bare-assert
# convention in pipeline/*.py, verified this session).
if sections_rejected + sections_kept != sections_considered:
    log.error(
        "clean.conservation_invariant_violated",
        parsed_artifact_id=parsed_artifact_id,
        sections_considered=sections_considered,
        sections_kept=sections_kept,
        sections_rejected=sections_rejected,
    )
    raise RuntimeError(
        f"clean: conservation invariant violated for {parsed_artifact_id!r}: "
        f"{sections_rejected} + {sections_kept} != {sections_considered}"
    )

# QUAL-05's other half — a broken parser (0 sections) must be distinguishable
# from a correct gate that rejected everything (N sections, 0 kept):
if sections_considered == 0:
    log.warning(
        "clean.zero_sections",
        parsed_artifact_id=parsed_artifact_id,
        msg="parser produced zero sections — distinct from a gate rejecting all sections",
    )

cleaned_doc = ParsedDoc(
    text=remove_boilerplate(parsed_doc.text),  # unchanged flat-text behavior (Pitfall 2)
    sections=cleaned_sections,
    metadata=parsed_doc.metadata,
)
```

### WR-05 parent-scoped hash (CLEAN-03)
```python
# Source pattern: chunk.py:315-318 (WR-05, already shipped and tested)
#   hash_input = f"{parsed_artifact_id}:{text}"
#   content_hash = hashlib.sha256(hash_input.encode("utf-8")).hexdigest()
#
# Apply identically in clean.py, replacing the current unscoped line at clean.py:232:
#   BEFORE: content_hash = hashlib.sha256(cleaned_bytes).hexdigest()
#   AFTER:
hash_input = f"{parsed_artifact_id}:{cleaned_text}"
content_hash = hashlib.sha256(hash_input.encode("utf-8")).hexdigest()
cleaned_bytes = cleaned_text.encode("utf-8")  # still used for the S3 put_object body
```

### `process_crawled` parity (CLEAN-02)
```python
# Source: pipeline/process.py:102-116 (read this session) — insert clean() between
# parse() and chunk(), threading parsed_doc through exactly like the Dagster asset.
try:
    parse_result, parsed_doc = parse(raw_id, src_id, mime_type=mime)
    parsed_id = parse_result["artifact_id"]

    clean_result = clean(parsed_id, src_id, parsed_doc=parsed_doc)  # NEW
    cleaned_doc = clean_result["cleaned_doc"]                        # NEW

    chunks_list = chunk(parsed_id, src_id, cleaned_doc)              # CHANGED: was parsed_doc
    if not chunks_list:
        processed += 1
        continue

    vectors, dim = embed(chunks_list)
    index(chunks_list, vectors, dim, parsed_id, collection=collection)

    processed += 1
    total_chunks += len(chunks_list)
except Exception:
    failed += 1
    log.warning("process_crawled: doc %s failed", raw_id, exc_info=True)
```
Note `chunk()` still parents to `parsed_id` (`parsed_artifact_id`), unchanged — only the `doc` argument passed to it changes from the uncleaned to the cleaned `ParsedDoc` (Anti-Patterns: never re-parent to the cleaned artifact).

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|---------------|--------|
| `clean()` returns only artifact metadata (`artifact_id`, `content_hash`, `language`, `dedup_status`, `storage_uri`) — no in-memory document | `clean()` also returns a `cleaned_doc: ParsedDoc` for the caller to forward in-memory | This phase | Enables CLEAN-01's dict-value-swap design without any new S3 round trip. |
| `clean.py:232` hashes cleaned text alone | `clean.py` hashes `f"{parsed_artifact_id}:{cleaned_text}"` (WR-05) | This phase | Matches `chunk.py`'s already-shipped convention; closes the cross-document collision bug before CLEAN-01 makes it observable. |
| `process_crawled`: `parse → chunk → embed → index` | `process_crawled`: `parse → clean → chunk → embed → index` | This phase | Brings `klake process` (the command the original 28%-garbage audit actually ran) to parity with the Dagster asset graph. |

**Deprecated/outdated:** None — this phase does not remove or deprecate any existing capability; it activates dormant/bypassed capability that already exists.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | The `quality-audit` command should be a Typer CLI command (not an API endpoint) for Phase 17, matching the `klake lineage`/`klake reindex` idiom of a read-heavy DB+S3 table-printing command. CONTEXT.md D-05 explicitly leaves this to Claude/planner discretion. | Architectural Responsibility Map, Recommended Project Structure | Low — if the planner instead wants an API endpoint too, that's additive, not a rework; the underlying aggregation function should be written CLI-agnostic either way (mirrors `process.py`'s D-03 "one function, many callers" precedent) so adding an API route later is cheap. |
| A2 | Storing rejection counts on `cleaned_document.metadata_` (no new table) satisfies QUAL-04's "computable from these records" requirement at Phase 17's scale. | Architecture Patterns Pattern 2, Alternatives Considered | Medium — if Phase 19/20 need per-section (not per-document-aggregate) rejection rows for their own richer classifiers, a table will be needed then; recommend not building it prematurely in Phase 17, but the planner could reasonably choose to build the table now if they want to avoid a later migration. Either choice satisfies Phase 17's acceptance criteria as written. |
| A3 | "Empty after boilerplate removal" is the only rejection reason Phase 17's `clean()` can meaningfully produce, since no substance/length gate exists yet. | Common Pitfalls #5, Code Examples | Low — this follows directly from CLEAN-04/QUAL-01/QUAL-03 being explicitly scoped to Phases 19/20 in REQUIREMENTS.md's traceability table; Phase 17 has no other gate logic to draw rejection reasons from. |
| A4 | Single parent-scoped hash (mirroring `chunk.py` exactly) is sufficient for CLEAN-03, rather than the two-hash storage/identity split suggested in `.planning/research/SUMMARY.md`. | Alternatives Considered | Low-Medium — if S3 storage-dedup across documents turns out to matter at production scale, a later phase can add the storage-hash split without touching the registry `content_hash` semantics locked by D-04; this is a pure storage-efficiency optimization, not a correctness requirement. |

**If this table is empty:** N/A — see entries above. All four assumptions are low-to-medium risk and independently reversible in a later phase without touching this phase's locked decisions (D-01 through D-12 in CONTEXT.md).

## Open Questions

1. **Does the standalone `klake clean` / `klake chunk` CLI pair (as opposed to `klake process`) also need to gain a clean-before-chunk connection in this phase?**
   - What we know: `cli/app.py`'s standalone `klake chunk <parsed_artifact_id>` command (`cli/app.py:240-283`) independently calls `load_parsed_doc()`/`reparse_from_raw()` and passes the result straight to `chunk()` — it never calls `clean()` at all. This is a *third* bypass, structurally identical to the two named in CLEAN-01/CLEAN-02, but not named in CONTEXT.md's phase boundary ("both Dagster asset graph and CLI `process_crawled`").
   - What's unclear: Whether this is an intentional scope boundary (these are low-level single-artifact debugging commands, not the load-bearing path) or an oversight in the phase's scoping.
   - Recommendation: Treat as out of scope for Phase 17 per CONTEXT.md's explicit phase boundary (only Dagster asset graph + `process_crawled` named), but the plan should note this residual bypass exists so it isn't assumed fixed. If the planner wants zero residual bypasses, this is a small additive change (same `clean()` call pattern) — worth a one-line mention in the plan's scope notes either way.

2. **What should the `quality-audit`'s garbage-rate column show for a source with zero processed documents (division by zero in `rejected/(rejected+kept)`)?**
   - What we know: D-10 fixes the formula as `rejected / (rejected + kept)`. If a source has no raw documents processed yet, both `rejected` and `kept` are 0.
   - What's unclear: Whether the table should show `0%`, `N/A`, or omit the row.
   - Recommendation: Show `N/A` (or equivalent) distinctly from `0%` — a source with 0% garbage (all real content) and a source with no data at all are different facts, and MEAS-01's "reproducible" bar depends on not conflating them.

3. **Should `clean()`'s new `parsed_doc` parameter be required (breaking) or optional (backward-compatible) for external callers not covered by this phase?**
   - What we know: `cli/app.py:229`'s standalone `klake clean` command and `api/app.py:788`'s clean endpoint both call `clean(parsed_artifact_id, source_id, settings=...)` today with no `parsed_doc` in hand.
   - What's unclear: Whether those callers should gain a `cleaned_doc` in their return value too (via the `load_parsed_doc()`/`reparse_from_raw()` fallback), or whether it's acceptable for `cleaned_doc` to be absent/`None` in their result dicts since nothing consumes it there.
   - Recommendation: Make the parameter optional and, when absent, skip building `cleaned_doc` entirely (return `None` or omit the key) rather than paying the `reparse_from_raw()` cost for callers that don't need it — cheaper, and avoids Pitfall 2's test-contract break for those exact code paths.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (project-wide; `xfail_strict = true` in `pyproject.toml:125`) |
| Config file | `pyproject.toml` |
| Quick run command | `uv run pytest tests/unit/test_clean.py tests/unit/test_clean_silver_key.py tests/unit/test_pipeline_extractions.py -x` |
| Full suite command | `uv run pytest tests/unit tests/integration -x` (excludes `tests/e2e`, which requires `docker compose up` per its module docstring) |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| CLEAN-01 | `chunk_document` receives sections with boilerplate removed; uncleaned `parsed_doc` no longer forwarded | integration | `uv run pytest tests/integration/test_dagster_assets.py -k materialize -x` (extend with a new assertion on chunk text) | Partial — `test_dagster_materialize_produces_artifacts` exists at `test_dagster_assets.py:291`; needs a new boilerplate-content assertion (Wave 0 gap). |
| CLEAN-02 | `klake process` produces chunks from cleaned text; identical output to Dagster path | unit/integration | New test needed — no `test_process*.py` file exists today (confirmed by search this session; only `test_pipeline_extractions.py` checks `process_crawled`'s signature, not its behavior) | ❌ Wave 0 — new test file `tests/unit/test_process_crawled_clean.py` or similar. |
| CLEAN-03 | Two documents with identical cleaned text produce distinct `content_hash` | unit | New test in `tests/unit/test_clean.py` asserting hash inequality across two `parsed_artifact_id`s with identical cleaned text | ❌ Wave 0 — extend `test_clean.py`. |
| QUAL-04 | Per-source table: total sections, kept, rejected, reasons, garbage rate | integration | New test invoking the `quality-audit` command/function against a seeded fixture set | ❌ Wave 0 — new test file for the audit command. |
| QUAL-05 | `rejected + kept == sections_considered`; zero-section case distinct from all-rejected case | unit | New test in `tests/unit/test_clean.py` for both the invariant and the zero-sections warning path | ❌ Wave 0 — extend `test_clean.py`. |
| MEAS-01 | `klake quality-audit` produces 34-row (or N-row, per Pitfall 4) table, reproducible | integration | New CLI-level test (Typer `CliRunner`, matching existing CLI test patterns elsewhere in `tests/`) | ❌ Wave 0. |

### Sampling Rate
- **Per task commit:** `uv run pytest tests/unit/test_clean.py tests/unit/test_clean_silver_key.py tests/unit/test_pipeline_extractions.py -x`
- **Per wave merge:** `uv run pytest tests/unit tests/integration -x`
- **Phase gate:** Full suite green before `/gsd-verify-work`, plus the existing `tests/e2e/test_e2e_healthcare.py` if a docker-compose environment is available (not required for unit/integration gate, but directly exercises `clean_document → chunk_document` materialization end-to-end and is the natural place to assert "known boilerplate fixture line is absent from resulting chunk text" — CLEAN-01's literal acceptance criterion).

### Wave 0 Gaps
- [ ] `tests/unit/test_clean.py` — extend with WR-05 hash-scoping assertions (CLEAN-03) and conservation-invariant assertions (QUAL-05)
- [ ] `tests/unit/test_process_crawled_clean.py` (new) — covers CLEAN-02's clean-stage insertion and parity with the Dagster path
- [ ] `tests/integration/test_dagster_assets.py` — extend `test_dagster_materialize_produces_artifacts` (or add a sibling test) with a boilerplate-removal content assertion on the chunk artifacts produced (CLEAN-01)
- [ ] New test file for the `quality-audit` CLI command (MEAS-01, QUAL-04) — no existing fixture/harness to reuse; needs its own `CliRunner`-based test following whatever pattern the project's other CLI-command tests use (grep `typer.testing.CliRunner` usage in `tests/` for the established pattern before writing)
- [ ] Framework install: none — pytest and all fixtures already present.

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-------------------|
| V2 Authentication | No | This phase touches no authentication surface. |
| V3 Session Management | No | Not applicable. |
| V4 Access Control | No | `quality-audit` is an internal/operator CLI command, not a new API surface exposed to end users; no new access-control boundary is introduced. |
| V5 Input Validation | Yes | `clean()`'s new `parsed_doc` parameter is internal (caller-supplied `ParsedDoc`, never raw user input) — no new external input surface. The `quality-audit` command's only "input" is an optional `--domain`/`--source` CLI flag, which should be passed through the same domain-filtering path as existing commands (`get_domain_for_source`/`Source.domain` — parameterized ORM query, no raw SQL, matching the existing `T-01-03`/`T-01-13` conventions already enforced project-wide). |
| V6 Cryptography | Yes (adjacent) | `hashlib.sha256` — stdlib, already the project's standard for content-addressing (matches `chunk.py`, `parse.py`); no new crypto primitive introduced. Not used for security-sensitive purposes (integrity/dedup key only, not authentication or encryption). |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|----------------------|
| Cross-document lineage/data corruption via hash collision under a `UNIQUE(content_hash, artifact_type)` constraint | Tampering (data integrity) | CLEAN-03's WR-05 parent-scoped hash — already the core deliverable of this phase; see Pitfall 1. This is the phase's single most important security-adjacent property: without it, one document's content can be silently substituted for another's in the registry, which for a healthcare corpus (clinical guidance, dosage information) is a data-integrity concern with real-world consequence, not merely a quality nit. |
| SQL injection via a hand-rolled `Source.domain` filter in the new `quality-audit` query | Tampering | Use SQLAlchemy's parameterized `select(Source).where(Source.domain == domain_value)` — matches the existing `get_domain_for_source`/`list_sources_for_crawl_all` idiom (both parameterized ORM, no raw SQL string interpolation, per the project's existing `T-01-03`/`T-01-13` conventions cited in `lineage.py`'s docstring). |
| A `quality-audit` re-run of the real pipeline (D-07) inadvertently mutating production data (writing new artifacts/S3 objects) when it's meant to be a read/measurement operation | Tampering (unintended write) | This is *expected and accepted* behavior per D-07 ("re-runs the pipeline") — but the plan should ensure `quality-audit` only re-runs `parse()`/`clean()` (both idempotent, dedup-by-hash) and does **not** re-run `embed()`/`index()` (which would trigger unnecessary embedding-cost spend and Qdrant writes for a read-oriented audit). Constrain the audit's pipeline re-run to `parse → clean` only — `chunk()`'s section-count and content are already fully determined by `clean()`'s output, so `chunk()` itself doesn't need to be re-run to compute the audit's `sections_considered/kept/rejected` numbers (those are computed *inside* `clean()`, per Code Examples). |

## Sources

### Primary (HIGH confidence)
- This repository's source, read fresh this session at cited file:line — `dagster_defs/assets.py` (lines 260-536), `pipeline/process.py` (full file, 123 lines), `pipeline/clean.py` (full file, 361 lines), `pipeline/chunk.py` (lines 1-330), `pipeline/parse.py` (full file, 399 lines), `plugins/protocols.py` (lines 1-100), `registry/models.py` (lines 58-450), `registry/repo.py` (lines 227-373, 651-988), `lineage.py` (lines 1-50), `ids.py` (full file), `cli/app.py` (command list + lines 200-690), `config/settings.py` (lines 108-140, 373-380), `domains/loader.py` (lines 36-76), `domains/healthcare/sources.yaml` (counted: 28 entries), `tests/unit/test_clean.py`, `tests/unit/test_clean_silver_key.py`, `tests/e2e/test_e2e_healthcare.py`, `tests/unit/test_pipeline_extractions.py`, `registry/alembic/versions/0010_sources_domain_column.py`, `pyproject.toml:125` (`xfail_strict`)
- `.planning/research/SUMMARY.md` — this project's own prior deep-research output (HIGH confidence per its own self-assessment: claims executed against pinned library versions, not recalled) — used for architecture/pitfall grounding not independently re-verified this session (e.g. the `crawl4ai`/`datatrove` filter-execution findings, which are Phase 19/20 concerns, not re-checked here since out of this phase's scope)
- `.planning/MILESTONE-CONTEXT.md` — audit evidence and root-cause layering (L0-L5), scope decisions D-1 through D-5
- `.planning/REQUIREMENTS.md` — v2.6 requirement definitions and phase-to-requirement traceability table
- `.planning/phases/17-close-the-bypass-measurement/17-CONTEXT.md` — locked user decisions D-01 through D-12

### Secondary (MEDIUM confidence)
- None used this session beyond the primary sources above — no external web/library documentation was needed; this phase is entirely internal-codebase retrofit work against already-pinned, already-installed dependencies.

### Tertiary (LOW confidence)
- The original ad-hoc audit script that produced the "28% garbage" / "4,499 chunks / 34 sources" figures cited in `MILESTONE-CONTEXT.md` was not located or re-run this session (not part of this repository's tracked source as far as could be determined) — its exact category-overlap accounting (the five listed percentages sum to ~44%, not 28%, implying overlapping categories) could not be independently verified. Flagged in Open Questions #2 territory and Pitfall 5 — treat the 28% figure as directional/historical, not a number this phase's own harness needs to reproduce exactly.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new packages; every function/module referenced was read directly this session.
- Architecture: HIGH — the dict-value-swap design, the WR-05 hash pattern, and the parsed_doc/sections distinction are all grounded in code read this session, not inferred; cross-checked against `.planning/research/SUMMARY.md`'s independently-reached, HIGH-confidence architecture conclusions.
- Pitfalls: HIGH on mechanism (all five pitfalls trace to specific file:line evidence, either read this session or inherited from SUMMARY.md's executed findings) / LOW on the exact magnitude of any given pitfall's real-world impact (e.g. how many actual documents in the healthcare pack will collide under the old hash scheme — not measured, would require a live corpus scan `.planning/research/SUMMARY.md` itself flagged as an unaddressed gap).

**Research date:** 2026-07-16
**Valid until:** No external dependency drift risk (no new packages) — this research is valid until the codebase itself changes underneath it. Recommend re-grounding against `assets.py`/`clean.py`/`process.py` line numbers if this phase's planning is deferred more than ~2 weeks past this research date, since this is an actively-developed area of the codebase (Phase 18-21 all touch adjacent code).
