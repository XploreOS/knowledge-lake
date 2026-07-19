# Pitfalls Research

**Domain:** Adding governed dataset release capabilities (versioned specs, usage-policy gating, quality contracts, partitions, deterministic splits/contamination detection, immutable releases + reproducibility manifests, diffing, lineage explorer, eval runs) to an existing document-ingestion/RAG framework with live production data and existing consumers — Knowledge Lake v2.7
**Researched:** 2026-07-19
**Confidence:** HIGH for findings grounded in this repo's own code (cited with file:line); MEDIUM for external DB/LLM-determinism claims cross-checked against current documentation and community sources (cited in Sources)

## How To Read This

This is not generic MLOps advice. Every pitfall below is either (a) a line-level consequence of
code that exists in `src/knowledge_lake/` today, or (b) an externally verified property of a
tool/technique this milestone is about to adopt for the first time (DataTrove's real executor,
Postgres immutability triggers, LLM-generation reproducibility). Where a claim is external, its
confidence tier and source are stated explicitly — per this project's own convention (see the
v2.6-era `PITFALLS.md`, now superseded by this file), nothing below is presented as authoritative
without grounding.

**The single most important finding:** `Dataset.name` is `UNIQUE` and mutated in place by
`update_dataset_export()` (`registry/repo.py:1465`), and `export_finetune_dataset(dataset_name)`
is called, unversioned, from **four independent existing surfaces** — CLI (`cli/app.py:1259`),
REST API (`api/app.py:1222`), the MCP tool registry (`agent/registry.py:96,130`), and a Dagster
asset (`dagster_defs/assets.py`). None of these four call sites carry a version or split concept
today. Every pitfall about "versioning" in this document is really a pitfall about **quietly
breaking one of these four call sites**, because they all currently assume "the dataset called
`X`" resolves to exactly one live, current thing.

**Second-most-important finding:** this milestone introduces the project's first case of adopting
a vendored library's *real* I/O machinery (DataTrove's `PipelineExecutor`/checkpoint system) after
a previous milestone **deliberately rejected it**. `pipeline/curate.py`'s module docstring is
explicit: *"DataTrove's disk-based reader/writer/executor scaffolding is never used. This
preserves the FOUND-03 single S3 client invariant... and never introduces a second S3 client path
via fsspec/s3fs."* That rejection was a considered architectural decision, not an oversight.
Reversing it is not "wire up the new API" — it is "onboard a second I/O subsystem into a codebase
that has spent four milestones enforcing it has only one."

---

## Critical Pitfalls

### Pitfall 1: `DatasetExample` split/status columns silently default existing rows into the wrong split

**What goes wrong:**
Adding a `split` column (train/validation/test/unassigned) to `DatasetExample` via
`ALTER TABLE dataset_examples ADD COLUMN split VARCHAR(16)` leaves every pre-migration row with
either `NULL` or whatever the column's default happens to be. `check_train_eval_contamination()`
today infers train vs. eval **not from a column but from payload shape**
(`"question" in payload` → eval-shaped; `"instruction" in payload` → train-shaped,
`export.py:159-181`). If the new split-aware contamination gate reads the new `split` column
*instead of* payload shape, every existing `DatasetExample` row — all generated before this
milestone — resolves to `split IS NULL`, and a naive `WHERE split = 'train'` / `WHERE split =
'eval'` gate simply **stops seeing old rows at all**. The contamination gate then reports
`contaminated_count: 0` — not because the old corpus has no contamination, but because it has been
silently excluded from the check. `_enforce_no_contamination()` fails closed on new data while
being blind to old data. A false sense of gate coverage is worse than no gate.

**Why it happens:**
The payload-shape sniff was never a stopgap that "looked like" a split column — it *was* the split
signal, computed on the fly from data every existing row already has. A new explicit `split`
column is semantically a cache of a **derived** value, and derived values need a backfill pass, not
a schema default. It is easy to treat `ADD COLUMN ... DEFAULT 'unassigned'` as "handled" when it
has only changed *how* the gap is represented, not closed it.

**How to avoid:**
- Backfill is mandatory, not optional, and must run **in the same migration/rollout unit** as the
  column add — never leave a window where new code reads a column old rows never got. Derive the
  backfilled value from the same signal `check_train_eval_contamination()` already uses today
  (`"question" in payload` → `split="eval"`; `"instruction" in payload` → `split="train"`), so the
  backfill is provably equivalent to current behavior, not a new interpretation of old data.
- Keep the payload-shape sniff **alive as a fallback path** inside the new contamination check for
  any row where `split IS NULL` post-backfill (there shouldn't be any, but a fail-closed default —
  treat unknown-split rows as "could be eval" — is safer than silently dropping them from the
  check).
- Add a migration-verification step (not just a migration) that asserts
  `SELECT count(*) FROM dataset_examples WHERE split IS NULL` is `0` after backfill, and make this
  assertion part of the phase's automated verification, not a manual spot-check.
- Version the split assignment itself (a `split_version` or `split_config_hash` column, mirroring
  the existing `filter_config_version` precedent from Phase 20 — PIPE-01) so that when the
  deterministic split *algorithm* changes later, that is a detectable, re-runnable event instead of
  silent drift.

**Warning signs:**
- A migration that adds `split` with `nullable=False, server_default='unassigned'` and no
  accompanying `UPDATE` statement.
- `check_train_eval_contamination()`'s new implementation has no code path referencing
  `"question" in payload` / `"instruction" in payload` at all — meaning old rows are invisible to it.
- Contamination counts drop to near-zero immediately after the migration ships, with no new
  overlap-resolution work having happened.

**Phase to address:** The phase that introduces deterministic splits + the new contamination gate.
The backfill must ship in the *same* phase as the column, not deferred.
**Verification:** A test with a fixture `DatasetExample` created via the *old* code path (payload
shape only, no split column set) that asserts the new contamination check still classifies it
correctly after backfill — i.e., a regression test proving old data isn't going dark.

---

### Pitfall 2: Adding a version/status concept to `Dataset` breaks all four existing `export_finetune_dataset(dataset_name)` call sites at once

**What goes wrong:**
`get_dataset_by_name()` / `get_or_create_dataset()` (`registry/repo.py:1351`) and
`export_finetune_dataset(dataset_name, ...)` (`pipeline/export.py:546`) both operate on the
`UNIQUE(name)` constraint (`registry/models.py:576`) — "the dataset called X" is assumed to be one
row. Once Dataset Projects introduce versioned specs and a `Dataset` can have multiple releases
(v1, v2, draft, released, archived), `dataset_name` alone becomes ambiguous. If the new schema
just adds a `version` column without changing the `UNIQUE(name)` constraint or the four call
sites' signatures, one of three bad things happens silently: (a) the unique constraint blocks
creation of the second version outright with an `IntegrityError` the caller doesn't expect from a
"just add a version" change; (b) the constraint is relaxed to `UNIQUE(name, version)` and
`get_dataset_by_name(name)` (still called with only a name, unchanged, by 4 call sites) now needs
a tiebreak rule that doesn't exist yet — it will pick *some* row via whatever ORDER BY happens to
be implicit in the query plan, which is non-deterministic across Postgres versions/query plans;
(c) `export_finetune_dataset("my_dataset")`, called by the MCP tool with no version argument
(this is a **user-facing agent tool** — an LLM cannot supply a version it was never told exists),
silently exports the wrong version forever.

**Why it happens:**
"Add versioning" reads as an additive schema change. It is actually a **breaking change to an
identity contract** four independent surfaces already rely on (`name` uniquely identifies a
dataset). The break is invisible in code review because none of the four call sites need to
*change syntactically* to keep compiling — they simply start resolving to different, possibly
wrong, data.

