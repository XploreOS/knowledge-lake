# Phase 19: Section Classifier + Patterns - Pattern Map

**Mapped:** 2026-07-16
**Files analyzed:** 9 (3 modified, 6 new)
**Analogs found:** 9 / 9

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|--------------------|------|-----------|-----------------|----------------|
| `src/knowledge_lake/pipeline/clean.py` (modify: add `classify_sections()`, evolve `_clean_sections()`/`clean()`) | service (pipeline stage) | transform (CRUD-adjacent: reads parsed artifact, writes cleaned artifact) | itself — `_clean_sections()` at line 172, `remove_boilerplate()` at line 83 | exact (extending existing function in place) |
| `src/knowledge_lake/pipeline/quality/__init__.py` (new) | utility (package init) | transform | `src/knowledge_lake/domains/models.py` (plain-model package convention) — no direct barrel-file analog exists; closest is how `plugins/protocols.py` re-exports dataclasses | role-match |
| `src/knowledge_lake/pipeline/quality/predicates.py` (new) | utility (pure predicate functions) | transform | `src/knowledge_lake/pipeline/chunk.py` — `token_count()` (line 59), `_split_sentences()` (line 68) — pure, dependency-light helper style | role-match |
| `src/knowledge_lake/pipeline/quality/constants.py` (new) | config/utility | transform | `src/knowledge_lake/pipeline/crawl.py` — `_GATE_BOILERPLATE_PATTERNS` (line 111) module-scope frozen-constant + local-encoder idiom; `chunk.py`'s module-level `_encoder = _tiktoken.get_encoding(...)` (line 53) | exact (duplication-for-isolation idiom is the direct precedent) |
| `src/knowledge_lake/domains/models.py` (modify: add `DomainFilters`) | model | CRUD (validation) | `DomainManifest`, `SourceEntry` in same file (lines 17-64) | exact |
| `src/knowledge_lake/domains/loader.py` (modify: add optional `filters.yaml` load) | service (loader) | file-I/O | itself — steps 1-3 (`domain.yaml`/`sources.yaml`/`taxonomy.yaml` loading, lines 69-90) | exact (extending existing method, but must diverge to "optional" not "required-or-raise") |
| `domains/healthcare/filters.yaml` (new) | config | file-I/O | `domains/healthcare/sources.yaml`, `domains/healthcare/taxonomy.yaml` (sibling YAML config files) | role-match |
| `tests/unit/test_clean.py` (modify: extend) | test | request-response (unit) | itself — existing boilerplate/section tests | exact |
| `tests/unit/test_quality_predicates.py` (new) | test | request-response (unit) | `tests/unit/test_domain_loader.py` (import-guard pattern for not-yet-existing module, lines 1-16) | role-match |
| `tests/unit/test_domain_loader.py` (modify: extend for filters.yaml) | test | request-response (unit) | itself | exact |

## Pattern Assignments

### `src/knowledge_lake/pipeline/clean.py` — `classify_sections()` + `_clean_sections()` evolution (service, transform)

**Analog:** itself, `_clean_sections()` at `src/knowledge_lake/pipeline/clean.py:172-215`, and `remove_boilerplate()` at lines 83-92.

**Existing helper to extend, not replace** (lines 172-215):
```python
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
Phase 19 must ADD a second rejection reason (e.g. `"classified_as_boilerplate"`) to the SAME
`rejection_reasons` dict shape and ACTUALLY drop sections where `is_boilerplate=True` from
`cleaned_sections` (per D-02) — this is the one behavioral change from "annotate all, drop none"
to "annotate all, drop boilerplate ones." The dict-accumulation style (`rejection_reasons[reason] =
rejection_reasons.get(reason, 0) + 1`) must be reused verbatim for the new reason so
`quality_audit.py` and `test_quality_audit.py` (which already depend on this dict shape) keep working.

**Boilerplate patterns to extend additively** (lines 48-62):
```python
BOILERPLATE_PATTERNS: list[re.Pattern] = [
    # Page headers/footers: "Page 1 of 5" or a bare page number on its own line
    re.compile(r"^(?:Page \d+ of \d+|\d+)\s*$", re.MULTILINE),
    # Cookie/privacy banners
    re.compile(
        r"(?i)(?:this site uses cookies|accept all cookies|cookie policy)[^\n]*$",
        re.MULTILINE,
    ),
    # Navigation elements from HTML crawls (entire line only)
    re.compile(
        r"(?im)^(?:home|about us|contact|sitemap|skip to (?:main )?content)\s*$",
    ),
    # Repeated copyright/disclaimer lines
    re.compile(r"(?i)^(?:disclaimer|copyright \d{4})[^\n]*$", re.MULTILINE),
]
```
CLEAN-05 requires `.append()`-style additive extension — never reorder or restructure into a dict
(Pitfall 5). New entries must be `re.compile(...)` objects added to the SAME flat list, covering:
navigation menus (extend/add), terms-of-service blocks, enrollment/marketing CTAs, cookie consent
(verify against real fixtures — may already be adequately covered), government disclaimer boilerplate.

**Imports pattern** (lines 22-38) — new imports needed for `classify_sections()`:
```python
from __future__ import annotations

