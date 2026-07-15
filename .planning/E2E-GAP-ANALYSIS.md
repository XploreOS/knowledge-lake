---
scope: cross-cutting
name: E2E Test & Codebase Gap Analysis
audited: 2026-07-15T02:48:00Z
audited_against: 49c77f4
status: findings_open
resolved:
  - id: KL-07
    resolved: 2026-07-15
    quick_task: 260715-5pb
    commits: [5b5bcd7]
    fix: >
      Replaced the hand-rolled _PRIVATE_NETS membership test with
      `not addr.is_global`, keeping the list as documentation. Verified through
      the real validate_public_url() in BOTH directions: 0.0.0.0, 100.64.0.1,
      198.18.0.1, 192.0.0.1, 240.0.0.1 and :: now blocked; controls (10.0.0.1,
      169.254.169.254, 127.0.0.1) still blocked; public IPv4/IPv6 and a live
      www.faa.gov resolution still ALLOWED — no over-blocking, crawling intact.
      DNS-rebinding TOCTOU remains open by design (separate change).
  - id: KL-04
    resolved: 2026-07-15
    quick_task: 260715-5pb
    commits: [6a1e9b4, 8b9e27b, 76963c2]
    fix: "See KL-06 — KL-04/05/06 were one problem and one fix."
  - id: KL-05
    resolved: 2026-07-15
    quick_task: 260715-5pb
    commits: [6a1e9b4, 8b9e27b, 76963c2]
    fix: "See KL-06 — KL-04/05/06 were one problem and one fix."
  - id: KL-06
    resolved: 2026-07-15
    quick_task: 260715-5pb
    commits: [6a1e9b4, 8b9e27b, 76963c2]
    decision: "Make the real chain explicit; payload quality_score = curated ?? enriched ?? None (user decision)"
    fix: >
      D-01's "parallel branches that do not block" was false parallelism:
      curate reads the enriched sibling for the 40% enrich term of its composite
      (defaulting to 0.5 when absent) and index reads it for the payload.
      Measured on the real aviation doc: the SAME document scored 0.797 when
      curate ran before enrich vs 0.965 after — a 21% swing from scheduling
      order alone. Added non-data deps edges (curate deps=[enrich],
      chunk deps=[curate]) making the order clean → enrich → curate → chunk →
      embed → index; data inputs unchanged. Added
      get_curated_artifact_for_parsed and payload precedence curated ??
      enriched ?? None. Added opt-in `klake index --refresh-payload` to repair
      already-indexed chunks (reindex previously copied points verbatim, so
      pre-enrichment payloads were unrepairable without full re-ingest).
      Live proof: 5 aviation chunks went from quality_score None → 0.797, and
      `search --min-quality-score 0.5` now returns hits for that document — the
      exact query KL-04 documented returning nothing.
    followup_caught: >
      The first attempt left core_pipeline_e2e_job's selection excluding
      curate_document_asset. Dagster drops a deps= edge whose target is outside
      the selection, so the race was still live in the main E2E job. Fixed in
      76963c2, plus a vacuous-guard fix: job.asset_layer.asset_graph IS
      job-scoped (8 keys vs global 13) but contains curate as a NON-EXECUTABLE
      node, so a pure ancestry assertion passed while the job never ran curate.
      The test now intersects ancestry with executable_asset_keys.
      Mutation-verified: removing curate from the selection fails 2 tests.
  - id: KL-11
    resolved: 2026-07-15
    quick_task: 260715-5pb
    commits: [8ee9082]
    fix: >
      Added truncate_lead(): prefers the last sentence-ending punctuation within
      the limit, falls back to the last word boundary, appends an ellipsis only
      when truncation occurred. summary_excerpt_chars (500) unchanged — the
      limit was fine, the slicing wasn't. Short summaries pass through
      byte-identical with no ellipsis.
  - id: KL-16
    resolved: 2026-07-15
    quick_task: 260715-5pb
    commits: [dbd8abd]
    decision: "Rename only; defer the pack-contributed-jobs extension point to the roadmap (user decision)"
    fix: >
      Renamed healthcare_e2e_job → core_pipeline_e2e_job (symbol + Dagster
      name=), dropped "healthcare" from the description, updated
      definitions.py and the two doc references. The asset selection was always
      generic. No domain name remains in framework core.
    still_open: >
      The real gap — domain packs cannot contribute Dagster jobs without editing
      framework source — is DEFERRED to the roadmap, not fixed. Packs remain
      data+prompts only.
  - id: KL-10
    resolved: 2026-07-15
    quick_task: 260715-5pb
    commits: [9d3f98b, bf8b6ac]
    fix: >
      Removed 42 stale xfail markers from tests that now XPASS (re-measured
      after the other fixes, per the ordering constraint — not reused from the
      audit). Left all 12 genuine XFAIL markers in place; xfail_strict only
      fails on XPASS. Then set xfail_strict = true. Mutation-verified: marking a
      passing test xfail now fails the run with XPASS(strict).
      Final: 943 passed, 0 xpassed, 0 failed, 0 errors, 12 xfailed.
    value: >
      The markers were hiding real bugs. Removing them surfaced KL-18 (two API
      endpoints returning 500) and KL-19 (4 tests that can never pass). This is
      precisely what a lying xfail marker costs.
  - id: KL-01
    resolved: 2026-07-15
    quick_task: 260715-51d
    commits: [635e96a, fa3a1ca, 6ea82c2]
    decision: "domain= FILTERS rows, it does not merely label the path (user decision)"
    fix: >
      All three export functions now filter rows by source domain via
      registry_repo.get_domain_for_source when domain is not None (strict
      equality; null-domain rows excluded). domain=None is unchanged — no
      filter, all domains, '_unclassified' path — with a regression test
      pinning that default. Filtering is now reachable: added --domain/-D to
      `klake export` and an optional `domain` field to the API ExportRequest
      (previously only Dagster could pass it). Verified on the same real data
      that exposed the bug: gold/aviation/rag_corpus/*.parquet went from
      51 aviation + 53 functional-medicine + 29 null (62% foreign) to
      51 rows, 100% aviation.
    known_limitation: >
      With domain=None the '_unclassified' path segment and S3 tag still
      describe an all-domain export. Renaming it would change the STORE-03
      gold-zone layout — deliberately deferred.
  - id: KL-02
    resolved: 2026-07-15
    quick_task: 260715-51d
    commits: [4396e56, fa3a1ca]
    fix: >
      A live probe showed the LiteLLM proxy already returns the correct cost in
      response._hidden_params["response_cost"] — the hand-maintained settings
      price table was both wrong and unnecessary. compute_call_cost() now
      prefers response_cost, falls back to completion_cost(), then to the flat
      estimate (now logged as an explicit under-estimation warning, not a bare
      cost_calc_failed). bootstrap_llm_pricing() registers under the ALIAS names
      actually sent (cheap_model/strong_model/eval_model) instead of Bedrock IDs,
      so the fallback resolves too; eval_model_* price settings added. Verified
      on a live eval_model call: cost went from $0.0002525 WITH a cost_calc_failed
      warning to $0.0020427 with NO warning — ~8x higher, i.e. the real price.
      Budget caps now mean what they say.
  - id: KL-03
    resolved: 2026-07-15
    quick_task: 260715-4b9
    commits: [c75468e, 9827c61, 4ab0744, 92ae035, ea14046]
    fix: >
      Root cause was infra/postgres/init.sql never creating the klake_test
      database the tests expect — so the documented local fallback
      (`make up && make test-integration`) was broken too, not just CI.
      Added klake_test to init.sql; repaired the 6 stale mock_put_raw
      signatures (added domain/tags to match production); replaced the
      "intentionally not run" comment block in ci.yml with a real integration
      job that brings up the project's own compose stack. Verified:
      `pytest tests/integration -m "not browser"` → 193 passed, 0 failed,
      0 errors (was 6 failed / 13 errors). Full suite → 859 passed, 0 failed.
      xfail_strict deliberately NOT flipped — that is KL-10 and requires
      removing the 42 stale markers first.
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
  discovered_during_remediation: 2   # KL-18, KL-19 — see `discovered` below
  open: 9
  resolved: 10
  high_open: 0
  verified_working: 7
discovered:
  - id: KL-18
    severity: high
    area: api
    reproduced: true
    found: 2026-07-15
    found_by: "KL-10 remediation — a stale xfail marker was hiding it"
    title: "GET /documents and GET /datasets return 500 (DetachedInstanceError)"
    status: open
  - id: KL-19
    severity: low
    area: tests
    reproduced: true
    found: 2026-07-15
    found_by: "KL-10 remediation"
    title: "4 mode-forwarding tests patch the wrong target and can never pass"
    status: open
tests:
  at_audit_time:
    combined: 828 passed
    failed: 6
    errors: 13
    xpassed: 42
    note: >
      828 is the COMBINED unit+integration run (`uv run pytest -q`), not
      unit-only — an earlier revision of this file mislabelled it as `unit`.
      Corrected 2026-07-15 during quick task 260715-4b9, which measured the
      unit-only baseline at 651 passed.
    caveat: "Failures and errors were pre-existing, not caused by the E2E run."
  after_kl03_fix:
    combined: 859 passed
    failed: 0
    errors: 0
    xpassed: 42
    integration: 193 passed
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

> **RESOLVED 2026-07-15** — quick task `260715-51d` (`635e96a`, `fa3a1ca`, `6ea82c2`).
> **Decision: `domain=` filters.** Re-running the exact probe that exposed this,
> against the same real data: `gold/aviation/rag_corpus/*.parquet` went from
> **133 rows (62% foreign)** to **51 rows, 100% aviation**. `--domain/-D` added to
> `klake export` and `domain` to the API so filtering is reachable outside Dagster.
> `domain=None` deliberately unchanged (all domains, `_unclassified` path), pinned
> by a regression test. See "Resolution" below.

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

**Resolution (2026-07-15, quick task `260715-51d`).** The ambiguity was resolved
in favour of filtering: `domain=X` now selects only rows whose source domain is
`X` (strict equality via `get_domain_for_source`; null-domain rows excluded), in
all three export functions. The path and S3 tag now describe contents truthfully.

`domain=None` is deliberately unchanged — no filter, all domains, `_unclassified`
path — because that is the current CLI/API default and narrowing it would be a
breaking change. A regression test pins that default alongside the new filter
tests.

Filtering was also *unreachable* before this: neither the CLI nor the API passed
`domain`, so only a Dagster operator could trigger the bug. Both now expose it
(`klake export --domain aviation`, `{"domain": "aviation"}` on the API), with the
committed `docs/openapi.json` regenerated.

Verified against the same real corpus that produced the original evidence:

```
before: 51 aviation + 53 functional-medicine + 29 null = 133 rows   (62% foreign)
after : 51 aviation                                    =  51 rows   (100% aviation)
```

*Known limitation, deliberately deferred:* with `domain=None` the
`_unclassified` segment and tag still label an all-domain export. Fixing that
means changing the STORE-03 gold-zone layout.

---

### KL-02 — LLM budget caps under-enforce by 2.4×–9×

> **RESOLVED 2026-07-15** — quick task `260715-51d` (`4396e56`, `fa3a1ca`).
> A live probe revealed the proxy **already computes the correct cost** and we
> were ignoring it. On a real `eval_model` call, reported cost went from
> **$0.0002525 with a `cost_calc_failed` warning** to **$0.0020427 with none** —
> ~8× higher, i.e. the true price. See "Resolution" below.

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

**Resolution (2026-07-15, quick task `260715-51d`).** A live probe against the
running proxy settled which of the two fixes was right, and the answer was better
than either:

```
response.model                   : cheap_model
_hidden_params["response_cost"]  : 3.74e-05   ← proxy already computed it, correctly
completion_cost() (alias fixed)  : 2.72e-05   ← from the hand-maintained settings table
```

The proxy computes cost from the real backend model's pricing on every call. The
settings price table was therefore both **wrong** (never consulted) and
**unnecessary** (duplicating something authoritative). `compute_call_cost()` now
tries, in order: `response_cost` → `completion_cost()` → flat estimate. The last
resort now logs an explicit under-estimation warning rather than a bare
`cost_calc_failed`, and `bootstrap_llm_pricing()` registers under the alias names
actually sent, so the middle rung genuinely works. `eval_model` — which had no
registered price at all — gained one, though `response_cost` covers it and every
future alias for free.

Verified on a real `eval_model` call (the alias that was previously unpriced):

```
before: cost_usd 0.0002525  + {"event": "enrich.cost_calc_failed", ...}
after : cost_usd 0.0020427  + no warning        (~8× higher — the real price)
```

`budget_usd` now means what it says.

---

### KL-03 — CI never runs the 211 integration tests, and they have rotted

> **RESOLVED 2026-07-15** — quick task `260715-4b9`
> (`c75468e`, `9827c61`, `4ab0744`, `92ae035`, `ea14046`).
> `pytest tests/integration -m "not browser"` → **193 passed, 0 failed, 0 errors**
> (was 6 failed / 13 errors). Full suite → 859 passed, 0 failed.
> See "Resolution" at the end of this finding.

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

**Resolution (2026-07-15, quick task `260715-4b9`).** Two corrections to the
analysis above, both surfaced while fixing it:

1. *The CI exclusion was deliberate, not an oversight.* `ci.yml` ended with a
   comment block stating integration tests are "intentionally not run on every
   push to keep CI fast and reliable... enable the job below by adding the
   required `services:`". The team knowingly traded CI coverage for speed and
   documented the local fallback. What went unnoticed was the **rot**, not the
   exclusion.
2. *The documented local fallback was broken too.* `infra/postgres/init.sql`
   creates `dagster_storage` and `litellm_storage` but never `klake_test` — the
   database `test_migrations.py:4` calls "the compose klake_test DB". So
   `make up && make test-integration` failed with 13 errors for anyone who tried
   it. The escape hatch that justified skipping CI did not work, which is why the
   rot could persist undetected.

Fixed: `klake_test` added to `init.sql` (idempotent, matching the existing
`\gexec` pattern); the six mocks given `domain=None, tags=None` to match
production `put_raw`; the comment block replaced with a real `integration` job
that brings up the project's own `docker compose` stack (one source of truth with
the local path — GH Actions `services:` cannot override MinIO's required
`server /data` command). `xfail_strict` was deliberately **not** flipped: 42
tests currently xpass, so enabling it turns them all red. That stays KL-10.

---

## Medium severity

Real defects with a workaround, a narrower blast radius, or a required
precondition.

### KL-04 — The quality filter silently returns nothing for the documented happy path

> **RESOLVED 2026-07-15** — `260715-5pb` (`6a1e9b4`, `8b9e27b`, `76963c2`). Fixed as one
> change with KL-05/KL-06 — see KL-06's resolution. `search --min-quality-score 0.5`
> now returns hits for the aviation document that previously returned nothing.


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

> **RESOLVED 2026-07-15** — `260715-5pb`. Payload precedence is now
> `curated ?? enriched ?? None`, so curate's composite reaches search. Live proof:
> 5 aviation chunks went from `quality_score: None` to `0.797`.


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

> **RESOLVED 2026-07-15** — `260715-5pb` (`6a1e9b4`, `8b9e27b`, `76963c2`).
> D-01's "parallel, doesn't block" was false parallelism — measured at a **21% swing**
> on the same document from scheduling order alone. The chain is now enforced, and
> `klake index --refresh-payload` repairs already-indexed chunks. See frontmatter
> `resolved` for the follow-up that caught the job-selection gap.


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

> **RESOLVED 2026-07-15** — `260715-5pb` (`5b5bcd7`). Now `not addr.is_global`.
> Verified both directions: all 6 reserved ranges blocked, 3 controls still blocked,
> public IPv4/IPv6 + live `faa.gov` still allowed (no over-blocking).


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

> **RESOLVED 2026-07-15** — `260715-5pb` (`9d3f98b`, `bf8b6ac`). 42 stale markers
> removed, 12 genuine xfails kept, `xfail_strict = true`, mutation-verified.
> **It was hiding real bugs — see KL-18 and KL-19.**


Markers like *"Wave 0 stub — implementation pending"* sit on features that now
work (`test_domain_loader`, `test_cli_init_index`, `test_api_search_mode`…). With
`xfail_strict` unset these can never fail the build: if the feature regressed, CI
would record a tidy `xfail` and stay green. Forty-two tests that look like
coverage and function as none.

### KL-11 — Wiki summaries are cut mid-sentence

> **RESOLVED 2026-07-15** — `260715-5pb` (`8ee9082`). Sentence/word-boundary
> truncation with an ellipsis; short summaries unchanged.


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

> **PARTIALLY RESOLVED 2026-07-15** — `260715-5pb` (`dbd8abd`). Renamed to
> `core_pipeline_e2e_job`; no domain name left in framework core. The real gap —
> packs cannot contribute Dagster jobs — is **deferred to the roadmap** by decision.


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

## Discovered during remediation (2026-07-15)

These were not in the original audit. Both were **hidden behind stale xfail
markers** and surfaced the moment KL-10 removed the lies — which is the clearest
possible argument for why KL-10 mattered.

### KL-18 — `GET /documents` and `GET /datasets` return 500 · **HIGH · open**

**What.** `list_documents_endpoint` (`api/app.py:1405`) and
`list_datasets_endpoint` (`:1496`) build their response objects **outside** the
`with get_session()` block. The ORM instances are detached by then, so the first
lazy attribute access raises `sqlalchemy.orm.exc.DetachedInstanceError` → 500.

**Evidence** — real app, real registry data:

```
GET /documents   -> 500  >>> BROKEN (5xx)
GET /datasets    -> 500  >>> BROKEN (5xx)
GET /sources     -> 200  OK
GET /health      -> 200  OK
```

**Why it hid for so long.** Two tests covered these endpoints
(`test_get_documents_returns_200`, `test_get_datasets_returns_200`) but carried
`xfail(reason="Wave 0 stub — GET /documents not yet added")`. The reason was
false — the endpoints exist; they're broken. The marker converted a real 500 into
a tidy green `xfail`. Compounding it, KL-08 means the running API container
serves only 2 of 29 routes, so nobody hits these endpoints locally either.

**Fix.** Build the response objects inside the session scope (or
`expunge`/eager-load before exit). Then delete the xfail markers — the tests
already assert the right thing.

### KL-19 — 4 mode-forwarding tests patch a target that is never consulted · **LOW · open**

**What.** `test_api_mode_forwarded_{hybrid,dense}` and
`test_cli_mode_forwarded_{hybrid,dense}` patch
`knowledge_lake.pipeline.search.search`. But `pipeline/route.py:18` does
`from knowledge_lake.pipeline.search import search` at import time, binding its
own module-level name — `routed_search` calls `route.search`, so the patch never
takes effect and the tests can never pass.

**This is a test bug, not a production gap.** `?mode=` and `--mode` are fully
wired and do forward into `routed_search(mode=...)`. Their xfail reasons claimed
the feature was "not yet added", which is false and was actively misleading.

**Fix.** Patch `knowledge_lake.pipeline.route.search` instead, then remove the
markers. Reasons have been corrected in the interim so the markers no longer lie.

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

1. ~~**KL-03 first.** Wire integration tests into CI before fixing anything else —
   otherwise the fixes below have nothing holding them in place, which is how
   KL-01 arrived.~~ **Done 2026-07-15** (`260715-4b9`). The net is now in place:
   211 integration tests run on every push to main.
2. ~~**KL-02** — a one-line key change; stops silent 9× budget overrun.~~
   **Done 2026-07-15** (`260715-51d`). Not a one-liner in the end — the proxy's
   own `response_cost` made the hand-maintained price table redundant.
3. ~~**KL-01** — decide whether `domain` filters or merely labels, then make the
   code and the S3 tag agree.~~ **Done 2026-07-15** (`260715-51d`). Decided:
   it filters.
4. ~~**KL-07** — a one-line `is_global` change.~~ **Done 2026-07-15** (`260715-5pb`).
5. ~~**KL-04 / KL-05 / KL-06** — one decision, not three patches.~~
   **Done 2026-07-15** (`260715-5pb`). Decided: make the real chain explicit.
6. ~~**KL-10** — remove the stale markers, *then* enable `xfail_strict`.~~
   **Done 2026-07-15** (`260715-5pb`). Order held; it surfaced KL-18 and KL-19.
7. **KL-18 — now the highest-priority open item.** Two API endpoints return 500.
   Small fix (session scoping), real user impact, and its tests already exist.
8. **KL-08 / KL-09** — the two remaining mediums from the original audit; not yet
   selected for remediation. Note KL-08 (container serves 2 of 29 routes,
   reports healthy) is *why* KL-18 went unnoticed locally: nobody can hit those
   endpoints on a stale container.
9. **KL-19**, then KL-12..KL-15, KL-17 as hygiene.

### Status

| | Count |
|---|---|
| Original findings | 17 — **10 resolved**, 7 open (0 high, 2 medium, 5 low) |
| Discovered during remediation | 2 — KL-18 (high), KL-19 (low), both open |
| **Open total** | **9** |

Suite: **943 passed, 0 xpassed, 0 failed, 0 errors, 12 xfailed**, `xfail_strict = true`.

---

## Method note

Every finding marked `reproduced: true` in the frontmatter was confirmed by
execution or by a probe script, not inferred from reading. KL-06 is marked
`reproduced: false`: the scheduling race is established by reading the asset
graph (`index_chunks` has no dependency on `enrich_document`) and its consequence
was observed, but the race itself was not forced under a multiprocess executor.

The E2E left one untracked artifact — `domains/aviation/` — and modified no
tracked file.
