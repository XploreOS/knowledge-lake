---
phase: 16-openkb-export
reviewed: 2026-07-14T00:00:00Z
depth: standard
files_reviewed: 6
files_reviewed_list:
  - src/knowledge_lake/pipeline/wiki.py
  - tests/unit/test_wiki.py
  - src/knowledge_lake/config/settings.py
  - src/knowledge_lake/api/schemas.py
  - src/knowledge_lake/cli/app.py
  - src/knowledge_lake/api/app.py
findings:
  critical: 2
  warning: 4
  info: 2
  total: 8
status: issues_found
---

# Phase 16: Code Review Report

**Reviewed:** 2026-07-14T00:00:00Z
**Depth:** standard
**Files Reviewed:** 6
**Status:** issues_found

## Summary

Reviewed the Phase 16 wiki compilation pipeline (`wiki.py`), its test suite, settings additions, CLI command, and API endpoint. The core compile logic is well-structured with good IDF filtering, manifest-based incremental rebuild, and security-aware slug generation. Two correctness bugs were found in `wiki.py`, both related to the incremental rebuild guarantee: stale pages are never cleaned up from S3, and the slug disambiguation check has a secondary-collision blind spot. Four warnings cover an API capability gap, an uncaught exception class in the CLI, unescaped entity names in wikilinks, and incorrect archive timestamps.

---

## Critical Issues

### CR-01: Removed pages computed but never acted upon — stale S3 objects accumulate indefinitely

**File:** `src/knowledge_lake/pipeline/wiki.py:598-601`
**Issue:** `_identify_changed_pages()` correctly computes `removed_pages` — the set of S3 keys present in the prior manifest but absent from the current build. However, `removed_pages` is assigned and then completely ignored. Nothing in the function ever calls `storage.delete_object(key)` (or equivalent) for removed pages. The updated manifest (line 650) writes only `current_hashes`, so removed pages will no longer appear in future manifests, but their S3 objects remain in the gold zone forever.

Concretely: if an entity drops below `min_entity_df` after a document is removed (or its enrichment updated), the concept page for that entity persists as an unreferenced orphan in `gold/{domain}/wiki/concept/`. A user importing the bucket as an Obsidian vault will see dead concept pages. KB-04 ("incremental rebuild") is documented as manifest-based content-hash diffing — the intent is clearly a clean rebuild, not append-only accumulation.

```python
# Lines 598-601 — removed_pages is computed but discarded:
new_pages, changed_pages, removed_pages = _identify_changed_pages(
    current_hashes, existing_manifest
)
pages_to_write = new_pages | changed_pages
# removed_pages is never referenced again
```

**Fix:** Delete stale S3 objects before writing the updated manifest. After step 9 (write changed pages), add:

```python
# ── 9b. Delete removed pages ──────────────────────────────────────────────
if not dry_run:
    for key in removed_pages:
        try:
            storage.delete_object(key)
        except ClientError as exc:
            log.warning(
                "wiki.compile.delete_failed",
                key=key,
                error=str(exc),
            )
```

If `StorageBackend` does not yet expose `delete_object`, that method must be added. The dry-run path already skips writes at line 610 so it will naturally skip deletes once added to the non-dry-run path. The return dict should also include `"pages_removed": len(removed_pages)` so callers can observe the cleanup.

---

### CR-02: Slug disambiguation does not detect secondary collisions — silent S3 page overwrite

**File:** `src/knowledge_lake/pipeline/wiki.py:464-472`
**Issue:** When building document slugs, the collision check only tests whether `base_slug` is already registered in `used_doc_slugs`. The disambiguated slug produced by `disambiguate_slug(base_slug, content_hash)` is written to `used_doc_slugs` (line 471) but never checked against it.

This creates a silent overwrite scenario:

1. Doc A has `slugify(title) == "foo"`. Registered: `used_doc_slugs["foo"] = A_id`.
2. Doc B has a title that naturally slugifies to `"foo-12345678"` (a title like "Foo 12345678" or "foo-12345678 report"). Registered: `used_doc_slugs["foo-12345678"] = B_id`.
3. Doc C has `slugify(title) == "foo"` (same as A), triggering disambiguation. If C's `content_hash[:8] == "12345678"`, then `disambiguate_slug("foo", C_hash) == "foo-12345678"`.
4. `"foo-12345678"` is **already** in `used_doc_slugs` (from B), but the check at line 467 only tests `base_slug ("foo")`, not the disambiguated form. The duplicate is silently accepted.
5. Both B and C map to the same S3 key `gold/.../wiki/doc/foo-12345678.md`. The later write overwrites the earlier one; one document's page is permanently lost.

