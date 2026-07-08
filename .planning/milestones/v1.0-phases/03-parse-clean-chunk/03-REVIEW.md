---
phase: 03-parse-clean-chunk
reviewed: 2026-07-05T05:00:00Z
depth: standard
files_reviewed: 22
files_reviewed_list:
  - src/knowledge_lake/pipeline/chunk.py
  - src/knowledge_lake/pipeline/clean.py
  - src/knowledge_lake/pipeline/parse.py
  - src/knowledge_lake/pipeline/utils.py
  - src/knowledge_lake/dagster_defs/assets.py
  - src/knowledge_lake/api/app.py
  - src/knowledge_lake/api/schemas.py
  - src/knowledge_lake/cli/app.py
  - src/knowledge_lake/config/settings.py
  - src/knowledge_lake/plugins/builtin/tika_parser.py
  - src/knowledge_lake/plugins/resolver.py
  - src/knowledge_lake/plugins/builtin/docling_parser.py
  - src/knowledge_lake/plugins/builtin/json_xml_parser.py
  - src/knowledge_lake/plugins/protocols.py
  - src/knowledge_lake/quality/scorer.py
  - src/knowledge_lake/registry/repo.py
  - tests/unit/test_chunk_token.py
  - tests/unit/test_clean.py
  - tests/unit/test_dedup.py
  - tests/unit/test_fallback_chain.py
  - tests/unit/test_parse_multiformat.py
  - tests/unit/test_quality_scorer.py
findings:
  critical: 0
  warning: 0
  info: 3
  total: 3
status: clean
---

# Phase 03: Code Review Report (Iteration 3 — Final)

**Reviewed:** 2026-07-05
**Depth:** standard
**Files Reviewed:** 22
**Status:** clean

## Summary

Final re-review after 9 fix commits across 2 prior iterations. All 9 fixes are verified correct. The last open critical finding (CR-01 from iter2 — `test_fallback_chain.py` patching a dead code path after the WR-03 refactor) was resolved in commit `cb9fb57`. No new Critical or Warning issues were introduced by the iter2 fix. The three Info items carried from iter1/iter2 are unchanged and re-listed below. No blocking issues remain.

---

## Iteration 2 Fix Verification

### CR-01 (iter2) — `test_fallback_chain.py` retarget from `resolve` to `entry_points`

**Status: CORRECT.**

Commit `cb9fb57` correctly replaces all four `patch("knowledge_lake.plugins.resolver.resolve", ...)` usages with `patch("knowledge_lake.plugins.resolver.entry_points", ...)`.

Key design choices — all verified sound:

1. **`_FakeEP` class (lines 71–79):** Exposes `.name` (str) and `.load()` returning a callable — correct `importlib.metadata.EntryPoint` interface match for the `parse_with_fallback` loop at `resolver.py:113`.

2. **`_make_factory` closure (lines 93–96):** Wraps `mock_instance` via an extra call to avoid the closure-in-loop variable capture bug. Each `_FakeEP` holds a factory bound to the correct mock. Correct.

3. **`_make_entry_points_mock(ep_map)` (lines 82–104):** Returns `_mock_entry_points`, a callable that intercepts only `group == "knowledge_lake.parsers"` and forwards all other groups to `real_entry_points`. Unrelated `entry_points(...)` calls in dependencies are unaffected. Correct.

4. **Factory accepts `**kwargs` (line 95):** Handles both the zero-argument call (`factory()` for non-tika parsers) and the kwarg call (`factory(tika_server_url=...)` for tika). Both return the bound mock instance. Correct.

5. **`test_unavailable_parser_skipped`:** `"missing"` is intentionally absent from ep_map so the `for/else` inside `parse_with_fallback` fires `raise LookupError("missing")`, which is caught, and the chain continues to `"b"`. Correct.

6. **`side_effect` semantics:** `entry_points(group=GROUP_PARSERS)` passes `group` as a keyword argument; `_mock_entry_points(group)` receives it correctly as a positional-or-keyword parameter. The `side_effect` callable is invoked by `unittest.mock` before returning the value. Correct.

All four tests now exercise the actual code path that `parse_with_fallback` uses since the WR-03 refactor.

---

## Info

### IN-01: Four artifact types share "doc" prefix — IDs are not self-describing

**File:** `src/knowledge_lake/ids.py` (not in review file list — carried from iter1)

**Issue:** `raw_document`, `parsed_document`, `cleaned_document`, and `bronze_document` all produce `"doc_"` prefixed IDs. Logs and CLI output cannot distinguish a raw artifact from a cleaned one by ID prefix alone, which undermines the operability goal of type-prefixed IDs.

**Fix:** Assign distinct prefixes (e.g. `"raw"`, `"prs"`, `"cln"`, `"brz"`) or document the single-prefix design as intentional in a code comment.

---

### IN-02: Boilerplate regex matches bare integers — risks stripping meaningful numeric content

**File:** `src/knowledge_lake/pipeline/clean.py:40`

**Issue:** The pattern `r"^(?:Page \d+ of \d+|\d+)\s*$"` with `re.MULTILINE` strips any line whose entire content is one or more digits. In healthcare regulatory documents this can remove numbered list items, standalone footnote numbers, dosage values on their own line, and structured table cell values.

**Fix:** Narrow the bare-integer branch to small numbers typical of page footers:
```python
re.compile(r"^(?:Page \d+ of \d+|\d{1,3})\s*$", re.MULTILINE)
```
Or anchor to common page-footer context only.

---

### IN-03: `test_encoding_errors_lower_score` passes for the wrong reason

**File:** `tests/unit/test_quality_scorer.py:46`

**Issue:** Line 46 reads:
```python
text_garbled = ("a" * 160) + ("" * 40)  # 20% replacement chars
```
`("" * 40)` evaluates to an empty string — not 40 Unicode replacement characters `�`. `text_garbled` is therefore `"a" * 160`, which is 40 characters shorter than `text_clean`. The assertion `score_clean >= score_garbled` holds because of the length difference (shorter text produces lower `text_length_score`), not because `encoding_score` detected garbled content. The test gives false assurance. The adjacent `test_encoding_errors_lower_score_with_replacement_chars` uses the correct literal `"�" * 40`.

**Fix:**
```python
text_garbled = ("a" * 160) + ("�" * 40)  # explicit U+FFFD replacement chars
```

---

_Reviewed: 2026-07-05_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
_Iteration: 3 (final)_