**How to avoid:**
- Decide explicitly, in the phase that introduces versioning, what `export_finetune_dataset(name)`
  (no version) means going forward: e.g. "resolves to the latest `released` version of the Dataset
  Project with this name" — and encode that resolution rule in one function
  (`get_latest_released_dataset_by_name()`), not as an implicit side effect of query ordering.
- Add an explicit, required `version` (or `release_id`) parameter to the *new* API surfaces
  (`klake dataset export`, the new REST endpoints), and treat the *old* signature as a
  backward-compatible convenience wrapper around the resolution rule above — document it as such,
  with a test that pins the resolution behavior.
- Update all four call sites (CLI `cli/app.py:1259`, API `api/app.py:1222`, MCP
  `agent/registry.py:96,130`, Dagster `dagster_defs/assets.py`) in the **same commit** that changes
  the identity model.
- The MCP tool's hardcoded `assert len(TOOLS) == 11` (`agent/registry.py:375`) is a guaranteed,
  loud reminder that a new/changed tool signature needs the assertion count bumped — treat a CI
  failure there as confirmation the surface was touched, not an annoyance to silence.

**Warning signs:**
- A migration adding `version` to `datasets` with the `UNIQUE(name)` constraint left unchanged (a
  future insert will crash) or silently dropped (a future read becomes ambiguous) with no
  accompanying decision recorded for either.
- `export_finetune_dataset` still takes exactly `(dataset_name, *, domain=None, settings=None)`
  after the phase — meaning either versioning wasn't actually wired to the read path, or an
  implicit "latest" rule was added with no test pinning which row wins.
- The MCP tool description for `export_finetune_dataset` is unchanged even though the underlying
  semantics changed — an agent will call it exactly as before and get a different result.

**Phase to address:** The phase that introduces the Dataset Project lifecycle + versioned Dataset
Specification (the first phase touching `Dataset`). Must include an explicit compatibility
decision for the four existing call sites, not just the new schema.
**Verification:** A test exercising `export_finetune_dataset("name")` (old signature, no version)
against a Dataset Project with two versions, asserting which version is returned and that the
assertion is a named, intentional rule — not accidental row order.

---

### Pitfall 3: A Usage Policy engine that gates on `license_type` will fail closed on nearly every existing source

**What goes wrong:**
`license_type` is `String(64), nullable=True` (`registry/models.py:85`), free text, and defaults to
the literal string `"unknown"` at **every** call site that creates a source:
`agent/registry.py:182,204`, `pipeline/ingest.py:249,360,483`. It has never been validated,
constrained to an enum, or enforced anywhere (confirmed: no `CheckConstraint`, no gate, in the
current codebase). The moment a Usage Policy engine adds a deterministic rule like *"reject sources
whose usage decision for `training` is not `approved`"*, sources with `license_type="unknown"` —
which is most or all of the existing 34+ healthcare sources plus the aviation pack's `sources.yaml`
(`license: public-domain` in YAML, mapped to `license_type` in `pipeline/domains.py:111`, but never
audited against the policy model) — will fail the gate. If the gate is wired to also block
existing *ingestion/export* paths (not just new Dataset Project sourcing), this breaks the
existing, working RAG corpus export with no user-facing warning beyond a policy-engine log line
nobody is watching yet, because policy gating is brand new and nothing has ever depended on it
succeeding before.

**Why it happens:**
`license_type` was designed as descriptive metadata for humans reading the source registry, not as
a machine-enforced gate input. Its default (`"unknown"`) was chosen because *most callers don't
know the license at ingest time* and the field was never meant to block anything — it was there so
a human could look it up later. A new policy engine that treats "unknown" as "denied by default"
(the only sound fail-closed choice for a *new* source) is correct for new intake — but is a silent
regression against the entire existing corpus if applied retroactively without a grandfather rule.

**How to avoid:**
- Treat this as a two-population problem from day one: **pre-milestone sources** (registered
  before the policy engine existed) vs. **post-milestone sources** (registered after). Do not apply
  the same default-deny rule to both.
- Ship a migration/backfill task, not just a schema addition: enumerate every existing
  `license_type` value in the corpus (`SELECT license_type, count(*) FROM sources GROUP BY 1`) and
  make an explicit, recorded policy decision per **distinct value actually present** — not a
  blanket default. `"unknown"` sources that are *already in production* need either (a) a one-time
  human review producing real usage-policy decisions, or (b) an explicit `grandfathered=True` /
  `policy_status="legacy_unreviewed"` marker that lets them keep working under the old (no-gate)
  behavior while being visibly flagged as needing review — never a silent pass that looks
  identical to an actual approval.
