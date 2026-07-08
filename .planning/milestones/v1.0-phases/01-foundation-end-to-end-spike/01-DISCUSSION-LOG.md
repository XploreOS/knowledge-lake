# Phase 1: Foundation & End-to-End Spike - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-02
**Phase:** 1-Foundation & End-to-End Spike
**Areas discussed:** Spike shape & Dagster timing, Spike test document, Repo & package layout, Dev models & lineage UX

---

## Spike shape & Dagster timing

| Option | Description | Selected |
|--------|-------------|----------|
| Functions first, wrap by phase end | Stages as plain functions behind plugin interfaces; wrapped as Dagster assets before phase close; Dagster in compose from first commit | ✓ |
| Dagster assets from first commit | Every stage written as a Dagster asset immediately | |
| Dagster deferred to Phase 2+ | Plain pipeline all of Phase 1; would relax the day-1 constraint | |

**User's choice:** Functions first, wrap by phase end

| Option | Description | Selected |
|--------|-------------|----------|
| Direct calls in Phase 1 | CLI/API call stage functions in-process; Dagster-run submission is a later swap behind same commands | ✓ |
| Submit Dagster runs from phase close | CLI/API submit Dagster runs via GraphQL once assets exist | |
| You decide | Planner picks fastest-to-verify option | |

**User's choice:** Direct calls in Phase 1

| Option | Description | Selected |
|--------|-------------|----------|
| Yes, scripted demo | One command runs full flow against bundled test doc, prints results + lineage; doubles as smoke test | ✓ |
| No, documented steps only | README documents manual commands | |

**User's choice:** Yes, scripted demo

| Option | Description | Selected |
|--------|-------------|----------|
| Package version + git SHA | e.g., 0.1.0+abc1234; falls back to package version outside git | ✓ |
| Git SHA only | Exact but opaque; breaks outside a repo | |
| Manual semver only | Simple but two dev commits stamp identical versions | |

**User's choice:** Package version + git SHA

---

## Spike test document

| Option | Description | Selected |
|--------|-------------|----------|
| One real healthcare PDF | Real public doc with headings + a table; proves Docling early | ✓ |
| Simple controlled fixture | Clean markdown/HTML; zero parser risk | |
| Both: fixture + one real PDF | Fixture first, PDF second pass | |

**User's choice:** One real healthcare PDF

| Option | Description | Selected |
|--------|-------------|----------|
| URL download, minimal | Fetch from public URL with full provenance metadata; Phase 2 broadens | ✓ |
| Local file, bundled in repo | Offline/deterministic but simulated provenance | |
| Both paths | Bundle + URL fetch | |

**User's choice:** URL download, minimal

| Option | Description | Selected |
|--------|-------------|----------|
| HHS/OCR HIPAA guidance PDF | e.g., Summary of the HIPAA Security Rule; public domain, stable URL | ✓ |
| CMS document | More tables, harder parse | |
| Planner picks by criteria | Any US-federal public-domain PDF, <50 pages, headings + ≥1 table | |

**User's choice:** HHS/OCR HIPAA guidance PDF

| Option | Description | Selected |
|--------|-------------|----------|
| Relevant chunk + citation | Fixed demo query returns right-section chunks with score + citation; lineage resolves; relevance human-checked once | ✓ |
| Any result returns | Pure plumbing proof | |
| Small golden-query set | 3-5 asserted queries; pulls eval concerns forward | |

**User's choice:** Relevant chunk + citation

---

## Repo & package layout

| Option | Description | Selected |
|--------|-------------|----------|
| Grow as needed | Only subpackages the spike touches; proposed structure is target map; no stubs | ✓ |
| Full skeleton up front | Entire proposed tree with stub modules | |
| You decide | Planner chooses per plan | |

**User's choice:** Grow as needed

| Option | Description | Selected |
|--------|-------------|----------|
| import knowledge_lake, dist knowledge-lake | Matches proposed src/knowledge_lake/; CLI klake | ✓ |
| import klake everywhere | One short name everywhere | |
| You decide | Planner picks | |

**User's choice:** import knowledge_lake, dist knowledge-lake

| Option | Description | Selected |
|--------|-------------|----------|
| Replace with proposed layout | Remove configs/, services/, workspace/; infra/ for service configs; data/ gitignored dev storage | ✓ |
| Map onto existing dirs | Keep the four pre-existing dirs | |
| You decide | Planner reconciles | |

**User's choice:** Replace with proposed layout

| Option | Description | Selected |
|--------|-------------|----------|
| Inside core package | Built-in plugins in knowledge_lake, registered via same entry-point/hook mechanism as third-party | ✓ |
| Separate packages per plugin | knowledge-lake-docling etc.; packaging overhead | |

**User's choice:** Inside core package

---

## Dev models & lineage UX

| Option | Description | Selected |
|--------|-------------|----------|
| Haiku 4.5 cheap / Sonnet strong+eval | cheap→Haiku 4.5, strong/eval→Sonnet, embedding→Titan V2, all Bedrock via LiteLLM | ✓ |
| Nova cheap / Claude strong | Nova Lite cheapest, weaker enrichment | |
| You decide | Planner writes mapping; user tunes later | |

**User's choice:** Haiku 4.5 cheap / Sonnet strong+eval

| Option | Description | Selected |
|--------|-------------|----------|
| Local sentence-transformers | Free, offline; demo needs zero AWS credentials | ✓ |
| Bedrock via LiteLLM | Exercises gateway day 1 but demo needs credentials | |

**User's choice:** Local sentence-transformers

| Option | Description | Selected |
|--------|-------------|----------|
| Tree + --json flag | Human-readable ancestry tree default; --json full graph; API returns JSON | ✓ |
| Flat table | Simpler render, hard to read branches | |
| JSON only | Least CLI work, worst ergonomics | |

**User's choice:** Tree + --json flag

| Option | Description | Selected |
|--------|-------------|----------|
| UUIDv7 + short prefix | doc_/chk_/src_ prefixes; time-sortable; CLI accepts unambiguous prefixes | ✓ |
| Plain UUIDv4 | Opaque in logs; b-tree fragmentation at scale | |
| You decide | Planner picks consistent scheme | |

**User's choice:** UUIDv7 + short prefix

---

## Claude's Discretion

- Registry schema details within the 17-registry blueprint, SQLAlchemy/psycopg specifics, Alembic layout, compose wiring, exact local embedding model, spike chunking parameters, error handling/logging design.

## Deferred Ideas

- None — discussion stayed within phase scope.
