# Project Research Summary

**Project:** Knowledge Lake Framework
**Milestone:** v2.6 — Data Quality & Enrichment
**Domain:** Retrofitting deterministic content-quality filtering into a shipped, lineage-tracked RAG pipeline
**Researched:** 2026-07-15
**Confidence:** HIGH on mechanism (nearly every claim grounded to file:line in this repo or executed against pinned library versions); LOW on threshold values (nobody publishes chunk-level numbers)

## Executive Summary

This is not a "add a filter" milestone. It is a **lineage repair** milestone wearing a quality costume. The audit's 28% garbage is a symptom; the disease is that `clean()` is a **leaf, not a link** — its only consumer is `curate` → the pretrain export. That is precisely why the DataTrove-filtered pretrain corpus looks healthy while the RAG corpus is 33% junk. The filters exist; they are on the branch nobody reads. The lineage graph already asserts a cleaning relationship the RAG path does not honor (`enrich.py:438` parents `enriched_document` to cleaned, while chunks/trees parent to parsed — chunks are **siblings** of `cleaned_document`, not descendants). That is a live violation of the PROJECT "Lineage" constraint, not a quality defect.

**The stack verdict is unusually clean: add nothing, wire what exists.** Every capability v2.6 needs is already pinned and installed. `FineWebQualityFilter` (installed, absent from `_build_filters()`) was executed against the audit's five garbage categories: it rejects the two largest buckets — **1,170 chunks = 26% of the corpus** — while passing a clinical-prose control. The only contingency dependency worth naming is trafilatura 2.1.0, and only if crawl-time pruning under-performs on gov/clinical HTML. Do not add it pre-emptively. Two document-calibrated filters were verified to be *actively destructive* at chunk scope: `C4ParagraphFilter` rejects 100% of chunks including legitimate clinical prose ("< 3 paragraphs" — no 512-token chunk has three), and `GopherQualityFilter` false-rejects a legit 26-word clinical chunk at both `min_doc_words=50` and `20`, via `min_stop_words`. v2.6 needs **new chunk-scoped threshold settings**; `CurateSettings` is correct where it is and wrong at chunk scope.

**The risk profile is the unifying theme.** This system was deliberately built to degrade gracefully at every layer — `index.py` nulls payload fields when a join misses (D-01, documented), `clean.py` returns a foreign artifact on hash collision, `route.py` auto-falls-back when tree results are empty (ROUTE-03/D-05), `export.py` falls back to metadata text when S3 reads fail. Each is a deliberate, documented, *correct-in-isolation* choice. Under a retrofit, graceful degradation stops being a safety property and becomes a **hazard**: nearly every failure mode below manifests as **silence, not exceptions**. **A v2.6 that breaks lineage will still be 971 tests green.** This is v2.5's own retrospective lesson recurring one layer down — *green gates measure mechanism, not output* — and the mitigation is structural: measurement before filtering, report-only before enforce, and the audit's classifier must stay independent of the gate's or the metric is a tautology.

---

## Contradicts the Brief

**This section requires an explicit user decision before requirements are defined.** Four findings undercut the milestone brief. Two are confirmed scope decisions (D-1, D-2) that the evidence says are wrong as stated.

### C-1: The brief undercounts the bypass — `klake process` never calls `clean()` at all

| | |
|---|---|
| **Brief says** | L0 is `assets.py:325` — Dagster's `clean_document` forwards the uncleaned `parsed_doc`. |
| **Evidence** | Confirmed exactly as briefed. **But `pipeline/process.py::process_crawled` — the implementation behind `klake process` (`cli/app.py:672`) — runs `parse → chunk → embed → index` at `process.py:103-112` and has no clean stage at all.** `clean()` has exactly four call sites corpus-wide: `cli/app.py:229`, `api/app.py:788`, `assets.py:318` (result discarded), and nothing else. **The audit that produced the 4,499-chunk / 28% evidence was an audit of `klake process`** (MILESTONE-CONTEXT.md:4) — a path that never had a clean stage to bypass. |
| **Consequence** | Fixing `assets.py:325` alone leaves the audited command producing 28% garbage. **The headline metric will not move on the command people actually run.** |
| **Recommendation** | **Fix both call paths in the same phase.** Raises L0 from "one-line dict fix" to "unify the pipeline entry points." Non-optional. |

**Related narrowing, in the brief's favor:** `enrich` is **not** fully bypassed. It reads the **cleaned blob** for its main text (`enrich.py:319-335`) and caches on `_enrichment_cache_key(cleaned_content_hash, prompt_version)` (`enrich.py:107`). Only `parsed_doc.sections` / `.metadata` are uncleaned (`enrich.py:340-341`). **The "pay enrich cost on garbage" horn of Open Question 1 largely dissolves** — enrich is per-*document*, not per-chunk (`enrich.py:279`). But the cleaned-hash cache key makes stronger cleaning a **billing event** (see C-4 / Pitfall 4).

