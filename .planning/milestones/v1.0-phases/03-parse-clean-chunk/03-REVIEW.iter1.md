---
phase: 03-parse-clean-chunk
reviewed: 2026-07-05T00:00:00Z
depth: standard
files_reviewed: 31
files_reviewed_list:
  - pyproject.toml
  - src/knowledge_lake/api/app.py
  - src/knowledge_lake/api/schemas.py
  - src/knowledge_lake/cli/app.py
  - src/knowledge_lake/config/settings.py
  - src/knowledge_lake/dagster_defs/assets.py
  - src/knowledge_lake/dagster_defs/definitions.py
  - src/knowledge_lake/ids.py
  - src/knowledge_lake/pipeline/chunk.py
  - src/knowledge_lake/pipeline/clean.py
  - src/knowledge_lake/pipeline/parse.py
  - src/knowledge_lake/plugins/builtin/docling_parser.py
  - src/knowledge_lake/plugins/builtin/json_xml_parser.py
  - src/knowledge_lake/plugins/builtin/tika_parser.py
  - src/knowledge_lake/plugins/builtin/unstructured_parser.py
  - src/knowledge_lake/plugins/protocols.py
  - src/knowledge_lake/plugins/resolver.py
  - src/knowledge_lake/quality/__init__.py
  - src/knowledge_lake/quality/scorer.py
  - src/knowledge_lake/registry/alembic/versions/0006_parse_clean_chunk_columns.py
  - src/knowledge_lake/registry/repo.py
  - tests/integration/test_dagster_assets.py
  - tests/integration/test_parse_structure.py
  - tests/integration/test_torture_corpus.py
  - tests/unit/test_chunk_token.py
  - tests/unit/test_clean.py
  - tests/unit/test_dedup.py
  - tests/unit/test_fallback_chain.py
  - tests/unit/test_parse_multiformat.py
  - tests/unit/test_quality_scorer.py
findings:
  critical: 2
  warning: 6
  info: 3
  total: 11
status: issues_found
---

# Phase 03: Code Review Report

**Reviewed:** 2026-07-05
**Depth:** standard
**Files Reviewed:** 31
**Status:** issues_found

## Summary

Phase 03 delivers parse → clean → chunk pipeline stages wired into the Dagster asset graph, CLI, and REST API. The implementation is substantially sound — the fallback chain, quality scorer, MinHash deduplication, and token-aware chunker are all well-reasoned. Two blockers require immediate attention before this code ships: a provable infinite-loop in the token-aware chunker and a silent mime-type drop in the Dagster asset graph that will cause all non-PDF files to be misparsed. Six warnings cover a race condition in the clean stage, missing safety guards in the chunk CLI/API path, a hardcoded Tika URL, and recurring code-duplication patterns.

---

## Critical Issues

### CR-01: `chunk_section()` infinite loop — sentence that fits in overlap but not remaining window

**File:** `src/knowledge_lake/pipeline/chunk.py:124-150`

**Issue:** The sliding-window accumulation loop never advances `i` when it emits a chunk and recomputes the overlap window. If the resulting overlap window is non-empty but the current sentence still cannot fit (i.e., `overlap_cost + costs[i] > max_tokens`), the condition on line 129 fires again on the very next iteration with exactly the same `current_sentences`. The loop then emits the overlap window, recomputes the same overlap, and repeats forever.

Concrete trigger scenario (max_tokens=512, overlap_tokens=64):
1. `current_sentences = [S]` where `cost(S) = 50` (fits in the 64-token overlap budget).
2. Current sentence `i` has `cost = 470` tokens. `50 + 470 = 520 > 512` — cannot fit.
3. Emit `[S]` as a chunk.
4. Overlap computation: `cost(S) = 50 <= 64` so `overlap_sents = [S]`.
5. `current_sentences = [S]`, `current_tokens = 50`. `i` does **not** advance.
6. Back to top: `50 + 470 > 512` AND `[S]` is non-empty — same condition fires.
7. Emit `[S]` again → same overlap → **infinite loop**.

