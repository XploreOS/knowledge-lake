# Technology Stack: v2.5 PageIndex Plugin Integration

**Project:** Knowledge Lake Framework - v2.5 Milestone
**Researched:** 2026-07-13
**Scope:** Stack additions for PageIndex tree indexing, OpenKB wiki compilation, two-stage query routing

## Executive Summary

The v2.5 milestone adds tree-based reasoning retrieval alongside the existing vector RAG pipeline. Key finding from research: **PageIndex uses `litellm.completion()` / `litellm.acompletion()` internally** (verified in `pageindex/utils.py`) -- it already speaks our LLM gateway language natively. OpenKB is a CLI application (Click-based, openai-agents-powered) -- we adopt its *architecture* (tree-then-wiki compilation pattern) but NOT its package as a dependency. Two-stage routing requires no external library; it is straightforward business logic on top of existing search infrastructure.

**Net new runtime dependencies: 4** (pageindex, PyPDF2, pymupdf, markitdown). Plus 1 optional utility (json-repair).

---

## New Dependencies (ADD)

### Core: Tree Indexing

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| pageindex | ==0.3.0.dev3 | Tree-based hierarchical document indexing | Core of the PageIndex system. Builds document tree structures via LLM-guided analysis. Uses litellm internally (verified in source). The `PageIndexClient` API (index/retrieve) is only available in 0.3.x, not the stable 0.2.8. OpenKB v0.4.4 pins this exact version. MIT license, 34k GitHub stars. |
| PyPDF2 | ==3.0.1 | PDF page text extraction (PageIndex hard dep) | PageIndex imports `PyPDF2.PdfReader` in `page_index.py` and `utils.py` for page-level text extraction. Deprecated (successor: `pypdf`) but PageIndex requires it. Accept as transitive; isolate behind our plugin boundary. Final release, no further changes. |
| pymupdf | >=1.26.4,<2 | PDF image extraction (PageIndex dep) | PageIndex imports pymupdf for extracting images from PDF pages. Also enables future multimodal wiki compilation (figures in wiki pages). |

### Core: Wiki Compilation (OpenKB-inspired)

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| markitdown[docx,pptx,xlsx,xls] | ==0.1.5 | Non-PDF file-to-markdown conversion for wiki pipeline | Microsoft's lightweight converter. Handles Word, PowerPoint, Excel for the short-document wiki path (docs under the page threshold that don't need PageIndex tree indexing). Docling is better for PDFs but markitdown is faster/lighter for office formats in the compilation pipeline. Python >=3.10, MIT license. Pin to 0.1.5 (OpenKB-validated). |

### Supporting (Optional but Recommended)

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| json-repair | >=0.59,<1 | Robust JSON recovery from LLM wiki output | Wiki compilation generates structured JSON (summaries, concepts, entities) that may be malformed from LLM output. Complements existing ENRICH-07 partial-JSON recovery (different pipeline stage). Lightweight, pure Python. |

### Transitive (no explicit pin needed)

| Technology | Pulled By | Status |
|------------|-----------|--------|
| python-dotenv 1.2.2 | pageindex | Loads .env for API keys. Lightweight, no conflicts with our pydantic-settings approach. |
| pyyaml | pageindex | Already in our deps (>=6.0,<7). Compatible. |

---

## Dependencies NOT to Add

