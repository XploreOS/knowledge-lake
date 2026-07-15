# Phase 18: Gate Decouple - Research

**Researched:** 2026-07-15
**Domain:** Pipeline change-gate decoupling (Python module refactoring)
**Confidence:** HIGH

## Summary

Phase 18 decouples the SCHED-02 re-crawl change gate (`_signature()` in `crawl.py`) from the evolving `BOILERPLATE_PATTERNS` list in `clean.py`. Currently, `_signature()` imports and calls `remove_boilerplate()` from `clean.py`, which iterates over `BOILERPLATE_PATTERNS`. When Phase 19 extends that pattern list, every source's signature would change, triggering unnecessary re-crawls of the entire corpus.

The solution is straightforward: freeze a point-in-time copy of the current 4 boilerplate patterns inside `crawl.py` as `_GATE_BOILERPLATE_PATTERNS`, create a `_gate_normalize()` function that applies them plus volatile suppression plus whitespace normalization, and remove the `from .clean import remove_boilerplate` import entirely. A pinning test locks the gate signature to a hardcoded SHA256 digest.

**Primary recommendation:** Extract the 4 current `BOILERPLATE_PATTERNS` into a frozen `_GATE_BOILERPLATE_PATTERNS` list in `crawl.py`, replace `remove_boilerplate()` with a gate-local `_gate_normalize()`, and add a pinning test that asserts byte-stability of the gate signature.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** The gate gets its own frozen, inline `_GATE_BOILERPLATE_PATTERNS` list inside `crawl.py` -- a point-in-time snapshot of the current 4 patterns. This mirrors the existing `_VOLATILE_PATTERNS` approach already in `crawl.py` and eliminates cross-module coupling entirely.
- **D-02:** The frozen patterns are NOT auto-synced from `clean.py`. They are deliberately static. If a gate-level normalization change is ever needed (unlikely), it requires an explicit, intentional edit to `crawl.py` -- not a side-effect of extending clean patterns.
- **D-03:** Replace the `remove_boilerplate()` import from `clean.py` with a gate-local `_gate_normalize()` function in `crawl.py`. This function applies `_GATE_BOILERPLATE_PATTERNS` + `_suppress_volatile()` + whitespace normalization. The `_signature()` function calls `_gate_normalize()` instead of `remove_boilerplate()`.
- **D-04:** The `from .clean import remove_boilerplate` import in `crawl.py` is removed entirely. No runtime dependency on `clean.py` from the change gate path.
- **D-05:** A pinning test computes `_signature(KNOWN_INPUT)` and asserts the result equals a hardcoded SHA256 hex digest. If someone modifies `_GATE_BOILERPLATE_PATTERNS`, the test fails with a clear message: "Gate signature changed -- this triggers re-crawl of all sources. Update the pin only if intentional."
- **D-06:** A second assertion processes the same input through `clean.py::remove_boilerplate()` with an ADDED pattern (simulating Phase 19), confirming the gate signature is unchanged -- proving decoupling works.

### Claude's Discretion
- Exact whitespace normalization implementation in `_gate_normalize()`
- Test fixture content
- Test file location
- Whether `_gate_normalize` reuses `_normalize_whitespace` from clean.py or inlines its own (prefer inlining for full isolation)

### Deferred Ideas (OUT OF SCOPE)
None -- discussion stayed within phase scope.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| GATE-01 | Decouple SCHED-02 change gate from clean patterns -- re-crawl gate uses frozen gate-local patterns, not evolving `BOILERPLATE_PATTERNS` | Covered by frozen `_GATE_BOILERPLATE_PATTERNS` (D-01/D-02), `_gate_normalize()` (D-03), import removal (D-04), and pinning test (D-05/D-06) |
</phase_requirements>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Content signature computation | Pipeline (crawl.py) | -- | `_signature()` is the gate's normalization+hash function; purely internal to the crawl module |
| Boilerplate removal for clean stage | Pipeline (clean.py) | -- | `remove_boilerplate()` remains in clean.py for the silver-stage cleaning path |
| Signature byte-stability assertion | Test suite | -- | Pinning test prevents accidental signature drift |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| hashlib (stdlib) | Python 3.12 | SHA256 content hashing | Already used by `_signature()`; no external dependency needed |
| re (stdlib) | Python 3.12 | Regex pattern matching for boilerplate | Already used for `_VOLATILE_PATTERNS`; same approach for `_GATE_BOILERPLATE_PATTERNS` |
| pytest | 8.0+ | Test framework | Already configured in pyproject.toml |

