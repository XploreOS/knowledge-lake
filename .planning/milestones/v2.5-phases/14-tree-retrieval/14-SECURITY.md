---
phase: "14"
name: tree-retrieval
asvs_level: 1
block_on: high
threats_total: 12
threats_closed: 12
threats_open: 0
audited: 2026-07-14
---

# Security Audit — Phase 14: Tree Retrieval

## Summary

All 12 threats from the phase threat register are CLOSED. All high-severity mitigations are
verified present in the implementation. No unregistered threat flags were raised in any of the
four plan SUMMARYs. Phase 14 is clear to ship.

---

## Threat Verification

| Threat ID | Category | Severity | Disposition | Status | Evidence |
|-----------|----------|----------|-------------|--------|----------|
| T-14-01 | Tampering | low | accept | CLOSED | Accepted — StaticPool in-memory SQLite; no production DB reachable from test harness |
| T-14-02 | Information Disclosure | low | accept | CLOSED | Accepted — storage and litellm.completion are mocked in-memory; no S3/LLM egress |
| T-14-03 | Tampering | high | mitigate | CLOSED | settings.py:665 — `"retriever"` present in `_validate_swap_key` field_validator tuple; regex `_SWAP_KEY_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]{0,63}$")` at line 515; rejects path traversal, spaces, injection |
| T-14-04 | Spoofing | low | accept | CLOSED | Accepted — `citation_source` additive default `"chunk"` in `Hit` (protocols.py:131); only tree search sets `"tree"`; no external input reaches this field |
| T-14-05 | Tampering | high | mitigate | CLOSED | pageindex_retriever.py — injection-resistant `_NAV_SYSTEM_PROMPT` (lines 52–73) instructs model to treat node text as untrusted data; node excerpts capped at `_NODE_EXCERPT_CHARS=512` (line 38, applied at line 268); `NavResult` bounded Pydantic model with `max_length=_MAX_NAV_NODE_IDS` (lines 79–87); unknown `node_ids` discarded before use (line 306) |
| T-14-06 | Denial of Service | high | mitigate | CLOSED | pageindex_retriever.py:250 — `registry_repo.get_llm_spend(session, scope="tree_search")` checked against `budget_usd` before any LLM call; line 320 records spend post-call; `temperature=0.0` (line 290); full try/except at line 323 catches any LLM failure and degrades to heuristic result without raising |
| T-14-07 | Elevation of Privilege | medium | mitigate | CLOSED | resolver.py:390 — `get_retriever()` delegates to `_resolve_with_kwargs(GROUP_RETRIEVERS, name, ...)` which raises `LookupError` on unknown names (lines 241–244); upstream `Settings.retriever` is regex-validated by `_validate_swap_key` (T-14-03 covers the upstream gate) |
| T-14-08 | Information Disclosure | low | accept | CLOSED | Accepted — `litellm_url`/`api_key` are constructor-injected (pageindex_retriever.py:173–178); defaults are localhost dev values; no `os.environ` reads in the builtin (CR-03) |
| T-14-09 | Denial of Service | high | mitigate | CLOSED | tree_search.py:112 — `asyncio.Semaphore(concurrency)` constructed with `settings.tree_search.concurrency` (default 5); `max_docs` (default 3) caps the shortlist size (line 164); single non-nested `asyncio.run` at line 239; per-key `asyncio.wait_for` timeout at line 119 |
| T-14-10 | Tampering | medium | mitigate | CLOSED | tree_search.py:60–92 — `_dict_to_tree` and `_dict_to_tree_index` read all fields explicitly by name (never `**spread`); malformed JSON caught by the outer try/except at line 250 and skips that document rather than crashing the query |
| T-14-11 | Denial of Service | low | mitigate | CLOSED | tree_search.py:204–206 — `if artifact is None: log.info("tree_search.no_tree_index", ...); continue` — missing tree_index artifact is logged and skipped; remaining documents still return Hits |
| T-14-12 | Information Disclosure | low | accept | CLOSED | Accepted — CLI renders only fields already present in `Hit.payload` (document, section_path, pages, score); no DB lookup or secret exposure |

