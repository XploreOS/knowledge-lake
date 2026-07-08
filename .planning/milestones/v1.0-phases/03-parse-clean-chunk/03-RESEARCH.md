# Phase 3: Parse, Clean & Chunk - Research

**Researched:** 2026-07-04
**Domain:** Document parsing, text cleaning, deduplication, and token-aware chunking
**Confidence:** HIGH

## Summary

Phase 3 transforms raw documents (already ingested in Phase 2) into clean, citation-traceable chunks. The work extends existing pipeline functions (`parse()`, `chunk()`) and the DoclingParser plugin to support multi-format parsing (PDF, HTML, DOCX, Markdown, CSV, XLSX, JSON, XML), adds a parser fallback chain (Docling -> Unstructured -> Tika), quality scoring, boilerplate removal, language detection, near-duplicate flagging via MinHash, and token-aware chunking with section hierarchy respect.

The existing codebase provides strong foundations: the ParserPlugin protocol, entry-point resolution, content-addressed silver zone storage, and registry artifact creation patterns are all proven from Phases 1-2. The primary engineering work is (1) extending DoclingParser for multi-format, (2) implementing the fallback chain resolver, (3) adding the clean stage, and (4) replacing char-based chunking with token-based chunking using tiktoken.

**Primary recommendation:** Extend the existing DoclingParser to handle all 8 required formats natively (Docling already supports PDF, HTML, DOCX, MD, CSV, XLSX out of the box -- verified), add lightweight JSON/XML parsers as simple built-in plugins, implement the fallback chain as a wrapper around the existing resolver pattern, and use `datasketch` for MinHash dedup (DataTrove has a dependency conflict with huggingface-hub and is better deferred to Phase 5 corpus curation).

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Fallback triggers on exception OR quality gate failure -- if Docling succeeds but produces a quality score below threshold, the next parser in chain is attempted
- **D-02:** Stop on first success -- when a parser passes both checks (no exception AND quality above threshold), that result is used immediately. No redundant multi-parser comparison runs
- **D-03:** Tokenizer for chunk sizing is tiktoken (cl100k_base) -- widely used baseline, fast, lightweight dependency
- **D-04:** Quality scoring uses heuristics + LLM spot-check -- deterministic heuristic score always computed, optional LLM call when score falls in gray zone (configurable band, e.g. 0.3-0.6)

### Claude's Discretion
- Parser chain order configurable via settings (list of parser names in priority order) vs fixed
- Whether all 3 parsers are required deps or optional extras with graceful skip
- Quality threshold: single global number vs per-format
- What happens to low-quality documents (flag-only vs halt)
- Torture-test corpus: checked into repo vs fetched from public URLs
- Default chunk size and overlap
- Table atomicity when tables exceed max chunk size
- Chunk overlap style (heading breadcrumb prefix, raw text overlap, or both)
- MinHash near-dedup scope (corpus-wide vs per-source-then-corpus)
- Boilerplate removal approach
- Near-duplicate action (flag only vs keep canonical + soft-delete rest)
- Language detection behavior (annotate only vs gate on supported languages)