| Package | Why NOT |
|---------|---------|
| **openkb** (0.4.4) | Click-based CLI app that pulls openai-agents, trafilatura, prompt_toolkit, watchdog, portalocker. We want the *architecture* (compile docs into interlinked wiki), not the CLI tooling. Our Typer CLI, LiteLLM gateway, and Dagster orchestration replace its runtime. Apache-2.0 lets us study and reimplement patterns. |
| **openai-agents** (0.18.2) | OpenKB's agent framework for multi-step wiki compilation. We don't need an agent loop -- sequential LiteLLM calls with our existing `litellm.completion()` patterns suffice for wiki page generation. Adds 15+ transitive deps (griffe, websockets, mcp SDK conflict risk). |
| **trafilatura** (2.1.0) | Web content extraction for OpenKB. We already have Crawl4AI + Scrapy producing clean markdown from web sources. Redundant. |
| **click** (8.4.x) | OpenKB's CLI framework. We use Typer. Already installed as a transitive dep of Typer but we do not depend on it for our code. |
| **watchdog** (6.0.0) | Filesystem monitoring for OpenKB's `openkb watch`. We use Dagster sensors for scheduling. Already installed as transitive but unused directly. |
| **semantic-router** | Query routing library. Overkill -- our routing is a binary/ternary decision (chunk vs tree vs both), not a many-route dispatch. Adds embedding overhead per query. |
| **LlamaIndex** | Has TreeIndex module but couples to its entire retrieval framework. PageIndex is purpose-built for this and already LiteLLM-native. |

---

## Existing Dependencies: No Version Bumps Required

| Package | Current | PageIndex Needs | Compatible? |
|---------|---------|-----------------|-------------|
| litellm | 1.92.0 | Tested on 1.84.0 (requirements.txt pin) | YES -- PageIndex uses only `litellm.completion()`, `litellm.acompletion()`, `litellm.drop_params = True`. All stable API since 1.x. Forward-compatible. |
| pyyaml | >=6.0,<7 | 6.0.2 (pinned in requirements.txt) | YES -- within our range. |
| Qdrant client | 1.18.0 | Not used by PageIndex | N/A -- Stage 1 is our existing code. |
| Docling | 2.112.0 | Not used by PageIndex | N/A -- parallel path: Docling parses for our pipeline, PageIndex reads PDFs directly for tree generation. |
| sentence-transformers | 5.6.0 | Not used by PageIndex | N/A -- still used for Stage 1 dense embeddings. |
| openai | 2.44.0 (transitive) | PageIndex does NOT import openai SDK | N/A -- no conflict. |
| pydantic | 2.13.4 | Not imported by pageindex | N/A -- used only in our wrapper code. |

---

## Integration Architecture

### How PageIndex Routes Through Our LiteLLM Proxy

PageIndex's `utils.py` calls `litellm.completion(model=model, messages=messages, temperature=0)` directly. It strips a `litellm/` prefix from model names. To route through our proxy:

```python
# In our PageIndex wrapper plugin (before any PageIndex calls):
import litellm
litellm.api_base = settings.litellm_url       # e.g. http://localhost:4000
litellm.api_key = settings.litellm_api_key     # e.g. sk-local-noauth

# PageIndex client initialization:
from pageindex import PageIndexClient
client = PageIndexClient(
    model="strong_model",          # Our task alias (resolved by LiteLLM proxy)
    retrieve_model="cheap_model",  # Our task alias for retrieval
    workspace=str(workspace_path), # Local temp dir for tree JSON
)
```

The `PageIndexClient.__init__` sets `OPENAI_API_KEY` env var from its `api_key` param, but `litellm.completion()` uses `litellm.api_base` and `litellm.api_key` when set globally -- our proxy configuration takes precedence over the env var. This is the same pattern our existing enrichment code uses.

### PageIndex API Surface (What We Use)

```python
from pageindex import PageIndexClient

# Index a document (builds tree via LLM calls):
client = PageIndexClient(model="strong_model", workspace="/tmp/trees")
doc_id = client.index("path/to/document.pdf")
# Also supports: client.index("path/to/doc.md", mode="md")

# Retrieve (deterministic tree traversal -- no LLM in retrieve.py itself):
from pageindex import get_document, get_document_structure, get_page_content
metadata = get_document(client.documents, doc_id)        # JSON string
structure = get_document_structure(client.documents, doc_id)  # Tree without text
content = get_page_content(client.documents, doc_id, "5-7")   # Page content
```

Key insight: **`retrieve.py` is purely deterministic** (dict lookup + DFS traversal). The "agentic" retrieval in PageIndex's examples uses the OpenAI Agents SDK to wrap these 3 tools in an LLM loop -- but we can achieve the same with a simple LiteLLM call that picks which pages to fetch based on the tree structure.

