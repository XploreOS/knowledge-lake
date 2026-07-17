# Phase 22: Address tech debt (garbage/junk measurement, Nyquist reconciliation) - Pattern Map

**Mapped:** 2026-07-17
**Files analyzed:** 5 (all modify-in-place; zero new files/modules per RESEARCH.md's explicit "no new module needed" recommendation)
**Analogs found:** 5 / 5 (all are self-analogs — extending the same file whose existing function is the pattern to mirror)

Note: This phase is unusual in that RESEARCH.md already did the pattern-extraction work in exhaustive detail
(exact line numbers, verbatim code, anti-patterns). This PATTERNS.md packages those same findings into the
planner-facing classification/analog format, adds a couple of additional excerpts RESEARCH.md didn't quote in
full (test fixture scaffolding, `chunk()`'s public signature, `export.py` docstring block), and does not
duplicate RESEARCH.md's `_apply_substance_gate()`/Pattern-1/2/3 narrative — see RESEARCH.md directly for that.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|-----------------|----------------|
| `src/knowledge_lake/pipeline/quality_audit.py` (add `run_full_pipeline_audit()`, fix Pitfall 1 in existing `run_quality_audit()`) | service (pipeline measurement/batch) | batch (per-source loop, in-memory aggregation) | itself — `run_quality_audit()` (same file, lines 26-147) | exact (self-analog; same module, same loop skeleton, same tally-and-return shape) |
| `src/knowledge_lake/cli/app.py` (add sibling CLI command or `--full` flag) | route/controller (CLI command) | request-response (invoke → print table/JSON) | itself — `cmd_quality_audit()` (same file, lines ~974-1017) | exact (self-analog; same Typer decorator, same `--json` flag convention, same table-header format) |
| `src/knowledge_lake/pipeline/export.py` (docstring-only note, D-07) | service (pipeline export) | CRUD (read chunk artifacts → write Parquet) | itself — module docstring block (lines 1-24) | exact (self-analog; no code change, only a design-boundary clarification appended to the existing docstring) |
| `tests/unit/test_quality_audit.py` (extend: chunk-tally tests, D-04 dilution-regression test, domain_filters-gap test) | test | request-response (fixture DB → function call → assert) | itself — existing `TestRunQualityAudit`-style classes (lines ~151-345) | exact (self-analog; same in-memory-SQLite + monkeypatched `get_engine` fixture, same `@patch` source-module mocking convention) |
| `tests/unit/test_cli_quality_audit.py` (extend: new CLI surface output-format test) | test | request-response (Typer `CliRunner` invoke → assert stdout) | itself — existing CLI test file (not yet read in full; same file, existing test functions for `cmd_quality_audit`) | role-match (same file; exact prior test not quoted here — see Step 4 note below) |

## Pattern Assignments

### `src/knowledge_lake/pipeline/quality_audit.py` — add `run_full_pipeline_audit()`

**Analog:** `run_quality_audit()`, same file, lines 26-147 (full function read above).

**Module docstring / scope boundary** (lines 1-17) — update in place to mention the new function's `chunk`/`export` scope while preserving the "never import embed/index" constraint verbatim:
```python
"""MEAS-01 quality-audit harness: re-run parse->clean and surface per-source
rejection counts (QUAL-04), without a separate frozen classifier (D-07).
...
Scope is strictly ``parse -> clean``. This module must never import
``knowledge_lake.pipeline.embed`` or ``knowledge_lake.pipeline.index`` — the
audit is read/measurement-only (D-07's "the pipeline IS the measurement")
and must never trigger vector-store writes or embedding spend.
"""
```

**Imports pattern** (lines 44-52) — function-local imports, mirrored exactly for the new function (add `chunk`, `export_rag_corpus`, `DomainLoader`, `_build_token_chunks`/`_apply_substance_gate`):
```python
from sqlalchemy import select

from knowledge_lake.config.settings import Settings, get_settings  # noqa: F401
from knowledge_lake.pipeline.clean import clean
from knowledge_lake.pipeline.ingest import _detect_mime_from_uri
from knowledge_lake.pipeline.parse import load_parsed_doc, parse, reparse_from_raw
from knowledge_lake.registry import repo as registry_repo
from knowledge_lake.registry.db import get_session
from knowledge_lake.registry.models import Artifact, Source
```

**Per-source / per-document loop skeleton to copy verbatim (structure, not content)** (lines 56-131):
```python
with get_session() as session:
    stmt = select(Source).where(Source.domain == domain).order_by(Source.created_at.asc())
    sources = session.execute(stmt).scalars().all()
    source_rows = [(src.id, src.name) for src in sources]  # PAYLOAD-01: materialize inside session

rows: list[dict] = []
for source_id, source_name in source_rows:
    with get_session() as session:
        stmt = (
            select(Artifact)
            .where(Artifact.source_id == source_id)
            .where(Artifact.artifact_type == "raw_document")
            .order_by(Artifact.created_at.asc())
        )
        raw_artifacts = session.execute(stmt).scalars().all()
        raw_docs = [(a.id, a.mime_type, a.storage_uri) for a in raw_artifacts]

    for raw_id, mime, storage_uri in raw_docs:
        try:
            with get_session() as session:
                children = registry_repo.list_children(session, raw_id)
                parsed_id = next(
                    (c.id for c in children if c.artifact_type == "parsed_document"), None
                )
            if parsed_id is not None:
                parsed_doc = load_parsed_doc(parsed_id, settings=s)
                if parsed_doc is None:
                    parsed_doc = reparse_from_raw(parsed_id, source_id, settings=s)
            else:
                parse_result, parsed_doc = parse(
                    raw_id, source_id,
                    mime_type=(mime or _detect_mime_from_uri(storage_uri or "")),
                    settings=s,
                )
                parsed_id = parse_result["artifact_id"]
            clean_result = clean(
                parsed_id, source_id, parsed_doc=parsed_doc, settings=s,
                domain_filters=domain_filters,  # ADD — Pitfall 1 fix, apply to BOTH old and new call sites
            )
        except Exception:
            documents_errored += 1
            log.warning("quality_audit.document_failed", source_id=source_id, raw_id=raw_id, exc_info=True)
            continue
        # accumulate sections_* / chunk kept-rejected-reasons here
```

**Frozen `garbage_rate` formula (Phase 17 D-10) — reuse verbatim, apply identically at chunk level** (lines 133-134):
```python
total = sections_rejected + sections_kept
garbage_rate = (sections_rejected / total) if total > 0 else None
# Apply the SAME rejected/(rejected+kept) shape to chunk-level counts —
# do not invent a different denominator convention.
```

**Error isolation pattern** (lines 117-125): per-document `try/except Exception`, increment `documents_errored`, `log.warning(..., exc_info=True)`, `continue` — never abort the whole audit on one bad document.

**Return-row shape convention** (lines 136-145): flat dict per source, keys named `{unit}_considered/kept/rejected`, `rejection_reasons` (summed dict), `documents_errored`, `{unit}_rate` (`None` when denominator is 0, never `0.0`).

**Gate-annotation reuse (D-04 mechanism — see RESEARCH.md Pattern 1/2/3 for full narrative, not repeated here):**
`pipeline/chunk.py`'s `_build_token_chunks()` + `_apply_substance_gate()` (chunk.py lines ~340-420, quoted in RESEARCH.md) are pure, already-public functions to import and call directly for in-memory kept/rejected/reason tallying — no new gate logic, no `gate_mode="report"` global change.

**Domain-filters resolution pattern to add** (mirrors `process.py` lines 112-113, cited in RESEARCH.md but not this file yet):
```python
from knowledge_lake.domains.loader import DomainLoader  # exact import path to confirm at plan time
domain_filters = DomainLoader.from_name(s.domain.domain_name).filters
```

---

### `src/knowledge_lake/cli/app.py` — add sibling CLI command / `--full` flag

**Analog:** `cmd_quality_audit()`, same file, lines ~974-1017 (quoted above in full).

**Command module docstring list** (lines 1-19) — add one line for the new command, mirroring the existing per-command one-liner convention:
```
  quality-audit — re-run parse+clean across a domain's sources and print a per-source garbage-rate table
```

**Decorator + Typer option pattern to copy** (lines 974-985):
```python
@app.command(name="quality-audit")
def cmd_quality_audit(
    domain: str = typer.Option(
        "healthcare", "--domain", "-d", help="Domain to audit (Source.domain filter)."
    ),
    as_json: bool = typer.Option(
        False, "--json", help="Output machine-readable JSON instead of a table."
    ),
) -> None:
```

**Function-local import + early-return-on-empty pattern** (lines 993-1002):
```python
from knowledge_lake.pipeline.quality_audit import run_quality_audit

rows = run_quality_audit(domain=domain)

if not rows:
    typer.echo(f"No sources found for domain {domain!r}.")
    return

if as_json:
    typer.echo(json.dumps(rows))
    return
```

**Table-header / row-formatting convention to extend with new chunk/export columns** (lines 1003-1017):
```python
header = (
    f"{'source_name':<30} {'considered':>10} {'kept':>6} {'rejected':>8} "
    f"{'errored':>8} {'garbage_rate':>12}"
)
typer.echo(header)
typer.echo("-" * len(header))
for row in rows:
    rate = row["garbage_rate"]
    rate_display = "N/A" if rate is None else f"{rate:.1%}"
    typer.echo(
        f"{row['source_name']:<30} {row['sections_considered']:>10} "
        f"{row['sections_kept']:>6} {row['sections_rejected']:>8} "
        f"{row['documents_errored']:>8} {rate_display:>12}"
    )
```

---

### `src/knowledge_lake/pipeline/export.py` — docstring-only D-07 note

**Analog:** its own module docstring, lines 1-24 (quoted below), no code change.

**Existing docstring structure to extend with a new "Design decisions" bullet:**
```python
"""Export stage: curated corpus, dataset examples → gold-zone Parquet/JSONL files.

Implements EXPORT-01 (RAG corpus → Parquet), EXPORT-02 (pretraining corpus → JSONL),
and EXPORT-03 (fine-tuning dataset → OpenAI chat-messages JSONL).

Design decisions:
    D-09: All exports write to a gold zone in the EXISTING StorageBackend (raw →
          bronze → silver → gold zone progression) — never a new storage backend.
    D-10: Polars writes the actual Parquet/JSONL files; DuckDB is the query/verify
          engine — DuckDB never writes export files.
    FOUND-03: Every write path uses a single in-memory io.BytesIO buffer, then
              StorageBackend.put_object() — never open() in write mode, never tempfile,
              never a local filesystem path.
    T-05-08: _RAG_CORPUS_FIELDS explicit allow-list enforced — export rows are built
             key-by-key, never via dataclasses.asdict() or a raw metadata_ dump.
"""
```
Add a new bullet under "Design decisions" (Phase 22 D-07): state the export is chunk-artifact-scoped
(citation-complete training data) by design, distinct from the deduplicated vector index — matching the
existing bullet style (`D-XX: <one-sentence claim>.`).

**The exact one-line filter this docstring note documents** (export.py, cited in RESEARCH.md as line 309):
```python
if not meta.get("substance_passed", True):
    substance_filtered_out += 1
    continue
```
Do not modify this line — D-07 is documentation-only.

---

### `tests/unit/test_quality_audit.py` — extend

**Analog:** itself — existing fixture block (lines 1-60, quoted above) and existing `Test*` classes (lines 151-345, not fully quoted — function names only).

**Fixture pattern to reuse verbatim (no new fixtures needed per RESEARCH.md Wave-0 note):**
```python
@pytest.fixture()
def engine():
    """In-memory SQLite engine, shared connection via StaticPool."""
    from knowledge_lake.registry.models import Base
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture(autouse=True)
def _patch_engine(monkeypatch, engine):
    """Route registry.db.get_session() to the in-memory test engine."""
    monkeypatch.setattr(registry_db, "get_engine", lambda: engine)
```

**Mocking convention (module docstring, lines 1-9) — critical, must follow exactly for new tests:**
> `parse`/`load_parsed_doc`/`reparse_from_raw`/`clean` are mocked at their SOURCE modules
> (`knowledge_lake.pipeline.parse`, `knowledge_lake.pipeline.clean`) because `quality_audit.py` uses
> function-local imports — each call re-resolves `from module import name` against the current module
> attribute, so patching the source module (not `quality_audit`'s own namespace) is what actually takes effect.

Existing test names to model new ones after (naming convention: `test_<behavior>_<expected_outcome>`):
`test_domain_filter_returns_only_matching_sources`, `test_zero_raw_documents_yields_none_garbage_rate`,
`test_rejection_reasons_summed_not_overwritten`, `test_garbage_rate_equals_rejected_over_rejected_plus_kept`,
`test_one_document_failure_does_not_abort_audit`, `test_existing_parsed_child_skips_parse_call`.

**New tests to add (per RESEARCH.md Wave-0 gaps and Validation Architecture table):**
- Chunk-level tally test (`-k chunk_audit`)
- D-04 dilution-regression test (`-k dilution`) — seed one pre-v2.6 chunk artifact with no `substance_passed`
  key and one fresh gated chunk in the same fixture DB; assert the new scoped measurement reports only the
  fresh one, not both
- domain_filters-gap regression test (`-k domain_filters`) — seed a clinical-code fixture text, assert it
  survives `clean()` inside the new/fixed function

---

### `tests/unit/test_cli_quality_audit.py` — extend

**Analog:** itself (existing test functions for `cmd_quality_audit`'s Typer surface — file exists but was not
read in this pass; reuse the same `CliRunner`/`app` invocation pattern already established there for the new
command/flag's output-format assertions). Follow the same `--json` vs table-mode dual-path testing already
implied by `cmd_quality_audit`'s `as_json` branch (app.py lines 993-996).

## Shared Patterns

### Function-local imports (module convention, all pipeline files)
**Source:** `pipeline/quality_audit.py` lines 44-52, `cli/app.py` lines 993 area
**Apply to:** the new `run_full_pipeline_audit()` and any new CLI command — every dependency is imported
inside the function body, never at module top-level (except `structlog`/`from __future__ import annotations`).
This is required, not optional — `test_quality_audit.py`'s mocking strategy depends on it (see test section
above).

### Frozen rate formula (Phase 17 D-10)
**Source:** `pipeline/quality_audit.py` lines 133-134
**Apply to:** both the chunk-level garbage-rate tally and the export-level junk-rate tally — always
`rejected / (rejected + kept)`, `None` when denominator is 0, never redefine the formula shape per-metric.

### Per-document error isolation
**Source:** `pipeline/quality_audit.py` lines 117-125
**Apply to:** the new function's per-document loop — `try/except Exception`, increment an `*_errored`
counter, `log.warning(..., exc_info=True)`, `continue` (never let one bad document abort the whole run).

### PAYLOAD-01 session-scoping discipline
**Source:** `pipeline/quality_audit.py` lines 62-65 ("Materialize to tuples inside the session")
**Apply to:** any new query the measurement function adds — never let an ORM object escape its `with
get_session()` block; extract plain tuples/ids first.

### CLI table/JSON dual-output convention
**Source:** `cli/app.py` lines 993-1017 (`cmd_quality_audit`)
**Apply to:** the new CLI surface — `--json` flag prints `json.dumps(rows)` and returns early; otherwise a
fixed-width `f"{...:<N}"` / `f"{...:>N}"` header + row table, with `"N/A"` (not `"0.0%"`) for `None` rates.

## No Analog Found

None — every file in scope is a self-analog (extending an existing function/module in place). RESEARCH.md
confirms zero new packages, zero new modules, zero new external integration surfaces for this phase.

## Metadata

**Analog search scope:** `src/knowledge_lake/pipeline/quality_audit.py`, `src/knowledge_lake/pipeline/chunk.py`,
`src/knowledge_lake/pipeline/export.py`, `src/knowledge_lake/cli/app.py`, `tests/unit/test_quality_audit.py`
(all read directly this session; `tests/unit/test_cli_quality_audit.py` referenced by name/convention only,
not re-read since RESEARCH.md already covers its fixture precedent).
**Files scanned:** 5 read directly (1 full quality_audit.py, partial reads of app.py/export.py/chunk.py/
test_quality_audit.py), plus RESEARCH.md's own already-exhaustive excerpts reused directly per the no-re-read
rule.
**Pattern extraction date:** 2026-07-17
</content>
