# Milestone Context: v2.6 — Data Quality & Enrichment

**Gathered:** 2026-07-15
**Source:** End-to-end data quality audit of `klake process` + code grounding of root causes
**Status:** Ready for `/gsd-new-milestone` (consume and delete this file)

---

## Goal

Stop garbage content from reaching the silver zone, chunking, tree index, and gold export — so the
RAG corpus is trustworthy rather than merely populated.

## Evidence: The Audit

4,499 chunks from 34 healthcare sources. **~28% garbage.**

| Problem | Count | Impact |
|---------|-------|--------|
| Too short (<30 chars) | 762 (16%) | Single words, e.g. "Featured" |
| No real sentences | 408 (9%) | Menu labels, headings without body |
| Exact duplicates | 653 (14%) | Same footer/boilerplate embedded repeatedly |
| Boilerplate | 123 (2%) | Cookie banners, nav footers, TOS, gov disclaimers |
| Marketing/pricing | 152 (3%) | Exam fees, enrollment CTAs, subscription prices |

**Gold RAG corpus: 119 of 357 rows (33%) are sub-30-char junk.**

**Worst sources:** ACC Clinical Guidelines (81% garbage), US Core IG (72%), eCQI (69%), FDA FAERS (55%).

## Root Causes — 6 layers, not 5

The audit identified 5 failing layers. Code grounding found a **6th that explains most of the damage**
and reframes the milestone.

### L0 (NEW — the big one): The clean stage is architecturally bypassed

`clean()` runs, de-boilerplates the parsed markdown, and writes a `cleaned_document` artifact to the
silver zone. **Nothing on the RAG path reads it.**

In `src/knowledge_lake/dagster_defs/assets.py`, `clean_document` forwards the *original, uncleaned*
in-memory `ParsedDoc` to every downstream stage:

```python
clean_result = clean(parsed_artifact_id, source_id, settings=settings)   # cleans the S3 blob
return {
    "parsed_doc": parsed_doc,   # ← the UNCLEANED object, forwarded verbatim
    ...
}
```

- `chunk_document` reads `clean_document["parsed_doc"]` → chunks uncleaned sections
- `tree_index_document` reads `clean_document["parsed_doc"]` → indexes uncleaned sections
- `enrich_document` reads `clean_document["parsed_doc"]` → pays LLM cost to enrich boilerplate
- `chunk()` parents chunks to `parsed_artifact_id`, not the cleaned artifact

**Consequence:** cleaned text is consumed *only* by the pretrain path (`curate` → DataTrove filters).
This is precisely why the DataTrove-filtered pretrain corpus looks healthy while the RAG corpus is
33% junk — the filters exist, they are just on the branch nobody reads.

### L1: Crawler returns full-page HTML
Nav, footers, and cookie banners enter the raw zone. No boilerplate stripping at extraction time.
Crawl4AI's `fit_markdown` / `PruningContentFilter` is available and unused.

### L2: Parser faithfully converts boilerplate into "sections"
Docling is doing its job correctly — a nav bar with 3 links legitimately becomes a section. The
problem is that nothing downstream distinguishes a nav section from a clinical-guidance section.

### L3: Chunker has no minimum-substance gate
`ChunkSettings` exposes only `max_tokens: 512`, `overlap_tokens: 64`, `tokenizer`. **There is no
minimum** — no floor to gate on. Any section, regardless of substance, becomes a chunk.

### L4: Indexer has no dedup check — and this is deliberate
`chunk()` hashes `f"{parsed_artifact_id}:{text}"`, with an explicit comment citing **WR-05**:
"dedup key must include parent to prevent lineage corruption across documents." The 653 exact
duplicates are the direct, designed consequence of that decision. Resolving this means confronting
WR-05, not merely adding a check. **Resolution chosen: dedup at index time (see below).**

### L5: Gold export filters on quantity, not quality
Garbage passes straight through to Parquet. `curate`'s composite quality score exists but does not
gate the RAG corpus export.

