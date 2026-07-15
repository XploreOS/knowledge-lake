---
scope: cross-cutting
name: E2E Test & Codebase Gap Analysis
audited: 2026-07-15T02:48:00Z
audited_against: 49c77f4
status: findings_open
method: >
  Live end-to-end run against the running stack (postgres, minio, qdrant,
  litellm, dagster, searxng). A new `aviation` domain pack was scaffolded via
  `klake domain new`, authored, registered, and driven through the full pipeline
  to gold-zone outputs using the FAA Airplane Flying Handbook Ch.4
  (public domain, 4.6 MB, 19pp -> 38 sections -> 51 chunks).
e2e_result: completed
counts:
  high: 3
  medium: 6
  low: 8
  total: 17
  verified_working: 7
tests:
  unit: 828 passed
  failed: 6
  errors: 13
  xpassed: 42
  note: "Failures and errors are pre-existing, not caused by the E2E run."
findings:
  - id: KL-01
    severity: high
    area: export
    reproduced: true
    title: Domain-scoped exports are not domain-scoped
  - id: KL-02
    severity: high
    area: llm/cost
    reproduced: true
    title: LLM budget caps under-enforce by 2.4x-9x
  - id: KL-03
    severity: high
    area: ci/tests
    reproduced: true
    title: CI never runs the 211 integration tests, and they have rotted
  - id: KL-04
    severity: medium
    area: search
    reproduced: true
    title: min-quality-score silently returns nothing for the documented happy path
  - id: KL-05
    severity: medium
    area: curate/index
    reproduced: true
    title: curate composite score never reaches search
  - id: KL-06
    severity: medium
    area: dagster/index
    reproduced: false
    title: Payload enrichment is a scheduling race, with no repair path
  - id: KL-07
    severity: medium
    area: security/ssrf
    reproduced: true
    title: SSRF guard misses several reserved ranges, including 0.0.0.0
  - id: KL-08
    severity: medium
    area: ops/docker
    reproduced: true
    title: API container serves 2 of 29 routes and reports healthy
  - id: KL-09
    severity: medium
    area: cli
    reproduced: true
    title: tree-search is unreachable from the CLI
  - id: KL-10
    severity: low
    area: tests
    reproduced: true
    title: 42 xpassed tests with xfail_strict unset
  - id: KL-11
    severity: low
    area: wiki
    reproduced: true
    title: Wiki summaries are cut mid-sentence
  - id: KL-12
    severity: low
    area: docs
    reproduced: true
    title: README documents the wrong model alias for enrich
  - id: KL-13
    severity: low
    area: cli
    reproduced: true
    title: Rich markup eats the regex in CLI help
  - id: KL-14
    severity: low
    area: export/lineage
    reproduced: true
    title: Two dst_ IDs per export
  - id: KL-15
    severity: low
    area: registry
    reproduced: true
    title: Domain is untyped JSON on sources.config
  - id: KL-16
    severity: low
    area: architecture
    reproduced: true
    title: Domain packs cannot contribute pipeline behavior
  - id: KL-17
    severity: low
    area: drift
    reproduced: true
    title: Assorted drift
verified_working:
  - lineage
  - raw_zone_immutability
  - litellm_only_constraint
  - plugin_swappability
  - domain_scaffolding
  - contamination_hard_gate
  - parse_and_retrieval_quality
---

# E2E Test & Gap Analysis — klake

**Audited:** 2026-07-15 against `49c77f4`
**E2E:** `klake domain new aviation` → authored pack → `init` → `ingest-url` → `parse` → `clean` → `curate` → `enrich` → `index` → `search` → `lineage` → `export` → `export-wiki`
**Result:** Pipeline completed end-to-end. 17 findings — 3 high, 6 medium, 8 low.

---

## The headline

The pipeline works. Every stage from `klake domain new aviation` through gold-zone
export completed successfully on a real 4.6 MB FAA PDF, and the framework's
central promise — lineage from raw source to final artifact — holds up cleanly.
The problems are not in whether it runs; they're in **what it silently claims
about what it produced**.

Three findings share one root cause: **a label asserts something the data doesn't
satisfy, and nothing fails.** A domain-tagged export containing 62% foreign data.
A budget cap that permits 9× its configured spend. A green CI badge over 211
tests that never run.

---

## High severity

Reachable in the documented production path, silent when wrong, and consequential
for data governance or cost.

### KL-01 — Domain-scoped exports are not domain-scoped

