# Feature Research: v2.6 Data Quality & Enrichment

**Domain:** RAG/corpus pipelines — content quality filtering, boilerplate detection, chunk-level gating
**Researched:** 2026-07-15
**Confidence:** HIGH on concrete thresholds (verified by reading installed DataTrove + Crawl4AI source directly); MEDIUM on architectural norms (converging evidence across 5+ independent implementations, but no single authoritative spec)

## Scope

This document maps the feature landscape for **v2.6 content-quality filtering only**. The pipeline (ingest → parse → clean → chunk/tree → enrich → embed → index → curate → export), hybrid retrieval, tree indexing, and DataTrove-based pretrain curation are all shipped and are **not** re-scoped here. The question answered is narrow: *given a shipped pipeline emitting 28% garbage chunks, what does a mature quality-filtering feature set look like, and which parts belong in v2.6?*

Evidence base: `.planning/MILESTONE-CONTEXT.md` audit (4,499 chunks, 34 sources), plus a survey of FineWeb/DataTrove, C4, Gopher/MassiveText, Crawl4AI, jusText/trafilatura, RAGFlow DeepDoc, Unstructured, and the web-template-detection literature.

---

## Ecosystem Context

### The single most important finding

**Every production system surveyed filters at multiple layers, and none relies on one.** DataTrove filters at document level *after* a separate extraction stage has already removed nav/footer via trafilatura. RAGFlow classifies layout regions *and* drops garbage regions *and* dedups repeated garbage. Crawl4AI prunes the DOM *before* markdown is ever generated. jusText classifies blocks *and then* refines using neighbours.

This directly validates the D-1 "full rework, fix each layer where it belongs" scope decision. It also reframes it: the six layers are not six chances to catch the same garbage — **each layer catches a class of garbage that no other layer can see.** Crawl-time has DOM/link structure that is destroyed by parse. Document-level has whole-document statistics invisible per-chunk. Cross-page has repetition invisible within one document. Chunk-level is the last place a local floor can apply. This is defense-in-depth by necessity, not redundancy.

### Q1 — What quality signals do production pipelines actually gate on?

Verified by reading the installed `datatrove` package source (`site-packages/datatrove/pipeline/filters/`) — these are **exact library defaults**, not blog paraphrase:

**`GopherQualityFilter`** (`gopher_quality_filter.py`, ref arxiv 2112.11446):

| Parameter | Default | Rejection reason emitted |
|-----------|---------|--------------------------|
| `min_doc_words` | 50 | `gopher_short_doc` |
| `max_doc_words` | 100,000 | `gopher_long_doc` |
| `min_avg_word_length` | 3 | `gopher_below_avg_threshold` |
| `max_avg_word_length` | 10 | `gopher_above_avg_threshold` |
| `max_symbol_word_ratio` | 0.1 (for `#` and for `...`/`…`) | `gopher_too_many_hashes` / `gopher_too_many_ellipsis` |
| `max_bullet_lines_ratio` | 0.9 | `gopher_too_many_bullets` |
| `max_ellipsis_lines_ratio` | 0.3 | `gopher_too_many_end_ellipsis` |
| `max_non_alpha_words_ratio` | 0.8 (≥80% of words must contain ≥1 alpha char) | `gopher_below_alpha_threshold` |
| `min_stop_words` | 2 | `gopher_enough_stop_words` |

`STOP_WORDS = ["the","be","to","of","and","that","have","with"]` — note this is a deliberately tiny list; the check is "does this text contain ≥2 of the 8 most common English function words", which is a cheap proxy for "is this a sentence rather than a label". **This is the single best deterministic answer to the audit's "no real sentences" bucket (408 chunks, 9%).**

**`FineWebQualityFilter`** (`fineweb_quality_filter.py`):

| Parameter | Default | Meaning |
|-----------|---------|---------|
| `line_punct_thr` | 0.12 | reject if <12% of non-empty lines end in terminal punctuation |
| `short_line_thr` | 0.67 | reject if >67% of lines are "short" |
| `short_line_length` | **30** | definition of a "short line" — **in characters** |
| `char_duplicates_ratio` | 0.01 | reject if >1% of chars are in duplicate lines |
| `new_line_ratio` | 0.3 | reject if newlines/words > 0.3 (list-like text) |

**The audit's ad-hoc 30-char threshold is not arbitrary — it coincides exactly with FineWeb's `short_line_length=30`.** That is a meaningful independent corroboration and answers open question 4 partially (see "Threshold guidance" below for the token-vs-char resolution).

**`C4QualityFilter`** (`c4_filters.py`, ref JMLR 20-074):
- Retain only lines ending in terminal punctuation `. ? ! " '` and *not* ending in `...`
- `min_words_per_line = 3` (drop the line)
- `min_num_sentences = 5` (drop the whole doc)
- `max_word_length = 1000`
- Drop lines containing `javascript`; drop whole doc on `lorem ipsum` or on `{`
- `POLICY_SUBSTRINGS = ["terms of use", "privacy policy", "cookie policy", "uses cookies", "use of cookies", "use cookies"]` → drop the line

**`GopherRepetitionFilter`** (Table A1, arxiv 2112.11446) — repetition thresholds: duplicate line fraction 0.30, duplicate line *character* fraction 0.20, duplicate paragraph fraction 0.30, top-2-gram char fraction 0.20, top-3-gram 0.18, top-4-gram 0.16, duplicate 5-gram char fraction 0.15 decaying to duplicate 10-gram 0.10.

**Critical caveat for v2.6:** every one of these is a **document-level** filter. `min_doc_words=50` on a 512-token chunk would be a very different (and much harsher) gate than on a web page. The ecosystem does **not** supply a canonical chunk-level floor — this is a genuine gap and v2.6 must derive its own (see "Threshold guidance").

### Q2 — Boilerplate detection: what deterministically separates nav/footer/TOS from content?

Three distinct mechanisms, in ascending order of power:

**(a) Link density — the classic, and it is cheap.** jusText defaults (verified from the algorithm doc):

```
MAX_LINK_DENSITY = 0.2      LENGTH_LOW  = 70     STOPWORDS_LOW  = 0.30
                            LENGTH_HIGH = 200    STOPWORDS_HIGH = 0.32
```