- Keep the free-text `license_type` field as-is (it's an SPDX-identifier-shaped field per its own
  docstring, `api/schemas.py:797`) and add the new usage-policy decision as a **separate**,
  structured table (`usage_policy_decisions`: source_id, dimension [retrieval/training/commercial/
  derivatives/redistribution/attribution/share-alike], decision, decided_by, decided_at, rationale)
  rather than overloading `license_type` itself with enforcement semantics it was never built to
  carry. This also gives an audit trail (the milestone brief's "auditable" requirement) that a
  single mutable string column cannot.
- Default new-source ingestion (`ingest.py`'s three call sites) to *require* an explicit
  `license_type` once the policy engine exists, rather than silently defaulting to `"unknown"` —
  otherwise the same problem regenerates for every source added after the migration too.

**Warning signs:**
- A policy-engine unit test suite that only tests sources with a real license value — none with
  `"unknown"`, none from the actual 34-source corpus.
- `klake dataset ...` commands or Dagster asset runs that start failing immediately after the
  policy engine ships, with the failure reason being "source has no approved usage decision" on
  sources that were exporting fine the day before.
- No migration script that touches existing `sources` rows — only new-table DDL.

**Phase to address:** The phase that introduces the Usage Policy engine. Must ship together with a
one-time backfill/grandfather pass over the existing `sources` table, run as an explicit,
reviewable step (ideally producing a printed table of every source and its assigned interim
policy status) before the gate is wired into any export path.
**Verification:** Run the new policy gate against the real existing 34-source healthcare corpus in
report-only mode first; assert zero previously-working exports fail closed without a human having
seen and approved the grandfather list.

---

### Pitfall 4: DB-layer immutability for "released" rows needs an enforced constraint, not an application-layer `if status == "released": raise`

**What goes wrong:**
The natural first implementation of "a Dataset Release is immutable" is a Python-level check —
`if release.status == "released": raise ImmutableReleaseError(...)` inside whatever
`update_release()` function is written. This protects exactly one code path: the one someone
remembered to add the check to. It does **not** protect: a future Alembic migration doing a bulk
`UPDATE`, a one-off `psql` fix run directly against the database (this project already has at
least one instance of a lingering dual-write/manual-patch situation — the `sources.config["domain"]`
pending-removal tech debt — showing direct-row surgery is not hypothetical here), a second code
path added later by someone who doesn't know the check exists (there is no `assert len(TOOLS) ==
11`-style forcing function for "did you add a mutation path"), or a bug that re-runs a completed
release job and calls the *creation* function again instead of the *update* function, bypassing the
update-side check entirely.

**Why it happens:**
Application-layer invariants are easy to write and easy to forget to re-apply at every new call
site. A single `CHECK` constraint or trigger is one artifact everyone touching the table must pass
through, including out-of-band `psql` sessions and future migrations. The former is convention; the
latter is enforcement. This project already knows the difference — it is the exact lesson behind
`xfail_strict = true` (a convention silently violated for months, per this project's own history)
and the Phase 18 gate-decoupling work (a *documented* warning comment in `crawl.py` that was
bypassed anyway until it was made structurally impossible to bypass).

**How to avoid:**
- Enforce immutability with a Postgres `BEFORE UPDATE` trigger on the releases table that rejects
  (raises) any `UPDATE` where `OLD.status = 'released'`, **except** for an explicit, narrow allowlist
  of fields that are legitimately mutable post-release (e.g., a `superseded_by` back-reference, or
  a `retracted_at` timestamp for the one legitimate post-release event — legal takedown). Compare
  `OLD` and `NEW` column-by-column in the trigger and only allow changes to that allowlist; reject
  everything else. This is the standard Postgres "audit-log/immutable-row" pattern and is a small,
  well-understood trigger.
- Belt-and-suspenders, not either/or: keep an application-layer check too (for a fast, readable
  error message before the DB round-trip), but treat the trigger as the actual guarantee and the
  Python check as UX.
- For the "bug re-runs a completed release job" case specifically: make the release-creation
  function **idempotent on a natural key** (e.g. `(dataset_project_id, version)` unique constraint,
  mirroring the existing `UNIQUE(name)` pattern on `datasets` and the `get_or_create_*` convention
  already used for `Dataset` and `LlmSpend` in this codebase) so a re-run either no-ops against the
  existing immutable row or raises a clean `IntegrityError` — never silently produces a second
  "released" row for the same version, and never attempts to mutate the first one.
- Alembic migrations that need to touch a `released` row for a genuine schema reason (e.g. adding a
  new nullable column) are fine — a trigger keyed on `status='released'` blocking *content* changes
  does not block `ALTER TABLE ... ADD COLUMN`, which is DDL, not a row `UPDATE`. Confirm this
  explicitly in the phase's design so the trigger isn't later blamed for blocking a legitimate
  migration.

**Warning signs:**
- Any PR implementing "immutable release" with no new SQL migration — Python-only means it's a
  convention, not a guarantee.
- A support/ops runbook step that says "if a release needs fixing, just update the row directly in
  psql" — the exact bypass the trigger exists to prevent.
- No test that opens a raw `session.execute(text("UPDATE releases SET ..."))` (bypassing any ORM-
  level guard) against a released row and asserts the database itself rejects it.

**Phase to address:** The phase that introduces immutable Dataset Releases. The trigger (or
equivalent DB-level enforcement) must ship in the same migration as the `releases` table itself,
not as a follow-up hardening pass.
**Verification:** A test that issues a raw SQL `UPDATE` (not through the application's ORM methods)
against a `released` row and asserts the database raises — proving the guarantee holds even when
application code is bypassed entirely.

---

### Pitfall 5: The reproducibility manifest will honestly promise "reproduce," not "replay" — conflating the two undermines the whole feature

**What goes wrong:**
Dataset generation goes through `litellm.completion(...)` at `pipeline/datasets.py:187` (QA pairs,
`temperature=0.2`) and `:230` (instruction pairs, `temperature=0.3`) via a LiteLLM proxy to AWS
Bedrock (per this project's context — "Using AWS Bedrock models through LiteLLM proxy"). Neither
call sets a `seed` parameter today. Even where a provider *does* expose a seed, determinism is not
guaranteed: temperature=0 + fixed seed still does not reproduce output bit-for-bit across most
production LLM serving stacks, because of floating-point non-associativity across
batched/parallel matrix operations, continuous-batching effects (a request's exact result depends
on what else is in its batch, which varies run to run), and provider-side model/infra updates that
happen silently between calls — publicly documented by both OpenAI and Anthropic (see Sources). A
"reproducibility manifest" that promises `reproduce.yaml` will regenerate the *exact same generated
examples* on rebuild is making a promise the underlying stack cannot keep, and the first person who
runs `reproduce.yaml` and gets different QA pairs will (correctly) conclude the manifest is broken,
when the manifest's actual scope was mis-stated.

**Why it happens:**
"Reproducibility manifest" is a term borrowed from deterministic build systems (pinned dependency
versions, hash-locked inputs) where it genuinely means bit-for-bit replay. Silently carrying that
meaning into a step with an LLM call in it overpromises. The deterministic parts of this pipeline
(cleaning, chunking, splits, dedup — all of which this project already treats as "deterministic
first," per the PROJECT constraint) genuinely are reproducible; the generation step is not, and
never can be with the current model-serving landscape.

**How to avoid:**
- Split the manifest's claims explicitly into two tiers, and label them as such in the manifest
  schema itself (not just in prose docs): **"Reproducible"** — every deterministic transform
  (source → clean → chunk → curate → split → contamination-check), pinned by content hash, prompt
  version, filter/threshold config version (this project already has the precedent:
  `filter_config_version` folded into the WR-05 chunk hash, PIPE-01/Phase 20) — rebuild these from
  the same inputs and get bit-identical output, and *this* is what `reproduce.yaml`'s
  rebuild-equivalence test should actually assert. **"Explainable, not replayable"** — the LLM
  generation step: pin and record everything that *was* controllable (model alias resolved to a
  concrete model ID/version at generation time, prompt template + version, temperature,
  max_tokens, and the full request/response if storage allows) so a human can understand *exactly
  what produced* a given example, without promising the regeneration will match it.
- The rebuild-equivalence test (already a named milestone deliverable) must therefore test the
  **deterministic tier only** — assert splits, dedup decisions, and quality-gate outcomes rebuild
  identically from the same source snapshot; do not assert LLM-generated example text rebuilds
  identically, and say so explicitly in the manifest/test names so nobody mistakes a passing test
  for a stronger guarantee than it is.
- For the LLM tier, the strongest honest guarantee available is **caching + record, not
  regeneration**: this project already has exactly this pattern for enrichment
  (`_enrichment_cache_key` on content hash + prompt version) and dataset generation
  (`_dataset_gen_cache_key`, `datasets.py:139`) — a "rebuild" of the generation step, run against
  unchanged inputs, hits cache and returns the *original* stored output rather than truly
  re-invoking the LLM. Lean into this: the manifest's real reproducibility claim for the generation
  step is "the recorded output is retrievable and pinned," not "re-invoking the model reproduces it."
- Record the resolved concrete model identity (not just the task-alias, e.g. `strong_model`) at
  generation time in the manifest — task aliases can silently repoint to a new model version over
  time (this is a stated project convention: aliases exist precisely so the underlying model can
  change), so the alias name alone is insufficient provenance for "what actually generated this."

**Warning signs:**
- A `reproduce.yaml` schema or rebuild test with no distinction between deterministic and
  LLM-generated pipeline stages.
- A "rebuild-equivalence test" that asserts generated example *text* is identical across two runs
  without cache hits — this will be flaky by construction and teach the team to add retries/fuzzy
  matching, quietly eroding the guarantee instead of scoping it correctly.
- Manifest fields that record only the task alias (`strong_model`) and not the concrete
  provider/model version actually invoked.

**Phase to address:** The phase that builds the reproducibility manifest + rebuild-equivalence
test. The tiering decision (deterministic vs. explainable-only) is a design decision that should be
recorded in that phase's plan, not discovered during implementation.
**Verification:** Two separate tests: one asserting deterministic-tier rebuild is bit-identical
from a fixed source snapshot; one explicitly asserting (and documenting) that the LLM-generation
tier is served from cache on rebuild rather than re-invoked, with cache-miss behavior (re-invoking
the model) clearly out of scope for the equivalence guarantee.

---

### Pitfall 6: Naive n-gram contamination detection produces false negatives on LLM-reworded content and false positives on domain boilerplate

**What goes wrong:**
The milestone brief calls for a "benchmark contamination gate" to replace the payload-shape sniff.
The obvious next implementation is exact or near-exact n-gram overlap (e.g., Jaccard similarity of
word 8-grams) between generated training examples and the protected eval set. Two failure modes
are near-certain in this specific corpus:

1. **False negatives.** `generate_qa_example`/`generate_instruction_example` (`datasets.py`) call
   an LLM to *produce* the training examples from source chunks. If the same underlying source
   chunk is later used (directly or via a near-duplicate document — this corpus already has
   documented near-dup detection via `dedup_status` in `curate.py`) to generate an eval example,
   the LLM's paraphrasing means the eval question/answer text and the training example's
   instruction/output text can share close to zero exact n-grams while being substantively the
   same knowledge, sourced from the same passage. An n-gram gate checks surface text; it cannot
   see through an LLM's rewording. This is the harder direction to solve and is a known, published
   weakness of surface-level contamination detection generally.
2. **False positives.** This corpus is dense with recurring, near-mandatory regulatory boilerplate
   — FDA boxed-warning language, CMS "this is not a legal document" notices, and HL7 IG
   license/copyright headers are all text that is *deliberately repeated verbatim* across many
   source documents in this domain. An n-gram contamination gate, applied naively, will flag two
   documents sharing a boilerplate disclaimer as "contaminated" overlap between train and eval,
   when neither example's *substantive* content overlaps at all. Fail-closed behavior (this
   project's established pattern, e.g. `_enforce_no_contamination`) means this generates
   **false-positive gate failures on exactly the class of content that this project's own v2.6
   cleaning work already had to specifically carve exemptions for** — the same recurring
   boilerplate text pattern that trips up boilerplate classifiers also trips up naive contamination
   detectors, for the same underlying reason (repetition looks like the signal, but in a regulated
   corpus repetition is often the content).

**Why it happens:**
Contamination-detection heuristics are typically developed against benchmark leakage in general
web/pretraining corpora, where "near-identical surface text across train/eval" is both the failure
mode and a good proxy for it. This corpus's failure mode is closer to "near-identical *knowledge*,
differently worded" (an LLM did the rewording), and its false-positive source is "near-identical
*mandatory boilerplate*, unrelated knowledge" — the opposite mismatch from the false-negative case,
both stemming from the fact this is a regulated, LLM-generated-example corpus, not a scraped
pretraining corpus.

**How to avoid:**
- **Do not rely on n-gram overlap alone.** Combine it with the **source-lineage overlap check this
  project already has** — `check_train_eval_contamination()`'s existing `cleaned_document`-ID-based
  direct/near-dup overlap logic (`export.py:115-224`) catches the false-negative case *correctly*,
  because it traces contamination through the **lineage graph** (which source chunk/document an
  example was generated from), not through surface text. This lineage-based check is immune to LLM
  paraphrasing precisely because it never looks at the generated text at all. **Keep it as the
  primary signal**; treat n-gram/embedding similarity as a *supplementary* signal for catching
  cases the lineage graph can't see (e.g., two independently-authored source documents that happen
  to describe the same fact) — not a replacement.
- Add a semantic/embedding-similarity check as the second supplementary signal for the same reason
  n-grams alone are weak against paraphrase — this project already has embeddings
  (`sentence-transformers`) and a vector store (Qdrant) in place; reuse them rather than building a
  new similarity mechanism.
- For the false-positive boilerplate case: apply the **same substance-gate signal already built for
  chunk quality** (`pipeline/quality/` predicates, the domain-pack allowlist convention from
  `filters.yaml`, Phase 19/20) to strip or down-weight boilerplate spans *before* computing n-gram
  overlap for contamination purposes — reuse the existing boilerplate classifier rather than
  building an independent one, and exempt/normalize known regulatory-boilerplate patterns before
  comparing.
- Keep the existing `contamination_override_artifact_ids` escape hatch
  (`ExportSettings.contamination_override_artifact_ids`) working for the new gate exactly as it
  does today — a documented, reviewed override for known, deliberate overlap (e.g., a shared
  disclaimer) remains the correct mechanism; do not remove it when the gate's *detection* mechanism
  changes underneath it.

**Warning signs:**
- A new contamination implementation with no reference to `cleaned_document` lineage, only text
  comparison.
- The override list (`contamination_override_artifact_ids`) growing rapidly right after the new
  gate ships, populated mostly with document pairs that share a legal disclaimer, not real content
  — a sign the gate is generating false positives operators are manually suppressing rather than
  the gate being fixed.
- No fixture pair in tests where the eval example is a paraphrase (not a substring) of training
  content from the same source chunk.

**Phase to address:** The phase that builds deterministic splits + the contamination gate. Must
explicitly retain and build on the existing lineage-based check rather than replacing it with a
purely textual one.
**Verification:** Two fixture-driven tests: (1) an LLM-paraphrased eval/train pair from the same
source chunk — lineage check must catch it, n-gram-only check would miss it, prove the combined
gate catches it; (2) a pair of documents sharing only a boilerplate disclaimer with unrelated
substantive content — the gate must NOT flag it, or must flag it distinctly from real contamination
(e.g., a `boilerplate_overlap_only` category the operator can triage separately, mirroring the
existing `direct_overlap_count` / `near_dup_overlap_count` split already present in
`_enforce_no_contamination`'s error message).

---

### Pitfall 7: Adopting DataTrove's real `PipelineExecutor`/checkpoint machinery reintroduces the exact I/O pattern `curate.py` was deliberately built to avoid

**What goes wrong:**
`pipeline/curate.py`'s module docstring is explicit and load-bearing: DataTrove filter classes are
called directly via `.filter(doc)` in a loop, and *"DataTrove's disk-based reader/writer/executor
scaffolding is never used. This preserves the FOUND-03 single S3 client invariant... and never
introduces a second S3 client path via fsspec/s3fs."* This was a deliberate architectural decision,
not an oversight (the docstring literally labels it "RESEARCH.md Anti-Pattern"). The new
`CurationEngine` protocol's DataTrove backend, per the milestone brief, is explicitly meant to use
DataTrove's *real* `Reader`/`Writer`/checkpoint API this time — Dagster-launched, with
accepted/rejected writers and checkpointing. Concretely, this means adopting
`datatrove.executor.LocalPipelineExecutor` (or similar), whose checkpoint state
(`logging_dir`/`completions/{rank}` marker files, confirmed in
`datatrove/executor/base.py:58,165,177,189`) defaults to a **local filesystem path**
(`f"logs/{timestamp}_{random_str}"` if unspecified) — a directory on whatever machine the Dagster
op happens to run on. Three concrete breakages follow:

1. **Checkpoint state on ephemeral local disk conflicts with the project's S3-as-production-store
   constraint.** If `logging_dir` is left at its local default (or pointed at a Dagster worker's
   local scratch dir), a container restart, redeploy, or rescheduling to a different node loses all
   checkpoint/completion state — "resumability," the exact property DataTrove's checkpointing
   exists to provide, silently reverts to "start over" with no error, because
   `skip_completed=True` (the default) simply finds no completion markers and reruns everything.
2. **fsspec/s3fs is not an installed dependency today** (verified: `import s3fs` fails in this
   environment). DataTrove's `get_datafolder()` supports S3-backed logging dirs *only* via an
   fsspec S3 filesystem (`s3://...` string, or an explicit `S3FileSystem` instance) — meaning
   pointing DataTrove's checkpoint dir at S3/MinIO to solve problem (1) requires adding `s3fs` as a
   new dependency, which is precisely the "second S3 client path" `curate.py`'s docstring calls out
   as the thing being avoided. This is not a minor implementation detail; it is the one thing this
   project's curation module was explicitly designed never to need.
3. **`LocalPipelineExecutor` uses `multiprocess`-based worker processes** (`forkserver` start
   method by default) — a different execution/concurrency model than the rest of this pipeline,
   which runs stages inline within a single Dagster op/process. Adopting it inside a Dagster asset
   means either nesting a multiprocessing pool inside a Dagster op (resource/lifecycle interactions
   with Dagster's own process model are untested here) or adopting a different DataTrove executor
   (e.g. one built around Ray or Slurm) that this project has no existing operational story for.

**Why it happens:**
The milestone brief frames "formalize the CurationEngine, DataTrove as the first production
backend" as primarily an abstraction-boundary change (introduce a protocol, DataTrove implements
it). The actual blocker is that DataTrove's *real* I/O machinery was never built to run
inside another orchestrator's process/storage model — it assumes it owns the filesystem and the
worker pool. This mismatch is invisible until someone actually reaches for the checkpoint feature
the milestone brief specifically asks for.

**How to avoid:**
- Decide explicitly, before implementation: does the new `CurationEngine` DataTrove backend
  actually need DataTrove's `PipelineExecutor`/checkpoint machinery, or can it get
  Dagster-launched-with-accepted/rejected-writers behavior by keeping the existing direct-call
  pattern (`.filter(doc)` in a loop) and building checkpointing/resumability using **this
  project's own existing primitives** — the Postgres registry (which already tracks per-artifact
  processing state and is exactly what `chunk_dedup_ledger`'s atomic-claim pattern from Phase 21
  demonstrates works well for exactly this kind of idempotent-resumable-processing problem) instead
  of DataTrove's file-marker checkpoints. This keeps FOUND-03 intact and reuses a pattern this
  codebase has already proven twice (dedup ledger, content-hash caching).
- If DataTrove's real executor genuinely is adopted (e.g., because the milestone wants to preserve
  compatibility with DataTrove's own reader/writer ecosystem for interop), then:
  - Explicitly add `s3fs`/`fsspec` as a pinned dependency (matching this project's exact-version
    pinning convention) and treat it as a **new, reviewed second I/O path** in the phase's risk
    section — not an incidental transitive dependency.
  - Point `logging_dir` at S3/MinIO explicitly in every environment (never rely on the local
    default), and add a startup/config check that fails loudly if it resolves to a local path in
    any non-throwaway environment.
  - Test the interaction between DataTrove's worker-process model and the Dagster op lifecycle
    directly (a Dagster op timeout or retry mid-DataTrove-run is a real scenario this pairing has
    to survive) before relying on it in production.
- Either way, this decision belongs in the phase design doc as an explicit "why" — the project
  already has one instance of a considered anti-pattern decision (`curate.py`'s docstring); a
  second, contradicting decision two milestones later needs its own recorded rationale so a future
  reader doesn't have to reverse-engineer why the codebase now does the opposite of what an
  existing docstring says.

**Warning signs:**
- A new dependency on `s3fs`/`fsspec` appearing in `pyproject.toml` with no corresponding line in
  the phase's risk/decision notes.
- Curation runs that "work in dev" (local disk checkpoint) but silently reprocess everything from
  scratch in production (ephemeral container disk) — the classic symptom of a checkpoint directory
  that isn't actually persistent.
- `curate.py`'s existing "Anti-Pattern" docstring left unchanged/uncontradicted while a new module
  imports `datatrove.executor.*` directly.

**Phase to address:** The phase that formalizes `CurationEngine` + the DataTrove production
backend. The local-vs-S3 checkpoint decision and the dependency-surface decision must be made
explicitly in that phase's plan, before implementation starts.
**Verification:** An integration test that runs the DataTrove backend, kills/restarts the process
mid-run (or simulates it by clearing any in-memory state), and asserts the second run resumes from
checkpoint rather than reprocessing already-accepted/rejected documents — run against whatever
storage backend production will actually use (S3/MinIO), not local disk, or the test proves
nothing about the real failure mode.

---

### Pitfall 8: One giant multi-table migration for the whole milestone breaks this project's own established "one migration per phase" convention and makes any single phase's rollback take down every other phase's tables

**What goes wrong:**
This project's Alembic history is a clean one-migration-per-phase-of-work sequence:
`0008_dataset_examples`, `0009_crawl_scheduling`, `0010_sources_domain_column`,
`0011_chunk_dedup_ledger` — each migration is scoped to one phase's concern, each has its own
tested, reversible `downgrade()`. v2.7 needs new tables/columns for: Dataset Project +
Specification, Usage Policy decisions, Quality Contract + rule outcomes, result partitions,
generated-example validation status, splits, releases + manifests, and possibly diff/lineage-
explorer support tables — roughly 6–8 new schema surfaces. Cramming all of them into one
`0012_dataset_ops_control_plane.py` migration means: (a) the FK dependency ordering across all of
them has to be worked out and gotten right in one shot (Dataset Project → Dataset Specification →
Quality Contract → Release, several of which likely reference `datasets`/`dataset_examples`,
`sources`, and each other) instead of incrementally, one already-tested layer at a time; (b) if a
later phase in the same milestone needs to tweak an earlier phase's table (near-certain — splits
will need to reference releases; releases will need to reference quality-contract outcomes), that
tweak either goes into the same giant migration (defeating the "one migration ships with the phase
that needs it" discipline) or into a second migration that now has a much larger, harder-to-review
diff against the first; (c) a `downgrade()` for one phase's mistake has to reverse-order-drop
tables several other phases now depend on, making an isolated rollback of just the broken phase
operationally impossible without also reverting everything shipped after it.

**Why it happens:**
A milestone this large in schema surface invites "let's just do the whole data model in one pass
since it's all one conceptual feature" — especially since Dataset Project, Specification, Quality
Contract, and Release genuinely are interdependent concepts designed together. But "designed
together" and "migrated together" are different questions; this project's own history shows
designing a *feature* across several phases while still shipping a small, single-purpose migration
per phase (Phase 19's `pipeline/quality/` predicate module and Phase 20's chunk-gate columns were
part of one designed-together quality system, shipped as two separate, independently reversible
migrations).

**How to avoid:**
- Follow the existing convention: **one small migration per phase, landing with the phase that
  needs it**, not one migration for the whole milestone. Sequence phases (and their migrations) so
  each new table's FK dependencies only ever point at tables that already exist from an earlier,
  already-shipped phase — e.g., Dataset Project + Specification first (no new FK dependencies
  beyond existing `sources`/`datasets`), then Usage Policy decisions (FK to `sources`, already
  exists), then Quality Contract + partitions (FK to Dataset Project + artifacts, both already
  exist by then), then splits (FK to `dataset_examples` + Dataset Project), then Releases +
  manifests last (FK to everything above, all already shipped and tested).
  This is exactly the dependency order the milestone's own target-feature list is already written
  in, which suggests the roadmap's phase order and the migration order should be the same order.
- Each migration keeps its own tested, reversible `downgrade()` — this project's convention already
  requires this (every existing migration file has one) — so a bad phase can be rolled back on its
  own without cascading into unrelated, already-working tables from other phases.
- Where a later phase genuinely needs to add a column/FK to an earlier phase's table (e.g., a
  `release_id` FK added to `dataset_examples` once releases exist), that's a small, separate,
  correctly-later-numbered migration (`0018_dataset_examples_add_release_fk.py`), not a rewrite of
  the earlier migration file — this project's Alembic history never edits a shipped migration in
  place.

**Warning signs:**
- A single migration file touching more than 2–3 new tables, or one whose `downgrade()` has to drop
  tables in an order requiring careful thought about cross-phase FK dependencies.
- A migration for "Phase N" that also silently alters a table introduced in "Phase N−3."
- Any temptation to squash multiple phases' migrations into one before merging to main "to keep the
  history clean" — this project's existing history is deliberately *not* squashed this way (11
  separate migration files across 6 milestones), and squashing would be a first-time deviation from
  it.