### Supporting
No additional libraries needed. This phase is pure refactoring of existing stdlib code.

**Installation:**
```bash
# No new packages required
```

## Architecture Patterns

### System Architecture Diagram

```
crawl.py::recrawl_source()
    |
    v
crawl.py::_signature(markdown)
    |
    v
crawl.py::_gate_normalize(text)          <-- NEW (replaces remove_boilerplate call)
    |
    +---> _GATE_BOILERPLATE_PATTERNS     <-- NEW (frozen copy of 4 patterns)
    +---> _suppress_volatile(text)        <-- EXISTING (unchanged)
    +---> whitespace normalization        <-- INLINED (no clean.py dependency)
    |
    v
hashlib.sha256(normalized.encode())
    |
    v
hex digest (compared to Source.last_content_hash)
```

**Decoupled from:**
```
clean.py::BOILERPLATE_PATTERNS           <-- Phase 19 extends this freely
clean.py::remove_boilerplate()           <-- No longer imported by crawl.py
clean.py::_normalize_whitespace()        <-- Not imported (inlined for isolation)
```

### Recommended Project Structure
```
src/knowledge_lake/pipeline/
    crawl.py          # Gate-local patterns + _gate_normalize() + _signature()
    clean.py          # BOILERPLATE_PATTERNS + remove_boilerplate() (unchanged)
tests/unit/
    test_recrawl_gate.py          # Existing gate tests (updated)
    test_gate_signature_pin.py    # NEW: pinning test for byte-stability
```

### Pattern 1: Gate-Local Pattern Freezing
**What:** A module-private list of compiled regex patterns that are intentionally NOT imported from another module, so changes to the source list do not propagate.
**When to use:** When a consumer needs a stable, point-in-time snapshot of patterns owned by another module.
**Example:**
```python
# Source: crawl.py existing _VOLATILE_PATTERNS (lines 77-90)
# This is the EXISTING pattern that _GATE_BOILERPLATE_PATTERNS follows:
_VOLATILE_PATTERNS: list[re.Pattern] = [
    re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}..."),
    re.compile(r"\b\d{2}:\d{2}:\d{2}\b"),
    re.compile(r"\b[0-9a-fA-F]{8}-..."),
    re.compile(r"\b[0-9a-fA-F]{16,}\b"),
]
```

### Pattern 2: Pinning Test for Byte-Stability
**What:** A test that computes a function's output for a known input and asserts it equals a hardcoded expected value, with a descriptive failure message explaining the consequence of changes.
**When to use:** When a function's output is stored externally (databases, S3) and changes would have cascading effects (re-crawl of all sources).
**Example:**
```python
def test_gate_signature_pinned():
    """Gate signature must be byte-stable -- changes trigger re-crawl of all sources."""
    known_input = "..."  # Fixed content
    expected_hash = "abc123..."  # Precomputed
    actual = _signature(known_input)
    assert actual == expected_hash, (
        "Gate signature changed -- this triggers re-crawl of all sources. "
        "Update the pin only if intentional."
    )
```

### Anti-Patterns to Avoid
- **Importing from clean.py for the gate path:** The entire point of this phase is eliminating the `from .clean import remove_boilerplate` dependency. Do not partially decouple (e.g., importing `_normalize_whitespace` but not `remove_boilerplate`).
- **Auto-syncing patterns:** Never add code that reads `clean.py::BOILERPLATE_PATTERNS` at runtime or build time to populate `_GATE_BOILERPLATE_PATTERNS`. The freeze must be explicit and manual.
- **Shared helper imports from clean.py:** Per user preference, inline whitespace normalization rather than importing `_normalize_whitespace`. Full isolation is the goal.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Content hashing | Custom hash function | `hashlib.sha256` | Already used; standard, deterministic |
| Regex compilation | Dynamic pattern loading | Compiled `re.Pattern` list at module level | Matches existing `_VOLATILE_PATTERNS` pattern; zero runtime overhead |

