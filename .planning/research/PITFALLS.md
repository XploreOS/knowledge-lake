# Pitfalls Research

**Domain:** Retrofitting aggressive content filtering into a shipped corpus pipeline with live downstream consumers
**Researched:** 2026-07-15
**Confidence:** HIGH (most findings are grounded in this repo's own code, not external opinion)

## How To Read This

Generic "filtering is hard" advice is omitted. Every pitfall below is either (a) a line-level
consequence of code that exists in `src/knowledge_lake/` today, or (b) an externally verified
failure mode of a tool this milestone is about to enable.

**The single most important finding:** this system was built to **degrade gracefully** —
`index.py` nulls payload fields when a join misses, `clean.py` returns a foreign artifact on
hash collision, `route.py` auto-falls-back when tree results are empty, `export.py` falls back to
metadata text when S3 reads fail. Every one of those is a *deliberate, documented* design choice.
Under a retrofit, graceful degradation stops being a safety property and becomes a **hazard**:
the failure modes below almost all manifest as *silence*, not exceptions. v2.5's headline lesson
("green gates measured mechanism, not output quality") applies with full force — a v2.6 that
breaks lineage will still be 971 tests green.

**Three corrections to the milestone brief, established by code grounding:**

1. **`enrich` is NOT fully bypassed.** `enrich_document(cleaned_artifact_id, ..., parsed_doc)`
   reads the **cleaned blob** for its main text (`enrich.py:319-335`) and caches on
   `_enrichment_cache_key(cleaned_content_hash, prompt_version)` (`enrich.py:107`). Only
   `parsed_doc.sections` and `parsed_doc.metadata` are uncleaned (`enrich.py:340-341`). L0's
   enrich scope is narrower than MILESTONE-CONTEXT states — but see Pitfall 9, because the
   cleaned-hash cache key makes stronger cleaning a **billing event**.
2. **The gold RAG export is NOT forward-only.** `export_rag_corpus` scans
   `list_artifacts_by_type(session, "chunk")` — the whole registry — on every run
   (`export.py:286`). A gate there cleans the existing corpus retroactively. See Pitfall 3.
3. **The lineage graph already claims something false.** `enrich.py:438` parents
   `enriched_document` to `cleaned_artifact_id`, and chunks/trees parent to
   `parsed_artifact_id`. So chunks are **siblings** of `cleaned_document`, not descendants.
   The graph asserts a cleaning relationship the RAG path does not honor. This is a live
   violation of the PROJECT "Lineage" constraint, not merely a quality defect — which is why
   L0 is a lineage phase, not a quality phase.

---

## Critical Pitfalls

### Pitfall 1: Fixing L0 by re-parenting chunks to `cleaned_document` silently nulls every payload field

**What goes wrong:**
The obvious L0 fix — "make chunks children of the cleaned artifact so lineage tells the truth" —
silently destroys the entire Qdrant payload for every newly indexed chunk. No exception, no log
line, no failing test. `source_name`, `source_url`, `format`, `tags`, `title`, `organization`,
`document_type`, `keywords`, and `quality_score` all become `None`/`[]`. Every PAYLOAD-02 search
filter then silently returns zero results for new chunks while continuing to work on old ones.

**Why it happens:**
`registry/repo.py:839-869`:

```python
def get_enriched_artifact_for_parsed(session, parsed_artifact_id) -> Artifact | None:
    cleaned = next((child for child in list_children(session, parsed_artifact_id)
                    if child.artifact_type == "cleaned_document"), None)
    if cleaned is None:
        return None
```

It walks **parsed → cleaned → enriched**. Pass it a `cleaned_document` ID and
`list_children(cleaned_id)` returns `enriched_document` children — none of type
`"cleaned_document"` — so it returns `None`. Then `index.py:101-107` does exactly what it was
designed to do:

```python
enriched = registry_repo.get_enriched_artifact_for_parsed(session, parsed_artifact_id)
if enriched is not None: ...
else: enrichment_metadata = {}; enriched_quality_score = None
```

`index.py`'s docstring is explicit: *"These four fields degrade gracefully to null/empty when
neither enrichment nor curation has run yet (D-01)."* The graceful-degradation contract cannot
distinguish "enrichment hasn't run yet" from "you passed the wrong artifact type."

Affected call sites all pass `chunk.parent_artifact_id` expecting a parsed ID:
`index.py:191` (`_resolve_document_payload_fields`), `index.py:271-284`
(`_build_payload_refresh_fn` via `payload["document"]`), `export.py:301-303`
(`parsed_id = chunk.parent_artifact_id  # chunk -> parsed`), and
`export.py:106+` `check_train_eval_contamination` — whose own inline comments spell out the
assumption: *"chunk's parent_artifact_id IS the parsed_document."*

**How to avoid:**
**Do not re-parent chunks.** Keep `parent_artifact_id = parsed_artifact_id` and fix L0 by
changing what `chunk()`/`tree_index()` **read**, not what they are **parented to**. The clean
stage's product is *text*, and the fix is to hand the downstream stages cleaned text —
lineage-wise, a chunk derived from cleaned text of a parsed document is legitimately still a
child of the parsed document, with a `cleaned_artifact_id` recorded in `metadata_` as the
provenance of the transformation.

If re-parenting is chosen anyway, it is a **schema migration**, not a wiring change: add a
`get_enriched_artifact_for_cleaned()` and update all four call sites in the same commit, and
add an assertion that rejects a wrong-typed artifact instead of returning `None`.

**Warning signs:**
- Newly indexed chunks have `source_name: null` in Qdrant while older ones don't.
- `klake search --source-name X` returns fewer results than `klake search` with no filter, and
  the gap grows with each new ingest.
- `quality_score` is `null` on new points — which then makes the Pitfall 4 export gate drop
  every new chunk.

**Phase to address:** Phase 17 (the L0 wiring phase — first, per MILESTONE-CONTEXT).
**Verification:** Assert `payload["source_name"] is not None` on a freshly indexed chunk in an
integration test. Add a `get_artifact(...).artifact_type == "parsed_document"` guard inside
`get_enriched_artifact_for_parsed` that **raises** instead of returning `None`.

---

### Pitfall 2: `cleaned_document` has no WR-05 protection — and aggressive cleaning makes collisions likely

**What goes wrong:**
This is the mirror image of the WR-05 decision, and it has been dormant only because nothing on
the RAG path reads the cleaned artifact. **L0 activates it.**

`chunk.py:317` deliberately scopes its hash to the parent:

```python
hash_input = f"{parsed_artifact_id}:{text}"   # WR-05
```

`clean.py:232` deliberately does not:

```python
content_hash = hashlib.sha256(cleaned_bytes).hexdigest()   # cleaned text alone
```

And `get_artifact_by_hash` is backed by a **`UNIQUE(content_hash, artifact_type)` index**
(`repo.py:363`). So there can be **at most one `cleaned_document` per unique cleaned text,
corpus-wide**. When two different source documents clean down to identical text, `clean.py:305-320`
returns the *other document's* artifact:

```python
existing = registry_repo.get_artifact_by_hash(session, content_hash, "cleaned_document")
if existing is not None:
    return {"artifact_id": existing.id, ...}   # belongs to a DIFFERENT source
```

Document B then has **no `cleaned_document` child of its own**. Consequences once L0 lands:
- B's chunks/trees get parented to or derived from A's cleaned artifact → cross-document lineage
  corruption, i.e. **exactly the failure WR-05 exists to prevent**, arriving through the door
  nobody was watching.
- `get_enriched_artifact_for_parsed(B_parsed)` finds no `cleaned_document` child → returns
  `None` → B's entire payload nulls out (Pitfall 1's symptom, different cause).
- The contamination gate's `chunk → parsed → cleaned` walk resolves B's eval chunks onto A's
  cleaned doc → **false contamination reports**, and `_enforce_no_contamination` **fails closed**
  in all three export functions. The milestone gets blocked at the export step by a lineage bug
  introduced at the clean step.

**Why it happens:**
The collision rate is a *function of cleaning aggressiveness*, and this milestone's entire
purpose is to raise it. Consider two thin ACC guideline landing pages (81% garbage per the audit)
whose only real content is nav + a title. Strip the nav aggressively and both collapse to the same
handful of bytes. **The more successful the filter, the more collisions it creates.** The 34-source
corpus already contains 653 exact-duplicate chunks — abundant evidence that near-empty pages are
converging on identical text before cleaning is even strong.

**How to avoid:**
Adopt the WR-05 convention in `clean.py`:
`content_hash = sha256(f"{parsed_artifact_id}:{cleaned_text}")`.

Then handle the consequence: new-scheme hashes never collide with old-scheme hashes, so
re-running `clean()` on an already-cleaned document creates a **second** `cleaned_document`
child of the same parsed document. `get_enriched_artifact_for_parsed` uses
`next((child for child in ... if child.artifact_type == "cleaned_document"), None)` — it picks an
**arbitrary** one. Payload resolution becomes nondeterministic. Fix in the same phase: make the
child lookup deterministic (order by `created_at DESC`, take newest) or add a
`superseded` marker.

Keep the S3 key content-addressed on the *text* hash (`clean.py:303`) so identical cleaned bytes
still write once — dedupe **storage**, not **identity**. Storage-level dedup was never the problem;
identity-level dedup is.

**Warning signs:**
- A `cleaned_document` whose `parent_artifact_id` belongs to a different `source_id` than its
  own `source_id`.
