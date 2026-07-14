# Phase 16: OpenKB Export - Research

**Researched:** 2026-07-14
**Domain:** Wiki compilation from enrichment metadata, gold-zone export, incremental builds
**Confidence:** HIGH

## Summary

Phase 16 builds a wiki compilation pipeline that transforms enriched documents into an interlinked Markdown knowledge base stored in the gold zone. The phase introduces a new `pipeline/wiki.py` module, a `WikiSettings` configuration submodel, a CLI command (`klake export-wiki`), and an API endpoint (`/export-wiki`). The core logic involves: (1) gathering all enriched documents for a domain, (2) computing IDF-filtered entity cross-links, (3) generating per-document summary pages, cross-document concept pages, and a root index page, (4) writing individual Markdown files to S3, and (5) maintaining a manifest for incremental rebuilds.

This phase is architecturally straightforward -- it follows the well-established export pattern from Phase 5 (`pipeline/export.py`) and the additive-module convention from Phases 13-15. No new external dependencies are needed; all required infrastructure (S3, registry, enrichment metadata) already exists. The primary technical challenge is the IDF computation and incremental rebuild logic, both of which are pure Python with no external library requirements.

**Primary recommendation:** Mirror `pipeline/export.py`'s structure (storage factory, domain segmentation, BytesIO writes) and `pipeline/tree_index.py`'s content-hash caching pattern for the manifest-based incremental rebuild.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- D-01: Wiki pages stored as individual Markdown files in gold zone under `gold/{domain}/wiki/`
- D-02: Page slugs derived deterministically via lowercase + hyphen-separated ASCII normalization; collision disambiguation via content-hash suffix
- D-03: Entity cross-linking uses enrichment metadata `entities` field; entity becomes a wikilink target only if document frequency >= 2 AND IDF passes threshold
- D-04: Concept pages list all documents containing that entity with links back; document pages link forward to qualifying entities
- D-05: Link density controlled by IDF threshold; default tuned for ~5-15 links per document page
- D-06: Wiki manifest (`_manifest.json`) tracks page content hash and dependency list; incremental rebuild identifies changed pages
- D-07: First-time build is full; subsequent runs diff against manifest
- D-08: Per-document summaries assembled from existing enrichment metadata (document_type, keywords, entities, first N tokens of cleaned text) -- no LLM call in default mode
- D-09: Opt-in LLM summary mode gated by `WikiSettings.use_llm_summaries` and LlmSpend budget cap
- D-10: `klake export-wiki` CLI command with --domain (required), --force, --dry-run
- D-11: `/export-wiki` POST endpoint with domain (required) and force (bool, default false)
- D-12: No MCP tool for wiki export in this phase
- D-13: Each wiki page is a separate S3 object (not bundled archive)
- D-14: Gold-zone wiki key pattern: `gold/{domain}/wiki/{page_type}/{slug}.md`
- D-15: Downloadable archive via `--archive` CLI flag; .tar.gz written as additional gold-zone artifact

### Claude's Discretion
- Exact module structure within `pipeline/wiki.py` (single file vs. package)
- Specific Markdown formatting of document and concept pages (headings, frontmatter)
- The exact IDF computation method (standard log-based IDF vs. simpler frequency ratio)
- Whether concept pages include a brief inline summary or only document links
- The archive format details (flat vs. preserving the type-prefix directory structure)

