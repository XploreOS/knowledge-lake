# Phase 9: Storage Segmentation - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-09
**Phase:** 9-storage-segmentation
**Mode:** `--auto` — all gray areas auto-selected; recommended defaults chosen without interactive prompts.
**Areas discussed:** Domain parameter threading, Object tagging pattern, Gold-zone domain key, Dedup/lineage backward safety

---

## Domain parameter threading

| Option | Description | Selected |
|--------|-------------|----------|
| Pass `domain` as kwarg from callers | Callers resolve domain via `get_domain_for_source()` and pass it to `put_raw`/`put_bronze`; storage layer stays pure | ✓ |
| Resolve domain inside `put_raw`/`put_bronze` | Storage layer queries registry internally to get domain | |
| Pre-compute domain-scoped key before calling `put_raw` | Caller builds the full key and passes it in, bypassing the key-construction layer | |

**Auto-selected:** Pass `domain: Optional[str] = None` kwarg from callers (recommended default)
**Notes:** Storage layer must not call registry (crossing layer boundary). Domain resolved in pipeline functions within the active `get_session()` block, then passed down. `_unclassified` fallback applied at key-construction time.

---

## Object tagging pattern

| Option | Description | Selected |
|--------|-------------|----------|
| Inline `Tagging=` in `put_object` | Tags and write are atomic; single call; boto3 supports `Tagging` parameter natively | ✓ |
| Separate `put_object_tagging()` call | Separate call after write; risks partial state (object written, tags failed) | |
| No tagging in `put_object`; tag after | Same problem as above | |

**Auto-selected:** Inline `Tagging=` in `put_object` with best-effort fallback (recommended default)
**Notes:** Tags are convenience metadata — must not abort write. If `put_object` fails due to tagging, retry without `Tagging` parameter and log warning. `_format_tags()` helper builds URL-encoded tag string.

---

## Gold-zone domain key

| Option | Description | Selected |
|--------|-------------|----------|
| Thread existing `domain` filter kwarg into key | No new params; domain already present in export function signatures | ✓ |
| Add new `export_domain` kwarg separate from filter | Explicit distinction between filter domain and key domain | |
| Always use `_unclassified` for gold zone | Simpler; avoids threading | |

**Auto-selected:** Thread existing `domain` filter kwarg into key; `_unclassified` when None (recommended default)
**Notes:** Export functions already receive `domain` as a filter. Re-using it as the key segment is zero-cost and consistent. Multi-domain exports (domain=None) fall back to `_unclassified`.

---

## Dedup/lineage backward safety

| Option | Description | Selected |
|--------|-------------|----------|
| Preserve existing no-op ordering; forward-only | `get_artifact_by_hash` before key construction; no migration | ✓ |
| Backfill existing keys to new format | Copy-forward all objects; update storage_uris in registry | |
| Dual-read (try new key, fall back to old) | Read old format if new key misses | |

**Auto-selected:** Preserve existing no-op ordering; forward-only (recommended default)
**Notes:** STORE-01 explicitly forbids backfill (WORM immutability). Existing artifacts keep their original `storage_uri`. Registry remains the source of truth for locating objects.

---

## Claude's Discretion

- `_format_tags` helper location (module-level vs static method in `StorageBackend`)
- URL-encoding implementation (`urllib.parse.urlencode` is standard)
- Exact `ClientError` error codes to catch for tagging fallback (broad catch with warning is acceptable)
- Whether `get_domain_for_source` is called at function entry or inside `get_session()` block — must be inside session

## Deferred Ideas

- Backfill of existing raw/bronze/silver objects to domain-scoped keys (REQUIREMENTS.md anti-pattern — explicitly out of scope)
- Per-domain S3 bucket segmentation (single-bucket with domain prefix is the correct Phase 9 scope)
- Tag-based S3 lifecycle policies (tags enable this as future ops work)
- Multi-domain export batching with per-domain gold objects (future enhancement)
