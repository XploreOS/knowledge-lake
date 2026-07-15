# Stack Research

**Domain:** Content-quality filtering for a crawl→parse→clean→chunk RAG pipeline (v2.6)
**Researched:** 2026-07-15
**Confidence:** HIGH (core findings executed against the pinned, installed versions; cross-checked against official docs)

## Headline Verdict

**Add nothing. Wire what exists.**

Every capability v2.6 needs is already installed and pinned in `pyproject.toml`. The gap is not
missing libraries — it is unwired configuration and one adapter line that discards the filtered
output. Three of the six root causes in `MILESTONE-CONTEXT.md` close with zero new dependencies.

| Layer | Need | Verdict | What to do |
|-------|------|---------|------------|
| L1 crawl | Strip nav/footer/cookie | **Add nothing** | Wire `PruningContentFilter` + `remove_consent_popups` in `crawl4ai_adapter.py` |
| L2 section | Boilerplate classification | **Add nothing** | Extend `BOILERPLATE_PATTERNS` in `pipeline/clean.py` |
| L3 chunk | Minimum-substance gate | **Add nothing** | Wire `FineWebQualityFilter` (installed, unused) in `pipeline/chunk.py` |
| L4 index | Dedup | **Add nothing** | SHA256 over normalized text in `pipeline/embed.py` |
| L5 gold | Quality gate | **Add nothing** | Existing `composite_quality_score` already computed |

The only dependency worth naming is **trafilatura 2.1.0**, and only as a *contingency* if the
already-installed Crawl4AI pruning under-performs on government/clinical HTML. Do not add it
pre-emptively.

## Recommended Stack

### Core Technologies (all already pinned — no version changes)

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| Crawl4AI | **0.9.1** (installed) | L1 boilerplate stripping at crawl time | `PruningContentFilter` verified to remove nav + footer while preserving clinical prose *and* tables. Already a dependency; the filter is simply never constructed. |
| DataTrove | **0.9.0** (installed) | L3 chunk-level substance gate | `FineWebQualityFilter` does line-level analysis with `short_line_length=30` — the audit's exact threshold, arrived at independently. Installed but absent from `_build_filters()`. |
| datasketch | **2.0.0** (installed) | Near-duplicate detection (already used) | Sufficient. The 653 exact duplicates need only SHA256; MinHash stays for corpus-wide near-dup. |
| `hashlib` (stdlib) | — | L4 index-time exact dedup | The 653 duplicates are *exact*. Exact hashing is deterministic, O(1), and needs no library. |

### Supporting Libraries

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| trafilatura | 2.1.0 (2026-06-07, Apache-2.0) | HTML main-content extraction | **Contingency only.** Add if Phase-17 validation shows `fit_markdown` still leaks boilerplate on gov/clinical HTML. Quality leader (WCXB F1 0.859, ~6.6% boilerplate admitted). HTML-only → helps the crawl path, never the PDF path. |
| `re` (stdlib) | — | Marketing/cookie/TOS patterns | Now — `PruningContentFilter` provably does *not* catch cookie banners or enrollment CTAs (see Verified Findings). |

### Development Tools

| Tool | Purpose | Notes |
|------|---------|-------|
| Existing pytest suite | Regression gate | Phase-3 tests depend on `BOILERPLATE_PATTERNS` — **extend, do not replace** (open question 5 in MILESTONE-CONTEXT). |
| `xfail_strict = true` | Already active | A quality gate that silently passes is exactly the v2.5 failure mode this flag now catches. |

## Installation

```bash
# NOTHING TO INSTALL for the recommended path.
# crawl4ai==0.9.1, datatrove==0.9.0, datasketch==2.0.0 are already pinned in pyproject.toml.

# CONTINGENCY ONLY — add if fit_markdown validation fails on gov/clinical HTML in Phase 17:
# uv add trafilatura==2.1.0
```

---

## Verified Findings

Everything below was executed against the installed `crawl4ai==0.9.1` / `datatrove==0.9.0`, not
recalled and not guessed.

### 1. Crawl4AI content filtering — the exact API surface

**`CrawlerRunConfig` has NO `content_filter` parameter.** Verified by signature introspection
across all 100 of its parameters. The content filter is passed to the *markdown generator*, which
is then passed to the run config:

```python
from crawl4ai import AsyncWebCrawler, CacheMode, CrawlerRunConfig, DefaultMarkdownGenerator, PruningContentFilter

config = CrawlerRunConfig(
    check_robots_txt=True,
    cache_mode=CacheMode.BYPASS,
    remove_consent_popups=True,          # browser-side JS: strips GDPR/IAB TCF/CMP cookie walls
    markdown_generator=DefaultMarkdownGenerator(
        content_filter=PruningContentFilter(threshold=0.48, threshold_type="fixed"),
        content_source="cleaned_html",   # options: cleaned_html | raw_html | fit_html
    ),
)
async with AsyncWebCrawler() as crawler:
    result = await crawler.arun(url=url, config=config)

filtered = result.markdown.fit_markdown   # ← the filtered output
```

> **Trap:** the official Crawl4AI docs *prose* states "In CrawlerRunConfig, you can specify a
> `content_filter`". That is wrong for 0.9.1 — the parameter does not exist and passing it raises.
> The docs' *code example* is correct. Trust the code example, not the sentence.

**Verified constructor signatures (0.9.1):**

```python
PruningContentFilter(user_query=None, min_word_threshold=None, threshold_type='fixed',
                     threshold=0.48, preserve_classes=None, preserve_tags=None)
BM25ContentFilter(user_query=None, bm25_threshold=1.0, language='english', use_stemming=True)
DefaultMarkdownGenerator(content_filter=None, options=None, content_source='cleaned_html')
```

**Is `fit_markdown` a separate field alongside `raw_markdown`? Yes.**
`MarkdownGenerationResult` fields: `raw_markdown`, `markdown_with_citations`,
`references_markdown`, `fit_markdown`, `fit_html`.

**What `PruningContentFilter` actually removes:**
1. Decomposes outright: `nav`, `footer`, `header`, `aside`, `script`, `style`, `form`, `iframe`, `noscript`.
2. Prunes nodes whose composite score falls below `threshold`. Score weights:
   `text_density 0.4, link_density 0.2, tag_weight 0.2, class_id_weight 0.1, text_length 0.1`.
3. Penalises class/id matching `nav|footer|header|sidebar|ads|comment|promo|advert|social|share`.

**Empirically verified on synthetic ACC-style clinical HTML** (nav + cookie banner + prose +
dosing table + footer):

| Element | Default `PruningContentFilter()` |
|---------|----------------------------------|
| Nav ("About Us") | **removed** ✓ |
| Footer copyright/TOS | **removed** ✓ |
| Clinical prose | **kept** ✓ |
| Dosing **table** | **kept** ✓ (the key risk — tables survived) |
| Cookie banner | **SURVIVED** ✗ |

Tables survived at the default `threshold=0.48`; `preserve_tags=["table"]` changed nothing on this
input but is a zero-cost safety belt worth setting given eCQI/US Core IG are table-heavy.
The cookie banner survives because `class="cookie-banner"` does not match the negative-pattern
regex — this is what `remove_consent_popups=True` and extended regex are for.

### 2. Two adapter-level defects that would silently nullify the whole L1 fix

Both are in `src/knowledge_lake/plugins/builtin/crawl4ai_adapter.py`:

**(a) `str(result.markdown)` returns `raw_markdown` — always.**
`MarkdownGenerationResult.__str__` is literally `return self.raw_markdown`. Line 160 of the adapter
reads:

```python
markdown_text = str(result.markdown) if result.markdown else ""
```

Configuring a content filter and leaving this line unchanged produces **no behavioural change
whatsoever** — the filter runs, and its output is discarded. This is the same class of bug as L0:
the work is done, nobody reads it. Must become an explicit `result.markdown.fit_markdown` read
with a fallback to `raw_markdown`.

**(b) `fit_markdown` becomes a poison string on filter failure.**
In `markdown_generation_strategy.py`:

```python
except Exception as e:
    fit_markdown = f"Error generating fit markdown: {str(e)}"
```

The exception is swallowed and the *error message becomes the content*. Under a naive
`fit_markdown or raw_markdown` fallback this truthy string sails into the WORM raw zone as a
document. Guard explicitly, do not rely on truthiness.