### Where PageIndex Fits in the Pipeline

```
Existing pipeline (unchanged):
  raw -> parse (Docling) -> clean -> chunk -> embed -> index (Qdrant) -> search

New parallel path (additive):
  raw -> tree_index (PageIndex) -> store tree JSON (silver zone, S3)
                                     |
  query -> router -+-> [chunk path] -> Qdrant hybrid search -> results
                   |
                   +-> [tree path]  -> Stage 1: Qdrant doc-level search
                                    -> Stage 2: Load tree JSON for top docs
                                    -> LLM reads structure, picks pages
                                    -> Return precise page content
```

### Two-Stage Retrieval Flow

```
1. Query arrives at router
2. Router classifies: chunk | tree | two_stage
3. If two_stage:
   a. Stage 1 (fast): Qdrant hybrid search, group by source_id, top-K docs
   b. Stage 2 (precise): For each shortlisted doc:
      - Load tree_index JSON from silver zone
      - LLM examines tree structure (titles + summaries)
      - LLM picks relevant page ranges
      - Fetch page content from tree
   c. Return combined results with tree-search provenance
```

### Wiki Compilation (OpenKB Architecture, Our Implementation)

We reimplement OpenKB's core compilation loop without its package:

| Doc Size | Conversion | LLM Work | Output |
|----------|-----------|----------|--------|
| Short (<20 pages) | markitdown -> markdown | Single LLM call: summary + concepts + entities | wiki pages in gold zone |
| Long (>=20 pages) | PageIndex -> tree index | LLM reads tree, generates summary + concepts per major section | wiki pages in gold zone |

Cross-linking: Entity extraction from enrichment metadata (already in our pipeline) feeds `[[wikilinks]]` between wiki pages. Sequential LiteLLM calls, orchestrated by Dagster.

---

## Plugin Protocol Extension

### New Plugin Type: TreeIndexerPlugin

```python
@runtime_checkable
class TreeIndexerPlugin(Protocol):
    """Protocol for tree-based document indexing."""
    
    name: str
    
    def build_tree(
        self, pdf_path: str, *, model: str = "strong_model"
    ) -> dict:
        """Build hierarchical tree index from a document.
        Returns: JSON-serializable tree with nodes containing
        title, node_id, start_page, end_page, summary, children.
        """
        ...
    
    def tree_retrieve(
        self, tree: dict, query: str, *, model: str = "cheap_model"
    ) -> list[dict]:
        """LLM-guided retrieval over a tree index.
        Returns: List of {page, content, reasoning} dicts.
        """
        ...
```

### New Artifact Types

| Artifact Type | Zone | Format | Description |
|---------------|------|--------|-------------|
| `tree_index` | silver | JSON | PageIndex tree structure for a document |
| `wiki_page` | gold | Markdown | Individual compiled wiki page (summary, concept, or entity) |
| `wiki_manifest` | gold | JSON | Index of all wiki pages with cross-link graph |

### Entry Points

```toml
[project.entry-points."knowledge_lake.tree_indexers"]
pageindex = "knowledge_lake.plugins.builtin.pageindex_plugin:PageIndexTreeIndexer"
```

---

## Version Pinning Strategy

```toml
# pyproject.toml additions (dependencies list)
dependencies = [
    # ... existing deps unchanged ...
    
    # PageIndex tree indexing (v2.5)
    "pageindex==0.3.0.dev3",          # Pre-release pin (PageIndexClient API only in 0.3.x)
    "PyPDF2==3.0.1",                  # PageIndex hard dep (deprecated but final release)
    "pymupdf>=1.26.4,<2",            # PageIndex image extraction
    
    # Wiki compilation (v2.5)
    "markitdown[docx,pptx,xlsx,xls]==0.1.5",  # Office format -> markdown (OpenKB-validated)
    "json-repair>=0.59,<1",           # Robust LLM JSON parsing for wiki output
]
```

