# Phase 19: Section Classifier + Patterns - Research

**Researched:** 2026-07-16
**Domain:** Section-level content classification, regex boilerplate extension, domain-pack filter config, pure quality predicates (Python/Pydantic/regex — no new external dependencies)
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

#### Section Classifier Architecture (CLEAN-04)
- **D-01:** A dedicated `classify_sections()` function computes per-section substance annotations (link_density, terminal_punct_ratio, stopword_ratio, token_count) and a `is_boilerplate: bool` flag. Classification is separated from filtering — the classifier annotates, a subsequent step decides keep/reject. This follows the project's "deterministic first" constraint.
- **D-02:** `clean()` evolves to operate at section granularity: load `ParsedDoc.sections`, run `classify_sections()` on each, filter out boilerplate sections, and return a cleaned `ParsedDoc` with only kept sections. The monolithic `remove_boilerplate(full_text)` remains available but `clean()` uses section-level classification as the primary path.
- **D-03:** Boilerplate classification uses the existing `BOILERPLATE_PATTERNS` regex list (extended per CLEAN-05) PLUS the substance signals. A section is classified as boilerplate if: (a) it matches a boilerplate regex pattern, OR (b) its substance signals fall below thresholds (low token_count + low terminal_punct_ratio + high link_density). Domain allowlists (CLEAN-06) can override the classification.

#### Substance Annotation Storage (CLEAN-04)
- **D-04:** Per-section substance annotations are stored in the `cleaned_document` artifact's `metadata_` dict under a `section_annotations` key. Each entry carries the section index, substance signals, and the keep/reject decision with reason. No new artifact type is created — the cleaned sidecar IS the cleaned_document artifact.

#### Extended Boilerplate Patterns (CLEAN-05)
- **D-05:** Extend `BOILERPLATE_PATTERNS` beyond the current 4 regexes to cover all 5 garbage categories from the audit: navigation menus, terms-of-service blocks, enrollment/marketing CTAs, cookie consent, and government disclaimer boilerplate. New patterns are additive — existing 4 patterns remain unchanged. Phase 3 test assertions must continue to pass.
- **D-06:** The gate-local frozen `_GATE_BOILERPLATE_PATTERNS` in `crawl.py` (Phase 18) is NOT updated when `BOILERPLATE_PATTERNS` is extended. This is the entire point of Phase 18's decoupling.

#### Domain-Pack Filter Configuration (CLEAN-06)
- **D-07:** `DomainLoader` gains optional `filters.yaml` loading. The file is optional — domain packs without it work with framework defaults only. When present, it is validated against a `DomainFilters` Pydantic model containing: `boilerplate_patterns` (additional regex patterns), `normative_allowlists` (regex patterns that must never be dropped), and `thresholds` (domain-specific substance thresholds).
- **D-08:** The healthcare pack contributes a `filters.yaml` with a clinical-code allowlist: `ICD-10`, `LOINC`, `RxNorm`, `§\d+\.\d+`, dosage patterns (`\d+\s*mg`, `PO\s+BID`, etc.). A section matching any allowlist pattern is never classified as boilerplate regardless of its substance signals.
- **D-09:** The `DomainFilters` model is defined in `domains/models.py` alongside the existing `DomainManifest`, `SourceEntry`, and `TaxonomyManifest` models.

#### Quality Predicate Module (QUAL-01)
- **D-10:** A `pipeline/quality/` package with pure predicate functions: `f(text, metadata) -> PredicateResult(passed: bool, reason: str)`. Zero dependencies on I/O, S3, Dagster, or settings. Each predicate is a standalone function.
- **D-11:** Predicates include: `check_token_floor()`, `check_alpha_ratio()`, `check_link_density()`, `check_stopword_ratio()`, `check_table_exemption()`, `check_domain_allowlist()`. A `run_predicates()` combinator applies them in sequence and returns a composite result.
- **D-12:** The quality predicate module is designed for consumption by Phase 20's chunk substance gate (QUAL-03). Phase 19 builds the module; Phase 20 wires it into the pipeline. The same predicates can also be used by the section classifier's substance check (D-03), providing consistency between section-level and chunk-level quality gates.

### Claude's Discretion

Claude has flexibility on: exact substance signal thresholds, regex pattern details for the 5 new garbage categories, `PredicateResult` implementation (namedtuple vs dataclass), internal module structure of `pipeline/quality/`, test fixture content, and whether `classify_sections()` lives in `clean.py` or a new `pipeline/classify.py` module.

### Deferred Ideas (OUT OF SCOPE)

None — discussion stayed within phase scope.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-------------------|
| CLEAN-04 | Section-aware cleaning with substance annotations — `clean()` must operate at section granularity, annotate each section with substance signals, and return a cleaned `ParsedDoc` with junk sections removed | Pattern 1 (classify-then-filter), Code Examples (`_clean_sections` extension), Pitfall 3 (allowlist-first ordering), Validation Architecture test map |
| CLEAN-05 | Extended boilerplate patterns covering all 5 garbage categories, additive to the existing 4 | Pattern 2 (additive regex extension), Open Question 2 (fixture validation against real audit sources), Pitfall 5 (order-dependent test assertions) |
| CLEAN-06 | Domain-pack filter configuration — optional `filters.yaml`, `DomainFilters` model, healthcare clinical-code allowlist | Code Examples (`DomainFilters` model), Pitfall 4 (optional-file loading must not break existing packs), Security Domain (V5 input validation via `yaml.safe_load`) |
| QUAL-01 | Pure quality predicate module — zero I/O/S3/Dagster dependencies, composable predicates, 100% branch coverage | Pattern 3 (gate-local duplication for dependency isolation), Pitfall 1 (DataTrove tokenizer crash), Don't Hand-Roll table, Validation Architecture (coverage gate command) |
</phase_requirements>