### Supporting detail: boilerplate patterns are weak
`BOILERPLATE_PATTERNS` in `pipeline/clean.py` is 4 line-anchored regexes: `^home|about us|contact|
sitemap$`, cookie lines, `Page N of M`, and copyright lines. None match a nav bar with 3 links, a
TOS block, or an enrollment CTA. Even if L0 were fixed, these patterns alone would not reach 28%.

---

## Scope Decisions (confirmed with user 2026-07-15)

### D-1: Full rework, including crawler-level extraction — **SELECTED**
Fix each layer where it belongs:
- Wire cleaned text onto the load-bearing path (L0)
- Crawler-level boilerplate stripping so nav/footers never enter the raw zone (L1) — Crawl4AI
  `fit_markdown` / `PruningContentFilter`
- Section-level boilerplate classification (L2)
- Minimum-substance gate at chunk (L3)
- Index-time dedup (L4)
- Quality gate on gold export (L5)

Accepted blast radius: touches ingest and the re-crawl path.

### D-2: Forward-only — **SELECTED**
New ingests get the cleaned pipeline; the existing 4,499-chunk corpus stays as-is. Mirrors the v2.0
STORE-01 forward-only precedent (which avoided rewriting raw keys to honor WORM).

**Known implication, accepted:** the existing 28% garbage is not retroactively removed. Garbage-rate
improvement will be observable only on newly processed sources. A deliberate reprocess from the
(immutable, intact) raw zone remains possible later if desired.

### D-3: Dedup at index time — **SELECTED**
Keep chunk artifacts per-document so lineage and WR-05 stay intact. Deduplicate *before embedding*:
one vector per unique text, payload carries all contributing source refs. Fixes embedding cost and
result pollution without making artifact lineage many-to-many.

### D-4: Research first — **SELECTED**
Run the 4 parallel project researchers (Stack, Features, Architecture, Pitfalls) before defining
requirements. Focus areas: boilerplate-removal techniques at extraction time, chunk-quality
heuristics, index-time dedup strategies, and pitfalls of retrofitting cleaning into an existing
pipeline.

---

## Constraints That Bind This Milestone

From PROJECT.md — these are not negotiable and should shape every requirement:

- **Deterministic first** — regex/heuristic filtering before any LLM enrichment. A quality gate that
  needs an LLM call per chunk violates this.
- **Immutability** — the raw zone must never be modified. L1 (crawler extraction) must be
  forward-only; do not rewrite existing raw objects.
- **Lineage** — every artifact traces to source with stable IDs and content hashes. This is exactly
  what D-3 protects.
- **LLM Gateway** — any LLM-assisted classification goes through LiteLLM with task-based aliases
  (`cheap_model` etc.), never a provider SDK.

## Open Questions for Research / Planning

1. Where does the substance gate belong — parse (drop the section), clean (strip it), or chunk
   (refuse to emit)? Dropping at parse loses lineage evidence of what was discarded; dropping at
   chunk means paying enrich cost on garbage first.
2. Should discarded content be recorded (a `rejected` artifact or metadata flag) so the garbage rate
   is measurable and auditable, rather than silently vanishing?
3. Does `fit_markdown` at crawl time interact badly with the SCHED-02 normalized-silver-text change
   gate? Aggressive pruning could make re-crawl diffs unstable and thrash the WORM raw zone.
4. Is the 30-char threshold from the audit the right floor, or should it be token-based to match
   `ChunkSettings`?
5. Do the 4 existing `BOILERPLATE_PATTERNS` get replaced or extended? Phase-3 tests depend on them.

## Notes for the Roadmapper

- Phase numbering continues from v2.5 → **v2.6 starts at Phase 17**.
- L0 (the bypass fix) is the highest-leverage, lowest-cost change and is a hard dependency for
  measuring everything else — sequence it first.
- A re-runnable quality audit (garbage rate as a tracked metric) was raised and *not* selected as a
  scope item, but is worth surfacing as a candidate requirement: without it, "did this work?" has no
  answer under D-2 forward-only.
