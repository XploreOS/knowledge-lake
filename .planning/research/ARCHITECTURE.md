# Architecture Research

**Domain:** Retrofitting content-quality filtering into a shipped Dagster-orchestrated data lake pipeline
**Researched:** 2026-07-15
**Confidence:** HIGH (every claim about existing behavior is cited to file:line and was read, not assumed)

---

## Executive Finding: There Are TWO Bypasses, Not One

The milestone brief documents L0 — `clean_document` forwards the uncleaned `ParsedDoc`. Verified:
`clean()` is called for its S3 side effect at `dagster_defs/assets.py:318`, and the return dict at
`assets.py:325` forwards `"parsed_doc": parsed_doc` — the object received verbatim from
`parsed_document` at `assets.py:301`. All three downstream assets read it:
`chunk_document` (`assets.py:372`), `enrich_document` (`assets.py:433`), `tree_index_document`
(`assets.py:501`). Confirmed exactly as briefed.

**But code grounding found a second, more total bypass that the brief does not mention — and it is
the one that produced the audited corpus.**

`pipeline/process.py::process_crawled()` — the implementation behind `klake process`
(`cli/app.py:672`) — runs `parse → chunk → embed → index` at `process.py:103-112` and **never calls
`clean()` at all.** There is no clean stage in that function. `clean()` has exactly four call sites
in the entire codebase:

| Call site | Path |
|-----------|------|
| `cli/app.py:229` | `klake clean` — manual, single-document |
| `api/app.py:788` | `POST /clean` — manual, single-document |
| `dagster_defs/assets.py:318` | `clean_document` asset — result discarded (L0) |
| — | *(no other)* |

The audit that produced the 4,499-chunk / 28%-garbage evidence was an audit of `klake process`
(MILESTONE-CONTEXT.md:4). That path never had a clean stage to bypass.

**Consequence for the roadmap:** fixing `clean_document`'s return dict fixes the Dagster path only.
`klake process` would still produce 28% garbage. **Both call paths must be fixed, or the milestone's
headline metric will not move on the command people actually run.** This raises L0 from "one-line
dict fix" to "unify the pipeline entry points," and it is the single highest-value correction this
research makes to the milestone brief.

A related structural finding, same theme: `crawl.py:892` writes a `bronze_document` markdown
artifact for every crawled page, and **nothing reads it.** `process_crawled` selects
`raw_document` artifacts (`process.py:78`) and parses raw HTML. Grep for `bronze_document`
consumers returns only the writer, the ID-prefix map (`ids.py:42`), and docstrings. Bronze markdown
is a dead-end artifact. This has decisive consequences for Q5 (see below).

---

## Standard Architecture

### System Overview — Current (as shipped)

```
┌──────────────────────────────────────────────────────────────────────┐
│                          INGEST / CRAWL                              │
│   Crawl4AIAdapter.fetch_page → CrawlPageResult{html, markdown}       │
│         │                              │                             │
│         ▼ put_raw (WORM)               ▼ put_bronze                  │
│   ┌───────────────┐              ┌───────────────┐                   │
│   │ raw_document  │              │bronze_document│  ◀── DEAD END     │
│   │  (full HTML)  │              │  (markdown)   │      nothing      │
│   └───────┬───────┘              └───────────────┘      reads it     │
├───────────┼──────────────────────────────────────────────────────────┤
│           ▼                    PARSE                                 │
│   parse() → ParsedDoc{text, sections[]}                              │
│   writes: silver/{hash}.md  +  silver/{hash}.sections.json ◀ sidecar │
├───────────┬──────────────────────────────────────────────────────────┤
│           │                                                          │
│     ┌─────┴──────────────────────────┐                               │
│     ▼ (Dagster)                      ▼ (klake process)               │
│  clean_document                   process_crawled                    │
│  ┌──────────────────────┐         ┌────────────────────────┐         │
│  │ clean() ─▶ S3 blob   │         │  NO CLEAN STAGE AT ALL │         │
│  │ returns parsed_doc ──┼─ ✗ ─┐   │  parse ▶ chunk ▶ embed │         │
│  │  (UNCLEANED)         │     │   │        ▶ index         │         │
│  └──────────┬───────────┘     │   └────────────┬───────────┘         │
├─────────────┼─────────────────┼────────────────┼─────────────────────┤
│             ▼ cleaned_document artifact        │                     │
│        ┌────────────┐                          │                     │
│        │  curate    │──▶ DataTrove filters ──▶ pretrain (HEALTHY)    │
│        └────────────┘                          │                     │
│             ╎                                  │                     │
│   uncleaned parsed_doc ────────────────────────┴──────┐              │
│             ▼                ▼                 ▼      ▼              │
│        chunk_document  tree_index_document  enrich_document          │
│             ▼                                                        │
│        embed ▶ index ▶ Qdrant  ──▶ RAG corpus (33% JUNK)             │
└──────────────────────────────────────────────────────────────────────┘
```

The diagram makes the defect legible: **cleaning is a leaf, not a link.** The only consumer of
`cleaned_document` is `curate` (`curate.py:144` retrieves cleaned text from S3), which feeds the
pretrain export. That is precisely why the DataTrove-filtered pretrain corpus looks healthy while
the RAG corpus is 33% junk — as the brief states, the filters are on the branch nobody reads.

### System Overview — Recommended (after v2.6)

```
┌──────────────────────────────────────────────────────────────────────┐
│  raw_document (full-fidelity HTML — UNCHANGED, WORM, reprocessable)  │
├──────────────────────────────┬───────────────────────────────────────┤
│                              ▼  parse() — stays FAITHFUL             │
│   ParsedDoc{sections[]} + silver/{hash}.sections.json                │
│                     (the EVIDENCE record: every section, incl. junk) │
├──────────────────────────────┬───────────────────────────────────────┤
│                              ▼  clean() — becomes SECTION-AWARE      │
│   ┌──────────────────────────────────────────────────────────┐       │
│   │ load sections ▶ classify ▶ DROP junk sections            │       │
│   │   ├─▶ cleaned/{hash}.md            (blob — curate/enrich)│       │
│   │   ├─▶ cleaned/{hash}.sections.json (NEW sidecar)         │       │
│   │   ├─▶ metadata: sections_total/dropped/reasons (METRIC)  │       │
│   │   └─▶ RETURNS cleaned ParsedDoc ─────────┐               │       │
│   └──────────────────────────────────────────┼───────────────┘       │
│                    THE FAN-OUT POINT ────────┤                       │
│         ┌────────────────┬───────────────────┴──┐                    │
│         ▼                ▼                      ▼                    │
│    chunk_document   tree_index_document   enrich_document            │
│    + min-token floor                      (no longer pays for junk)  │
│         ▼                                                            │
│    chunks (parent = parsed_artifact_id — UNCHANGED, WR-05 intact)    │
│         ▼                                                            │
│    dedup_chunks (NEW) ─▶ text_hash ledger (Postgres)                 │
│         ▼  unique texts only                                         │
│    embed ▶ index ▶ Qdrant ──▶ RAG corpus                             │
│         ▼                                                            │
│    export_rag_corpus + quality gate (NEW)                            │
└──────────────────────────────────────────────────────────────────────┘
```