This will hang any worker processing a document that has at least two sentences where one sentence's token cost exceeds `max_tokens - overlap_tokens` (448 tokens at default settings). Long healthcare regulatory sentences or table captions easily reach this threshold.

The guard at line 113 (`if len(sentences) == 1: return [text]`) only protects the single-sentence case; it does not protect against this multi-sentence scenario.

**Fix:**
```python
# After computing overlap_sents / overlap_cost:
current_sentences = overlap_sents
current_tokens = overlap_cost
# Guard: if even the overlap window cannot accommodate the current sentence,
# force-add it to prevent an infinite loop (oversized sentence escapes atomically).
if overlap_cost + costs[i] > max_tokens:
    current_sentences.append(sentences[i])
    current_tokens += costs[i]
    i += 1
```

---

### CR-02: Dagster `parsed_document` asset silently drops `mime_type` — all non-PDF files parsed as PDF

**File:** `src/knowledge_lake/dagster_defs/assets.py:157-160` (ingest) and `195` (parse)

**Issue:** `ingest_raw_document` uses `config.mime_type` when calling `ingest_file` / `ingest_url`, but **never adds it to the returned result dict**. Lines 157-160 add only `collection` and `raw_artifact_id`:

```python
result["collection"] = config.collection
result["raw_artifact_id"] = result["artifact_id"]
return result   # mime_type is NOT in result
```

The downstream `parsed_document` asset reads mime_type on line 195:
```python
mime_type = ingest_raw_document.get("mime_type", "application/pdf")
```

Because the key is absent, this always resolves to `"application/pdf"` regardless of what the user configured. For HTML, DOCX, Markdown, CSV, and XLSX files ingested through the Dagster pipeline (described in comments as the production execution path), `parse_with_fallback` is called with the wrong MIME type, causing `DoclingParser.can_parse("application/pdf")` to return `True` and Docling to treat binary HTML or DOCX bytes as a PDF — producing parse failures or empty/garbage `ParsedDoc` output and failing the quality gate.

The CLI and API `parse` commands are unaffected because they accept `mime_type` as an explicit argument.

**Fix:**
```python
# In ingest_raw_document, add after line 157:
result["mime_type"] = config.mime_type
```

---

## Warnings

### WR-01: `clean.py` race condition — dedup check and artifact creation in separate sessions

**File:** `src/knowledge_lake/pipeline/clean.py:241-340`

**Issue:** The exact-dedup check (lines 242-258, session block 1) and the artifact creation (lines 318-340, session block 3) are in **separate** `with get_session()` blocks separated by expensive I/O: language detection, MinHash computation, and an S3 `put_object`. Two concurrent `clean()` calls for the same document can both pass the dedup check (neither has committed yet), then both attempt to create an artifact with identical `(content_hash, "cleaned_document")`. The unique constraint on the artifacts table prevents silent corruption but surfaces as an unhandled DB integrity error (likely a 500 from the API endpoint).

`parse.py` explicitly addresses this pattern with a comment at lines 94-96: *"Dedup check and artifact creation in a single session block to prevent race conditions (CR-02). Both the read and the write happen within the same session, making the dedup + insert effectively atomic."* `clean.py` does not follow this pattern.

**Fix:** Move the S3 write (`storage.put_object`) and the `create_cleaned_artifact` call into the same `with get_session()` block as the dedup check, mirroring the `parse.py` session discipline:
```python
with get_session() as session:
    existing = registry_repo.get_artifact_by_hash(session, content_hash, "cleaned_document")
    if existing is not None:
        return {...}
    # S3 write is idempotent for same key — safe inside the session block
    storage.put_object(cleaned_key, cleaned_bytes)
    artifact = registry_repo.create_cleaned_artifact(session, ...)
    session.flush()
    result = {...}
```

---

### WR-02: `chunk_endpoint` and `cmd_chunk` bypass `_uri_to_key()` — unhandled `IndexError` on malformed URIs

**File:** `src/knowledge_lake/api/app.py:569` and `src/knowledge_lake/cli/app.py:268`