**Phase to address:** A cross-cutting rollout concern owned by the roadmap/requirements phase, not
a single implementation phase — record the migration-per-phase sequencing decision (and the FK
dependency order) explicitly in `ROADMAP.md`/`REQUIREMENTS.md` for v2.7, then each phase plan
inherits "your phase ships exactly one migration."
**Verification:** Count of new Alembic revision files at milestone end roughly equals count of
schema-touching phases (not one); each migration's `downgrade()` is exercised in CI
(`alembic downgrade -1` then `alembic upgrade head` round-trip) per this project's existing
reversibility discipline.

---

### Pitfall 9: The flagship non-healthcare dataset will expose that domain-pack conventions were only ever exercised against healthcare — proven by the aviation/climate packs already in the repo

**What goes wrong:**
This is not hypothetical risk — it is already partially reproduced in the repository today.
`domains/healthcare/` has `domain.yaml`, `sources.yaml`, `taxonomy.yaml`, `prompts/`, `validators/`,
**and** `filters.yaml` (the clinical-code allowlist protecting short, structured content like
`ICD-10 E11.9` or `Metformin 500 mg PO BID` from the substance gate — Phase 19/20, CLEAN-06).
`domains/aviation/` — already checked in, with a real `domain.yaml`, `sources.yaml` (FAA handbooks,
`license: public-domain`), `taxonomy.yaml`, `prompts/`, and `validators/` — has **no
`filters.yaml`**. `domains/climate/` has only `prompts/` and `validators/` — no `domain.yaml`,
`sources.yaml`, or `taxonomy.yaml` at all; it is a stub. Neither non-healthcare pack has ever been
run through the chunk-substance gate's domain-allowlist mechanism, which today is a healthcare-only
artifact even though the gate itself is documented as domain-agnostic-by-design. If the flagship "AI
Agent Security and Permission Dataset" is built as a brand-new domain pack (most likely, since it
matches neither aviation, climate, nor healthcare), it will hit the exact same class of problem
these two stub packs already reveal: domain-specific short/structured content this new domain
considers load-bearing (e.g., a permission-scope string like `read:documents`, a CVSS score, a tool
name like `mcp__filesystem__read`) has no allowlist protecting it from the same char/token-floor and
repetition heuristics that Phase 19/20 had to specifically carve exceptions for in healthcare — and
those exceptions do not automatically transfer, because `filters.yaml`'s `normative_allowlists` are
hand-authored regex patterns specific to ICD-10/LOINC/RxNorm/dosage shapes.
Separately: `domains/local/` exists specifically because `DomainLoader.from_name()` hardcodes the
`"domains/"` path segment (a known limitation, per this project's own memory notes) — meaning a
pack placed under `domains/local/<name>/` is **not loadable via `klake init --domain <name>`** the
normal way; only `domains/<name>/` (top-level) packs load through the standard path. If the
flagship dataset's domain pack is scaffolded via whatever tooling defaults to `domains/local/` (the
existing `functional-medicine` pack lives there), it will silently fail to load through the normal
CLI path and the failure will look like a domain-registration bug rather than a path-convention
mismatch.