**Why pin `pageindex==0.3.0.dev3` exactly:**
- Pre-release (`.dev3`); behavior may change between dev versions
- OpenKB v0.4.4 (the production wiki system) validates this exact version
- The stable release (0.2.8) lacks `PageIndexClient` class and `md_to_tree` function
- VectifyAI explicitly recommends "bump deliberately after vetting each release"
- MIT license allows vendoring the 6 source files if upstream breaks

**Why accept PyPDF2 despite deprecation:**
- PageIndex's `page_index.py` and `utils.py` import `PyPDF2.PdfReader` directly
- Migrating to `pypdf` requires patching upstream (different import path)
- Final release (3.0.1, Dec 2022) -- frozen, no surprise breaking changes
- Isolate behind our TreeIndexerPlugin protocol boundary

**Why pin markitdown to 0.1.5 (not latest 0.1.6):**
- OpenKB v0.4.4 pins 0.1.5 specifically
- 0.1.6 is one minor patch ahead (May 2026 vs the OpenKB June pin)
- Conservative: use the version validated by the ecosystem we're integrating with
- Can bump to 0.1.6 after validating no breaking changes in office format conversion

---

## Dependency Conflict Analysis

| Concern | Risk | Mitigation |
|---------|------|------------|
| PyPDF2 vs pypdfium2 (installed via Docling) | NONE | Different packages entirely. PyPDF2 is pure Python PDF reader. pypdfium2 wraps PDFium C library. Coexist without conflict. |
| litellm version gap (PageIndex tested 1.84, we have 1.92) | LOW | Only uses `litellm.completion()` and `litellm.acompletion()` with `temperature=0`. These are the most stable APIs in litellm. Tested `drop_params=True` global setting which is also stable since 1.x. |
| markitdown vs Docling (both handle PDFs) | NONE | Different roles: Docling = primary pipeline parser (deep structure, tables, OCR, reading order). markitdown = lightweight office-format converter for wiki compilation of non-PDF formats (docx, xlsx, pptx). For PDFs, PageIndex handles its own reading. |
| pymupdf installation size (~50MB) | LOW | One-time install cost. Required by PageIndex. Docling uses pypdfium2 (different backend). Both coexist. |
| pageindex pre-release stability | MEDIUM | Pin exactly. Wrap behind protocol. MIT license allows vendoring 6 files (`__init__.py`, `client.py`, `config.yaml`, `page_index.py`, `page_index_md.py`, `retrieve.py`, `utils.py`) if upstream introduces breaking changes. |
| json-repair vs ENRICH-07 partial recovery | NONE | Complementary: ENRICH-07 handles truncated output from enrichment LLM calls. json-repair handles wiki compilation output (different pipeline stage, different failure modes). |
| python-dotenv vs pydantic-settings | NONE | python-dotenv is a transitive dep of pageindex. pydantic-settings can optionally use it but doesn't conflict. Both read .env files but pydantic-settings takes precedence for our code. |
| `uv` resolution of pre-release | LOW | `uv pip install "pageindex==0.3.0.dev3"` requires `--prerelease=allow` flag or explicit `==` pin in pyproject.toml. uv handles this with `tool.uv.prerelease = "if-necessary-or-explicit"` or explicit pin. |

---

## Configuration Additions

### New Settings Models