### Deferred Ideas (OUT OF SCOPE)
- Watch mode / auto-update on raw drop (KB-06)
- Wiki lint command (contradictions, orphaned pages, stale content) (KB-07)
- Multi-turn chat grounded in wiki content (KB-08)
- Full-text search over wiki pages
- Custom wiki templates/themes
- Corpus-level meta-tree (TREE-07)
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| KB-01 | System compiles ingested documents into an interlinked wiki of Markdown pages with `[[wikilinks]]` in the gold zone | Core wiki compilation logic in pipeline/wiki.py; D-01/D-13/D-14 key patterns; BytesIO -> put_object S3 write pattern |
| KB-02 | Wiki pages include per-document summaries, cross-document concept pages, and a root index | D-08 deterministic summaries from enrichment metadata; three page types (doc/concept/index) with typed prefixes |
| KB-03 | Entity cross-linking uses IDF-filtered entities from enrichment metadata (only link on specific terms) | D-03/D-04/D-05 IDF computation; EnrichmentResult.entities field (max 50 items); document-frequency >= 2 filter |
| KB-04 | Wiki compilation is incremental -- adding a new source rebuilds only affected pages, not the full wiki | D-06/D-07 manifest-based tracking; SHA256 content hashes; dependency graph for concept pages |
| KB-05 | Wiki export is available via CLI (`klake export-wiki`) and API endpoint | D-10/D-11 additive CLI command + POST endpoint; mirror existing export patterns |
</phase_requirements>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Wiki compilation logic | API / Backend (pipeline) | -- | All computation is server-side; no client involved |
| IDF entity filtering | API / Backend (pipeline) | -- | Pure Python computation over registry data |
| Incremental rebuild (manifest) | API / Backend (pipeline) | Object Storage | Pipeline owns logic; S3 stores manifest |
| Wiki page persistence | Object Storage (S3) | -- | Pages are individual S3 objects in gold zone |
| CLI surface | API / Backend (CLI) | -- | Typer command delegates to pipeline function |
| API surface | API / Backend (FastAPI) | -- | POST endpoint delegates to pipeline function |
| Archive generation | API / Backend (pipeline) | Object Storage | tarfile in-memory, then S3 put_object |

## Standard Stack

### Core (Already in project -- no new installs)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| orjson | latest | JSON serialization for manifest | Already used in export.py, fast JSONL writes |
| structlog | latest | Structured logging | Already used in all pipeline modules |
| hashlib (stdlib) | -- | SHA256 content hashing | Used by tree_index.py for cache keys |
| tarfile (stdlib) | -- | Archive generation | No external dependency needed for .tar.gz |
| io (stdlib) | -- | BytesIO for S3 writes | Established pattern across all pipeline modules |
| re (stdlib) | -- | Slug normalization | Simple ASCII normalization, no library needed |
| math (stdlib) | -- | IDF computation (log) | Standard log-based IDF formula |

### Supporting (Already in project)
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| Pydantic | 2.13.x | WikiSettings model, WikiManifest schema | Settings submodel pattern; manifest validation |
| pydantic-settings | -- | Env-var override via KLAKE_WIKI__ prefix | Part of existing Settings infrastructure |
| SQLAlchemy | 2.0.x | Registry queries for enrichment data | list_artifacts_by_type, get_enriched_artifact_for_parsed |
| FastAPI | 0.139.x | /export-wiki endpoint | Additive POST endpoint |
| Typer | 0.26.x | klake export-wiki command | Additive CLI command |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| stdlib tarfile | shutil.make_archive | shutil writes to filesystem; tarfile works with BytesIO (S3 constraint) |
| Manual IDF | sklearn TfidfVectorizer | Overkill for simple term-frequency count; adds massive dependency |
| Custom slug | python-slugify | Extra dependency for a 3-line function; existing project has no slug library |

**Installation:**
```bash
# No new packages needed -- all libraries already in the project
```

## Package Legitimacy Audit

> No new packages are installed in this phase. All libraries referenced are already project dependencies verified in prior phases.

| Package | Registry | Age | Downloads | Source Repo | Verdict | Disposition |
|---------|----------|-----|-----------|-------------|---------|-------------|
| (none) | -- | -- | -- | -- | -- | -- |