**Why it happens:**
Every substance/quality-gate exemption mechanism built so far (Phase 19's `DomainFilters`, Phase
20's `must_not_reject.yaml` fixture) was designed, tuned, and CI-verified against healthcare content
specifically, because healthcare was the only domain with real production data and a real garbage-
rate problem to solve. "Domain-agnostic core, domain-specific extension point" was the *architecture*
decision (correctly), but only one domain has ever actually exercised the extension point end to
end. Aviation and climate were scaffolded (sources, prompts, taxonomy) without ever being run
through ingestion at volume, so the gap was never surfaced.

**How to avoid:**
- Treat "author a `filters.yaml` (or equivalent Quality Contract domain-level rule set) for the
  flagship domain" as an explicit, budgeted task in the flagship-dataset phase — not an assumed
  side effect of "add a domain pack." Use the same conjunction-of-signals approach Phase 19/20
  established (positional invariance, link density, domain-term presence, length) rather than
  reusing healthcare's regex patterns verbatim, since the *shapes* of load-bearing short content
  differ (dosage strings vs. permission-scope strings vs. tool-call identifiers).
  This is a Quality Contract this milestone should therefore ship a genuinely reusable pattern for
  — not just port healthcare's hardcoded regexes but factor "domain contributes a normative
  allowlist for its own short/structured content" as first-class Quality Contract config, since the
  milestone brief already positions Quality Contracts as multi-level and domain-scoped-capable.
- Ship the flagship domain pack at `domains/<name>/` (top-level), not `domains/local/<name>/`, so it
  loads via the standard `klake init --domain <name>` path — confirm this explicitly given the known
  `from_name()` limitation, rather than discovering it when the flagship demo doesn't register.
- Run the flagship domain's real source corpus through the chunk-substance gate in **report-only
  mode first** (the same discipline Phase 19/20 mandated for healthcare) and have a human
  familiar with the flagship domain review the rejection list before the gate is allowed to drop
  anything for it — do not assume the gate's healthcare-tuned thresholds are domain-neutral just
  because the *code* is domain-agnostic.
- Don't assume the aviation or climate stub packs are a shortcut to the flagship — audit whether
  either is a legitimate candidate (aviation is meaningfully further along) versus building the
  "AI Agent Security and Permission Dataset" as a wholly new pack; either way, the filters.yaml gap
  and the `domains/local/` loader gap apply.

**Warning signs:**
- The flagship phase's plan has no task for domain-specific quality-gate tuning, only "add sources"
  and "generate examples."
- The new domain pack directory is created under `domains/local/` and `klake init --domain <name>`
  is never actually exercised against it before the demo.
- Rejection-list review for the flagship corpus is skipped or done by whoever is available, not
  someone who can judge whether a rejected chunk (e.g., a terse permission string) is actually
  garbage or load-bearing for that domain.

**Phase to address:** The flagship "AI Agent Security and Permission Dataset" phase — but the
underlying gap (domain-level Quality Contract config as a reusable, non-healthcare-specific
mechanism) should be designed one phase earlier, in the Quality Contract phase, precisely so the
flagship phase isn't the first and only place this is tested.
**Verification:** A must-not-reject fixture set for the flagship domain (mirroring
`tests/fixtures/must_not_reject.yaml`'s healthcare precedent) reviewed by a human familiar with the
domain, in CI, before the flagship dataset is released.

---

### Pitfall 10: `check_train_eval_contamination()`'s payload-shape sniff has silent failure modes today that a naive replacement will inherit unless explicitly fixed

**What goes wrong:**
The current implementation (`export.py:159-181`) branches purely on dict-key presence:
`"question" in payload` → eval; `elif "instruction" in payload` → train. Any `DatasetExample`
whose payload has neither key (a malformed row, a future third example type, or a manually inserted
row) is **silently skipped from both sides of the overlap check** — it contributes to neither
`eval_cleaned_doc_ids` nor `finetune_cleaned_doc_ids`, so it can never be flagged as contamination
regardless of its actual origin. A "replace the sniff with a split column" effort that reads the
new `split` column but keeps the same "if neither train nor eval, silently ignore" default inherits
this exact gap under a new name. Given the milestone is explicitly adding a "generated-example
validation lifecycle" with new payload shapes possible (`repaired`, etc.) and an `ExampleValidator`
interface, the chance of a new, third payload shape appearing that the old two-branch sniff (or its
naive split-column replacement) doesn't recognize is high, not hypothetical.

**Why it happens:**
A binary if/elif with no else silently treats "doesn't match either pattern" as "not interesting"
rather than "unknown, needs attention" — the classic default-allow-by-omission bug shape, the same
category of issue this project's `xfail_strict = true` incident (a stale xfail hiding failing
endpoints) already taught it to guard against with an explicit, loud check rather than a silent
pass-through.

**How to avoid:**
- The new split-aware contamination check should have an explicit `else` branch: any
  `DatasetExample` whose `split` is not one of the recognized values (`train`/`validation`/`test`)
  should be logged loudly and, per this project's fail-closed convention
  (`_enforce_no_contamination`), should probably count toward a distinct "unclassified — needs
  review" bucket in the result dict, not be silently dropped. Never let "doesn't match a known
  category" default to "assumed safe."
- Given the milestone's new example lifecycle has more states (`generated`, `validating`,
  `accepted`, `recoverable`, `repaired`, `rejected`), decide explicitly which of these states'
  examples participate in the contamination check at all — a `rejected` example presumably
  shouldn't count toward either side; a `repaired` one should count under its final accepted shape.
  Encode this as an explicit mapping (state → contamination-relevant split, or "excluded"), not an
  implicit fallthrough.