**What.** `export_rag_corpus()`, `export_pretrain_corpus()` and
`export_finetune_dataset()` all accept a `domain` kwarg. It is used *only* to
build the S3 path segment and the object tag — never to filter rows. The row
query is `list_artifacts_by_type(session, "chunk")`: the entire corpus, every
domain.

**Reachable.** Live via Dagster — the documented production orchestrator.
`ExportRagConfig.domain` is passed straight through at
`dagster_defs/assets.py:799`: `export_rag_fn(domain=config.domain or None, …)`.
Same at `:854` and `:912`. The CLI and API never pass it, so they are honest by
omission.

**Evidence.**

```
export_rag_corpus(domain="aviation") →
  s3://klake-data/gold/aviation/rag_corpus/dst_019f6399….parquet   (tagged domain=aviation)

domain breakdown of rows INSIDE that file:
  ┌─────────────────────┬─────┐
  │ functional-medicine ┆  53 │  ← foreign
  │ aviation            ┆  51 │
  │ null                ┆  29 │  ← foreign
  └─────────────────────┴─────┘
  62% of the "aviation" export is not aviation data.
```

**Impact.** The path and the S3 tag both assert a domain the contents don't
satisfy. For a framework whose premise is domain packs and export contracts —
and which tracks per-source licenses — this silently mislabels provenance.
Exporting one domain's corpus under another's label is a licensing and governance
problem, not just a filtering bug.

**Fix.** Filter rows by domain when `domain` is passed, or rename the parameter
to `path_label` and refuse to tag what wasn't filtered. Note `export-wiki`
already does this correctly — it *requires* `--domain` and genuinely scopes its
output — so the pattern is proven in-repo.

---

### KL-02 — LLM budget caps under-enforce by 2.4×–9×

**What.** `bootstrap_llm_pricing()` registers prices keyed by *Bedrock model ID*
(`bedrock/us.anthropic.claude-haiku-4-5…`). But calls go through the LiteLLM
proxy keyed by *task alias* (`cheap_model`). The keys never match, so
`litellm.completion_cost()` raises on **every single call** and
`compute_call_cost()` silently falls back to a flat estimate that is materially
cheaper than the real price.

**Evidence.** `bootstrap_llm_pricing(s)` runs at `enrich.py:367` — immediately
before the call. The warning still fires, every time:

```
{"error": "This model isn't mapped yet. model=cheap_model,
           custom_llm_provider=openai", "event": "enrich.cost_calc_failed"}

For 1000 in + 1000 out tokens:
  reported (fallback) : $0.002000
  true cheap_model    : $0.004800   → understated 2.40×
  true strong_model   : $0.018000   → understated 9.00×

  budget_usd = 5.0  behaves like  $12.00 (cheap) / $45.00 (strong)
```

**Impact.** The gate at `enrich.py:357` (`current_spend >= s.enrich.budget_usd`)
reads an accumulator fed entirely by the understated estimate, so every
`budget_usd` in the codebase is 2.4–9× looser than written. `eval_model` is worse
still: it is never registered at all — only `cheap_model_bedrock_id` and
`strong_model_bedrock_id` are — so it could never be priced even if the key
matched.

**Fix.** Register prices under the alias names actually sent (`cheap_model`,
`strong_model`, `eval_model`), or read `response._hidden_params["response_cost"]`
which the proxy already computes. Add `eval_model` pricing. Consider making a
pricing-lookup miss loud rather than a silent fallback — a cost guardrail that
quietly guesses is worse than one that fails.

---

### KL-03 — CI never runs the 211 integration tests, and they have rotted

**What.** `.github/workflows/ci.yml:69` runs
`uv run pytest tests/unit -m "not browser" -q`. That is the only test invocation.
All 29 files / 211 tests under `tests/integration/` never execute in CI — and
they are now broken.

**Evidence.**

```
$ uv run pytest -q
6 failed, 828 passed, 5 skipped, 12 xfailed, 42 xpassed, 13 errors

— 6 failures, stale mocks: production put_raw() gained a `domain` kwarg,
  the test doubles never followed —
  TypeError: mock_put_raw() got an unexpected keyword argument 'domain'

— 13 errors, missing fixture DB no documented step creates —
  psycopg.OperationalError: database "klake_test" does not exist
```

**Impact.** The integration suite is where this project's real risk lives —
lineage continuity across stages, registry writes, S3 round-trips. It currently
provides zero regression protection behind a green badge. The `put_raw(domain=…)`
drift is the tell: a production signature changed, the integration tests that
would have caught it were never run, and the rot went unnoticed. KL-01 and KL-04
are precisely the class of bug this suite exists to catch.