**Packages removed due to [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

## Architecture Patterns

### System Architecture Diagram

```
                           klake export-wiki --domain X
                                      |
                                      v
                    +----------------------------------+
                    |   pipeline/wiki.py               |
                    |   compile_wiki(domain, force)    |
                    +----------------------------------+
                           |              |
            +--------------+              +--------------+
            v                                            v
   +------------------+                      +-------------------+
   | Registry Queries |                      | S3 Manifest Load  |
   | (enriched docs,  |                      | (_manifest.json)  |
   | sources, domains)|                      +-------------------+
   +------------------+                              |
            |                                        v
            v                              +-------------------+
   +------------------+                    | Diff: identify    |
   | IDF Computation  |                    | changed/new docs  |
   | (entity DF/IDF)  |                    +-------------------+
   +------------------+                              |
            |                                        v
            v                              +-------------------+
   +------------------+                    | Rebuild Decision  |
   | Page Generation  |<-------------------| (affected pages)  |
   | - doc pages      |                    +-------------------+
   | - concept pages  |
   | - index page     |
   +------------------+
            |
            v
   +------------------+          +-------------------+
   | S3 Writes        |--------->| gold/{domain}/    |
   | (BytesIO each    |          | wiki/doc/...      |
   |  page + manifest)|          | wiki/concept/...  |
   +------------------+          | wiki/index.md     |
                                 | wiki/_manifest.json|
                                 +-------------------+
```

### Recommended Project Structure
```
src/knowledge_lake/
├── pipeline/
│   └── wiki.py              # Core wiki compilation logic (single file)
├── config/
│   └── settings.py          # + WikiSettings submodel addition
├── cli/
│   └── app.py               # + klake export-wiki command
├── api/
│   ├── app.py               # + /export-wiki POST endpoint
│   └── schemas.py           # + WikiExportRequest/WikiExportResponse
tests/unit/
└── test_wiki.py             # Unit tests for wiki compilation
```

### Pattern 1: Export Pipeline Function
**What:** A public function that gathers data from registry, transforms it, and writes to gold-zone S3.
**When to use:** This is THE pattern for all gold-zone exports in this project.
**Example:**
```python
# Source: pipeline/export.py (existing pattern)
def compile_wiki(
    *,
    domain: str,
    force: bool = False,
    dry_run: bool = False,
    archive: bool = False,
    settings: Settings | None = None,
) -> dict:
    """Compile the wiki knowledge base for a domain (KB-01..05).
    
    Returns dict with keys: pages_created, pages_updated, pages_unchanged,
    concept_pages, manifest_uri
    """
    s = settings or get_settings()
    storage = _make_storage(s)
    # ... gather enrichment data, compute IDF, generate pages, write to S3
```

### Pattern 2: Settings Submodel
**What:** A Pydantic BaseModel nested under Settings with env-var override via KLAKE_WIKI__ prefix.
**When to use:** For all new configuration needed by the wiki compilation.
**Example:**
```python
# Source: config/settings.py (existing pattern, mirrors ExportSettings)
class WikiSettings(BaseModel):
    """Wiki export configuration (KB-01..05).
    
    Nested under Settings as settings.wiki. Environment variable pattern:
    KLAKE_WIKI__MIN_ENTITY_IDF, KLAKE_WIKI__USE_LLM_SUMMARIES, etc.
    """
    min_entity_idf: float = 1.5
    """Minimum IDF score for an entity to get its own concept page (D-03/D-05)."""
    
    min_entity_df: int = 2
    """Minimum document frequency for an entity to qualify (D-03)."""
    
    use_llm_summaries: bool = False
    """Opt-in LLM summary generation (D-09). Deterministic-first."""
    
    summary_excerpt_chars: int = 500
    """First N characters of cleaned text used as lead paragraph (D-08)."""
    
    budget_usd: float = 5.0
    """Spend cap for LLM summaries (mirrors EnrichSettings pattern, D-09)."""
    
    model_alias: str = "cheap_model"
    """LiteLLM task alias for wiki summary calls (D-09)."""
```

### Pattern 3: Content-Hash Incremental Build
**What:** A manifest JSON file stored in S3 alongside the generated artifacts, tracking content hashes and dependencies.
**When to use:** When output must be incrementally rebuilt rather than fully regenerated.
**Example:**
```python
# Source: pipeline/tree_index.py (content_hash caching pattern)
# Manifest structure:
{
    "version": "1",
    "built_at": "2026-07-14T12:00:00Z",
    "entity_idf_scores": {"entity_slug": 2.3, ...},
    "pages": {
        "doc/source-id/doc-slug.md": {
            "content_hash": "sha256:...",
            "depends_on": ["enriched_artifact_id_1"],
            "entities": ["entity-a", "entity-b"]
        },
        "concept/entity-slug.md": {
            "content_hash": "sha256:...",
            "depends_on": ["doc/source-id/doc-a.md", "doc/source-id/doc-b.md"]
        },
        "index.md": {
            "content_hash": "sha256:...",
            "depends_on": ["*"]  # rebuilt if any page changes
        }
    }
}
```

### Pattern 4: Deterministic Slug Generation
**What:** A pure function that converts a title to a filesystem-safe slug for S3 keys and Obsidian filenames.
**When to use:** For all page key derivation (D-02).
**Example:**
```python
import re
import hashlib

def slugify(title: str) -> str:
    """Convert a title to a lowercase hyphen-separated ASCII slug.
    
    Matches the project's existing slugification convention (D-02).
    Obsidian vault compatibility: slug = filename without extension.
    """
    # Lowercase and replace non-alphanumeric with hyphens
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower())
    # Strip leading/trailing hyphens
    slug = slug.strip("-")
    # Collapse multiple hyphens
    slug = re.sub(r"-{2,}", "-", slug)
    return slug or "untitled"


def disambiguate_slug(slug: str, content_hash: str) -> str:
    """Append a short hash suffix if a slug collision is detected (D-02)."""
    suffix = content_hash[:8]
    return f"{slug}-{suffix}"
```

### Pattern 5: IDF Computation
**What:** Compute inverse document frequency for entity terms across the corpus.
**When to use:** For filtering which entities become concept pages (D-03/D-05).
**Example:**
```python
import math

def compute_entity_idf(
    entity_doc_freq: dict[str, int],
    total_docs: int,
) -> dict[str, float]:
    """Compute log-based IDF for each entity.
    
    IDF(t) = log(N / df(t)) where N = total docs, df(t) = docs containing t.
    Higher IDF = more specific term (appears in fewer documents).
    """
    idf_scores = {}
    for entity, df in entity_doc_freq.items():
        if df >= 2:  # D-03: minimum document frequency
            idf_scores[entity] = math.log(total_docs / df)
    return idf_scores
```

### Anti-Patterns to Avoid
- **Writing pages to local filesystem:** All S3 writes must go through BytesIO -> put_object (PROJECT.md constraint). Never use open() in write mode.
- **Full rebuild every time:** Must implement manifest-based diff (D-06/KB-04). Tests must verify incremental behavior.
- **LLM calls in default mode:** Deterministic-first constraint. Default compile_wiki uses only enrichment metadata, no LLM.
- **Hardcoded IDF threshold:** Must be configurable via WikiSettings.min_entity_idf (D-05 env-var pattern).
- **Modifying existing export.py:** This is a NEW module (pipeline/wiki.py), not a modification to existing export logic. Additive-only convention.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| JSON serialization | Custom string concatenation | orjson.dumps() | Already used everywhere; handles encoding edge cases |
| Content hashing | Custom hash function | hashlib.sha256() | Standard, matches tree_index.py pattern |
| Archive creation | Shell tar commands | tarfile (stdlib) with BytesIO | Works with in-memory buffers, no filesystem |
| Slug generation | External python-slugify | 3-line regex function | Zero dependencies; slug logic is trivial |
| Settings env-vars | Manual os.getenv | WikiSettings in pydantic-settings | Automatic KLAKE_WIKI__ resolution |
| S3 key construction | Ad-hoc f-strings | Centralized constant pattern | Matches _GOLD_PREFIX + domain_seg + type hierarchy |

**Key insight:** This phase needs NO new external dependencies. The entire wiki compilation is pure Python data transformation + S3 writes using existing infrastructure.

## Common Pitfalls

### Pitfall 1: BytesIO Encoding for Markdown
**What goes wrong:** Writing str directly to put_object without encoding, or forgetting to seek(0) on BytesIO.
**Why it happens:** put_object expects bytes, not str. Markdown content is generated as str.
**How to avoid:** Always `.encode("utf-8")` before calling put_object. No BytesIO needed for single-page writes -- just pass the encoded bytes directly.
**Warning signs:** `TypeError: a bytes-like object is required` at runtime.

### Pitfall 2: Entity Slug Collisions
**What goes wrong:** Two different entities (e.g., "Type 2 Diabetes" and "Type-2 Diabetes") produce the same slug.
**Why it happens:** Slug normalization collapses whitespace/punctuation differences.
**How to avoid:** Build a slug -> entity mapping during compilation; on collision, apply the content-hash disambiguation suffix (D-02). Track all used slugs in a set.
**Warning signs:** Overwritten concept pages; test with entities that differ only in punctuation.

### Pitfall 3: IDF Threshold Too Low Produces Noise
**What goes wrong:** Common terms like "patient" or "treatment" get concept pages with links to every document.
**Why it happens:** In a healthcare domain, domain-general terms have high DF (appear in many docs) but may still pass a low IDF threshold.
**How to avoid:** Default threshold empirically tuned for ~5-15 links per doc page (D-05). Expose via WikiSettings.min_entity_idf for operator tuning. Add dry-run output showing link counts per page.
**Warning signs:** Index page overwhelmed with concept links; concept pages linking to 80%+ of all documents.

### Pitfall 4: Manifest Race Condition
**What goes wrong:** Two concurrent wiki compilations read the same manifest, both write changes, and one overwrites the other's updates.
**Why it happens:** S3 put is not atomic with read-modify-write.
**How to avoid:** Wiki compilation is an operator-triggered batch operation (not concurrent by design). Add a log warning if manifest timestamps suggest a concurrent build. The CLI/API should not parallelize wiki builds for the same domain.
**Warning signs:** Pages disappearing after rebuild; manifest losing entries.

### Pitfall 5: Enrichment Metadata Not Yet Available
**What goes wrong:** Some documents have been ingested but not yet enriched (no enriched_document artifact). Wiki compilation silently skips them.
**Why it happens:** The pipeline stages are async/independent; enrichment may lag behind ingestion.
**How to avoid:** Log a structured warning for each document with no enrichment data. Include the count of skipped documents in the return dict. Document in CLI output.
**Warning signs:** Wiki missing pages for recently ingested documents; user confusion about "where is my document?"

### Pitfall 6: Wikilink Syntax Incompatibility
**What goes wrong:** Generated `[[wikilinks]]` use slugs that don't match actual filenames, breaking Obsidian resolution.
**Why it happens:** Obsidian resolves wikilinks by filename (without extension); if the link text doesn't match the page's filename, it's a dead link.
**How to avoid:** `[[wikilink]]` target must exactly equal the page filename without `.md` extension. Since slug = filename stem (D-02), links use the slug: `[[concept-slug]]` links to `concept/concept-slug.md`. Document this contract in code comments.
**Warning signs:** Broken links in Obsidian vault import; link targets showing as "not found".

## Code Examples

### Wiki Page Generation (Document Page)
```python
# Pattern: assemble from enrichment metadata (D-08, no LLM)
def _render_doc_page(
    *,
    title: str,
    document_type: str,
    keywords: list[str],
    entities: list[str],
    lead_paragraph: str,
    qualifying_entities: dict[str, str],  # entity -> concept slug
    source_name: str,
    source_url: str | None,
) -> str:
    """Render a per-document wiki page as Markdown."""
    lines = [
        f"# {title}",
        "",
        f"**Type:** {document_type}",
        f"**Source:** {source_name}",
    ]
    if source_url:
        lines.append(f"**URL:** {source_url}")
    lines.extend(["", "## Summary", "", lead_paragraph, ""])
    
    if keywords:
        lines.extend(["## Keywords", ""])
        lines.append(", ".join(keywords))
        lines.append("")
    
    if qualifying_entities:
        lines.extend(["## Related Concepts", ""])
        for entity, slug in sorted(qualifying_entities.items()):
            lines.append(f"- [[{slug}|{entity}]]")
        lines.append("")
    
    return "\n".join(lines)
```

### Incremental Rebuild Logic
```python
# Pattern: manifest diff for incremental build (D-06)
def _identify_changed_pages(
    current_docs: dict[str, str],  # page_key -> content_hash
    manifest: dict,                 # loaded _manifest.json
) -> tuple[set[str], set[str], set[str]]:
    """Compare current state against manifest.
    
    Returns: (new_pages, changed_pages, removed_pages)
    """
    manifest_pages = manifest.get("pages", {})
    manifest_keys = set(manifest_pages.keys())
    current_keys = set(current_docs.keys())
    
    new_pages = current_keys - manifest_keys
    removed_pages = manifest_keys - current_keys
    changed_pages = {
        key for key in (current_keys & manifest_keys)
        if current_docs[key] != manifest_pages[key].get("content_hash")
    }
    return new_pages, changed_pages, removed_pages
```

### CLI Command Pattern
```python
# Pattern: mirrors existing cmd_export (additive command)
@app.command(name="export-wiki")
def cmd_export_wiki(
    domain: str = typer.Option(
        ..., "--domain", "-d", help="Domain to compile wiki for (required)."
    ),
    force: bool = typer.Option(
        False, "--force", "-f", help="Ignore manifest, full rebuild."
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show what would change without writing."
    ),
    archive: bool = typer.Option(
        False, "--archive", help="Also write a .tar.gz archive of the wiki."
    ),
) -> None:
    """Compile an interlinked wiki knowledge base in the gold zone (KB-01..05)."""
    from knowledge_lake.pipeline.wiki import compile_wiki
    
    try:
        result = compile_wiki(domain=domain, force=force, dry_run=dry_run, archive=archive)
    except (ValueError, LookupError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    
    typer.echo("Wiki export complete:")
    typer.echo(f"  pages_created:   {result['pages_created']}")
    typer.echo(f"  pages_updated:   {result['pages_updated']}")
    typer.echo(f"  pages_unchanged: {result['pages_unchanged']}")
    typer.echo(f"  concept_pages:   {result['concept_pages']}")
    typer.echo(f"  manifest_uri:    {result['manifest_uri']}")
    if result.get("archive_uri"):
        typer.echo(f"  archive_uri:     {result['archive_uri']}")
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| GraphRAG entity extraction | IDF-filtered enrichment entities | D-03 (this phase) | Simpler, no new dependency, leverages existing enrichment |
| Full rebuild on every change | Manifest-based incremental | D-06 (this phase) | Scales to large corpora without redundant writes |
| LLM-generated summaries | Deterministic-first from metadata | D-08 (this phase) | Zero cost, fast, no external dependency in default mode |

**Deprecated/outdated:**
- Nothing deprecated -- this is a new capability. However, the existing `klake export` commands (rag-corpus, pretrain, finetune) remain unchanged; `export-wiki` is additive.

## Assumptions Log

> List all claims tagged `[ASSUMED]` in this research.

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | IDF threshold of 1.5 produces ~5-15 links per document page for 28-source healthcare domain | Standard Stack / WikiSettings | Low -- configurable via env var, empirically tunable |
| A2 | Obsidian resolves `[[slug]]` wikilinks against filenames without extension | Architecture Patterns | Medium -- if wrong, link format needs adjustment; verified by Obsidian docs convention |
| A3 | tarfile module can write .tar.gz to BytesIO without intermediate filesystem | Code Examples | Very low -- stdlib documented behavior |
| A4 | Enrichment metadata `entities` field is populated for all enriched documents | Architecture Patterns | Low -- Phase 4 guarantees this; empty list is the fallback |

## Open Questions (RESOLVED)

1. **IDF threshold empirical value**
   - RESOLVED: Default to 1.5 via `WikiSettings.min_entity_idf`; exposed as `KLAKE_WIKI__MIN_ENTITY_IDF` for operator tuning; dry-run output shows link distribution per page (implemented in `compile_wiki`).
   - What we know: D-05 specifies ~5-15 links per doc page; standard log-based IDF with threshold ~1.5 is a reasonable starting point
   - What was unclear: Exact optimal value for the healthcare domain's 28 sources

2. **Wikilink format for Obsidian compatibility**
   - RESOLVED: Use `[[slug|Entity Name]]` in document pages (readable) and `[[doc-slug|Document Title]]` in concept pages. The slug portion matches the filename for resolution; the display text after `|` is shown to the user.
   - What we know: Obsidian resolves `[[filename]]` where filename = stem without extension. CONTEXT.md says "slug = filename without extension"
   - What was unclear: Whether to use `[[slug]]` or `[[slug|Display Name]]` for better readability

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.x with pytest-asyncio |
| Config file | pyproject.toml `[tool.pytest.ini_options]` |
| Quick run command | `pytest tests/unit/test_wiki.py -x` |
| Full suite command | `pytest tests/unit/ -x` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| KB-01 | compile_wiki produces Markdown pages with [[wikilinks]] in gold zone | unit | `pytest tests/unit/test_wiki.py::test_compile_wiki_produces_wikilinks -x` | Wave 0 |
| KB-02 | Output includes doc pages, concept pages, and index page | unit | `pytest tests/unit/test_wiki.py::test_wiki_page_types -x` | Wave 0 |
| KB-03 | Entity cross-linking uses IDF-filtered entities | unit | `pytest tests/unit/test_wiki.py::test_idf_filtering -x` | Wave 0 |
| KB-04 | Incremental rebuild only rebuilds affected pages | unit | `pytest tests/unit/test_wiki.py::test_incremental_rebuild -x` | Wave 0 |
| KB-05 | CLI and API surface available | unit | `pytest tests/unit/test_wiki.py::test_cli_export_wiki -x` | Wave 0 |

### Sampling Rate
- **Per task commit:** `pytest tests/unit/test_wiki.py -x`
- **Per wave merge:** `pytest tests/unit/ -x`
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/unit/test_wiki.py` -- covers KB-01..KB-05
- [ ] Test fixtures: in-memory SQLite + mocked StorageBackend (mirrors test_tree_index.py)

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | -- |
| V3 Session Management | no | -- |
| V4 Access Control | no | -- |
| V5 Input Validation | yes | WikiSettings validated by Pydantic; domain name validated by _DOMAIN_NAME_RE; page slugs sanitized by slugify() |
| V6 Cryptography | no | -- |

### Known Threat Patterns for this phase

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Path traversal via domain name | Tampering | _DOMAIN_NAME_RE regex validation (already exists in api/app.py and cli/app.py) |
| S3 key injection via entity/title strings | Tampering | slugify() strips all non-alphanumeric chars; key = prefix + slugified string only |
| Markdown injection in page content | Information Disclosure | Content sourced from enrichment metadata (already bounded by EnrichmentResult Pydantic model); no user-supplied raw strings in page bodies |
| Denial of service via huge corpus | Denial of Service | IDF threshold limits concept page count; pagination in registry queries; log warnings for large corpora |

## Sources

### Primary (HIGH confidence)
- `src/knowledge_lake/pipeline/export.py` -- verified gold-zone export pattern (BytesIO, put_object, domain segmentation) [VERIFIED: codebase]
- `src/knowledge_lake/pipeline/enrich.py` -- verified EnrichmentResult schema (entities: list[str], max 50) [VERIFIED: codebase]
- `src/knowledge_lake/config/settings.py` -- verified Settings submodel pattern (ExportSettings, TreeSettings) [VERIFIED: codebase]
- `src/knowledge_lake/pipeline/tree_index.py` -- verified content-hash caching and SHA256 pattern [VERIFIED: codebase]
- `src/knowledge_lake/cli/app.py` -- verified CLI command registration pattern (cmd_export) [VERIFIED: codebase]
- `src/knowledge_lake/api/app.py` -- verified API endpoint pattern (export_endpoint) [VERIFIED: codebase]
- `src/knowledge_lake/registry/repo.py` -- verified registry query functions (list_artifacts_by_type, get_enriched_artifact_for_parsed) [VERIFIED: codebase]
- `.planning/phases/16-openkb-export/16-CONTEXT.md` -- locked decisions D-01..D-15 [VERIFIED: project docs]

### Secondary (MEDIUM confidence)
- IDF computation formula: standard information retrieval formula log(N/df) [ASSUMED]
- Obsidian `[[wikilink]]` resolution behavior: filename-based matching [ASSUMED]

### Tertiary (LOW confidence)
- None -- all findings based on verified codebase patterns

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- all libraries already in project; no new installs
- Architecture: HIGH -- mirrors established export.py and tree_index.py patterns exactly
- Pitfalls: HIGH -- derived from specific codebase patterns and CONTEXT.md constraints

**Research date:** 2026-07-14
**Valid until:** 2026-08-14 (stable -- no external dependency changes expected)
