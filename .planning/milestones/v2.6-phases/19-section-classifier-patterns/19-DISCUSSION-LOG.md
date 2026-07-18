# Phase 19: Section Classifier + Patterns - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-16
**Phase:** 19-Section Classifier + Patterns
**Areas discussed:** Section classifier architecture, Substance annotation storage, Domain-pack filter loading, Quality predicate module design
**Mode:** --auto (all decisions auto-selected)

---

## Section Classifier Architecture

| Option | Description | Selected |
|--------|-------------|----------|
| Dedicated classify_sections() function | Compute per-section annotations and is_boilerplate flag, separate from filtering | ✓ |
| Extend remove_boilerplate() to operate per-section | Keep existing function but iterate over sections internally | |
| LLM-based section classifier | Use LLM to classify sections (violates deterministic-first) | |

**Auto-selected:** Dedicated classify_sections() function (recommended default)
**Rationale:** Separating classification from filtering follows deterministic-first constraint. Classifier computes signals; subsequent step decides keep/reject. Enables quality predicates (QUAL-01) to consume same annotations.

---

## Substance Annotation Storage

| Option | Description | Selected |
|--------|-------------|----------|
| On cleaned_document artifact metadata | Store section_annotations in existing metadata_ dict | ✓ |
| Separate annotation artifact | New artifact type for section annotations | |
| Inline in cleaned text as structured comments | Embed annotations in the markdown output | |

**Auto-selected:** On cleaned_document artifact metadata (recommended default)
**Rationale:** CLEAN-04 says "annotations are persisted in the cleaned sidecar." The cleaned artifact already has metadata_ — adding section_annotations there avoids new artifact types and matches existing patterns.

---

## Domain-Pack Filter Loading

| Option | Description | Selected |
|--------|-------------|----------|
| Optional filters.yaml with DomainFilters Pydantic model | DomainLoader loads it if present, validates with Pydantic | ✓ |
| Mandatory filters.yaml for all domain packs | Every pack must provide filter config | |
| Extend domain.yaml with inline filter section | Add filter config to existing domain.yaml | |

**Auto-selected:** Optional filters.yaml with DomainFilters Pydantic model (recommended default)
**Rationale:** Matches existing optional-file pattern. Not all domains need custom filters. Pydantic validates schema. Healthcare pack adds filters.yaml with clinical-code allowlist.

---

## Quality Predicate Module Design

| Option | Description | Selected |
|--------|-------------|----------|
| Pure functions with PredicateResult return + run_predicates() combinator | Standalone functions, composed via combinator | ✓ |
| Predicate classes with __call__ protocol | OOP approach with configurable predicates | |
| Single composite function with config dict | One function with all checks and config parameter | |

**Auto-selected:** Pure functions with PredicateResult return + run_predicates() combinator (recommended default)
**Rationale:** Pure functions are simplest composable unit. Combinator applies in sequence, short-circuits on failure. Matches QUAL-01's "deterministic and 100% branch coverage" criteria.

---

## Claude's Discretion

- Exact substance signal thresholds
- Regex pattern details for extended garbage categories
- PredicateResult implementation (namedtuple vs dataclass)
- Internal module structure of pipeline/quality/
- Test fixture content
- Whether classify_sections() lives in clean.py or a new module

## Deferred Ideas

None — discussion stayed within phase scope.
