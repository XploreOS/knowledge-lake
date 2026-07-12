# Domain Packs

A **domain pack** is a self-contained bundle of configuration that teaches
Knowledge Lake about a specific subject area: where to find sources, how to
classify content, and how to enrich it. Packs are pure configuration — the
framework code stays domain-agnostic and loads packs at runtime.

## What's in this directory

```
domains/
├── README.md              # this file
├── healthcare/            # reference pack — tracked, ships with the framework
│   ├── domain.yaml        #   pack metadata (name, description, defaults)
│   ├── sources.yaml       #   seed sources to register (crawl + upload types)
│   ├── taxonomy.yaml      #   domain taxonomy / classification labels
│   ├── prompts/           #   Jinja templates for LLM enrichment & QA
│   │   ├── enrich.j2
│   │   └── qa_generation.j2
│   └── validators/        #   domain-specific validation logic
│       └── validate.py
└── local/                 # your own / experimental packs — git-ignored
    └── .gitkeep
```

Every pack **must** contain `domain.yaml`, `sources.yaml`, `taxonomy.yaml`, a
`prompts/` directory, and `validators/validate.py`. The loader
(`knowledge_lake.domains.loader.DomainLoader`) raises `FileNotFoundError` if any
of these are missing.

## Tracked reference packs vs. your local packs

| Location | Tracked in git? | Purpose |
|----------|-----------------|---------|
| `domains/<name>/` | ✅ Yes | Curated reference packs that ship with the framework (e.g. `healthcare`). |
| `domains/local/<name>/` | ❌ No (git-ignored) | Your own or experimental packs. Never committed to this repo. |

You have two ways to work with your own packs:

1. **In-repo scratch space** — drop a pack under `domains/local/<name>/` and load
   it by pointing the domains root at that directory:

   ```bash
   export KLAKE_DOMAINS_ROOT=domains/local
   uv run klake init --domain <name>
   ```

2. **Fully external** — keep your packs anywhere on disk and set
   `KLAKE_DOMAINS_ROOT` to that path. This keeps proprietary packs entirely
   outside the framework repository.

## Authoring a new pack

There is no auto-generated data here — you write a pack by hand. The quickest
start is to copy the reference pack and adapt it:

```bash
cp -r domains/healthcare domains/local/my-domain
# then edit domain.yaml, sources.yaml, taxonomy.yaml, prompts/, validators/
```

Once the files are in place, register the pack's seed sources:

```bash
# reference pack (default root = domains/)
uv run klake init --domain healthcare

# a local pack under domains/local/
KLAKE_DOMAINS_ROOT=domains/local uv run klake init --domain my-domain
```

`klake init` **reads** an existing pack and bulk-registers its crawl-type
sources into the registry. Upload-type sources are reported but must be
downloaded and uploaded manually.

## Guidelines for reference packs

If you're contributing a pack intended to ship with the framework (tracked under
`domains/<name>/` rather than `domains/local/`):

- Respect source licenses and `robots.txt` — only include sources that permit
  crawling. Record license/attribution in `sources.yaml`.
- Do not commit private, paywalled, or restricted sources.
- Keep prompts provider-agnostic (all model calls go through LiteLLM with
  task-based aliases, never hardcoded model IDs).
- Open an issue or discussion first — see [CONTRIBUTING.md](../CONTRIBUTING.md).