### Deferred Ideas (OUT OF SCOPE)
- None -- discussion stayed within phase scope
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| PARSE-01 | Parse PDF, HTML, DOCX, Markdown, CSV, XLSX, JSON, XML to structured Markdown/tables via Docling | Docling natively supports PDF, HTML, DOCX, MD, CSV, XLSX (verified). JSON/XML need simple built-in parsers |
| PARSE-02 | Fallback chain Docling -> Unstructured -> Tika when primary fails or scores low | Fallback chain resolver pattern, optional extras for heavy deps |
| PARSE-03 | Preserve page numbers, headings, sections, table boundaries | DoclingDocument iterate_items + DocItemLabel types give page provenance, section headers, tables |
| PARSE-04 | Quality score recorded in registry; low scores flag for review | New quality_score column on Artifact, heuristic scoring function |
| PARSE-05 | Torture-test corpus validates parser behavior before bulk ingestion | Fixture-based test corpus with healthcare documents |
| CLEAN-01 | Remove boilerplate, normalize whitespace, preserve citations | Regex-based boilerplate patterns + whitespace normalization |
| CLEAN-02 | Language detection recorded in registry | lingua-language-detector 2.2.0 + new language column |
| CLEAN-03 | Exact (hash) and near-duplicate (MinHash) detection and flagging | xxhash for exact dedup (existing), datasketch for MinHash |
| CHUNK-01 | Section-aware chunking respecting heading hierarchy | Existing section iteration pattern, heading breadcrumb prefix |
| CHUNK-02 | Token-aware with configurable size/overlap per domain pack | tiktoken cl100k_base (verified available), configurable settings |
| CHUNK-03 | Tables chunked atomically -- never split mid-table | Table detection via DocItemLabel.TABLE, atomic chunk handling |
| CHUNK-04 | Every chunk records parent document, section path, page reference | Existing chunk artifact fields: parent_artifact_id, section_path, page_ref |
</phase_requirements>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Multi-format parsing | Pipeline (parse stage) | Plugin (DoclingParser) | Pipeline orchestrates fallback; plugin does the actual conversion |
| Quality scoring | Pipeline (parse stage) | Registry (storage) | Score computed in pipeline, persisted to Artifact metadata |
| Boilerplate removal | Pipeline (clean stage) | -- | Pure text transformation, no external service |
| Language detection | Pipeline (clean stage) | Registry (storage) | Detection in pipeline, result stored in Artifact |
| Near-duplicate detection | Pipeline (clean stage) | Database (PostgreSQL) | MinHash computed in pipeline, dedup status in registry |
| Token-aware chunking | Pipeline (chunk stage) | -- | Pure in-process computation using tiktoken |
| Fallback chain resolution | Plugin resolver | Settings | Resolver iterates configured chain; settings stores order |
| Torture-test validation | Test suite | -- | pytest fixtures with real healthcare documents |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| docling | 2.108.0 | Primary multi-format parser | Already installed; handles PDF, HTML, DOCX, MD, CSV, XLSX natively [VERIFIED: uv run test] |
| tiktoken | 0.13.0 | Token counting for chunk sizing | Already available (transitive dep of litellm); cl100k_base confirmed working [VERIFIED: uv run test] |
| datasketch | 1.10.0 | MinHash near-duplicate detection | Lightweight (no dep conflicts), standard MinHash/LSH implementation [ASSUMED] |
| lingua-language-detector | 2.2.0 | Language detection | Per CLAUDE.md recommended stack; accurate on short text [ASSUMED] |
| xxhash | 3.8.0 | Fast content hashing for exact dedup | Already installed and working [VERIFIED: uv run test] |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| unstructured | 0.23.1 | Fallback parser (2nd in chain) | When Docling fails or scores low; optional extra (heavy: pulls spacy, thinc) [ASSUMED] |
| tika | 3.1.0 | Last-resort parser (3rd in chain) | When both Docling and Unstructured fail; requires Tika server (Docker) [ASSUMED] |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| datasketch for MinHash | DataTrove 0.9.0 minhash | DataTrove requires huggingface-hub<=0.36.2, conflicts with sentence-transformers requiring 1.21.0 [VERIFIED: uv pip install --dry-run] |
| tiktoken cl100k_base | sentencepiece / tokenizers | tiktoken is faster for pure token counting, already available, no model download needed |
| lingua | langdetect | langdetect unmaintained since 2021, less accurate on short text per CLAUDE.md |
| Regex boilerplate removal | trafilatura | trafilatura is for HTML extraction from web pages; our input mix includes PDFs and structured data where it adds no value |

**Installation:**
```bash
# Add to pyproject.toml dependencies
uv add datasketch==1.10.0 lingua-language-detector==2.2.0

# Optional extras (heavy deps, not required for core operation)
# unstructured==0.23.1 tika==3.1.0
```

**Version verification:**
- tiktoken 0.13.0: Already in uv.lock, importable, cl100k_base encoding works [VERIFIED: uv run test]
- datasketch 1.10.0: Available via `uv pip install --dry-run`, no conflicts [VERIFIED: dry-run]
- lingua-language-detector 2.2.0: Available via `uv pip install --dry-run`, no conflicts [VERIFIED: dry-run]
- unstructured 0.23.1: Available but pulls 20+ transitive deps (spacy, thinc, etc.) [VERIFIED: dry-run]
- tika 3.1.0: Lightweight Python client, needs Tika server running [VERIFIED: dry-run]

## Package Legitimacy Audit

| Package | Registry | Age | Downloads | Source Repo | Verdict | Disposition |
|---------|----------|-----|-----------|-------------|---------|-------------|
| tiktoken | PyPI | 3+ yrs | HIGH (OpenAI official) | github.com/openai/tiktoken | OK | Approved (already in lockfile) |
| datasketch | PyPI | 8+ yrs | HIGH | github.com/ekzhu/datasketch | OK | Approved |
| lingua-language-detector | PyPI | 5+ yrs | MEDIUM | github.com/pemistahl/lingua-py | OK | Approved |
| unstructured | PyPI | 3+ yrs | HIGH | github.com/Unstructured-IO/unstructured | OK | Approved (optional) |
| tika | PyPI | 8+ yrs | HIGH | github.com/chrismattmann/tika-python | OK | Approved (optional) |