**Fix.** Add a CI job with Postgres/MinIO/Qdrant services that creates
`klake_test` and runs `tests/integration`. Repair the six stale mocks. Set
`xfail_strict = true` (see KL-10).

---

## Medium severity

Real defects with a workaround, a narrower blast radius, or a required
precondition.

### KL-04 — The quality filter silently returns nothing for the documented happy path

**What.** The README presents `ingest-url` as the "full pipeline shortcut" and,
thirty lines later, documents `search --min-quality-score 0.5`. Run both and you
get zero results, with no warning.

`ingest-url` runs ingest→parse→chunk→embed→index — it skips clean, enrich and
curate. Payload `quality_score` is written only from a sibling *enriched*
artifact (`index.py:131-137`). A Qdrant `Range(gte=…)` filter excludes points
whose key was never written, so every chunk disappears.

**Evidence.**

```
$ klake search "…energy management…" --collection klake_chunks --top-k 3
  [1] score=1.0000  …  quality_score: None   ← indexed fine

$ klake search "…energy management…" --min-quality-score 0.5
  No results for query   ← same corpus, silently empty
```

**Fix.** Either have `ingest-url` run the full chain, or warn when filtering on a
payload key that is null across the collection. At minimum, correct the README.

---

### KL-05 — `curate`'s composite score never reaches search

**What.** `curated_document` and `enriched_document` are siblings — both parent
off `cleaned_document` (D-01). But `index()` resolves only the enriched one via
`get_enriched_artifact_for_parsed()`. The DataTrove-style composite score that
`klake curate` computes is never read by the indexer.

Observed: curate produced `quality_score: 0.797` for the aviation doc. That
number cannot influence retrieval. The only payload score that exists comes from
LLM enrichment — which is Bedrock-gated and costs money. So the free,
deterministic quality gate is decorative for search, and the paid one is
mandatory.

Curate also warns `No enriched_document sibling found; defaulting
enrich_quality_score to 0.5` — its composite silently blends in a hardcoded
constant whenever enrichment hasn't run.

**Fix.** Have the indexer prefer the curated score (or carry both as distinct
payload keys, e.g. `curation_score` vs `enrichment_score`) rather than collapsing
two different measurements into one ambiguous field.

---

### KL-06 — Payload enrichment is a scheduling race, with no repair path

**What.** `index_chunks` reads the enriched sibling *at runtime*. But D-01
deliberately makes `enrich_document` a parallel branch that, in its own
docstring, "does not block chunk_document". Nothing orders them.

```
clean_document ──┬── chunk_document → embed_chunks → index_chunks
                 │                                        ↑
                 ├── enrich_document ─── read at runtime ─┘  (not a dependency)
                 └── curate_document_asset
```

Whether `quality_score`, `document_type`, `keywords` and `title` land in the
payload depends on which branch Dagster happens to schedule first —
nondeterministic under a multiprocess executor.

**Worse.** There is no repair. `klake index` / `reindex` copies points verbatim
into the new physical collection — it does not recompute payloads from the
registry. Confirmed: after running enrich *and then* reindexing,
`--min-quality-score 0.5` still returned nothing. Once a chunk is indexed
pre-enrichment, only a full re-ingest fixes it.

**Fix.** Make `index_chunks` depend on `enrich_document` (accepting the
serialization), or add a payload-refresh mode to reindex that re-derives from the
registry rather than copying.

---

### KL-07 — SSRF guard misses several reserved ranges, including `0.0.0.0`

**What.** `validate_public_url()` is otherwise well built — https-only,
`getaddrinfo()` across all A/AAAA records, IPv4-mapped-IPv6 unwrapping, and
redirect re-validation on every hop. But its blocklist is a hand-rolled list of
nine networks, and hand-rolled lists miss things.

**Evidence.**

```
ADDRESS            BLOCKED?     is_global  NOTE
0.0.0.0            >>> ALLOWED  False      'this host' — reaches localhost on Linux
100.64.0.1         >>> ALLOWED  False      CGNAT (RFC 6598)
198.18.0.1         >>> ALLOWED  False      benchmark (RFC 2544)
192.0.0.1          >>> ALLOWED  False      IETF protocol assignments
240.0.0.1          >>> ALLOWED  False      reserved / future use
::                 >>> ALLOWED  False      IPv6 unspecified
10.0.0.1           blocked      False      control ✓
169.254.169.254    blocked      False      cloud IMDS — control ✓
127.0.0.1          blocked      False      control ✓
```

