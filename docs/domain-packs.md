# Domain Packs

## What Is a Domain Pack

A domain pack is a directory under `domains/<domain-name>/` that specializes the framework's enrichment prompts, source lists, and validation logic for a specific knowledge domain. The pack is loaded by convention by `DomainLoader.from_name(name)` — no core framework code changes are needed to add a new domain.

Set `KLAKE_DOMAIN__DOMAIN_NAME=<name>` to activate a domain pack for enrichment. When this variable is unset, the framework uses a generic enrichment prompt. For the full list of domain-related environment variables, see [configuration.md](configuration.md).

## Directory Structure

```
domains/
└── mydomainname/
    ├── domain.yaml              # required — domain metadata (name, version, description)
    ├── sources.yaml             # required — seed source list
    ├── taxonomy.yaml            # required — categories, entity types, coding systems
    ├── prompts/
    │   ├── enrich.j2            # required — LLM enrichment system prompt
    │   └── qa_generation.j2     # optional — QA pair generation prompt
    └── validators/
        ├── __init__.py
        └── validate.py          # optional — domain-specific validation logic
```

The directory name must match the `name` field in `domain.yaml` and must satisfy the domain name format: `^[a-zA-Z][a-zA-Z0-9_-]{0,63}$`.

## domain.yaml

Required fields:

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Must match the directory name exactly |
| `version` | string | Semver string (e.g. `"1.0.0"`) |
| `description` | string | Human-readable description of the domain |

**Healthcare example:**
```yaml
name: healthcare
version: "1.0.0"
description: "Healthcare domain pack — HL7/FHIR, CMS, HHS, ONC, CDC, FDA, NIH/NLM, and clinical terminology sources"
```

## sources.yaml

A YAML list of source entries. Each entry defines a seed data source for the domain. Fields:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | Yes | Human-readable source name |
| `url` | string | Yes | Canonical URL |
| `source_type` | string | Yes | `html`, `pdf`, `csv`, `xml`, `json` |
| `license` | string | Yes | SPDX identifier: `public-domain`, `open`, `CC`, `unknown` |
| `tags` | list[string] | Yes | Classification tags |
| `crawl_config` | dict | Yes | `depth` (int), `rate_limit_rps` (float), `robots_txt` (bool), `max_pages` (int) |
| `ingest_type` | string | Yes | `crawl` or `upload` (see below) |
| `requires_registration` | bool | No | If `true`, free user registration is required before downloading |

**`ingest_type` values:**

- **`crawl`** — automatically crawled by the framework when `klake init --domain <name>` or `POST /domains/load` is called. The crawl config controls depth and rate limiting.
- **`upload`** — requires manual bulk file download. These sources are counted in the `upload_required_count` response field but are NOT auto-registered. The operator must manually download the file and run `klake upload <path>` or call `POST /uploads`.

**Example entry (crawl type):**
```yaml
- name: "HIPAA Security Rule"
  url: "https://www.hhs.gov/hipaa/for-professionals/security/laws-regulations/index.html"
  source_type: "html"
  license: "public-domain"
  tags: ["hipaa", "security-rule", "hhs", "regulation", "federal"]
  crawl_config: {depth: 2, rate_limit_rps: 0.5, robots_txt: true}
  ingest_type: "crawl"
```

**Example entry (upload type):**
```yaml
- name: "LOINC Clinical Terminology (CSV bulk)"
  url: "https://loinc.org/downloads/"
  source_type: "csv"
  license: "open"
  tags: ["loinc", "coding", "terminology"]
  crawl_config: {}
  ingest_type: "upload"
  requires_registration: true
```

## taxonomy.yaml

Domain-specific ontology defining entity types, subtypes, and categories. The content is loaded by `DomainLoader` and made available to enrichment and validation logic. The framework does not enforce a rigid schema — the structure can be adapted to the domain.