**Warning signs:**
- The new contamination check's result dict has no field for "examples with unrecognized
  status/split" — meaning such rows are being silently excluded exactly like today.
- A new example status is added to the lifecycle enum without a corresponding update to whatever
  function decides contamination-check participation.

**Phase to address:** The phase that replaces the payload-shape sniff with the deterministic split +
contamination gate.
**Verification:** A fixture `DatasetExample` with a status/split value the check doesn't recognize
— assert the new implementation surfaces it as a countable "unclassified" result, not silence.

---

## Technical Debt Patterns

Shortcuts that seem reasonable but create long-term problems for this milestone specifically.

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|-----------------|-----------------|
| Adding `split`/`status` columns to `DatasetExample` without a backfill migration | Ships the schema fast | Every pre-milestone row is invisible to the new contamination gate (Pitfall 1) | Never — backfill must ship in the same unit as the column |
| Gating Usage Policy on `license_type="unknown"` with a blanket default-deny, no grandfather list | Simple, uniform rule | Breaks every existing export path on day one (Pitfall 3) | Never for existing sources; acceptable as the rule for genuinely new sources going forward |
| Python-only immutability check on Dataset Release | Fast to write, no migration needed | Bypassable by direct SQL, re-run bugs, forgotten call sites (Pitfall 4) | Acceptable only as a UX layer *in addition to* a DB trigger, never as the sole guarantee |
| Treating `reproduce.yaml` as a full re-run guarantee including LLM generation | Sounds impressive, matches "reproducibility manifest" branding | First real rebuild attempt produces different generated text, breaks trust in the whole manifest (Pitfall 5) | Never — scope the claim honestly from the start |
| One big migration for the whole v2.7 schema | Feels tidier, one PR | Breaks this project's own per-phase rollback discipline, FK ordering risk (Pitfall 8) | Never — contradicts established convention with no offsetting benefit |
| Porting healthcare's `filters.yaml` regexes verbatim to the flagship domain pack "just to have something" | Fast, unblocks the demo | Protects the wrong content shapes; flagship-specific short/structured content still gets dropped (Pitfall 9) | Only as a starting template, never as the final rule set without domain-specific review |
| Reusing DataTrove's `PipelineExecutor` with default local-disk `logging_dir` in production | No new dependency to add immediately | Checkpoint state silently vanishes on container restart, resumability quietly stops working (Pitfall 7) | Only in local dev/CI, never in the deployed environment |
| Keeping the old two-branch payload sniff's silent-skip-on-unknown behavior inside the new split-aware gate | Minimal-diff rewrite | New example lifecycle states (repaired/recoverable) silently escape the contamination check (Pitfall 10) | Never — add an explicit unclassified bucket |

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|--------------|-----------------|-------------------|
| DataTrove `PipelineExecutor`/checkpoint API | Assuming it composes cleanly with a Dagster op's process/storage model because both are "just Python" | Explicitly design the checkpoint-storage location and worker-process model before wiring it in; consider keeping the existing Postgres-ledger checkpoint pattern instead (Pitfall 7) |
| Postgres immutability enforcement | Relying on application code paths only | Use a `BEFORE UPDATE` trigger with an explicit mutable-fields allowlist (Pitfall 4) |
| LiteLLM/Bedrock generation calls | Assuming `temperature` alone (or a seed, if ever added) guarantees reproducible regeneration | Record concrete model version + prompt version + full output; treat regeneration as cache-hit retrieval, not re-invocation (Pitfall 5) |
| MCP tool registry (`agent/registry.py`) | Forgetting the hardcoded `assert len(TOOLS) == 11` when adding/changing dataset-related tools for versioned export | Bump the assertion deliberately as a forcing function whenever the tool surface changes (Pitfall 2) |
| Domain-pack loader (`DomainLoader.from_name`) | Scaffolding the flagship domain pack under `domains/local/<name>/` by default | Ship it at top-level `domains/<name>/` so `klake init --domain <name>` actually resolves it (Pitfall 9) |

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Naive n-gram contamination check re-scanning all dataset examples × all eval examples pairwise | Contamination gate runtime grows quadratically as generated-example volume grows across multiple Dataset Projects | Keep the lineage-graph-based check (`cleaned_document` ID overlap) as the primary O(n) signal; use n-gram/embedding comparison only within already-lineage-flagged candidate pairs, not corpus-wide pairwise | Becomes noticeable once a single project's generated-example count reaches the low thousands, worse across many concurrent Dataset Projects |
| DataTrove `LocalPipelineExecutor` multiprocessing pool spun up inside every Dagster op invocation | Dagster worker resource contention, unpredictable curation-op runtimes | Size `workers`/`tasks` explicitly relative to the Dagster worker's actual CPU allocation; do not default to DataTrove's auto-detected worker count inside a shared/containerized environment | Becomes visible under concurrent Dagster runs on a single node |

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| Treating `license_type="unknown"` as implicitly permissive during the Usage Policy engine rollout | Redistributing/training on content whose license status was never actually reviewed, undermining the entire "auditable usage-policy decisions" goal of this milestone | Fail closed on `"unknown"` for any *new* enforcement point, with an explicit, human-reviewed grandfather list for pre-existing sources (Pitfall 3) — never a blanket pass |
| Storing full LLM request/response payloads in reproducibility manifests without considering what upstream source text they may contain | Manifests could leak content whose redistribution the Usage Policy engine specifically restricted, defeating the policy gate at a different layer | Apply the same usage-policy/license gating to manifest contents as to the dataset export itself — a manifest is a redistribution surface too |
| A DB immutability trigger with an overly broad "mutable fields" allowlist (e.g., allowing `status` itself to be changed back from `released`) | Defeats the entire immutability guarantee via a permitted backdoor field | Keep the allowlist to genuinely append-only/administrative fields (e.g., `retracted_at`), never anything that can move a release back to a mutable state |

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---------|-------------|-------------------|
| MCP/agent tool for dataset export not updated to require/accept a version once versioning ships | An LLM agent calling `export_finetune_dataset` silently gets an unspecified (possibly stale or possibly latest) version with no way to know which | Update the tool's description/schema to make version resolution explicit, and document the default-resolution rule in the tool's own description so an agent calling it without a version knows what it's getting |
| Contamination gate failing closed with an opaque error after the split/gate rework | Operators used to today's clear `direct_overlap_count`/`near_dup_overlap_count` message lose that clarity if the new gate's error message isn't equally decomposed | Preserve and extend the existing decomposed error-message convention (add an `unclassified_count` bucket per Pitfall 10) rather than collapsing to a single opaque count |
| Domain-pack authors for the flagship dataset given no guidance on what a Quality Contract's domain-level rule set should contain | Ad hoc, under-tested `filters.yaml`-equivalent for the new domain, discovered broken late | Ship the Quality Contract phase with a documented "how to add domain-specific allowlist rules" guide/template, informed by the healthcare precedent, before the flagship phase needs it |