import hashlib
import re
from dataclasses import replace

import structlog
from datasketch import MinHash, MinHashLSH

from knowledge_lake.config.settings import Settings, get_settings
from knowledge_lake.pipeline.utils import uri_to_key as _uri_to_key
from knowledge_lake.plugins.protocols import ParsedDoc, Section
from knowledge_lake.registry import repo as registry_repo
from knowledge_lake.registry.db import get_session
from knowledge_lake.storage.s3 import _UNCLASSIFIED_DOMAIN, StorageBackend
```
Add: `from knowledge_lake.pipeline.quality import run_predicates, PredicateResult` and
`from knowledge_lake.domains.models import DomainFilters` (only if `clean()`/`classify_sections()`
takes a `domain_filters` param — needed per D-03/D-08).

**Section-level classification signature to add** (per D-01, RESEARCH.md Pattern 1 — grounded in
existing `_clean_sections` shape):
```python
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
**Critical ordering (Pitfall 3):** allowlist check MUST be an unconditional override applied last —
`is_boilerplate = (not allowlisted) and (matches_pattern or fails_thresholds)`. A short clinical
code (e.g. `"ICD-10 E11.9"`) will fail every substance threshold; the allowlist must short-circuit
that, not merely tie-break it.

**Docstring/conservation-invariant style to reuse** (lines 221-338, `clean()`): the QUAL-05
conservation invariant check —
```python
if sections_rejected + sections_kept != sections_considered:
    log.error(
        "clean.conservation_invariant_violated",
        parsed_artifact_id=parsed_artifact_id,
        sections_considered=sections_considered,
        sections_kept=sections_kept,
        sections_rejected=sections_rejected,
    )
    raise RuntimeError(
        f"clean: conservation invariant violated for {parsed_artifact_id!r}: "
        f"{sections_rejected} + {sections_kept} != {sections_considered}"
    )
```
must continue to hold after `classify_sections()` is wired in — `sections_kept` now reflects
BOTH old rejection reasons (empty after boilerplate strip) AND the new `is_boilerplate` drop, so
`sections_rejected` must sum both paths without double-counting a section that hits both.

**Metadata storage pattern** (per D-04) — reuse the exact `metadata={...}` dict-building style at
`registry_repo.create_cleaned_artifact(... metadata={...})` (lines 485-497):
```python
metadata={
    "language": language,
    "dedup_status": dedup_status,
    "minhash_num_perm": s.clean.minhash_num_perm,
    "sections_considered": sections_considered,
    "sections_kept": sections_kept,
    "sections_rejected": sections_rejected,
    "rejection_reasons": rejection_reasons,
},
```
Add a new key `"section_annotations"` to this same dict (list of per-section dicts: index,
substance signals, keep/reject decision + reason) — no new artifact type, per D-04.

---

### `src/knowledge_lake/pipeline/quality/` package (new) — pure predicates (utility, transform)

**Analog:** `src/knowledge_lake/pipeline/chunk.py` for the local-encoder/pure-function style;
`src/knowledge_lake/pipeline/crawl.py` for the duplication-for-isolation idiom.

**Module-scope encoder duplication pattern** (mirrors `chunk.py:52-65`, applied per RESEARCH.md
Pattern 3 / D-12 — do NOT import `pipeline.chunk` since it pulls in `registry.db`/`storage.s3`):
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

**DataTrove constants safe to import directly** (verified working per RESEARCH.md; do NOT call
`split_into_words()` — raises `AttributeError` in this environment, Pitfall 1):
```python
from datatrove.pipeline.filters.gopher_quality_filter import STOP_WORDS
from datatrove.utils.text import TERMINAL_PUNCTUATION, PUNCTUATION_SET
```
Use `text.split()` or `re.findall(r"\w+", text)` for word tokenization instead of DataTrove's
tokenizer path.