```python
class TreeIndexSettings(BaseModel):
    """PageIndex tree indexing configuration (v2.5).
    
    Env pattern: KLAKE_TREE_INDEX__*
    """
    
    enabled: bool = True
    """Enable tree indexing for documents above page_threshold."""
    
    page_threshold: int = 20
    """Documents >= this many pages get tree-indexed (mirrors OpenKB default)."""
    
    model_alias: str = "strong_model"
    """LiteLLM task alias for tree generation (needs reasoning capability)."""
    
    retrieve_model_alias: str = "cheap_model"
    """LiteLLM task alias for tree-guided retrieval steps."""
    
    add_summaries: bool = True
    """Generate per-node LLM summaries (more tokens at index time but better retrieval)."""
    
    max_tokens_per_node: int = 20000
    """Maximum token budget per tree node (PageIndex default)."""
    
    max_pages_per_node: int = 10
    """Maximum pages a single tree node can span (PageIndex default)."""


class WikiSettings(BaseModel):
    """OpenKB-style wiki compilation configuration (v2.5).
    
    Env pattern: KLAKE_WIKI__*
    """
    
    enabled: bool = True
    """Enable wiki compilation from ingested documents."""
    
    model_alias: str = "strong_model"
    """LiteLLM task alias for wiki compilation (needs structured output)."""
    
    budget_usd: float = 10.0
    """Spend cap for wiki compilation (multiple LLM calls per document)."""
    
    output_prefix: str = "gold/wiki"
    """S3 key prefix for compiled wiki artifacts."""
    
    cross_link: bool = True
    """Enable cross-document concept and entity linking."""
    
    short_doc_converter: str = "markitdown"
    """Converter for short documents (< page_threshold). 'markitdown' or 'docling'."""


class RouterSettings(BaseModel):
    """Two-stage query routing configuration (v2.5).
    
    Env pattern: KLAKE_ROUTER__*
    """
    
    strategy: Literal["auto", "chunk_only", "tree_only", "two_stage"] = "auto"
    """Routing strategy.
    - 'auto': heuristic/LLM decides per query
    - 'chunk_only': always Qdrant chunk search (v2.0 behavior, backward-compatible)
    - 'tree_only': always PageIndex tree retrieval
    - 'two_stage': always Qdrant doc-select then tree retrieval
    """
    
    auto_classifier: Literal["heuristic", "llm"] = "heuristic"
    """How 'auto' classifies queries. 'heuristic' = rule-based (zero cost, deterministic-first).
    'llm' = single cheap_model call per query."""
    
    stage1_top_k: int = 5
    """Number of candidate documents from Stage 1 (Qdrant) to pass to Stage 2."""
    
    tree_traversal_max_steps: int = 5
    """Maximum LLM reasoning steps during tree traversal (cost guard)."""
```

---

## Environment Variables (New)

| Variable | Default | Purpose |
|----------|---------|---------|
| `KLAKE_TREE_INDEX__ENABLED` | `true` | Enable/disable tree indexing |
| `KLAKE_TREE_INDEX__PAGE_THRESHOLD` | `20` | Min pages for tree indexing |
| `KLAKE_TREE_INDEX__MODEL_ALIAS` | `strong_model` | Model for tree generation |
| `KLAKE_TREE_INDEX__ADD_SUMMARIES` | `true` | Generate node summaries |
| `KLAKE_WIKI__ENABLED` | `true` | Enable/disable wiki compilation |
| `KLAKE_WIKI__BUDGET_USD` | `10.0` | Wiki compilation spend cap |
| `KLAKE_WIKI__CROSS_LINK` | `true` | Cross-document linking |
| `KLAKE_ROUTER__STRATEGY` | `auto` | Query routing strategy |
| `KLAKE_ROUTER__AUTO_CLASSIFIER` | `heuristic` | Auto-routing method |
| `KLAKE_ROUTER__STAGE1_TOP_K` | `5` | Docs passed to Stage 2 |

---

## Docker Compose Additions

**None required.** PageIndex, markitdown, pymupdf, and json-repair are pure Python libraries. They connect to our existing LiteLLM proxy container for model calls. No new services needed.

---

## LLM Cost Model for v2.5 Features

| Operation | Model Alias | Est. Cost/Call | Frequency | Budget Source |
|-----------|-------------|----------------|-----------|---------------|
| Tree node summary | strong_model | ~$0.003/node | Once per section at index time | LlmSpend table (existing) |
| Tree structure generation | strong_model | ~$0.01/document | Once per document at index time | LlmSpend table |
| Tree traversal step | cheap_model | ~$0.001/step | 3-5 steps per query per shortlisted doc | LlmSpend table |
| Wiki summary generation | strong_model | ~$0.005/document | Once per document during compilation | wiki budget_usd cap |
| Wiki concept synthesis | strong_model | ~$0.003/concept | Once per concept (may update on new docs) | wiki budget_usd cap |
| Query routing (LLM mode) | cheap_model | ~$0.0003/query | Every query when auto_classifier=llm | LlmSpend table |

