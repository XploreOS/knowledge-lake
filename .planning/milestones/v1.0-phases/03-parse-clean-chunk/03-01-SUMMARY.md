---
phase: 03-parse-clean-chunk
plan: "01"
subsystem: parse
status: complete
tags: [parsing, quality-scoring, fallback-chain, multi-format, torture-corpus]
dependency_graph:
  requires: [02-ingestion]
  provides: [parse-with-fallback, quality-scorer, json-xml-parser, alembic-0006]
  affects: [pipeline/parse.py, plugins/resolver.py, plugins/builtin/docling_parser.py]
tech_stack:
  added:
    - datasketch==1.10.0 (MinHash near-dedup — plan 02/03 will use)
    - lingua-language-detector==2.2.0 (language detection — plan 02 will use)
  patterns:
    - Heuristic quality scorer with optional LLM gray-zone check (D-04)
    - Ordered parser fallback chain with exception + quality-gate triggers (D-01, D-02)
    - Lazy imports for optional heavy dependencies (unstructured, tika, defusedxml)
    - 100 MiB DoS guard at parse entry points (T-03-02)
key_files:
  created:
    - src/knowledge_lake/quality/__init__.py
    - src/knowledge_lake/quality/scorer.py
    - src/knowledge_lake/plugins/builtin/json_xml_parser.py
    - src/knowledge_lake/plugins/builtin/unstructured_parser.py
    - src/knowledge_lake/plugins/builtin/tika_parser.py
    - src/knowledge_lake/registry/alembic/versions/0006_parse_clean_chunk_columns.py
    - tests/fixtures/torture_test/healthcare_sample.html
    - tests/fixtures/torture_test/healthcare_sample.md
    - tests/fixtures/torture_test/healthcare_sample.csv
    - tests/fixtures/torture_test/healthcare_sample.json
    - tests/fixtures/torture_test/healthcare_sample.xml
    - tests/fixtures/torture_test/__init__.py
    - tests/unit/test_parse_multiformat.py
    - tests/unit/test_fallback_chain.py
    - tests/unit/test_quality_scorer.py
    - tests/unit/test_clean.py (xfail stub — plan 02)
    - tests/unit/test_dedup.py (xfail stub — plan 02)
    - tests/unit/test_chunk_token.py (xfail stub — plan 03)
    - tests/integration/test_parse_structure.py
    - tests/integration/test_torture_corpus.py
  modified:
    - pyproject.toml (new deps, 3 new parser entry points, integration marker)
    - src/knowledge_lake/config/settings.py (ParseSettings, CleanSettings, ChunkSettings)
    - src/knowledge_lake/plugins/builtin/docling_parser.py (6-format multi-format extension)
    - src/knowledge_lake/plugins/resolver.py (parse_with_fallback function)
    - src/knowledge_lake/pipeline/parse.py (uses parse_with_fallback, records quality_score)
    - tests/unit/test_builtin_plugins.py (updated stale Phase 1 HTML test)
decisions:
  - D-01 fallback on exception OR quality gate failure — implemented in parse_with_fallback()
  - D-02 stop on first success — chain exits immediately on passing result
  - D-04 deterministic heuristic first (4 weighted factors) with optional LLM gray-zone check
  - Empty document special case — scores exactly 0.0 (text_len=0 AND sections=0 short-circuit)
  - Optional parsers (unstructured, tika) use lazy imports — graceful skip if not installed
  - defusedxml used when available for XXE prevention (T-03-04); stdlib fallback with log warning
metrics:
  duration: "10m"
  completed_date: "2026-07-05"
  tasks: 3
  files_created: 19
  files_modified: 5
  tests_passing: 202
  tests_xfail: 3
---

# Phase 03 Plan 01: Parser Chain and Quality Scoring Summary

**One-liner:** Multi-format parser fallback chain (Docling 6-format + JsonXmlParser) with weighted heuristic quality scoring, optional LLM gray-zone check, Alembic 0006 migration, and torture-test corpus validation across 5 healthcare document formats.

## What Was Built

### Core Deliverables

**Multi-format DoclingParser** (`src/knowledge_lake/plugins/builtin/docling_parser.py`):
Extended from PDF-only to all 6 Docling-native formats: PDF, HTML, DOCX, Markdown, CSV, XLSX. The `_mime_to_suffix()` map drives file extension selection so Docling auto-detects format from suffix. Added 100 MiB DoS guard before any temp-file write (T-03-02).

**JsonXmlParser** (`src/knowledge_lake/plugins/builtin/json_xml_parser.py`):
Stdlib-only parser for `application/json`, `application/xml`, `text/xml`. Recursive `_extract_json_text()` collects all string leaves; `_extract_xml_text()` depth-first extracts `.text`/`.tail` values. XXE guard via `defusedxml.ElementTree.fromstring()` with graceful fallback to stdlib (T-03-04).

**Optional fallback stubs** (`unstructured_parser.py`, `tika_parser.py`):
Both use lazy imports in `can_parse()` to gracefully return `False` when optional deps are absent. Raises `RuntimeError` on parse failure so the fallback chain continues (D-01 exception trigger).