**PredicateResult style** — follow `ValidationResult` in `domains/models.py:76-95` (closest existing
precedent for a `dataclass` result-carrying type in this codebase):
```python
@dataclass
class ValidationResult:
    passed: bool
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
```
Recommended (Claude's Discretion, D-11): `@dataclass(frozen=True)` with `passed: bool` and
`reason: str` fields for `PredicateResult`.

**Zero-I/O import boundary** — `pipeline/quality/` must NEVER import `pipeline.chunk`, `pipeline.clean`,
`registry.db`, `registry.repo`, `storage.s3`, `config.settings`, or `dagster`. Test this boundary
explicitly (see test section below).

---

### `src/knowledge_lake/domains/models.py` — `DomainFilters` model (model, CRUD/validation)

**Analog:** `DomainManifest` (lines 53-64) and `SourceEntry` (lines 17-51) in the same file.

**Existing sibling model style to copy exactly:**
```python
class DomainManifest(BaseModel):
    """Top-level metadata from domain.yaml (DOMAIN-01 schema)."""

    name: str
    """Domain pack name (e.g. 'healthcare'). Must match the directory name."""

    version: str
    """Semantic version string (e.g. '1.0.0')."""

    description: str
    """Human-readable description of this domain pack."""
```
```python
class SourceEntry(BaseModel):
    name: str
    url: str
    source_type: str
    license: str
    tags: list[str] = []
    crawl_config: dict = {}
```
`DomainFilters` should follow this same plain-`BaseModel`, field-with-docstring-comment convention
(no `BaseSettings`, all fields constructed from a pre-loaded YAML dict):
```python
class DomainFilters(BaseModel):
    """Optional domain-pack filter configuration from filters.yaml (CLEAN-06)."""

    boilerplate_patterns: list[str] = []
    normative_allowlists: list[str] = []
    thresholds: dict[str, float] = {}
```

---

### `src/knowledge_lake/domains/loader.py` — optional `filters.yaml` load (service, file-I/O)

**Analog:** itself — steps 1-3 (`domain.yaml`, `sources.yaml`, `taxonomy.yaml` loading, lines 69-90).

**Existing required-file pattern (do NOT copy the "raise on missing" part for this one file):**
```python
domain_yaml_path = domain_dir / "domain.yaml"
if not domain_yaml_path.exists():
    raise FileNotFoundError(f"domain.yaml not found in domain pack: {domain_dir}")
self.manifest: DomainManifest = DomainManifest.model_validate(
    yaml.safe_load(domain_yaml_path.read_text(encoding="utf-8"))
)
```
**Required divergence (Pitfall 4):** `filters.yaml` must use an explicit optional-load branch,
never `FileNotFoundError`:
```python
filters_yaml_path = domain_dir / "filters.yaml"
if filters_yaml_path.exists():
    self.filters: DomainFilters | None = DomainFilters.model_validate(
        yaml.safe_load(filters_yaml_path.read_text(encoding="utf-8"))
    )
else:
    self.filters = None
```
Import addition: `from knowledge_lake.domains.models import DomainFilters` alongside the existing
`from knowledge_lake.domains.models import DomainManifest, SourceEntry` (line 29). Security:
`yaml.safe_load` exclusively (T-06-04) — same as all three other loads in this file; the
`_DOMAIN_NAME_RE` path-traversal guard (line 33) already covers `filters.yaml`'s path since it's
built the same way (`domain_dir / "filters.yaml"`) — no new guard code needed.

---

### `domains/healthcare/filters.yaml` (new, config, file-I/O)

**Analog:** `domains/healthcare/sources.yaml`, `domains/healthcare/taxonomy.yaml` — sibling YAML
files in the same directory, same `yaml.safe_load`-consumed convention.

Per D-08, contents should be a flat YAML dict matching `DomainFilters` fields:
```yaml
normative_allowlists:
  - "ICD-10"
  - "LOINC"
  - "RxNorm"
  - "§\\d+\\.\\d+"
  - "\\d+\\s*mg"
  - "PO\\s+BID"
boilerplate_patterns: []
thresholds: {}
```

---

### Tests

**`tests/unit/test_domain_loader.py` — extend** (analog: itself, lines 1-40):
```python
from __future__ import annotations
from pathlib import Path

try:
    from knowledge_lake.domains.loader import DomainLoader
except ImportError:
    DomainLoader = None  # type: ignore[assignment, misc]

DOMAINS_ROOT = Path(__file__).parent.parent.parent
HC_DIR = DOMAINS_ROOT / "domains" / "healthcare"

def test_domain_loader_from_name_returns_loader() -> None:
    assert DomainLoader is not None, "DomainLoader not yet implemented"
    loader = DomainLoader.from_name("healthcare", root=DOMAINS_ROOT)
    assert loader is not None
```
Add: a test loading `domains/aviation` (which has NO `filters.yaml`) asserting `loader.filters is None`
and that no exception is raised (Pitfall 4 regression guard) — this is the single most important
new test in this file for CLEAN-06.

**`tests/unit/test_quality_predicates.py` — new file.** Use the same try/except import-guard idiom
shown above for a not-yet-existing module, plus an explicit import-boundary test:
```python
def test_quality_module_has_no_io_dependencies() -> None:
    """pipeline.quality must never transitively import sqlalchemy/boto3/dagster."""
    import sys
    import knowledge_lake.pipeline.quality  # noqa: F401
    forbidden = {"sqlalchemy", "boto3", "dagster"}
    loaded = {m.split(".")[0] for m in sys.modules}
    assert not (forbidden & loaded)
```

## Shared Patterns

### Additive-only mutation of module-level constant lists (CLEAN-05, GATE-01 precedent)
**Source:** `src/knowledge_lake/pipeline/crawl.py:105-125` (`_GATE_BOILERPLATE_PATTERNS`, frozen
snapshot), `src/knowledge_lake/pipeline/clean.py:48-62` (`BOILERPLATE_PATTERNS`, live list)
**Apply to:** `clean.py`'s `BOILERPLATE_PATTERNS` extension. Never touch `crawl.py`'s frozen copy
(D-06) — this is the entire point of Phase 18's decoupling. Always `.append()`/list-concat, never
restructure into a dict or change element type.

### Duplication-for-isolation idiom (dependency boundary enforcement)
**Source:** `src/knowledge_lake/pipeline/crawl.py:105-110` (comment explaining the frozen-copy
rationale), `src/knowledge_lake/pipeline/chunk.py:52-65` (module-level `_encoder`/`token_count()`)
**Apply to:** `pipeline/quality/constants.py`'s local `token_count()` — must duplicate the
6-line helper rather than `from knowledge_lake.pipeline.chunk import token_count`, with an inline
comment citing QUAL-01's zero-I/O constraint (mirrors the exact comment style already in `crawl.py`).

### yaml.safe_load exclusively (security, T-06-04)
**Source:** `src/knowledge_lake/domains/loader.py` lines 74, 81, 90 — every YAML load in this file
uses `yaml.safe_load(path.read_text(encoding="utf-8"))`, never `yaml.load`.
**Apply to:** The new optional `filters.yaml` load in `loader.py`, and any test fixture loading.

### Pydantic BaseModel with inline docstring-comment fields (domain pack config)
**Source:** `src/knowledge_lake/domains/models.py` — `DomainManifest`, `SourceEntry` (plain
`BaseModel`, not `BaseSettings`; every field followed by a `"""docstring"""` comment)
**Apply to:** `DomainFilters` model — same file, same style, same "constructed from pre-loaded
YAML dict" convention (no env var binding).

### structlog structured logging with dotted event names
**Source:** `src/knowledge_lake/pipeline/clean.py` — `log.info("clean.start", ...)`,
`log.error("clean.conservation_invariant_violated", ...)`, `log.warning("clean.zero_sections", ...)`
**Apply to:** Any new logging in `classify_sections()` (e.g. `log.info("clean.section_classified", ...)`)
— follow the `"<module>.<event>"` dotted naming convention with structured kwargs, never f-string
messages.

### dataclasses.replace for non-mutating Section transforms
**Source:** `src/knowledge_lake/pipeline/clean.py:206` — `cleaned_sections.append(replace(section, text=cleaned_section_text))`
**Apply to:** Any new code building modified `Section` copies inside `classify_sections()` or the
updated `_clean_sections()` — never mutate the caller's original `Section` objects (Phase 17
mutation-aliasing hazard).

## No Analog Found

None — all files to be created/modified have a strong existing analog in the codebase (either a
sibling file in the same directory, or the file itself being extended in place).

## Metadata

**Analog search scope:** `src/knowledge_lake/pipeline/` (clean.py, chunk.py, crawl.py, process.py,
quality_audit.py), `src/knowledge_lake/domains/` (loader.py, models.py), `domains/healthcare/`,
`domains/aviation/`, `tests/unit/` (test_clean.py, test_domain_loader.py, test_quality_audit.py)
**Files scanned:** 12
**Pattern extraction date:** 2026-07-16