**Key insight:** This phase is purely about module coupling removal. There is no complex algorithm to get wrong -- only the discipline of freezing patterns and removing an import.

## Common Pitfalls

### Pitfall 1: Forgetting to compute the pinned hash AFTER implementation
**What goes wrong:** Developer writes the pinning test with a placeholder hash, implements `_gate_normalize()`, then forgets to update the test with the actual computed hash.
**Why it happens:** The hash can only be computed after `_gate_normalize()` is implemented (chicken-and-egg).
**How to avoid:** Implement `_gate_normalize()` first, run `_signature("known input")` in a REPL/test to get the actual hash, THEN write the pinning test with that value.
**Warning signs:** Pinning test fails on first run with a hash mismatch.

### Pitfall 2: Breaking existing test_recrawl_gate.py tests
**What goes wrong:** The existing 5 tests in `test_recrawl_gate.py` import `_signature` and compute expected hashes. Changing `_signature()`'s normalization logic changes these hashes.
**Why it happens:** `_signature()` currently calls `remove_boilerplate()` which applies patterns + whitespace normalization. The new `_gate_normalize()` must produce IDENTICAL output for the same patterns + normalization logic.
**How to avoid:** Ensure `_gate_normalize()` applies the exact same 4 patterns in the same order with the same `re.sub("", text)` + same whitespace normalization as `remove_boilerplate()` currently does. Run existing tests BEFORE writing new ones.
**Warning signs:** `test_nonce_noise_unchanged` or `test_unchanged_skips_no_raw` fails.

### Pitfall 3: Whitespace normalization divergence
**What goes wrong:** The inlined whitespace normalization in `_gate_normalize()` does not exactly match `_normalize_whitespace()` from clean.py, causing the gate signature to differ from what was stored for existing sources.
**Why it happens:** Subtle differences in strip/collapse logic (e.g., handling of leading newlines, tab characters).
**How to avoid:** Copy `_normalize_whitespace()` verbatim into the gate-local function. The function is 5 lines of straightforward logic.
**Warning signs:** Sources that were previously "unchanged" suddenly appear "changed" after deployment.

### Pitfall 4: Docstring/comment references to remove_boilerplate
**What goes wrong:** The `_signature()` docstring and `recrawl_source()` docstring both reference `remove_boilerplate`. After the change, these are stale.
**Why it happens:** Easy to forget documentation updates during a refactor.
**How to avoid:** Update all docstrings in the same commit as the code change.
**Warning signs:** Code review flags stale documentation.

### Pitfall 5: xfail_strict interaction
**What goes wrong:** If a developer marks a failing test as `xfail` during development, it will fail the build when it starts passing.
**Why it happens:** `xfail_strict = true` in pyproject.toml.
**How to avoid:** Never use xfail markers. Fix tests directly.
**Warning signs:** CI failure with "test passed but was marked xfail".

## Code Examples

### Current _signature() implementation (to be replaced)
```python
# Source: src/knowledge_lake/pipeline/crawl.py lines 106-118
def _signature(markdown: str) -> str:
    normalized = remove_boilerplate(markdown or "")
    return hashlib.sha256(
        _suppress_volatile(normalized).encode("utf-8")
    ).hexdigest()
```