Context-free classification: `link_density > 0.2 → bad`; block shorter than `LENGTH_LOW` → `bad` if it contains any link, else `short` (deferred, **not dropped**); otherwise stopword density above `STOPWORDS_HIGH` → `good` if longer than `LENGTH_HIGH` else `near-good`; between LOW and HIGH → `near-good`; below `STOPWORDS_LOW` → `bad`. A **context-sensitive second pass** then resolves `short`/`near-good` blocks using their neighbours.

The design lesson is more valuable than the numbers: **jusText refuses to make a final drop decision on a short block in isolation.** A 20-char block is a nav item if surrounded by nav items and a section heading if surrounded by prose. A naive "drop everything under 30 chars" gate cannot make that distinction and *will* delete legitimate headings and table cells.

**(b) DOM/structural signals — only available at crawl time.** Crawl4AI's `PruningContentFilter` (verified from installed source, `crawl4ai/content_filter_strategy.py`):

```python
threshold = 0.48                    # default; threshold_type "fixed" | "dynamic"
metric_weights = {"text_density": 0.4, "link_density": 0.2, "tag_weight": 0.2,
                  "class_id_weight": 0.1, "text_length": 0.1}
excluded_tags = {nav, footer, header, aside, script, style, form, iframe, noscript}
negative_patterns = re.compile(r"nav|footer|header|sidebar|ads|comment|promo|advert|social|share", re.I)
# link density contribution: score += 0.2 * (1 - link_text_len / text_len)
```

It also exposes `preserve_classes` / `preserve_tags` escape hatches. **`<nav>`/`<footer>` tags and `class="sidebar"` are unambiguous boilerplate evidence that is irrecoverably destroyed the moment HTML becomes markdown.** This is the strongest single argument for the L1 crawl-level work in D-1 — no downstream heuristic can reconstruct this signal.

