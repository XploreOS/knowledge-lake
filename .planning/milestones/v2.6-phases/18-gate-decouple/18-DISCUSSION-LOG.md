# Phase 18: Gate Decouple - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-15
**Phase:** 18-Gate Decouple
**Areas discussed:** Pattern freezing mechanism, Import decoupling approach, Pinning test design
**Mode:** --auto (all decisions auto-selected)

---

## Pattern Freezing Mechanism

| Option | Description | Selected |
|--------|-------------|----------|
| Inline frozen list in crawl.py | Copy current 4 patterns as a static list, matching _VOLATILE_PATTERNS precedent | ✓ |
| Separate gate_patterns.py module | New module that clean.py and crawl.py both import from | |
| Version-tagged snapshot | Use a config-versioned snapshot that updates explicitly | |

**Auto-selected:** Inline frozen list in crawl.py (recommended default)
**Rationale:** Matches existing `_VOLATILE_PATTERNS` approach in the same file. Zero cross-module coupling. Simplest change.

---

## Import Decoupling Approach

| Option | Description | Selected |
|--------|-------------|----------|
| Gate-local _gate_normalize() function | Replace remove_boilerplate() call with self-contained function in crawl.py | ✓ |
| Keep import but freeze input patterns | Pass frozen patterns to remove_boilerplate as parameter | |
| Extract shared normalize utility | Move normalization to a shared utils module | |

**Auto-selected:** Gate-local _gate_normalize() function (recommended default)
**Rationale:** `_signature()` already has its own `_suppress_volatile()`. Extending with gate-local boilerplate removal maintains full isolation.

---

## Pinning Test Design

| Option | Description | Selected |
|--------|-------------|----------|
| Hardcoded hex digest assertion | Hash known input, assert matches pinned value | ✓ |
| Golden file comparison | Store expected output in a fixture file | |
| Property-based stability test | Assert N runs of same input produce same output | |

**Auto-selected:** Hardcoded hex digest assertion (recommended default)
**Rationale:** Same pattern used elsewhere for content-hash stability. Clear failure message guides developers.

---

## Claude's Discretion

- Whitespace normalization implementation details in `_gate_normalize()`
- Test fixture content selection
- Test file location
- Whether to inline `_normalize_whitespace` or import it (prefer inline for full isolation)

## Deferred Ideas

None — discussion stayed within phase scope.