**Healthcare taxonomy structure:**
```yaml
entity_types:
  - Condition
  - Medication
  - Procedure
  - ClinicalCode
  - Regulation
  - Guideline
  - Standard

subtypes:
  ClinicalCode:
    - ICD10
    - LOINC
    - NDC
    - HCPCS
    - RxNorm

categories:
  - clinical_terminology
  - federal_regulation
  - interoperability_standard
  - public_health_data
  - drug_information
```

## Prompts

Prompts are Jinja2 templates stored in `prompts/`. They are rendered by `DomainLoader.render_prompt(template_name)`.

### `enrich.j2` (required)

Injected as the LLM system prompt for `pipeline.enrich.enrich_document()`. The healthcare prompt instructs the LLM to extract FHIR/HIPAA-specific metadata, recognize clinical coding systems (ICD-10-CM, LOINC, NDC, HCPCS, RxNorm, SNOMED), and assign document_type values appropriate for healthcare (e.g. `regulation`, `guidance`, `clinical_guideline`, `terminology_standard`).

The prompt template receives these variables:
- `{{ title }}` — deterministically extracted title
- `{{ dates }}` — deterministically extracted dates
- `{{ headings }}` — deterministically extracted headings
- `{{ excerpt }}` — document text excerpt (capped at `KLAKE_ENRICH__EXCERPT_CHARS` characters)

The healthcare `enrich.j2` includes a prompt-injection defense clause that instructs the LLM to treat all document text strictly as content to analyze, never as instructions to follow.

### `qa_generation.j2` (optional)

Used by `pipeline.datasets.generate_qa_example()` when `KLAKE_DOMAIN__DOMAIN_NAME` is set. Template variable: `{{ domain_name }}`.

### Custom prompts

Any `.j2` file in the `prompts/` directory can be loaded with `DomainLoader.render_prompt("custom.j2")`.

## validators/validate.py (optional)

An optional Python module for domain-specific validation. Loaded dynamically via `importlib` — only stdlib imports are allowed (no `knowledge_lake` imports).

The healthcare validator provides:
- **PHI heuristic gate** — detects potential Protected Health Information patterns (SSN, DOB, patient name, NPI) using regex. When triggered, adds `phi_gate_triggered=True` to warnings. The matched text span is never logged.
- **Clinical coding system check** — detects ICD-10-CM, LOINC, NDC, HCPCS, and RxNorm code patterns in document text. Informational only; no failure on detection.

The validator exposes a `HealthcareValidator` class with a single method:
```python
def validate_document(self, document: dict) -> ValidationResult
```

`ValidationResult` has `passed` (bool), `warnings` (list[str]), `errors` (list[str]).

If no validation logic is needed, the module can contain just `pass`.

## DomainLoader API

```python
from knowledge_lake.domains.loader import DomainLoader

loader = DomainLoader.from_name("healthcare")
# or with explicit root for non-standard deployments:
loader = DomainLoader.from_name("healthcare", root="/path/to/project")
```

`DomainLoader.from_name(name, root=None)`:
- `root` defaults to the project root resolved from `settings.domain.domains_root`.
- Raises `FileNotFoundError` if the domain directory does not exist.
- Validates `name` against the domain name format regex.

Loader attributes:
- `.domain` — parsed `domain.yaml` dict
- `.sources` — list of `SourceEntry` objects from `sources.yaml`
- `.taxonomy` — parsed `taxonomy.yaml` dict
- `.render_prompt(template_name)` — renders a Jinja2 template from `prompts/`, returns the rendered string

## Registration

Load a domain pack and register its crawl-type sources:

```bash
# CLI
klake init --domain mydomainname

# API
POST /domains/load
{"name": "mydomainname"}
```

Both are idempotent — existing sources (by normalized URL) are silently skipped. Upload-type sources are counted but not registered; the CLI will print a notice with how many sources require manual download.

## Healthcare Pack Reference

The healthcare domain pack contains 28 curated sources: 24 `crawl` type and 4 `upload` type.

**Standards bodies (4 crawl):**