The identical flaw exists in the concept-slug registry at lines 479-488.

```python
# Lines 464-472 — disambiguated slug not checked for secondary collision:
for doc in domain_docs:
    title = doc["title"] or f"document-{doc['artifact_id']}"
    base_slug = slugify(title)
    if base_slug in used_doc_slugs:                          # only checks base slug
        slug = disambiguate_slug(base_slug, doc["content_hash"])
    else:
        slug = base_slug
    used_doc_slugs[slug] = doc["artifact_id"]               # registered, but never re-checked
```

**Fix:** After computing the disambiguated slug, check again and iterate until a free slug is found:

```python
for doc in domain_docs:
    title = doc["title"] or f"document-{doc['artifact_id']}"
    base_slug = slugify(title)
    if base_slug not in used_doc_slugs:
        slug = base_slug
    else:
        # Disambiguate and keep appending until the slug is unique.
        content_hash_hex = doc["content_hash"]
        slug = disambiguate_slug(base_slug, content_hash_hex)
        if slug in used_doc_slugs:
            # Fall back to a longer suffix (next 8 chars) to resolve secondary collision.
            artifact_hash = hashlib.sha256(doc["artifact_id"].encode()).hexdigest()
            slug = disambiguate_slug(base_slug, artifact_hash)
    used_doc_slugs[slug] = doc["artifact_id"]
    key = f"{_GOLD_PREFIX}/{domain_seg}/{_WIKI_SEGMENT}/doc/{slug}.md"
    doc_slug_map[doc["artifact_id"]] = (slug, key)
```

Apply the same pattern to the concept slug loop at lines 479-488.

---

## Warnings

### WR-01: API `/export-wiki` silently omits `dry_run` and `archive` parameters — CLI/API capability gap

**File:** `src/knowledge_lake/api/schemas.py:278-295` and `src/knowledge_lake/api/app.py:1271`
**Issue:** `WikiExportRequest` defines only `domain` and `force`. The API handler calls:

```python
result = compile_wiki(domain=body.domain, force=body.force)
```

`dry_run` and `archive` are never forwarded. Users of the REST API cannot perform a dry-run preview of wiki changes, and cannot request a `.tar.gz` archive. The CLI exposes both (`--dry-run`, `--archive`), and the test suite validates them at the CLI level but has no API-level equivalents. This breaks the design principle D-02 ("API is a thin JSON wrapper over the same functions the CLI uses — no behaviour re-implementation").

**Fix:** Add the missing fields to `WikiExportRequest` and forward them in the handler:

```python
# schemas.py
class WikiExportRequest(BaseModel):
    domain: str = Field(..., min_length=1, max_length=100)
    force: bool = Field(default=False)
    dry_run: bool = Field(default=False, description="Preview changes without writing to S3.")
    archive: bool = Field(default=False, description="Also write a .tar.gz archive of all wiki pages.")

# api/app.py wiki_export_endpoint
result = compile_wiki(
    domain=body.domain,
    force=body.force,
    dry_run=body.dry_run,
    archive=body.archive,
)
```

Add corresponding test cases in `TestApiExportWiki` for `dry_run=True` (verifies no S3 writes) and `archive=True` (verifies `archive_uri` returned).

---

### WR-02: CLI `cmd_export_wiki` does not catch `botocore.ClientError` — S3 failures produce unhandled tracebacks

**File:** `src/knowledge_lake/cli/app.py:1098-1106`
**Issue:** `compile_wiki` can raise `botocore.exceptions.ClientError` on S3 failures (e.g., permission denied on manifest fetch, network error during page write, or bucket not found). The CLI handler catches only `(ValueError, LookupError)`:

```python
try:
    result = compile_wiki(domain=domain, force=force, dry_run=dry_run, archive=archive)
except (ValueError, LookupError) as exc:
    typer.echo(f"Error: {exc}", err=True)
    raise typer.Exit(code=1) from exc
```

An S3 `ClientError` will propagate as an unhandled exception, printing a full Python traceback to the terminal instead of a clean error message and exit code 1. Every other S3-touching CLI command has the same gap, but wiki compilation is especially likely to hit it on first run (bucket misconfiguration).

**Fix:**

```python
from botocore.exceptions import ClientError as BotocoreClientError

try:
    result = compile_wiki(domain=domain, force=force, dry_run=dry_run, archive=archive)
except (ValueError, LookupError, BotocoreClientError) as exc:
    typer.echo(f"Error: {exc}", err=True)
    raise typer.Exit(code=1) from exc
```

