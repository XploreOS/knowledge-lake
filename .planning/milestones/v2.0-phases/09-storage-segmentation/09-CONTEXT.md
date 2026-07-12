# Phase 9: Storage Segmentation - Context

**Gathered:** 2026-07-09
**Status:** Ready for planning
**Mode:** `--auto` (gray areas auto-selected, recommended defaults chosen without prompts — every decision below is auditable and revisable before planning)

<domain>
## Phase Boundary

Deliver **domain/source-scoped S3 keys, object tags, and gold-zone segmentation** without breaking content-addressed dedup, lineage, or WORM immutability — and without ever rewriting existing raw objects.

Three requirements in scope:

- **STORE-01** — New objects are written under `{zone}/{domain}/{source_id}/{hash}.{ext}` with a real routed `_unclassified` fallback segment. Existing raw keys are never rewritten (forward-only). The `get_artifact_by_hash` no-op remains ordered before key construction.
- **STORE-02** — Every object write applies S3 object tags — `domain`, `source_name`, `format`, `artifact_type` — within the S3 10-tag limit, as convenience metadata only. The registry remains the source of truth.
- **STORE-03** — The gold zone is segmented by domain and dataset type: `gold/{domain}/rag_corpus/`, `gold/{domain}/pretrain/`, `gold/{domain}/finetune/`.

**Out of scope:** Qdrant hybrid vectors (Phase 10), Dagster re-crawl sensor (Phase 11), MCP/agent surfaces (Phase 12). No backfill of existing raw objects — forward-only.

</domain>

<decisions>
## Implementation Decisions

### STORE-01 — Domain/source-scoped S3 keys

- **D-01:** Key format changes to `{zone}/{domain}/{source_id}/{hash}.{ext}` for raw, bronze, and silver zones. The `_unclassified` segment is the fallback when `domain` is `None` or empty — it is a real routed segment, never an empty string, `//`, or the literal `"None"`.
- **D-02:** `put_raw(source_id, data, ext, session, ...)` gains a new `domain: Optional[str] = None` kwarg. Callers are responsible for resolving domain via `get_domain_for_source(source_id, session)` and passing it in. The storage layer (`s3.py`) never calls the registry — domain is resolved at the calling pipeline function and passed downward.
- **D-03:** Same pattern for `put_bronze(source_id, data, ext, session, *, parent_artifact_id, domain=None)` — domain-scoped bronze key: `bronze/{domain}/{source_id}/{hash}.{ext}`.
- **D-04:** Silver-zone key construction is updated in both pipeline modules:
  - `parse.py`: `silver/{source_id}/{hash}.md` → `silver/{domain}/{source_id}/{hash}.md`
  - `clean.py`: `silver/{source_id}/cleaned/{hash}.md` → `silver/{domain}/{source_id}/cleaned/{hash}.md`
  Both callers resolve domain via `get_domain_for_source()` within their existing `get_session()` block, then pass it to the key-construction line.
- **D-05:** **Dedup/lineage ordering preserved.** The `get_artifact_by_hash` registry no-op must remain ordered BEFORE key construction (already the case in `put_raw` and `put_bronze`). Domain only enters at the key-construction step (after the hash is known and no-op check passes) — not before. This preserves the four-layer WORM contract exactly.
- **D-06:** **Forward-only, no migration.** Existing raw/bronze/silver keys (`{zone}/{source_id}/...`) are never rewritten. New writes use domain-scoped keys. Existing artifacts retain their original `storage_uri` in the registry and continue to be readable. No Alembic migration, no S3 copy-forward, no backfill.

### STORE-02 — S3 object tags on every write

- **D-07:** `put_object(key, data)` gains a new `tags: Optional[dict[str, str]] = None` kwarg. When provided, the dict is URL-encoded via a private helper `_format_tags(tags: dict[str, str]) -> str` and passed to `_client.put_object(Tagging=...)`. Both MinIO and AWS S3 support the `Tagging` parameter natively.
- **D-08:** Tagging is **inline** in the same `put_object` call — not via a separate `put_object_tagging()` call. This is atomic: the object and its tags are written together. A separate tagging call would risk partial state (object written, tags not).
- **D-09:** Four standard tags: `domain`, `source_name`, `format`, `artifact_type`. Tag values are capped at 256 characters (S3 tag value limit). Total tags = 4 (well within the S3/MinIO 10-tag limit). `source_name` and `domain` are resolved by the calling pipeline function and passed alongside other write parameters.
- **D-10:** Tagging is **best-effort only** — a tagging failure MUST NOT abort the object write. If `put_object` fails due to a tagging-related `ClientError` (e.g., permission error, malformed tag), log a warning and retry the same `put_object` call without the `Tagging` parameter. The object must always be written; tags are convenience metadata.
- **D-11:** Tags are populated at each write site:
  - `put_raw` → `{domain, source_name, format: ext, artifact_type: "raw_document"}`
  - `put_bronze` → `{domain, source_name, format: ext, artifact_type: "bronze_document"}`
  - Silver zone (`parse.py`, `clean.py`) → `{domain, source_name, format: ext, artifact_type: "parsed_document" / "cleaned_document"}`
  - Gold zone (`export.py`) → `{domain, format: "parquet" / "jsonl", artifact_type: "rag_corpus" / "pretrain_corpus" / "finetune_dataset"}` — `source_name` omitted for multi-source exports.
  Callers that already have `source_name` from a registry lookup pass it in; callers that don't (gold exports) omit it.

