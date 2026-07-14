# Phase 15: Query Router - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-14
**Phase:** 15-query-router
**Areas discussed:** Route value naming, Surface exposure, Heuristic trigger conservativeness, Auto-mode fallback semantics, Merge/"both" scope boundary

> Run in `--auto` mode: no interactive prompts were shown. For each area, the
> recommended (conservative-first, additive-only, requirements-literal)
> option was auto-selected and logged below.

---

## Route value naming — `tree` vs `two_stage`

| Option | Description | Selected |
|--------|-------------|----------|
| Alias — both dispatch to `tree_search()` | `tree` and `two_stage` are synonyms for the one tree path Phase 14 shipped | ✓ |
| Distinct implementations | Build a separate "tree-only, no Qdrant shortlist" path to justify two names | |

**Selected:** Alias.
**Reason:** Phase 14 only implemented `tree_search()`, which is inherently
two-stage by construction (D-08 of Phase 14). Building a second, genuinely
different tree-only path just to give `tree` a distinct meaning from
`two_stage` would be new scope not requested by ROUTE-01..04.

---

## Surface exposure — extend existing endpoints vs new ones

| Option | Description | Selected |
|--------|-------------|----------|
| Extend existing `/search`, `search` CLI, MCP `search` tool with `route` param | Matches ROUTE-04 text literally | ✓ |
| Add new dedicated endpoints (`/tree-search`, `/routed-search`) | `PITFALLS.md`'s generic caution against modifying existing surfaces | |

**Selected:** Extend existing surfaces.
**Reason:** ROUTE-04 explicitly says "MCP tools and API endpoints expose the
route parameter alongside existing mode parameter" — that only makes sense
against the surfaces that already have `mode`. The underlying pipeline
functions (`search()`, `tree_search()`) stay untouched; only the thin
adapters change.

---

## Heuristic trigger conservativeness

| Option | Description | Selected |
|--------|-------------|----------|
| Narrow regex set (section/page refs, comparison phrasing, outline requests) | Matches PITFALLS.md's explicit "start conservative" guidance and the STATE.md Phase-15 blocker | ✓ |
| Broad/aggressive trigger set | Higher tree-search adoption, higher false-positive/latency risk with no validation dataset | |

**Selected:** Narrow regex set.
**Reason:** No labeled query dataset exists yet to validate routing quality
(STATE.md blocker, logged before this discussion). Starting conservative and
tuning from the new structlog routing-decision events (D-06) is the lower-risk
path.

---

## Auto-mode fallback semantics

| Option | Description | Selected |
|--------|-------------|----------|
| Auto falls back tree→chunk on zero tree hits; explicit routes never fall back | Balances robustness (auto) with literal operator control (explicit) | ✓ |
| No fallback anywhere (routes always literal) | Simpler, but risks empty results in auto mode when tree misfires | |
| Always fall back (even for explicit `route=tree`) | Contradicts "operator override" semantics already established in ARCHITECTURE.md | |

**Selected:** Auto falls back; explicit routes are literal.
**Reason:** `ARCHITECTURE.md` §6 already frames explicit route settings as an
"operator override" — always honoring the literal choice. `PITFALLS.md`
separately flags the unhandled "both fail" gap as a real risk for `auto`
specifically, where the router (not the operator) made the choice.

---

## Merge/"both" scope boundary

| Option | Description | Selected |
|--------|-------------|----------|
| Out of scope for Phase 15 | REQUIREMENTS.md's locked ROUTE-01..04 don't include a merge requirement | ✓ |
| Build it now | `14-CONTEXT.md`'s Deferred Ideas named it as "coming to Phase 15" | |

**Selected:** Out of scope.
**Reason:** `14-CONTEXT.md` and the v2.5 research docs (`ARCHITECTURE.md`,
`FEATURES.md`) both mention a merge/dedup path, but the actual roadmap
success criteria and REQUIREMENTS.md ROUTE-01..04 only describe single-path
dispatch. Building the merge path would be scope creep relative to the
locked requirements — flagged as a deferred idea instead of built.

---

## Claude's Discretion

- Exact regex pattern wording/ordering for the heuristic classifier.
- Router module filename (`pipeline/route.py` vs `routing.py`).
- Structlog event name for routing-decision logging.
- `RouterSettings` field name (`default_route` vs `route`).
- Whether the classifier is a standalone function or inline in `routed_search()`.

## Deferred Ideas

- Merged/"both" chunk+tree result path (dedup + re-rank) — future release.
- LLM-based routing for ambiguous queries; routing telemetry/feedback loop
  (ROUTE-05/06) — future release.
- OpenKB wiki export — Phase 16 (independent).
- Corpus-level meta-tree navigation (PageIndex File System, TREE-07) — v2.6+.