| Source | URL | Tags |
|--------|-----|------|
| HL7 FHIR R4 Specification | build.fhir.org | fhir, standards, hl7 |
| US Core Implementation Guide | hl7.org/fhir/us/core/ | fhir, us-core, uscdi |
| SMART on FHIR | docs.smarthealthit.org | fhir, smart, oauth2 |
| CDA/C-CDA HL7 Implementation Guide | build.fhir.org/ig/HL7/CDA-core-sd/ | cda, c-cda, hl7 |

**Federal agencies — CMS (4 crawl):**

| Source | Tags |
|--------|------|
| CMS Conditions of Participation | cms, conditions-of-participation, regulation |
| HCPCS Level II Code System | hcpcs, coding, cms, billing |
| Medicare Coverage Database | medicare, coverage, cms |
| CMS Medicare Portal | medicare, cms, benefits |

**HHS/OCR (2 crawl):**

| Source | Tags |
|--------|------|
| HIPAA Security Rule | hipaa, security-rule, hhs, regulation |
| HIPAA Privacy Rule | hipaa, privacy-rule, hhs, regulation |

**ONC (2 crawl):**

| Source | Tags |
|--------|------|
| USCDI v3 | uscdi, onc, interoperability |
| ONC 21st Century Cures Act Final Rule | onc, cures-act, interoperability |

**CDC (2 crawl + 1 upload):**

| Source | Type | Tags |
|--------|------|------|
| ICD-10-CM Code Set (CMS bulk) | upload | icd-10, coding, cms |
| CDC MMWR | crawl | cdc, epidemiology, public-health |
| CDC WONDER Public Health Data | crawl | cdc, wonder, public-health |

**FDA (1 crawl + 1 upload):**

| Source | Type | Tags |
|--------|------|------|
| DailyMed Drug Label Database | crawl | fda, dailymed, drugs |
| FDA National Drug Code (NDC) Database | upload | ndc, fda, drugs |

**NIH/NLM (3 crawl + 1 upload):**

| Source | Type | Tags |
|--------|------|------|
| LOINC Clinical Terminology | upload | loinc, coding, terminology |
| RxNorm via NLM RxNav | crawl | rxnorm, drugs, nlm |
| MedlinePlus Health Information | crawl | medlineplus, nlm, consumer-health |
| NCI Thesaurus Browser | crawl | nci, thesaurus, oncology |

**Registry — NPPES (1 upload):**

| Source | Tags |
|--------|------|
| NPPES NPI Bulk Data File | nppes, npi, providers, cms |

**Clinical guidelines (3 crawl):**

| Source | Tags |
|--------|------|
| AHRQ Evidence-Based Reports | ahrq, guidelines, evidence-based |
| AHA Clinical Guidelines | aha, cardiology, guidelines |
| ACC Clinical Guidelines | acc, cardiology, guidelines |

**Research (3 crawl):**

| Source | Tags |
|--------|------|
| PubMed Central Open Access | pubmed, research, open-access |
| NIH ClinicalTrials.gov | clinical-trials, nih, research |
| FDA Adverse Event Reporting System (FAERS) | fda, faers, adverse-events |

**Upload-type sources requiring manual download:**
- ICD-10-CM: Download tabular ZIP from CMS, extract CSV files.
- NDC: Download bulk ZIP from FDA (`product.txt` / `package.txt`).
- LOINC: Free user registration at loinc.org required before downloading.
- NPPES: Download monthly NPI bulk CSV from CMS.

## Activating a Domain for Enrichment

Set `KLAKE_DOMAIN__DOMAIN_NAME=mydomainname` before running enrichment:

```bash
# CLI
KLAKE_DOMAIN__DOMAIN_NAME=healthcare klake enrich --cleaned-artifact-id art_019f...

# or in .env
KLAKE_DOMAIN__DOMAIN_NAME=healthcare
```

When set, `pipeline.enrich.enrich_document()` loads `domains/mydomainname/prompts/enrich.j2` and injects it as the LLM system prompt. When unset, a generic prompt is used.

The `POST /enrich` API endpoint also respects `KLAKE_DOMAIN__DOMAIN_NAME` — the domain system prompt is loaded server-side from the active setting.