---

## Accepted Risks Log

| Threat ID | Accepted By | Rationale |
|-----------|-------------|-----------|
| T-14-01 | Plan 14-01 threat model | Test fixture isolation — StaticPool in-memory SQLite never reaches production Postgres; ASVS L1 scope |
| T-14-02 | Plan 14-01 threat model | Test mocking — no real S3 or LiteLLM calls made from the test suite; ASVS L1 scope |
| T-14-04 | Plan 14-02 threat model | Additive default "chunk" on `Hit.citation_source`; field is set only internally by search paths, not by any external input |
| T-14-08 | Plan 14-03 threat model | Dev-default credentials ("sk-local-noauth", localhost:4000); production values flow from Settings; no `os.environ` reads in the builtin (CR-03) |
| T-14-12 | Plan 14-04 threat model | CLI renders only Hit.payload fields; no registry lookups or secrets exposed at render time; ASVS L1 scope |

---

## Unregistered Threat Flags

None. No SUMMARY.md for any plan in this phase raised threat flags that lacked a corresponding
threat ID in the register.

---

## Verification Notes (ASVS Level 1)

All verifications are grep-level (pattern exists in cited file) per ASVS L1 requirements.

**T-14-03 (high):** `_validate_swap_key` field_validator at `settings.py:665` covers
`"retriever"` in the tuple alphabetically ordered as
`crawler, discovery, embedder, indexer, parser, retriever, vectorstore`. The `_SWAP_KEY_RE`
regex `^[a-zA-Z][a-zA-Z0-9_-]{0,63}$` at line 515 is applied inside the validator at line 674.

**T-14-05 (high):** Three-layer mitigation confirmed present:
1. `_NAV_SYSTEM_PROMPT` (lines 52–73) contains the explicit instruction to treat node text as
   content, not commands, and to never deviate from JSON output format.
2. Node excerpt truncation: `f"...{node.summary}"[:_NODE_EXCERPT_CHARS]` at line 268.
3. `NavResult.node_ids` field has `max_length=_MAX_NAV_NODE_IDS` (50) at line 87; unknown IDs
   discarded at line 306 before any Hit reordering.

**T-14-06 (high):** Budget gate at `pageindex_retriever.py:250` reads
`scope="tree_search"` (not `"tree_index"` or `"global"` — scope isolation from Phase 13
confirmed; zero occurrences of `scope="tree_index"` or `scope="global"` in this file). Spend
recorded post-call at line 320 with the same scope. Full LLM-call wrapped in a bare
`except Exception` at line 323 that returns `heuristic_hits` without re-raising. `temperature=0.0`
at line 290.

**T-14-09 (high):** `asyncio.Semaphore(concurrency)` at `tree_search.py:112` uses
`s.tree_search.concurrency` (line 239 passes this value). A guard at lines 231–238 raises a
clear `RuntimeError` if `tree_search()` is called from within a running event loop (CR-02
protection). Per-key `asyncio.wait_for(..., timeout=_TREE_LOAD_TIMEOUT_SECONDS)` at line 119
bounds individual stuck loads.

**T-14-07 (medium, below block_on=high):** `_resolve_with_kwargs` raises `LookupError` on
unknown entry-point names at `resolver.py:241–244`. Settings upstream validation (T-14-03)
ensures the name passed to `get_retriever` already satisfies the regex before the entry-point
lookup occurs.

**T-14-10 (medium, below block_on=high):** `_dict_to_tree` and `_dict_to_tree_index` at
`tree_search.py:60–92` read every field by key name; no `**spread` usage found. Outer
`except Exception` at line 250 catches JSON parse failures and logs + skips without propagating.