**Impact.** The common cases (RFC-1918, IMDS, loopback) are correctly blocked, so
this is defense-in-depth rather than an open door — reaching it needs a hostname
that resolves into one of the missed ranges. But `klake discover` auto-registers
URLs harvested from SearXNG, so attacker-influenced hostnames do reach this
guard.

Related, and inherent to the design: validation resolves the hostname, then the
HTTP client resolves it *again* when connecting — the classic DNS-rebinding
TOCTOU. Pinning the validated IP (connect-by-IP with a Host header) closes it.

**Fix.** One line: `if not addr.is_global: raise`. The `is_global` column above
shows stdlib already classifies every missed range correctly. Keep
`_PRIVATE_NETS` as documentation.

---

### KL-08 — The API container serves 2 of 29 routes, and reports healthy

**What.**

```
repo      src/knowledge_lake/api/app.py       60,750 bytes — 29 routes
container /app/src/knowledge_lake/api/app.py   1,296 bytes —  2 routes  (dated Jul 2)

$ curl localhost:8000/openapi.json  →  GET /health          …and nothing else
$ docker compose ps                 →  api  Up 3 days (healthy)
```

The Dockerfile bakes source in via `COPY src/ ./src/` with no volume mount, and
`docker compose up -d` — exactly what the README prescribes — will not rebuild an
existing image. The healthcheck probes only `/health`, which happens to be one of
the two surviving routes, so the container certifies itself healthy while 27 of
29 endpoints 404.

**Impact.** Partly a local artifact — these containers are 13 days stale. But the
design makes it a trap rather than an accident: nothing surfaces the drift, and
the health signal actively vouches for it. Same failure class as the known
Dagster code-location staleness.

**Fix.** Mount `./src` for dev, and/or have the healthcheck assert a
version/route-count fingerprint that a stale image cannot satisfy. Document
`up -d --build`.

---

### KL-09 — `tree-search` is unreachable from the CLI

**What.** The CLI ships the consumer (`klake tree-search`) but not the producer.
Building a tree index is only possible through the `tree_index_document` Dagster
asset — there is no `klake tree-index` command. The registry holds **0**
`tree_index` artifacts, and the command answers `No results` as though the query
simply missed.

**Fix.** Expose a `tree-index` command, and distinguish "no tree index has been
built" from "no matches" in the output.

---

## Low severity

Hygiene, drift, and papercuts — individually small, collectively the texture a
reviewer notices.

### KL-10 — 42 xpassed tests with `xfail_strict` unset

Markers like *"Wave 0 stub — implementation pending"* sit on features that now
work (`test_domain_loader`, `test_cli_init_index`, `test_api_search_mode`…). With
`xfail_strict` unset these can never fail the build: if the feature regressed, CI
would record a tidy `xfail` and stay green. Forty-two tests that look like
coverage and function as none.

### KL-11 — Wiki summaries are cut mid-sentence

`wiki.py:538` — `lead = (doc["summary"] or "")[:500]`. A hard character slice: no
word boundary, no ellipsis. The stored summary is fine; the published page is
what breaks:

```
…pilots must use indicated altitude and indicated airspeed
as their frame of reference rather than▮   ← page ends here

stored value continues: "…rather than height above ground or groundspeed."
```

This is the human-facing deliverable of the whole pipeline, and it reads as
truncated output.

### KL-12 — README documents the wrong model alias for `enrich`

README:208 says enrich "Calls LiteLLM (`strong_model` alias → Bedrock)".
`settings.py:160` defaults `model_alias = "cheap_model"`, and the run log confirms
`model=cheap_model`. A cost-relevant discrepancy.

### KL-13 — Rich markup eats the regex in CLI help

`klake domain new --help` renders *"must match `^{0,63}$`"*. The pattern is
correct in source (`^[a-zA-Z][a-zA-Z0-9_-]{0,63}$`) — Rich parses the character
classes as markup tags and strips them. Escape the brackets or disable markup for
that string. The same regex is also duplicated across `cli/app.py:1138` and
`domains/scaffold.py:31`.

### KL-14 — Two `dst_` IDs per export