- Count of `parsed_document` artifacts > count of `cleaned_document` artifacts.
- `clean.exact_dup` log lines firing across different sources (today they'd be near-invisible).
- Contamination gate newly failing closed on export with no eval-set change.

**Phase to address:** Phase 17 — **same phase as L0, non-negotiably**. Wiring cleaned text onto the
load-bearing path without fixing this hash scheme converts a dormant bug into active lineage
corruption on the first run.
**Verification:** Test: two different `parsed_document`s that clean to byte-identical text must
produce two distinct `cleaned_document` artifacts, each with the correct `parent_artifact_id`.

---

### Pitfall 3: "Forward-only" is false for the gold zone — and the two garbage numbers will be conflated

**What goes wrong:**
D-2 says the existing corpus stays as-is. That is true for raw, bronze, silver, chunk artifacts,
and Qdrant. It is **not true for gold.** `export_rag_corpus` re-derives the entire corpus from the
registry on every invocation (`export.py:286`) and writes a fresh Parquet snapshot under a new
`export_id` (`export.py:366`). Add a quality gate there and the **next export drops the 119 junk
rows out of the existing 357 immediately** — with zero new ingests.

This produces two garbage-rate metrics that move for completely different reasons:

| Metric | Behavior after the gate lands | Why |
|---|---|---|
| Gold RAG corpus junk % | Drops from 33% → ~0% **on the next export run** | Full re-derivation + gate |
| Qdrant chunk garbage % | Unchanged at ~28%, decays only as new clean docs dilute it | Forward-only, no backfill |

Someone will run `export-rag-corpus`, see 0% junk, and declare v2.6 shipped — while search still
returns "Featured" as a hit. **The number that improves fastest is the one that measures the
least.**

**Why it happens:**
The gold zone *looks* like a persisted artifact tier, so "forward-only" gets applied to it by
analogy with raw. It is actually a materialized view.

**How to avoid:**
- State explicitly in the requirements that **D-2 forward-only applies to raw/bronze/silver/
  chunks/Qdrant, and that gold is a re-derived snapshot to which the gate applies retroactively.**
  This is a *benefit* — take it — but name it so it isn't mistaken for evidence the filter works.
- Track and report the two rates **separately and side by side**. Never report one number.
- The gate-at-export is the cheapest win in the milestone and needs no backfill. Sequence it
  early for the value, but do not let it become the success metric.

**Warning signs:**
- A milestone report citing "gold corpus junk: 0%" as the headline.
- Any single "garbage rate" figure with no zone qualifier.

**Phase to address:** Gold export gate phase (L5). Requirements phase must record the
D-2 scoping correction.
**Verification:** Two distinct tracked metrics with distinct names, e.g.
`gold_rag_junk_rate` and `indexed_chunk_junk_rate`.

---

### Pitfall 4: The only quality score reaching the export gate is document-level — it cannot see chunk-level garbage

**What goes wrong:**
The natural implementation of "quality gate on gold export" is
`if row["quality_score"] >= threshold`. It cannot work. `export.py:302-308`:

```python
enriched = registry_repo.get_enriched_artifact_for_parsed(session, parsed_id)
quality_score = enriched.quality_score if enriched else None
```

That is the **document's** enrichment score, stamped identically onto every chunk of that
document. An FDA FAERS page (55% garbage per the audit) has *one* score — shared by its clinical
tables and its cookie banner alike. A threshold gate on it does exactly the wrong thing:
- **Drops whole good documents** whose score dipped (taking their good chunks with them).
- **Keeps every nav chunk** of documents whose score is high.

It is structurally incapable of moving the 33% figure, because the 33% is *within-document*
variance and this score has none.

Two aggravating details:
- `export.py:308` uses `enriched.quality_score` **only** — it does not apply the
  curated-then-enriched precedence that `index.py:112-115` established for KL-04/05/06. So the
  export gate wouldn't even see the DataTrove composite. An inconsistency worth closing.
- `curate.py`'s composite (`parse*0.30 + enrich*0.40 + filters*0.30`) is **also** document-level,
  and defaults `enrich_quality_score` to `0.5` when no enriched sibling exists (`curate.py:234`).
  A gate at 0.5 becomes a coin flip on un-enriched documents.

**Why it happens:**
`quality_score` already exists as a column and is already in the export row's allow-list. It reads
as the obvious gate input. It is the wrong *granularity*, which is invisible from the field name.

**How to avoid:**
The gate needs a **chunk-level substance signal**, computed deterministically at chunk time and
persisted on `chunk.metadata_` (alongside the existing `is_table`, `oversized`,
`heading_prefix` keys — the slot already exists). Export gates on that, and may **additionally**
gate on the document score. Do not conflate them; carry both fields in the row.

Note this makes the chunk-time substance gate a **hard dependency** of the export gate. Sequence
accordingly: L3 before L5.

**Warning signs:**
- A gate implementation touching only `export.py`.
- A gate that drops whole documents but leaves the row count for "Featured"-style chunks unchanged.
- Sub-30-char rows in the gated Parquet output.

**Phase to address:** L3 (chunk substance gate) must land before L5 (export gate).
**Verification:** Assert the gated Parquet contains zero rows that the audit script classifies as
garbage — running the *audit's own* classifier against the export output, not a reimplementation.

---

### Pitfall 5: Index-time dedup makes boilerplate **more** retrievable, not less (Qdrant `Modifier.IDF`)

**What goes wrong:**
This inverts the intuition behind D-3, and it is the least obvious finding here.

`qdrant_store.py:156` creates the sparse vector with `SparseVectorParams(modifier=Modifier.IDF)`.
Qdrant's docs state IDF is computed from **live collection statistics** and *"depends on the
currently stored documents and therefore can't be pre-computed"*, with:

```
IDF(q_i) = ln((N - n(q_i) + 0.5) / (n(q_i) + 0.5) + 1)
```

where `n(q_i)` = number of points containing the term. Today, a footer term appears in ~653 of
4,499 points → `n` is large → IDF is low → BM25 correctly treats it as noise. **The 653
duplicates are currently suppressing themselves.**

Collapse them to one point and `n` drops from ~653 → 1. IDF spikes. The single surviving footer
chunk becomes a **highly discriminative, top-ranked BM25 hit** for every one of its terms. You
will have removed 652 mediocre hits and manufactured one excellent one. In the hybrid RRF branch
that surviving point may now outrank real clinical content.

**Why it happens:**
Dedup is framed as an embedding-cost and result-pollution fix (D-3, correctly). The BM25 coupling
is invisible because IDF is computed **server-side inside Qdrant** — there is no IDF code in this
repo to grep. Nothing in `index.py` or `sparse_embedder.py` hints at it;
`sparse_embedder.py:19` even says *"this module only emits raw term-frequency vectors."*

**How to avoid:**
- **Dedup and the substance gate must ship together, and the gate must run first.** A footer chunk
  that the L3 substance gate refuses to emit never reaches Qdrant, so its IDF never spikes. Dedup
  alone is actively harmful; dedup *after* filtering is safe. This is a hard ordering constraint
  on the roadmap.
- Explicitly regression-test the sparse branch: run `klake search --mode sparse` for a term that
  appears only in the deduped boilerplate (e.g. a cookie-banner phrase) before and after dedup.
  Expect the rank to *rise* — that's the pitfall firing.
- Uncertain and worth a live check (docs don't specify): whether Qdrant computes IDF per-shard or
  collection-wide. If per-shard, the effect varies with shard placement and is non-reproducible
  across environments.

**Warning signs:**
- `--mode sparse` and `--mode hybrid` results diverge sharply after dedup ships while `--mode
  dense` is stable — the IDF branch is the only thing that changed.
- A cookie-banner or nav phrase ranks #1 for its own terms.

**Phase to address:** Index-time dedup phase (L4). Roadmap ordering: **L3 → L4**, never L4 alone.
**Verification:** Before/after sparse-mode rank of a known boilerplate term, asserted in an
integration test against a live Qdrant.

---

### Pitfall 6: Forward-only makes IDF drift a permanent, monotonic condition — not a transient

**What goes wrong:**
D-2 makes the mixed corpus the **expected steady state**. Combined with Pitfall 5's mechanism:
as clean documents are added, `N` grows while `n(nav_term)` **stops growing** (new docs no longer
contain nav text). By the IDF formula, `IDF(nav_term)` climbs **monotonically forever**. The old
garbage chunks therefore become *progressively more retrievable over time*, and — because
forward-only means they are never removed — this never self-corrects. The corpus gets cleaner and
the garbage gets more prominent, simultaneously.

The magnitude is modest at 4,499 points and grows with corpus size. But it means "the garbage will
get diluted as we add clean sources" — the implicit assumption behind accepting D-2 — is **the
opposite of true for the sparse branch**. Dilution works for dense; it inverts for BM25.

**Why it happens:**
"Forward-only + dilution" is an intuition from *dense* retrieval, where adding good vectors
genuinely crowds out bad ones by cosine similarity. BM25 IDF is a *corpus-relative* statistic;
adding good documents actively increases the score of terms unique to the bad ones.

**How to avoid:**
Three honest options, in ascending cost:
1. **Payload-filter the old chunks out of search** rather than deleting them: stamp a
   `substance_gate: "pre_v2_6"` marker and let search exclude it. Cheap, reversible, honors
   forward-only for *storage* while fixing *retrieval*. **Recommended** — the existing
   `refresh_all_points_payload` reindex path (KL-06, `index.py:359-365`) already exists to stamp
   payload fields onto existing points without re-embedding. This is a solved problem in this
   codebase.
2. Accept the drift, document it, and monitor sparse-mode ranks.
3. Reprocess the 34 sources from the intact raw zone into a new collection and alias-swap. This is
   what the alias-backed reindex + count-parity gate (INDEX-02, D-06) was built for, and the raw
   zone is deliberately immutable to make it possible. It is *not* a WORM violation — nothing is
   rewritten. Consider it a candidate requirement rather than out of scope.

Option 1 is the point worth making loudest: **"forward-only" was chosen to protect WORM
immutability, but retrieval-time exclusion via a payload flag achieves the quality goal without
touching a single stored byte.** The v2.0 STORE-01 precedent that D-2 invokes was about not
*rewriting raw keys* — it says nothing about filtering at query time.

**Warning signs:**
- Sparse-mode quality degrading over successive milestones while dense-mode improves.
- A rising share of top-10 hits coming from pre-v2.6 chunks.

**Phase to address:** Requirements phase must confront this — it may change the D-2 decision from
"do nothing about old chunks" to "flag old chunks in payload, exclude at search."
**Verification:** Run a fixed query set against the collection at N and 2N points; assert
boilerplate ranks do not rise.

---

### Pitfall 7: Enabling `fit_markdown` invalidates every `last_content_hash` at once — and thrashes bronze, not raw

**What goes wrong:**
This is MILESTONE-CONTEXT Open Question 3, and the answer is more specific — and more actionable —
than "aggressive pruning could thrash the WORM raw zone."

`crawl.py:106-118`:

```python
def _signature(markdown: str) -> str:
    normalized = remove_boilerplate(markdown or "")
    return hashlib.sha256(_suppress_volatile(normalized).encode("utf-8")).hexdigest()
```

and `crawl.py:190`: `sig = _signature(probe.markdown or "")`.

Turn on `fit_markdown` and `probe.markdown` changes for **all 34 sources simultaneously**. Every
gate evaluates `sig != last_content_hash` → **every source re-crawls on the next sensor tick.**
A stampede against FDA, CMS, ACC, and NLM — real rate-limited government hosts. CRAWL-03's adaptive
backoff will absorb it, but 429/403 storms are exactly what it exists to survive, not to invite.

**The raw zone is safe.** `put_raw` is content-addressed with a registry no-op before any S3 write
(`storage/s3.py:236-249`): unchanged HTML → same SHA256 → existing artifact returned, no write.
WORM is structurally protected. **The raw zone is not the risk.**

**The bronze zone is the risk.** Bronze stores the *markdown* (`crawl.py:890-892`), content-
addressed on markdown bytes — which **have** changed. So every source produces:
new bronze → new parsed → new cleaned → new chunks → **new embeddings**. The mixed corpus arrives
as an immediate near-doubling of the entire 34-source corpus, not as a gradual trickle. Every
document exists twice: once pre-filter, once post-filter, both indexed, both searchable, both
citable. That is a far worse mixed-corpus condition than D-2 contemplated.

If the change gate then also churns run-to-run (Pitfall 8), this repeats **every tick**.

**How to avoid:**
1. **Decouple the change gate from the content filter.** The gate exists to answer "did the source
   page change?" — it must be computed from a **stable projection** of the page, never from the
   filtered output. Keep `_signature()` on `raw_markdown`; let `fit_markdown` feed the bronze/parse
   path only. The adapter must return both (`crawl4ai_adapter.py:160` currently returns
   `str(result.markdown)`; `result.markdown` in Crawl4AI carries both `raw_markdown` and
   `fit_markdown` — surface them as separate fields).
2. **Sequence the L1 rollout deliberately.** Enabling crawler-level pruning is a
   re-ingest-everything event. Do it as an explicit, rate-limited, one-shot backfill with the
   sensor **paused**, not by flipping a setting and letting the sensor discover it.
3. Consider a signature version marker so a gate-algorithm change is a *known* mass invalidation
   rather than a surprise.

**Warning signs:**
- All 34 sources report `reason="changed"` on one tick.
- 429/403 rate climbing across unrelated hosts simultaneously.
- Bronze artifact count doubling; chunk count roughly doubling with no new sources.

**Phase to address:** L1 (crawler extraction) — must include the gate-decoupling change. Requires
an explicit rollout plan, not just a config default.
**Verification:** Test that `_signature()` output is unchanged when `fit_markdown` is
enabled/disabled for the same fixture HTML.

---

### Pitfall 8: `remove_boilerplate` is shared by the clean stage **and** the change gate — widening the patterns invalidates every hash

**What goes wrong:**
The same trap as Pitfall 7, reached from the other direction — and it fires even if L1 is deferred.

`crawl.py:115` calls `remove_boilerplate(markdown)` — the *same function* `clean.py:81` uses.
MILESTONE-CONTEXT's plan to strengthen `BOILERPLATE_PATTERNS` (Open Question 5) therefore changes
`_signature()` for every source → mass re-crawl → the Pitfall 7 cascade. **The boilerplate-pattern
work and the crawler work are coupled through this one function call, and nothing in the codebase
signals it.**

Worse, the coupling is *known-hazardous and already documented*. `crawl.py:67-75` carries an
explicit warning:

> *"This is deliberately GATE-ONLY — it must never alter remove_boilerplate, which the clean stage
> shares and which must preserve human-meaningful dates."*

and v2.0's retrospective records **"gate-local normalization"** as an established pattern:
*"suppress volatile tokens inside the change gate rather than mutating shared clean.py — keeps the
WORM signature stable without redesigning the silver stage."* The pattern was established. The
**shared `BOILERPLATE_PATTERNS` list was left inside the blast radius anyway.**

This is v2.5 Lesson 2 verbatim: *"A recorded lesson is not an enforced one."*

**Why it happens:**
`remove_boilerplate` reads as a pure text utility. Its second caller is in a different module, in a
different subsystem, with a completely different correctness requirement (stability, not quality).

**How to avoid:**
- **Sever the shared call.** The gate needs a *stable* normalizer; the clean stage needs an
  *aggressive* one. These requirements are in direct opposition and will diverge further with every
  milestone. Give the gate its own frozen `_gate_normalize()` and stop calling
  `remove_boilerplate` from `crawl.py`.
- If sharing is kept, **version it**: `remove_boilerplate(text, version=1)`, gate pins `version=1`,
  clean uses `version=2`. Then a pattern change is an explicit, reviewable gate decision.
- **Answering Open Question 5 directly:** *extend*, don't replace — but the extension must be a
  new, versioned pattern set consumed only by `clean()`. Phase-3 tests depend on the existing four
  patterns; keep them passing by keeping `version=1` intact.

Note one existing pattern is already a healthcare false positive today:
`re.compile(r"(?i)^(?:disclaimer|copyright \d{4})[^\n]*$")` strips any line beginning
"Disclaimer" — including FDA/HHS/CMS disclaimer lines that carry genuine regulatory scope
statements. See Pitfall 11.

**Warning signs:**
- A PR touching `BOILERPLATE_PATTERNS` with no test change under `tests/**/crawl*`.
- Mass `reason="changed"` re-crawls after a cleaning-only change.

**Phase to address:** L2 (boilerplate classification) — but the severing must land in Phase 17
alongside L0, before any pattern is touched.
**Verification:** A test asserting `_signature(html_fixture)` is byte-stable across a
`BOILERPLATE_PATTERNS` change (i.e. the gate is provably decoupled).

---

### Pitfall 9: Stronger cleaning invalidates every content-hash cache — this is a **budget** event that fails closed

**What goes wrong:**
Three separate caches key on the **cleaned document's content hash**:

| Cache | Key | Cost on invalidation |
|---|---|---|
| Enrichment | `_enrichment_cache_key(cleaned_content_hash, prompt_version)` (`enrich.py:107`) | 1 LLM call × 34 sources × N docs, `strong_model` |
| Curation | `_curation_cache_key(cleaned_content_hash, filter_config_version)` (`curate.py:80`) | CPU only (DataTrove) |
| Tree index | TREE-02 content-hash skip | LLM only in opt-in summary mode |
| Dataset gen | `_dataset_gen_cache_key(source_content_hash, prompt_version)` (`datasets.py:139`) | 1 `eval_model` call per chunk |

Change `BOILERPLATE_PATTERNS` → every `cleaned_document` content hash changes → **every one of
those caches misses** → full re-enrichment of the corpus at real Bedrock cost. The `LlmSpend`
budget cap then does exactly what it was designed to do: **halt gracefully, fail closed,
mid-corpus**. Half the corpus re-enriched, half stale, the run stopped. This is the
"budget cap with graceful halt" pattern from v1.0 working correctly — and it will look like a
mysterious pipeline failure to anyone who didn't plan for it.

The dataset-gen cache is the sharpest edge: it's keyed per **chunk**, so a chunk-text change from
cleaning re-bills the eval-set generation per chunk.

**Why it happens:**
Content-hash caching is a *v1.0 established pattern* explicitly recorded in the retrospective as a
success ("prevents re-billing identical documents across runs"). Its correctness depends on the
input text being stable. This milestone's entire purpose is to change that text. **The pattern that
saved money is the pattern that now bills you.**

**How to avoid:**
- Treat the cleaning-pattern change as a **planned re-enrichment**, budgeted in advance. Estimate
  cost during requirements: `docs × strong_model` for enrich + `chunks × eval_model` for datasets.
- Raise `LlmSpend` budget deliberately for the rollout window, or accept a partial halt and make it
  **resumable** (it already is — the cache means a re-run picks up where it stopped).
- **Sequence the substance gate BEFORE the re-enrichment.** If the gate drops 28% of chunks first,
  you re-enrich a corpus that is 28% smaller. Doing it in the other order pays LLM cost to enrich
  garbage — the exact waste L0 was supposed to eliminate — and pays it *at maximum scale*.
- Note the silver lining: `enrich` already reads cleaned text (`enrich.py:319-335`), so it is
  already correct-by-construction here. There is no L0 work to do for enrich's main text; the work
  is `parsed_doc.sections` (`enrich.py:340-341`).

**Warning signs:**
- `LlmSpend` climbing sharply during what was scoped as a "deterministic filtering" milestone.
- A budget-cap halt mid-run right after a cleaning change.
- Enrichment cache hit rate dropping to ~0.

**Phase to address:** Requirements phase (cost estimate) + L2/L3 sequencing. The roadmap must state
the order: **substance gate → cleaning strengthening → re-enrichment.**
**Verification:** Estimate and record expected LLM spend for the rollout in the phase plan; compare
to actual.

---

### Pitfall 10: The 30-char floor punishes exactly the content healthcare is made of

**What goes wrong:**
The audit's "762 chunks under 30 chars = garbage" finding is *evidence*, not a *specification*.
Adopting 30 chars as the gate would discard real clinical content. Sub-30-char content that is
legitimately load-bearing in this corpus:

| Example | Chars | Why it matters |
|---|---|---|
| `ICD-10 E11.9` | 12 | The answer to "what's the code for T2DM without complications" |
| `Metformin 500 mg PO BID` | 23 | A dosage — the entire clinical payload |
| `LOINC 2160-0` | 12 | Creatinine, serum |
| `Contraindicated in pregnancy` | 28 | Normative, absolute |
| `See §164.312(a)(1)` | 18 | HIPAA Security Rule cross-reference |
| `Cardinality: 0..1` | 17 | FHIR/US Core IG — the *content* of an IG spec |
| `Do not exceed 4 g/day` | 21 | A safety limit |

Note the audit's worst sources — **US Core IG (72% garbage), eCQI (69%)** — are precisely the
specification-style documents whose real content is *terse structured statements*. A char floor
would score an IG's normative cardinality table as garbage and its verbose introduction as good.
The garbage-rate metric would improve while the corpus got worse. That is the v2.5 lesson recurring
in a new instrument.

Additional structural mismatches:
- **Wrong unit.** `ChunkSettings` is token-based (`cl100k_base`, `chunk.py:53`,
  `max_tokens: 512`). A char floor beside a token ceiling means two incompatible units gating the
  same object. `token_count()` already exists and is O(1) cached.
- **Tables are atomic by design.** CHUNK-03 emits `is_table=True` sections as single chunks
  regardless of size (`chunk.py:230-240`). A dense 2×2 table can be short and complete. `is_table`
  is already on `chunk.metadata_` — the exemption flag exists.
- **Prose heuristics misfire on structure.** Terminal punctuation (DataTrove's C4 filter) and
  stopword ratio (Gopher) are prose-shaped. `Cardinality: 0..1` has no terminal punctuation, no
  stopwords, and a high symbol ratio — it fails all three while being 100% signal.
- **Language detection is scoped to 5 European languages** (`clean.py:115-121`) and returns
  `"unknown"` otherwise. Anything else — including a mostly-code or mostly-numeric section — is
  `"unknown"`. Never gate on `language != "en"`; it would drop structured content and any
  non-covered language wholesale.

**Why it happens:**
The audit measured a *correlation* (short ⇒ usually junk) in this corpus. Correlation is a fine
detector and a terrible gate. Of 762 short chunks, most are "Featured" — but the ones that aren't
are the highest-value chunks in the corpus.

**How to avoid:**
Answering **Open Question 4** directly: **no, 30 chars is not the right floor, and a length floor
alone is not the right instrument.** Use a small deterministic composite, all of it free:

```
reject if NOT is_table
       AND token_count(text) < min_tokens        # ~8 tokens, not 30 chars
       AND alpha_ratio in a plausible band       # excludes pure nav labels
       AND no domain-signal hit                  # allowlist below
       AND link_density high OR stopword_ratio ~0
```

with hard exemptions (per Trafilatura's model — *per-element-type rules, not one global score*):
- `is_table=True` → **always exempt**. Already flagged.
- **Domain-code allowlist**: a chunk matching `ICD-10 \w\d+`, `LOINC \d+-\d`, `RxNorm \d+`,
  `§\d+\.\d+`, `\d+\s*(mg|mcg|g|mL|units)`, `\d+\.\.\d+` (FHIR cardinality) is exempt regardless of
  length. This is cheap, deterministic, and belongs in the **healthcare domain pack** — the
  `domains/{name}/` convention exists precisely so a domain can contribute its own signal without
  core changes. **The core gate must be domain-agnostic; the allowlist must be the domain pack's.**
- A heading with no body is *not* automatically garbage — a heading that IS the answer
  ("Contraindications") loses its meaning only because the body was stripped elsewhere. Prefer
  merging an orphan heading into its next sibling section over dropping it.
- **Ship report-only first.** Run the gate in dry-run, dump every rejection with its reason to a
  reviewable list, and have a human read the healthcare rejections before it gates anything. Given
  that even Trafilatura — best-in-class, F1 0.937 — has **recall 0.92** (SANDIA SAND2024-10208),
  ~8% of real content loss is the *floor* for mature extractors. Budget for it; measure it; don't
  assume zero.

**Warning signs:**
- Any bare `len(text) < N` in the gate.
- A rejection list containing dosages, codes, or cardinalities.
- Garbage rate improving while US Core IG / eCQI chunk counts collapse.

**Phase to address:** L3 (chunk substance gate). The domain allowlist is a healthcare-pack
contribution, same phase.
**Verification:** A fixture set of ~20 hand-labeled short-but-vital clinical strings that the gate
must **not** reject, in CI. This is the "write lessons into CI, not documents" pattern from v2.5.

---

### Pitfall 11: Repetition is simultaneously the best boilerplate signal and the best normative-content signal

**What goes wrong:**
"Text repeated across many pages is boilerplate" is the strongest available heuristic, and in a
regulated corpus it is also a **description of the most important content**:

- FDA boxed warnings — identical on every label page of a drug class. **Normative.**
- *"This guidance represents the current thinking of the FDA... It does not establish legally
  enforceable responsibilities."* — on every FDA guidance page. **Legally load-bearing**; it defines
  the document's authority, which is exactly what a RAG answer needs to qualify a citation.
- HL7 IG license/copyright headers — on every page of a spec. Arguably boilerplate.
- CMS "This is not a legal document" notices. **Scope-defining.**
- Standard safety warnings repeated per-section by design, because the authors intended them to be
  unmissable.

The existing pattern `^(?:disclaimer|copyright \d{4})[^\n]*$` (`clean.py:59`) **already strips FDA
and HHS disclaimer lines today.** Strengthening the patterns without care extends this to the
boxed warnings.

Deleting a black-box warning from a healthcare RAG corpus is a *safety* defect, not a quality one.
It is also invisible: nothing fails, the garbage rate improves, and the corpus quietly loses its
contraindications.

**Why it happens:**
Repetition-based boilerplate detection is imported wholesale from *web-scale pretraining* corpora
(DataTrove, FineWeb), where nav chrome dominates and normative repeated text does not exist. The
heuristic's training domain and this corpus's domain disagree about what repetition means.
This is also why the DataTrove-filtered pretrain path "looks healthy" — it optimizes a different
objective (token quality at scale) than RAG (answer-bearing precision), and its filters are tuned
for the former.

**How to avoid:**
Repetition alone must **never** be sufficient to drop content. Require a conjunction with signals
that normative text does not have:
- **Positional invariance**: nav/footer appear at the same DOM position on every page; a boxed
  warning appears inside the content flow. `section.section_path` and `section.page` are already on
  every Section — a block whose `section_path` is constant across every document of a source is
  chrome; one that moves is content.
- **Link density**: nav is ~100% links; a warning has ~0.
- **Domain-term presence**: run the domain pack's allowlist (Pitfall 10). A repeated block
  containing a drug name, a dosage, or a `§` citation is exempt regardless of repetition. The
  healthcare pack already ships a taxonomy and a validator — reuse them as a substance signal, not
  just an enrichment validator.
- **Length**: a cookie banner is short; a boxed warning is a paragraph.
- Keep an explicit **normative-phrase allowlist** in the healthcare pack (`"boxed warning"`,
  `"contraindicat"`, `"do not use"`, `"black box"`, `"warning:"`, `"this guidance"`) that
  hard-exempts.

**Report-only mode is mandatory here**, not optional. A human who knows healthcare (per PROJECT
context, the user does) must read the rejection list from a real 34-source run before this gates
anything.

**Warning signs:**
- Rejection list contains the word "warning", "contraindicated", or "boxed".
- A drug-label document's chunk count drops by more than the nav-chrome share.
- Search for a known contraindication returns nothing after the filter lands.

**Phase to address:** L2 (section boilerplate classification), with the normative allowlist in the
healthcare domain pack.
**Verification:** A fixture FDA label page whose boxed warning survives the full clean → chunk →
index path, asserted in CI.

---

### Pitfall 12: Crawl-time pruning is unrecoverable, and it will eat the tree index

**What goes wrong:**
L1 is the only filtering layer where mistakes cannot be undone in practice. Raw HTML is retained
(good), but nothing re-derives bronze from raw — over-pruned markdown is what the whole pipeline
sees, forever, unless someone deliberately reprocesses.

Two concrete, verified over-pruning modes:

1. **Crawl4AI issue #582 (open since 2025-01-29, v0.4.247, unfixed):** `PruningContentFilter`
   strips `<a>` and `<strong>` tags **including their text**. In this corpus that means: bolded
   drug names, bolded warnings, and the anchor text of links to the actual guidance documents —
   deleted. Note INGEST-10 follows PDF/doc links from crawled pages; the extraction the crawler
   prunes and the links the pipeline follows come from different fields (`result.html` vs
   `result.markdown`, `crawl.py:662-665`), so link-following survives — but the human-readable
   context around those links does not.
2. **Link-density scoring kills index/TOC pages.** A guideline index, a spec's table of contents,
   an eCQI measure list — these are ~100% links by construction. To `PruningContentFilter` they are
   indistinguishable from nav. **But they are real content for the tree index** (TREE-01 builds the
   hierarchy from `ParsedDoc.sections`), and ROUTE-02's `structural_breadth` classifier routes
   exactly those queries to the tree path.

And the failure is **silent by design**: ROUTE-03's D-05 auto-fallback means an empty tree result
transparently falls back to the chunk path (a v2.5 decision, correct in isolation). So the tree
index can quietly stop working and every query still returns *something*. Nobody notices tree
retrieval died.

**Why it happens:**
`PruningContentFilter` optimizes for "extract the article body" — a news/blog framing. A spec's
TOC, an IG's cardinality table, and a measure index are all article-body-negative and
corpus-value-positive.

**How to avoid:**
- **Never let a crawl-time filter be the only copy.** Store *both*: bronze keeps `raw_markdown`;
  `fit_markdown` goes to a **sibling** bronze artifact. Then L1 is reversible and the tree index can
  read the unpruned version. This is the "sidecar for derived structure" pattern already established
  in v2.5 (`parse()` writes a sections sidecar).
- Pin `threshold_type="fixed"`. `"dynamic"` computes a page-relative threshold, so an unrelated
  block changing shifts the boundary for *every* block — maximal instability across the exact
  heterogeneous 34-source set this corpus has. (Crawl4AI's docs offer **no** threshold-sensitivity
  guidance and **no** determinism guarantee — only "tweak it empirically.")
- Set `min_word_threshold` low or `0`; it is a word-count floor with the same defect as Pitfall 10's
  char floor.
- **Instrument the auto-fallback rate.** A rising `route=tree → chunk` fallback rate is the only
  observable symptom that L1 ate the tree scaffolding. Add the counter *before* L1 ships, or the
  regression is undetectable.
- Per-format rules, not one global filter: HTML gets pruning; PDF (Docling) does not — it has no
  nav chrome, and pruning a clinical PDF's layout-analyzed output is pure loss.

**On determinism (Open Question 3, precise answer):** `PruningContentFilter` is a pure DOM-scoring
function — **deterministic for identical HTML**. The instability is not randomness; it is that a
*threshold function is discontinuous*. A block scoring 0.49 vs 0.51 flips wholesale. So a trivial
HTML delta (a rotating byline, an ad slot, a JS-rendered widget, an updated visitor counter)
produces a **large** markdown delta. The risk to SCHED-02 is real — but it is fully mitigated by
Pitfall 7's fix (keep the gate on `raw_markdown`), which removes the coupling entirely rather than
trying to make pruning stable. **Do that, and Open Question 3 stops being a question.**

**Warning signs:**
- Bronze markdown < 20% of raw markdown length for a source known to be content-rich.
- A source's `ParsedDoc.sections` count collapsing after L1.
- Rising `route=auto` → chunk fallback rate.
- Bolded drug names or link text missing from bronze.

**Phase to address:** L1 (crawler extraction). The dual-markdown sidecar and the fallback counter
are both L1 acceptance criteria.
**Verification:** Fixture: a TOC-style index page must still yield a usable tree index after L1.

---

### Pitfall 13: Index-time dedup breaks point identity, citation attribution, and the incremental-add path

**What goes wrong:**
D-3 says "one vector per unique text, payload carries all contributing source refs." The payload
`index.py:214-234` builds is **scalar throughout**:

```python
payload = {
    "document": parsed_artifact_id,   # singular
    "chunk_id": full_chunk_id,        # singular; also IS the point ID
    "section_path": ..., "page": ..., "source_id": ..., "source_name": ...,
}
points.append(VectorPoint(id=_strip_prefix(full_chunk_id), ...))
```

**The point ID *is* a chunk ID** (`index.py:213`, `_strip_prefix`). Collapse N chunks into one
point and you must choose one chunk's UUID as the identity. The other N−1 chunks are then
**unaddressable in Qdrant** — a search hit can cite only the arbitrarily-chosen winner. RETR-08's
citation contract and the whole "traceable from raw source to AI-ready output" Core Value degrade
to "traceable to one of several sources, chosen by insertion order."

Three concrete breakages:

1. **`refresh_all_points_payload` breaks.** `_build_payload_refresh_fn` (`index.py:271-284`)
   resolves via `old_payload.get("document")` — singular. With a deduped point, which document's
   metadata wins? The KL-06 repair path — the same mechanism Pitfall 6 recommends for flagging old
   chunks — silently resolves against one arbitrary contributor.
2. **Payload filters change semantics.** PAYLOAD-02 filters on `source_name`, `format`, `tags`,
   `source_id`. Turn `source_name` into a list and Qdrant's match-any semantics are *probably*
   right for filtering — but `title`, `document_type`, and `page` become genuinely ambiguous, and
   the API/CLI render one of them to the user as *the* citation. A user filtering
   `--source-name "FDA"` gets a hit whose displayed citation says "CMS".
3. **Incremental add is impossible as specified.** Document 35 arrives with text identical to an
   existing collapsed point. To append its ref you must *find that point* — but you only have
   `sha256(text)`, and the point ID is `_strip_prefix(chunk_id)`, an unrelated UUID. **There is no
   way to look up "the point for this text"** without either a scroll-and-scan (O(N) per chunk) or
   a payload index on a text hash. Nothing in `qdrant_store.py` provides this.

**Why it happens:**
D-3 was chosen to protect artifact lineage (correctly — it does). But it moves the many-to-one
relationship from the *registry*, which has a schema and constraints, into the *Qdrant payload*,
which has neither. The complexity didn't vanish; it relocated somewhere with no integrity checks.

**How to avoid:**
- **Make the deduped point content-addressed.** `point_id = uuid5(NAMESPACE, sha256(normalized_text))`.
  Then "find the point for this text" is an O(1) `retrieve` by ID, incremental add works, and
  re-index is idempotent by construction. This mirrors the `put_raw` content-addressed pattern
  the project has already validated twice.
- **Payload carries `contributors: list[{chunk_id, document, source_id, source_name, section_path,
  page}]`, plus a designated `primary` for single-citation rendering.** Keep the scalar fields
  populated from `primary` so PAYLOAD-01/02 filters and every existing surface keep working
  unchanged — additive, not a breaking change.
- **Define the primary deterministically** (e.g. lowest `source_id`, then lowest `section_path`) so
  the same corpus always yields the same citation. An arbitrary/insertion-order primary makes
  search results non-reproducible across re-indexes — and non-reproducible results are
  indistinguishable from a bug.
- Update `_build_payload_refresh_fn` to resolve per-contributor.
- Surface multi-attribution in the API: a hit sourced from 5 documents should say so. That's
  *information* (this text is standard across the corpus), not noise.

**Warning signs:**
- A search hit whose `source_name` doesn't match the document its text came from.
- Re-indexing the same corpus twice produces different citations for the same query.
- Dedup implemented with a scroll-and-scan lookup (it will be O(N) per chunk and will not scale
  past the current corpus).

**Phase to address:** L4 (index-time dedup). Point-ID scheme is the first design decision of that
phase — everything else follows from it.
**Verification:** Ingest the same text under two sources; assert one point, two contributors, a
stable primary, and that both `--source-name` filters find it.

---

### Pitfall 14: Near-duplicate collapse destroys the delta — and the delta is usually the answer

**What goes wrong:**
Extending dedup from exact to near-dup (0.8 Jaccard) looks like a natural next step. In a clinical
corpus it is a data-destruction bug:

- Two FDA label sections identical except **the dosage** — adult vs pediatric. 0.8 Jaccard: "same".
- Two state Medicaid eligibility pages identical except **the state and the income threshold**.
- Two US Core profiles identical except **one cardinality** `0..1` vs `1..1` — which is the entire
  normative content of the profile.
- Two guideline recommendations identical except **Class I vs Class III** — i.e. "do this" vs
  "do not do this."

MinHash over 5-word shingles (`clean.py:139-164`) is *specifically* insensitive to a single
changed token in a long passage. **The precise property that makes it good at finding duplicated
boilerplate makes it blind to the one word that inverts a clinical recommendation.**

**Why it happens:**
Near-dup collapse is standard practice in *pretraining* corpora, where near-identical documents
genuinely add nothing to next-token prediction. RAG has the opposite requirement: the corpus must
be able to distinguish two documents that differ in one clinically decisive token. Importing a
pretraining technique into the retrieval path is the same category error as Pitfall 11.

**How to avoid:**
- **D-3 as written is correct: exact-match only at index time. Do not extend to near-dup.**
  Record this as an explicit decision with this rationale so a future milestone doesn't "improve"
  it.
- The architecture already agrees. `clean.py` treats near-dup as **advisory metadata**
  (`dedup_status`, explicitly *"advisory only, not a gate"*, `clean.py:245-253`), and
  `curate.batch_dedup_corpus()` is the authoritative near-dup signal — scoped to the
  **pretrain** path, where it belongs (CURATE-02, D-02). The existing separation of concerns is
  right. Preserve it.
- If near-dup is ever revisited, it must **cluster and keep**, never collapse: link near-dups with
  a `near_dup_group_id` payload field and let search diversify results, rather than deleting the
  variants.
- Note that Pitfall 2's cleaning-driven collision growth applies here too: aggressive cleaning
  pushes *more* pairs across the 0.8 threshold, so a near-dup gate would get more destructive
  exactly as cleaning improves.

**Warning signs:**
- Search for "pediatric dose of X" returns the adult dose.
- `dedup_status: near_dup` being read anywhere on the RAG path.
- Chunk count dropping more than the audit's 14% exact-duplicate figure predicts.

**Phase to address:** L4 — as an explicit **non-goal** recorded in the phase plan, not silence.
**Verification:** Fixture: two chunks differing only in a dosage must both survive dedup and be
independently retrievable.

---

### Pitfall 15: Silent dropping makes the filter unfalsifiable — and this project already learned that lesson

**What goes wrong:**
If `chunk()` simply refuses to emit, the filter produces **no evidence of its own operation**. You
cannot distinguish:
- the gate correctly dropped 300 nav chunks,
- the parser produced no sections (a Docling regression),
- L1 over-pruned the page to nothing,
- the gate is broken and dropping everything.

All four look identical: fewer chunks. Every test passes. The garbage rate improves in all four
cases — including the two where the pipeline is broken.

This is v2.5's headline lesson (*"green gates measured mechanism, not output quality... A pipeline
can be fully correct and fully worthless simultaneously"*) reappearing one layer down: **a filter
with no rejection record is a filter whose correctness cannot be measured at all.**

**Why it happens:**
`continue` is one line and an audit trail is a schema decision. And the audit that found the 28%
was an *external* script — so the pipeline has no internal notion of "garbage" to report on.

**How to avoid:**
Answering **Open Question 2** directly: **yes, record rejections — but as metadata and counters,
not as artifacts.**

- **Do not** write a `rejected` S3 artifact per drop. That is ~1,260 objects per corpus of content
  you specifically decided you don't want, in a zone with WORM semantics, permanently.
- **Do** record, per document, on the chunk stage's result and in the Dagster asset's metadata:
  `{rejected_count, kept_count, rejection_reasons: {too_short: N, link_dense: N, no_substance: N,
  boilerplate_pattern: N}}`. Dagster asset metadata is the natural home — it's per-run,
  queryable, historical, and already how this project surfaces asset observability.
- **Do** persist a bounded sample (first ~20 rejections per document, text truncated) so the
  rejection list is human-reviewable without storing the whole rejected corpus.
- **Do** ship **report-only mode first** (`chunk.substance_gate_mode: report|enforce`, default
  `report`). Run the full 34 sources, read the rejections, *then* flip to enforce. Given
  Trafilatura's 0.92 recall as the best-in-class benchmark, assume you will find false positives —
  the only question is whether you find them before or after they're in production.
- **Make the audit script a first-class, re-runnable artifact.** MILESTONE-CONTEXT notes a
  re-runnable quality audit was raised and not selected. It should be selected. Under D-2
  forward-only, *"did this work?" has no answer without it* — and the project's own retrospective
  says the lesson only becomes real when it's a build gate, not a document.

**Warning signs:**
- A gate implemented as a bare `continue`.
- No way to answer "what did the filter reject from source X last night?"
- The gate shipping straight to `enforce`.

**Phase to address:** L3 (substance gate) for the counters; a dedicated **quality-audit
requirement** (re-runnable garbage-rate metric) should be added to the milestone. It is the
instrument the whole milestone is judged by.
**Verification:** `rejected_count + kept_count == sections_considered` for every document — a
conservation check that catches "the gate dropped everything" and "the parser produced nothing"
as distinct failures.

---

### Pitfall 16: Measuring success under forward-only — four ways the number lies

**What goes wrong:**
The garbage rate will improve for at least four reasons that have nothing to do with the filter
working:

1. **Denominator dilution.** Add clean documents to a 4,499-chunk corpus with 28% garbage and the
   corpus-wide rate falls **even if the filter does literally nothing**. Ingesting 4,499 clean
   chunks halves the rate by arithmetic alone.
2. **Source-mix selection.** The audit's spread is enormous: ACC 81%, US Core 72%, eCQI 69%,
   FDA FAERS 55% — and by implication some sources near 0%. Validate on new sources and you are
   measuring **which sources you picked**, not the filter. Test on a clean PDF source and you'll
   see a 95% improvement that is entirely the source's doing.
3. **Zone confusion.** Gold improves retroactively and immediately (Pitfall 3); Qdrant doesn't. One
   number moves for free.
4. **Metric-definition drift.** If the gate's own heuristic becomes the audit's definition of
   garbage, the measurement is circular and always reports 100% success. The filter would score
   perfectly against itself while `Cardinality: 0..1` quietly disappears.

**Why it happens:**
Forward-only removes the natural before/after comparison. Without a controlled comparison, every
available number is confounded — and the confounds all point the same, flattering direction.

**How to avoid:**
The raw zone is intact and immutable. **That is not merely a compliance property — it is the
control group.** Use it:

- **Pairwise, per-source, same-source comparison.** Reprocess a held-out subset of the *same*
  sources from raw into a **shadow collection** (the alias-backed reindex machinery, INDEX-02/D-06,
  already supports a parallel physical collection without disturbing the live alias). Compare
  garbage rate **per `source_id`, old vs new**. Same documents, same everything, one variable.
  This is the only measurement that isolates the filter.
- **Report per-source, never corpus-wide.** A corpus-wide number is uninterpretable under D-2.
  A table of 34 rows (source → old rate → new rate) is unambiguous and immune to dilution and
  source-mix effects.
- **Keep the audit's classifier independent of the gate's classifier.** They must be able to
  disagree — that disagreement is the only real signal. If they're the same code, the metric is a
  tautology. Freeze the audit's definition before building the gate.
- **Add a false-negative instrument**, not just a false-positive one. The garbage rate only measures
  what got through. Nothing in the plan measures what got *wrongly removed* — and per Pitfall 10/11
  that is the dangerous direction in healthcare. The hand-labeled fixture set from Pitfall 10 is
  that instrument.

**Warning signs:**
- A single corpus-wide garbage-rate figure in the milestone report.
- Validation performed only on newly added sources.
- The audit script importing from the gate module.
- No measurement of content wrongly removed.

**Phase to address:** Requirements phase — the measurement design must exist **before** the filter
phases, or the milestone repeats v2.5's mistake with a new instrument. Consider a Phase-17-adjacent
"quality audit harness" phase.
**Verification:** The 34-row per-source before/after table, produced from a raw-zone reprocess of a
held-out subset into a shadow collection.

---

### Pitfall 17: Existing RAG eval datasets cite chunks the gate will remove — and the contamination gate fails closed

**What goes wrong:**
Two coupled problems, the second of which can block the milestone at its final step.

**(a) The eval sets are made of garbage.** `generate_qa_example` (`datasets.py:254`) reads a chunk
artifact and generates a Q&A pair from its text, stamping `citation_chunk_id` programmatically
(`datasets.py:375-380`). Applied to the 762 sub-30-char chunks, it produced Q&A pairs grounded in
"Featured". Those examples are in `rag_eval` datasets now. Any retrieval benchmark run against them
measures the model's ability to retrieve nav labels. **A v2.6 that improves retrieval will score
*worse* on these eval sets** — because the chunks the eval expects are exactly the ones the gate
removed. Someone will read that as a regression and roll back a working fix.

**(b) The contamination gate is load-bearing and fails closed.** `check_train_eval_contamination`
computes overlap between eval-cited cleaned docs and `pretrain_cleaned_doc_ids`, where the latter
is derived from *"curated_document artifacts whose quality_score >= min_quality_score_for_pretrain"*
(`export.py:183-188`). Change the quality gate and **`pretrain_cleaned_doc_ids` changes** → the
overlap set changes → `_enforce_no_contamination` may **newly fail closed** in all three export
functions. The milestone gets blocked at export by a change made at clean.

And there is precedent: v1.0's retrospective records this gate producing a **false positive** that
required a `contamination_override_artifact_ids` workaround. The override list is still in settings.
Any override IDs currently in there were justified against the *old* corpus composition; after the
gate lands they may be silently over-permissive — the override is applied *after* computing raw
overlap (`export.py` docstring), so a stale override hides a *new*, real contamination.

**Why it happens:**
Eval datasets are treated as ground truth. They are *derived artifacts of the same pipeline* being
fixed — they inherit its defects. And the contamination gate's input is the quality gate's output,
a dependency visible nowhere in either module.

**How to avoid:**
- **Version the eval datasets.** Existing `rag_eval` sets are `v1 (pre-filter)`. Do not compare
  v2.6 retrieval against them; regenerate after the gate lands and label the new ones
  `v2 (post-filter)`. Never compute a v1-vs-v2 delta and call it a regression.
- **Add a dangling-citation check**: every `citation_chunk_id` in an active eval dataset must
  resolve to a chunk present in the gated gold export. This catches Pitfall 3's retroactive drop.
- **Re-audit `contamination_override_artifact_ids` as part of the gate phase.** A stale override is
  strictly worse than no override — it suppresses a real finding.
- **Run the contamination gate in the gate phase's plan, not at export time.** Discover the
  fail-closed early, while it's a phase issue rather than a ship blocker.
- Regenerating eval sets re-bills `eval_model` per chunk (Pitfall 9's `_dataset_gen_cache_key`).
  Budget it. Silver lining: regenerate *after* the substance gate and you generate from ~28% fewer,
  much better chunks — cheaper *and* better. Ordering matters.

**Warning signs:**
- Retrieval benchmarks dropping after v2.6 lands.
- `_enforce_no_contamination` raising during an export that previously succeeded.
- An eval example whose `answer` is a nav label.
- `contamination_override_artifact_ids` non-empty and unreviewed.

**Phase to address:** L5 (gold export gate) must include eval regeneration + contamination re-audit
as acceptance criteria.
**Verification:** Zero dangling `citation_chunk_id` against the gated export; contamination gate
green on a full export run.

---

### Pitfall 18: Wiki IDF cross-linking shifts under L0 — and the incremental rebuild will lie

**What goes wrong:**
`compute_entity_idf` (`wiki.py:182-215`) computes `log(total_docs / df)` over **entity document
frequency from enrichment metadata**, then admits concept pages where
`df >= min_entity_df AND idf >= min_entity_idf` (`wiki.py:522-531`).

Two forces move these numbers:

1. **L0 changes enrichment input.** `enrich` uses `parsed_doc.sections` (uncleaned) for its section
   context (`enrich.py:340-341`). Wire cleaned sections in and the extracted entity sets change →
   `entity_doc_freq` changes → **every entity's IDF changes** → different entities cross
   `min_entity_idf` → concept pages appear and vanish, and cross-links appear and vanish **on
   documents that did not themselves change.**
2. **Forward-only grows `total_docs` forever.** `IDF = log(total_docs / df)` rises monotonically
   with `total_docs` for any entity whose `df` is static. Under D-2, `total_docs` only grows →ical
   more entities cross the threshold over time → concept-page count grows superlinearly. There is
   already a `>1000 docs` large-corpus warning in the code (`wiki.py:507`), and PROJECT.md already
   flags the Phase-16 decision as *"⚠ threshold still needs empirical tuning for link density."*
   v2.6 makes an already-flagged tuning problem worse.

**And KB-04's incremental rebuild will mislead.** `_identify_changed_pages` (`wiki.py:218-253`)
diffs **content hashes** against the manifest. An IDF shift changes the *rendered links* on a page
→ its content hash changes → it lands in `changed_pages`. So an IDF-threshold change triggers a
near-**full** rebuild that the manifest reports as ordinary incremental churn. Every page is
"changed" but nothing semantically changed — the diff is signal-free exactly when you most want to
know what moved.

**Why it happens:**
IDF is a **corpus-global statistic** hidden inside a stage that presents as per-document
compilation. Nothing in the wiki phase's interface hints that changing an unrelated pipeline stage
mutates every page's links.

**How to avoid:**
- **Snapshot the IDF inputs into the manifest**: persist `{total_docs, entity_doc_freq_hash,
  min_entity_idf, min_entity_df}`. On rebuild, compare — if they moved, the rebuild is a **full
  rebuild by declaration**, not an incremental one that happens to touch everything. Makes the
  cause legible.
- **Treat a threshold or corpus-composition change as an explicit full-rebuild trigger**, distinct
  from content change. Two different rebuild reasons, reported differently.
- **Track concept-page count as a metric.** It is the cheapest observable proxy for IDF drift, and
  it will grow under D-2 whether or not v2.6 touches the wiki.
- Consider **freezing `total_docs`** to a snapshot per wiki build so link stability doesn't depend
  on ingest timing — otherwise the same corpus produces different wikis depending on when it ran.
  Non-reproducible output is the same class of problem as Pitfall 13's arbitrary primary.

**Warning signs:**
- A wiki rebuild reporting ~100% pages changed after a pipeline change that touched no document.
- Concept-page count growing faster than document count.
- Cross-links appearing on pages whose source document is untouched.

**Phase to address:** L0 (Phase 17) — its blast radius reaches the wiki, and the phase plan must say
so. Manifest snapshotting is a small addition to the wiki module.
**Verification:** Assert `_identify_changed_pages` returns ∅ for a rebuild where neither content
nor IDF inputs changed.

---

### Pitfall 19: Reaching for an LLM classifier — where the temptation creeps in, and why it's a false economy

**What goes wrong:**
L2 ("section-level boilerplate classification") is where the deterministic-first constraint will
break. "Is this section a nav bar or clinical guidance?" *feels* semantic. It will feel especially
tempting after the deterministic heuristics produce their first false positives (they will, per
Pitfall 10/11) and someone proposes `cheap_model` as the tie-breaker for the gray zone.

The costs, concretely:
- **Call-count explosion.** Enrichment is *one call per document*, cached by content hash — a v1.0
  pattern explicitly recorded as a cost-control success. A per-chunk classifier at 4,499 chunks is
  a ~**150× increase in call count** against an `LlmSpend` budget model designed for per-document
  economics. It will hit the cap and halt (Pitfall 9).
- **Ingest-path latency.** The gate is inline in `chunk()`. Every ingest now blocks on Bedrock.
  Dagster retries multiply it.
- **Nondeterminism at the gate.** The same chunk may be kept on Monday and dropped on Tuesday. The
  corpus stops being reproducible from raw — which quietly voids Pitfall 16's entire measurement
  strategy, because the control group is no longer reproducible either.
- **It doesn't buy the accuracy it promises.** The gray zone where an LLM helps is small; the
  deterministic signals (link density, `is_table`, token count, positional invariance, domain-term
  presence) resolve the overwhelming majority.

**The decisive argument:** **the audit found the 28% deterministically.** A script with no LLM
identified 762 too-short, 408 no-sentence, 653 exact-dup, 123 boilerplate, and 152 marketing
chunks. **If a deterministic classifier can find the garbage, a deterministic classifier can gate
it.** The existence of the audit is proof the LLM isn't needed. Any proposal for a per-chunk LLM
call should be required to state what it catches that the audit script missed.

**Why it happens:**
Classification reads as an LLM-shaped task. And the project has a *good* LLM pattern
(heuristic-first, LLM opt-in with guaranteed fallback — v2.5's most successful shape), which makes
adding "one more opt-in LLM mode" feel like established practice rather than a new cost center.

**How to avoid:**
- If an LLM path is added at all, it must follow the **v2.5 shape exactly**: deterministic result
  computed **first** and **always**, LLM able to *reorder or annotate* but **never** to remove
  content the heuristic kept, opt-in, budget-capped, never on the default path. That is the
  `PageIndexRetriever` contract (*"LLM-nav cannot raise, cannot degrade"*) and it should be the
  literal template. **Never let an LLM be the thing that deletes content.**
- Better: use the LLM **offline, once**, to help *design* the heuristics — label 200 sections, find
  what the heuristics miss, encode the finding as a regex. Zero runtime cost, zero
  nondeterminism, and the output is reviewable.
- Route any LLM use through LiteLLM with `cheap_model` (per the LLM Gateway constraint) — but the
  constraint that binds harder is **deterministic-first**, and MILESTONE-CONTEXT already states it:
  *"A quality gate that needs an LLM call per chunk violates this."*

**Warning signs:**
- A `litellm` import appearing in `chunk.py` or a new `classify.py` on the ingest path.
- `LlmSpend` growth during a milestone scoped as deterministic filtering.
- A gate whose result varies across runs on identical input.

**Phase to address:** L2 (section classification) — record "no per-chunk LLM call" as an explicit
phase constraint, not an assumption.
**Verification:** The gate is a pure function: same input → same output, no network. Assert it in a
unit test with no mocks needed — if it needs a mock, it's calling out.

---

### Pitfall 20: Gating at parse or clean starves the tree index — the substance gate belongs at chunk

**What goes wrong:**
MILESTONE-CONTEXT Open Question 1 asks where the substance gate belongs: parse (drop the section),
clean (strip it), or chunk (refuse to emit). The tradeoff as posed — "dropping at parse loses
lineage evidence; dropping at chunk means paying enrich cost on garbage first" — misses the
deciding constraint.

`chunk_document` and `tree_index_document` are **parallel consumers of the same
`ParsedDoc.sections`** (TREE-05: tree index fans out from `clean_document` alongside chunking).
They need **different filters over the same input**:

| Section | Chunker wants | Tree index wants |
|---|---|---|
| Nav bar | drop | drop |
| TOC / index page | drop (no prose) | **keep** — it is the document's structure |
| Heading with no body | drop or merge | **keep** — it is a tree node |
| Short table | **keep** (atomic, CHUNK-03) | keep |

Drop link-dense and body-less sections at parse or clean and the **tree index loses its
scaffolding**. Headings without bodies *are* tree nodes — TREE-03 states nodes carry
`title, summary, page range, children`, and *"deterministic mode uses heading text"* as the
summary. A body-less heading is a perfectly good tree node and a worthless chunk. A gate at
parse/clean cannot express that, because it has one output feeding two consumers with opposite
requirements.

And the degradation is silent: ROUTE-03's D-05 auto-fallback means an emptied tree quietly falls
back to the chunk path.

**Why it happens:**
"Filter early" is a good default in data pipelines — do work once, upstream. It fails when one
upstream output feeds consumers with **conflicting** requirements. This one does.

**How to avoid:**
**Gate at chunk. Answering Open Question 1 directly:**
- **Parse:** never gate. It is the faithful-representation layer; L2 correctly identifies Docling as
  *"doing its job correctly."* Do not teach the parser opinions.
- **Clean:** strip *text-level* boilerplate (the shared normalizer's job) and **annotate** sections
  with deterministic substance signals (`link_density`, `token_count`, `alpha_ratio`,
  `is_boilerplate_candidate`) — computed once, cheaply, on the `Section` objects. **Annotate, don't
  drop.** One computation, both consumers, each applies its own policy.
- **Chunk:** apply the substance gate — refuse to emit. This is where CHUNK-03's `is_table`
  exemption already lives and where `ChunkSettings` already lives (`max_tokens`, `overlap_tokens`,
  `tokenizer` — a `min_tokens` sibling is the natural home).
- **Tree index:** applies its own, much weaker filter (drop only hard nav chrome), keeping structure.

The "pay enrich cost on garbage" objection dissolves: enrich is **per-document**, not per-chunk
(`enrich.py:279`), and reads the **cleaned blob** — so text-level cleaning at the clean stage
already removes the boilerplate enrich would otherwise pay for. Chunk-level gating costs
nothing extra in LLM spend.

The annotate-don't-drop shape is also the v2.5 "sidecar for derived structure" pattern
(`parse()` writes a sections sidecar that chunk/tree both read): compute derived signal once,
persist beside the data, let each consumer decide. Precedent exists.

**Warning signs:**
- A `continue` in `parse()` or a section-dropping loop in `clean()`.
- Tree node counts dropping proportionally with chunk counts (they should decouple).
- Rising `route=tree → chunk` auto-fallback rate.

**Phase to address:** L2 computes the annotations; L3 consumes them at chunk. The
annotate/consume split is the key architectural decision and must be made in L2's plan.
**Verification:** A TOC-style document yields a healthy tree index and near-zero chunks — both
correct, from one `ParsedDoc`.

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Bare `len(text) < 30` gate | One line; matches the audit finding exactly | Deletes ICD-10 codes, dosages, FHIR cardinalities; corrupts US Core/eCQI (the two worst sources) while the metric improves | **Never** — use `token_count()` + `is_table` exemption + domain allowlist |
| Re-parent chunks to `cleaned_document` to "fix lineage" | Lineage graph reads correctly | Silently nulls all 11 payload fields; breaks 4 call sites incl. the fail-closed contamination gate | **Never** without migrating `get_enriched_artifact_for_parsed` and all callers in the same commit |
| Extend `BOILERPLATE_PATTERNS` in place | 5-minute change | Mass re-crawl of 34 gov sites via the shared `_signature()` call; bronze/parsed/chunk duplication | Only after the gate's normalizer is severed or versioned |
| Ship the gate straight to `enforce` | Skips a rollout step | Irreversible content loss with no rejection record; Trafilatura's 0.92 recall says false positives are near-certain | **Never** in a clinical corpus — report-only first, human review, then enforce |
| Gate at export only (skip the chunk gate) | Only touches `export.py` | Cannot work — `quality_score` is document-level; can't see within-document garbage | Never — it's not a shortcut, it's a no-op |
| Ship dedup (L4) before the substance gate (L3) | Immediate embedding-cost win | Qdrant `Modifier.IDF` promotes the surviving boilerplate to top BM25 hits | Never — hard ordering constraint |
| Arbitrary "primary" contributor on a deduped point | Avoids a tie-break rule | Non-reproducible citations across re-indexes; indistinguishable from a bug | Never — define a deterministic rule |
| Per-chunk LLM classifier for the "gray zone" | Feels more accurate | ~150× call-count vs the per-document norm; budget halt; nondeterministic corpus; voids the measurement control | Never on the default path; offline heuristic *design* only |
| Extend dedup to near-dup (0.8 Jaccard) | Removes 653 + more | Collapses adult/pediatric doses, Class I/III recommendations, `0..1` vs `1..1` | Never at index time — keep it advisory in `curate` where it belongs |
| Skip the re-runnable quality audit | Saves a phase | Under D-2 forward-only, "did this work?" has no answer — v2.5's exact failure | Never — it is the milestone's only instrument |
| Silent `continue` in the gate | One line | Filter becomes unfalsifiable; 4 distinct failures look identical | Never — counters + reasons are cheap |
| Single corpus-wide garbage-rate metric | One number to report | Confounded by dilution, source mix, and zone; improves even if the filter does nothing | Never — report per-source, old vs new |

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| **Crawl4AI `fit_markdown`** | Replacing `raw_markdown` with `fit_markdown` in the adapter | Return both; bronze stores both as siblings; only the parse path consumes `fit_markdown` |
| **Crawl4AI `PruningContentFilter`** | `threshold_type="dynamic"` (docs' implied default framing) | Pin `"fixed"` — dynamic is page-relative, so an unrelated block shifts every block's boundary |
| **Crawl4AI `PruningContentFilter`** | Trusting it with `<a>`/`<strong>` content | Open bug #582 strips their text entirely — bolded drug names and link text vanish. Validate on a real FDA label before trusting |
| **Crawl4AI `min_word_threshold`** | Setting it to the docs' suggested 50 | A word floor with Pitfall 10's exact defect at the worst layer (unrecoverable). Set low or 0 |
| **Qdrant `Modifier.IDF`** | Assuming IDF is a static property of the text | It's a live collection statistic — `ln((N-n+0.5)/(n+0.5)+1)`. Dedup and forward-only both move it |
| **Qdrant point IDs** | Keeping `_strip_prefix(chunk_id)` as the ID after dedup | `uuid5(NAMESPACE, sha256(text))` — makes dedup lookup O(1) and re-index idempotent |
| **Qdrant payload filters** | Turning scalar `source_name` into a list and assuming filters still work | Keep scalars from a deterministic `primary`; add `contributors[]` alongside (additive) |
| **Qdrant sharding** | Assuming IDF is collection-wide | Docs don't specify per-shard vs collection-wide. Verify against the running server before relying on IDF stability |
| **SCHED-02 change gate** | Computing `_signature()` from filtered markdown | Compute from a **stable projection**; the gate answers "did the page change?", not "is the content good?" |
| **`remove_boilerplate()`** | Treating it as a private clean-stage helper | It has a second caller in `crawl.py:115` with an opposite requirement (stability). Sever or version |
| **`put_raw`** | Fearing a re-crawl storm corrupts WORM | It is content-addressed with a registry no-op — raw is safe. **Bronze** is the exposed zone |
| **`LlmSpend` budget cap** | Not budgeting for cache invalidation | Every cleaned-hash change invalidates enrich + curate + tree + dataset caches → full re-enrichment → graceful halt mid-run |
| **DataTrove filters** | Reusing Gopher/C4 for the RAG substance gate | They're prose-shaped and tuned for pretraining; terminal-punctuation and stopword checks misfire on tables, codes, cardinalities |
| **lingua language detection** | Gating on `language != "en"` | Only 5 European languages configured (`clean.py:115-121`); everything else → `"unknown"`, including structured/numeric content |

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Dedup lookup by scroll-and-scan | Index stage time grows quadratically with corpus size | Content-addressed point ID → O(1) `retrieve` | Noticeable at ~10k points; unusable at ~50k |
| `clean.py` transient LSH corpus scan | `clean()` wall time grows linearly per call; S3 GET per existing artifact | Already documented as T-03-06 (*"acceptable for < 10,000 documents"*). Aggressive cleaning increases both artifact count and per-call cost | Already at 34 sources × N docs; will bite during a full reprocess |
| Full re-enrichment on cache invalidation | `LlmSpend` spike, then a graceful halt mid-run | Gate first (28% fewer chunks), budget deliberately, resume via cache | On the first run after a `BOILERPLATE_PATTERNS` change |
| Re-crawl stampede on gate invalidation | Simultaneous 429/403 across FDA/CMS/ACC/NLM | Decouple the gate from the filter; pause the sensor; one-shot rate-limited backfill | On the first sensor tick after L1 |
| Concept-page growth from `total_docs` drift | Wiki build time grows; hairball cross-links | Snapshot IDF inputs; track concept-page count | Existing `>1000 docs` warning at `wiki.py:507` |
| Per-chunk LLM classifier | Ingest blocks on Bedrock; ~150× call count | Deterministic gate | At the first real 4,499-chunk run |
| Full wiki rebuild disguised as incremental | KB-04 reports ~100% pages changed | Snapshot IDF inputs in the manifest | On any IDF-input change |

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| Stripping FDA/HHS/CMS **disclaimer** lines as boilerplate | Removes the statement defining a document's legal authority. A RAG answer citing FDA guidance without "does not establish legally enforceable responsibilities" **misrepresents its regulatory force** | The existing `^(?:disclaimer\|copyright \d{4})` pattern already does this. Add a normative-phrase allowlist in the healthcare pack |
| Stripping **boxed/black-box warnings** as repeated boilerplate | A clinical RAG corpus that has lost its contraindications. Repetition is the *intent* of a boxed warning | Never drop on repetition alone; require conjunction with link density + positional invariance + absence of domain terms |
| Near-dup collapsing adult vs pediatric dosing | Corpus can no longer distinguish a safe dose from an overdose | Exact-match dedup only at index time (D-3 as written) |
| Near-dup collapsing Class I vs Class III recommendations | "Do this" and "do not do this" become one chunk | Same — MinHash over 5-word shingles is blind to the one token that inverts the meaning |
| Deduped point citing the wrong source | An answer attributed to FDA that came from a vendor page — a provenance failure in a regulated domain, and a direct Core Value violation | Deterministic `primary` + full `contributors[]`; surface multi-attribution |
| Stale `contamination_override_artifact_ids` after the gate changes the pretrain set | Override applied *after* raw-overlap computation → silently suppresses a **new, real** train/eval contamination | Re-audit the override list in the gate phase; treat a non-empty override as a review item |
| Crawl-time pruning removing link text (bug #582) | Loss of the citation trail to the authoritative source document | Keep `raw_markdown` as a sibling; validate on a real FDA label fixture |

## "Looks Done But Isn't" Checklist

- [ ] **L0 wiring:** Often missing the `cleaned_document` WR-05 hash fix — verify two parsed docs
      cleaning to identical text yield two distinct cleaned artifacts with correct parents.
- [ ] **L0 wiring:** Often missing the payload check — verify a freshly indexed chunk has non-null
      `source_name` and `quality_score` in Qdrant, not just that the code runs.
- [ ] **L0 wiring:** Often missing the wiki blast radius — verify a wiki rebuild reports ∅ changed
      pages when nothing changed.
- [ ] **Substance gate:** Often missing the `is_table` exemption — verify a 2×2 clinical table
      survives.
- [ ] **Substance gate:** Often missing the domain allowlist — verify `ICD-10 E11.9`,
      `Metformin 500 mg PO BID`, `Cardinality: 0..1` all survive.
- [ ] **Substance gate:** Often missing rejection accounting — verify
      `rejected + kept == sections_considered`.
- [ ] **Substance gate:** Often missing report-only mode — verify the default is `report`, not
      `enforce`.
- [ ] **Boilerplate patterns:** Often missing the shared-caller check — verify `_signature()` is
      byte-stable across the pattern change.
- [ ] **Boilerplate patterns:** Often missing the normative allowlist — verify an FDA boxed warning
      survives clean → chunk → index.
- [ ] **Crawler extraction:** Often missing dual markdown — verify bronze retains `raw_markdown`
      alongside `fit_markdown`.
- [ ] **Crawler extraction:** Often missing the tree check — verify a TOC page still yields a usable
      tree index.
- [ ] **Crawler extraction:** Often missing the fallback counter — verify `route=tree → chunk`
      fallback rate is observable *before* L1 ships.
- [ ] **Index-time dedup:** Often missing content-addressed point IDs — verify incremental add finds
      the existing point without a scroll.
- [ ] **Index-time dedup:** Often missing sparse regression — verify a boilerplate term's
      `--mode sparse` rank did not *rise*.
- [ ] **Index-time dedup:** Often missing `refresh_all_points_payload` — verify the KL-06 repair path
      still resolves a deduped point.
- [ ] **Export gate:** Often missing chunk-level scoring — verify it gates on a chunk field, not
      `enriched.quality_score`.
- [ ] **Export gate:** Often missing eval regeneration — verify zero dangling `citation_chunk_id`.
- [ ] **Export gate:** Often missing the contamination re-audit — verify
      `_enforce_no_contamination` passes on a full export.
- [ ] **Measurement:** Often missing the control — verify a per-source old-vs-new table exists from a
      raw-zone reprocess, not a corpus-wide number.
- [ ] **Measurement:** Often missing the false-negative instrument — verify a hand-labeled
      must-not-reject fixture set is in CI.

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Payload nulled by re-parenting (P1) | **LOW** | `reindex --refresh-payload` (KL-06) re-derives payload from the registry without re-embedding — once the join is fixed |
| Cross-document cleaned-artifact collision (P2) | **HIGH** | Lineage is already corrupt; requires identifying affected artifacts, deleting cleaned/chunk rows, reprocessing from raw. **Prevent, don't recover** |
| Sparse IDF promotion of boilerplate (P5) | **MEDIUM** | Delete the offending points or payload-flag them + filter at search; IDF recovers automatically |
| IDF drift under forward-only (P6) | **LOW** | `reindex --refresh-payload` to stamp `substance_gate: pre_v2_6`, then filter at search. No re-embedding |
| Re-crawl stampede (P7) | **LOW→MEDIUM** | Raw is safe (content-addressed). Pause the sensor; CRAWL-03 backoff absorbs 429s. Bronze/chunk duplication needs cleanup or payload flagging |
| Full re-enrichment budget halt (P9) | **LOW** | Fail-closed and resumable by design. Raise the cap and re-run; the cache resumes where it stopped |
| Over-aggressive gate deleted real content (P10/P11) | **HIGH** if enforced without report-only; **ZERO** with it | Raw zone is intact → reprocess. But the *loss of trust* and the misleading metric are unrecoverable. This is why report-only is mandatory |
| Over-pruned bronze from L1 (P12) | **MEDIUM** | Raw HTML retained → re-derive bronze. But nothing does this automatically; needs a deliberate reprocess job |
| Wrong citation on a deduped point (P13) | **MEDIUM** | Re-index with contributors + deterministic primary. Any answers already generated with wrong attribution are not recoverable |
| Near-dup collapse of clinical variants (P14) | **HIGH** | The delta is gone from the index. Reprocess from raw. **Prevent** — don't ship near-dup |
| Eval sets invalidated (P17) | **MEDIUM** | Regenerate from gated chunks (costs `eval_model` per chunk). Version rather than overwrite |
| Wiki IDF churn (P18) | **LOW** | Full rebuild; it's derived. Cost is build time, not data |
| Measurement confounded (P16) | **LOW** technically, **HIGH** in consequence | Reprocess a held-out subset from raw into a shadow collection. The real cost is having shipped believing a wrong number |

## Pitfall-to-Phase Mapping

Phase numbering continues at **17** per MILESTONE-CONTEXT. Suggested grouping — the roadmapper owns
the final split; **the ordering constraints below are not negotiable.**

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| P1 Re-parenting nulls payload | **17 — L0 wiring** | Fresh chunk has non-null `source_name`; type guard raises on wrong artifact type |
| P2 `cleaned_document` WR-05 gap | **17 — L0 wiring** (same phase, mandatory) | Two docs → identical cleaned text → two artifacts, correct parents |
| P18 Wiki IDF drift | **17 — L0 wiring** (blast radius) | Rebuild reports ∅ changed pages when nothing changed |
| P8 Shared `remove_boilerplate` | **17 — sever the gate's normalizer** (before any pattern change) | `_signature()` byte-stable across a pattern change |
| P16 Measurement confounds | **Requirements + a quality-audit phase** (before the filter phases) | Per-source old-vs-new table from a raw reprocess into a shadow collection |
| P15 Silent dropping | **L3 + the quality-audit phase** | `rejected + kept == sections_considered`; report-only default |
| P3 Gold is not forward-only | **Requirements** (D-2 scoping correction) | Two separately named metrics |
| P12 Crawl pruning / tree starvation | **L1 — crawler extraction** | Dual markdown in bronze; TOC page yields a tree; fallback counter live |
| P7 `fit_markdown` invalidates the gate | **L1 — crawler extraction** | `_signature()` unchanged when `fit_markdown` toggles |
| P11 Normative repeated text | **L2 — section classification** (+ healthcare pack allowlist) | FDA boxed warning survives clean → chunk → index |
| P19 LLM classifier temptation | **L2 — section classification** | Gate is a pure function; no network in the unit test |
| P20 Gate placement (parse/clean/chunk) | **L2 annotates, L3 consumes** | TOC doc → healthy tree, ~zero chunks, from one `ParsedDoc` |
| P10 The 30-char trap | **L3 — chunk substance gate** (+ healthcare pack allowlist) | Hand-labeled must-not-reject fixtures in CI |
| P9 Cache invalidation budget | **L2/L3 sequencing + requirements cost estimate** | Predicted vs actual `LlmSpend` recorded in the phase plan |
| P5 Dedup promotes boilerplate via IDF | **L4 — index dedup** (**must follow L3**) | Boilerplate term's sparse rank does not rise |
| P13 Dedup breaks point identity | **L4 — index dedup** | Same text, two sources → one point, two contributors, stable primary |
| P14 Near-dup destroys the delta | **L4 — explicit non-goal in the phase plan** | Two chunks differing only in dosage both survive |
| P6 IDF drift under forward-only | **Requirements** (may revise D-2) → payload-flag + search filter | Fixed query set at N and 2N points; boilerplate ranks don't rise |
| P4 Document-level score can't gate chunks | **L5 — export gate** (**must follow L3**) | Gated Parquet has zero rows the audit classifies as garbage |
| P17 Eval sets + contamination gate | **L5 — export gate** | Zero dangling `citation_chunk_id`; contamination gate green |

**Hard ordering constraints:**
1. **L0 (P1, P2, P8, P18) first** — it is a lineage fix, and it is the only phase whose defects
   corrupt data rather than merely degrade it. MILESTONE-CONTEXT is right that it's highest-leverage;
   it is also highest-risk.
2. **Measurement before filtering** — the audit harness and the must-not-reject fixture set must
   exist before any gate ships, or v2.6 repeats v2.5's exact failure with a new instrument.
3. **L3 before L4** — dedup without the substance gate makes BM25 worse via `Modifier.IDF`.
4. **L3 before L5** — the export gate has no chunk-level signal to gate on until L3 produces one.
5. **L3 before the L2 pattern strengthening** — so the full re-enrichment runs against a 28%
   smaller corpus.
6. **L1 last, with a rollout plan** — it is the widest blast radius, the only unrecoverable layer,
   and the one that forces a full re-ingest.

## Confidence Notes

| Finding | Confidence | Basis |
|---|---|---|
| P1, P2, P3, P4, P13, P17, P18, P20 mechanisms | **HIGH** | Read directly from this repo's source; line references given |
| P5, P6 (Qdrant IDF from live collection stats) | **HIGH** | Qdrant docs state IDF *"depends on the currently stored documents and therefore can't be pre-computed"*, formula given. **The magnitude at 4,499 points is untested here — verify empirically before relying on it** |
| Qdrant IDF per-shard vs collection-wide | **LOW** | Docs do not specify. Verify against the running server |
| P7 (raw safe, bronze exposed) | **HIGH** | `put_raw`'s four documented enforcement layers, `storage/s3.py:236-249` |
| P12 (`PruningContentFilter` strips `<a>`/`<strong>`) | **MEDIUM** | crawl4ai#582, open, reported against 0.4.247. **Unverified against 0.9.x — test before adopting** |
| P12 (pruning is deterministic-but-discontinuous) | **MEDIUM** | Inferred from the documented algorithm (DOM scoring + threshold). Crawl4AI docs make **no** determinism guarantee. The recommended mitigation (decouple the gate) makes this moot |
| P10/P11 (healthcare false positives) | **HIGH** | Domain reasoning + SANDIA SAND2024-10208 (Trafilatura recall 0.92 = ~8% real-content loss is the best-in-class floor) |
| P9 (cache invalidation cost) | **HIGH** | Cache keys read from source; cost magnitude unestimated |
| P16 (measurement confounds) | **HIGH** | Arithmetic + the audit's own per-source spread (81% → low single digits) |

## Gaps

- **Magnitude of the IDF effect at 4,499 points is unmeasured.** The mechanism is certain; whether
  a deduped footer actually reaches the top-10 needs a live Qdrant experiment. Worth a spike in L4.
- **`PruningContentFilter` behavior on 0.9.x is unverified.** Bug #582 is from 0.4.247. Test against
  a real FDA/ACC page before L1 commits to it.
- **Exact-duplicate collision rate after aggressive cleaning is unknown.** P2's severity scales with
  it. Cheap to measure: run the proposed cleaner over the existing 34 sources' parsed artifacts
  (read-only) and count `sha256(cleaned_text)` collisions across different parents. **Do this during
  requirements** — it sizes the risk before Phase 17 commits.
- **Whether the healthcare pack's existing taxonomy/validator can be reused as a substance signal**
  was not investigated. If it can, the domain allowlist is nearly free.
- **No measurement exists of the tree index's current health**, so P12's regression would have no
  baseline. Capture the tree-node count and the route-fallback rate before L1.

## Sources

- Qdrant IDF modifier — [qdrant.tech/documentation/concepts/indexing/#idf-modifier](https://qdrant.tech/documentation/concepts/indexing/#idf-modifier) — HIGH (formula and live-statistics semantics stated explicitly)
- Crawl4AI markdown generation / PruningContentFilter — [docs.crawl4ai.com/core/markdown-generation/](https://docs.crawl4ai.com/core/markdown-generation/) — MEDIUM (no determinism or sensitivity guidance)
- Crawl4AI issue #582, `PruningContentFilter` strips `<a>`/`<strong>` — [github.com/unclecode/crawl4ai/issues/582](https://github.com/unclecode/crawl4ai/issues/582) — MEDIUM (open, v0.4.247, unverified on 0.9.x)
- SANDIA SAND2024-10208, "An Evaluation of Main Content Extraction" (Aug 2024) — [osti.gov/servlets/purl/2429881](https://www.osti.gov/servlets/purl/2429881) — HIGH (Trafilatura F1 0.937 / precision 0.978 / **recall 0.92**)
- Trafilatura evaluation docs — [trafilatura.readthedocs.io/en/latest/evaluation.html](https://trafilatura.readthedocs.io/en/latest/evaluation.html) — HIGH (lists/tables are the hard cases; per-element opt-out rather than global scoring)
- **This repository's source** — HIGH, and the basis for most findings:
  `pipeline/clean.py`, `pipeline/chunk.py`, `pipeline/index.py`, `pipeline/export.py`,
  `pipeline/crawl.py`, `pipeline/enrich.py`, `pipeline/curate.py`, `pipeline/wiki.py`,
  `pipeline/datasets.py`, `plugins/builtin/sparse_embedder.py`, `plugins/builtin/qdrant_store.py`,
  `plugins/builtin/crawl4ai_adapter.py`, `registry/repo.py`, `storage/s3.py`,
  `dagster_defs/assets.py`
- `.planning/RETROSPECTIVE.md` — HIGH — v2.5 Lesson 1 (green gates measured mechanism), Lesson 2
  (a recorded lesson is not an enforced one), v2.0's gate-local normalization pattern, v1.0's
  contamination-gate false positive
- `.planning/PROJECT.md` — HIGH — WR-05 decision, forward-only STORE-01 precedent, the
  clean-stage-bypass defect row, IDF-tuning ⚠ flag
- `.planning/MILESTONE-CONTEXT.md` — HIGH — audit evidence, six root causes, D-1..D-4

---
*Pitfalls research for: retrofitting content filtering into an existing corpus pipeline (Knowledge Lake v2.6)*
*Researched: 2026-07-15*
