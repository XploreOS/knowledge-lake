# Phase 18: Gate Decouple - Context

**Gathered:** 2026-07-15
**Status:** Ready for planning

<domain>
## Phase Boundary

Decouple the re-crawl change gate's content-signature normalization from the evolving `BOILERPLATE_PATTERNS` in `clean.py`. After this phase, extending boilerplate patterns (Phase 19) no longer triggers re-crawl of all sources.

**Requirements:** GATE-01

</domain>

<decisions>
## Implementation Decisions

### Pattern Freezing Mechanism
- **D-01:** The gate gets its own frozen, inline `_GATE_BOILERPLATE_PATTERNS` list inside `crawl.py` — a point-in-time snapshot of the current 4 patterns. This mirrors the existing `_VOLATILE_PATTERNS` approach already in `crawl.py` and eliminates cross-module coupling entirely.
- **D-02:** The frozen patterns are NOT auto-synced from `clean.py`. They are deliberately static. If a gate-level normalization change is ever needed (unlikely), it requires an explicit, intentional edit to `crawl.py` — not a side-effect of extending clean patterns.

### Import Decoupling
- **D-03:** Replace the `remove_boilerplate()` import from `clean.py` with a gate-local `_gate_normalize()` function in `crawl.py`. This function applies `_GATE_BOILERPLATE_PATTERNS` + `_suppress_volatile()` + whitespace normalization. The `_signature()` function calls `_gate_normalize()` instead of `remove_boilerplate()`.
- **D-04:** The `from .clean import remove_boilerplate` import in `crawl.py` is removed entirely. No runtime dependency on `clean.py` from the change gate path.

### Pinning Test
- **D-05:** A pinning test computes `_signature(KNOWN_INPUT)` and asserts the result equals a hardcoded SHA256 hex digest. If someone modifies `_GATE_BOILERPLATE_PATTERNS`, the test fails with a clear message: "Gate signature changed — this triggers re-crawl of all sources. Update the pin only if intentional."
- **D-06:** A second assertion processes the same input through `clean.py::remove_boilerplate()` with an ADDED pattern (simulating Phase 19), confirming the gate signature is unchanged — proving decoupling works.

### Claude's Discretion

Claude has flexibility on: exact whitespace normalization implementation in `_gate_normalize()`, test fixture content, test file location, and whether `_gate_normalize` reuses `_normalize_whitespace` from clean.py or inlines its own (prefer inlining for full isolation).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & Scope
- `.planning/REQUIREMENTS.md` §GATE-01 — Full requirement definition and acceptance criteria
- `.planning/ROADMAP.md` §Phase 18 — Success criteria (signature stability + pinning test)

### Pipeline Code (the coupling)
- `src/knowledge_lake/pipeline/crawl.py` — `_signature()` (line 106), `_suppress_volatile()` (line 93), `_VOLATILE_PATTERNS` (line 77), `remove_boilerplate` import
- `src/knowledge_lake/pipeline/clean.py` — `BOILERPLATE_PATTERNS` (line 46), `remove_boilerplate()` (line 81), `_normalize_whitespace()` (line 66)

### Prior Phase Context
- `.planning/phases/17-close-the-bypass-measurement/17-CONTEXT.md` — Phase 17 context (parallel phase, shares clean.py ownership)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `_VOLATILE_PATTERNS` + `_suppress_volatile()` in `crawl.py:77-103` — Existing gate-local pattern list + suppression function; the new `_GATE_BOILERPLATE_PATTERNS` follows this exact structure
- `_normalize_whitespace()` in `clean.py:66` — Could be inlined for full isolation, or imported (low risk since it's stable infrastructure, not evolving patterns)

### Established Patterns
- Gate-local suppression: `crawl.py` already owns `_VOLATILE_PATTERNS` as a separate, frozen list that never touches `clean.py` — this phase extends that principle to boilerplate
- Content hashing via `hashlib.sha256` — `_signature()` already computes the final hash; only the normalization input changes
- Comment documentation: existing inline comments explain the SCHED-02 design (T-11-THRASH) — new code should maintain this documentation standard

### Integration Points
- `_signature()` is called by `recrawl_source()` (line 142+) — the only consumer of the change gate
- Dagster `recrawl_sensor` triggers `recrawl_source()` — indirectly affected but no code change needed there
- Phase 19 will extend `BOILERPLATE_PATTERNS` in `clean.py` — this phase must complete (or be parallel-safe) before that extension

</code_context>

<specifics>
## Specific Ideas

No specific requirements — the implementation is straightforward pattern extraction with a pinning test. Follow the existing `_VOLATILE_PATTERNS` precedent in the same file.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 18-Gate Decouple*
*Context gathered: 2026-07-15*