Each export mints `new_id("dataset")` for the *filename*, then `create_dataset()`
mints another for the *row* — so `dataset_id=dst_…87d8` points at
`…87ce.parquet`. Traceability survives (the `name` and `storage_uri` both carry
the file's ID), so this is confusion rather than breakage — but "which dst_ is
this?" is a question a lineage-first framework shouldn't provoke.

### KL-15 — Domain is untyped JSON on `sources.config`

`sources` has no `domain` column; domain lives inside the `config` JSON blob and
is duplicated into the Qdrant payload. It's a first-class concept in the CLI
(`--domain`), the storage layout (`raw/{domain}/…`) and the pack system — but
it's unindexed, unvalidated, and unconstrained in the registry.

### KL-16 — Domain packs cannot contribute pipeline behavior

A pack may ship `domain.yaml`, `sources.yaml`, `taxonomy.yaml`, `prompts/` and a
validator — data and text, no behavior. Meanwhile `healthcare_e2e_job` lives in
framework core (`dagster_defs/assets.py:928`) and is registered in
`definitions.py:85`, so every deployment of a "domain-agnostic framework" ships a
job named for one domain.

In fairness the job's *selection* is entirely generic — it's misnamed, not
domain-coupled, and the aviation pack could run it as-is. The gap is the missing
extension point: there's no way for `aviation` to contribute an `aviation_e2e_job`
without editing framework source.

### KL-17 — Assorted drift

- `put_raw()`'s docstring documents `raw/{source_id}/{sha256}.{ext}`; actual keys
  are `raw/{domain}/{source_id}/…` — the same `domain` kwarg that broke the mocks
  in KL-03.
- No `LLMGatewayPlugin` protocol, though the architecture doc lists LLM gateways
  alongside parsers and vector stores as replaceable plugins. LiteLLM is imported
  directly in `enrich`, `datasets`, `tree_index`, `scorer`.
- `datasets.py` hardcodes `"openai/eval_model"` / `"openai/strong_model"` while
  `enrich.py` reads its alias from settings — the alias is configurable in one
  place and not the other.
- `domains/models.py:78` — a framework-core dataclass documented as *"Result from
  HealthcareValidator"*.

---

## What holds up

Verified by exercise, not by reading. These are load-bearing and they work.

| Capability | Verdict | Evidence |
|---|---|---|
| **Lineage** — the core promise | holds | 4-node chain enriched→cleaned→parsed→raw, all six fields present, `pipeline_version` git-pinned to `0.1.0+49c77f4`. |
| **Raw-zone immutability** | holds | Content-addressed keys, registry no-op on hash hit, `head_object` guard. `delete_object` appears only in the gold-zone wiki path. |
| **LiteLLM-only constraint** | holds | Zero `anthropic`/`openai` SDK imports; boto3 confined to S3; no hardcoded provider model IDs outside settings. |
| **Plugin swappability** | holds | `importlib.metadata.entry_points` resolution across 7 typed Protocols; builtins never read `os.environ` directly. |
| **Domain scaffolding** | holds | `domain new` → author → `init` is a genuine workflow. Idempotent re-registration, crawl/upload split honored, prompt-injection defense in the generated template. |
| **Contamination hard gate** | holds | Failed closed on a true positive from pre-existing data and refused to write. Correct behavior — see caveat below. |
| **Parse & retrieval quality** | holds | Docling: 19pp → 38 sections, quality 0.989. Search returned the energy-management chapter summary as top hit. Enrichment produced accurate aviation metadata from the pack's own prompt. |

One caveat on the contamination gate: it is *full-corpus*, not domain-scoped. A
single overlapping healthcare document blocked the brand-new aviation export — a
domain that shares nothing with it. Fail-closed is right; coupling every domain's
exports to every other domain's state is the same missing dimension as KL-01.

---

## Suggested fix order

1. **KL-03 first.** Wire integration tests into CI before fixing anything else —
   otherwise the fixes below have nothing holding them in place, which is how
   KL-01 arrived.
2. **KL-02** — a one-line key change; stops silent 9× budget overrun.
3. **KL-07** — a one-line `is_global` change; closes the reserved-range gap.
4. **KL-01** — decide whether `domain` filters or merely labels, then make the
   code and the S3 tag agree.
5. **KL-04 / KL-05 / KL-06** — these are one decision: settle what
   `quality_score` in the payload actually means, who writes it, and when.
6. The rest as hygiene.

---

## Method note

Every finding marked `reproduced: true` in the frontmatter was confirmed by
execution or by a probe script, not inferred from reading. KL-06 is marked
`reproduced: false`: the scheduling race is established by reading the asset
graph (`index_chunks` has no dependency on `enrich_document`) and its consequence
was observed, but the race itself was not forced under a multiprocess executor.

The E2E left one untracked artifact — `domains/aviation/` — and modified no
tracked file.
