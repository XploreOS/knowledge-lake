---
phase: 03-parse-clean-chunk
reviewed: 2026-07-05T03:00:00Z
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
  - src/knowledge_lake/plugins/builtin/unstructured_parser.py
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
  critical: 1
  warning: 0
  info: 3
  total: 4
status: issues_found
---

# Phase 03: Code Review Report (Iteration 2)

**Reviewed:** 2026-07-05
**Depth:** standard
**Files Reviewed:** 22
**Status:** issues_found

## Summary

Iteration 2 re-review after 8 fixes were applied in iteration 1. All 8 fixes are verified as correct and complete. One new blocker was introduced by the WR-03 fix: `parse_with_fallback` was refactored to use an inline `entry_points()` loop (needed for tika URL injection), but the four tests in `test_fallback_chain.py` still patch `knowledge_lake.plugins.resolver.resolve` — a function `parse_with_fallback` no longer calls. Three of the four tests are now broken: they patch a no-op and the actual entry-point dispatch reaches no mock parsers, so `parse_with_fallback` exhausts the chain and raises `ValueError` instead of returning the expected result. Three tests fail for the wrong reason; one (`test_all_parsers_exhausted_raises`) passes accidentally. The three Info findings from iter1 are unchanged and carried forward below.

---

## Iteration 1 Fix Verification

### CR-01 — `chunk_section()` infinite loop guard

**Status: CORRECT.** Lines 150-153 of `chunk.py` add the guard immediately after the overlap window is computed. If `overlap_cost + costs[i] > max_tokens`, the current sentence is force-appended and `i` is advanced, breaking the infinite loop. The comment on the following line was correctly updated to "Do NOT advance i otherwise".

### CR-02 — `mime_type` propagation in Dagster `ingest_raw_document`

**Status: CORRECT.** Line 163 of `assets.py` adds `result["mime_type"] = config.mime_type` to the result dict before return. The downstream `parsed_document` asset reads `ingest_raw_document.get("mime_type", "application/pdf")` and now receives the correct MIME type.

### WR-01 — `clean.py` single-session dedup+artifact creation

**Status: CORRECT.** Lines 286-331 of `clean.py` combine the exact-dedup check (step 5), S3 write (step 9), and artifact creation (step 10) in a single `with get_session()` block, mirroring `parse.py`'s session discipline. The near-dup LSH scan retains its own read-only session block (lines 241-276) since it is advisory-only.

### WR-02 — `uri_to_key()` used in chunk API/CLI

**Status: CORRECT.** Both `chunk_endpoint` (api/app.py:568-569) and `cmd_chunk` (cli/app.py:267-268) now import `uri_to_key` from `knowledge_lake.pipeline.utils` and delegate to it. Malformed URIs raise `ValueError` instead of `IndexError`, which is caught by the existing `except ValueError` handlers.

### WR-03 — `tika_server_url` added to `Settings`

**Status: CORRECT (but introduces CR-01 below).** Three-part fix applied: `settings.py` has `tika_server_url: str = "http://localhost:9998"` at line 173; `tika_parser.py` has `__init__(self, tika_server_url)` storing `self._endpoint`; `resolver.py`'s `parse_with_fallback` injects `tika_server_url=settings.tika_server_url` when name == "tika". The config injection is correct. Side effect: `parse_with_fallback` now uses its own inline `entry_points()` loop instead of calling `resolve()`, breaking the test mock targets (see CR-01 below).

### WR-04 — `_uri_to_key` moved to `pipeline/utils.py`

**Status: CORRECT.** `pipeline/utils.py` exists with the canonical `uri_to_key` implementation and full docstring. Both `parse.py` (line 18) and `clean.py` (line 23) import it as `_uri_to_key`. No local copies remain.

### WR-05 — `ParseResponse`/`CleanResponse` schema descriptions corrected

**Status: CORRECT.** `ParseResponse.artifact_id` description reads `"Parsed document artifact ID (doc_...)."` (line 259) and `CleanResponse.artifact_id` reads `"Cleaned document artifact ID (doc_...)."` (line 287). Both now match the `"doc"` prefix assigned by `ids.py`.

### WR-06 — `_resolve_with_kwargs()` extracted in `resolver.py`

**Status: CORRECT.** `_resolve_with_kwargs(group, name, **kwargs)` is defined at lines 193-220. `get_embedder` (line 243), `get_vectorstore` (line 263), and `get_discovery` (line 285) all delegate to it. The loop body and LookupError message are maintained in one place for those three functions. `get_parser` and `get_crawler` correctly continue using the simpler `resolve()` since they require no constructor kwargs.

---

## Critical Issues

### CR-01: `test_fallback_chain.py` — all four tests patch a dead code path after WR-03 refactor

**File:** `tests/unit/test_fallback_chain.py:84`, `109`, `128`, `146`

**Issue:** Before the WR-03 fix, `parse_with_fallback` called `resolve(GROUP_PARSERS, parser_name)` to obtain each parser. All four tests in this file mock that path:

```python
with patch("knowledge_lake.plugins.resolver.resolve", side_effect=_side_resolve):
    parsed_doc, parser_name, quality_score = parse_with_fallback(...)
```

After the WR-03 fix, `parse_with_fallback` was changed to use its own inline `entry_points(group=GROUP_PARSERS)` loop (resolver.py lines 113-128) so it could inject `tika_server_url` via constructor kwargs. `resolve()` is no longer in the call path for this function. The `patch` on `resolve` now patches a function that `parse_with_fallback` never calls, so the mock `_side_resolve` is never invoked.

Concrete failure trace for `test_fallback_stops_on_first_success` (chain=["a","b"]):
1. Patch is applied to `resolve` — has no effect on `parse_with_fallback`.
2. `parse_with_fallback` calls real `entry_points(group="knowledge_lake.parsers")`.
3. No registered entry point has name "a" — `for/else` fires `raise LookupError("a")` — caught — continue.
4. No registered entry point has name "b" — same — continue.
5. `raise ValueError("All parsers in chain exhausted...")` — test fails with unexpected `ValueError`.

Three tests fail this way: `test_fallback_stops_on_first_success`, `test_fallback_on_low_quality`, and `test_unavailable_parser_skipped`. `test_all_parsers_exhausted_raises` passes accidentally (the real chain is exhausted because no mock parsers are registered, but for the wrong reason — the test is supposed to verify that a parser that raises `RuntimeError` causes fallback-then-exhaustion, not that entry-point lookup fails for every parser).

**Fix:** Change the patch target from `resolve` to `entry_points` in all four tests:

```python
# Replace:
with patch("knowledge_lake.plugins.resolver.resolve", side_effect=_side_resolve):

# With:
from importlib.metadata import entry_points as real_entry_points

def _mock_entry_points(group):
    if group != "knowledge_lake.parsers":
        return real_entry_points(group=group)
    # Return fake entry-point objects whose .name matches "a", "b", "missing"
    class FakeEP:
        def __init__(self, name, factory):
            self.name = name
            self._factory = factory
        def load(self):
            return self._factory
    ep_map = {"a": mock_a_class, "b": mock_b_class}
    return [FakeEP(n, f) for n, f in ep_map.items()]

with patch("knowledge_lake.plugins.resolver.entry_points", side_effect=_mock_entry_points):
    ...
```

Alternatively, since `mock_a` and `mock_b` are already callable (MagicMock), each FakeEP's `load()` can return a factory that returns the mock when called with no args (or with tika kwargs).

---

## Info

### IN-01: Four artifact types share "doc" prefix — IDs are not self-describing for document artifacts

**File:** `src/knowledge_lake/ids.py` (not in this review's file list — carried from iter1)

**Issue:** `raw_document`, `parsed_document`, `cleaned_document`, and `bronze_document` all map to the `"doc"` prefix. Logs and CLI output cannot distinguish a raw artifact from a cleaned one by prefix alone. The stated purpose of type-prefixed IDs is operability. Carried forward — not addressed in iter1.

**Fix:** Assign distinct prefixes (e.g., `"raw"`, `"prs"`, `"cln"`, `"brz"`) or document the single-prefix design as intentional.

---

### IN-02: Boilerplate regex matches bare integers — risks stripping meaningful numeric content

**File:** `src/knowledge_lake/pipeline/clean.py:38-39`

**Issue:** The pattern `r"^(?:Page \d+ of \d+|\d+)\s*$"` with `re.MULTILINE` will strip any line whose entire content is one or more digits. In healthcare regulatory documents this removes numbered list items, standalone footnote numbers, dosage values on their own line, and structured table values. The adjacent `Page N of M` guard is necessary; the bare-integer alternative is overly aggressive.

**Fix:** Narrow the bare-integer branch, e.g. to match only small footer-style numbers:
```python
re.compile(r"^(?:Page \d+ of \d+|\d{1,3})\s*$", re.MULTILINE)
```
Or anchor it to common page-footer context only.

---

### IN-03: `test_encoding_errors_lower_score` passes for the wrong reason

**File:** `tests/unit/test_quality_scorer.py:46`

**Issue:** Line 46 reads:
```python
text_garbled = ("a" * 160) + ("" * 40)  # 20% replacement chars
```
`("" * 40)` evaluates to an empty string, not to 40 Unicode replacement characters `�`. `text_garbled` is therefore `"a" * 160` — 40 characters shorter than `text_clean`. The assertion `score_clean >= score_garbled` holds because of the length difference (shorter text → lower `text_length_score`), not because of encoding errors. The test gives false assurance that `encoding_score` works. The adjacent test `test_encoding_errors_lower_score_with_replacement_chars` uses the correct `"" * 40` (literal `�`).

**Fix:**
```python
text_garbled = ("a" * 160) + ("�" * 40)  # explicit U+FFFD replacement chars
```

---

_Reviewed: 2026-07-05_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
_Iteration: 2_