**(c) Cross-page repetition — the strongest signal, and nobody in our stack exploits it.** The literature (Site Style Tree; arxiv 1409.2590 on web-template detection; Pomikálek's thesis on removing boilerplate and duplicate content) converges: *a block appearing on many pages of the same site is boilerplate, near-definitionally.* SST aggregates DOM trees across pages with per-node counters; the most-repeated nodes are pruned. The literature also notes a **small sample of pages per site suffices** to induce the template — this is not an expensive whole-corpus operation.

RAGFlow implements an in-document variant: text repeated across `garbage_layouts` regions is collected and removed globally within the document.

**This maps precisely onto the audit's largest bucket.** 653 exact duplicates (14%) are, overwhelmingly, *the same footer embedded once per page of one site*. The worst offenders (ACC Clinical Guidelines 81%, US Core IG 72%, eCQI 69%) are exactly the profile of a site whose template dominates its content. Cross-page repetition is the one signal that explains the concentration of garbage in specific sources — and the framework already has the ingredient it needs: chunks are `source_id`-scoped, so "count how many documents of this source contain this exact block" is a single indexed query.

**(d) Structural type labels.** RAGFlow DeepDoc's `LayoutRecognizer` classifies 11 page-element types and defines `garbage_layouts = ["footer", "header", "reference"]`, dropped unless positional `keep_feats` rescue them (footer above 90% page height, header below 10%). Unstructured assigns `Title` / `NarrativeText` / `ListItem` / `Header` / `Footer` / `UncategorizedText`, and the documented recommendation is to filter low-value types — especially `UncategorizedText` — *before* chunking and embedding. Both are **classify-then-gate**: a structural label drives the decision, not a text statistic. This is the model for L2 section-level classification.

Note what (d) implies for the framework's plugin posture: Docling's job is *faithful conversion* (correctly identified in the audit as L2 "Docling is doing its job"). RAGFlow/Unstructured put the garbage decision in a **separate classification step that consumes the parser's structural output** — they do not ask the parser to lie. v2.6 should do the same, which keeps the `ParserPlugin` seam clean.

**Gap — marketing/pricing (152 chunks, 3%).** No surveyed OSS tool has a deterministic filter for enrollment CTAs, exam fees, or subscription pricing. C4's `POLICY_SUBSTRINGS` is the closest analogue and it is a hand-maintained 6-phrase list. This bucket is irreducibly domain-specific, which is an argument for pattern extensibility via the existing domain pack convention rather than a core filter.

### Q3 — Where in the pipeline do systems filter, and is dropping the norm?

**Dropping is unambiguously the norm at ingest.** DataTrove's `BaseFilter` contract is literally "Returns true if a sample should be KEPT, false if it should be REMOVED". RAGFlow pops garbage boxes. Unstructured's guidance is to filter before chunking/embedding. jusText and trafilatura's entire purpose is removal.

**But — and this is the crucial nuance — dropping from the pipeline is not the same as destroying the record.** DataTrove's `BaseFilter.run()`:

```python
with self.exclusion_writer if self.exclusion_writer else contextlib.nullcontext() as writer:
    ...
    filter_result, reason = get_filter_result(doc_filter_result)
    if filter_result:
        self.stat_update(StatHints.forwarded); yield doc
    else:
        self.stat_update(StatHints.dropped)
        if reason: self.stat_update(f"dropped_{reason}")
        if self.exclusion_writer:
            if reason: doc.metadata["filter_reason"] = reason
            writer.write(doc, rank)
```

Dropped documents are **written to a separate destination, tagged with the reason that dropped them**, and a `dropped_{reason}` counter is incremented. The norm is: *drop from the load-bearing path, persist the rejection with an attributable reason.*

**Tag-and-filter-at-query-time is NOT how production systems handle quality.** Query-time metadata filtering is used for *relevance* scoping (source, date, topic). ChunkRAG (arxiv 2410.19572) is frequently miscited as evidence for query-time quality filtering — it is not. It does per-chunk LLM relevance scoring **against the user's query at retrieval time**; it is a reranker, and relevance-to-query is a fundamentally different axis from is-this-text-garbage. A cookie banner is garbage regardless of the query.

Three concrete reasons tag-only fails for this project specifically:
1. You still pay the embedding cost on 28% garbage (and the enrich LLM cost, per L0).
2. Garbage still pollutes **corpus-wide BM25/IDF statistics** — the hybrid sparse index computes document frequencies over whatever is indexed. 653 copies of a footer distort term statistics for every query, including ones that filter the garbage out. This is invisible to a payload filter.
3. It defers the problem to every consumer forever, and the framework has many surfaces (CLI, API, MCP, wiki, export) that would each need to remember to apply the filter.

**Recommended placement per layer** (this is the ecosystem's answer to open question 1):

| Layer | What only *it* can see | Gains | Loses |
|-------|------------------------|-------|-------|
| Crawl (L1) | DOM tags, class/id, link structure | Kills nav/footer at the root; cheapest downstream | Signal-destructive and irreversible if it overwrites raw; interacts with SCHED-02 |
| Parse (L2) | Section/layout structure, heading context | Structural labels are precise | Dropping here erases lineage evidence |
| Clean (L0) | Whole-document text statistics | Already built; already has the filters | Currently bypassed — worthless until L0 is fixed |
| Chunk (L3) | Final emitted unit | Last local floor; prevents junk chunks existing | Enrich cost already paid if enrich runs first |
| Index (L4) | Corpus-wide duplicate view | Only place dedup is safe under WR-05 | Cannot recover text-level quality |
| Export (L5) | Downstream use context | Different thresholds per dataset type | Too late to save embedding cost |

The convergent answer to *"where does the substance gate belong"*: **classify at parse/clean (annotate, don't delete), gate at chunk (refuse to emit), record the rejection.** Annotation preserves lineage evidence; the gate at chunk is where the emitted unit is finally decided; the rejection record makes it auditable. This threads the needle in the open question — you do not have to choose between "lose lineage evidence" and "pay enrich cost on garbage", because classification and gating are separable steps.

### Q4 — Observability of discarded content

Yes, and it is a first-class feature, not an afterthought:
- **DataTrove**: `exclusion_writer` (a full `DiskWriter` — rejects land in a real, queryable dataset), `doc.metadata["filter_reason"]`, and `stat_update(f"dropped_{reason}")` counters per pipeline step. Every filter returns `(False, "reason_string")` rather than a bare bool — the API is *designed* so that a drop is always attributable.
- **C4QualityFilter** additionally emits per-*line* stats: `line-total`, `line-filter-no_terminal_punc`, `line-filter-too_few_words`, `line-filter-javascript`, `line-filter-too_long_word`.

A "quality report" as a feature is therefore: **per-stage, per-reason drop counters + a persisted rejection set + a kept/total ratio**, all keyed to a filter-config version so runs are comparable.

**This is decisive for v2.6.** Under D-2 forward-only, the existing 4,499-chunk corpus keeps its garbage. There is no before/after on the same data. A garbage-rate metric computed per-run *is the only available proof the fix worked* — the milestone's success criterion is otherwise unfalsifiable. The MILESTONE-CONTEXT notes this was raised and not selected as scope; the research says it should be. Note it is also nearly free: DataTrove already emits the reasons, and `curate.py` already instantiates these filters via `_build_filters()`. The counters exist and are being thrown away.

### Q5 — Quality-gated export: do thresholds differ by downstream use?

Yes, materially, and the project already embodies the split without having named it.

- **Pretrain** wants *volume with a floor*. Gopher/C4/FineWeb thresholds are tuned to discard the worst decile of a web crawl while keeping trillions of tokens. `min_doc_words=50` is permissive. Near-duplicates are aggressively removed (MinHash) because duplicate training data causes memorization.
- **RAG** wants *precision per retrievable unit*. Every indexed chunk is a candidate answer; a single junk chunk surfacing in top-k is a user-visible defect. The correct RAG threshold is strictly **stricter** than the pretrain threshold — the unit is smaller, and the cost of one bad unit is higher.
- **Finetune** wants *exemplar quality* — stricter still, and typically curated/human-reviewed.

The audit is the empirical proof of this asymmetry in this very repo: **the DataTrove-filtered pretrain corpus looks healthy while the RAG corpus is 33% junk.** Same source documents, same pipeline, different fate — because (per L0) the filters only ever reached the pretrain branch. So the finding is not merely "thresholds should differ"; it is that **RAG currently has no threshold at all**, and `export_rag_corpus()` (confirmed by reading `pipeline/export.py`) iterates chunk artifacts with a field allow-list but no quality predicate whatsoever.

---

## Feature Landscape

### Table Stakes (must have for v2.6)

Without these, v2.6 does not deliver its stated goal.

| Feature | Why Expected | Complexity | Dependencies (existing) | Notes |
|---------|--------------|------------|-------------------------|-------|
| **Cleaned text on the load-bearing path (L0)** | The defect. Filters that exist but are unreachable are not features. Nothing else is measurable until this is true. | **LOW** (code) / MED (test blast radius) | `dagster_defs/assets.py` `clean_document`; `chunk_document`, `tree_index_document`, `enrich_document` read `clean_document["parsed_doc"]` | Forward the *cleaned* text. Requires deciding the carrier: cleaning currently returns markdown, but chunk/tree consume a structured `ParsedDoc` with `sections[]`. **This is the hidden cost of L0 — it is not a one-line change**, because a cleaned markdown blob has no `sections`. Either clean operates on `ParsedDoc.sections` (recommended — preserves `section_path`/`page` needed by CHUNK-04 and TREE-03) or re-derive sections from cleaned markdown (lossy, breaks page refs). Sequence first per MILESTONE-CONTEXT. |
| **Minimum-substance gate at chunk (L3)** | No floor exists (`ChunkSettings` = `max_tokens`/`overlap_tokens`/`tokenizer` only). 16% of chunks are single words. | **LOW** | `pipeline/chunk.py::_build_token_chunks`; `config/settings.py::ChunkSettings`; `token_count()` already available | Add `min_tokens` + composite substance predicate. Must exempt tables (`is_table=True` is atomic per CHUNK-03) — a table of dosages legitimately has few stopwords and no terminal punctuation, and a naive gate deletes it. Per-chunk local decision. |
| **Sentence-substance heuristics (stopword + terminal-punct + alpha ratio)** | Length alone cannot catch "no real sentences" (9%). Ecosystem-standard, all deterministic. | **LOW** | new `quality/` predicates; reuse in chunk gate | Direct ports of Gopher `min_stop_words=2`, `max_non_alpha_words_ratio=0.8`, C4 terminal-punct + `min_words_per_line=3`. Per-chunk local. |
| **Extended boilerplate patterns** | Current 4 regexes cannot match a 3-link nav bar, TOS block, or CTA. Even a fixed L0 would not reach 28% with them. | **LOW** | `pipeline/clean.py::BOILERPLATE_PATTERNS`, `remove_boilerplate()` | **Extend, do not replace** — Phase-3 tests depend on the existing 4 (open question 5). Add C4 `POLICY_SUBSTRINGS`. Keep line-anchored to preserve the T-03-07 inline-citation guarantee. |
| **Index-time exact dedup (L4)** | 653 duplicate embeddings. D-3 already decided this. | **MED** | `pipeline/index.py`; Qdrant payload; `chunk()` WR-05 hash unchanged | One vector per unique text; payload carries all contributing chunk/source refs. **Exact-hash only** (see anti-features). Cross-document context required. |
| **Quality gate on gold RAG export (L5)** | 33% of `rag_corpus` is junk. Gate is the export's contract with its consumer. | **LOW** | `pipeline/export.py::export_rag_corpus`; `quality/scorer.py::compute_composite_quality_score` | Currently no quality predicate at all. Threshold must be independently configurable from the pretrain path (Q5). |
| **Rejection recording + garbage-rate metric** | Under D-2 forward-only this is **the only way to prove the fix worked**. Ecosystem-standard (`exclusion_writer` + `dropped_{reason}`). | **MED** | new artifact/metadata flag; `registry/models.py` (artifacts table is already generic); structlog | Answers open question 2 with a clear "yes". Every gate returns `(bool, reason)` — copy DataTrove's `BaseFilter` contract exactly. Reason strings must be a closed enum for countability. |
| **Filter-config versioning** | Thresholds *will* be tuned. Without a version, cached artifacts silently retain old-filter output and runs are not comparable. | **LOW** | `curate.py::_curation_cache_key` already does exactly this (`sha256(f"{hash}:{filter_config_version}")`) | Proven pattern in-repo — reuse it for the chunk/clean gates. |

### Differentiators (valuable, higher effort)

| Feature | Value Proposition | Complexity | Dependencies | Notes |
|---------|-------------------|------------|--------------|-------|
| **Crawl-level boilerplate stripping (L1)** | Only layer that can see `<nav>`/`<footer>`/`class="sidebar"`. Signal is destroyed by parse and unrecoverable downstream. In D-1 scope. | **MED** | `pipeline/crawl.py` (Crawl4AI); ingest + re-crawl path; SCHED-02 change gate | Crawl4AI returns **both** `raw_markdown` and `fit_markdown` — store raw unchanged in the WORM raw zone, persist `fit_markdown` as a *derived* artifact. This preserves immutability and answers open question 3 (see anti-features for the `dynamic` threshold trap). |
| **Cross-page repetition detection** | **The strongest boilerplate signal available**, and it explains the audit's biggest bucket and its per-source concentration (81%/72%/69%). Nothing else in the stack exploits it. | **HIGH** | needs per-source block-frequency index; `source_id` scoping already exists on chunks/artifacts | "Block appears in ≥N documents of this source → boilerplate." Requires cross-document context — this is the architecture-driving feature. Cheaper than it looks: literature says a small page sample per site induces the template. Could subsume the marketing/CTA bucket *without* hand-written patterns, since CTAs repeat site-wide. |
| **Section-level boilerplate classification (L2)** | Turns "is this text junk" into "is this section a nav/footer/TOS region" — precise, and follows RAGFlow/Unstructured `garbage_layouts` prior art. In D-1 scope. | **MED** | `ParsedDoc.sections`; `plugins/protocols.py`; `pipeline/clean.py` | Classify-then-gate. Annotate sections rather than deleting them — preserves lineage evidence and lets chunk make the drop decision. |
| **Neighbour-context refinement for short blocks** | jusText's core insight: a short block is nav-or-heading depending on neighbours. Prevents the substance gate from eating legitimate headings/table cells. | **MED** | requires section ordering (already in `ParsedDoc.sections`) | Within-document context. Meaningfully reduces false positives from a naive length floor. |
| **Domain-scoped boilerplate patterns** | The 3% marketing/pricing bucket is irreducibly domain-specific; no OSS tool covers it. Healthcare knows what an enrollment CTA looks like. | **LOW** | `domains/healthcare/` (has `domain.yaml`, `taxonomy.yaml`, `prompts/`, `validators/`) | Add a `boilerplate.yaml` following the existing pack convention → zero core changes per domain, consistent with the proven domain-pack decision. |
| **Per-reason quality report (CLI/API)** | Makes garbage rate a tracked, trendable metric rather than a one-off audit. Turns "did this work?" into a number. | **MED** | rejection recording; `klake` Typer app; DuckDB over gold zone | The re-runnable audit MILESTONE-CONTEXT flags as a candidate requirement. Natural CLI: `klake quality-report --domain healthcare`. |
| **Quality-score propagation to search (QUALITY-01)** | Deferred since v2.0; PROJECT.md says reconsider in v2.6. | **LOW** | Qdrant payload; `pipeline/search.py` | **Complement, not substitute** for the ingest gate — it cannot fix BM25/IDF pollution. Reasonable to keep deferred; the ingest gate is the real fix. |

### Anti-Features (traps for *this* project)

| Anti-Feature | Why Requested / Surface Appeal | Why Problematic **here** | Alternative |
|--------------|-------------------------------|--------------------------|-------------|
| **Per-chunk LLM quality classification** | "Just ask the model if it's garbage." Papers like ChunkRAG appear to endorse it. | Four independent violations: (1) breaks the **deterministic-first** constraint outright; (2) cost scales per chunk — 4,499 chunks/run and unbounded on re-runs; (3) **non-deterministic output breaks content-hash idempotency** — the pipeline caches on content hash everywhere (`_curation_cache_key`, `_enrichment_cache_key`, TREE-02, SCHED-02), and a gate that can answer differently for identical input makes re-runs non-reproducible and lineage unexplainable; (4) **ChunkRAG is miscited** — it scores relevance *to a query at retrieval time*, which is a different axis from is-this-garbage. | Deterministic heuristics (Gopher/C4/FineWeb) catch the overwhelming majority. If LLM assist is ever needed, apply it *once per section-type at parse*, not per chunk, via LiteLLM `cheap_model` under the existing `LlmSpend` cap — mirroring the proven "deterministic first, LLM opt-in" pattern from TREE-04/RETR-06. |
| **Aggressive crawl-time pruning as the only defense / overwriting raw with `fit_markdown`** | "Fix it at the source — why store garbage at all?" | Directly violates **raw-zone immutability**. Worse: `PruningContentFilter(threshold_type="dynamic")` adapts its threshold to page characteristics, so **identical input can produce different output across runs** — which would thrash the SCHED-02 normalized-silver-text change gate and churn the WORM raw zone. This is exactly the failure mode open question 3 anticipates, and it is real. | Store `raw_markdown`/HTML unchanged in raw; persist `fit_markdown` as a **derived** artifact. Use `threshold_type="fixed"` (default 0.48) for reproducibility. Keep the change gate on normalized silver text. Crawl pruning is one layer, never the only one. |
| **Trained/ML boilerplate classifier (Web2Text, fastText quality classifier, FineWeb-Edu style)** | State-of-the-art accuracy; FineWeb-Edu uses one. | FineWeb-Edu's classifier required ~500k LLM annotations to train. Needs labeled data the project does not have, introduces a model artifact to version, and makes the drop decision unexplainable — which collides with the **lineage** core value ("every artifact traces back with stable IDs and content hashes"). "The classifier said 0.31" is not a lineage record. | Deterministic heuristics + cross-page repetition. The audit's garbage is *structurally obvious* (footers, nav, single words) — it does not need ML. |
| **Chunk-level dedup by dropping the parent from the hash** | The obvious fix for 653 duplicates: `sha256(text)` and dupes collapse. | Overturns **WR-05** and corrupts lineage: identical text in two documents would collapse to one artifact with one parent, making the artifact graph many-to-many and destroying "which document did this come from". D-3 already rejected this. | Index-time dedup (D-3): keep per-document chunk artifacts; one *vector* per unique text; payload carries all contributing refs. |
| **Near-duplicate (MinHash) dedup of chunks at index time** | "We already have MinHash in `clean.py`, reuse it." | The 653 duplicates are **exact**, so near-dup adds no recall on the actual problem while adding real risk: clinical text is full of legitimately near-identical passages (dosage tables differing in one number, guideline variants by age band). MinHash at `threshold=0.8` on 512-token chunks would silently collapse *clinically distinct* content — a correctness bug in a healthcare corpus, and a much worse failure than a duplicate footer. | Exact content-hash dedup only at index time. Corpus-wide MinHash stays where it belongs: document-level on the pretrain path (`curate.batch_dedup_corpus`, already authoritative per D-02). |
| **Retroactive backfill / reprocessing the existing 4,499 chunks** | "Fix the corpus we have — 33% junk is unusable today." | D-2 explicitly chose forward-only. Scope explosion, and it competes for effort with the fix itself. The raw zone is immutable and intact, so this remains possible later at any time — deferring costs nothing but patience. | Forward-only + a garbage-rate metric to prove new ingests are clean. A deliberate reprocess-from-raw is a separate, later decision. |
| **Silent dropping (no rejection record)** | Simpler: just `continue` in the loop. | Under D-2 forward-only, silent drops make the milestone's success **unfalsifiable** — no before/after exists on the same data. Also contradicts the ecosystem norm (`exclusion_writer` exists in DataTrove precisely because drops must be auditable), and contradicts the project's lineage core value. | Every gate returns `(bool, reason)`; persist rejects + increment `dropped_{reason}` counters. |
| **Replacing the 4 existing `BOILERPLATE_PATTERNS`** | They are weak and embarrassing; rewrite cleanly. | Phase-3 tests depend on them (open question 5), and they are line-anchored specifically to preserve inline citations (T-03-07) — a subtle guarantee easy to regress. With `xfail_strict=true` repo-wide, breakage will be loud but the citation regression would be silent. | Extend the list. Keep line-anchoring. Add new pattern *classes* alongside rather than rewriting. |
| **A single global quality threshold across all dataset types** | One knob, simpler config. | Q5's finding is that RAG needs a **stricter** gate than pretrain, and the audit proves the asymmetry empirically in this repo. One knob forces a choice between a junk RAG corpus and a starved pretrain corpus. | Per-dataset-type thresholds; the gold zone is already segmented by domain × dataset type (STORE-03). |
| **Gating on `oversized` / table chunks with prose heuristics** | Uniformity: apply the same predicate everywhere. | Tables legitimately fail nearly every prose heuristic — few stopwords, no terminal punctuation, low alpha ratio, high symbol ratio. A uniform gate deletes exactly the highest-value healthcare content (dosage tables, code sets, measure specs). CHUNK-03 makes tables atomic for good reason. | Exempt `is_table=True` from prose predicates; gate tables on their own (non-empty, has rows). |

---

## Local vs Contextual: the architecture-driving axis

The downstream consumer explicitly asked for this split. It determines what can be a pure function versus what needs an index.

| Feature | Context required | Implication |
|---------|------------------|-------------|
| Min token/char floor | **Per-chunk local** | Pure function. `f(text) -> (bool, reason)`. Trivially testable, no I/O. |
| Stopword count / ratio | **Per-chunk local** | Pure function. |
| Terminal-punctuation ratio | **Per-chunk local** | Pure function. |
| Alpha / symbol-to-word ratio | **Per-chunk local** | Pure function. |
| Bullet / ellipsis line ratios | **Per-chunk local** | Pure function. |
| Boilerplate substring/regex match | **Per-chunk local** | Pure function. Patterns are config (domain pack). |
| Within-chunk repeated-line detection | **Per-chunk local** | Pure function (`find_duplicates` over lines). |
| Link density | **Per-chunk local**, *if* markup survives | Computable from markdown `[](...)`; far more accurate from HTML DOM at crawl time. |
| Neighbour refinement (jusText) | **Within-document** | Needs ordered `ParsedDoc.sections`. Available in-memory at clean/chunk. No new index. |
| Section-type classification | **Within-document** | Needs section + position + heading context. In-memory. |
| Document-level Gopher/C4/FineWeb gates | **Whole-document** | Already exist in `curate.py`. Available at clean once L0 is fixed. |
| **Exact chunk dedup** | **Cross-document (corpus)** | Needs a corpus-wide hash lookup. Belongs at index (D-3). |
| **Cross-page repetition** | **Cross-document, scoped to `source_id`** | Needs a per-source block-frequency index. **The only feature demanding new persistent state.** |
| Garbage-rate metric | **Cross-run (aggregate)** | Needs persisted per-reason counters + filter-config version. |

**The architectural line falls cleanly:** everything except the last three is a **pure, in-memory, per-unit predicate** — a `quality/` module of pure functions, trivially unit-testable, no I/O, no registry access. That module is most of the milestone's value and can be built and tested in isolation before any wiring. Exact dedup and cross-page repetition are the only features that need cross-document state, and they are also the two highest-value ones (14% + the bulk of the per-source concentration). Budget accordingly: **the cheap features are cheap, and the expensive ones are expensive for a real reason.**

## Threshold Guidance

Answering open question 4 (*is 30 chars right, or should it be token-based?*):

**Use tokens, and here is the reasoning chain.** `ChunkSettings` is already token-native (`max_tokens=512`, `overlap_tokens=64`, cl100k_base), and `token_count()` is already a cached O(1) call in `chunk.py`. A char floor beside a token ceiling is an inconsistent unit that will confuse operators tuning the pair.

But the 30-char figure is *evidentially useful* and should not be discarded: it independently coincides with FineWeb's `short_line_length=30`, so it is a defensible **lower bound** — text below it is short by two independent reckonings. 30 chars ≈ 7–8 cl100k tokens.

| Candidate | Value | Source | Verdict |
|-----------|-------|--------|---------|
| `min_tokens` floor | **start ~8–16, tune upward empirically** | 30 chars ≈ 8 tokens (FineWeb `short_line_length=30`, corroborated by the audit) | Evidence-anchored **floor**. Start conservative; the substance predicates below do the real work. |
| Gopher `min_doc_words=50` as a chunk floor | 50 words ≈ 65+ tokens | DataTrove default — **document-level** | **Do not adopt directly.** Would delete legitimate short sections and every table. Cited as an upper bound of what "substance" means for a *document*, not a chunk. |
| `min_stop_words` | **2** | Gopher default (verified in source) | Adopt as-is. Best single signal for "no real sentences" (9% bucket). |
| `max_non_alpha_words_ratio` | **0.8** (≥80% of words contain an alpha char) | Gopher default (verified) | Adopt for prose; exempt tables. |
| `min_words_per_line` | **3** | C4 default (verified) | Adopt. Kills "Featured". |
| Terminal punctuation required | lines ending `. ? ! " '`, not `...` | C4 default (verified) | Adopt as a *ratio* (FineWeb `line_punct_thr=0.12`), not a hard per-line rule — headings legitimately lack terminal punctuation. |
| `max_link_density` | **0.2** | jusText `MAX_LINK_DENSITY` | Adopt for nav detection. |
| Pruning `threshold` | **0.48**, `threshold_type="fixed"` | Crawl4AI default (verified) | Adopt fixed, never dynamic (see anti-features). |
| Cross-page repetition | block in ≥N docs of a source | literature (SST); no canonical N | **Must be tuned empirically.** N as a *fraction* of the source's document count is likelier to generalise than an absolute count, given sources range widely in size. |

**Honest gap:** no surveyed system publishes a chunk-level substance threshold, because production corpus tooling is document-level and RAG tooling largely does not gate at all. Every chunk-level number above is an *adaptation*, not a citation. They should ship as configurable settings with the audit as the tuning harness — which is a further argument for the garbage-rate metric being table stakes rather than optional.

## Feature Dependencies

```
[L0] cleaned text on load-bearing path   ←── HARD PREREQUISITE FOR MEASURING ANYTHING
    |          (assets.py: clean_document forwards cleaned, not parsed_doc)
    |          └── blocked_on: carrier decision (ParsedDoc.sections vs markdown blob)
    |
    ├──> [L2] section-level boilerplate classification (annotate, don't delete)
    |         └──enhanced_by──> neighbour-context refinement (jusText-style)
    |         └──enhanced_by──> domain-scoped patterns (domains/healthcare/boilerplate.yaml)
    |
    ├──> quality/ predicate module (PURE FUNCTIONS — no deps, build first, test in isolation)
    |         |
    |         ├──> [L3] min-substance gate at chunk  (per-chunk local)
    |         |         └──requires──> table exemption (is_table=True, CHUNK-03)
    |         |
    |         └──> [L5] quality gate on gold RAG export  (per-chunk local + composite score)
    |
    └──> [L1] crawl-level fit_markdown (forward-only; derived artifact, raw untouched)
              └──conflicts_with──> SCHED-02 change gate IF threshold_type="dynamic"
              └──requires──> threshold_type="fixed" for reproducibility

[L4] index-time exact dedup   (cross-document; independent of L0 — can run in parallel)
     └──preserves──> WR-05 (chunk artifacts stay per-document)

cross-page repetition detection   (cross-document, source-scoped — NEW persistent state)
     └──requires──> per-source block-frequency index
     └──subsumes (partially)──> marketing/CTA patterns, footer boilerplate

rejection recording ──requires──> every gate returns (bool, reason) [DataTrove BaseFilter contract]
     └──enables──> garbage-rate metric ──enables──> "did v2.6 work?" under D-2 forward-only
     └──requires──> filter-config versioning (reuse curate.py::_curation_cache_key pattern)
```

### Dependency Notes

- **L0 gates measurement, not just quality.** Until chunk/tree/enrich read cleaned text, every other gate's effect is unobservable — you cannot attribute an improvement to a filter that sits on a branch nobody reads. MILESTONE-CONTEXT is right to sequence it first.
- **L0 is cheaper in code than in consequences.** The forwarding change is small; the carrier decision (markdown vs `ParsedDoc.sections`) is the real design work, because `section_path`/`page` must survive for CHUNK-04 and TREE-03. Cleaning `sections[]` in place is the recommendation.
- **The `quality/` predicate module has no dependencies at all** and should be built first in parallel with L0 — pure functions, pure unit tests, no registry, no S3, no Dagster.
- **L4 (dedup) is independent of L0** and can proceed in parallel — it operates on chunk text regardless of whether that text was cleaned.
- **Rejection recording must be designed in from the first gate, not retrofitted.** Retrofitting means revisiting every gate's signature. Copy DataTrove's `(bool, reason)` contract from the start; it costs nothing on day one and is expensive on day thirty.
- **Cross-page repetition conflicts with nothing but is the only feature needing new persistent state** — hence the natural candidate for a later phase or for deferral if the cheap layers get the garbage rate low enough on their own.

## MVP Definition

### Launch with (v2.6 core)

- [ ] **L0 — cleaned text on the load-bearing path** — highest leverage, lowest code cost, hard prerequisite for measuring everything else
- [ ] **`quality/` pure-predicate module** — Gopher/C4/FineWeb heuristics as pure functions returning `(bool, reason)`; zero dependencies; build in parallel with L0
- [ ] **L3 — min-substance gate at chunk** — with table exemption; kills the 16% + 9% buckets
- [ ] **Extended boilerplate patterns** — additive to the existing 4; adds C4 `POLICY_SUBSTRINGS`; kills the 2% bucket
- [ ] **L4 — index-time exact dedup** — kills the 14% bucket; D-3 already decided
- [ ] **L5 — quality gate on gold RAG export** — with a RAG threshold independent of pretrain
- [ ] **Rejection recording + garbage-rate metric** — under D-2 this is the only proof of success; nearly free given DataTrove already emits the reasons

### Add once core works

- [ ] **L1 — crawl-level `fit_markdown`** — in D-1 scope, but derived-artifact-only and `threshold_type="fixed"`; gate on confirming no SCHED-02 interaction
- [ ] **L2 — section-level classification** — annotate-don't-delete; more precise than text statistics
- [ ] **Neighbour-context refinement** — reduces false positives once the naive gate's FP rate is measured
- [ ] **Domain-scoped boilerplate patterns** — the 3% marketing bucket; follows the domain-pack convention
- [ ] **`klake quality-report`** — makes garbage rate trendable rather than a one-off

### Defer

- [ ] **Cross-page repetition detection** — highest-value single signal but the only one needing new persistent state. Defer *only if* the cheap layers demonstrably get the garbage rate low enough; the metric will tell you. Revisit with data, not opinion.
- [ ] **QUALITY-01 search propagation** — complement to the ingest gate, not a substitute; deferred since v2.0 and reasonable to keep deferred
- [ ] **Retroactive backfill** — D-2 forward-only; raw zone is immutable and intact, so this stays possible indefinitely

## Feature Prioritization Matrix

| Feature | User Value | Cost | Priority | Rationale |
|---------|------------|------|----------|-----------|
| L0 cleaned text on path | HIGH | LOW | **P1** | The defect. Unblocks measurement of everything else. |
| `quality/` predicate module | HIGH | LOW | **P1** | Pure functions, no deps, most of the value. |
| L3 chunk substance gate | HIGH | LOW | **P1** | 25% of garbage (16% short + 9% no-sentence). |
| L4 index-time dedup | HIGH | MED | **P1** | 14% of garbage + embedding cost + BM25/IDF pollution. |
| L5 export quality gate | HIGH | LOW | **P1** | 33% of RAG corpus is junk; export has no gate at all today. |
| Rejection + garbage rate | HIGH | MED | **P1** | Under D-2, the only falsifiable success criterion. |
| Extended boilerplate patterns | MED | LOW | **P1** | Cheap; additive; 2% bucket. |
| Filter-config versioning | MED | LOW | **P1** | Proven in-repo pattern; cheap now, expensive later. |
| L1 crawl `fit_markdown` | HIGH | MED | **P2** | In D-1 scope; SCHED-02 interaction must be proven benign first. |
| L2 section classification | MED | MED | **P2** | More precise than statistics; needs L0 first. |
| Domain boilerplate patterns | MED | LOW | **P2** | 3% bucket; zero core change via pack convention. |
| Neighbour refinement | MED | MED | **P2** | Reduces FPs; only worth it once FP rate is measured. |
| `klake quality-report` | MED | MED | **P2** | Turns the metric into a tracked trend. |
| Cross-page repetition | HIGH | HIGH | **P3** | Strongest signal, only new-state feature. Decide with data. |
| QUALITY-01 propagation | LOW | LOW | **P3** | Cannot fix IDF pollution; ingest gate is the real fix. |

## Competitor Feature Analysis

| Feature | DataTrove / FineWeb | RAGFlow | Crawl4AI / jusText | Unstructured | **Our v2.6 approach** |
|---------|---------------------|---------|--------------------|--------------|----------------------|
| Filter unit | Document | Layout region | DOM node / block | Element | **Chunk** (+ section, + document via L0) |
| Length gate | `min_doc_words=50` | n/a | `LENGTH_LOW=70` chars | n/a | `min_tokens` (token-native, ~8–16 start) |
| Sentence check | `min_stop_words=2`, C4 `min_num_sentences=5` | n/a | stopword density 0.30/0.32 | n/a | Gopher `min_stop_words=2` + FineWeb `line_punct_thr=0.12` |
| Boilerplate | `POLICY_SUBSTRINGS` (6 phrases) | `garbage_layouts=[footer,header,reference]` | `<nav>/<footer>` tags + `negative_patterns` | drop `UncategorizedText` | Extended patterns + section classification + (P3) cross-page |
| Link density | n/a | n/a | jusText **0.2**; Crawl4AI weight 0.2 | n/a | 0.2 on markdown links |
| Dedup | MinHash, corpus-wide, document | in-document garbage text | n/a | n/a | **Exact hash at index**, per D-3 (WR-05 preserved) |
| Drop vs tag | **Drop** + `exclusion_writer` + `filter_reason` | **Drop** (`bxs.pop`) | **Drop** (but `short` deferred to context) | **Drop** before embedding | **Drop from path, record the rejection** |
| Observability | `dropped_{reason}` counters + reject dataset | n/a | n/a | n/a | Same contract: `(bool, reason)` + counters + rejects |
| Short-block handling | hard drop | positional `keep_feats` rescue | **defer to neighbours** | n/a | Table exemption (P1) + neighbour refinement (P2) |

The pattern across the table: **we are the only system gating at chunk granularity**, because we are the only one whose primary output is a retrievable unit rather than a training document or a page extraction. That is why the ecosystem gives us signals but not thresholds, and why the garbage-rate metric is not optional — it is the tuning harness for numbers nobody else has published.

---

## Confidence Assessment

| Area | Confidence | Reason |
|------|------------|--------|
| DataTrove filter thresholds | **HIGH** | Read directly from installed `site-packages/datatrove/pipeline/filters/*.py` — primary source, exact defaults, not paraphrase |
| Crawl4AI PruningContentFilter internals | **HIGH** | Read directly from installed `site-packages/crawl4ai/content_filter_strategy.py` |
| Existing codebase behaviour (L0/L3/L5 root causes) | **HIGH** | Direct reads of `clean.py`, `chunk.py`, `curate.py`, `export.py`, `settings.py`; L5 "no quality predicate on export" independently confirmed |
| jusText thresholds | **MEDIUM** | Single authoritative doc (project's own `algorithm.rst`), not cross-checked against source |
| "Drop is the norm at ingest" | **MEDIUM-HIGH** | Converging evidence across 4 independent implementations; DataTrove's `BaseFilter` docstring is explicit |
| RAGFlow `garbage_layouts` | **MEDIUM** | Fetched from GitHub source, single source, not executed |
| Cross-page repetition as strongest signal | **MEDIUM** | Strong literature consensus (SST, arxiv 1409.2590, Pomikálek thesis) but no implementation in our stack to verify against |
| Chunk-level threshold values | **LOW** | **Genuine gap** — nobody publishes these. All chunk-level numbers are adaptations from document-level defaults and must be tuned empirically. |

## Open Questions Resolved / Left Open

| MILESTONE-CONTEXT question | Research answer |
|---------------------------|-----------------|
| 1. Where does the substance gate belong? | **Classify at parse/clean (annotate), gate at chunk (refuse to emit), record the rejection.** Classification and gating are separable, so the "lose lineage vs pay enrich cost" dilemma is false. |
| 2. Should discarded content be recorded? | **Yes — table stakes.** DataTrove's `exclusion_writer` + `filter_reason` + `dropped_{reason}` is the ecosystem norm, and under D-2 it is the only proof v2.6 worked. |
| 3. Does `fit_markdown` thrash the SCHED-02 gate? | **Yes, if `threshold_type="dynamic"`** (adaptive threshold → non-reproducible output). Mitigated by `threshold_type="fixed"` (0.48) + storing `fit_markdown` as a derived artifact with raw untouched. |
| 4. Is 30 chars right, or token-based? | **Token-based** (`ChunkSettings` is token-native). 30 chars is a defensible evidence-anchored *floor* (≈8 tokens; matches FineWeb `short_line_length=30`) but length alone is insufficient — the stopword/punctuation predicates do the real work. |
| 5. Replace or extend `BOILERPLATE_PATTERNS`? | **Extend.** Phase-3 tests depend on them and their line-anchoring encodes the T-03-07 inline-citation guarantee. |
| (unresolved) What is the right `min_tokens`? | **No published value exists at chunk granularity.** Ship as config; tune with the garbage-rate metric. |
| (unresolved) What N for cross-page repetition? | No canonical value. Likely a *fraction* of a source's document count rather than an absolute. |

## Sources

- `datatrove` installed source: `pipeline/filters/{gopher_quality_filter,fineweb_quality_filter,c4_filters,gopher_repetition_filter,base_filter}.py` — **HIGH** (primary, exact defaults read from disk)
- `crawl4ai` installed source: `content_filter_strategy.py` (`PruningContentFilter`, `RelevantContentFilter`) — **HIGH** (primary)
- Knowledge Lake codebase: `pipeline/{clean,chunk,curate,export,index}.py`, `config/settings.py`, `domains/healthcare/` — **HIGH** (primary)
- `.planning/MILESTONE-CONTEXT.md` audit + `.planning/PROJECT.md` — **HIGH** (primary)
- jusText algorithm doc (github.com/miso-belica/jusText/blob/main/doc/algorithm.rst) — **MEDIUM** (authoritative project doc)
- RAGFlow `deepdoc/vision/layout_recognizer.py` (`garbage_layouts`) — **MEDIUM** (GitHub source fetch)
- Gopher / MassiveText (arxiv 2112.11446, incl. Table A1 repetition thresholds) — **MEDIUM** (corroborated by datatrove source comments)
- C4 (JMLR 20-074) — **MEDIUM** (corroborated by datatrove `c4_filters.py` docstring)
- FineWeb (arxiv 2406.17557), FineWeb-2 (arxiv 2506.20920) — **MEDIUM**
- Web template detection (arxiv 1409.2590); Site Style Tree; Pomikálek, *Removing Boilerplate and Duplicate Content from Web Corpora* — **MEDIUM**
- ChunkRAG (arxiv 2410.19572) — **LOW** (abstract only; PDF fetch returned corrupted binary). Cited only to *refute* its applicability as an ingest gate — the abstract is sufficient to establish that it scores relevance against a user query at retrieval time.
- Unstructured.io preprocessing/chunking docs — **LOW** (vendor blog/docs)
- Databricks "Build an unstructured data pipeline for RAG" cookbook — **LOW** (vendor docs)

**Cross-referencing note:** the thresholds in this document were deliberately verified against **installed library source on disk** rather than accepted from search results. This matters — several search summaries reported Gopher's bullet-lines ratio as 0.8 or "80%", while the actual `datatrove` default is `max_bullet_lines_ratio=0.9` and the paper comment reads "more than 90% of lines starting with a bullet point". The web-sourced number was wrong. Any threshold in this document marked HIGH was read from source; treat MEDIUM/LOW thresholds as needing verification before they are hard-coded.

---
*Feature research for: Knowledge Lake Framework v2.6 (Data Quality & Enrichment)*
*Researched: 2026-07-15*