**Issue:** Both the API `/chunk` endpoint and the CLI `chunk` command extract the S3 key with the raw split:
```python
key = storage_uri.split("/", 3)[3]
```
This bypasses `_uri_to_key()` (defined in `parse.py` and `clean.py`) which validates the `s3://` prefix and raises a descriptive `ValueError`. If `storage_uri` is malformed (e.g., a non-S3 URI or a URI with fewer than 4 `/` separators), `split("/", 3)[3]` raises `IndexError`. The `except ValueError` block at `app.py:577` does **not** catch `IndexError`, so the exception propagates to a 500 response. The CLI's `except (ValueError, LookupError)` handler at `cli/app.py:282` similarly misses `IndexError`.

**Fix:** Replace the manual split with the existing helper (exposed from a shared module to avoid import coupling):
```python
from knowledge_lake.pipeline.parse import _uri_to_key
key = _uri_to_key(storage_uri)  # raises ValueError with clear message on bad URI
```
Also add `IndexError` to the except clauses as a defense-in-depth measure until the above is done.

---

### WR-03: Tika server URL hardcoded — not configurable via Settings

**File:** `src/knowledge_lake/plugins/builtin/tika_parser.py:21` and `88`

**Issue:** `_DEFAULT_TIKA_ENDPOINT = "http://localhost:9998"` is a module-level constant passed directly to `tika_parser.from_buffer(raw, serverEndpoint=_DEFAULT_TIKA_ENDPOINT)`. There is no way to override this URL without modifying the source file. The project CLAUDE.md mandates that `settings.py` is "the single source of truth for all environment/config" and that "no other module should call os.getenv() or read environment variables directly." All other service URLs (`qdrant_url`, `litellm_url`, `searxng_url`, `database_url`) are settable via `Settings`. Tika is an exception with no justification.

**Fix:** Add a `tika_server_url` field to `Settings` (or inject via constructor argument to `TikaParser`), then read it in `parse()`:
```python
# settings.py:
tika_server_url: str = "http://localhost:9998"

# tika_parser.py:
class TikaParser:
    def __init__(self, tika_server_url: str = "http://localhost:9998"):
        self._endpoint = tika_server_url
```

---

### WR-04: `_uri_to_key()` duplicated verbatim between `parse.py` and `clean.py`

**File:** `src/knowledge_lake/pipeline/clean.py:161-172`

**Issue:** The comment at line 163 explicitly says *"Copied from pipeline/parse.py to avoid circular imports."* The function is identical in both files. Any future change (e.g., supporting `gs://` URIs or stricter path validation) must be applied to both files. Circular-import avoidance does not require duplication — the function belongs in a shared utilities module that neither `parse.py` nor `clean.py` imports from.

**Fix:** Move to `src/knowledge_lake/pipeline/utils.py` (new file) and import in both:
```python
# knowledge_lake/pipeline/utils.py
def uri_to_key(uri: str) -> str:
    if not uri.startswith("s3://"):
        raise ValueError(f"Expected s3:// URI, got: {uri!r}")
    parts = uri.split("/", 3)
    if len(parts) < 4 or not parts[3]:
        raise ValueError(f"Cannot extract key from URI: {uri!r}")
    return parts[3]
```

---

### WR-05: `ParseResponse` and `CleanResponse` schema descriptions reference wrong ID prefix

**File:** `src/knowledge_lake/api/schemas.py:259` and `288`

**Issue:** `ParseResponse.artifact_id` carries the description `"Parsed document artifact ID (art_...)"` and `CleanResponse.artifact_id` carries `"Cleaned document artifact ID (art_...)"`. However, `ids.py` maps both `"parsed_document"` and `"cleaned_document"` to the `"doc"` prefix. Actual IDs will start with `"doc_"`, not `"art_"`. OpenAPI schema consumers (SDK generators, documentation portals, integration tests relying on the description text) will encounter a mismatch. The prefix `"art_"` is reserved for the `"artifact"` kind in `ids.py` which is not used by these pipeline stages.

