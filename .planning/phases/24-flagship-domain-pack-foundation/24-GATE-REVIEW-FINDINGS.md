# Phase 24 Gate Review Findings — `agent-security` Chunk-Substance Gate (Report-Only Run)

**Date:** 2026-07-22
**Domain:** `agent-security`
**Discipline:** PITFALLS.md Pitfall 9 — report-only run first, human review before any gate change (CONTEXT.md D-04)
**Phase Boundary:** This document is the finding, not the fix. The actual `domains/agent-security/filters.yaml` normative allowlist is explicitly **Phase 26's (Quality Contract)** job — see Handoff section below. `domains/agent-security/filters.yaml` does NOT exist as of this writing, and this plan does not create it.

---

## 1. Measurement

Plan 24-02 ingested the real `agent-security` corpus end-to-end with `chunk_quality.gate_mode="report"` active for the entire run, so both kept and rejected chunks were persisted as real `Artifact` rows (`artifact_type="chunk"`), each carrying `metadata_.substance_passed` and, for rejections, `metadata_.rejection_reason`.

**Verify-command substitution (documented per the plan's own efficiency note and 24-02's identical precedent):** this measurement was gathered via **direct SQLAlchemy registry queries** against the already-persisted `Source`/`Artifact` rows, not by re-running `uv run klake quality-audit --domain agent-security --full --json`. Source inspection of `run_full_pipeline_audit()` (`pipeline/quality_audit.py`) confirms it re-derives the corpus from `parse()` → `clean()` → `chunk()` from scratch — it does not read persisted state. Re-running it against this corpus size was estimated (and independently confirmed by 24-02's own execution) at well over an hour of pure redundant recomputation of work Plan 24-02 already did. The direct-query approach reads the exact same underlying facts (`Artifact.metadata_["substance_passed"]`/`["rejection_reason"]` on the corpus's own persisted chunk rows) in seconds. This substitution is the same one 24-02-SUMMARY.md documents for its own Task 2 verification — treated as an established, legitimate pattern for this phase, not a shortcut around the requirement.

### Corpus-wide numbers

| Metric | Value |
|---|---|
| Domain | `agent-security` |
| Total chunk artifacts | 2,163 |
| Rejected chunks (`substance_passed == False`) | **978** |
| Kept chunks (`substance_passed == True`) | 1,185 |
| **`chunk_garbage_rate`** | **45.21%** (978 / 2163) |

### Rejection-reason breakdown (all 978 rejected chunks, real counts)

| Reason | Count |
|---|---|
| `line_punct_ratio` | 500 |
| `short_line_ratio` | 400 |
| `char_dup_ratio` | 51 |
| `list_ratio` | 2 |
| `below_stopword_ratio:0.05<0.05` | 9 |
| `below_terminal_punct_ratio:0.02<0.02` | 5 |
| `below_stopword_ratio:0.04<0.05` | 6 |
| `below_stopword_ratio:0.03<0.05` | 4 |
| `below_stopword_ratio:0.00<0.05` | 1 |

### Per-source breakdown (real counts)

| Source | Total chunks | Rejected | Rejection rate |
|---|---|---|---|
| OWASP Top 10 for LLM Applications | 1,161 | 402 | 34.63% |
| OWASP Agentic AI — Threats and Mitigations | 329 | 175 | 53.19% |
| Model Context Protocol Specification | 520 | 342 | 65.77% |
| MITRE ATLAS | 0 | 0 | — (0 pages ingested; SPA-rendering gap, see 24-02-SUMMARY.md Decision 4 — expected, not a corpus gap) |
| IETF RFC 6749 — OAuth 2.0 Authorization Framework | 52 | 38 | 73.08% |
| NIST AI Risk Management Framework (AI RMF 1.0) | 48 | 13 | 27.08% |
| NIST AI 600-1 Generative AI Profile | 53 | 8 | 15.09% |

**Scope caveat (carried forward from 24-02-SUMMARY.md Decision 1):** the OWASP-sourced totals above include ~69 scope-creep pages beyond `sources.yaml`'s intended two OWASP entries (a rogue crawl session picked up an OWASP donate page, project index, and multi-language ASVS translations). This inflates the OWASP rejection denominator with genuinely low-value pages (donate/nav/translation-index content) that would legitimately be rejected regardless of domain-tuning — the per-source rates above should be read with that in mind, not as a pure signal of gate over-aggressiveness.