---

### WR-03: Entity names and document titles in wikilinks are not sanitized — Markdown/wikilink formatting corrupted by `|` or `]]`

**File:** `src/knowledge_lake/pipeline/wiki.py:244` and `wiki.py:281`
**Issue:** Entity names and document titles come from LLM enrichment output. They are inserted verbatim into Obsidian-style wikilinks:

```python
# wiki.py line 244 (doc page concept links)
lines.append(f"- [[{concept_slug}|{entity_name}]]")

# wiki.py line 281 (concept page backlinks)
lines.append(f"- [[{doc_slug}|{doc_title}]]")
```

In Obsidian wikilink syntax `[[target|display]]`, a `|` character inside `entity_name` or `doc_title` acts as a second separator, silently truncating the display text. A `]]` sequence inside those values prematurely closes the wikilink, leaving trailing text as malformed plain Markdown. Titles like `"Insulin | Dosage Guidelines"` or entity names like `"IL-6 [Interleukin-6]"` are realistic outputs from the enrichment LLM.

The same applies in `_render_index_page` at line 324 and the `# {title}` / `# {entity_name}` headings at lines 219 and 272 — a title containing a newline would break the Markdown heading.

**Fix:** Sanitize display text before inserting into wikilinks:

```python
def _sanitize_wikilink_display(text: str) -> str:
    """Strip characters that would break Obsidian wikilink display text."""
    # Replace | (wikilink separator) and remove ]] (wikilink terminator)
    return text.replace("|", "-").replace("]]", "")
```

Apply at all wikilink construction sites:
```python
lines.append(f"- [[{concept_slug}|{_sanitize_wikilink_display(entity_name)}]]")
lines.append(f"- [[{doc_slug}|{_sanitize_wikilink_display(doc_title)}]]")
```

---

### WR-04: `tarfile.TarInfo` mtime not set — all files in archive have epoch-0 timestamps

**File:** `src/knowledge_lake/pipeline/wiki.py:668-672`
**Issue:** When building the `.tar.gz` archive, `TarInfo` objects are constructed without setting `mtime`:

```python
info = tarfile.TarInfo(name=arc_name)
info.size = len(data)
tar.addfile(info, io.BytesIO(data))
```

`TarInfo.mtime` defaults to `0`, which corresponds to 1970-01-01 00:00:00 UTC. Every file in the archive will appear to be from the Unix epoch. When users import the archive into Obsidian or any file manager, sorting/filtering by modification date produces useless results, and sync tools that use mtime (rsync, git-annex) will treat all files as identically old.

**Fix:** Set `mtime` to the current wall-clock time when creating each `TarInfo`:

```python
import time

_now = int(time.time())

# Inside the archive loop:
info = tarfile.TarInfo(name=arc_name)
info.size = len(data)
info.mtime = _now
tar.addfile(info, io.BytesIO(data))
```

Using a single `_now` value captured before the loop keeps all entries consistent within a single archive run.

---

## Info

### IN-01: `from collections import defaultdict` imported inside a function body

**File:** `src/knowledge_lake/pipeline/wiki.py:313`
**Issue:** `defaultdict` is imported at the function body level inside `_render_index_page`, which is called potentially thousands of times in a large corpus. While Python caches module imports and this doesn't cause repeated I/O, placing imports inside frequently-called functions is against the project's (and PEP 8's) convention.

**Fix:** Move `from collections import defaultdict` to the top-level import block (lines 27–43).

---

### IN-02: `DatasetKind` and `ExportKind` are non-functional `str` subclasses — dead code

**File:** `src/knowledge_lake/cli/app.py:405-409` and `cli/app.py:998-1007`
**Issue:** Both classes are defined as plain `str` subclasses with class attributes, not as `enum.Enum` or `str, Enum`:

```python
class DatasetKind(str):
    QA = "qa"
    INSTRUCTION = "instruction"
```

`DatasetKind("foo")` succeeds (it just calls `str("foo")`), so these provide no validation. Neither class is used in any function signature or Typer type annotation — both callers perform manual string checks. These classes are entirely unreferenced dead code.

**Fix:** Either replace with a proper `enum.Enum`:

```python
class DatasetKind(str, enum.Enum):
    QA = "qa"
    INSTRUCTION = "instruction"
```

and use them as Typer argument types for built-in validation, or delete them entirely if manual validation is preferred.

---

_Reviewed: 2026-07-14T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
