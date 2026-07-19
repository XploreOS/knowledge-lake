# Stack Research — v2.7 Additions (Governed Dataset Production and Release Lifecycle)

**Domain:** DatasetOps control plane additions — CurationEngine formalization, Croissant metadata, dataset cards, reproducibility manifests, group-aware splits, benchmark contamination
**Researched:** 2026-07-19
**Confidence:** HIGH on version numbers (live PyPI/GitHub verification); MEDIUM-HIGH on API/architecture details (GitHub source + release-notes review); design recommendations are original synthesis grounded in this repo's own documented conventions (curate.py anti-pattern notes, Phase 21 dedup-ledger precedent, T-05-08 allow-list discipline)

**Scope note:** This file covers ONLY the six areas in the v2.7 research question. It does not re-litigate any already-validated v1.0–v2.6 stack choice (Dagster, Docling, Crawl4AI/Scrapy, Qdrant, MinIO/boto3, PostgreSQL/SQLAlchemy/Alembic, FastAPI/Typer/MCP, LiteLLM, DataTrove's 3 filter classes, datasketch, Polars/DuckDB/PyArrow) — those stay exactly as pinned.

## Headline Answer

**Zero new runtime dependencies are required for 5 of 6 capabilities.** Only Croissant metadata benefits from a new package, and even there the recommendation is a **dev-only** dependency, not a production one. Everything else is achievable with what's already pinned (`datatrove==0.9.0`, `datasketch==2.0.0`, `sentence-transformers==5.6.0`, `jinja2`, `pyyaml`, `orjson`, `xxhash`, `hashlib`/`importlib.metadata`/`subprocess` from stdlib).

| # | Capability | New runtime dependency? | Recommendation |
|---|---|---|---|
| 1 | CurationEngine + DataTrove backend | No — same pin (`datatrove==0.9.0`) | Adopt `LocalPipelineExecutor` + native readers/writers/checkpointing; do NOT install `datatrove[s3]` or `datatrove[ray]` |
| 2 | Croissant metadata | Dev-only (`mlcroissant==1.1.0`) | Hand-emit `croissant.json` via Pydantic + orjson; use `mlcroissant validate` in CI only |
| 3 | Dataset card | No | Jinja2 template, same pattern as `enrich.j2`/`qa_generation.j2` |
| 4 | Reproducibility manifest | No | Pure application logic on existing hashing/serialization libs |
| 5 | Group-aware split | No | Hand-rolled deterministic hash-bucket split (stdlib `hashlib`) |
| 6 | Benchmark contamination | No | Tiered: n-gram (stdlib) → MinHash (`datasketch`, already pinned) → embedding (`sentence-transformers`, already pinned) |

---

## 1. CurationEngine + DataTrove backend

### What DataTrove's real API looks like (verified via PyPI + GitHub source, 2026-07-19)

**Version:** `datatrove==0.9.0`, released 2026-03-04 (PyPI — matches the version and date already recorded in this repo's CLAUDE.md). No `0.9.1` or `0.10.0` has shipped since; 0.9.0 is confirmed the current latest release as of today. **Upgrading is not warranted** — there is nothing newer to upgrade to.

**Execution layer** (`datatrove.executor`):
- `LocalPipelineExecutor` — multiprocessing on a single machine; `workers=N` runs N tasks concurrently (one per core). This is the only executor relevant to this repo's single-Dagster-host deployment.
- `SlurmPipelineExecutor` — HPC cluster via `sbatch` job arrays. Not applicable (no Slurm in this stack).
- `RayPipelineExecutor` — distributed Ray cluster; requires the `ray` extra (`ray[default]`). **Not warranted for v2.7** — the flagship dataset is dozens-to-low-hundreds of examples and the existing corpus is a few thousand chunks; there is no scale problem Ray would solve here, and it would introduce a second orchestration/scheduling system alongside Dagster. Flag as future-only if corpus scale grows by 2+ orders of magnitude.

**Readers/Writers** (`datatrove.pipeline.readers` / `datatrove.pipeline.writers`):
- Readers yield `datatrove.data.Document` objects; writers extend a common `DiskWriter` base (`JsonlWriter`, `ParquetWriter`, etc.) with `output_folder`, `output_filename` (supports `${rank}` templating), `compression`, `adapter` (custom Document → output-dict mapping), `max_file_size`.
- Storage backend is `DataFolder`, which wraps `fsspec` — this is how DataTrove supports local, S3, GCS, Azure, and HF Hub paths transparently. **S3 access requires the `s3` extra** (`pip install datatrove[s3]`, pulls in `s3fs`).

**Accepted/rejected writers — the actual mechanism (this directly answers the "formal CurationEngine" design question):**
- Every `BaseFilter` subclass (including the 3 already used — `GopherRepetitionFilter`, `GopherQualityFilter`, `C4QualityFilter`) accepts an `exclusion_writer` constructor parameter: "optionally pass in a writer that will save the dropped documents." When a filter's `.run()` (not `.filter()`) drops a document, it writes that document to the exclusion writer with the rejection reason stamped into its metadata, and updates the block's own `PipelineStats` (`stat_update(StatHints.dropped)`).
- **This is exactly the accepted/rejected writer machinery CurationEngine needs** — but note the important tension below.

**Checkpointing/resume — the actual mechanism:**
- File-based markers: on successful completion of a task (a shard, one process's slice of work), the executor writes an empty file to `completions/{rank:05d}` and per-task stats to `stats/{rank:05d}.json`.
- On relaunch, `is_rank_completed(rank)` checks for the marker; if present, that shard's entire pipeline (reader → filters → writer) is skipped entirely — no partial re-processing within a shard, but no re-doing of already-finished shards either. `skip_completed=True` by default.
- This is genuine resumability, distinct from and complementary to Dagster's own retry semantics: **Dagster's `RetryPolicy` retries a whole asset** (e.g., re-run `curate_all_documents` from scratch); **DataTrove's checkpoint machinery resumes a large multi-shard curation run mid-way**, skipping shards that already finished. Use both — Dagster wraps the asset, DataTrove's executor handles shard-level resumability inside it.

### The critical integration tension with `pipeline/curate.py`

`curate.py`'s own docstring documents an anti-pattern-avoidance decision: **CURATE-01 calls each filter's `.filter(doc)` method directly in a loop, never `.run()`**, specifically so that *every* configured filter is scored regardless of whether an earlier one already failed (today's `score_document()` returns a dict with one entry per filter, all three always attempted).

DataTrove's native `.run()` — the method that actually feeds a `PipelineExecutor` block list — does the opposite by design: in a `[reader, filter1, filter2, filter3, writer]` pipeline, a document dropped by `filter1` never reaches `filter2` or `filter3`. Chaining the three existing filters as three separate pipeline steps would **lose the multi-reason recording** CURATE-01 and the composite-quality-score (CURATE-03) depend on.

**Recommended CurationEngine design for the DataTrove backend:** keep a single custom pipeline block — a thin `PipelineStep` wrapper around today's `score_document()` logic — as the *only* filter step in the DataTrove pipeline list. This block calls all three filters via `.filter()` internally (exactly as today), builds the composite score, and itself decides accept/reject; only this wrapper's accept/reject decision goes through `exclusion_writer`. This preserves CURATE-01/03 behavior exactly while gaining DataTrove's native checkpointing, sharding, and accepted/rejected writer plumbing — the `CurationEngine.execute()` contract (prepare/execute/collect) maps naturally onto "build reader + composite-filter-block + accepted/rejected writers" → `LocalPipelineExecutor(pipeline=[...]).run()` → collect `PipelineStats`.

### S3 and the FOUND-03 single-client invariant

`curate.py`'s docstring already documents a deliberate anti-pattern-avoidance: DataTrove's disk-based reader/writer/executor scaffolding is not used today specifically to preserve "the FOUND-03 single S3 client invariant... never introduces a second S3 client path via fsspec/s3fs." Formalizing `LocalPipelineExecutor` for v2.7 should **preserve this invariant, not abandon it**:

- **Do NOT install `datatrove[s3]`.** Running `DataFolder` directly against the MinIO/S3 bucket would give DataTrove its own `fsspec`+`s3fs` client, a second S3 code path alongside the existing `StorageBackend` (boto3).
- **Recommended pattern:** stage in/out explicitly. Before running the executor, pull the relevant `cleaned_document` texts from S3 via the existing `StorageBackend` into a local scratch directory (ephemeral, cleaned up after the run — this is working-set data, not a data-lake zone, so it does not implicate the "no local filesystem as production store" constraint any more than `tempfile`-based LLM/embedding batching would). Point `LocalPipelineExecutor`'s reader/writer at that local scratch path. After the run, read the writer's accepted/rejected NDJSON output and re-upload through the existing `StorageBackend` to the silver/gold zone, same as every other pipeline stage does today.
- This keeps DataTrove's checkpoint/writer machinery genuinely useful (resumability across a long local batch job) without adding a second S3 client.

### Verdict

**Sufficient at 0.9.0** — no version bump needed or available. No new dependency. The work is entirely architectural: wrap the existing filter-scoring logic as a single DataTrove pipeline block, drive it through `LocalPipelineExecutor` for native checkpointing/sharding/exclusion-writer behavior, and keep all I/O staged through the existing `StorageBackend` rather than DataTrove's fsspec/S3 extra.

---

## 2. Croissant metadata (MLCommons dataset format)

**Package:** `mlcroissant`
**Latest version:** `1.1.0`, released 2026-04-16 (verified via PyPI). Requires Python `>=3.10` — compatible with this repo's `>=3.12` floor.
**Maturity:** Actively maintained by MLCommons + Google contributors; this is the reference implementation of the Croissant JSON-LD spec (`dct:conformsTo: http://mlcommons.org/croissant/1.0`), used by Hugging Face, Kaggle, and OpenML for auto-generated dataset metadata. Not a fringe tool.

### Dependency footprint — checked against this repo's actual resolved lock file

`mlcroissant`'s declared runtime deps: `absl-py`, `etils[epath]>=1.7.0`, `jinja2`, `jsonpath-rw`, `networkx`, `pandas`, `pandas-stubs`, `python-dateutil`, `rdflib`, `requests`, `scipy`, `tqdm` (fetched from the package's own `pyproject.toml`).

Cross-checked against `uv.lock` in this repo: **`networkx` (3.6.1, via `torch`), `pandas` (3.0.3, via `docling-core`), `scipy` (1.18.0, via `sentence-transformers`→`scikit-learn`), `python-dateutil`, `requests`, and `tqdm` are already transitively resolved today** — they cost nothing new. The genuinely new packages would be `absl-py`, `etils`, `jsonpath-rw`, and `rdflib` (the heaviest of the four, but a mature, stable, pure-Python RDF library — not a GPU/ML dependency).

### Does it support production (emission), not just validation?

Yes — both directions exist: `mlc.nodes.Metadata(...)`, `mlc.nodes.FileObject(...)`, `mlc.nodes.RecordSet(...)`, `mlc.nodes.Field(...)` can be constructed programmatically and serialized with `.to_json()`. The CLI also ships `mlcroissant validate --jsonld <file>` (exit code 0/1, prints warnings) for conformance checking of any manifest, hand-written or library-generated.

### Recommendation: hand-emit, validate via dev-only dependency

Given the footprint (4 new packages, one of them moderately heavy) and this repo's demonstrated convention of using a mature tool's *validation/verification surface* rather than adopting its full object model in production code (the exact same reasoning `curate.py` already documents for DataTrove's own writer scaffolding), the recommended split is:

- **Production code:** hand-emit `croissant.json` as a small set of Pydantic models (`CroissantDataset`, `CroissantFileObject`, `CroissantRecordSet`, `CroissantField`) serialized via the already-pinned `orjson`. The Croissant `@context` block is a fixed, spec-versioned constant (documented in the spec, effectively boilerplate) — this is not free-form JSON-LD authoring, it's filling in a known template, which is exactly what the existing `_RAG_CORPUS_FIELDS` explicit-allow-list discipline (T-05-08) already does for RAG-corpus rows. Zero new runtime dependency.
- **Dev/test only:** add `mlcroissant==1.1.0` to `[dependency-groups] dev` (never imported by application code) and add a CI test that shells out to `mlcroissant validate --jsonld <generated-manifest-fixture>` to prove every hand-emitted manifest is spec-conformant. This gets the correctness guarantee of the reference implementation without adding `rdflib`/`absl-py`/`etils`/`jsonpath-rw` to what an operator running `pip install knowledge-lake` actually pulls down.

**Alternative considered and rejected for now:** use `mlcroissant` directly in production for emission. This is a legitimate, lower-long-term-maintenance option (if the Croissant spec evolves past 1.0, the library upgrades for you; a hand-rolled emitter has to track spec changes manually) — but it conflicts with this repo's minimal-footprint convention today. Revisit if the hand-rolled emitter proves brittle across a future Croissant spec bump.

---

## 3. Dataset card generation

No new dependency. Follow the exact pattern already proven at two call sites in this repo — `domains/{name}/prompts/enrich.j2` and `domains/{name}/prompts/qa_generation.j2` — using the already-pinned `jinja2>=3.1,<4`.

Recommended content structure (structure to *borrow*, not a library to adopt):
- **Hugging Face Dataset Card conventions** for the shape of a YAML frontmatter block (`license`, `task_categories`, `language`, `pretty_name`, `size_categories`) followed by prose sections — this is a widely-recognized convention even though this project does not push to the HF Hub.
- **Datasheets for Datasets** (Gebru et al.) question set for the prose body: motivation, composition, collection process, preprocessing/cleaning/labeling, uses, distribution, maintenance — a good fit for the "release manifest" bundle since it directly answers governance/provenance questions the milestone already requires (source usage-policy, quality contract outcomes, lineage).

A single `templates/dataset_card.md.j2` rendered from the same context dict already assembled for the reproducibility manifest (dataset spec, quality-contract summary, split stats, license/policy decisions, lineage counts) keeps this a pure templating exercise, not a new subsystem.

**Alternative considered and rejected:** `huggingface_hub`'s `DatasetCard` / `DatasetCardData` / `.from_template()`. Its dependency footprint is genuinely light (`requests`, `filelock`, `packaging`, `pyyaml`, `tqdm`, `typing-extensions`, `fsspec` — most already present transitively), so this is not a footprint objection. It's rejected because its primary value-add — YAML-frontmatter tag validation against the Hub's controlled vocabularies and `push_to_hub()` — is irrelevant to a project that does not publish to the HF Hub, and the existing Jinja2 pattern is strictly simpler and already proven twice in this codebase. Revisit only if a future milestone adds an explicit "publish to Hugging Face Hub" export target.

---

## 4. Reproducibility manifest / content-hash determinism

**Pure application logic — no new dependency.** This is squarely in the pattern this codebase already uses everywhere (`_curation_cache_key`, `_dataset_gen_cache_key`, WR-05 chunk hashing): a `reproduce.yaml` manifest is just a deterministic function of already-available inputs, serialized with already-pinned libraries:

| Need | Already-pinned tool |
|---|---|
| Content hashing (source snapshots, config versions) | `xxhash` (existing fast-hash use), `hashlib.sha256` (existing synthetic cache-key pattern) |
| Structured manifest serialization | `pyyaml` (already pinned, `>=6.0,<7`) for `reproduce.yaml`; `orjson` for any JSON sibling |
| Installed-version snapshot at release time | stdlib `importlib.metadata.version("datatrove")` etc. — zero new dependency, in stdlib since Python 3.8 |
| Git commit pinning | stdlib `subprocess.run(["git", "rev-parse", "HEAD"])` — avoid adding `GitPython` for one command |

The manifest should capture: dataset-spec hash, per-source content hashes/snapshot timestamps, `filter_config_version`/`prompt_version` (both already exist as cache-invalidation keys in `curate.py`/`datasets.py`), split-seed + split ratios, pinned dependency versions actually resolved at build time (via `importlib.metadata`, not just the `pyproject.toml` declared range — this is what makes the manifest useful for the milestone's "rebuild-equivalence test"), and the git commit SHA. No library does this "for you" in a way that would be worth the dependency — it is inherently project-specific bookkeeping.

---

## 5. Deterministic, group-aware dataset splitting

### The dependency-cost argument is weaker than it first appears

`scikit-learn` (currently `1.9.0` on PyPI, verified) is **already fully resolved in this repo's `uv.lock`** — it comes in transitively via `sentence-transformers → scikit-learn`. Adding a direct pin costs **zero net new install weight**. So this is not primarily a "new dependency" decision.

### But the algorithm-fit argument favors hand-rolling anyway

`GroupShuffleSplit` is built for repeated randomized resampling (its intended use case is cross-validation: many different random re-splits of the *same, fixed* group set). Its actual mechanism shuffles the full array of unique groups and partitions the shuffled array by target size. That means: **the split assignment is a function of the entire group list's shuffled order, not of any single group in isolation.** Add one new source/document group to the corpus for the next dataset release, and the entire downstream split assignment can shift — including for groups that were already released as "train" in a previous, immutable release. That directly conflicts with the milestone's "versioned... group-aware train/validation/test splits" requirement, where a release's split assignments need to stay stable as the corpus grows across releases (unless a full re-split is deliberately intended).

**Recommendation: hand-roll a deterministic hash-bucket splitter.** This is not a novel pattern for this codebase — it is the *exact same technique* already validated and shipped in Phase 21's `chunk_dedup_ledger` (`uuid5(NAMESPACE, sha256(normalize_for_dedup(text)))` — a deterministic hash-bucket used for stable point-ID assignment). Applied to splitting:

```python
bucket = int(hashlib.sha256(f"{group_id}:{split_seed}".encode()).hexdigest(), 16) % 100
# then range-partition: e.g. bucket < 80 -> train, 80 <= bucket < 90 -> val, else -> test
```

This is a pure function of `(group_id, split_seed)` — adding new groups never reassigns existing ones, it is trivially reproducible from the manifest (`split_seed` + ratios are all the reproducibility manifest needs to capture, not a stored RNG state or shuffle order), and it needs zero new dependency (stdlib `hashlib`).

**If the team prefers the canonical `sklearn` API anyway** (e.g., because the flagship dataset's corpus is intentionally frozen before every split, never grown incrementally) — that's a legitimate, zero-additional-install-cost alternative; just pin `scikit-learn` directly rather than relying on an unpinned transitive dependency, since a future `sentence-transformers` release could drop its own `scikit-learn` dependency and silently break an implicit reliance on it.

**No new dependency either way.**

---

## 6. Benchmark contamination detection

Given the corpus scale stated in the milestone (dozens to low-hundreds of examples for the flagship dataset), the practical answer is a **tiered approach using only already-pinned libraries** — no new dependency.

### What NOT to reach for at this scale

DataTrove itself ships a `decont` extra (`pip install datatrove[decont]`) that pulls in Hugging Face's `lighteval` — a full LLM-evaluation-harness library — to build a 13-gram Bloom filter from benchmark sets and drop any document with 10+ consecutive matching n-grams (the FineWeb/GPT-3-style methodology, designed for filtering *trillion-token pretraining corpora* against benchmark leakage at scale). This is the same category of mismatch already documented in this repo's own stack rationale for rejecting NeMo Curator (GPU-cluster-first tooling applied to a workload two orders of magnitude below the scale it was built for). **Do not add `datatrove[decont]`/`lighteval`** for a dozens-to-hundreds-example flagship dataset — the Bloom-filter machinery buys nothing a plain Python set-overlap check doesn't already give you at this scale, at a fraction of the dependency cost.

### Recommended tiered MVP (all reuse already-pinned libraries)

1. **Tier 1 — n-gram overlap (mandatory, cheapest).** Word n-gram (e.g. 8–13-gram, matching the same GPT-3/FineWeb methodology DataTrove's `decont` extra encodes, minus the Bloom filter) Jaccard/overlap check between each candidate example and the benchmark/eval set, implemented with stdlib `itertools` + `set` operations. Catches verbatim/near-verbatim copy-paste contamination. Zero dependency, trivially fast at this corpus size (no need for approximate structures like Bloom filters, which only pay off at corpus sizes several orders of magnitude larger).
2. **Tier 2 — MinHash near-dup (reuse existing pattern).** `datasketch==2.0.0` is already pinned and already used for exactly this kind of fuzzy-duplicate detection in `curate.py`'s `batch_dedup_corpus()` (`MinHashLSH` + `compute_minhash()`). Insert the benchmark/eval set's MinHashes into the same kind of LSH index and query each flagship candidate against it — this is a direct extension of an already-shipped, already-tested pattern, not a new capability.
3. **Tier 3 — embedding cosine-similarity (optional, cheap at this scale).** `sentence-transformers==5.6.0` is already pinned (local embedder) and already wired behind the `EmbedderPlugin` protocol. Embedding a few hundred examples and computing cosine similarity against a benchmark set to catch paraphrased/semantic-level contamination the first two tiers miss is inexpensive at this scale (a few hundred embedding calls, no LLM cost) — worth including in the MVP rather than deferring, since the marginal cost is near-zero and the existing plugin already does the embedding work for indexing.

This tiered design also composes naturally with `export.py`'s existing `check_train_eval_contamination()` — that function's near-dup-flag-based logic (from `batch_dedup_corpus()`) is effectively Tier 2 already applied to *internal* train/eval overlap; extending it to check against an *external* benchmark set (not just the internal corpus) is the natural v2.7 generalization the milestone calls for, replacing the payload-shape-sniffing heuristic with a real n-gram/MinHash/embedding-backed gate.

---

## Installation

No changes to production dependencies in `pyproject.toml`'s `dependencies = [...]` list — `datatrove==0.9.0`, `datasketch==2.0.0`, `sentence-transformers==5.6.0`, `jinja2>=3.1,<4`, `pyyaml>=6.0,<7`, `orjson==3.11.9`, `xxhash==3.8.1` are all already present and sufficient.

```toml
# pyproject.toml — the only change: add to the dev-only dependency group,
# never imported by src/knowledge_lake/** application code.
[dependency-groups]
dev = [
    "mypy>=1.11",
    "pytest>=8.0",
    "pytest-asyncio>=0.24",
    "pytest-cov>=5.0",
    "ruff>=0.6",
    "hypothesis>=6.100",
    "mlcroissant==1.1.0",  # NEW — dev-only, used solely by a CI conformance test
                           # that shells out to `mlcroissant validate`. Never
                           # imported by production code (see Section 2).
]
```

If, after implementation, the team decides to emit Croissant manifests directly via `mlcroissant`'s node API instead of hand-rolling (see Section 2 alternative), move the pin to `dependencies` and expect `absl-py`, `etils[epath]>=1.7.0`, `jsonpath-rw`, and `rdflib` to appear as genuinely new entries in `uv.lock` (the rest of `mlcroissant`'s declared deps — `pandas`, `scipy`, `networkx`, `python-dateutil`, `requests`, `tqdm` — are already resolved transitively today and would not grow the lock file further).

## Alternatives Considered

| Category | Recommended | Alternative | Why Not (for v2.7) |
|----------|-------------|-------------|---------------------|
| Curation execution | `LocalPipelineExecutor` | `RayPipelineExecutor` (`datatrove[ray]`) | No scale problem at dozens-hundreds/few-thousand-item corpus; would add a second distributed-execution system alongside Dagster |
| Curation storage I/O | Existing `StorageBackend` (boto3) + local scratch dir | `datatrove[s3]` (fsspec/s3fs) | Second S3 client path — violates the FOUND-03 invariant `curate.py` already documents as deliberately avoided |
| Croissant emission | Hand-rolled Pydantic + orjson, `mlcroissant` as dev-only validator | `mlcroissant` in production for emission | 4 new production deps (`absl-py`, `etils`, `jsonpath-rw`, `rdflib`) for a static, well-known JSON-LD template; conflicts with this repo's "use validation surface, not object model" convention |
| Dataset card | Jinja2 template (existing pattern) | `huggingface_hub` `DatasetCard`/`.from_template()` | Its value-add (Hub tag-vocabulary validation, `push_to_hub()`) is irrelevant — this project doesn't publish to the HF Hub |
| Group-aware split | Hand-rolled deterministic hash-bucket (stdlib `hashlib`) | `sklearn.model_selection.GroupShuffleSplit` | Split assignment is a function of the whole shuffled group array, not growth-stable across dataset releases as new source groups are added |
| Benchmark contamination | Tiered n-gram → MinHash (`datasketch`) → embedding (`sentence-transformers`) | `datatrove[decont]` (`lighteval`) | Bloom-filter-scale machinery for a dozens-to-hundreds-example corpus — same GPU/scale mismatch already documented against NeMo Curator |

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| `datatrove[ray]` / `RayPipelineExecutor` | No scale justification at this corpus size; adds a second distributed-orchestration system next to Dagster | `LocalPipelineExecutor` |
| `datatrove[s3]` (s3fs) | Second S3 client path, breaks the documented FOUND-03 single-client invariant | Existing `StorageBackend` (boto3) with explicit local-scratch stage-in/stage-out |
| `datatrove[decont]` (`lighteval`) | Full LLM-eval-harness dependency, Bloom-filter machinery built for trillion-token-scale corpora; same category error as NeMo Curator at this project's scale | Tiered n-gram (stdlib) → MinHash (`datasketch`, already pinned) → embedding (`sentence-transformers`, already pinned) |
| `mlcroissant` as a production/runtime import | Adds `absl-py`, `etils`, `jsonpath-rw`, `rdflib` to every operator's install for a static JSON-LD template this repo can hand-emit safely | Pydantic + orjson emission; `mlcroissant` as a dev-only CI conformance checker |
| `sklearn.model_selection.GroupShuffleSplit` for versioned releases | Not growth-stable — reshuffles prior release assignments when the group set grows | Deterministic hash-bucket split (same technique as Phase 21's `chunk_dedup_ledger`) |
| NeMo Curator, IBM Data Prep Kit | GPU-cluster-first / Spark-and-Ray-first tooling; redundant given DataTrove + Dagster are already the chosen curation/orchestration stack; explicitly out of scope for v2.7 | DataTrove (already pinned), formalized via `CurationEngine` |
| A second vector database | No v2.7 requirement touches retrieval infrastructure; Qdrant already covers hybrid search | Qdrant (already pinned, unchanged) |
| `GitPython` for commit-SHA capture | One `subprocess` call away; not worth a dependency | stdlib `subprocess.run(["git", "rev-parse", "HEAD"])` |

## Version Compatibility

| Package | Version | Status in this repo |
|---------|---------|----------------------|
| `datatrove` | `0.9.0` | Already pinned; confirmed current latest (released 2026-03-04, no newer release exists) |
| `datasketch` | `2.0.0` | Already pinned; reused as-is for Tier 2 contamination check |
| `sentence-transformers` | `5.6.0` | Already pinned; reused as-is for Tier 3 contamination check |
| `mlcroissant` | `1.1.0` (latest, released 2026-04-16) | New — dev-only group; requires Python `>=3.10`, compatible with this repo's `>=3.12` |
| `scikit-learn` | `1.9.0` (latest, released 2026-06-02) | Already resolved transitively via `sentence-transformers`; NOT recommended as a direct pin for splitting (see Section 5) — no action needed |
| `networkx` / `pandas` / `scipy` | `3.6.1` / `3.0.3` / `1.18.0` | Already resolved transitively (via `torch`, `docling-core`, `sentence-transformers`→`scikit-learn` respectively) — relevant only as context for the `mlcroissant` footprint discussion in Section 2 |
| `pydantic` / `sqlalchemy` / `datatrove` exact pins | `2.13.4` / `2.0.51` / `0.9.0` | No conflicts found with any recommendation in this document |

## Sources

- https://pypi.org/project/datatrove/ — version 0.9.0, release date 2026-03-04 (HIGH confidence, official package index, live-fetched)
- https://github.com/huggingface/datatrove (README, `pyproject.toml`, `pipeline/filters/base_filter.py`, `executor/base.py`) — executor types, extras table, `BaseFilter`/`exclusion_writer`, checkpoint/resume mechanism (MEDIUM-HIGH confidence, live-fetched GitHub source and docs)
- https://pypi.org/project/mlcroissant/ — version 1.1.0, release date 2026-04-16, Python `>=3.10` requirement (HIGH confidence, live-fetched)
- https://github.com/mlcommons/croissant (python/mlcroissant `pyproject.toml`, README) — runtime dependency list, production/consumption API split, `mlcroissant validate` CLI (MEDIUM-HIGH confidence, live-fetched)
- https://docs.mlcommons.org/croissant/docs/croissant-spec.html — required top-level Croissant JSON-LD fields (MEDIUM confidence, live-fetched, single source)
- https://pypi.org/project/scikit-learn/ — version 1.9.0, release date 2026-06-02 (HIGH confidence, live-fetched)
- https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.GroupShuffleSplit.html — `GroupShuffleSplit` API shape (HIGH confidence, official docs)
- https://huggingface.co/docs/huggingface_hub/package_reference/cards — `DatasetCard`/`DatasetCardData`/`.from_template()` API (MEDIUM confidence, official docs, summarized)
- Local repo inspection: `pyproject.toml`, `uv.lock` (grep for `datatrove`, `scikit-learn`, `pandas`, `scipy`, `networkx` package blocks and their `dependencies` arrays) — HIGH confidence, ground truth for "what's already transitively resolved" claims
- Local repo inspection: `src/knowledge_lake/pipeline/curate.py`, `pipeline/datasets.py`, `pipeline/export.py` — read in full to ground the CurationEngine integration-tension analysis and the T-05-08/FOUND-03 precedents cited throughout

---
*Stack research for: Knowledge Lake Framework v2.7 (Governed Dataset Production and Release Lifecycle)*
*Researched: 2026-07-19*