### C-2: D-1's crawler-level extraction (SELECTED) is a no-op-plus-risk — recommend defer or drop

| | |
|---|---|
| **Brief says** | D-1 selected: crawler-level stripping via `fit_markdown` / `PruningContentFilter` "so nav/footers never enter the raw zone." |
| **Evidence** | `fit_markdown` affects `result.markdown` — **not** `result.html`. `_write_artifacts` writes raw = **HTML** (`crawl.py:879-884`), bronze = **markdown** (`crawl.py:892-897`). **Nothing reads bronze**: grep returns only the writer, the ID-prefix map (`ids.py:42`), and docstrings. `process_crawled` selects `raw_document` (`process.py:78`) and re-parses raw HTML through Docling. The change gate reads `probe.markdown` (`crawl.py:190`) — **affected, and live.** |
| **Consequence** | Enabling `fit_markdown` today changes exactly two things: **a dead-end artifact, and the re-crawl change gate.** It improves nothing on the RAG path while destabilizing re-crawl — the strictly worst combination. D-1's stated premise is also false: pruning never touches the raw zone under the current write path, so **the WORM concern the brief raises dissolves**, and with it D-1's rationale. |
| **Recommendation** | **Defer or drop D-1's crawler-extraction item.** The L2 section classifier covers a **superset**: it deletes nav/footers regardless of crawl pruning, at a stage that is reversible, evidenced by the parsed sidecar, and **uniform across HTML, PDF, CSV and manual upload** — whereas crawl pruning only ever helps crawled HTML. For L1 to pay off, `parse()` must consume bronze instead of re-parsing raw HTML — a much larger change that partially duplicates L2's work. If kept, keep it **last**, gated on the metric proving crawl-shaped garbage survives L2. |

Two verified aggravators: **Crawl4AI bug #582** (open since 2025-01-29, unfixed) strips `<a>` and `<strong>` **including their text** — bolded drug names, bolded warnings, and link text to the authoritative source, deleted. And **link-density scoring kills index/TOC pages** — a guideline index or eCQI measure list is ~100% links by construction and indistinguishable from nav, yet is real content for the tree index (TREE-01). ROUTE-03's D-05 auto-fallback then means the tree index can quietly stop working while every query still returns something. L1 is also the only layer whose mistakes are unrecoverable in practice: nothing re-derives bronze from raw.

### C-3: D-2 forward-only (SELECTED) is factually wrong for gold, and actively harmful for BM25

**(a) "Forward-only" is false for the gold zone.** `export_rag_corpus` scans `list_artifacts_by_type(session, "chunk")` — **the whole registry** — on every run (`export.py:286`) and writes a fresh Parquet snapshot under a new `export_id` (`export.py:366`). Gold is a **materialized view, not a persisted tier.** A gate there drops the 119 junk rows out of the existing 357 **immediately, with zero new ingests**. This is a *benefit* — take it — but it manufactures two metrics that move for different reasons:

| Metric | Behavior after the gate lands | Why |
|---|---|---|
| Gold RAG corpus junk % | 33% → ~0% **on the next export run** | Full re-derivation + gate |
| Qdrant chunk garbage % | Unchanged at ~28% | Forward-only, no backfill |

**The number that improves fastest is the one that measures the least.** Someone will run `export-rag-corpus`, see 0%, and declare v2.6 shipped while search still returns "Featured".

**(b) Forward-only makes BM25 monotonically *worse* over time.** `qdrant_store.py:156` creates the sparse vector with `SparseVectorParams(modifier=Modifier.IDF)`. Qdrant computes IDF from **live collection statistics** — `IDF(q_i) = ln((N - n(q_i) + 0.5) / (n(q_i) + 0.5) + 1)`. Under D-2, as clean documents are added, `N` grows while `n(nav_term)` **stops growing**. **`IDF(nav_term)` therefore climbs monotonically forever and never self-corrects.** The corpus gets cleaner and the garbage gets *more prominent*, simultaneously. "The garbage will get diluted as we add clean sources" — the implicit assumption behind accepting D-2 — is **the opposite of true for the sparse branch**. Dilution works for dense; it inverts for BM25.

**Recommendation:** Revise D-2 from "do nothing about old chunks" to **"flag old chunks in payload, exclude at search."** Stamp `substance_gate: "pre_v2_6"` via `refresh_all_points_payload` — the **KL-06 reindex path already exists to stamp payload fields onto existing points without re-embedding** (`index.py:359-365`). Solved problem in this codebase. The point worth making loudest: **forward-only was chosen to protect WORM immutability, but retrieval-time exclusion achieves the quality goal without touching a single stored byte.** The v2.0 STORE-01 precedent D-2 invokes was about not *rewriting raw keys*; it says nothing about filtering at query time.

### C-4: The 30-char floor is the wrong instrument — wrong unit, and it targets the wrong content