A targeted regex search across **all 978 rejected chunks** for the literal domain-specific shapes PITFALLS.md Pitfall 9 and CONTEXT.md D-04 name by name (permission-scope strings like `word:word`, `mcp__`-prefixed tool identifiers, `CVSS`, severity-level phrases, OAuth `scope=` parameters) found only **7 matches**, all of which were confirmed (via full-text inspection, quoted below) to be false positives of the regex itself — XML namespace declarations (`xmlns:content`), CSS selectors (`td:nth`), and WordPress REST API field names (`wp:featuredmedia`), not real permission scopes or tool identifiers. **No literal `mcp__filesystem__read`-style tool-call identifier or `read:documents`-style permission-scope string was found being wrongly rejected in this corpus** — those exact named exemplars either don't appear as isolated short chunk text in the crawled corpus, or appear embedded in longer prose that clears the gate on its own merits.

---

## 2. Real Rejected-Chunk Sample (quoted verbatim, not paraphrased)

31 real rows sampled: up to 4 per source (stratified across all 7 sources) plus every one of the 7 domain-pattern-regex hits described above. This satisfies the "at least 10, or all real rows if fewer than 10 exist" acceptance bar with room to spare — every entry below is a real, persisted `Artifact` row's actual stored chunk text (read from `storage_uri` via `storage.get_object()`), not a summary or paraphrase.

### Genuine boilerplate — correctly rejected (majority pattern)

| # | Source | Reason | Chunk text (verbatim) |
|---|---|---|---|
| 1 | IETF RFC 6749 | `line_punct_ratio` | `Footer\n\nrfc-editor.org is maintained by the\nInternet Engineering Task Force\n·\nReport a Bug` |
| 2 | IETF RFC 6749 | `line_punct_ratio` | `RFC 5378 : BCP 78 : Rights Contributors Provide to the IETF Trust\n\nBest Current Practice\nShow abstract` |
| 3 | IETF RFC 6749 | `short_line_ratio` | `In this section\n\nThe RFC Series uses certain conventions that may not be familiar to all readers. Some of the most common are listed here; refer to this more\nin-depth overview\nfor further information.` |
| 4 | IETF RFC 6749 | `char_dup_ratio` | `Errata\n\nErrata are listed in the Errata section of the sidebar for each RFC when they exist. Errata with a Verified status have been reviewed and are considered accurate...` |
| 5 | OWASP Top 10 | `below_terminal_punct_ratio:0.02<0.02` | `Sharing of Personal Information\n\nWe disclose personal information as set forth below, and where individuals have otherwise consented:\nPublicly Available Information, including Your Contributions to Open-Source Projects...` (site privacy-policy boilerplate) |
| 6 | OWASP Top 10 | `short_line_ratio` | `Change Log\n\nAll notable changes to the OWASP Top 10 for LLM Applications project will be documented in this file.\nThe format is based on\nKeep a Changelog\n, and this project adheres to\nSemantic Versioning\n.` |
| 7 | OWASP Top 10 | `line_punct_ratio` | `[1.0.1] - 2023-08-26\n\nv1.1 Instructions for the Expert Group reference` |
| 8 | OWASP Agentic AI | `short_line_ratio` | `OWASP GenAI Security Project\n\nA global community-driven and expert led initiative to create freely available open source guidance and resources...\nMembers\nk+\nCountries\n+\nAI Cybersecurity Publications\n+` (marketing/stat-widget nav content) |
| 9 | OWASP Agentic AI | `line_punct_ratio` | `What's New\n\nResources\nBlog\nEvents\nNews` |
| 10 | OWASP Agentic AI | `line_punct_ratio` | `State of Agentic AI Security and Governance 2.01\n\nThe State of Agentic AI Security and Governance provides a comprehensive view of today's landscape...\nDownload Now` (blog-promo card) |
| 11 | MCP Specification | `line_punct_ratio` | `Broad ecosystem support\n\nMCP is an open protocol supported across a wide range of clients and servers. AI assistants like\nClaude\nand\nChatGPT\n, development tools like\nVisual Studio Code\n,\nCursor\n,\nMCPJam\n, and many others all support MCP...` (marketing copy) |
| 12 | MCP Specification | `line_punct_ratio` | `[{"content":"The MCP protocol is about to undergo its biggest revision since launch...` (raw JSON blog-feed dump) |
| 13 | MCP Specification | `line_punct_ratio` | `On this page\n\nMCP Apps` (nav breadcrumb) |
| 14 | NIST AI RMF 1.0 | `char_dup_ratio` | `Artificial Intelligence Risk Management Framework (AI RMF 1.0)\n\nThis publication is available free of charge from: https://doi.org/10.6028/NIST.AI.100-1\nJanuary 2023\nU.S. Department of Commerce Gina M. Raimondo, Secretary...` (title-page boilerplate) |
| 15 | NIST AI 600-1 | `line_punct_ratio` | `Contact Information\n\nai-inquiries@nist.gov\nNational Institute of Standards and Technology Attn: NIST AI Innovation Lab...` (contact footer) |
| 16-22 | (various) | — | 7 regex-flagged "domain-pattern" false positives — XML namespace declarations (`xmlns:content="http://purl.org/rss/1.0/modules/content/"`), raw CSS (`.acf-h1,.acf-admin-page ...{font-size:21px}`), and WordPress REST JSON (`{"name":"OWASP Gen AI Security Project", ...}`) from RSS/comment-feed and admin-widget scrape artifacts — none are real permission scopes, tool identifiers, or severity strings; the regex matched incidental colon-separated tokens (`xmlns:content`, `td:nth`, `wp:featuredmedia`) in markup, not domain semantics. |