Also: `fit_markdown` defaults to `""` (empty string), **not** `None`, when no filter is set —
`generate_markdown` returns `fit_markdown=fit_markdown or ""`. Docs claim `None`. Check
truthiness, never `is None`.

### 3. DataTrove at section/chunk granularity — usable, with sharp edges

**Is DataTrove's `Document`-in model document-scoped by design? No.**
`Document` is a 4-field dataclass — `text`, `id`, `media`, `metadata`. It is a plain text wrapper
with nothing binding it to whole-document scope. Filters expose
`.filter(doc) -> bool | tuple[bool, str]`. Any string can be wrapped at any granularity.
`pipeline/curate.py::score_document()` already proves the in-memory pattern (and correctly avoids
DataTrove's disk I/O scaffolding). The same call works on a chunk.

The *thresholds*, however, are calibrated for whole web documents. That distinction is where the
danger lives.

**Empirically tested against the audit's five garbage categories + a clinical-prose control:**

| Audit category | Count | `FineWebQualityFilter` | `C4ParagraphFilter` |
|---|---|---|---|
| Too short ("Featured") | 762 (16%) | **REJECT** `line_punct_ratio` ✓ | REJECT ✓ |
| No real sentences (menu labels) | 408 (9%) | **REJECT** `line_punct_ratio` ✓ | REJECT ✓ |
| Nav bar, 3 links | — | **REJECT** `line_punct_ratio` ✓ | REJECT ✓ |
| Marketing/pricing CTA | 152 (3%) | PASS ✗ | REJECT ✓ |
| Cookie banner | 123 (2%) | PASS ✗ | REJECT ✓ |
| **LEGIT clinical prose (control)** | — | **PASS** ✓ | **REJECT** ✗✗ |

**`FineWebQualityFilter` is the single highest-leverage unused asset in the stack.** It is already
installed, is absent from `_build_filters()`, and cleanly separates the two largest garbage
categories (**1,170 chunks = 26% of the corpus**) from legitimate clinical content. Its default
`short_line_length=30` independently matches the audit's empirically-derived 30-char threshold —
strong convergent evidence that 30 chars is the right floor (open question 4).

Verified signature:
```python
FineWebQualityFilter(line_punct_thr=0.12, line_punct_exclude_zero=False, stop_chars=None,
                     short_line_thr=0.67, short_line_length=30,
                     char_duplicates_ratio=0.01, new_line_ratio=0.3, language='eng')
```

**Two filters that MUST NOT be used at chunk granularity — both verified to destroy good content:**

- **`C4ParagraphFilter` rejects everything**, including the clinical-prose control, with reason
  `"< 3 paragraphs"`. No 512-token chunk has 3 paragraphs. Using it as a chunk gate would empty the
  corpus.
- **`GopherQualityFilter` false-rejects legitimate chunks.** `curate.py`'s current
  `min_doc_words=50` rejects a 26-word clinical chunk (`gopher_short_doc`). Lowering to
  `min_doc_words=20` *still* rejects it — via `min_stop_words=2`, because a short clinical sentence
  legitimately contains fewer than two of `{the, be, to, of, and, that, have, with}`. Gopher's
  heuristics assume document-length text.

**Therefore: v2.6 needs NEW chunk-scoped threshold settings — do not reuse `CurateSettings`.**
The document-level thresholds are correct for the pretrain path and must stay untouched there.

**One tuning risk to validate in-phase:** `short_line_thr=0.67` rejected the single sentence
`"Aspirin reduces risk."` (`short_line_ratio`). Markdown chunks with many short lines — bulleted
clinical criteria, table rows — may false-reject. Tune `short_line_thr` against a held-out sample
of *known-good* chunks before enabling as a hard gate; consider annotate-first, gate-second
(mirrors the CLEAN-02 language-detection precedent).

**Edge cases are safe:** empty and whitespace-only text return `(False, 'empty')` — no
`ZeroDivisionError` on the `new_line / len(words)` path.

### 4. Index-time dedup — nothing to add

The audit's 653 duplicates are **exact**, not near. `hashlib.sha256` over normalized chunk text is
deterministic, O(1) per chunk, and requires no dependency. `datasketch==2.0.0` is already present
and already carries corpus-wide near-dup via `curate.batch_dedup_corpus()` if fuzzy matching is
ever wanted at index time.

Integration point for D-3: **`src/knowledge_lake/pipeline/embed.py::embed()`** — the single
chokepoint between chunk artifacts and vectors. Dedup here keeps `chunk()`'s
`{parsed_artifact_id}:{text}` key (WR-05) fully intact, exactly as D-3 requires. Do not touch
`chunk.py:318`.

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| Crawl4AI `PruningContentFilter` (installed) | trafilatura 2.1.0 | If Phase-17 validation shows `fit_markdown` leaking boilerplate on gov/clinical HTML. Best-in-class quality (WCXB F1 0.859). Cost: +4 transitive deps (lxml, justext, courlan, htmldate). HTML-only. |
| `PruningContentFilter` | `BM25ContentFilter(user_query=...)` | Query-scoped extraction. **Not applicable** — ingestion is query-agnostic; there is no query at crawl time. |
| Extended regex (deterministic) | `LLMContentFilter` | **Never.** Violates the deterministic-first constraint and would route per-page LLM calls outside the cost model. |
| SHA256 exact dedup | `datasketch` MinHash at index time | Only if near-duplicates (not the audited exact 653) prove to be a material problem later. Already installed — no new dep either way. |

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| **`C4ParagraphFilter` at chunk level** | Verified: rejects 100% of chunks including legitimate clinical prose (`"< 3 paragraphs"`). Would empty the corpus. | `FineWebQualityFilter` |
| **`GopherQualityFilter` at chunk level** | Verified: false-rejects a legit 26-word clinical chunk at both `min_doc_words=50` and `20` (via `min_stop_words`). Document-calibrated. | `FineWebQualityFilter` + chunk-scoped settings |
| **`CurateSettings` thresholds reused for chunks** | Same root cause — tuned for whole documents; correct where they are, wrong at chunk scope. | New chunk-scoped threshold fields |
| **`CrawlerRunConfig(content_filter=...)`** | Parameter does not exist in 0.9.1. Docs prose is wrong. | `CrawlerRunConfig(markdown_generator=DefaultMarkdownGenerator(content_filter=...))` |
| **`str(result.markdown)`** | Returns `raw_markdown` unconditionally — silently discards the filter's entire output. Repeats the L0 bypass. | `result.markdown.fit_markdown` with guarded fallback |
| **`LLMContentFilter`** (crawl4ai) | Per-page LLM call violates deterministic-first; bypasses LiteLLM gateway. | `PruningContentFilter` |
| **boilerpy3 1.0.7** | Dormant — last release 2023-11-01 (~2.7 years). | Nothing needed |
| **readability-lxml 0.8.4.1** | Minimal maintenance; lower precision than trafilatura in every benchmark surveyed. | trafilatura (contingency) |
| **resiliparse 1.0.8** | Fast and actively maintained, but admits **22.8% boilerplate** vs trafilatura's 6.6% — optimises recall, which is precisely the wrong trade for a garbage-reduction milestone. Pins `fastwarc==1.0.8`. | trafilatura (contingency) |
| **jusText 3.0.2** | Subsumed — already a transitive dependency *of* trafilatura. No reason to use directly. | trafilatura (contingency) |
| **NeMo Curator** | GPU-first; violates the CPU-only DigitalOcean constraint. | DataTrove (installed) |

## Stack Patterns by Variant

**If `fit_markdown` validates clean on gov/clinical HTML (expected):**
- Add zero dependencies. Wire `PruningContentFilter` + `remove_consent_popups=True` + the
  `fit_markdown` read in `crawl4ai_adapter.py`.

**If `fit_markdown` leaks boilerplate on ACC/eCQI/US Core IG (the 81%/69%/72% offenders):**
- Add `trafilatura==2.1.0` behind the existing plugin seam, applied to `result.html`.
- Because it is HTML-only, it cannot help the PDF path — that garbage must be caught at L3 by
  `FineWebQualityFilter` regardless.

**If `short_line_thr=0.67` false-rejects legitimate table rows / bulleted criteria:**
- Ship the gate in annotate-only mode first (record `substance_status` in chunk metadata),
  measure, then flip to a hard gate. Mirrors the CLEAN-02 language-detection precedent.

## Version Compatibility

| Package | Compatible With | Notes |
|---------|-----------------|-------|
| crawl4ai 0.9.1 | (installed, pinned) | `remove_consent_popups` requires a browser context — Playwright 1.61.0 already present. No new pin. |
| datatrove 0.9.0 | spacy>=3.8, nltk>=3.10 | Both already pinned. `FineWebQualityFilter` uses the same `split_into_words` path as the already-working `GopherRepetitionFilter` (per commit 9a28f92) — no new download step. |
| trafilatura 2.1.0 (contingency) | lxml>=6.1.1, justext>=3.0.2, courlan, htmldate | **Check `lxml>=6.1.1` against Docling 2.112.0's lxml constraint before adding** — the Typer/docling pin precedent shows this project has been bitten by exactly this. |
| datasketch 2.0.0 | (installed) | No change. |

## Answers to the Open Questions

- **Q4 (30 chars vs token-based):** Use **30 chars**. `FineWebQualityFilter.short_line_length`
  independently defaults to exactly 30 — the audit and FineWeb's production tuning converged. It
  is also a *line*-level metric, which token counts cannot express. Keep `tiktoken` for
  `max_tokens`; the floor is a different measurement, not the same one inverted.
- **Q5 (replace vs extend `BOILERPLATE_PATTERNS`):** **Extend.** Phase-3 tests depend on the 4
  existing regexes, and the new burden (marketing CTAs, TOS blocks, cookie text) is additive —
  `FineWebQualityFilter` provably does not catch those two categories, so regex remains load-bearing.
- **Q3 (`fit_markdown` × SCHED-02 change gate):** Real risk, and it cuts *favourably*. The
  SCHED-02 gate already normalizes silver text; pruning nav/footers removes the most volatile page
  regions, which should make re-crawl diffs **more** stable, not less. The genuine hazard is
  threshold non-determinism across crawls — `threshold_type='fixed'` (the default) is
  deterministic; **`threshold_type='dynamic'` is not and must not be used** given the WORM raw zone.

## Sources

- **`crawl4ai==0.9.1` installed package** — `content_filter_strategy.py`, `markdown_generation_strategy.py`, `models.py`, `async_configs.py`: signature introspection + source read + executed on synthetic clinical HTML. Confidence: **HIGH** (executed against the pinned version).
- **`datatrove==0.9.0` installed package** — `Document` dataclass fields, filter registry, `FineWebQualityFilter.filter` source; executed against all 5 audit garbage categories + prose control. Confidence: **HIGH**.
- [Crawl4AI Fit Markdown docs](https://docs.crawl4ai.com/core/fit-markdown/) · [Markdown Generation docs](https://docs.crawl4ai.com/core/markdown-generation/) — cross-check of the `fit_markdown` field and generator wiring. Confidence: **MEDIUM** (prose contains a verified error re: `CrawlerRunConfig(content_filter=)`).
- [PyPI JSON API](https://pypi.org/pypi/trafilatura/json) — trafilatura 2.1.0 / resiliparse 1.0.8 / justext 3.0.2 / readability-lxml 0.8.4.1 / boilerpy3 1.0.7 versions, licenses, upload dates. Confidence: **HIGH** (authoritative registry).
- [WCXB: A Multi-Type Web Content Extraction Benchmark](https://arxiv.org/html/2605.21097v1) · [WCXB Leaderboard](https://webcontentextraction.org/) — trafilatura F1 0.859 vs resiliparse 0.797, boilerplate-admission rates. Confidence: **MEDIUM**.
- [An Empirical Comparison of Web Content Extraction Algorithms (Bevendorff et al., SIGIR 2023)](https://dl.acm.org/doi/pdf/10.1145/3539618.3591920) · [Trafilatura evaluation docs](https://trafilatura.readthedocs.io/en/latest/evaluation.html) — corroborating ranking. Confidence: **MEDIUM**.
- **Repo code grounding** — `pipeline/clean.py`, `pipeline/curate.py`, `pipeline/chunk.py:318`, `pipeline/embed.py`, `plugins/builtin/crawl4ai_adapter.py:160`, `config/settings.py`, `pyproject.toml`. Confidence: **HIGH**.

---
*Stack research for: v2.6 Data Quality & Enrichment*
*Researched: 2026-07-15*