### STORE-03 — Gold-zone domain segmentation

- **D-12:** Gold-zone keys change from `{prefix}/{type}/{id}` to `{prefix}/{domain}/{type}/{id}`. Full key templates:
  - `{s.export.gold_prefix}/{domain}/rag_corpus/{export_id}.parquet`
  - `{s.export.gold_prefix}/{domain}/pretrain/{export_id}.jsonl`
  - `{s.export.gold_prefix}/{domain}/finetune/{dataset_id}.jsonl`
- **D-13:** The `domain` value for gold-zone keys comes from the `domain` filter argument that the export functions already accept (used for filtering which artifacts to export). Thread this same value directly into the key. If `domain=None` (multi-domain export), use `_unclassified` as the segment.
- **D-14:** No new parameters are needed in the export function signatures — the existing `domain` filter kwarg doubles as the key-segment value. The key-construction lines in `export_rag_corpus()`, `export_pretrain_corpus()`, and `export_finetune_dataset()` are the only changes in `export.py`.

### Claude's Discretion

- Whether `_format_tags` is a module-level function or a static method on `StorageBackend` in `s3.py`.
- Exact URL-encoding implementation for the tag string (`urllib.parse.urlencode` is the obvious choice).
- Exact `ClientError` error codes to catch for the tagging fallback (broad `ClientError` + warning log is acceptable; targeting specific codes like `AccessDenied` / `InvalidArgument` is cleaner).
- Whether `get_domain_for_source` is called at the pipeline function entry point or inside the `get_session()` block — must stay inside the session for SQLAlchemy session safety.
- Exact naming of the domain kwarg in `put_raw`/`put_bronze` (`domain` is the clearest choice).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase scope & requirements
- `.planning/ROADMAP.md` §"Phase 9: Storage Segmentation" — goal + 4 success criteria (domain-scoped keys, dedup/lineage preservation, S3 object tags, gold-zone segmentation).
- `.planning/REQUIREMENTS.md` — STORE-01, STORE-02, STORE-03 (full acceptance text with explicit out-of-scope anti-patterns: no WORM raw key rewrites, no eager backfill, no GPU sparse encoders in this phase).

### Prior phase context (load-bearing decisions)
- `.planning/phases/08-crawl-maturation/08-CONTEXT.md` — D-05: `crawl_config` nesting pattern in `Source.config`; storage layer usage in crawl.py.
- `.planning/phases/07-metadata-foundation/07-CONTEXT.md` — D-05: `Source.config` JSON convention for non-columnar metadata; D-03: graceful-degradation contract (new failures must not block core operations).

### Core storage layer (primary change targets)
- `src/knowledge_lake/storage/s3.py` — `StorageBackend.put_raw()` (Layer 1-6 WORM logic); `put_bronze()`; `put_object()` — all three must gain domain + tags support. The `head_object` guard and `get_artifact_by_hash` no-op ordering are load-bearing constraints.

### Pipeline code (secondary change targets)
- `src/knowledge_lake/pipeline/parse.py` — silver key construction at line 100 (`silver/{source_id}/{hash}.md`); domain resolved via `get_domain_for_source` in existing session block.
- `src/knowledge_lake/pipeline/clean.py` — silver/cleaned key at line 300 (`silver/{source_id}/cleaned/{hash}.md`); same session-block pattern as `parse.py`.
- `src/knowledge_lake/pipeline/export.py` — gold-zone keys at lines 323, 409, 523 (`{prefix}/rag_corpus/`, `/pretrain/`, `/finetune/`); domain param already present as a filter, thread into key.
- `src/knowledge_lake/pipeline/ingest.py` — `ingest_url()` calls `storage.put_raw(source.id, data, ext, session, ...)` (line 430, 533); must pass domain kwarg after resolving.
- `src/knowledge_lake/pipeline/crawl.py` — `storage.put_raw(source_id, html, "html", session, ...)` at line 679; `storage.put_bronze(...)` at line 687; both must pass domain.

### Registry pattern to follow
- `src/knowledge_lake/registry/repo.py` — `get_domain_for_source` (line 820) — exact pattern for domain resolution that callers must use. Returns `Optional[str]`; callers use `or "_unclassified"` to apply the fallback.