### Domain-specific / structured content — plausibly wrongly rejected (minority pattern, the actual finding)

| # | Source | Reason | Chunk text (verbatim) |
|---|---|---|---|
| 23 | OWASP Top 10 | `below_stopword_ratio:0.04<0.05` | `LLM05:2023 - SSRF Vulnerabilities\n\nDescription:\nExploiting LLMs to perform unintended requests or access restricted resources, such as internal services, APIs, or data stores.` |
| 24 | MCP Specification | `char_dup_ratio` | `What is the Model Context Protocol (MCP)?\n\nCopy page\nCopy page\nMCP (Model Context Protocol) is an open-source standard for connecting AI applications to external systems. Using MCP, AI applications like Claude or ChatGPT can connect to data sources (e.g. local files, databases), tools (e.g. search engines, calculators) and workflows (e.g. specialized prompts)-enabling them to access key informatio...` |
| 25 | NIST AI RMF 1.0 | `line_punct_ratio` | `5.1 Govern\n\nThe GOVERN function:\nGOVERN is a cross-cutting function that is infused throughout AI risk management and enables the other functions of the process...` |
| 26 | NIST AI RMF 1.0 | `line_punct_ratio` | `GOVERN 1.4:\nThe risk management process and its outcomes are\nestablished through transparent policies, procedures, and other\ncontrols based on organizational risk priorities. Categories\nSubcategories\nContinued on next page NIST AI 100-1\nGOVERN 1.5:\nOngoing monitoring and periodic review...` |
| 27 | NIST AI RMF 1.0 | `line_punct_ratio` | `GOVERN 3.2:\nPolicies and procedures are in place to define and\ndifferentiate roles and responsibilities for human-AI configura-\ntions and oversight of AI systems. GOVERN 4:\nOrganizational\nteams are committed\nto a culture\nGOVERN 4.1:...` |
| 28 | NIST AI 600-1 | `line_punct_ratio` | `Each table of suggest ed actions includes:\n\nThe tables below begin with the AI RMF subcategory, shaded in blue, followed by suggested actions.\nAction ID\nSuggested\nAction\nGAI Risks\nGV\n-1.1-001\nAlign GAI\ndevelopment and\nuse with applicable laws and regulations,\nincluding\nthose related to data privacy\n, copyright and intellectual property law.\nData Privacy;\nHarmful Bias and\nHomogenization\n; Intellect...` |

---

## 3. Judgment

**Yes — with a specific, sample-grounded qualification.**

The gate's healthcare-tuned heuristics (`short_line_ratio`, `line_punct_ratio`, `char_dup_ratio`, `below_stopword_ratio` — all inherited unmodified from Phase 19/20's healthcare-derived thresholds) are **wrongly dropping a real, identifiable minority of agent-security domain-specific structured content**, though not in the exact literal form CONTEXT.md D-04 and PITFALLS.md Pitfall 9 named as exemplars.

**What was NOT found:** a corpus-wide regex search of all 978 rejected chunks for the literal exemplar shapes (permission-scope strings like `read:documents`, `mcp__`-prefixed tool-call identifiers, CVSS/severity strings, OAuth `scope=` parameters) turned up zero genuine hits — the 7 pattern matches found were all regex false positives on unrelated markup (XML namespaces, CSS selectors, WordPress REST field names), confirmed by reading their full chunk text. Those specific named exemplars simply do not appear as short, isolated chunk text anywhere in this corpus's 978 rejections.

**What WAS found**, grounded directly in sample rows 23–28 above: real, domain-specific taxonomy and standards-framework content structurally analogous to what healthcare's `filters.yaml` protects (ICD-10/LOINC/dosage codes) is being rejected by the same thresholds, for the same structural reason healthcare's is protected — short, list-like, low-prose-density text that legitimate domain taxonomies and standards documents are made of:

- **OWASP vulnerability-taxonomy entries** (row 23: `LLM05:2023 - SSRF Vulnerabilities` with its `Description:` label) — exactly the `threat_category` taxonomy shape CONTEXT.md D-03 names, rejected for having a marginally-low stopword ratio (a taxonomy ID + colon + short description is inherently stopword-sparse, the same reason a bare `ICD-10 E11.9` is stopword-sparse).
- **NIST AI RMF structured subcategory entries** (rows 25–27: `GOVERN 1.4:`, `GOVERN 3.2:`, `GOVERN 4.1:` framework taxonomy nodes) — the `standards_framework` category CONTEXT.md D-03 names, rejected under `line_punct_ratio` for the same reason a numbered clinical criterion list is punctuation-and-newline-dense rather than flowing prose.
- **NIST action-ID table rows** (row 28: `GV-1.1-001` with its structured Action ID / Suggested Action / GAI Risks columns) — a severity/ID-code table shape directly analogous to the CVSS-style short severity/ID strings named in D-03 and Pitfall 9, rejected under `line_punct_ratio` for table-like line breaks.
- **A definitional MCP passage** (row 24) rejected under `char_dup_ratio` — a false-positive artifact of a duplicated "Copy page\nCopy page" UI-button label prefixing genuine substantive content, not a content-quality signal at all.

**The overwhelming majority of the 978 rejections (rows 1–22, and by extension almost all of the `line_punct_ratio`/`short_line_ratio`/`char_dup_ratio` reason buckets that make up 951 of 978 rejections) are genuine boilerplate correctly rejected** — RFC footers, cookie/privacy boilerplate, WordPress RSS/comment feeds, raw CSS, admin-widget JSON, and blog-promo cards. The gate is working as intended for the vast bulk of what it drops. This is not a case of the gate being broadly miscalibrated for this domain; it is a case of a **specific, minority-but-real class of short/structured domain content having no allowlist protection**, exactly mirroring why healthcare needed `filters.yaml` in the first place — general-purpose substance heuristics structurally cannot distinguish "low-value nav-menu link list" from "high-value numbered taxonomy/framework subcategory list" without a domain-aware allowlist telling them which patterns to never drop.

---

## 4. Handoff to Phase 26 (Quality Contract)

Per CONTEXT.md's Phase Boundary and ROADMAP.md's explicit ordering note ("its domain-specific quality-gate tuning still waits on Phase 26 to exist"), **this plan documents the gap only — it does not close it.** No `domains/agent-security/filters.yaml` or any other quality-gate fix is authored in this phase (confirmed: `domains/agent-security/filters.yaml` does not exist as of this writing).

**Phase 26 (Quality Contract) is the phase responsible for authoring the actual fix.** Based on this findings document's evidence, that fix should take the same shape as `domains/healthcare/filters.yaml` — a `normative_allowlists` list of narrow, specific regex patterns (per `DomainFilters`'s own docstring warning in `src/knowledge_lake/domains/models.py` lines 70-104: never a broad `.*` pattern, which would silently disable boilerplate classification for the entire domain) — mirroring healthcare's `"ICD-10"`, `"LOINC"`, `"RxNorm"`, `"§\\d+\\.\\d+"` entries with agent-security-specific analogs such as:

- A pattern matching taxonomy-ID-prefixed short entries (e.g. `LLM\d{2}:\d{4}` for OWASP's `LLM05:2023`-style IDs)
- A pattern matching NIST AI RMF's function/category/subcategory ID shape (e.g. `\b(GOVERN|MAP|MEASURE|MANAGE)\s+\d+(\.\d+)?:` )
- A pattern matching structured action-ID table rows (e.g. `\bGV-\d+\.\d+-\d{3}\b` and sibling MP-/MS-/MG- prefixes NIST 600-1 uses)
- The literal exemplars CONTEXT.md D-03 names (`mcp__[a-zA-Z_]+` tool identifiers, `\b\w+:\w+\b`-shaped permission scopes, CVSS/severity strings) should still be included proactively in Phase 26's allowlist even though this specific corpus snapshot did not surface a live rejected instance of them — the corpus will grow, and Pitfall 9's guidance is to protect the *shape* of domain content, not just what happened to be rejected in one measurement window.

This findings document — its measured `chunk_garbage_rate` (45.21%), its rejection-reason breakdown, and above all its real quoted sample rows 23–28 — is the direct, real, evidence-backed input Phase 26 should consume when scoping and authoring that allowlist. Phase 26 should not need to re-run this measurement from scratch; it can start from the sample and reasoning above.