### Target _gate_normalize() implementation
```python
# New function replacing remove_boilerplate() call in _signature()
# Follows existing _VOLATILE_PATTERNS pattern (lines 77-90 of crawl.py)

_GATE_BOILERPLATE_PATTERNS: list[re.Pattern] = [
    # Page headers/footers: "Page 1 of 5" or bare page number
    re.compile(r"^(?:Page \d+ of \d+|\d+)\s*$", re.MULTILINE),
    # Cookie/privacy banners
    re.compile(
        r"(?i)(?:this site uses cookies|accept all cookies|cookie policy)[^\n]*$",
        re.MULTILINE,
    ),
    # Navigation elements (entire line only)
    re.compile(
        r"(?im)^(?:home|about us|contact|sitemap|skip to (?:main )?content)\s*$",
    ),
    # Repeated copyright/disclaimer lines
    re.compile(r"(?i)^(?:disclaimer|copyright \d{4})[^\n]*$", re.MULTILINE),
]


def _gate_normalize(text: str) -> str:
    """Gate-local normalization: frozen boilerplate patterns + whitespace collapse.

    GATE-01: This function is deliberately decoupled from clean.py. Changes to
    BOILERPLATE_PATTERNS in clean.py do NOT affect this function. If the gate's
    normalization must change, edit _GATE_BOILERPLATE_PATTERNS explicitly.
    """
    for pattern in _GATE_BOILERPLATE_PATTERNS:
        text = pattern.sub("", text)
    # Inline whitespace normalization (mirrors _normalize_whitespace from clean.py
    # at the time of freeze -- 2026-07-15)
    lines = [line.rstrip() for line in text.split("\n")]
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
```

### Target _signature() implementation (updated)
```python
def _signature(markdown: str) -> str:
    """Compute content signature: gate-local normalize, suppress volatile, SHA256.

    Uses gate-local _gate_normalize() (frozen patterns, GATE-01) then applies
    volatile-token suppression (ISO timestamps, UUIDs, hex nonces) so
    dynamically-rendered pages do not thrash the WORM raw zone (SCHED-02).
    """
    normalized = _gate_normalize(markdown or "")
    return hashlib.sha256(
        _suppress_volatile(normalized).encode("utf-8")
    ).hexdigest()
```

### Pinning test example
```python
# tests/unit/test_gate_signature_pin.py
import pytest
from knowledge_lake.pipeline.crawl import _signature
from knowledge_lake.pipeline.clean import BOILERPLATE_PATTERNS, remove_boilerplate

# Known fixture content -- contains boilerplate that the gate patterns match
_FIXTURE = (
    "Page 3 of 10\n\n"
    "# Clinical Guidelines for Hypertension Management\n\n"
    "Evidence-based recommendations for care.\n\n"
    "Skip to main content\n\n"
    "Copyright 2026 All rights reserved.\n"
)

# Precomputed hash (filled after _gate_normalize is implemented)
_EXPECTED_HASH = "<sha256-hex-computed-after-implementation>"


def test_gate_signature_byte_stable():
    """GATE-01: Gate signature must not change when clean.py patterns change."""
    actual = _signature(_FIXTURE)
    assert actual == _EXPECTED_HASH, (
        "Gate signature changed -- this triggers re-crawl of all sources. "
        "Update the pin only if intentional."
    )


def test_gate_decoupled_from_clean_patterns():
    """GATE-01: Adding a pattern to clean.py does NOT change the gate signature."""
    import re
    # Simulate Phase 19: add a new pattern to BOILERPLATE_PATTERNS
    new_pattern = re.compile(r"(?i)^subscribe to our newsletter[^\n]*$", re.MULTILINE)
    original_len = len(BOILERPLATE_PATTERNS)

    # Compute gate signature BEFORE and AFTER adding pattern to clean.py
    sig_before = _signature(_FIXTURE)

    # Temporarily extend BOILERPLATE_PATTERNS (simulating Phase 19)
    BOILERPLATE_PATTERNS.append(new_pattern)
    try:
        sig_after = _signature(_FIXTURE)
        assert sig_before == sig_after, (
            "Gate signature changed after extending BOILERPLATE_PATTERNS in clean.py. "
            "The gate is still coupled to clean.py -- decoupling is broken."
        )
    finally:
        # Restore original patterns
        BOILERPLATE_PATTERNS.pop()
        assert len(BOILERPLATE_PATTERNS) == original_len
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `_signature()` calls `remove_boilerplate()` from clean.py | `_signature()` calls gate-local `_gate_normalize()` | Phase 18 (this phase) | Extending clean patterns no longer triggers re-crawl |

**Deprecated/outdated:**
- `from knowledge_lake.pipeline.clean import remove_boilerplate` in crawl.py: Removed by this phase. The gate path no longer depends on clean.py at runtime.

## Assumptions Log

> List all claims tagged `[ASSUMED]` in this research.

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| -- | -- | -- | -- |

**If this table is empty:** All claims in this research were verified or cited -- no user confirmation needed.

All findings in this research are derived from direct codebase inspection (grep/read of source files). No external documentation lookups or assumed knowledge were needed -- this is a pure internal refactoring phase.

## Open Questions

1. **Exact pinning test hash value**
   - What we know: The hash depends on `_gate_normalize()` + `_suppress_volatile()` applied to the fixture text
   - What's unclear: The exact SHA256 hex digest (must be computed after implementation)
   - Recommendation: Implement `_gate_normalize()` first, compute hash, then hardcode into test. This is implementation-time work, not a planning blocker.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.0+ with pytest-asyncio |
| Config file | `pyproject.toml` [tool.pytest.ini_options] |
| Quick run command | `pytest tests/unit/test_gate_signature_pin.py tests/unit/test_recrawl_gate.py -x` |
| Full suite command | `pytest tests/ -x` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| GATE-01a | Gate signature byte-stable across clean.py changes | unit | `pytest tests/unit/test_gate_signature_pin.py::test_gate_signature_byte_stable -x` | Wave 0 |
| GATE-01b | Adding pattern to BOILERPLATE_PATTERNS does not change gate sig | unit | `pytest tests/unit/test_gate_signature_pin.py::test_gate_decoupled_from_clean_patterns -x` | Wave 0 |
| GATE-01c | Existing recrawl gate tests still pass (no regression) | unit | `pytest tests/unit/test_recrawl_gate.py -x` | Exists |

### Sampling Rate
- **Per task commit:** `pytest tests/unit/test_gate_signature_pin.py tests/unit/test_recrawl_gate.py -x`
- **Per wave merge:** `pytest tests/ -x`
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/unit/test_gate_signature_pin.py` -- covers GATE-01 (pinning + decoupling assertion)