Estimates at scale: 100 documents, avg 30 pages each:
- Tree indexing: ~$4-8 one-time (strong_model, summarize all nodes)
- Wiki compilation: ~$5-10 one-time (summaries + concepts + entities)
- Tree retrieval: ~$0.50/100 queries (cheap_model, 5 steps avg)

All within existing budget infrastructure (LlmSpend table + per-feature budget caps).

---

## uv Pre-release Handling

PageIndex 0.3.0.dev3 is a pre-release. uv needs explicit configuration:

```toml
# pyproject.toml
[tool.uv]
prerelease = "if-necessary-or-explicit"
```

Or use the explicit pin `"pageindex==0.3.0.dev3"` which uv resolves as "explicit pre-release request" when using `==` operator with a pre-release version string.

---

## Vendoring Fallback Plan

If PageIndex introduces breaking changes in a future dev release, vendor the package (MIT license, 6 files, ~800 lines total):

```
src/knowledge_lake/plugins/vendor/pageindex/
    __init__.py
    client.py
    config.yaml
    page_index.py
    page_index_md.py
    retrieve.py
    utils.py
```

Modify `utils.py` to remove the `litellm/` prefix stripping (unnecessary when we control the model string) and replace the PyPDF2 import with pypdf (one-line change: `from pypdf import PdfReader` instead of `from PyPDF2 import PdfReader`).

---

## Sources

| Source | Confidence | What It Confirmed |
|--------|------------|-------------------|
| github.com/VectifyAI/PageIndex/blob/main/pageindex/utils.py | HIGH | Uses `litellm.completion()` and `litellm.acompletion()` directly; strips `litellm/` prefix; retries 10x; temperature=0 |
| github.com/VectifyAI/PageIndex/blob/main/pageindex/client.py | HIGH | `PageIndexClient` API: `model`, `retrieve_model`, `workspace` params; `index()` method handles PDF and MD |
| github.com/VectifyAI/PageIndex/blob/main/pageindex/retrieve.py | HIGH | Deterministic retrieval (no LLM): `get_document`, `get_document_structure`, `get_page_content` -- pure dict/tree lookup |
| github.com/VectifyAI/PageIndex/main/requirements.txt | HIGH | Hard deps: litellm==1.84.0, pymupdf==1.26.4, PyPDF2==3.0.1, python-dotenv==1.2.2, pyyaml==6.0.2 |
| github.com/VectifyAI/OpenKB pyproject.toml | HIGH | Pins pageindex==0.3.0.dev3, markitdown[docx,pptx,xlsx,xls]==0.1.5, litellm==1.87.2; Python >=3.10 |
| pypi.org/project/pageindex | MEDIUM | Stable is 0.2.8 (March 2026); pre-release 0.3.0.dev3 (July 10, 2026); Python >=3.7; no declared PyPI deps |
| pypi.org/project/openkb (0.4.4) | HIGH | Python >=3.10; full dep list verified; Apache-2.0 license |
| github.com/microsoft/markitdown | HIGH | v0.1.6 latest (May 2026); Python >=3.10; supports PDF/docx/xlsx/pptx/html/csv; lightweight API (`MarkItDown().convert()`) |
| pypi.org/project/PyPDF2 | HIGH | Deprecated, final version 3.0.1 (Dec 2022), successor is `pypdf` |
| Existing codebase (settings.py, protocols.py, search.py, pyproject.toml) | HIGH | Integration points confirmed: plugin protocol pattern, LiteLLM proxy config, existing hybrid search |
| pypi.org/project/openai-agents (0.18.2) | MEDIUM | Provider-agnostic with `[litellm]` extra; confirms we DON'T need it -- PageIndex works without agents SDK |