| | |
|---|---|
| **Brief asks (Q4)** | "Is the 30-char threshold the right floor, or should it be token-based?" |
| **Evidence** | **Wrong unit:** `ChunkSettings` is token-native (`cl100k_base`, `max_tokens: 512`, `chunk.py:53`); `token_count()` is a cached O(1) call. A char floor beside a token ceiling is two incompatible units gating the same object. **Wrong target:** sub-30-char content that is legitimately load-bearing — `ICD-10 E11.9` (12), `Metformin 500 mg PO BID` (23), `LOINC 2160-0` (12), `Contraindicated in pregnancy` (28), `See §164.312(a)(1)` (18), `Cardinality: 0..1` (17), `Do not exceed 4 g/day` (21). |
| **The kicker** | The audit's worst sources — **US Core IG (72%), eCQI (69%)** — are precisely the specification-style documents whose real content **is** terse normative statements. A char floor would score an IG's normative cardinality table as garbage and its verbose introduction as good. **The garbage-rate metric would improve while the corpus got worse.** The v2.5 lesson recurring in a new instrument. |
| **Recommendation** | The audit measured a **correlation** (short ⇒ usually junk). Correlation is a fine detector and a terrible gate. Use a deterministic composite: `token_count < min_tokens` (~8) **AND** `NOT is_table` **AND** alpha_ratio out of band **AND** no domain-signal hit **AND** (high link_density OR ~zero stopword_ratio). Hard exemptions: `is_table=True` always; a **healthcare-pack domain-code allowlist** (`ICD-10 \w\d+`, `LOINC \d+-\d`, `RxNorm \d+`, `§\d+\.\d+`, `\d+\s*(mg\|mcg\|g\|mL\|units)`, `\d+\.\.\d+`). **The core gate must be domain-agnostic; the allowlist must be the domain pack's.** |

**One genuine tension between researchers, and it is resolvable:** STACK argues **30 chars** (because `FineWebQualityFilter.short_line_length` independently defaults to exactly 30 — convergent evidence); FEATURES, ARCHITECTURE and PITFALLS argue **tokens**. Not in conflict: 30 chars is FineWeb's *line*-level metric **inside** `FineWebQualityFilter`, adopt as-is; the *chunk* floor is a different measurement and should be token-denominated (~8 tokens ≈ 30 chars). Use both, at their own granularities. Never write a bare `len(text) < 30`.

---

## Key Findings

### Recommended Stack — "add nothing, wire what exists"

| Layer | Verdict | What to do |
|-------|---------|------------|
| L1 crawl | Add nothing | Wire `PruningContentFilter` + `remove_consent_popups` — **but see C-2; likely defer** |
| L2 section | Add nothing | Extend `BOILERPLATE_PATTERNS` in `pipeline/clean.py` |
| L3 chunk | Add nothing | Wire `FineWebQualityFilter` (installed, unused) |
| L4 index | Add nothing | `hashlib.sha256` (stdlib) — the 653 duplicates are **exact**, not near |
| L5 gold | Add nothing | `composite_quality_score` already computed |