## Summary

Phase 19 extends three existing, already-read files (`pipeline/clean.py`, `domains/loader.py`,
`domains/models.py`) and creates one new package (`pipeline/quality/`). All the scaffolding this
phase needs already exists and was purpose-built for it: `clean.py`'s `_clean_sections()` (built in
Phase 17) already iterates `ParsedDoc.sections`, counts kept/rejected/considered, and enforces the
QUAL-05 conservation invariant — but it never actually *drops* a section (CLEAN-04's section removal
is explicitly deferred to this phase, per its own docstring). `crawl.py`'s `_GATE_BOILERPLATE_PATTERNS`
(Phase 18) is a frozen, deliberately-duplicated copy of `BOILERPLATE_PATTERNS` — extending the live
list in `clean.py` is safe by construction and requires zero changes to `crawl.py`.

The riskiest technical finding: Docling's parser (`docling_parser.py::_extract_sections`) **never
sets `Section.is_table=True`** — no `DocItemLabel.TABLE` handling exists in any builtin parser. This
means `check_table_exemption()` (D-11) is currently a dead safety net for real-world Docling-parsed
documents; it must still be built (it protects other parsers and future Docling table support), but
the planner should not treat it as sufficient protection for tabular dosage/lab-value content today —
the domain allowlist (D-08) is the actual safety net for clinical codes embedded in prose or malformed
table-as-text sections.

Second finding: DataTrove (already a pinned dependency, used in `curate.py`) exposes reusable,
zero-I/O building blocks — `STOP_WORDS` (8-word list) and `TERMINAL_PUNCTUATION` (a set) importable
cheaply from `datatrove.pipeline.filters.gopher_quality_filter` and `datatrove.utils.text`. However,
`datatrove.utils.text.split_into_words()` internally requires a spaCy tokenizer backend and **raised
`AttributeError: module 'importlib' has no attribute 'metadata'`** when invoked in this environment —
confirmed by direct execution. Do not call `split_into_words()` from `pipeline/quality/`. Use a
dependency-free `text.split()` or `\w+` regex for word tokenization instead, and reuse only the
static `STOP_WORDS` / `TERMINAL_PUNCTUATION` constants (safe, cheap imports, no tokenizer factory
invoked).