**Quality Scorer** (`src/knowledge_lake/quality/scorer.py`):
`compute_quality_score()` runs 4 weighted heuristics (text_length 0.35, sections 0.20, encoding 0.25, empty_sections 0.20). Empty doc short-circuit returns exactly 0.0. `maybe_llm_spot_check()` fires only when score is inside the gray zone AND `llm_spot_check=True` — uses LiteLLM `cheap_model` alias with lazy import.

**parse_with_fallback()** (`src/knowledge_lake/plugins/resolver.py`):
Iterates `settings.parse.chain` in order. Triggers D-01 fallback on: `LookupError` (parser unavailable), `can_parse()` returning False, any exception from `parse()`, or quality score below `quality_threshold`. Returns `(ParsedDoc, parser_name, quality_score)` on first success (D-02). Raises `ValueError` with full chain list when exhausted.

**Alembic 0006 migration** (`0006_parse_clean_chunk_columns.py`):
Adds `quality_score FLOAT`, `language VARCHAR(16)`, `dedup_status VARCHAR(32)` to the `artifacts` table. `down_revision = "0005"` chains correctly to the unique-sources migration.

**Settings extension** (`config/settings.py`):
Added `ParseSettings`, `CleanSettings`, `ChunkSettings` nested sub-models. All configurable via `KLAKE_PARSE__*`, `KLAKE_CLEAN__*`, `KLAKE_CHUNK__*` env vars.

**pipeline/parse.py extension**:
Replaced single `get_parser(s).parse()` call with `parse_with_fallback()`. Records `quality_score` and `parser_used` in artifact `metadata_` JSON column (Alembic 0006 dedicated column added for future use). Result dict extended with `quality_score` and `parser_used` keys.

### Torture Corpus (PARSE-05)

All 5 fixtures score well above the 0.35 gate:
| Fixture | Parser | Score |
|---------|--------|-------|
| hhs_security_rule.pdf | DoclingParser | 1.000 |
| healthcare_sample.html | DoclingParser | 1.000 |
| healthcare_sample.md | DoclingParser | 0.950 |
| healthcare_sample.csv | DoclingParser | 0.700 |
| healthcare_sample.json | JsonXmlParser | 0.779 |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Updated stale Phase 1 test expecting HTML parsing to fail**
- **Found during:** Task 2 — after extending DoclingParser to support HTML, existing test `test_cannot_parse_html_in_phase1` asserted `can_parse("text/html") is False`
- **Fix:** Renamed and inverted to `test_can_parse_html_phase3` asserting True
- **Files modified:** `tests/unit/test_builtin_plugins.py`
- **Commit:** `2696ca6`

**2. [Rule 1 - Bug] Empty document scores 0.0 special case**
- **Found during:** Task 2 acceptance criteria check — `ParsedDoc("", [], {})` scored 0.35 because `encoding_score = 1.0` for empty text (no replacement chars)
- **Fix:** Added early return `0.0` when `text_len == 0 AND sections == []`
- **Files modified:** `src/knowledge_lake/quality/scorer.py`
- **Commit:** `2696ca6`

**3. [Rule 2 - Missing functionality] Added `integration` pytest marker**
- **Found during:** Task 3 — PytestUnknownMarkWarning when using `@pytest.mark.integration`
- **Fix:** Added marker to `[tool.pytest.ini_options]` markers list in `pyproject.toml`
- **Files modified:** `pyproject.toml`
- **Commit:** `b1cb07e`

## Threat Model Review

All T-03-01 through T-03-04 mitigations implemented:
- T-03-01: TemporaryDirectory cleanup on SIGKILL preserved from Phase 1 (CR-08)
- T-03-02: 100 MiB size limit in DoclingParser.parse(), UnstructuredParser.parse()
- T-03-03: Temp file suffix from whitelist map, never from user input
- T-03-04: defusedxml.fromstring() for XML parsing; graceful stdlib fallback with warning

T-03-SC (package legitimacy): datasketch and lingua-language-detector pre-audited in RESEARCH.md — no blocking checkpoint required.

## Self-Check: PASSED

### Files verified to exist:
- src/knowledge_lake/quality/scorer.py — FOUND
- src/knowledge_lake/plugins/builtin/json_xml_parser.py — FOUND
- src/knowledge_lake/registry/alembic/versions/0006_parse_clean_chunk_columns.py — FOUND
- tests/integration/test_torture_corpus.py — FOUND
- tests/fixtures/torture_test/healthcare_sample.html — FOUND

### Commits verified to exist:
- 1a47883 (Task 1 infrastructure) — FOUND
- 2696ca6 (Task 2 parser chain) — FOUND
- b1cb07e (Task 3 corpus + tests) — FOUND

### Test results:
- 202 unit tests passed, 3 xfailed (stub placeholders for plans 02/03)
- 11 integration tests passed (parse_structure + torture_corpus)
- 0 failures