### Component Responsibilities (target state)

| Component | Responsibility | Change |
|-----------|---------------|--------|
| `raw_document` zone | Full-fidelity capture; reprocess substrate | **Unchanged** — see Q5 |
| `parse()` | Faithful structure extraction + evidence sidecar | Unchanged |
| `clean()` | **Section-level substance filtering**; returns cleaned ParsedDoc | **Modified — the load-bearing change** |
| `chunk()` | Token-aware splitting + **min-substance floor** | Modified (additive setting) |
| `enrich()` | LLM metadata over *cleaned* sections | Behavior change via input only |
| `dedup_chunks` | Collapse identical texts to one vector; ledger the refs | **New** |
| `index()` | Payload + upsert | Modified (point-ID derivation) |
| `export_rag_corpus()` | Gold Parquet + **quality gate** | Modified (additive filter) |
| Change gate `_signature()` | Stable re-crawl decision | **Modified — decouple (see Q5)** |

---

## Q1: Closing the Bypass

### Recommendation: Option (b) — clean operates on Sections, writes a cleaned sections sidecar, and returns a cleaned `ParsedDoc`. Chunks keep `parent_artifact_id = parsed_artifact_id`.

**Option (c) — "chunk reads the cleaned_document artifact from S3 and re-derives sections" — must be
rejected outright. It is not merely inefficient; it is incorrect.**

`clean()` has an exact-dedup early return at `clean.py:305-320`: on a content-hash match it returns
`existing.id` / `existing.storage_uri` — an artifact that may belong to **a different source
entirely** (the lookup at `clean.py:305` is `get_artifact_by_hash(session, content_hash,
"cleaned_document")`, unscoped by source). Two pages that clean to identical text collapse to one
`cleaned_document`. If chunk re-read that artifact's S3 blob, it would chunk *another document's*
content and attribute it to this document. Option (c) converts a dedup optimization into silent
cross-source content substitution. In-memory forwarding is immune: the freshly computed cleaned
`ParsedDoc` always belongs to *this* document regardless of which artifact row won the dedup race.

Option (a) (clean returns a cleaned ParsedDoc built by running `remove_boilerplate` over the blob)
is a strict subset of (b) and cannot solve Q2 — you cannot round-trip a filtered markdown blob back
into `Section` objects without re-parsing, and re-parsing is exactly what `reparse_from_raw()` warns
costs ~40s per PDF (`parse.py:337-339`). Option (b) subsumes (a): filter the sections, then *derive*
the cleaned blob from the survivors. That keeps the blob and the sections consistent — which is
non-negotiable, because divergence between them is the very defect being fixed.

The sidecar interaction the brief asks about is favorable, not conflicting. `parse()` already writes
`{hash}.sections.json` (`parse.py:221-233`) and `load_parsed_doc()` already rehydrates it
(`parse.py:265-322`), with `reparse_from_raw()` as the pre-sidecar fallback (`parse.py:325`). So:

- **`clean()` gets its section input for free** — call `load_parsed_doc(parsed_artifact_id)`, fall
  back to `reparse_from_raw()`, exactly the pattern `cli/app.py`'s `cmd_chunk`/`cmd_tree_index`
  already use (`parse.py:20-21`). This also makes `klake clean` work standalone, which it must,
  since `clean()` is invoked with only an artifact ID from CLI/API (`cli/app.py:229`,
  `api/app.py:788`).
- **The parsed sidecar becomes the evidence record.** It is written before filtering and never
  modified. `parsed_sections − cleaned_sections` *is* the discard audit trail (see Q6).
- **The cleaned sidecar is the survivor set**, and gives the same standalone-rehydration property to
  the cleaned stage that Task 8 gave the parsed stage.

### Lineage: chunks must NOT re-parent to `cleaned_artifact_id`

The brief asks whether chunks should now parent to the cleaned artifact. **No.** Five things break,
and two of them are safety gates:

1. **Cross-source lineage corruption (the fatal one).** Per `clean.py:305-320`, one
   `cleaned_document` can be shared by documents from different sources. Parenting chunks to it
   makes chunk→source attribution ambiguous. This does not merely bend WR-05 — it *inverts* it.
   WR-05's stated purpose (`chunk.py:315-316`) is "dedup key must include parent to prevent lineage
   corruption across documents"; re-parenting to a cross-document-shared node reintroduces exactly
   that corruption through the parent itself.
2. **Index payload resolution breaks.** `index.py:191` calls
   `_resolve_document_payload_fields(session, parsed_artifact_id)`, which uses the two-hop walkers
   `get_enriched_artifact_for_parsed` / `get_curated_artifact_for_parsed` (`repo.py:839-903`). Both
   walk `parsed → cleaned → {enriched|curated}`. Handed a cleaned ID, `list_children(cleaned)` finds
   no `cleaned_document` child → returns `None` → `quality_score`, `document_type`, `keywords`,
   `title` all silently become `None` on every indexed point. Silent, not loud.
3. **Gold export breaks identically.** `export.py:301` is literally
   `parsed_id = chunk.parent_artifact_id  # chunk -> parsed`, feeding
   `get_enriched_artifact_for_parsed` at `export.py:303`. Same silent null-out — while v2.6 is
   *trying* to gate exports on quality.
4. **The contamination hard gate breaks.** `check_train_eval_contamination` walks chunk → parsed →
   cleaned to build the eval set (`export.py:113-119`, `export.py:155-159`). This is a fail-closed
   train/eval guardrail (`export.py:81-88`). Feeding it wrong parentage makes it fail *open* or
   throw spuriously. Never perturb a fail-closed gate as a side effect of a refactor.
5. **The reindex repair path breaks.** `_build_payload_refresh_fn` re-resolves each point from
   `payload["document"]` (`index.py:271-284`), which is set to `parsed_artifact_id`
   (`index.py:215`). Changing parentage without changing this leaves the repair path resolving
   against a stale contract.