## "Looks Done But Isn't" Checklist

- [ ] **Split column migration:** Often missing a backfill pass for pre-existing `DatasetExample` rows — verify `SELECT count(*) FROM dataset_examples WHERE split IS NULL` is zero after migration, not just that the column exists.
- [ ] **Usage Policy gate:** Often missing a grandfather/backfill decision for existing sources — verify the gate runs in report-only mode against the real 34-source corpus with zero unexpected export failures before it's wired to block anything.
- [ ] **Immutable Dataset Release:** Often only application-layer-checked — verify a raw SQL `UPDATE` against a `released` row is rejected by the database itself, not just by application code.
- [ ] **Reproducibility manifest:** Often silently implies LLM-generated content will regenerate identically — verify the manifest schema and its rebuild-equivalence test explicitly separate deterministic-tier claims from LLM-generation-tier claims.
- [ ] **Contamination gate rework:** Often keeps the old two-branch (question/instruction) sniff's silent-skip-on-unknown behavior under a new column name — verify there's an explicit "unclassified" bucket, not silent exclusion.
- [ ] **CurationEngine DataTrove backend:** Often demoed working in local dev (local-disk checkpoint) without ever being tested against the actual production storage backend — verify checkpoint/resume is tested against S3/MinIO, or against the Postgres-ledger alternative, not local disk.
- [ ] **Migration count:** Often ships as one large migration "to keep it simple" — verify the number of new Alembic revisions this milestone roughly matches the number of schema-touching phases.
- [ ] **Flagship domain pack:** Often scaffolded without a `filters.yaml`-equivalent Quality Contract rule set — verify a must-not-reject fixture set exists and has been reviewed by someone who knows the flagship domain, mirroring the healthcare precedent.
- [ ] **MCP tool count assertion:** Often forgotten when dataset-related tool signatures change — verify `assert len(TOOLS) == N` in `agent/registry.py` was deliberately updated, not left stale.

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|-----------------|
| Split column shipped without backfill, discovered post-release | LOW | Run a corrective backfill UPDATE using the same payload-shape derivation rule as the old sniff; add the missing migration-verification assertion; no data is lost since payload shape is still present |
| Usage Policy engine blocking existing exports | LOW–MEDIUM | Add the grandfather/legacy-unreviewed status retroactively; re-run the gate in report-only mode first before re-enabling enforcement |
| Immutable release mutated via a bypassed application check | MEDIUM–HIGH | Depends whether a DB trigger exists as a second layer; if not, restore from the WORM raw zone + regenerate the release deterministically where possible (deterministic tier only, per Pitfall 5), and add the trigger going forward |
| One giant migration shipped, later phase needs to touch an earlier table awkwardly | MEDIUM | Add a new, correctly-numbered follow-up migration rather than editing the shipped one; document the FK dependency retroactively |
| Flagship domain pack's substance gate drops load-bearing short content | LOW–MEDIUM | Re-run in report-only mode, build the missing normative allowlist from the rejection list (same recovery pattern this project already used for healthcare in Phase 19/20), re-export |
| DataTrove checkpoint state lost due to local-disk default | LOW | Reprocessing from the immutable raw/silver zones is always possible (nothing is destroyed, only redundant recompute is incurred); fix the `logging_dir` configuration going forward |

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|-------------------|----------------|
| 1: Split/status columns silently default existing rows | Deterministic splits + contamination gate phase | Backfill completeness assertion + old-code-path regression test |
| 2: Versioning breaks 4 existing `export_finetune_dataset` call sites | Dataset Project + Specification foundation phase | Test pinning the no-version-argument resolution rule; all 4 call sites updated in one commit |
| 3: Usage Policy gate fails closed on `license_type="unknown"` | Usage Policy engine phase | Report-only run against the real 34-source corpus, zero unexpected failures, human-reviewed grandfather list |
| 4: Application-only immutability is bypassable | Immutable Dataset Release phase | Raw-SQL `UPDATE` against a released row rejected by the database itself |
| 5: Reproducibility manifest overpromises LLM-tier replay | Reproducibility manifest + rebuild-equivalence test phase | Two separate tests: deterministic-tier bit-identical rebuild; LLM-tier served from cache, not re-invoked |
| 6: Naive n-gram contamination misses paraphrase, flags boilerplate | Deterministic splits + contamination gate phase | Paraphrase-pair fixture caught via lineage; boilerplate-only-overlap fixture not flagged as real contamination |
| 7: DataTrove real executor reintroduces the rejected I/O anti-pattern | CurationEngine + DataTrove backend phase | Kill/restart-mid-run integration test against production storage backend, not local disk |
| 8: One giant migration breaks per-phase rollback discipline | Cross-cutting, owned by roadmap/requirements phase | Migration count roughly equals schema-touching phase count; each `downgrade()` exercised in CI |
| 9: Flagship non-healthcare pack lacks domain-tuned quality rules | Flagship dataset phase (mechanism designed one phase earlier, in the Quality Contract phase) | Domain-reviewed must-not-reject fixture set in CI before release |
| 10: Contamination check silently drops unrecognized payload/status shapes | Deterministic splits + contamination gate phase | Fixture with unrecognized split/status surfaces as a countable "unclassified" result, not silence |