**Fix:**
```python
# schemas.py line 259:
artifact_id: str = Field(description="Parsed document artifact ID (doc_...).")
# schemas.py line 288:
artifact_id: str = Field(description="Cleaned document artifact ID (doc_...).")
```

---

### WR-06: `get_embedder` / `get_vectorstore` / `get_discovery` each inline the entry-point loop instead of using `resolve()`

**File:** `src/knowledge_lake/plugins/resolver.py:201-211`, `230-240`, `249-270`

**Issue:** `resolve(group, name)` exists precisely to encapsulate the entry-point lookup loop and the `LookupError` message. Yet `get_embedder`, `get_vectorstore`, and `get_discovery` each copy this loop verbatim, adding a per-name conditional for constructor arg injection. The loop body and the LookupError message are now maintained in four places. If the entry-point iteration semantics ever change (e.g., handling namespace packages), three copies must be updated.

**Fix:** Extract a `resolve_with_args(group, name, **kwargs)` helper and use it:
```python
def resolve_with_args(group: str, name: str, **kwargs: Any) -> Any:
    for ep in entry_points(group=group):
        if ep.name == name:
            return ep.load()(**kwargs)
    raise LookupError(
        f"No plugin {name!r} registered in entry-point group {group!r}. ..."
    )

def get_embedder(settings):
    kwargs = {"litellm_url": settings.litellm_url} if settings.embedder == "litellm" else {}
    return resolve_with_args(GROUP_EMBEDDERS, settings.embedder, **kwargs)
```

---

## Info

### IN-01: Four artifact types share "doc" prefix — IDs are not self-describing for document artifacts

**File:** `src/knowledge_lake/ids.py:32-41`

**Issue:** `raw_document`, `parsed_document`, `cleaned_document`, and `bronze_document` all map to the `"doc"` prefix. The stated purpose of prefixed IDs is that logs and CLI output are "self-describing." A `doc_` prefix cannot distinguish a raw upload from a parsed or cleaned artifact. Only `chunk` ("chk"), `source` ("src"), `crawl_job` ("job"), and `crawl_state` ("cst") are genuinely distinguishable from the prefix alone.

**Suggestion:** Assign distinct prefixes (e.g., `"raw"`, `"prs"`, `"cln"`, `"brz"`) with a migration to rename existing IDs, or document the current single-prefix design as intentional to avoid confusion.

---

### IN-02: Boilerplate regex matches bare integers — risks stripping meaningful numeric content

**File:** `src/knowledge_lake/pipeline/clean.py:38-39`

**Issue:** The pattern `r"^(?:Page \d+ of \d+|\d+)\s*$"` with `re.MULTILINE` matches any line whose content is only digits. This will remove lines such as numbered list items (`"1"`, `"2"`, `"3"`), standalone footnote numbers, or table values that appear alone on a line. In healthcare regulatory documents, bare numbers may be dosage values, ICD codes, or section identifiers in structured tables.

**Suggestion:** Narrow the bare-integer alternative to avoid collateral removal, e.g., by requiring typical footer context (leading whitespace at line boundaries) or by limiting the pattern to small numbers unlikely to be content (`\d{1,3}` instead of `\d+`).

---

### IN-03: `test_encoding_errors_lower_score` uses empty string instead of U+FFFD replacement character

**File:** `tests/unit/test_quality_scorer.py:46`

**Issue:** Line 46 reads:
```python
text_garbled = ("a" * 160) + ("" * 40)  # 20% replacement chars
```
`"" * 40` evaluates to an empty string in Python (not to 40 Unicode replacement characters `�`). `text_garbled` is therefore `"a" * 160` — shorter than `text_clean = "a" * 200`. The test assertion `score_clean >= score_garbled` passes because the length difference depresses the quality score, not because of encoding errors. The test in the adjacent function `test_encoding_errors_lower_score_with_replacement_chars` correctly uses `"" * 40` (the actual `�` character). This test gives false confidence that the `encoding_score` heuristic works when text length differs.

**Fix:**
```python
text_garbled = ("a" * 160) + ("�" * 40)  # explicit U+FFFD
```

---

_Reviewed: 2026-07-05_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