Third finding: `pipeline/chunk.py` already has a `token_count()` helper using a cached
`tiktoken.get_encoding("cl100k_base")` encoder — the natural choice for consistency between
section-level and chunk-level substance gates (D-12's explicit goal). But `chunk.py` imports
`registry.repo`, `registry.db`, and `storage.s3` at module scope — importing `pipeline.chunk` from
`pipeline/quality/` would transitively pull in DB/S3 dependencies and violate QUAL-01's "zero I/O, S3,
Dagster" requirement. The codebase already has a precedent for resolving exactly this tension:
`crawl.py`'s `_GATE_BOILERPLATE_PATTERNS` is a deliberate, frozen, duplicated copy of `clean.py`'s
patterns specifically to avoid a cross-module dependency. Apply the same idiom: `pipeline/quality/`
should instantiate its own module-level `tiktoken.get_encoding("cl100k_base")` encoder, duplicating
the ~6-line `token_count()` function rather than importing `chunk.py`.

**Primary recommendation:** Build `classify_sections()` and `pipeline/quality/` as pure, dependency-free
modules that duplicate small helpers (token counting, stopword/punctuation constants) rather than
importing from `chunk.py` or `clean.py`'s heavier siblings — mirroring the `crawl.py` gate-decoupling
precedent already proven in Phase 18. Wire `classify_sections()` into `clean()`'s existing
`_clean_sections()` call site so `clean()` becomes the single place sections are both cleaned and
filtered.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Section substance classification | Pipeline (silver zone, `clean.py`) | Quality module (`pipeline/quality/`) | `clean()` orchestrates; predicates are pure functions it calls |
| Boilerplate regex matching | Pipeline (`clean.py`) | Domain pack (`filters.yaml`) | Framework defaults + domain-pack additive patterns |
| Domain-code allowlist (never-drop) | Domain pack (`domains/healthcare/filters.yaml`) | Domain loader (`DomainLoader`) | Domain-specific knowledge must live in the domain pack, not framework code |
| Pure quality predicates | Quality module (`pipeline/quality/`) | — | Zero I/O by design — consumed by both `clean.py` (Phase 19) and `chunk.py`/Phase 20's gate |
| Gate-signature stability | `crawl.py` (frozen local copy) | — | Already decoupled in Phase 18; Phase 19 must not touch it |

## Standard Stack

### Core (all already installed — no new packages)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Pydantic | 2.13.x [VERIFIED: pyproject.toml pin `pydantic` already in use for `DomainManifest`/`SourceEntry`] | `DomainFilters` model validation | Matches existing `domains/models.py` pattern exactly |
| PyYAML (`yaml.safe_load`) | already a dep | Load optional `filters.yaml` | `DomainLoader` already uses `yaml.safe_load` exclusively (T-06-04) |
| tiktoken | already a dep (`pipeline/chunk.py` uses `cl100k_base`) | `token_count()` in quality predicates | Consistency with chunk-level token accounting (D-12) |
| `re` (stdlib) | — | Extended `BOILERPLATE_PATTERNS`, allowlist regexes | Deterministic-first constraint; no NLP library needed for pattern matching |
| datatrove (constants only) | 0.9.0 [VERIFIED: `pip show datatrove` → 0.9.0, matches CLAUDE.md pin] | `STOP_WORDS`, `TERMINAL_PUNCTUATION` constants | Already a pinned dependency (`curate.py`); reuse constants, not the tokenizer |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `dataclasses.replace` | stdlib | Build cleaned `Section` copies | Already the established pattern in `_clean_sections()` — never mutate caller's `Section` objects |
| `structlog` | already a dep | Logging classification decisions | Matches every other pipeline module's logging convention |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Duplicating `token_count()` in `pipeline/quality/` | Import `pipeline.chunk.token_count` | Importing `chunk.py` pulls in `registry.db`/`storage.s3` at module scope — violates QUAL-01's zero-I/O requirement. Duplication (with a comment citing this rationale) is the correct choice, mirroring the `crawl.py` gate-decoupling precedent. |
| `datatrove.utils.text.split_into_words()` for tokenization | `text.split()` / `re.findall(r"\w+", text)` | `split_into_words()` requires a spaCy tokenizer backend that **raised `AttributeError` in this environment** when invoked directly. Confirmed empirically — do not use in `pipeline/quality/`. |
| nltk stopwords corpus | DataTrove's static `STOP_WORDS` list (8 words) | nltk requires a corpus download (`nltk.download('stopwords')`) which is an I/O side effect at runtime — violates QUAL-01's zero-I/O constraint. DataTrove's tiny static list is a plain Python list, safe to import. |
| A new `PredicateResult` dataclass | `NamedTuple` | Both are fine (Claude's Discretion, D-decisions). Recommend `dataclass(frozen=True)` for readability/extensibility parity with `ValidationResult` in `domains/models.py`, which is the closest existing precedent in this codebase. |

**Installation:** None required — zero new packages for this phase.

**Version verification:** `datatrove==0.9.0`, `pydantic` (already pinned), `tiktoken` (already used in `chunk.py`) — all confirmed already present in `.venv` via `pip show` / direct import. No registry lookups needed since nothing new is installed.

## Package Legitimacy Audit

**No new external packages are introduced by this phase.** All functionality is built from already-installed, already-pinned dependencies (`pydantic`, `PyYAML`, `tiktoken`, `datatrove` — constants only) plus stdlib (`re`, `dataclasses`). The Package Legitimacy Gate is not applicable; no `npm view` / `pip index versions` / registry check is required.

**Packages removed due to [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

## Architecture Patterns

### System Architecture Diagram

```
ParsedDoc.sections (from Docling/Tika/Unstructured parser)
        │
        ▼
┌───────────────────────────────────────────────────────────┐
│ clean.py :: clean()                                        │
│                                                              │
│  parsed_doc.sections                                        │
│        │                                                    │
│        ▼                                                    │
│  classify_sections(sections, domain_filters)  ◄── NEW       │
│        │                                                    │
│        │  for each Section:                                 │
│        │    1. compute substance signals ────────────┐      │
│        │       (link_density, terminal_punct_ratio,   │      │
│        │        stopword_ratio, token_count)          │      │
│        │                    │                          │      │
│        │                    ▼                          │      │
│        │       pipeline/quality/ pure predicates ◄──────┘      │
│        │       (check_token_floor, check_alpha_ratio,          │
│        │        check_link_density, check_stopword_ratio,      │
│        │        check_table_exemption, check_domain_allowlist) │
│        │                    │                                  │
│        │                    ▼                                  │
│        │       run_predicates() → PredicateResult(passed,reason)│
│        │                    │                                  │
│        │    2. regex check: BOILERPLATE_PATTERNS               │
│        │       (extended, 5 categories) OR domain               │
│        │       filters.yaml boilerplate_patterns                │
│        │                    │                                  │
│        │    3. domain allowlist override (D-08):                │
│        │       normative_allowlists match → NEVER boilerplate   │
│        │                    │                                  │
│        │                    ▼                                  │
│        │       is_boilerplate: bool + reason                    │
│        │                                                          │
│        ▼                                                          │
│  filter kept sections → cleaned ParsedDoc.sections (junk REMOVED) │
│        │                                                          │
│        ▼                                                          │
│  section_annotations → cleaned_document.metadata_["section_annotations"] │
└───────────────────────────────────────────────────────────┘
        │
        ▼
chunk_document / tree_index_document / enrich_document
(all three already consume clean_document["parsed_doc"] — Phase 17 wiring; no change needed there)

Domain pack:
domains/healthcare/filters.yaml (optional)
        │
        ▼
DomainLoader.filters: DomainFilters | None  ◄── NEW (loader.py, models.py)
        │  boilerplate_patterns: list[str]
        │  normative_allowlists: list[str]  (ICD-10, LOINC, RxNorm, §\d+\.\d+, dosage patterns)
        │  thresholds: dict[str, float]
        │
        └──► consumed by classify_sections() as domain_filters= parameter
```

### Recommended Project Structure

```
src/knowledge_lake/pipeline/
├── clean.py                 # classify_sections() added here (Claude's discretion: or new classify.py)
├── quality/                 # NEW package (QUAL-01)
│   ├── __init__.py           # re-exports run_predicates, PredicateResult, check_*
│   ├── predicates.py          # pure predicate functions — zero I/O/S3/Dagster/settings imports
│   └── constants.py           # local STOP_WORDS-derived set, TERMINAL_PUNCTUATION import, local token_count()
src/knowledge_lake/domains/
├── loader.py                 # + optional filters.yaml loading (CLEAN-06)
├── models.py                  # + DomainFilters model
domains/healthcare/
├── filters.yaml               # NEW — clinical-code allowlist (D-08)
tests/unit/
├── test_clean.py               # extend: classify_sections + section removal tests
├── test_quality_predicates.py   # NEW — 100% branch coverage target
├── test_domain_loader.py         # extend: filters.yaml optional-load tests
├── test_domain_filters_model.py   # NEW (or folded into test_domain_loader.py)
```

### Pattern 1: Classify-then-filter separation (D-01, D-02)

**What:** `classify_sections()` is a pure annotation step — it never mutates or drops sections. A
separate step in `clean()` (or a thin wrapper) uses the returned `is_boilerplate` flags to build the
filtered section list.

**When to use:** Always, per D-01 — "classification is separated from filtering." This mirrors the
DataTrove `BaseFilter.filter(doc) -> bool | tuple[bool, str]` idiom already used in `curate.py`
(`_apply_filters`), which calls `.filter(doc)` directly rather than `.run()` specifically so results
for every filter are visible, not just the first failure (RESEARCH.md Pitfall 2 from Phase 5's
research, referenced in `curate.py` docstring).

**Example (grounded in existing `_clean_sections` shape in `clean.py:172`):**
```python
# Source: existing pattern in src/knowledge_lake/pipeline/clean.py:172-215
def classify_sections(
    sections: list[Section],
    *,
    domain_filters: DomainFilters | None = None,
) -> list[SectionClassification]:
    """Pure annotation step — never mutates or drops sections."""
    results = []
    for section in sections:
        signals = _compute_substance_signals(section.text)
        allowlisted = _matches_allowlist(section.text, domain_filters)
        is_boilerplate = (
            not allowlisted
            and (_matches_boilerplate_pattern(section.text, domain_filters)
                 or _fails_substance_thresholds(signals))
        )
        results.append(SectionClassification(
            section=section, signals=signals,
            is_boilerplate=is_boilerplate, allowlisted=allowlisted,
        ))
    return results
```

### Pattern 2: Additive regex extension, never replace (D-05)

**What:** `BOILERPLATE_PATTERNS` in `clean.py:48` grows from 4 to ~9+ entries. The existing 4 must
remain byte-identical (Phase 3 tests in `tests/unit/test_clean.py` assert on them directly by
behavior, e.g. `test_boilerplate_removal_page_header`).

**When to use:** Extending `BOILERPLATE_PATTERNS` for CLEAN-05's five categories:
- navigation menus (extend the existing nav-line pattern's word list, or add a new line-anchored
  pattern for common nav phrases like "Skip to footer", "Main menu", breadcrumbs)
- terms-of-service blocks (new pattern — multi-line block detection is harder with line-anchored
  regex; consider a paragraph-level heuristic: a section/line containing "terms of service" or
  "terms and conditions" case-insensitively)
- enrollment/marketing CTAs ("Enroll now", "Sign up today", "Register for", "$X per exam" style
  patterns — this overlaps with the audit's "Marketing/pricing" category)
- cookie consent (existing pattern already covers "this site uses cookies" / "accept all cookies" /
  "cookie policy" — verify audit fixture language against this before assuming coverage gaps)
- government disclaimer boilerplate ("This website is not a substitute for...", ".gov footer text",
  "For Official Use Only", "Privacy Policy" line)

**Anti-pattern:** Do not replace `BOILERPLATE_PATTERNS[0:4]` positionally — always `.append()` or
concatenate a new list, so accidental reordering never breaks the Phase-3 assertions that check
specific substrings are removed/preserved.

### Pattern 3: Gate-local duplication for dependency isolation (established precedent)

**What:** When a pure/isolated module needs a tiny helper from a heavier module, duplicate the
helper locally with a comment explaining why, rather than importing the heavier module.

**When to use:** `pipeline/quality/`'s token counting. This is not a new pattern invented for this
phase — it is the exact idiom Phase 18 already used for `_GATE_BOILERPLATE_PATTERNS` in `crawl.py`
(a frozen, explicitly-not-synced duplicate of `clean.py`'s `BOILERPLATE_PATTERNS`, with a comment
citing GATE-01). Apply identically here.

**Example:**
```python
# Source: pipeline/chunk.py:53 pattern, duplicated per QUAL-01's zero-I/O
# constraint (importing pipeline.chunk would pull in registry.db/storage.s3
# at module scope). See crawl.py's _GATE_BOILERPLATE_PATTERNS for the
# established precedent of this duplication-for-isolation idiom (Phase 18).
import tiktoken as _tiktoken
_encoder = _tiktoken.get_encoding("cl100k_base")

def token_count(text: str) -> int:
    return len(_encoder.encode(text))
```

### Anti-Patterns to Avoid

- **Calling `datatrove.utils.text.split_into_words()` from `pipeline/quality/`:** Confirmed to raise
  `AttributeError: module 'importlib' has no attribute 'metadata'` in this environment via the spaCy
  tokenizer factory path. Use `text.split()` or a simple `\w+` regex instead.
- **Positional replacement of `BOILERPLATE_PATTERNS` entries:** Breaks Phase-3 test assumptions about
  pattern order/content. Always append.
- **Assuming `section.is_table=True` reliably marks tables:** No builtin parser (`docling_parser.py`,
  `tika_parser.py`, `unstructured_parser.py`, `json_xml_parser.py`) currently sets this flag to
  `True` anywhere. `check_table_exemption()` must still be built per D-11, but treat it as
  forward-looking infrastructure, not a currently-effective safety net — the domain allowlist is the
  real protection for tabular clinical content today.
- **Importing `pipeline.chunk` or `pipeline.clean` into `pipeline/quality/`:** Both modules import
  `registry.db`/`storage.s3`/`config.settings` at module scope, which would break QUAL-01's
  zero-dependency contract even if the predicate functions themselves never call those imports.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Stopword list | A custom curated English stopword list | DataTrove's `STOP_WORDS` (8-word) constant, imported directly (not via the filter class) | Already a pinned dependency; avoids introducing nltk's corpus-download I/O or spaCy's model dependency for something this small |
| Terminal punctuation set | Hand-enumerate `.`, `!`, `?`, and Unicode terminal punctuation | `datatrove.utils.text.TERMINAL_PUNCTUATION` (a `set`, safe to import directly) | Already covers Unicode terminal punctuation (Arabic, Armenian, CJK, etc.) — a hand-rolled ASCII-only set would silently misclassify non-English clinical sources |
| Token counting | `len(text.split())` word-count as a token proxy | Module-local `tiktoken.get_encoding("cl100k_base")` encoder (duplicated per Pattern 3 above) | Matches `ChunkSettings.tokenizer = "cl100k_base"` and `chunk.py`'s existing `token_count()` — keeping section-level and chunk-level substance signals on the same unit avoids threshold-tuning drift between Phase 19 and Phase 20 (D-12's explicit goal) |
| Domain-pack YAML parsing | A bespoke parser/validator for `filters.yaml` | `yaml.safe_load()` + `DomainFilters(BaseModel)`, following `DomainManifest`/`SourceEntry`'s exact pattern in `domains/models.py` | `DomainLoader` already has this exact optional-file idiom fully solved for mandatory files; only the "optional, framework-default-if-absent" branch is new |

**Key insight:** Every "don't hand-roll" item in this phase already has a precedent living in the
codebase or an already-pinned dependency. There is no case where this phase needs to reach for a new
library — the discipline here is choosing the *lightweight* half of an existing dependency
(constants, not tokenizer classes) and duplicating tiny pure functions rather than creating
cross-module coupling.

## Common Pitfalls

### Pitfall 1: `datatrove.utils.text.split_into_words()` crashes in this environment

**What goes wrong:** Calling `split_into_words(text)` (or any DataTrove function that routes through
`load_word_tokenizer()`) raises `AttributeError: module 'importlib' has no attribute 'metadata'`
inside `datatrove/utils/_import_utils.py::_is_distribution_available`.

**Why it happens:** DataTrove's word tokenizer factory lazily checks for `spacy` availability via
`importlib.metadata.distributions()`, but in this environment `importlib.metadata` isn't accessible
as an attribute of the already-imported `importlib` module (a DataTrove-side import-ordering bug,
not something this codebase can fix).

**How to avoid:** Never call `split_into_words()`/`split_into_sentences()`/`split_into_paragraphs()`
from `pipeline/quality/`. Use `text.split()` (whitespace) for `stopword_ratio`'s word tokenization,
and a simple regex (e.g. `re.split(r'(?<=[.!?])\s+', text)` or scanning for `TERMINAL_PUNCTUATION`
membership at line/text end) for `terminal_punct_ratio`.

**Warning signs:** Any traceback mentioning `word_tokenizers.py` or `_import_utils.py` during test
runs of the new `pipeline/quality/` module.

### Pitfall 2: `is_table` exemption is a no-op for real Docling documents today

**What goes wrong:** A planner or reviewer might assume `check_table_exemption()` fully protects
tabular dosage/lab-value data because D-11 lists it as a predicate. In practice, `docling_parser.py`
never sets `Section.is_table=True` (no `DocItemLabel.TABLE` handling in `_extract_sections()`), and
neither do the other three builtin parsers.

**Why it happens:** Table extraction/flagging was never wired into the parser layer — this predates
Phase 19 and is out of this phase's requirement scope (CLEAN-04/05/06/QUAL-01 do not mention parser
changes).

**How to avoid:** Build `check_table_exemption()` per D-11 (it's still correct forward-looking
infrastructure and protects any future parser/format that does set the flag), but do not rely on it
as the primary defense for clinical tabular content in this phase's verification. The domain
allowlist (D-08, matching `ICD-10`, `LOINC`, `RxNorm`, dosage regex patterns like `\d+\s*mg`,
`PO\s+BID` against section *text*, regardless of `is_table`) is what actually satisfies success
criterion 3 ("`ICD-10 E11.9` or `Metformin 500 mg PO BID` is never dropped").

**Warning signs:** A must-not-reject test fixture that is a genuine HTML/PDF table (not prose) failing
even after the allowlist is wired — this would surface the parser gap, which is out of Phase 19's
scope to fix but should be flagged in `Open Questions` for a future phase.

### Pitfall 3: Section-level allowlist checks must run BEFORE the substance-threshold check, not after

**What goes wrong:** If the pipeline computes `is_boilerplate` from substance signals first and only
consults the allowlist as a tie-breaker on ambiguous cases, a short clinical-code-only section (e.g.
a table row rendered as a section with text `"ICD-10 E11.9"` — 3 tokens, no terminal punctuation, high
symbol density) will fail every substance threshold and get dropped before the allowlist is ever
consulted.

**Why it happens:** It's natural to write `is_boilerplate = fails_thresholds and not regex_match`,
but a boolean expression evaluated in the wrong order, or a predicate combinator that short-circuits
on the first failing check without checking allowlist membership, produces exactly this bug.

**How to avoid:** The allowlist check must be an unconditional override applied last:
`is_boilerplate = (not allowlisted) and (matches_boilerplate_pattern or fails_substance_thresholds)`.
Write the must-not-reject fixture tests (short ICD/RxNorm/dosage strings) FIRST as a regression guard
before implementing the threshold logic (TDD-first for this specific interaction, given its safety
criticality).

### Pitfall 4: `filters.yaml` being optional must not break domain packs that lack it

**What goes wrong:** If `DomainLoader.__init__` treats `filters.yaml` the same way it treats the four
mandatory files (`domain.yaml`, `sources.yaml`, `taxonomy.yaml`, `validators/validate.py` —
`FileNotFoundError` if missing), every existing domain pack (`aviation`, `climate`, `local/*`)
immediately breaks on next load.

**Why it happens:** `DomainLoader`'s existing pattern for all 4 current files is
"required-or-raise" — CLEAN-06's `filters.yaml` is the first optional file this loader has ever had,
so there's no copy-paste-safe precedent to follow blindly.

**How to avoid:** Explicit `if filters_yaml_path.exists(): ... else: self.filters = None` (or a
`DomainFilters()` all-default instance) — never raise `FileNotFoundError` for this one file. Add a
regression test loading `domains/aviation` (which will not have `filters.yaml`) to prove the loader
doesn't require it.

### Pitfall 5: `BOILERPLATE_PATTERNS` order-dependent Phase-3 assertions

**What goes wrong:** `tests/unit/test_clean.py` tests specific substrings being removed/preserved
(e.g. `"Page 3 of 10" not in result`). None of them assert on list length or index — but a careless
refactor (e.g. converting `BOILERPLATE_PATTERNS` into a dict keyed by category, or wrapping each
pattern in a new tuple structure) would break every call site that iterates `for pattern in
BOILERPLATE_PATTERNS: text = pattern.sub("", text)` in `remove_boilerplate()`.

**Why it happens:** `BOILERPLATE_PATTERNS: list[re.Pattern]` — its type signature is a flat list;
changing that shape ripples into `remove_boilerplate()`, and transitively into `crawl.py`'s frozen
snapshot comparison test (18-01's pinning test), which processes the SAME `KNOWN_INPUT` through both
`_gate_normalize()` (frozen) and `clean.py::remove_boilerplate()` (with an added pattern) to prove
decoupling.

**How to avoid:** Keep `BOILERPLATE_PATTERNS` a flat `list[re.Pattern]`; append new compiled patterns
to it. Run the Phase 18 pinning test (`tests/unit/test_crawl_gate_signature.py` or wherever
18-01-PLAN.md placed it) after extending patterns, to prove gate decoupling still holds.

## Code Examples

### Reading the existing `_clean_sections` shape to extend (not replace) it

```python
# Source: src/knowledge_lake/pipeline/clean.py:172-215 (current, pre-Phase-19)
def _clean_sections(
    sections: list[Section],
) -> tuple[list[Section], int, int, int, dict[str, int]]:
    cleaned_sections: list[Section] = []
    rejection_reasons: dict[str, int] = {}
    sections_kept = 0
    sections_rejected = 0

    for section in sections:
        cleaned_section_text = remove_boilerplate(section.text)
        cleaned_sections.append(replace(section, text=cleaned_section_text))
        if cleaned_section_text.strip():
            sections_kept += 1
        else:
            sections_rejected += 1
            reason = "empty_after_boilerplate_removal"
            rejection_reasons[reason] = rejection_reasons.get(reason, 0) + 1

    sections_considered = len(sections)
    return cleaned_sections, sections_considered, sections_kept, sections_rejected, rejection_reasons
```

Phase 19's job (per D-02, D-03): after cleaning each section's text (unchanged above), ALSO call
`classify_sections()` on the result and drop sections where `is_boilerplate=True`, tracking a NEW
rejection reason (e.g. `"classified_as_boilerplate"`) alongside the existing
`"empty_after_boilerplate_removal"` reason — additive to the existing `rejection_reasons` dict shape
that `quality_audit.py` and `test_quality_audit.py` already depend on.

### DataTrove constants safe to import directly (verified working)

```python
# Source: verified via direct execution in this environment, 2026-07-16
from datatrove.pipeline.filters.gopher_quality_filter import STOP_WORDS
# STOP_WORDS == ['the', 'be', 'to', 'of', 'and', 'that', 'have', 'with']

from datatrove.utils.text import TERMINAL_PUNCTUATION, PUNCTUATION_SET
# TERMINAL_PUNCTUATION is a set including '.', '!', '?' plus Unicode terminal marks
```

### DomainFilters model (following DomainManifest's exact pattern)

```python
# Source: pattern from src/knowledge_lake/domains/models.py (DomainManifest, SourceEntry)
class DomainFilters(BaseModel):
    """Optional domain-pack filter configuration from filters.yaml (CLEAN-06)."""

    boilerplate_patterns: list[str] = []
    """Additional regex patterns (as strings — compiled by the loader/classifier)."""

    normative_allowlists: list[str] = []
    """Regex patterns that must never be classified as boilerplate regardless
    of substance signals (e.g. ICD-10, LOINC, RxNorm, dosage patterns)."""

    thresholds: dict[str, float] = {}
    """Domain-specific override thresholds for substance signal checks
    (e.g. {'min_token_count': 5, 'max_link_density': 0.3})."""
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|---------------|--------|
| Monolithic `remove_boilerplate(full_text)` only | Section-granular `classify_sections()` + section removal | Phase 19 (this phase) | Junk sections are removed entirely rather than just having boilerplate substrings stripped from otherwise-kept text |
| `clean_document` forwards uncleaned `ParsedDoc` | `clean_document` forwards the cleaned `ParsedDoc` with sections filtered | Phase 17 (already done) — Phase 19 makes the filtering meaningful | Downstream consumers (chunk/tree/enrich) now actually benefit from cleaning |
| 4 static `BOILERPLATE_PATTERNS` | 9+ patterns covering 5 audit garbage categories | Phase 19 | Higher hit-rate on real audit garbage without touching the gate's frozen copy |

**Deprecated/outdated:** None — this phase extends existing infrastructure rather than replacing a
prior approach.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | The five CLEAN-05 pattern categories (nav, TOS, marketing CTAs, cookie consent, gov disclaimer) map cleanly onto line-anchored regexes the same way the existing 4 patterns do | Architecture Patterns, Pattern 2 | TOS/marketing blocks are often multi-line/multi-sentence, not single lines — a line-anchored pattern may under-match; the planner should budget time for iterating regex fixtures against real audit source text (ACC Clinical Guidelines, US Core IG, eCQI, FDA FAERS — the "worst sources" named in MILESTONE-CONTEXT.md) rather than assuming first-draft regexes hit the target |
| A2 | `PredicateResult` should be a `dataclass(frozen=True)` rather than `NamedTuple` | Standard Stack, Alternatives Considered | Low risk — explicitly Claude's Discretion per CONTEXT.md; either works, no behavioral difference |
| A3 | Domain-specific `thresholds` in `filters.yaml` should override (not compose with) framework-default thresholds per-key | Code Examples, DomainFilters | If threshold override semantics should instead be "domain adds new checks" rather than "domain overrides floor values," the merge logic differs — needs explicit decision at plan time |

**If this table is empty:** N/A — see entries above; all three should be confirmed or explicitly
decided during planning rather than left implicit in code.

## Open Questions

1. **Should `check_table_exemption()`'s current ineffectiveness (Pitfall 2) be raised as a
   discussion item before or during planning, or silently accepted as forward-looking infra?**
   - What we know: No builtin parser sets `is_table=True` currently.
   - What's unclear: Whether this gap is already tracked as tech debt elsewhere (not found in
     STATE.md's tech-debt list as of this research) or whether it should be added there now.
   - Recommendation: Build the predicate per D-11 as specified (it's still correct code), but add a
     line to STATE.md's tech-debt list referencing this gap, scoped to a future phase — do not expand
     Phase 19 to touch parser code, which is out of CLEAN-04/05/06/QUAL-01's stated scope.

2. **Exact regex fixtures for the 5 extended boilerplate categories are not yet validated against
   real audit source HTML/text.**
   - What we know: MILESTONE-CONTEXT.md names the worst-offending sources by name and percentage.
   - What's unclear: The literal boilerplate strings in those sources (this research did not fetch
     live HTML from ACC/US Core IG/eCQI/FDA FAERS).
   - Recommendation: The planner should include a task to pull 1-2 representative raw/parsed
     artifacts from those sources (if present in the dev DB/S3 from the original audit run) as fixture
     material for the new regex patterns, rather than inventing synthetic fixture text from category
     names alone.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| datatrove | STOP_WORDS/TERMINAL_PUNCTUATION constants | ✓ | 0.9.0 | — |
| tiktoken | token_count() (local encoder) | ✓ | already used in chunk.py | — |
| pydantic | DomainFilters model | ✓ | already used in domains/models.py | — |
| PyYAML | filters.yaml loading | ✓ | already used in loader.py | — |

**Missing dependencies with no fallback:** none
**Missing dependencies with fallback:** none

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.x + pytest-cov 5.x (both pinned in pyproject.toml) |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` — `xfail_strict = true`, `testpaths = ["tests"]` |
| Quick run command | `uv run pytest tests/unit/test_clean.py tests/unit/test_quality_predicates.py tests/unit/test_domain_loader.py -x -q` |
| Full suite command | `uv run pytest --cov=knowledge_lake --cov-branch` (branch coverage requires explicit `--cov-branch`; not currently in default `make test`, which runs `pytest --cov=knowledge_lake` without it) |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| CLEAN-04 | `classify_sections()` computes substance signals + is_boilerplate; `clean()` drops boilerplate sections | unit | `pytest tests/unit/test_clean.py -k classify -x` | ❌ Wave 0 (extend existing test_clean.py) |
| CLEAN-04 | Substance annotations persisted in `cleaned_document.metadata_["section_annotations"]` | unit | `pytest tests/unit/test_clean.py -k section_annotations -x` | ❌ Wave 0 |
| CLEAN-05 | Extended patterns cover 5 garbage categories; existing Phase-3 assertions still pass | unit | `pytest tests/unit/test_clean.py -x` (full file, regression-checks existing + new) | ✅ (existing file, extend) |
| CLEAN-06 | `DomainFilters` model validates `filters.yaml`; healthcare allowlist never drops clinical codes | unit | `pytest tests/unit/test_domain_loader.py -k filters -x` | ❌ Wave 0 |
| CLEAN-06 | `ICD-10 E11.9` / `Metformin 500 mg PO BID` chunk never dropped | unit (must-not-reject fixture, forward reference to MEAS-02) | `pytest tests/unit/test_clean.py -k allowlist -x` | ❌ Wave 0 |
| QUAL-01 | Predicates are pure, zero-I/O, independently importable | unit + import-boundary test | `pytest tests/unit/test_quality_predicates.py -x` plus an explicit test asserting `import knowledge_lake.pipeline.quality` does not transitively import `sqlalchemy`/`boto3`/`dagster` | ❌ Wave 0 |
| QUAL-01 | 100% branch coverage on `pipeline/quality/` | coverage gate | `pytest tests/unit/test_quality_predicates.py --cov=knowledge_lake.pipeline.quality --cov-branch --cov-report=term-missing --cov-fail-under=100` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `pytest tests/unit/test_clean.py tests/unit/test_quality_predicates.py -x -q`
- **Per wave merge:** `pytest tests/unit/ -x -q` (all unit tests — this phase touches shared `clean.py` consumed by process.py, quality_audit.py, dagster assets)
- **Phase gate:** `pytest --cov=knowledge_lake --cov-branch` full suite green, plus the explicit 100%-branch-coverage gate on `pipeline/quality/` specifically, before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/unit/test_quality_predicates.py` — new file, covers QUAL-01 (100% branch coverage target)
- [ ] `domains/healthcare/filters.yaml` — new fixture file, needed before `test_domain_loader.py` filters tests can run against the real healthcare pack
- [ ] A must-not-reject fixture set (short ICD-10/LOINC/RxNorm/dosage strings) — forward reference to
      Phase 20's MEAS-02, but Phase 19 needs at least a minimal version of these fixtures to prove
      CLEAN-06's acceptance criterion in this phase, since the full ~20-item MEAS-02 set is Phase 20's
      job
- [ ] Coverage gate: `--cov-branch` flag is not in the default `make test` — the planner should decide
      whether to add a `make test-quality-coverage` target or run coverage inline in a verification
      task

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-------------------|
| V2 Authentication | no | Phase has no auth surface |
| V3 Session Management | no | N/A |
| V4 Access Control | no | N/A |
| V5 Input Validation | yes | `filters.yaml` regex patterns loaded via `yaml.safe_load` (never `yaml.load`) — same guard `DomainLoader` already enforces (T-06-04). Domain name path-traversal guard (`_DOMAIN_NAME_RE`) already covers `filters.yaml`'s path since it's constructed the same way as the other 4 files (`domain_dir / "filters.yaml"`) — no new traversal surface. |
| V6 Cryptography | no | N/A |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|----------------------|
| ReDoS via a malicious/malformed regex in a domain pack's `filters.yaml` `boilerplate_patterns`/`normative_allowlists` | Denial of Service | Domain packs are trusted, repo-committed configuration (not user-uploaded at runtime) — same trust boundary as `sources.yaml`'s existing regex-bearing fields (`crawl_config`). No new mitigation needed beyond what already exists, but the planner should avoid unbounded-repetition regex constructs (`(a+)+`) in the new `BOILERPLATE_PATTERNS` entries as a matter of code hygiene, consistent with the existing patterns' simple line-anchored style. |
| YAML deserialization RCE via `filters.yaml` | Tampering | Already mitigated — `yaml.safe_load` exclusively, per `DomainLoader`'s existing T-06-04 convention. No new work needed; just follow the same call when adding the optional file load. |

## Sources

### Primary (HIGH confidence)
- Direct codebase reads: `src/knowledge_lake/pipeline/clean.py`, `domains/loader.py`,
  `domains/models.py`, `pipeline/process.py`, `pipeline/crawl.py`, `pipeline/chunk.py`,
  `pipeline/quality_audit.py`, `plugins/protocols.py`, `plugins/builtin/docling_parser.py`,
  `dagster_defs/assets.py`, `tests/unit/test_clean.py`, `tests/unit/test_domain_loader.py`,
  `tests/unit/test_process_crawled_clean.py`, `.planning/REQUIREMENTS.md`,
  `.planning/MILESTONE-CONTEXT.md`, `.planning/phases/17-*/17-CONTEXT.md`,
  `.planning/phases/18-*/18-CONTEXT.md`, `pyproject.toml`, `Makefile`, `.planning/config.json`
- Direct execution verification: `datatrove.pipeline.filters.gopher_quality_filter.STOP_WORDS`,
  `datatrove.utils.text.TERMINAL_PUNCTUATION`/`PUNCTUATION_SET` import successfully;
  `datatrove.utils.text.split_into_words()` raises `AttributeError` when invoked, confirmed via
  `.venv/bin/python -c "..."` in this environment on 2026-07-16

### Secondary (MEDIUM confidence)
- None — no external documentation lookups were needed; all findings were groundable directly in
  this repository's existing code and pinned dependency versions.

### Tertiary (LOW confidence)
- None.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — every recommended tool is already installed and used elsewhere in this exact codebase; no external research needed.
- Architecture: HIGH — grounded directly in `clean.py`'s existing `_clean_sections()` shape and Phase 17/18's already-shipped wiring.
- Pitfalls: HIGH — Pitfall 1 (DataTrove tokenizer crash) and Pitfall 2 (`is_table` never set) were both confirmed by direct code/execution inspection in this session, not inferred from training data.

**Research date:** 2026-07-16
**Valid until:** 30 days (stable, internal codebase — no external API/library churn risk since no new dependencies are introduced)
