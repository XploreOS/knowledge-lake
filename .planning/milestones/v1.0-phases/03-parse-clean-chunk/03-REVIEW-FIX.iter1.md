---
phase: 03-parse-clean-chunk
fixed_at: 2026-07-05T00:00:00Z
review_path: .planning/phases/03-parse-clean-chunk/03-REVIEW.md
iteration: 1
findings_in_scope: 8
fixed: 8
skipped: 0
status: all_fixed
---

# Phase 03: Code Review Fix Report

**Fixed at:** 2026-07-05
**Source review:** .planning/phases/03-parse-clean-chunk/03-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 8 (2 Critical + 6 Warning)
- Fixed: 8
- Skipped: 0

## Fixed Issues

### CR-01: `chunk_section()` infinite loop — sentence that fits in overlap but not remaining window

**Files modified:** `src/knowledge_lake/pipeline/chunk.py`
**Commit:** `657abd3`
**Applied fix:** Added a guard immediately after computing the overlap window: if `overlap_cost + costs[i] > max_tokens`, force-appends the current sentence to `current_sentences`, adds its cost, and advances `i`. This breaks the infinite loop case where an oversized sentence (cost > max_tokens − overlap_tokens) would otherwise cause the same overlap window to be emitted forever. The comment on the next line was updated from "Do NOT advance i" to "Do NOT advance i otherwise" to reflect the conditional nature of the advance.

---

### CR-02: Dagster `parsed_document` asset silently drops `mime_type` — all non-PDF files parsed as PDF

**Files modified:** `src/knowledge_lake/dagster_defs/assets.py`
**Commit:** `e9ee618`
**Applied fix:** Added `result["mime_type"] = config.mime_type` after the existing `result["raw_artifact_id"]` assignment in `ingest_raw_document`. The downstream `parsed_document` asset already reads `ingest_raw_document.get("mime_type", "application/pdf")` — so this single line ensures the correct MIME type is forwarded to the parse stage instead of always defaulting to `"application/pdf"`.

---

### WR-01: `clean.py` race condition — dedup check and artifact creation in separate sessions

**Files modified:** `src/knowledge_lake/pipeline/clean.py`
**Commit:** `5c2301b`
**Applied fix:** Restructured `clean()` to move the exact-dedup check (previously step 5 in its own session), the S3 write (step 9), and the artifact creation (step 10) into a single `with get_session()` block — mirroring the session discipline already in `parse.py`. Steps 6 (language detection), 7 (MinHash), and 8 (near-dup LSH scan) are performed before this block since they are pure computation or read-only I/O that does not need to be atomic with the write. The near-dup LSH scan retains its own read-only session. A detailed comment in the code explains the atomicity guarantee.

---

### WR-02: `chunk_endpoint` and `cmd_chunk` bypass `_uri_to_key()` — unhandled `IndexError` on malformed URIs

**Files modified:** `src/knowledge_lake/api/app.py`, `src/knowledge_lake/cli/app.py`
**Commit:** `e178fac`
**Applied fix:** Replaced the inline `if not storage_uri.startswith("s3://"):` + `storage_uri.split("/", 3)[3]` pattern in both `chunk_endpoint` (api/app.py) and `cmd_chunk` (cli/app.py) with `from knowledge_lake.pipeline.utils import uri_to_key; key = uri_to_key(storage_uri)`. The shared `uri_to_key` helper raises a descriptive `ValueError` (caught by the existing `except ValueError` blocks) instead of an unhandled `IndexError` when the URI has fewer than 4 `/` separators. Note: WR-04 (creating `pipeline/utils.py`) was applied before this fix to make the import available.

---

### WR-03: Tika server URL hardcoded — not configurable via Settings

**Files modified:** `src/knowledge_lake/config/settings.py`, `src/knowledge_lake/plugins/builtin/tika_parser.py`, `src/knowledge_lake/plugins/resolver.py`
**Commit:** `e2b7afc`
**Applied fix:** Three-part change:
1. `settings.py` — added `tika_server_url: str = "http://localhost:9998"` to `Settings`, overridable via `KLAKE_TIKA_SERVER_URL` env var.
2. `tika_parser.py` — removed module-level `_DEFAULT_TIKA_ENDPOINT` constant; added `__init__(self, tika_server_url: str = "http://localhost:9998") -> None` that stores `self._endpoint`; updated both usages of the constant in `parse()` to use `self._endpoint`.
3. `resolver.py` — updated `parse_with_fallback` to inject `tika_server_url=settings.tika_server_url` when instantiating the `"tika"` parser, mirroring the litellm/qdrant/searxng injection pattern already present for embedder, vectorstore, and discovery plugins.

---

### WR-04: `_uri_to_key()` duplicated verbatim between `parse.py` and `clean.py`

**Files modified:** `src/knowledge_lake/pipeline/utils.py` (new), `src/knowledge_lake/pipeline/parse.py`, `src/knowledge_lake/pipeline/clean.py`
**Commit:** `8867a85`
**Applied fix:** Created `src/knowledge_lake/pipeline/utils.py` with `uri_to_key(uri: str) -> str` — the canonical shared implementation with full docstring. In `parse.py`: added `from knowledge_lake.pipeline.utils import uri_to_key as _uri_to_key` and removed the local function definition (replaced with a one-line comment noting the re-export). In `clean.py`: added the same import and removed the verbatim duplicate function body along with the `# ── Storage URI helper ──` section header. The `_uri_to_key` alias preserves all existing call sites unchanged.

---

### WR-05: `ParseResponse` and `CleanResponse` schema descriptions reference wrong ID prefix

**Files modified:** `src/knowledge_lake/api/schemas.py`
**Commit:** `ed4fc49`
**Applied fix:** Updated field descriptions:
- `ParseResponse.artifact_id`: `"Parsed document artifact ID (art_...)."` → `"Parsed document artifact ID (doc_...)."`
- `CleanResponse.artifact_id`: `"Cleaned document artifact ID (art_...)."` → `"Cleaned document artifact ID (doc_...)."`

These now match the `"doc"` prefix assigned in `ids.py` for both `"parsed_document"` and `"cleaned_document"` artifact kinds.

---

### WR-06: `get_embedder` / `get_vectorstore` / `get_discovery` each inline the entry-point loop

**Files modified:** `src/knowledge_lake/plugins/resolver.py`
**Commit:** `a3a4d11`
**Applied fix:** Extracted a new private helper `_resolve_with_kwargs(group, name, **kwargs)` that contains the single entry-point iteration loop with `LookupError` message. Refactored `get_embedder`, `get_vectorstore`, and `get_discovery` to compute their `kwargs` dict conditionally and delegate to `_resolve_with_kwargs` — each function body shrinks from ~8 lines to 2. The loop body and error message are now maintained in one place. The WR-03 `parse_with_fallback` inline loop also uses this pattern for the `"tika"` parser.

---

## Skipped Issues

None — all 8 in-scope findings were successfully fixed.

---

_Fixed: 2026-07-05_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