## Sources

- `src/knowledge_lake/registry/models.py` (Dataset/DatasetExample schema, `license_type`), `src/knowledge_lake/registry/repo.py` (`get_or_create_dataset`, `update_dataset_export`), `src/knowledge_lake/pipeline/export.py` (`check_train_eval_contamination`, `export_finetune_dataset`, `_enforce_no_contamination`), `src/knowledge_lake/pipeline/curate.py` (DataTrove anti-pattern docstring), `src/knowledge_lake/pipeline/datasets.py` (LiteLLM generation calls, temperature, cache keys), `src/knowledge_lake/agent/registry.py` (`assert len(TOOLS) == 11`, MCP call sites), `src/knowledge_lake/registry/alembic/versions/*` (migration history/convention), `domains/aviation/`, `domains/climate/`, `domains/healthcare/filters.yaml` (domain-pack maturity gap) — all read directly from this repository, 2026-07-19.
- Prior `.planning/research/PITFALLS.md` (v2.6-era version, now superseded by this file) — reviewed for cross-milestone continuity; its "graceful degradation becomes a hazard under retrofit" and "a recorded lesson is not an enforced one" framings directly inform this document's approach.
- [Why Temperature=0 Doesn't Guarantee Determinism in LLMs](https://mbrenndoerfer.com/writing/why-llms-are-not-deterministic) — MEDIUM confidence, cross-checked against multiple independent sources below.
- [Does Temperature 0 Guarantee Deterministic LLM Outputs?](https://www.vincentschmalbach.com/does-temperature-0-guarantee-deterministic-llm-outputs/) — MEDIUM confidence.
- [The Temperature=0 Myth: Why Your LLM Still Isn't Deterministic](https://mikulskibartosz.name/why-temperature-0-isnt-deterministic) — MEDIUM confidence.
- [vLLM Discussion #17166: why temperature=0, top_p=1, seed=42 is still not enough](https://github.com/vllm-project/vllm/discussions/17166) — MEDIUM confidence, practitioner-verified.
- [PostgreSQL Documentation: Trigger Functions](https://www.postgresql.org/docs/current/plpgsql-trigger.html) — HIGH confidence, official documentation.
- [Triggers to prevent insertions, updates, and/or deletions on a table in PostgreSQL](https://gist.github.com/diraneyya/ada8660d2e51a1d0949d471e72c81aba) — MEDIUM confidence, community pattern reference.
- [Audit trigger — PostgreSQL wiki](https://wiki.postgresql.org/wiki/Audit_trigger) — MEDIUM confidence, community-maintained but widely cited reference pattern.
- DataTrove source (`datatrove/executor/base.py`, `datatrove/executor/local.py`, `datatrove/io.py`) as vendored in this project's `.venv` — HIGH confidence, read directly.

---
*Pitfalls research for: Governed dataset release lifecycle (Dataset Project/Specification, Usage Policy, Quality Contract, partitions, CurationEngine, generated-example validation, splits/contamination, immutable Releases + reproducibility manifests, diffing, lineage explorer, Evaluation Run foundation) added to the existing Knowledge Lake ingestion/RAG pipeline*
*Researched: 2026-07-19*