*(Existing `tests/unit/test_recrawl_gate.py` covers regression for the gate's functional behavior -- no gap there.)*

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | -- |
| V3 Session Management | no | -- |
| V4 Access Control | no | -- |
| V5 Input Validation | no | Regex patterns operate on already-fetched content, not user input |
| V6 Cryptography | no | SHA256 used for content fingerprinting only, not security |

This phase has no security surface -- it is a pure internal refactoring of normalization logic with no new inputs, no new network calls, and no new data paths. The SSRF guards in `recrawl_source()` are unchanged.

## Sources

### Primary (HIGH confidence)
- `src/knowledge_lake/pipeline/crawl.py` -- Direct code inspection of `_signature()`, `_suppress_volatile()`, `_VOLATILE_PATTERNS`, `remove_boilerplate` import
- `src/knowledge_lake/pipeline/clean.py` -- Direct code inspection of `BOILERPLATE_PATTERNS`, `remove_boilerplate()`, `_normalize_whitespace()`
- `tests/unit/test_recrawl_gate.py` -- Direct code inspection of existing gate tests
- `tests/unit/test_clean.py` -- Direct code inspection of clean stage tests
- `.planning/phases/18-gate-decouple/18-CONTEXT.md` -- User decisions (D-01 through D-06)
- `.planning/REQUIREMENTS.md` -- GATE-01 definition and acceptance criteria

### Secondary (MEDIUM confidence)
None needed -- all findings from direct codebase inspection.

### Tertiary (LOW confidence)
None.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - No new libraries; pure stdlib refactoring
- Architecture: HIGH - Direct codebase inspection; pattern mirrors existing `_VOLATILE_PATTERNS`
- Pitfalls: HIGH - Derived from actual code structure and test dependencies

**Research date:** 2026-07-15
**Valid until:** Indefinite (internal refactoring; no external dependency drift)