**Packages removed due to [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

## Architecture Patterns

### System Architecture Diagram

```
Raw Document (S3 raw zone)
    |
    v
[PARSE STAGE] ─────────────────────────────────────────────
    |                                                       |
    v                                                       v
Fallback Chain Resolver                            Quality Scorer
    |                                                       |
    ├─ DoclingParser (primary, multi-format)                |
    ├─ UnstructuredParser (fallback 1, optional)            |
    └─ TikaParser (fallback 2, optional)                   |
    |                                                       |
    v                                                       v
ParsedDoc (text + sections + metadata)     quality_score → Registry
    |
    v                         Silver Zone (S3)
    +──────────────────────→  silver/{source_id}/{hash}.md
    |
    v
[CLEAN STAGE] ──────────────────────────────────────────────
    |
    ├─ Boilerplate removal (regex patterns)
    ├─ Whitespace normalization (preserve citations)
    ├─ Language detection → Registry (lingua)
    └─ Near-duplicate detection (exact hash + MinHash LSH)
    |
    v
CleanedDoc (text + metadata + dedup_status + language)
    |
    v
[CHUNK STAGE] ──────────────────────────────────────────────
    |
    ├─ Section-aware splitting (respect heading hierarchy)
    ├─ Token counting (tiktoken cl100k_base)
    ├─ Table atomicity (never split TABLE items)
    ├─ Heading breadcrumb prefix (context for retrieval)
    └─ Overlap (configurable token overlap between chunks)
    |
    v
Chunk Artifacts → Registry (parent_doc, section_path, page_ref)
```

### Recommended Project Structure
```
src/knowledge_lake/
├── pipeline/
│   ├── parse.py          # Extended: fallback chain + quality scoring
│   ├── clean.py          # NEW: boilerplate, language, dedup
│   └── chunk.py          # Extended: token-aware, table-atomic
├── plugins/
│   ├── protocols.py      # Extended: quality scoring types
│   ├── resolver.py       # Extended: chain resolver function
│   └── builtin/
│       ├── docling_parser.py       # Extended: multi-format
│       ├── unstructured_parser.py  # NEW: optional fallback
│       ├── tika_parser.py          # NEW: optional fallback
│       └── json_xml_parser.py      # NEW: simple JSON/XML
├── config/
│   └── settings.py       # Extended: parse/clean/chunk settings
├── registry/
│   ├── models.py         # Extended: quality_score, language, dedup_status
│   └── alembic/versions/
│       └── 0006_parse_clean_chunk_columns.py  # NEW migration
└── quality/
    └── scorer.py         # NEW: heuristic + optional LLM quality scoring
```

### Pattern 1: Fallback Chain Resolver
**What:** Iterates an ordered list of parser names, trying each until one succeeds with acceptable quality.
**When to use:** When the primary parser fails (exception) or produces a quality score below threshold (D-01).
**Example:**
```python
# Source: CONTEXT.md D-01, D-02
def parse_with_fallback(
    raw: bytes,
    mime_type: str,
    chain: list[str],  # e.g. ["docling", "unstructured", "tika"]
    quality_threshold: float,
    settings: Settings,
) -> tuple[ParsedDoc, str, float]:
    """Try parsers in chain order. Stop on first success (D-02)."""
    for parser_name in chain:
        try:
            parser = resolve_parser(parser_name, settings)
        except LookupError:
            log.warning("parser_not_available", name=parser_name)
            continue  # graceful skip if not installed

        if not parser.can_parse(mime_type):
            continue

        try:
            parsed_doc = parser.parse(raw, mime_type)
        except Exception as exc:
            log.warning("parser_failed", name=parser_name, error=str(exc))
            continue  # exception → try next (D-01)

        score = compute_quality_score(parsed_doc, mime_type)
        if score >= quality_threshold:
            return parsed_doc, parser_name, score
        else:
            log.warning("parser_low_quality", name=parser_name, score=score)
            continue  # quality gate failure → try next (D-01)

    raise ValueError(f"All parsers in chain failed for mime_type={mime_type}")
```

### Pattern 2: Token-Aware Chunking with Table Atomicity
**What:** Splits sections by token count using tiktoken, but never splits tables.
**When to use:** All chunking operations (CHUNK-01 through CHUNK-04).
**Example:**
```python
# Source: CONTEXT.md D-03, PARSE-03
import tiktoken

enc = tiktoken.get_encoding("cl100k_base")

def token_count(text: str) -> int:
    return len(enc.encode(text))

def chunk_section(
    text: str,
    max_tokens: int = 512,
    overlap_tokens: int = 64,
    heading_prefix: str = "",
) -> list[str]:
    """Split text into token-bounded chunks with overlap."""
    if token_count(text) <= max_tokens:
        return [f"{heading_prefix}\n\n{text}".strip() if heading_prefix else text]

    # Split on sentence boundaries, accumulate until max_tokens
    sentences = split_sentences(text)
    chunks = []
    current = []
    current_tokens = token_count(heading_prefix) if heading_prefix else 0

    for sent in sentences:
        sent_tokens = token_count(sent)
        if current_tokens + sent_tokens > max_tokens and current:
            chunk_text = " ".join(current)
            if heading_prefix:
                chunk_text = f"{heading_prefix}\n\n{chunk_text}"
            chunks.append(chunk_text)
            # Overlap: keep last N tokens worth of sentences
            current, current_tokens = _compute_overlap(current, overlap_tokens)
            if heading_prefix:
                current_tokens += token_count(heading_prefix)
        current.append(sent)
        current_tokens += sent_tokens

    if current:
        chunk_text = " ".join(current)
        if heading_prefix:
            chunk_text = f"{heading_prefix}\n\n{chunk_text}"
        chunks.append(chunk_text)

    return chunks
```

### Pattern 3: Quality Scoring Heuristics
**What:** Fast deterministic quality assessment of parse output.
**When to use:** After every parse, synchronously (D-04).
**Example:**
```python
# Source: CONTEXT.md D-04
def compute_quality_score(parsed_doc: ParsedDoc, mime_type: str) -> float:
    """Heuristic quality score 0.0-1.0 for parsed output.

    Factors (weighted):
    - text_length_ratio: actual vs expected length for format (0.3)
    - section_count: has structural sections (0.2)
    - table_extraction: tables found if expected (0.15)
    - encoding_errors: unicode replacement chars ratio (0.2)
    - empty_section_ratio: sections with no text (0.15)
    """
    scores = {}

    # Text length check
    text_len = len(parsed_doc.text)
    scores["text_length"] = min(text_len / 100, 1.0)  # at least 100 chars

    # Section structure
    section_count = len(parsed_doc.sections)
    scores["sections"] = min(section_count / 3, 1.0)  # at least 3 sections

    # Encoding errors (unicode replacement character)
    replacement_ratio = parsed_doc.text.count("�") / max(text_len, 1)
    scores["encoding"] = 1.0 - min(replacement_ratio * 100, 1.0)

    # Empty sections
    if section_count > 0:
        empty = sum(1 for s in parsed_doc.sections if not s.text.strip())
        scores["empty_sections"] = 1.0 - (empty / section_count)
    else:
        scores["empty_sections"] = 0.5

    # Weighted aggregate
    weights = {"text_length": 0.3, "sections": 0.2, "encoding": 0.3, "empty_sections": 0.2}
    return sum(scores[k] * weights[k] for k in weights)
```

### Pattern 4: MinHash Near-Duplicate Detection
**What:** Uses MinHash signatures with LSH for efficient near-duplicate discovery.
**When to use:** After cleaning, across the full corpus (CLEAN-03).
**Example:**
```python
# Source: DataTrove production values (num_perm=128, threshold=0.8)
from datasketch import MinHash, MinHashLSH

def compute_minhash(text: str, num_perm: int = 128) -> MinHash:
    """Compute MinHash signature for a document."""
    m = MinHash(num_perm=num_perm)
    # Shingle the text into 5-grams (words)
    words = text.lower().split()
    for i in range(len(words) - 4):
        shingle = " ".join(words[i:i+5])
        m.update(shingle.encode("utf-8"))
    return m

# LSH index for corpus-wide dedup
lsh = MinHashLSH(threshold=0.8, num_perm=128)
```

### Anti-Patterns to Avoid
- **Hand-rolling tokenizers:** Never count tokens by `len(text.split())` or character division. Use tiktoken directly -- different tokenizers produce vastly different counts for the same text.
- **Splitting tables across chunks:** Tables must be atomic. If a table exceeds max_tokens, it becomes its own oversized chunk (flagged but not split).
- **Synchronous LLM calls in the hot path:** The LLM quality spot-check must be optional and only triggered in the gray zone. Never call LLM for every document.
- **Modifying raw zone:** The clean stage writes to silver zone. Raw zone is immutable (FOUND-04).
- **Loading DataTrove for MinHash only:** DataTrove conflicts with current huggingface-hub version. Use datasketch directly for MinHash/LSH.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Token counting | Character-based approximation | tiktoken cl100k_base | Exact token counts prevent truncation; cl100k_base is the standard baseline |
| MinHash signatures | Custom hash-based fingerprinting | datasketch MinHash + LSH | Proven implementation, handles edge cases in hash collision, band optimization |
| Language detection | Regex-based heuristics | lingua-language-detector | Handles short text, 75+ languages, no API dependency |
| PDF/HTML/DOCX parsing | Custom format readers | Docling DocumentConverter | Layout analysis, table extraction, reading order, formula detection |
| Sentence splitting | Simple regex `split(".")` | Better regex with abbreviation handling | "Dr. Smith" should not split; use `re.split(r'(?<=[.!?])\s+(?=[A-Z])')` with guard patterns |

**Key insight:** Document parsing is deceptively complex -- table boundaries, reading order in multi-column PDFs, OCR for scanned pages, encoding detection. Every "simple" custom parser eventually becomes a maintenance burden as edge cases accumulate.

## Common Pitfalls

### Pitfall 1: Docling Format Detection Requires Correct File Extension
**What goes wrong:** Docling uses file extension to detect format. If you write bytes to a temp file without the correct suffix, it silently fails or picks the wrong parser.
**Why it happens:** The existing DoclingParser already handles this for PDF (writes to `.pdf` temp file), but multi-format extension requires a comprehensive MIME-to-suffix map.
**How to avoid:** Maintain a complete `_mime_to_suffix()` mapping for all supported types. The mapping must cover all 8 required formats.
**Warning signs:** Docling raises `ConversionError: File format` or produces empty markdown.

### Pitfall 2: tiktoken Encoding Overhead on Large Documents
**What goes wrong:** Calling `enc.encode(text)` on a 100KB document for every potential split point is O(n) per call, making chunking O(n^2).
**Why it happens:** Naive implementation counts tokens for the full remaining text at each split decision.
**How to avoid:** Count tokens per sentence/paragraph once, then accumulate counts. Only re-encode when computing overlap boundaries.
**Warning signs:** Chunking a single large document takes >5 seconds.

### Pitfall 3: MinHash Shingle Size Affects Dedup Quality
**What goes wrong:** Too-small shingles (unigrams) produce false positives; too-large shingles (10-grams) miss near-duplicates with minor edits.
**Why it happens:** Shingle size is a precision/recall tradeoff. Healthcare docs often share boilerplate headers/footers that inflate similarity.
**How to avoid:** Use 5-word shingles (standard in DataTrove/FineWeb). Run boilerplate removal BEFORE MinHash computation so shared headers don't cause false matches.
**Warning signs:** >50% of corpus flagged as duplicates, or known duplicates not caught.

### Pitfall 4: Quality Score Gray Zone Amplifies LLM Costs
**What goes wrong:** If the gray zone band is too wide (e.g., 0.2-0.8), most documents trigger the expensive LLM spot-check path.
**Why it happens:** Heuristic scores cluster differently per format -- PDFs score higher on structure, CSVs score lower.
**How to avoid:** Start with a narrow gray zone (0.3-0.5) and tune based on the torture-test corpus results. Make the band configurable per format.
**Warning signs:** LLM spot-check triggered on >20% of documents in the torture test.

### Pitfall 5: Unstructured/Tika Import Errors in Minimal Installations
**What goes wrong:** ImportError crashes the fallback chain if unstructured or tika aren't installed.
**Why it happens:** These are optional heavy dependencies. Production deployments may not have them.
**How to avoid:** Use lazy imports with try/except in the parser plugins. The fallback chain resolver must gracefully skip unavailable parsers (log warning, continue to next).
**Warning signs:** LookupError from resolver when running without optional deps.

### Pitfall 6: Heading Breadcrumb Prefix Inflates Token Count
**What goes wrong:** A deep heading hierarchy prefix like "HIPAA > Administrative Safeguards > Access Control > Standard" consumes 20+ tokens per chunk, reducing effective content.
**Why it happens:** Every chunk gets the full path prepended for citation context.
**How to avoid:** Limit breadcrumb depth to 2-3 levels. Store full path in metadata (payload) rather than in chunk text. Only prepend the immediate parent heading as text context.
**Warning signs:** Chunks with 30%+ of token budget consumed by breadcrumb.

## Code Examples

### Extending DoclingParser for Multi-Format
```python
# Source: Verified via uv run tests of Docling 2.108.0 format support
from docling.datamodel.base_models import InputFormat

_MIME_TO_INPUT_FORMAT = {
    "application/pdf": InputFormat.PDF,
    "text/html": InputFormat.HTML,
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": InputFormat.DOCX,
    "text/markdown": InputFormat.MD,
    "text/csv": InputFormat.CSV,
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": InputFormat.XLSX,
}

_MIME_TO_SUFFIX = {
    "application/pdf": ".pdf",
    "text/html": ".html",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "text/markdown": ".md",
    "text/csv": ".csv",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/json": ".json",
    "application/xml": ".xml",
    "text/xml": ".xml",
}
```

### Registry Schema Extension (Alembic Migration)
```python
# Source: Existing patterns in registry/models.py
"""Add quality_score, language, dedup_status to artifacts table."""

def upgrade() -> None:
    op.add_column("artifacts", sa.Column("quality_score", sa.Float, nullable=True))
    op.add_column("artifacts", sa.Column("language", sa.String(16), nullable=True))
    op.add_column("artifacts", sa.Column("dedup_status", sa.String(32), nullable=True))
    # dedup_status values: NULL (not checked), 'unique', 'exact_dup', 'near_dup'
```

### Settings Extension for Parse/Clean/Chunk Config
```python
# Source: Existing settings.py pattern (pydantic-settings, KLAKE_ prefix)
class ParseSettings(BaseModel):
    """Parser chain and quality scoring configuration."""
    chain: list[str] = ["docling", "unstructured", "tika"]
    quality_threshold: float = 0.4
    quality_gray_zone: tuple[float, float] = (0.3, 0.6)
    llm_spot_check: bool = True

class CleanSettings(BaseModel):
    """Cleaning and dedup configuration."""
    minhash_num_perm: int = 128
    minhash_threshold: float = 0.8
    minhash_shingle_size: int = 5

class ChunkSettings(BaseModel):
    """Token-aware chunking configuration."""
    max_tokens: int = 512
    overlap_tokens: int = 64
    tokenizer: str = "cl100k_base"
    heading_breadcrumb_depth: int = 2
```

### Boilerplate Removal Patterns
```python
# Source: Common patterns in healthcare document processing [ASSUMED]
import re

BOILERPLATE_PATTERNS = [
    # Page headers/footers
    re.compile(r"^(Page \d+ of \d+|^\d+$)", re.MULTILINE),
    # Cookie notices and privacy banners
    re.compile(r"(?i)(this site uses cookies|accept all cookies|privacy policy).*$", re.MULTILINE),
    # Navigation elements (from HTML crawls)
    re.compile(r"(?i)^(home|about|contact|sitemap|skip to (?:main )?content)$", re.MULTILINE),
    # Repeated disclaimers
    re.compile(r"(?i)^(disclaimer|copyright \d{4}).*$", re.MULTILINE),
]

def remove_boilerplate(text: str) -> str:
    """Remove common boilerplate patterns while preserving citations."""
    for pattern in BOILERPLATE_PATTERNS:
        text = pattern.sub("", text)
    # Normalize whitespace (collapse multiple blank lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Character-based chunking | Token-aware chunking (tiktoken) | 2023-2024 | Prevents silent truncation in LLM context windows |
| Fixed chunk sizes | Semantic/section-aware chunking | 2024 | Better retrieval quality by respecting document structure |
| Simple text dedup (exact hash) | MinHash + exact hash | Standard practice | Catches paraphrased/reformatted duplicates |
| Single parser | Parser chain with quality scoring | Emerging 2024-2025 | Handles the long tail of document formats gracefully |

**Deprecated/outdated:**
- Character-based chunking (MAX_CHUNK_CHARS=1200): Being replaced by token-based in this phase
- Single-parser assumption: Extended to fallback chain

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | datasketch 1.10.0 is the correct package for MinHash/LSH | Standard Stack | Low -- well-established package, 8+ years old |
| A2 | 512 tokens is a good default chunk size for all-MiniLM-L6-v2 (384-dim) | Code Examples | Medium -- may need tuning; MiniLM has 256 token training max but handles 512 in practice |
| A3 | 5-word shingles are optimal for healthcare document dedup | Pitfall 3 | Low -- standard practice from DataTrove/FineWeb; can be tuned |
| A4 | Unstructured 0.23.1 API: `partition()` function for format-agnostic parsing | Architecture | Medium -- API may have changed; verify at implementation time |
| A5 | Tika Python client 3.1.0 uses `tika.parser.from_buffer()` for bytes parsing | Architecture | Low -- stable API, but requires Tika server running |
| A6 | Boilerplate regex patterns cover healthcare document headers/footers | Code Examples | Medium -- may need expansion based on torture-test results |
| A7 | Quality gray zone 0.3-0.6 is narrow enough to avoid excessive LLM calls | Pitfall 4 | Medium -- depends on score distribution; tune on torture-test |

## Open Questions (RESOLVED)

1. **JSON/XML format handling without native Docling support**
   - What we know: Docling supports specific XML schemas (USPTO, JATS, XBRL) but not generic XML. Generic JSON is only supported as Docling's own format.
   - What's unclear: Whether to write simple built-in parsers (json.loads + recursive text extraction) or rely on Unstructured for these formats.
   - RESOLVED: Write minimal JSON/XML parsers as built-in plugins (`JsonXmlParser`) since the parsing logic is trivial (extract text fields, preserve structure as markdown). This avoids requiring heavy optional deps for simple formats. Plans: 03-01 Task 2.

2. **Table atomicity when table exceeds max_tokens**
   - What we know: Tables must never be split (CHUNK-03). But healthcare tables (ICD-10 code lists, drug formularies) can be very large.
   - What's unclear: Best handling for oversized tables -- keep as single oversized chunk, or truncate with continuation metadata?
   - RESOLVED: Keep as single oversized chunk (flag in metadata: `oversized=True`). Downstream consumers (embedding, retrieval) handle truncation at their layer. This preserves atomicity per the requirement. Plans: 03-03 Task 1.

3. **Torture-test corpus: source of healthcare documents**
   - What we know: Need at least 1 PDF (complex layout), 1 HTML, 1 DOCX, 1 CSV/XLSX, 1 JSON/XML.
   - What's unclear: Whether to use real public healthcare docs (licensing) or synthetic test fixtures.
   - RESOLVED: Use real public domain healthcare documents (HHS PDFs, CDC HTML pages, CMS CSV files) as fixtures checked into `tests/fixtures/torture_test/`. All sources are US government = public domain. Plans: 03-01 Task 3.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.12 | Core runtime | Yes | 3.12.3 | -- |
| uv | Package management | Yes | 0.11.26 | -- |
| Docling | PARSE-01 | Yes (in lockfile) | 2.108.0 | Unstructured fallback |
| tiktoken | CHUNK-02 | Yes (transitive dep) | 0.13.0 | -- |
| xxhash | CLEAN-03 (exact dedup) | Yes | 3.8.0 | -- |
| datasketch | CLEAN-03 (MinHash) | No (needs install) | 1.10.0 | -- |
| lingua-language-detector | CLEAN-02 | No (needs install) | 2.2.0 | -- |
| unstructured | PARSE-02 (fallback) | No (optional) | 0.23.1 | Skip in chain |
| tika | PARSE-02 (fallback) | No (optional) | 3.1.0 | Skip in chain |
| Tika Server (Java) | tika package | No | -- | Skip tika in chain |
| PostgreSQL | Registry | Yes (Docker) | 16+ | -- |
| MinIO | Silver zone storage | Yes (Docker) | -- | -- |

**Missing dependencies with no fallback:**
- datasketch 1.10.0 -- must be added to pyproject.toml (CLEAN-03 requirement)
- lingua-language-detector 2.2.0 -- must be added to pyproject.toml (CLEAN-02 requirement)

**Missing dependencies with fallback:**
- unstructured 0.23.1 -- optional extra; fallback chain gracefully skips if not installed
- tika 3.1.0 -- optional extra; fallback chain gracefully skips if not installed
- Tika Server -- not needed if tika is skipped in chain

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.x + pytest-asyncio |
| Config file | pyproject.toml [tool.pytest.ini_options] |
| Quick run command | `uv run pytest tests/unit/ -x -q` |
| Full suite command | `uv run pytest tests/ -v` |

### Phase Requirements to Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| PARSE-01 | Multi-format parsing (8 formats) | unit + integration | `uv run pytest tests/unit/test_parse_multiformat.py -x` | No -- Wave 0 |
| PARSE-02 | Fallback chain (exception + quality gate) | unit | `uv run pytest tests/unit/test_fallback_chain.py -x` | No -- Wave 0 |
| PARSE-03 | Structure preservation (page, heading, table) | integration | `uv run pytest tests/integration/test_parse_structure.py -x` | No -- Wave 0 |
| PARSE-04 | Quality scoring + registry recording | unit | `uv run pytest tests/unit/test_quality_scorer.py -x` | No -- Wave 0 |
| PARSE-05 | Torture-test corpus passes quality gates | integration | `uv run pytest tests/integration/test_torture_corpus.py -x` | No -- Wave 0 |
| CLEAN-01 | Boilerplate removal + whitespace normalization | unit | `uv run pytest tests/unit/test_clean.py -x` | No -- Wave 0 |
| CLEAN-02 | Language detection recorded in registry | unit | `uv run pytest tests/unit/test_clean.py::test_language_detection -x` | No -- Wave 0 |
| CLEAN-03 | Exact + near-duplicate detection | unit + integration | `uv run pytest tests/unit/test_dedup.py -x` | No -- Wave 0 |
| CHUNK-01 | Section-aware heading hierarchy chunking | unit | `uv run pytest tests/unit/test_chunk_token.py -x` | No -- Wave 0 |
| CHUNK-02 | Token-aware configurable size/overlap | unit | `uv run pytest tests/unit/test_chunk_token.py::test_token_limits -x` | No -- Wave 0 |
| CHUNK-03 | Table atomicity (never split) | unit | `uv run pytest tests/unit/test_chunk_token.py::test_table_atomic -x` | No -- Wave 0 |
| CHUNK-04 | Chunk records parent, section_path, page_ref | unit | `uv run pytest tests/unit/test_chunk_token.py::test_chunk_metadata -x` | No -- Wave 0 |

### Sampling Rate
- **Per task commit:** `uv run pytest tests/unit/ -x -q`
- **Per wave merge:** `uv run pytest tests/ -v`
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/unit/test_parse_multiformat.py` -- covers PARSE-01
- [ ] `tests/unit/test_fallback_chain.py` -- covers PARSE-02
- [ ] `tests/unit/test_quality_scorer.py` -- covers PARSE-04
- [ ] `tests/unit/test_clean.py` -- covers CLEAN-01, CLEAN-02
- [ ] `tests/unit/test_dedup.py` -- covers CLEAN-03
- [ ] `tests/unit/test_chunk_token.py` -- covers CHUNK-01 through CHUNK-04
- [ ] `tests/integration/test_parse_structure.py` -- covers PARSE-03
- [ ] `tests/integration/test_torture_corpus.py` -- covers PARSE-05
- [ ] `tests/fixtures/torture_test/` -- test corpus directory

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No | -- |
| V3 Session Management | No | -- |
| V4 Access Control | No | -- |
| V5 Input Validation | Yes | Pydantic models for all config; MIME type validation before parsing; file size limits |
| V6 Cryptography | No | -- (hashing for dedup is not security-critical) |

### Known Threat Patterns for Document Processing

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Malicious PDF/DOCX (zip bombs, macro execution) | Tampering | Docling runs in temp directory with size limits; no macro execution; timeout on parse |
| Path traversal in temp file creation | Information Disclosure | TemporaryDirectory context manager (already in DoclingParser); never construct paths from user input |
| Denial of service via large documents | Denial of Service | File size check before parsing (configurable max, e.g., 100MB); timeout on parse operation |
| XML External Entity (XXE) injection | Information Disclosure | Use defusedxml or disable external entities in XML parser; Docling handles this internally for its XML formats |
| Content injection via parsed output | Tampering | Parsed output goes to silver zone (content-addressed, immutable); downstream consumers treat it as untrusted text |

## Sources

### Primary (HIGH confidence)
- Docling 2.108.0 format support: Verified via `uv run python` testing all InputFormat enum values and running actual conversions for PDF, HTML, DOCX, MD, CSV, XLSX
- tiktoken 0.13.0 cl100k_base: Verified via `uv run python` import and encoding test
- xxhash 3.8.0: Verified via `uv run python` import and hashing test
- DataTrove huggingface-hub conflict: Verified via `uv pip install --dry-run datatrove` showing version downgrade requirement
- Existing codebase patterns: Read from source files (protocols.py, resolver.py, parse.py, chunk.py, settings.py, models.py)

### Secondary (MEDIUM confidence)
- datasketch 1.10.0 availability: Verified via `uv pip install --dry-run datasketch` (no conflicts)
- lingua-language-detector 2.2.0: Verified via `uv pip install --dry-run` (no conflicts)
- unstructured 0.23.1 dependency weight: Verified via `uv pip install --dry-run` (20+ transitive deps)

### Tertiary (LOW confidence)
- MinHash optimal parameters (num_perm=128, threshold=0.8, shingle_size=5): Based on DataTrove/FineWeb literature [ASSUMED]
- Quality score heuristic weights: Based on document processing best practices [ASSUMED]
- Default chunk size of 512 tokens: Based on embedding model training characteristics [ASSUMED]

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - all core packages verified via actual runtime or dry-run install
- Architecture: HIGH - extends proven existing patterns with minimal new abstractions
- Pitfalls: MEDIUM - based on document processing experience and verified constraints
- Chunk sizing defaults: MEDIUM - depends on embedding model behavior in practice

**Research date:** 2026-07-04
**Valid until:** 2026-08-04 (stable domain; Docling/tiktoken APIs unlikely to change within 30 days)