**Core technologies:**
- **DataTrove 0.9.0** (installed) — `FineWebQualityFilter` is **the single highest-leverage unused asset in the stack**. Verified: rejects "too short" (762) and "no real sentences" (408) via `line_punct_ratio` while **passing** the clinical-prose control.
- **Crawl4AI 0.9.1** (installed) — `PruningContentFilter` verified on synthetic ACC-style HTML: nav removed ✓, footer removed ✓, clinical prose kept ✓, **dosing table kept ✓** (the key risk), **cookie banner SURVIVED ✗**. Regex remains load-bearing regardless.
- **`hashlib` (stdlib)** — exact dedup needs no library.
- **trafilatura 2.1.0** — **contingency only.** WCXB F1 0.859, ~6.6% boilerplate admitted (vs resiliparse's 22.8%). HTML-only → cannot help the PDF path. **Check `lxml>=6.1.1` against Docling's constraint before adding** — the Typer/docling pin precedent shows this project has been bitten by exactly this.

**Three verified API traps that would silently nullify the whole L1 fix:**
1. **`CrawlerRunConfig` has NO `content_filter` parameter** in 0.9.1 (verified across all 100 params). The docs' *prose* says it does; the docs' *code example* is correct. Pass the filter to `DefaultMarkdownGenerator`.
2. **`str(result.markdown)` returns `raw_markdown` — always.** `MarkdownGenerationResult.__str__` is literally `return self.raw_markdown`. `crawl4ai_adapter.py:160` does exactly this. **Configuring a filter and leaving that line unchanged produces no behavioural change whatsoever — the filter runs and its output is discarded. Same class of bug as L0: the work is done, nobody reads it.**
3. **`fit_markdown` becomes a poison string on filter failure** — `except Exception as e: fit_markdown = f"Error generating fit markdown: {str(e)}"`. Under a naive `fit_markdown or raw_markdown` fallback, that truthy error string sails into the zone as document content. It also defaults to `""`, not `None`. Check truthiness, never `is None`.

### Expected Features

**Must have (table stakes):**
- **L0 — cleaned text on the load-bearing path, both call paths**
- **`quality/` pure-predicate module** — `f(text) -> (bool, reason)`; **zero dependencies, no I/O, build first in parallel with L0**
- **L3 — min-substance gate at chunk**, with `is_table` exemption + domain allowlist
- **Extended boilerplate patterns** — additive to the existing 4
- **L4 — index-time exact dedup** — **only after L3**
- **L5 — quality gate on gold RAG export** — currently **no quality predicate at all**
- **Rejection recording + garbage-rate metric** — the brief lists the re-runnable audit as a "candidate"; **all four researchers say table stakes.** Under D-2 it is the only falsifiable success criterion. Nearly free — DataTrove already emits the reasons; the counters are being thrown away.
- **Filter-config versioning** — reuse the proven `_curation_cache_key` pattern

**Should have:** section-level classification (annotate, don't delete); domain-scoped `boilerplate.yaml` via the existing `DomainLoader` rail; neighbour-context refinement (jusText's insight: a short block is nav-or-heading depending on neighbours); `klake quality-report`.

**Defer:** cross-page repetition detection (**the strongest boilerplate signal available**, and the only feature needing new persistent state — decide with the metric, not opinion); QUALITY-01 search propagation (cannot fix IDF pollution); retroactive backfill (raw is immutable and intact — deferring costs nothing but patience).

**Anti-features:** per-chunk LLM classification (~150× call-count vs the per-document norm; **nondeterministic output breaks content-hash idempotency**, voiding the measurement control; ChunkRAG is **miscited** — it scores relevance *to a query at retrieval time*, a different axis from is-this-garbage); near-dup dedup at index time; a single global threshold across dataset types; prose heuristics on tables.

### Architecture Approach

**The structural change in one sentence: `clean` moves from being a leaf to being the fan-out node.** `clean()` loads sections via the existing `load_parsed_doc()` → `reparse_from_raw()` fallback, classifies, drops junk sections, writes a cleaned sections sidecar, and **returns a cleaned `ParsedDoc`** consumed in-memory by chunk/tree/enrich.

**Three decisions, each with a rejected alternative:**

1. **Chunks must NOT re-parent to `cleaned_artifact_id`.** Five things break, two are safety gates: cross-source lineage corruption; `index.py:191` payload resolution silently nulls (`get_enriched_artifact_for_parsed` walks parsed→cleaned→enriched; hand it a cleaned ID and it returns `None`); `export.py:301` breaks identically **while v2.6 is trying to gate exports on quality**; the **fail-closed** contamination gate (`export.py:113-119`) is perturbed; the KL-06 reindex repair path resolves against a stale contract. **Change the data, not the parentage** — record `cleaned_artifact_id` additively in chunk `metadata_`. **The recommended design touches no artifact parentage anywhere.**
2. **Never re-read the cleaned blob from S3 to re-derive sections.** `clean()`'s exact-dedup early return (`clean.py:305-320`) can return **another source's artifact**. Re-reading it converts a dedup optimization into **silent cross-source content substitution**. In-memory forwarding is immune.
3. **No `FilterPlugin` seam.** Every existing seam wraps a replaceable *external tool* with a competing ecosystem. Content filtering has none. **The precedent is decisive: DataTrove is called directly from `curate.py:119` and was never given a seam** — despite being an external tool with real alternatives. If DataTrove didn't earn a seam, a regex classifier hasn't. Variability here is **by domain, not by tool** — use the proven domain-pack rail.

**Major components:**
1. **`clean()`** — section-aware filtering; returns cleaned `ParsedDoc`; writes cleaned sidecar + drop-count metadata — *the load-bearing change*
2. **`quality/` predicate module** — pure functions, no I/O, most of the milestone's value, testable before any wiring
3. **`dedup_chunks` (new)** — between chunk and embed; Postgres `chunk_text_index` ledger + `uuid5(NAMESPACE, sha256(text))` point IDs
4. **`_GATE_NORMALIZE_PATTERNS` (new)** — frozen copy in `crawl.py`; severs the gate from the clean stage

### Critical Pitfalls

1. **L0 activates a dormant lineage-corruption bug — and its rate scales with the milestone's own success.** `clean.py:232` hashes `sha256(cleaned_bytes)` — **text alone, no parent scoping**, unlike `chunk.py:317`'s deliberate WR-05 `f"{parsed_artifact_id}:{text}"` — behind a **`UNIQUE(content_hash, artifact_type)`** index (`repo.py:363`). So there is **at most one `cleaned_document` per unique cleaned text, corpus-wide**, and on collision `clean()` returns *another document's* artifact. Dormant only because nothing on the RAG path reads it. **L0 activates it.** Two thin ACC landing pages (81% garbage) whose only content is nav + title collapse to identical bytes once nav is stripped aggressively — **the more successful the filter, the more lineage corruption it creates.** Consequences: cross-document lineage corruption (exactly what WR-05 exists to prevent, arriving through the door nobody was watching), payload null-out, and **false contamination reports that fail closed and block the milestone at its final step.** *Avoid:* adopt WR-05's convention in `clean.py` in **the same phase as L0, non-negotiably**; keep the S3 key content-addressed on text (dedupe **storage**, not **identity**); make the child lookup deterministic (`created_at DESC`) since new-scheme hashes create a second cleaned child.
2. **Dedup makes boilerplate MORE retrievable — hard ordering constraint L3 → L4.** The 653 duplicates are **currently suppressing themselves**: a footer term in ~653 of 4,499 points → high `n` → low IDF → BM25 correctly treats it as noise. Collapse to one point and `n` drops 653 → 1, **IDF spikes, and the single surviving footer becomes a highly discriminative top-ranked BM25 hit.** *You will have removed 652 mediocre hits and manufactured one excellent one.* Invisible because IDF is computed **server-side inside Qdrant** — no IDF code in this repo to grep; `sparse_embedder.py:19` even says "this module only emits raw term-frequency vectors." **Dedup alone is actively harmful; dedup after filtering is safe.**
3. **`remove_boilerplate` is shared by the clean stage AND the change gate.** `crawl.py:115` calls the *same function* `clean.py:81` uses, deliberately (D-06). **Extending `BOILERPLATE_PATTERNS` therefore changes every source's content signature → all 34 report "changed" → 34 full crawls against FDA/CMS/ACC/NLM on one tick.** The brief treats L1 and open-question-5 as independent; **the code says they are one change.** The coupling is *already known-hazardous*: `crawl.py:67-75` carries an explicit warning and v2.0's retrospective records "gate-local normalization" as an established pattern — **the shared pattern list was left inside the blast radius anyway. This is v2.5 Lesson 2 verbatim: "a recorded lesson is not an enforced one."** Good news: raw is structurally safe (`put_raw` is a registry no-op *before* any S3 write, `s3.py:277-287`) — a cost event, not a corruption event. *Avoid:* sever the gate's normalizer early; the gate wants **frozen**, clean wants **aggressive, evolving** — opposite objectives, must not share a mutable list.
4. **Stronger cleaning is a BUDGET event that fails closed.** Four caches key on the cleaned content hash: enrichment (`strong_model`, per doc), curation (CPU), tree index, and **dataset-gen — keyed per chunk, per `eval_model` call.** Change the patterns → all miss → full re-enrichment → the `LlmSpend` cap does exactly what it was designed to do: **halt gracefully, mid-corpus.** Half re-enriched, half stale, run stopped — and it looks like a mysterious pipeline failure to anyone who didn't plan for it. **The pattern that saved money is the pattern that now bills you.** *Avoid:* estimate cost in requirements; **sequence the substance gate BEFORE the re-enrichment** so you re-enrich a 28%-smaller corpus (cheaper *and* better).
5. **Repetition is simultaneously the best boilerplate signal and the best normative-content signal.** FDA boxed warnings, "*This guidance represents the current thinking of the FDA... does not establish legally enforceable responsibilities*", CMS "not a legal document" notices — identical on every page **by the authors' intent**. The existing `^(?:disclaimer|copyright \d{4})[^\n]*$` (`clean.py:59`) **already strips FDA/HHS disclaimer lines today.** Deleting a black-box warning from a healthcare RAG corpus is a **safety** defect, not a quality one — and it is invisible: nothing fails, the garbage rate *improves*, the corpus quietly loses its contraindications. *Avoid:* repetition alone must **never** be sufficient to drop; require conjunction with positional invariance + link density + absence of domain terms. **Report-only mode is mandatory here, not optional.** Given Trafilatura's **recall 0.92** (SANDIA SAND2024-10208) is the best-in-class floor, **~8% real-content loss is the baseline for a mature extractor. Budget for it; measure it; don't assume zero.**
6. **The gate placement question has a decisive answer the brief's framing misses.** `chunk_document` and `tree_index_document` are **parallel consumers of the same sections** needing **opposite** filters: a TOC page and a body-less heading are **worthless chunks and perfectly good tree nodes** (TREE-03: "deterministic mode uses heading text" as the summary). A gate at parse/clean cannot express that — one output, two consumers, conflicting requirements. Degradation is silent via ROUTE-03's auto-fallback. **Answer: parse never gates; clean strips text-level boilerplate and ANNOTATES sections with substance signals; chunk gates; tree applies its own much weaker filter.** The "pay enrich cost" objection dissolves (enrich is per-document and already reads cleaned text). Mirrors v2.5's own sidecar pattern: compute derived signal once, persist beside the data, let each consumer decide.

---

## Implications for Roadmap

Phase numbering continues at **17**. Sequenced by hard dependency — **L0–L5 is a taxonomy of causes, not a build order.**

### Phase 17: Close the bypass (both paths) + WR-05 hash fix + measurement hooks
**Rationale:** The only prerequisite for every other change — with the bypass open, no filter can be observed to work. Also the **highest-risk** phase: a lineage fix whose defects corrupt data rather than merely degrade it.
**Delivers:** `clean()` loads sections via `load_parsed_doc()` → `reparse_from_raw()` fallback, applies **today's existing weak patterns** per section, writes the cleaned sidecar, returns the cleaned `ParsedDoc`. `clean_document` forwards it. **`process_crawled` calls `clean()` (C-1).** `clean.py:232` adopts parent-scoped hashing. Drop-count metadata + baseline metric.
**Avoids:** Pitfalls 1, 2, 18 (wiki IDF blast radius). **Deliberately ships with the weak patterns — this phase proves the plumbing and establishes the baseline while changing filter policy as little as possible. Two variables, two phases.**
**Do not miss:** the exact-dup **early return** (`clean.py:305-320`) returns before the write block and must also return a cleaned ParsedDoc.

### Phase 18: Decouple the SCHED-02 change gate
**Rationale:** Small, isolated, **hard prerequisite** for touching `BOILERPLATE_PATTERNS` (19) or crawl extraction (22). Doing it first turns a 34-source re-crawl storm into a non-event.
**Delivers:** frozen `_GATE_NORMALIZE_PATTERNS`; `_signature` stops importing the clean stage's mutable list; a test pinning gate-signature byte-stability across a clean-stage change.
**Note:** could merge into 17 — genuinely small — but independently verifiable and blocks two later phases.

### Phase 18.5 (or a Phase-17-adjacent slot): Quality-audit harness + must-not-reject fixtures
**Rationale:** **Measurement before filtering, or v2.6 repeats v2.5's exact failure with a new instrument.** All four researchers converged; the brief lists this as a non-selected candidate.
**Delivers:** per-source **old-vs-new** table (34 rows) from a raw-zone reprocess of a held-out subset into a **shadow collection** (INDEX-02/D-06 alias machinery already supports this); ~20 hand-labeled short-but-vital clinical fixtures in CI; two **separately named** metrics (`gold_rag_junk_rate`, `indexed_chunk_junk_rate`).
**Avoids:** Pitfall 16 — **the garbage rate will improve for at least four reasons unrelated to the filter working**: denominator dilution (ingesting 4,499 clean chunks halves the rate by arithmetic alone), source-mix selection (the audit's spread is 81% → near-0%), zone confusion, and **metric-definition drift — if the gate's heuristic becomes the audit's definition, the measurement is circular and always reports 100% success.** **Keep the audit's classifier independent of the gate's. Freeze the audit's definition before building the gate.** Add a **false-negative instrument** — nothing else measures what got *wrongly removed*, the dangerous direction in healthcare.

### Phase 19: Section classifier (annotate) + extended patterns
**Depends on:** 17, 18. **Rationale:** the highest-yield policy change, now measurable against 17's baseline. Should move 28% → single digits.
**Delivers:** deterministic section-level heuristics (link density 0.2, terminal-punct ratio, stopword ratio, token floor) computed as **annotations on `Section`**, not drops; extended patterns; domain-pack `filters.yaml` + normative-phrase allowlist via `DomainLoader`. **Tables exempt.** Extend, don't replace, the existing 4 (Phase-3 tests + the T-03-07 inline-citation line-anchoring guarantee).
**Avoids:** Pitfalls 11, 19, 20. **Deleting tables with prose-shaped heuristics is the most likely way to ship a catastrophic regression in this milestone.**

### Phase 20: Chunk min-substance gate (report-only → enforce) + gold export quality gate
**Depends on:** 17. Parallelizable with 19.
**Delivers:** `ChunkSettings.min_tokens` + composite predicate + `is_table` exemption + healthcare domain-code allowlist; `FineWebQualityFilter` wired with **new chunk-scoped settings** (never `CurateSettings`); rejection counters with `(bool, reason)` per DataTrove's `BaseFilter` contract; **`substance_gate_mode: report|enforce`, default `report`.**
**Then** the export gate — which **must** gate on a **chunk-level** field, not `enriched.quality_score`. That score is the **document's**, stamped identically onto every chunk: an FDA FAERS page (55% garbage) has *one* score shared by its clinical tables and its cookie banner. A threshold on it **drops whole good documents and keeps every nav chunk** — structurally incapable of moving the 33%, because the 33% is *within-document* variance and this score has none. (Also: `export.py:308` uses `enriched.quality_score` only — it doesn't apply `index.py:112-115`'s curated-then-enriched precedence. Worth closing.) **This makes L3 a hard dependency of L5.**
**Also required:** version the eval datasets. `generate_qa_example` produced Q&A pairs grounded in "Featured" — **a v2.6 that improves retrieval will score *worse* on the existing eval sets, and someone will read that as a regression and roll back a working fix.** Re-audit `contamination_override_artifact_ids` — a stale override is strictly worse than none; it suppresses a *new, real* finding.
**Conservation check:** `rejected + kept == sections_considered` — catches "the gate dropped everything" and "the parser produced nothing" as *distinct* failures. Without it, four different failures (correct drop / Docling regression / over-pruning / broken gate) look identical: fewer chunks, all tests green, garbage rate improved **in all four cases including the two where the pipeline is broken.**

### Phase 21: Index-time dedup — **MUST follow 20**
**Rationale (hard constraint):** Pitfall 5. Dedup before the substance gate makes BM25 *worse*. Also: most of the 653 are boilerplate that 19/20 remove at source — **build against the residual, not the pre-filter mass. If the residual is small, descope this phase entirely** — an explicit decision point, not a foregone conclusion.
**Delivers:** `chunk_text_index` ledger + Alembic migration; `dedup_chunks` asset between chunk and embed; **`point_id = uuid5(NAMESPACE, sha256(normalized_text))`** — dedup lookup O(1), re-index idempotent by construction, mirroring the validated `put_raw` content-addressed pattern. Payload keeps **scalar** fields from a **deterministic `primary`** (additive `contributors[]` alongside) so PAYLOAD-01/02 filters keep working. **Non-goal, recorded explicitly: near-dup.**
**Avoids:** Pitfalls 5, 13, 14. **Add `dedup_chunks` to `core_pipeline_e2e_job`'s selection in the same commit** — `assets.py:975-985` documents in blood that **Dagster silently drops a `deps=` edge whose target is outside the selection**; `curate_document_asset` was left out and resurrected the exact KL-06 race the edge existed to close.
**Design against:** a naive in-memory "dedup the list before embedding" **catches almost nothing** — `chunk()`/`embed()`/`index()` all run **per document**, and the 653 are cross-document. It will ship, pass its unit tests, and move the count ~2%.

### Phase 22: Crawler-level extraction — **RECONSIDER SCOPE (C-2)**
**Rationale:** widest blast radius, the only unrecoverable layer, benefit is a **subset** of 19's. **Before building: verify it is not a no-op.** If pursued: pruned → **bronze only**, raw stays full-fidelity HTML, dual markdown (raw + fit as siblings), `threshold_type="fixed"` **never `dynamic`**, `min_word_threshold` low or 0, per-format rules (HTML prunes; PDF never does), and the `route=tree → chunk` fallback counter must be live **before** it ships or the regression is undetectable.

### Phase Ordering Rationale — hard constraints, not preferences

1. **17 first** — the only phase whose defects *corrupt* data rather than degrade it.
2. **Measurement before filtering** — or v2.6 repeats v2.5's failure with a new instrument.
3. **18 before 19** — or extending patterns triggers a 34-source re-crawl storm.
4. **L3 before L4** — `Modifier.IDF` promotes surviving boilerplate to top BM25 hits.
5. **L3 before L5** — the export gate has no chunk-level signal to gate on until L3 makes one.
6. **L3 before the L2 pattern strengthening** — so the full re-enrichment runs against a 28%-smaller corpus.
7. **L1 last, with a rollout plan** — widest blast radius, unrecoverable, forces a full re-ingest.

**Critical path: 17 → 19.** Everything else is a leaf or parallelizable. **The `quality/` predicate module has no dependencies at all** — pure functions, pure unit tests, no registry, no S3, no Dagster — and should be built first in parallel with 17.

### Research Flags

Needs `--research-phase`:
- **Phase 21 (dedup)** — IDF magnitude at 4,499 points **unmeasured**; whether Qdrant computes IDF **per-shard or collection-wide is undocumented** (if per-shard, the effect is non-reproducible across environments). Worth a live spike.
- **Phase 22 (crawler)** — `PruningContentFilter` behavior on 0.9.x unverified; bug #582 is from 0.4.247. Test against a real FDA/ACC page before committing.
- **Phase 20 (thresholds)** — **no published chunk-level substance threshold exists anywhere.** Every number is an adaptation, tunable only against the metric.

Standard patterns (skip research):
- **Phase 17** — `load_parsed_doc`/`reparse_from_raw` fallback and the WR-05 hash convention are both established in-repo.
- **Phase 18** — v2.0's gate-local normalization is a recorded, proven pattern.
- **Phase 19** — heuristics read from installed source; the `DomainLoader` rail is proven by `enrich.j2`.

---

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | **HIGH** | Executed against pinned `crawl4ai==0.9.1` / `datatrove==0.9.0` — signature introspection, source reads, filters run against all five audit categories plus a prose control. Not recalled, not guessed. Docs downgraded to MEDIUM: the Crawl4AI prose contains a **verified error**. |
| Features | **HIGH** on thresholds / **MEDIUM** on norms | Thresholds read from installed `site-packages`, deliberately **not** from search results — and this mattered: several summaries reported Gopher's bullet ratio as 0.8 when the actual default is **0.9**. The web number was wrong. Architectural norms are 5+ converging implementations, no authoritative spec. |
| Architecture | **HIGH** | Every claim cited to file:line and read, not inferred. `clean()`'s call sites exhaustively grepped; the bronze dead-end verified by grepping all consumers. |
| Pitfalls | **HIGH** on mechanism / **LOW** on magnitude | Most findings are line-level consequences of code that exists today. The IDF mechanism is certain (Qdrant docs state formula and live-statistics semantics); magnitude at 4,499 points untested. |

**Overall confidence: HIGH on what is true, LOW on what to set.** The research is unusually strong on mechanism and unusually weak on numbers — because the numbers do not exist. **We are the only system in the surveyed ecosystem gating at chunk granularity**, since we are the only one whose primary output is a *retrievable unit* rather than a training document or a page extraction. That is exactly why the ecosystem gives us signals but not thresholds, and why the garbage-rate metric is not optional: **it is the tuning harness for numbers nobody else has published.**

### Gaps to Address

- **Exact-duplicate collision rate after aggressive cleaning is unknown** — Pitfall 2's severity scales directly with it. **Cheap to measure and should be done during requirements, before Phase 17 commits:** run the proposed cleaner over the existing 34 sources' parsed artifacts (read-only) and count `sha256(cleaned_text)` collisions across different parents.
- **IDF magnitude at 4,499 points** — mechanism certain, effect size unknown. Spike in Phase 21.
- **`PruningContentFilter` on 0.9.x** — bug #582 unverified against the pinned version.
- **Chunk-level threshold values** — genuine ecosystem gap. Ship as config, tune with the metric.
- **`short_line_thr=0.67` may false-reject markdown with many short lines** — bulleted clinical criteria, table rows. It rejected `"Aspirin reduces risk."` in testing. Tune against known-good chunks; annotate-first, gate-second (the CLEAN-02 language-detection precedent).
- **No baseline exists for tree-index health** — Pitfall 12's regression would be undetectable. Capture tree-node count + route-fallback rate before Phase 22.
- **Whether the healthcare pack's existing taxonomy/validator can be reused as a substance signal** was not investigated. If yes, the domain allowlist is nearly free.
- **Qdrant IDF per-shard vs collection-wide** — undocumented. Verify against the running server before relying on IDF stability.

## Sources

### Primary (HIGH confidence)
- **This repository's source, read at cited file:line** — `pipeline/{clean,chunk,index,export,crawl,enrich,curate,process,parse,wiki,datasets}.py`, `plugins/builtin/{qdrant_store,sparse_embedder,crawl4ai_adapter}.py`, `registry/repo.py`, `storage/s3.py`, `dagster_defs/assets.py`, `config/settings.py`
- **`crawl4ai==0.9.1` installed package** — signature introspection + source read + **executed** on synthetic clinical HTML
- **`datatrove==0.9.0` installed package** — filter defaults read from disk; **executed** against all 5 audit categories + prose control
- `.planning/{PROJECT,MILESTONE-CONTEXT,RETROSPECTIVE}.md`; in-code decision records (WR-05 `chunk.py:315-316`, KL-04/05/06, D-06/SCHED-02, FOUND-04, Task 8/KL-09)
- [Qdrant IDF modifier](https://qdrant.tech/documentation/concepts/indexing/#idf-modifier) — formula + live-statistics semantics stated explicitly
- [SANDIA SAND2024-10208](https://www.osti.gov/servlets/purl/2429881) — Trafilatura F1 0.937 / precision 0.978 / **recall 0.92**
- [PyPI JSON API](https://pypi.org/pypi/trafilatura/json) — versions, licenses, upload dates

### Secondary (MEDIUM confidence)
- [Crawl4AI docs](https://docs.crawl4ai.com/core/markdown-generation/) — **prose contains a verified error** re: `CrawlerRunConfig(content_filter=)`; no determinism guidance
- [crawl4ai#582](https://github.com/unclecode/crawl4ai/issues/582) — strips `<a>`/`<strong>` text; open, v0.4.247, **unverified on 0.9.x**
- Gopher/MassiveText (arxiv 2112.11446), C4 (JMLR 20-074), FineWeb (arxiv 2406.17557) — corroborated by datatrove source
- jusText `algorithm.rst`; RAGFlow `layout_recognizer.py` (`garbage_layouts`)
- [WCXB benchmark](https://webcontentextraction.org/) + Bevendorff et al. SIGIR 2023 — extractor rankings
- Web template detection (arxiv 1409.2590); Site Style Tree; Pomikálek thesis — cross-page repetition

### Tertiary (LOW confidence)
- ChunkRAG (arxiv 2410.19572) — abstract only; **cited solely to refute** its applicability as an ingest gate
- Unstructured.io / Databricks RAG cookbook — vendor docs

---
*Research completed: 2026-07-15*
*Ready for roadmap: yes — **pending an explicit user decision on C-2 (D-1 crawler extraction) and C-3 (D-2 forward-only)***