### Key constraint from REQUIREMENTS.md (out-of-scope anti-patterns)
- `REQUIREMENTS.md` Out of Scope: "Eager backfill / re-keying of existing raw objects — violates raw-zone WORM immutability; STORE-01 is forward-only."
- `REQUIREMENTS.md` Out of Scope: no `get_artifact_by_hash` ordering changes — it stays before key construction.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`put_raw()` WORM layers (s3.py):** six-layer immutability enforcement is correct and must be preserved exactly. The domain kwarg only affects Layer 3 (key construction) — Layers 1, 2 (hash + registry no-op) and Layers 4–6 (head_object guard, S3 write, registry node) are unchanged.
- **`put_bronze()` (s3.py):** mirrors `put_raw` exactly — same six layers, same extension pattern for domain kwarg.
- **`_SILVER_PREFIX` constant (parse.py line 29, clean.py line 39):** both modules define the same `_SILVER_PREFIX = "silver"` constant; key construction uses an f-string with this prefix. The change is a one-line update to each f-string.
- **`_GOLD_PREFIX` constant (export.py line 51):** same pattern — `_GOLD_PREFIX = "gold"`. The three gold key f-strings at lines 323, 409, 523 each need domain inserted.
- **`get_domain_for_source(source_id, session)` (repo.py:820):** returns `Optional[str]`; already called in `index.py`'s session block. Callers that need domain for key construction follow the same pattern: `domain = repo.get_domain_for_source(source_id, session) or "_unclassified"`.

### Established Patterns
- **Domain-as-`_unclassified` fallback:** `or "_unclassified"` is the idiomatic Python expression; never build the key with `None` or empty string.
- **Additive, backward-compatible signatures:** all new kwargs (`domain=None`, `tags=None`) default to non-breaking values so existing callers (tests, other pipeline code) continue working unchanged.
- **Session-boundary rule:** `get_domain_for_source` must be called within the same `get_session()` block that creates/reads artifacts. Do not call it outside a session or pass results across session boundaries.
- **`put_object` is the single write primitive:** all zone-specific writes go through `put_object` at the bottom. Adding `tags` to `put_object` automatically covers all callers.

### Integration Points
- `ingest.py:430, 533` → `storage.put_raw(source.id, data, ext, session, domain=domain_resolved, tags={...})`
- `crawl.py:679` → `storage.put_raw(source_id, html, "html", session, domain=domain_resolved, tags={...})`
- `crawl.py:687` → `storage.put_bronze(..., domain=domain_resolved, tags={...})`
- `parse.py:100` → silver key f-string updated to include domain
- `clean.py:300` → silver/cleaned key f-string updated to include domain
- `export.py:323, 409, 523` → gold key f-strings updated to include domain
- `s3.py:put_object()` → gains `tags: Optional[dict[str, str]] = None` kwarg with inline `Tagging=` + best-effort fallback

</code_context>

<specifics>
## Specific Ideas

- The `_unclassified` fallback segment must literally appear in the S3 key — not an empty string or skipped segment. Key consumers (DuckDB queries, S3 lifecycle policies) must be able to treat `_unclassified` as a normal prefix value.
- `put_raw`'s WORM defense-in-depth comment documents "no S3 If-None-Match:'*' (MinIO gap — FOUND-04)". That constraint is unchanged — the only S3-side change is adding a `Tagging=` parameter, not If-None-Match.
- Gold-zone exports are multi-source by nature; `source_name` tag is omitted for gold writes (no meaningful single source to attribute). The other three tags (`domain`, `format`, `artifact_type`) are always present.
- `_format_tags` encodes tags as a URL-encoded string: `domain=healthcare&source_name=cms&format=html&artifact_type=raw_document` — the format required by the S3 `Tagging` parameter.
- Tag value truncation at 256 chars: `source_name` from the registry is already a short label (e.g., `"cms.gov"`) — truncation guard is a defensive measure, not an expected code path.

</specifics>

<deferred>
## Deferred Ideas

- **Backfill of existing raw/bronze/silver objects to domain-scoped keys** — explicitly out of scope (REQUIREMENTS.md anti-pattern). If uniform S3 lifecycle policies are later required, a copy-forward tool can be written separately.
- **Object lock / WORM bucket policy changes** — unchanged by this phase; current four-layer WORM contract is sufficient.
- **Tag-based S3 lifecycle policies or cost-allocation tagging** — the tags from STORE-02 enable these as a future ops concern; not implemented here.
- **Per-domain S3 bucket segmentation** — not requested; domain prefix within a single bucket is the correct scope for Phase 9.
- **Multi-domain export with per-domain gold objects** — if a single export covers multiple domains, the `_unclassified` segment is used; a future batching mode could split per-domain automatically.

None of the above were requested as scope — captured so they aren't lost.

</deferred>

---

*Phase: 9-storage-segmentation*
*Context gathered: 2026-07-09*
