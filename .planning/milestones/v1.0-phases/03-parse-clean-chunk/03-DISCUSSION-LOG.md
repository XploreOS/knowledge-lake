# Phase 3: Parse, Clean & Chunk - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-04
**Phase:** 03-parse-clean-chunk
**Areas discussed:** Parser fallback chain, Quality scoring, Chunking strategy, Dedup & cleaning scope

---

## Parser Fallback Chain

### Q1: What should trigger fallback?

| Option | Description | Selected |
|--------|-------------|----------|
| Exception only | Only escalate when Docling throws an error or returns empty output | |
| Exception + quality gate | Escalate on error OR when quality score is below a threshold | ✓ |
| You decide | Claude picks the approach | |

**User's choice:** Exception + quality gate
**Notes:** Catches cases where Docling "succeeds" but produces garbage.

### Q2: Should all 3 parsers be required dependencies?

| Option | Description | Selected |
|--------|-------------|----------|
| All required | All three installed in the base image | |
| Optional with skip | Only Docling required, others are extras | |
| You decide | Claude decides based on dependency weight | ✓ |

**User's choice:** You decide

### Q3: Fixed or configurable chain order?

| Option | Description | Selected |
|--------|-------------|----------|
| Fixed order | Docling → Unstructured → Tika always | |
| Configurable list | Settings define parser chain as ordered list | |
| You decide | Claude decides what fits plugin architecture | ✓ |

**User's choice:** You decide

### Q4: Stop on first success or run all?

| Option | Description | Selected |
|--------|-------------|----------|
| Stop on first success | First parser that passes both checks wins | ✓ |
| Run all, pick best | Run all parsers, score each, pick highest quality | |
| You decide | Claude decides the tradeoff | |

**User's choice:** Stop on first success

---

## Quality Scoring

### Q1: Heuristics only or include LLM?

| Option | Description | Selected |
|--------|-------------|----------|
| Heuristics only | Deterministic scoring based on structural signals | |
| Heuristics + LLM spot-check | Heuristic always, LLM on edge cases in gray zone | ✓ |
| You decide | Claude picks based on deterministic-first constraint | |

**User's choice:** Heuristics + LLM spot-check

### Q2: What happens to low-quality documents?

| Option | Description | Selected |
|--------|-------------|----------|
| Flag only, continue pipeline | Mark needs_review, document still proceeds | |
| Flag and halt | Low-quality docs stop at parse stage | |
| You decide | Claude decides based on batch-first architecture | ✓ |

**User's choice:** You decide

### Q3: Single global threshold or per-format?

| Option | Description | Selected |
|--------|-------------|----------|
| Single global threshold | One number in settings | |
| Per-format thresholds | Different thresholds per MIME type | |
| You decide | Claude decides for MVP | ✓ |

**User's choice:** You decide

### Q4: Torture-test corpus storage?

| Option | Description | Selected |
|--------|-------------|----------|
| Checked into repo | tests/fixtures/torture-corpus/ directory | |
| Fetched from URLs | Public URLs downloaded on first test run | |
| You decide | Claude decides the tradeoff | ✓ |

**User's choice:** You decide

---

## Chunking Strategy

### Q1: Which tokenizer for chunk sizing?

| Option | Description | Selected |
|--------|-------------|----------|
| tiktoken (cl100k) | OpenAI's cl100k_base, fast, widely used baseline | ✓ |
| Model-matched | Use configured embedding model's tokenizer | |
| You decide | Claude picks based on tool-agnostic principle | |

**User's choice:** tiktoken (cl100k)

### Q2: Default chunk size and overlap?

| Option | Description | Selected |
|--------|-------------|----------|
| 512 tokens, 50 overlap | Conservative, fits most embedding models | |
| 1024 tokens, 128 overlap | Larger context per chunk | |
| You decide | Claude decides defaults, configurable per domain pack | ✓ |

**User's choice:** You decide

### Q3: Table atomicity for oversized tables?

| Option | Description | Selected |
|--------|-------------|----------|
| Table = one chunk always | Never split, allow oversized exception | |
| Split large tables by row groups | Header + N rows per chunk | |
| You decide | Claude decides based on healthcare table sizes | ✓ |

**User's choice:** You decide

### Q4: Chunk overlap style?

| Option | Description | Selected |
|--------|-------------|----------|
| Heading breadcrumb prefix | Section path prepended to each chunk | |
| Raw text overlap only | Standard sliding window | |
| Both (breadcrumb + overlap) | Maximum context, more tokens | |
| You decide | Claude picks for citation-traceable retrieval | ✓ |

**User's choice:** You decide

---

## Dedup & Cleaning Scope

### Q1: MinHash near-dedup scope?

| Option | Description | Selected |
|--------|-------------|----------|
| Corpus-wide | Compare all documents regardless of source | |
| Per-source first, then corpus | Two passes: intra-source then cross-source | |
| You decide | Claude decides for batch-first architecture | ✓ |

**User's choice:** You decide

### Q2: Boilerplate removal approach?

| Option | Description | Selected |
|--------|-------------|----------|
| Heuristic patterns | Regex/rule-based removal of known patterns | |
| Trafilatura-style extraction | Library-based main content extraction | |
| You decide | Claude decides based on input mix | ✓ |

**User's choice:** You decide

### Q3: Near-duplicate action?

| Option | Description | Selected |
|--------|-------------|----------|
| Flag only | Mark near_duplicate in registry, all copies remain | |
| Keep canonical, soft-delete rest | Oldest/highest-quality becomes canonical | |
| You decide | Claude decides based on lineage-preservation | ✓ |

**User's choice:** You decide

### Q4: Language detection behavior?

| Option | Description | Selected |
|--------|-------------|----------|
| Annotate only | Record language, all docs continue | |
| Gate on supported languages | Unsupported languages halted | |
| You decide | Claude picks for healthcare-first domain | ✓ |

**User's choice:** You decide

---

## Claude's Discretion

User deferred the following to Claude's judgment:
- Parser chain configurability vs fixed order
- Parser dependency management (required vs optional extras)
- Quality threshold structure (global vs per-format)
- Low-quality document handling (flag vs halt)
- Torture-test corpus storage strategy
- Default chunk size and overlap parameters
- Table atomicity for oversized tables
- Chunk overlap style (breadcrumb vs raw vs both)
- MinHash dedup scope (corpus-wide vs per-source-then-corpus)
- Boilerplate removal approach
- Near-duplicate action (flag vs soft-delete)
- Language detection behavior (annotate vs gate)

## Deferred Ideas

None — discussion stayed within phase scope.