**Instead: change the data, not the parentage.** Chunks keep `parent_artifact_id =
parsed_artifact_id` (`chunk.py:354`) and the WR-05 hash key `f"{parsed_artifact_id}:{text}"`
(`chunk.py:317`) stays byte-for-byte. Record the cleaning provenance additively in chunk
`metadata_` (`chunk.py:361-365` already takes a metadata dict): `cleaned_artifact_id`,
`cleaned_content_hash`. Lineage then answers "which cleaned artifact produced this chunk's text?"
without making the parent edge many-to-many. The core-value constraint ("every artifact traces back
to source") is satisfied by the parsed edge, which is the *structural* parent; cleaning is a
transform recorded as metadata on the edge, not a new edge.

**This is the cheapest correct answer and it changes zero registry schema.**

---

## Q2: Granularity Mismatch

`clean()` today never sees a `Section`. It fetches the parsed markdown blob from S3
(`clean.py:221-223`), runs `remove_boilerplate()` over the flat string (`clean.py:228`), and the four
`BOILERPLATE_PATTERNS` (`clean.py:46-60`) are all line-anchored `re.MULTILINE` substitutions. The
brief's diagnosis is exactly right: the garbage is section-shaped, and a line-anchored regex cannot
express "this whole section is a nav bar."

### Recommendation: filter `Section` objects; never rewrite their metadata.

The key insight that makes this safe: **filtering is a DROP, not a REWRITE.** Surviving sections
carry their original `section_path` and `page` verbatim (`protocols.py:43-61`), so every citation
metadata field chunking depends on is preserved by construction — `chunk.py:237-238` and
`chunk.py:250-252` read `section.section_path` / `section.page` straight through.

**Hard rule for the implementers: do not renumber `section_path` after dropping.** It is tempting to
close the gaps so paths read §1, §2, §3. Doing so would silently shift every citation in the corpus
and make `section_path` unstable across runs whenever the filter threshold changes — and
`section_path` is a citation field (`protocols.py:86-90`, D-07) surfaced to users and stored in
Qdrant payloads (`index.py:216`). A gap (§1, §3, §7) is correct and is itself evidence that
something was dropped.

The one sub-path needing care is `chunk.py:245-247`: sub-chunk paths are derived as
`f"{section.section_path}.{i+1}"` from the *surviving* section's own subdivision. That is internal to
a section and unaffected by dropping sibling sections. No change needed.

**Deriving the cleaned blob.** After filtering, `cleaned_text` = join of surviving sections' rendered
text, then the existing line-level `remove_boilerplate()` as a second pass for intra-section junk
(page numbers, cookie lines). This keeps `cleaned_document`'s contract intact — it is still
`text/markdown` at `silver/{domain}/{source_id}/cleaned/{hash}.md` (`clean.py:303`), still what
`curate` reads (`curate.py:144`) and `enrich` excerpts. Content changes, contract does not. Under
D-2 forward-only this yields new content hashes → new artifacts → existing corpus untouched. Exactly
the STORE-01 precedent.

**Section-level classification signals (deterministic-first, per the binding constraint):**

| Signal | Rule of thumb | Catches |
|--------|--------------|---------|
| Link density | links ÷ words above threshold | nav bars, footers, link farms |
| Terminal punctuation ratio | no sentence-ending punctuation | menu labels, "no real sentences" (408 / 9%) |
| Token floor | section below N tokens and not a table | "Featured" (762 / 16%) |
| Stop-word ratio | prose has stop words; nav does not | nav, tag clouds |
| Pattern match (extended) | TOS/cookie/CTA/pricing blocks | boilerplate (123), marketing (152) |
| Repetition across documents | same section text in ≥K docs of a source | site-wide chrome |

Tables (`Section.is_table`, `protocols.py:55`) must be exempt from prose-shaped heuristics — a table
legitimately has no terminal punctuation and few stop words. `chunk.py:230` already treats tables as
a special atomic case; the filter must mirror that carve-out or it will delete every table in the
corpus. **This is the single most likely way to ship a catastrophic regression in this milestone.**

**On the existing 4 patterns (brief's open question #5): extend, do not replace.** Phase-3 tests pin
them, and they are shared with the re-crawl change gate (`crawl.py:115`) — see Q5. Add new
section-level classification as a separate function operating on `Section`; leave
`remove_boilerplate(text)` as the line-level pass it is. Two functions, two granularities, two test
suites, one of which stays green.

---

## Q3: Where the Substance Gate Lives

### Recommendation: a two-tier gate. **Section-level drop at clean** (primary), **token floor at chunk** (backstop). Parse stays faithful.

The brief frames this as a trilemma with a real cost on each horn. The fan-out topology resolves it.
`enrich_document` (`assets.py:407`) and `chunk_document` (`assets.py:349`) both take
`clean_document` as their data input — they fan out from the same node. As the question notes,
**anything downstream of that fan-out cannot protect enrich.** A gate at chunk leaves
`enrich_document` paying `cheap_model` LLM cost to summarize cookie banners forever. So the primary
gate must be at or above `clean`. That eliminates "chunk only."

**Parse must stay faithful, and the reason is now concrete rather than philosophical.** The stated
cost of dropping at parse is "loses evidence of what was discarded." That cost is real *and
avoidable*: because `parse()` writes the sections sidecar with every section before filtering
(`parse.py:221-233`), dropping at *clean* loses nothing — the evidence is already durable in the
silver zone. Dropping at *parse* would destroy it at the source, and would also break D-2's stated
escape hatch ("a deliberate reprocess from the immutable raw zone remains possible later"). Parse is
also the plugin seam (`ParserPlugin`, `protocols.py:176`); putting policy inside it would make every
parser implementation responsible for reimplementing the same filter — a textbook seam violation.

So: **clean is the correct home.** It is the only stage that (a) sits above the fan-out, (b) already
exists as a filtering stage conceptually, (c) has an upstream evidence record, and (d) is not a
plugin seam.

The chunk-level token floor remains worth adding as a cheap backstop, for a distinct failure mode:
a *substantive* section can still emit a runt sub-chunk from the sliding-window remainder at
`chunk.py:166-167`. Note `ChunkSettings` genuinely has no floor — only `max_tokens: 512`,
`overlap_tokens: 64`, `tokenizer`, `heading_breadcrumb_depth` (`settings.py:125-143`), confirming
L3. Add `min_tokens`.

**On the brief's open question #4 (30 chars vs tokens): use tokens.** The audit's 30-char figure is
an artifact of the audit script, not a principle. `ChunkSettings` is token-denominated and
`token_count()` is already a cached O(1) call (`chunk.py:59-65`). A char floor would be the only
character-based measure in a token-based module. ~8 tokens ≈ 30 chars is a reasonable starting
default; tune against the Q6 metric. Tables must be exempt from the floor (`chunk.py:230-240`) — a
2-row table is legitimately short and CHUNK-03 says tables are atomic.

---

## Q4: Index-Time Dedup

### The scoping trap that must be designed around

**The 653 exact duplicates are overwhelmingly cross-document** (the same footer embedded across many
pages — MILESTONE-CONTEXT.md:22). But `chunk()` runs **per document**, and so does everything
downstream of it: `embed(chunks)` receives one document's chunks (`embed.py:44`), `index()` receives
one document's chunks plus a single `parsed_artifact_id` (`index.py:132-140`).

**Therefore a naive in-memory "dedup the list before embedding" inside `embed_chunks` catches almost
nothing.** It only collapses repeats *within* one document. Cross-document dedup requires durable
state. Any design that does not confront this will ship, pass its unit tests, and move the duplicate
count by ~2%.

### Recommendation: a Postgres text-hash ledger + deterministic UUIDv5 point IDs.

**Placement:** a new stage between `chunk_document` and `embed_chunks`. Not inside `chunk()` (that
would violate D-3 / WR-05 by making chunk artifacts many-to-many), and not inside `index()` (too
late — the embedding cost is already paid at `embed.py:47`). D-3 says "deduplicate *before
embedding*," which pins it precisely to this seam.

```
chunk_document ──▶ dedup_chunks (NEW) ──▶ embed_chunks ──▶ index_chunks
   all chunks         unique texts          vectors for       upsert
   (artifacts         + ledger writes       unique only       unique only
    unchanged)
```

**Mechanism:**

1. `text_hash = sha256(normalized_text)` — deliberately **without** the parent, the exact inverse of
   the WR-05 chunk key (`chunk.py:317`). The two hashes coexist and mean different things: the WR-05
   hash identifies *a chunk artifact of a document* (lineage); the text hash identifies *a unique
   string in the corpus* (vector identity). Stating this duality explicitly in the requirement will
   prevent someone "simplifying" them back together.
2. New registry table `chunk_text_index(text_hash PK, point_id, first_chunk_id, occurrence_count,
   created_at)` — the dedup ledger. Postgres owns registries; this is consistent with the existing
   architecture rather than a new store.
3. `point_id = uuid5(KLAKE_NAMESPACE, text_hash)` — deterministic. Identical text anywhere in the
   corpus resolves to the same Qdrant point ID, so **Qdrant collapses duplicates by construction on
   upsert**, and the operation is idempotent under re-run. This eliminates a read-before-write
   round-trip per chunk.
4. On ledger hit: skip embed, increment `occurrence_count`, record the occurrence. On miss: insert,
   embed, upsert.

**Payload carrying N source refs.** Do not stuff an unbounded occurrence array into the Qdrant
payload — it grows without limit for site-wide chrome (a footer across 500 pages) and every
incremental add would require a read-modify-write of the point. Instead:
- Payload carries the **canonical/representative** citation (first-seen `chunk_id`, `document`,
  `section_path`, `page` — the existing fields at `index.py:214-234`, unchanged in shape) plus
  `text_hash` and `occurrence_count`.
- The **ledger is the source of truth** for the full occurrence set. Attribution beyond the
  representative is a Postgres lookup keyed by `text_hash`, not a payload scan.

This preserves the existing payload contract (important: `_RAG_CORPUS_FIELDS` at `export.py:65-75`
is an explicit allow-list, and `search()` filters on payload fields at `search.py:56-63`) while
making the fan-out queryable.

**Re-index.** `reindex_collection` (`index.py:289`) is safe as-is: `copy_all_points` and
`reembed_all_points` copy point IDs verbatim, so already-collapsed points stay collapsed; the
dedup is not re-derived and cannot drift. **One caveat to document:** the payload repair path
`_build_payload_refresh_fn` (`index.py:271-284`) re-resolves fields from `payload["document"]` —
for a deduped point that is the representative's document only. Non-representative documents'
metadata will not influence the refreshed payload. That is a coherent semantic (the representative
is canonical), but it must be written down or it will be rediscovered as a bug.

**Incremental adds.** New document, same footer → ledger hit → no embed, no upsert, ledger
increment. Cheap and correct. The point's `occurrence_count` in the payload goes stale unless you
re-upsert; recommend accepting staleness (payload count is advisory; ledger is authoritative) rather
than paying a write per duplicate.

**Search attribution.** A hit on deduped text is attributed to the representative document. For
*boilerplate*, this is irrelevant — it should have been filtered upstream, and after Q2/Q3 land, most
of the 653 will never reach the index at all. For *legitimately repeated substantive text* (a
standard clinical definition repeated across guidelines), the representative attribution is a real
(if minor) fidelity loss, resolvable by hydrating occurrences from the ledger when
`occurrence_count > 1`. Recommend shipping without hydration and adding it only if the metric shows
material duplicate volume surviving the filters.

**Sequencing consequence:** because Q2/Q3 remove most duplicates at the source, **dedup should be
built after them** — you want to design against the residual, not the pre-filter mass. Building it
first risks over-engineering for a problem the filter already solved.

**Forward-only note:** new points use UUIDv5-from-text; existing points use stripped-chunk-UUID
(`index.py:213`, `_strip_prefix` at `index.py:403`). The collection will hold **mixed ID
derivations**. This is acceptable under D-2 (payload always carries `chunk_id`, so resolution is
unaffected) but must be explicitly documented, since it silently breaks the current invariant
"point ID == chunk artifact UUID."

---

## Q5: Crawler Extraction and the Raw Zone — the highest-risk area

### Finding 1: as currently plumbed, `fit_markdown` would deliver ZERO quality benefit to RAG.

`Crawl4AIAdapter.fetch_page` builds `CrawlerRunConfig(check_robots_txt=True,
cache_mode=CacheMode.BYPASS)` (`crawl4ai_adapter.py:107-110`) — no content filter, confirming L1.
It returns both `html` (`crawl4ai_adapter.py:141-142`) and `markdown`
(`crawl4ai_adapter.py:160`). `_write_artifacts` then writes **raw = HTML** (`crawl.py:879-884`) and
**bronze = markdown** (`crawl.py:892-897`).

`fit_markdown` / `PruningContentFilter` affects `result.markdown` — **not** `result.html`. So:

- Raw is unaffected → **the WORM concern the brief raises largely dissolves.** Pruning does not
  touch the raw zone at all under the current write path.
- Bronze markdown is affected → **and nothing reads bronze** (verified: no consumer;
  `process_crawled` selects `raw_document` at `process.py:78` and Docling re-parses the HTML).
- The change gate reads `probe.markdown` (`crawl.py:190`) → **affected, and it is live.**

**Net: enabling `fit_markdown` today changes exactly two things — a dead-end artifact, and the
re-crawl change gate. It improves nothing on the RAG path while destabilizing re-crawl.** This is
the strictly worst possible combination, and it is not obvious from the milestone brief. D-1's
crawler-extraction scope item, as literally stated, is a no-op-plus-risk.

### Finding 2: raw MUST stay full-fidelity HTML.

The brief asks: does pruned content go to raw, bronze, or both? **Bronze only. Raw must remain the
unpruned capture.** Rationale, and it is D-2's own logic: D-2 accepts leaving 28% garbage in the
existing corpus *specifically because* "a deliberate reprocess from the (immutable, intact) raw zone
remains possible later" (MILESTONE-CONTEXT.md:108-109). Writing pruned content to raw destroys that
guarantee prospectively — a threshold tuned wrong in July 2026 becomes permanently unrecoverable
data loss, and raw stops being a faithful record of the source (a legal/provenance property, given
the license-tracking constraint). Pruning is a *transformation*; transformations belong in
bronze/silver. Raw is capture. **The layering already encodes the right answer.**

### Finding 3: therefore L1's real cost is making bronze load-bearing.

For crawler-level extraction to pay off at all, the HTML path must consume bronze markdown instead
of re-parsing raw HTML through Docling. That is a `parse()` input-selection change: for HTML
sources with a bronze child, parse the bronze markdown; else parse raw. **This is a substantially
larger change than "enable a flag,"** it touches the parse fallback chain
(`parse.py:128`, `settings.py:86`), and it partially duplicates work the Q2 section classifier
already does on the Docling output.

**Recommendation: descope or defer L1.** The Q2 section-level classifier deletes nav bars and
footers regardless of whether they were pruned at crawl time, and it does so at a stage where the
decision is (a) reversible, (b) evidenced by the parsed sidecar, and (c) uniform across HTML, PDF,
CSV and manual upload — whereas crawl-time pruning only ever helps crawled HTML. **L1 buys a subset
of L2's benefit at higher blast radius and permanent-loss risk.** If the roadmap keeps D-1's "full
rework including crawler extraction," it should keep it as the *last* phase, gated on the Q6 metric
showing that crawl-shaped garbage actually survives the L2 filter. This is a direct challenge to a
confirmed scope decision, made on evidence, and the requirements author should weigh it explicitly
rather than inherit D-1 unexamined.

### Finding 4: the SCHED-02 change gate is coupled to `remove_boilerplate` — and this blocks L2, not just L1.

This is the interaction the brief asks about, and it is worse than framed — it binds a scope item the
brief did not connect to it.

`_signature()` at `crawl.py:106-118` computes:
```python
normalized = remove_boilerplate(markdown or "")          # crawl.py:115  ← SHARED with clean stage
return sha256(_suppress_volatile(normalized).encode()).hexdigest()
```
It **imports the silver-stage `remove_boilerplate` from `pipeline/clean.py`** (`crawl.py:40`),
deliberately, per decision D-06 "so the gate and the clean stage agree on boilerplate"
(`crawl.py:109-110`).

**Consequence: extending `BOILERPLATE_PATTERNS` (brief's open question #5) changes every scheduled
source's content signature.** At `crawl.py:193`, `sig == last_hash` fails for all 34 sources → all
report "changed" → all trigger a full `crawl_source()` on the next sensor tick. The v2.6 milestone
cannot touch the clean stage's patterns without perturbing re-crawl. **The brief treats these as
independent (L1 vs L2 + open question #5); the code says they are one change.**

Severity assessment — and here the news is good:
- **It is NOT a WORM violation and NOT raw-zone growth.** `put_raw` layer 2 is a registry no-op on
  SHA256 match *before any S3 write* (`s3.py:277-287`). Re-crawled unchanged HTML writes no new raw
  object and creates no new artifact. The raw zone is structurally protected against exactly this.
- **It IS a one-time thundering herd** — 34 full crawls in one tick, with rate-limit and cost
  implications — and it is self-healing (`touch_source_crawl(..., last_content_hash=sig)` at
  `crawl.py:205` stores the new signature; the next tick is quiet).

The genuine, non-self-healing risk is the one the brief intuits: **if crawl-time pruning is
threshold-sensitive or nondeterministic, `_signature` flaps between values → the gate returns
"changed" on every tick, forever → `crawl_source()` runs every tick, forever.** Raw stays clean
(dedup), but bandwidth, rate limits (CRAWL-03 backoff), and cost do not. `PruningContentFilter` is
scoring-threshold-based over dynamically rendered pages — precisely the profile that flaps. Note
the existing `_VOLATILE_PATTERNS` machinery (`crawl.py:76-103`) was built to solve exactly this
class of problem for timestamps/nonces, which is prior evidence the team has already been bitten
here once.

**Recommendation — architectural, and a prerequisite for several other phases:**

**Decouple the change gate from the clean stage's evolving patterns.** The two have opposite
objectives and must not share a mutable list:

| | Objective | Wants patterns to be |
|---|---|---|
| Change gate | Stable re-crawl decisions | **Frozen** |
| Clean stage | Maximum garbage removal | **Aggressive, evolving** |

Give the gate its own frozen `_GATE_NORMALIZE_PATTERNS` (seeded as a copy of today's four patterns),
pinned by a test asserting gate-signature stability across clean-stage changes. Decision D-06's
premise — that gate and clean "agreeing on boilerplate" is desirable — was reasonable when patterns
were static; v2.6 makes them dynamic and inverts the conclusion. **This is a small change that must
land early, because it unblocks pattern work (L2) and any future crawl-extraction work (L1)
without a re-crawl storm.**

If the gate is ever intentionally changed, treat it as a signature-schema bump and accept one
deliberate re-crawl wave — the raw zone is safe (`s3.py:280`); it is a cost event, not a corruption
event.

---

## Q6: Recording What Was Discarded

### Recommendation: metadata counters + the sidecar diff. **No `rejected` artifact type.**

The brief weighs three options against the lineage constraint. The architecture already provides the
answer for free:

**`parsed_sections − cleaned_sections` is the discard record.** `parse()` writes the full section
set to the silver sidecar before any filtering (`parse.py:221-233`); `clean()` writes the survivor
set. Both are durable, content-hashed, and lineage-linked (cleaned parents off parsed —
`clean.py:335`). The discarded set is exactly recoverable by diff, for any document, at any time,
with zero new storage and zero new artifact types.

**Against a `rejected` artifact type:** every artifact must trace to source with a stable ID,
content hash, storage URI and registry row (the core-value constraint). A rejected-section artifact
would mean thousands of tiny S3 objects and registry rows per corpus — for content whose defining
property is that it is worthless. The lineage constraint is a reason **not** to do this: it says
every artifact must be traceable, not that every byte must become an artifact. Cost scales with
garbage volume; value does not.

**For the metric (and this is load-bearing under D-2):** the brief's Notes-for-the-Roadmapper flags
that without a re-runnable audit, "did this work?" has no answer — because forward-only means the
existing 28% stays and dilutes any corpus-wide measurement. **Concur strongly, and it should be a
requirement, not a "candidate."** A quality fix whose success cannot be measured is
indistinguishable from a no-op.

Cheapest sufficient design — extend `clean()`'s existing metadata dict (`clean.py:340-344`, which
already carries `language`, `dedup_status`, `minhash_num_perm`):

```python
metadata={
    "language": language,
    "dedup_status": dedup_status,
    "minhash_num_perm": s.clean.minhash_num_perm,
    # v2.6 additions — the garbage-rate metric, per document:
    "sections_total":   42,
    "sections_dropped": 11,
    "drop_reasons":     {"link_density": 6, "no_terminal_punct": 3, "too_short": 2},
    "filter_config_version": "v1",
}
```

This makes garbage rate a **SQL aggregate over Postgres JSONB** — no corpus scan, no new table, no
new artifact. Add a matching per-chunk `dropped_by_floor` counter at the chunk stage and a
`klake quality-report` command that aggregates both. `filter_config_version` mirrors the existing
`CurateSettings.filter_config_version` convention (`settings.py:309`) and lets you attribute a rate
change to a config change rather than a corpus change — without it the metric is uninterpretable the
first time someone tunes a threshold.

---

## Q7: Plugin Seam

### Recommendation: **NO `FilterPlugin`. Inline pipeline code in `clean.py`, with domain-pack-supplied pattern lists.**

The project's core value is tool-agnosticism, and the instinct to add a seam is the right instinct
to *have* — but applied here it misreads what the seams are for. Every existing seam wraps a
**replaceable external tool** with a competing ecosystem:

| Seam | External tool | Alternatives that exist |
|------|--------------|------------------------|
| `ParserPlugin` | Docling | Unstructured, Tika |
| `CrawlerPlugin` | Crawl4AI | Scrapy, Playwright |
| `VectorStorePlugin` | Qdrant | Milvus, Weaviate |
| `IndexerPlugin`/`RetrieverPlugin` | PageIndex | — |
| `EmbedderPlugin` | sentence-transformers | LiteLLM |

Content filtering has **no external tool to swap.** It is in-house deterministic heuristics over an
in-house `Section` dataclass. The closest analogue is DataTrove, and the project's own precedent is
decisive: **DataTrove is used as a library called directly from `curate.py`
(`curate.py:119`, `curate.py:40`) — it was never given a plugin seam**, despite being an external
tool with real alternatives (NeMo Curator, Dolma). If DataTrove didn't earn a seam, a regex
classifier certainly hasn't.

Each seam has real recurring cost: an entry-point group, resolver wiring, a swap key on `Settings`
with `_validate_swap_key` (`settings.py:698-711`), protocol conformance tests, and a
`runtime_checkable` Protocol to maintain (`protocols.py`). Paying that for code with exactly one
implementation and no candidate second implementation is speculative generality — the seam would
exist to honor a principle rather than to serve a swap.

**Variability here is by domain, not by tool** — healthcare nav bars differ from legal nav bars —
and the project already has a first-class extension point for that: the domain-pack convention.
PROJECT.md's "Domain convention over plugin entry-points" decision is marked ✓ Validated with the
rationale "zero core code changes per new domain pack." `enrich` already loads domain-specific
prompts this way (`assets.py:451-454`, via `DomainLoader.from_name(...).render_prompt("enrich.j2")`).
**Boilerplate patterns should ride the same rail:** core ships generic heuristics; a domain pack
contributes `filters.yaml` (extra patterns, tuned thresholds), loaded by `DomainLoader`. That
delivers the extensibility a seam would, at a fraction of the cost, using a mechanism already
proven in this codebase.

**If a future need for pluggable filtering emerges, the refactor is cheap** — a pure function over
`Section` is trivially wrapped in a Protocol later. Seams are cheap to add and expensive to remove;
add it when there is a second implementation, not before.

---

## Data Flow: Before / After

### Before

```
parse ──▶ ParsedDoc(uncleaned) ─────────────────────────────┬──▶ chunk ▶ embed ▶ index ▶ RAG (33% junk)
   │                                                        ├──▶ tree_index
   │                                                        └──▶ enrich (pays LLM cost on junk)
   └──▶ clean ──▶ cleaned_document ──▶ curate ──▶ pretrain (healthy — the only reader)

klake process:  parse ──▶ chunk ▶ embed ▶ index          (clean never called at all)
```

### After

```
parse ──▶ ParsedDoc(faithful) + sections sidecar [EVIDENCE]
   │
   └──▶ clean (section-aware)
          ├──▶ cleaned_document blob      ──▶ curate ──▶ pretrain
          ├──▶ cleaned sections sidecar   [SURVIVORS]
          ├──▶ metadata: dropped counts   [METRIC]
          └──▶ returns cleaned ParsedDoc ─┬──▶ chunk (+min_tokens) ▶ dedup ▶ embed ▶ index ▶ RAG
                                          ├──▶ tree_index
                                          └──▶ enrich  (junk already gone)

klake process:  parse ──▶ clean ──▶ chunk ▶ dedup ▶ embed ▶ index    (unified with Dagster path)
```

**The structural change in one sentence: `clean` moves from being a leaf to being the fan-out node.**

---

## New vs Modified Components

### New (additive — nothing existing changes behavior)

| Component | Location | Notes |
|-----------|----------|-------|
| Section classifier | `pipeline/clean.py` (new fns) | Pure fns over `Section`; unit-testable in isolation |
| Cleaned sections sidecar | `silver/{d}/{s}/cleaned/{hash}.sections.json` | Mirrors `parse.py:221-233` |
| `load_cleaned_doc()` | `pipeline/clean.py` | Mirrors `load_parsed_doc` (`parse.py:265`) |
| `chunk_text_index` ledger | `registry/models.py` + Alembic | Dedup source of truth |
| `dedup_chunks` stage | `pipeline/dedup.py` + Dagster asset | Between chunk and embed |
| `FilterSettings` | `config/settings.py` | Thresholds + `filter_config_version` |
| `ChunkSettings.min_tokens` | `settings.py:125-143` | Field additive; **non-zero default = behavior change** |
| Quality-report command | `cli/app.py` + `pipeline/` | Aggregates clean metadata |
| Domain `filters.yaml` | `domains/healthcare/` | Via existing `DomainLoader` |
| `_GATE_NORMALIZE_PATTERNS` | `pipeline/crawl.py` | Frozen copy; decouples gate |

### Modified (existing behavior changes — each needs a test-impact review)

| Component | file:line | Change | Risk |
|-----------|-----------|--------|------|
| `clean()` | `clean.py:170-361` | Section-aware; returns cleaned `ParsedDoc`; new sidecar + metadata | Content hash changes → new artifacts (forward-only, OK) |
| `clean()` exact-dup return | `clean.py:305-320` | Early-return path must also return a cleaned ParsedDoc | **Easy to miss — returns before the write block** |
| `clean_document` asset | `assets.py:318-328` | Forward the *cleaned* doc | The headline fix |
| `process_crawled` | `process.py:103-112` | **Insert the clean stage** | **The fix the brief omits** |
| `chunk()` | `chunk.py:290-296` | Apply `min_tokens`; table carve-out | Fewer chunks; Phase-3 tests |
| `chunk()` metadata | `chunk.py:361-365` | Add `cleaned_artifact_id` / hash | Additive within a modified call |
| `BOILERPLATE_PATTERNS` | `clean.py:46-60` | Extend | **Perturbs change gate until decoupled** |
| `_signature()` | `crawl.py:106-118` | Use frozen gate patterns | Must land before pattern work |
| `index()` | `index.py:210-245` | UUIDv5 point IDs; `text_hash`/`occurrence_count` payload | Mixed ID schemes in collection |
| `export_rag_corpus()` | `export.py:280-345` | Quality gate before row build | `_RAG_CORPUS_FIELDS` allow-list (`export.py:65`) |
| `core_pipeline_e2e_job` | `assets.py:994-1013` | Add `dedup_chunks` to selection | **See anti-pattern 1 — deps silently drop** |

### Explicitly NOT changed

- `Section` / `ParsedDoc` dataclasses (`protocols.py:34-79`) — filtering needs no new fields
- Chunk parentage + WR-05 key (`chunk.py:317`, `chunk.py:354`) — Q1
- Two-hop lineage walkers (`repo.py:839-903`)
- Contamination gate (`export.py:106`)
- Raw zone, `put_raw` (`s3.py:222+`) — Q5
- Any plugin Protocol — Q7

---

## Lineage / WR-05 Impact Analysis

| Proposal | Touches parentage? | Impact |
|----------|-------------------|--------|
| clean returns cleaned ParsedDoc | No | Data-only. Chunk parent unchanged. **WR-05 intact.** |
| Cleaned sections sidecar | No | Sidecar is metadata on an existing artifact (as `sections_uri`, `parse.py:246`) |
| Section drop at clean | No | New cleaned content hash → new cleaned artifact, still `parent = parsed` (`clean.py:335`) |
| Chunk `min_tokens` | No | Fewer chunk artifacts; each still parents to parsed |
| Chunk metadata `cleaned_artifact_id` | No | Records the transform without an edge |
| **Chunk → cleaned re-parent** | **YES** | **REJECTED** — breaks `repo.py:839-903`, `index.py:191`, `export.py:301`, contamination gate `export.py:113-119`, `index.py:271-284`; and `clean.py:305-320` makes cleaned artifacts cross-source-shared |
| Index dedup ledger | No | Ledger is a lookup table, not an artifact. Chunk artifacts remain 1:1 per document. **This is exactly what D-3 protects.** |
| UUIDv5 point IDs | No | Qdrant point ≠ artifact. Payload `chunk_id` still resolves to the registry |
| Export quality gate | No | Read-side filter |
| Crawl-time pruning (if pursued) | No | Bronze only; raw untouched (`crawl.py:879-884`) |

**Summary: the recommended design touches no artifact parentage anywhere.** Every lineage edge in
the registry today survives v2.6 unchanged. That is not a coincidence — it is the constraint that
drove option (b) over (c), data-forwarding over re-parenting, and a ledger over many-to-many chunk
artifacts.

---

## Anti-Patterns (specific to this retrofit)

### 1. Adding an asset without adding it to the job selection

`assets.py:975-985` documents this in blood: `curate_document_asset` was left out of
`core_pipeline_e2e_job`, and **Dagster silently drops a `deps=` edge whose target is outside the
selection** — resurrecting the exact KL-06 scheduling race the deps edge existed to close, in the
main E2E job. `test_asset_ordering.py` pins the selection.
**Do this instead:** when `dedup_chunks` lands, add it to the selection (`assets.py:994-1013`) *in
the same commit* and extend the ordering test.

### 2. Deleting tables with prose-shaped heuristics

Link density, terminal punctuation and stop-word ratio all mark a legitimate table as garbage. The
codebase already carves tables out (`chunk.py:230-240`, CHUNK-03; `Section.is_table`,
`protocols.py:55`).
**Do this instead:** exempt `is_table` from every prose heuristic, and pin it with a test using a
real table fixture. This is the most likely catastrophic regression in the milestone.

### 3. Renumbering `section_path` after dropping sections

Shifts every citation; makes paths threshold-dependent; corrupts existing Qdrant payloads' meaning.
**Do this instead:** keep original paths. Gaps are correct and are themselves evidence.

### 4. Deduping inside `chunk()`

Directly violates D-3 and WR-05 (`chunk.py:315-316`); makes chunk artifacts many-to-many.
**Do this instead:** dedup between chunk and embed, against a ledger.

### 5. In-memory-only dedup

Catches intra-document repeats only; the 653 duplicates are cross-document. Will pass its tests and
move the metric ~2%.
**Do this instead:** durable `text_hash` ledger.

### 6. Changing `BOILERPLATE_PATTERNS` while the change gate imports it

`crawl.py:115` → 34 sources re-crawl. Recoverable, but avoidable.
**Do this instead:** decouple the gate first (small, early phase).

### 7. Writing pruned content to raw

Destroys D-2's own escape hatch and the source-fidelity/licensing property. Irreversible.
**Do this instead:** raw = capture, bronze/silver = transformation.

### 8. Fixing only the Dagster asset

`klake process` never calls `clean()` (`process.py:103-112`). Fixing `assets.py:325` alone leaves
the audited command producing 28% garbage.
**Do this instead:** fix both call paths in the same phase, or the metric will not move.

---

## Suggested Build Order

Sequenced by hard dependency, not by layer number. The brief's L0–L5 is a taxonomy of causes, not a
build order.

### Phase 17 — Close the bypass (both paths) + measurement hooks
**Depends on:** nothing. **Blocks:** everything.
- `clean()` loads sections via `load_parsed_doc()` → `reparse_from_raw()` fallback (`parse.py:265`,
  `parse.py:325`); applies today's existing `remove_boilerplate` per section; writes the cleaned
  sections sidecar; **returns the cleaned `ParsedDoc`**. Handle the exact-dup early return
  (`clean.py:305-320`).
- `clean_document` forwards the cleaned doc (`assets.py:325`).
- **`process_crawled` calls `clean()`** (`process.py:103-112`).
- Emit `sections_total` / `sections_dropped` metadata + `klake quality-report`.

**Why first:** it is the only change that is a prerequisite for every other one — with the bypass
open, no filter can be observed to work. **Deliberately ships with the existing weak patterns:** this
phase proves the *plumbing* end-to-end and establishes the baseline metric while changing filter
*policy* as little as possible. Two variables, two phases.

### Phase 18 — Decouple the SCHED-02 change gate
**Depends on:** nothing. **Blocks:** 19 and 22.
- Frozen `_GATE_NORMALIZE_PATTERNS` in `crawl.py`; `_signature` (`crawl.py:115`) stops importing the
  clean stage's mutable list. Test pins gate-signature stability against clean-stage changes.

**Why here:** small, isolated, and a hard prerequisite for touching `BOILERPLATE_PATTERNS` (19) or
crawl extraction (22). Doing it before 19 turns a 34-source re-crawl storm into a non-event. Could
merge into 17 if the roadmapper prefers fewer phases — it is genuinely small — but it is
independently verifiable and blocks two later phases, which argues for its own slot.

### Phase 19 — Section classifier + extended patterns
**Depends on:** 17 (needs the cleaned path), 18 (needs gate decoupled). **Blocks:** 21.
- Deterministic section-level heuristics (link density, terminal punct, stop-word ratio, token
  floor) + extended patterns; **tables exempt**; domain-pack `filters.yaml` via `DomainLoader`.
- Extend, don't replace, the 4 existing patterns (Phase-3 tests).

**Why here:** the highest-yield policy change, and now measurable against 17's baseline. This is the
phase that should move 28% → single digits.

### Phase 20 — Chunk min-substance floor + gold export quality gate
**Depends on:** 17. **Independent of** 19 (can run parallel).
- `ChunkSettings.min_tokens` (`settings.py:125-143`); table carve-out.
- Quality gate in `export_rag_corpus` (`export.py:280-345`), mirroring
  `min_quality_score_for_pretrain` (`settings.py:360`).

**Why here:** both are small, read-side/backstop changes with thresholds best tuned against 17's
metric. Grouped because they are the same *kind* of change (a threshold on an existing path).

### Phase 21 — Index-time dedup
**Depends on:** 19 (design against the residual). **Blocks:** nothing.
- `chunk_text_index` ledger + migration; `dedup_chunks` asset between chunk and embed; UUIDv5 point
  IDs; `text_hash`/`occurrence_count` payload; **add to `core_pipeline_e2e_job` selection**.

**Why after 19, not before:** most of the 653 duplicates are boilerplate that 19 removes at source.
Building dedup first means designing for a mass that is about to disappear. Measure the residual
after 19, then size this. **If the residual is small, this phase may be descoped entirely** — worth
stating as an explicit decision point rather than a foregone conclusion.

### Phase 22 — Crawler-level extraction — RECONSIDER SCOPE
**Depends on:** 18, and on 19's metric. **Blocks:** nothing.
- **Before building: verify it is not a no-op.** As plumbed, `fit_markdown` changes only bronze
  (dead-end) and the change gate. Real value requires making `parse()` consume bronze for HTML
  sources — a much larger change.
- If pursued: pruned → **bronze only**; raw stays full-fidelity HTML; verify signature stability
  across repeated probes of a dynamic page before enabling.

**Why last, and why flagged:** highest blast radius, permanent-loss risk if raw is touched, and its
benefit is a *subset* of 19's — which covers PDF/CSV/upload too, not just crawled HTML. The
recommendation is to **defer or drop D-1's crawler-extraction item** unless 19's metric proves
crawl-shaped garbage survives. This contradicts a confirmed scope decision and should be surfaced
for an explicit re-decision rather than inherited.

### Dependency graph

```
17 (bypass, both paths + metric) ──┬──▶ 19 (classifier) ──▶ 21 (dedup)
                                   │        ▲
18 (gate decouple) ────────────────┼────────┘
     │                             │
     │                             └──▶ 20 (floor + export gate)
     └────────────────────────────────▶ 22 (crawler — reconsider)
```

**Critical path: 17 → 19.** Everything else is a leaf or parallelizable.

---

## Integration Points

| Boundary | Communication | Considerations |
|----------|--------------|----------------|
| `parse` → `clean` | S3 sections sidecar + `metadata_["sections_uri"]` (`parse.py:246`) | Already exists; `load_parsed_doc` (`parse.py:265`) with `reparse_from_raw` (`parse.py:325`) fallback |
| `clean` → chunk/tree/enrich | In-memory `ParsedDoc` via Dagster dict (`assets.py:325`) | **The fix.** Never via S3 (`clean.py:305-320` cross-source dedup) |
| `clean` → `curate` | S3 blob (`curate.py:144`) | Contract unchanged; content improves |
| `chunk` → `dedup` → `embed` | In-process list of dicts (`embed.py:44`) | New stage; no IO manager (Pitfall 7, `assets.py:37-39`) |
| `dedup` ↔ Postgres | `chunk_text_index` ledger | New table + Alembic migration |
| `index` → Qdrant | `VectorPoint` (`protocols.py:82`) | Payload shape preserved; point-ID derivation changes |
| `crawl` gate → `clean` | **`remove_boilerplate` import (`crawl.py:40`, `crawl.py:115`)** | **Sever this** |
| `crawl` → raw/bronze | `_write_artifacts` (`crawl.py:858-907`) | raw=HTML, bronze=markdown(dead) |
| domain pack → `clean` | `DomainLoader` (`assets.py:451-454`) | Reuse the enrich.j2 rail for `filters.yaml` |

### External services

| Service | Integration | Gotchas |
|---------|------------|---------|
| Crawl4AI | `CrawlerRunConfig` (`crawl4ai_adapter.py:107-110`) | `fit_markdown` affects `.markdown` only, not `.html`; threshold-sensitive → gate flap |
| Qdrant | `VectorStorePlugin` (`protocols.py:212`) | UUIDv5 IDs give free idempotent dedup; mixed ID schemes under D-2 |
| DataTrove | Direct library call (`curate.py:119`) | **Precedent: no plugin seam** (Q7) |
| LiteLLM | Task aliases only | Filtering must be deterministic — no per-chunk LLM (binding constraint) |
| Postgres | SQLAlchemy + Alembic | Metric as JSONB aggregate; ledger as a table |

---

## Confidence

| Area | Confidence | Basis |
|------|-----------|-------|
| Bypass mechanics (both) | **HIGH** | Read directly; `clean()` call sites exhaustively grepped |
| Bronze is a dead end | **HIGH** | Grepped all consumers; `process.py:78` selects `raw_document` |
| Re-parenting breaks 5 things | **HIGH** | Each traced to file:line |
| Gate ↔ clean coupling | **HIGH** | `crawl.py:40`, `crawl.py:115` |
| Raw safe from re-crawl storms | **HIGH** | `s3.py:277-287` no-op before write |
| Dedup is cross-document | **HIGH** | Per-document call graph verified end to end |
| `fit_markdown` is a no-op for RAG | **MEDIUM-HIGH** | Follows from verified plumbing; not empirically run |
| Section heuristics will hit ~28% | **MEDIUM** | Heuristic choice is empirical — hence metric-first sequencing |
| Threshold values (min_tokens, link density) | **LOW** | Must be tuned against the Phase-17 metric; do not hard-code from the audit |

---

## Sources

- Primary: the codebase, read at the cited file:line. Confidence HIGH — this is the authoritative
  source for existing behavior, and every claim above was verified rather than inferred from
  documentation.
- `.planning/PROJECT.md` — constraints, key decisions, plugin/domain precedents.
- `.planning/MILESTONE-CONTEXT.md` — D-1..D-4 scope decisions, audit evidence.
- Existing in-code decision records: WR-05 (`chunk.py:315-316`), KL-04/05/06 (`assets.py:23-35`,
  `index.py:11-30`), D-06/SCHED-02/T-11-THRASH (`crawl.py:67-75`), Pattern 1 / FOUND-04
  (`s3.py:232-250`), Task 8 / KL-09 (`parse.py:9-21`).

---
*Architecture research for: retrofitting content-quality filtering into a shipped lineage-tracked pipeline*
*Researched: 2026-07-15*
