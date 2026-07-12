---
gsd_plan_version: 1.0
quick_id: 260712-nyq
slug: add-klake-domain-new-name-scaffold-comma
date: 2026-07-12
branch: feat/klake-domain-new
status: in-progress
---

# Quick Task: `klake domain new <name>` scaffold command

## Goal

Make authoring a new domain pack a first-class workflow (`klake domain new <name>`)
that generates a valid, loadable pack skeleton — replacing the copy-paste-an-existing-pack
approach. Also trim the now-stale maintainer contact reminders and refresh the
domains README to reference the new command.

## Context / constraints

- `DomainLoader.__init__` currently hardcodes `mod.HealthcareValidator()` (loader.py:125),
  so any pack must name its validator `HealthcareValidator` to load. This breaks the
  domain-agnostic contract and would force scaffolded packs to use a nonsensical class
  name. Must generalize the validator lookup first.
- `DomainLoader.from_name(name, root)` resolves `root/"domains"/name`, so `klake init
  --domain <name>` loads `domains/<name>`. The scaffold therefore defaults to `domains/`.
- Pack files required by the loader: `domain.yaml`, `sources.yaml`, `taxonomy.yaml`,
  `prompts/` (Jinja templates), `validators/validate.py`.
- Name guard: `^[a-zA-Z][a-zA-Z0-9_-]{0,63}$` (reuse existing path-traversal guard).
- CLI delegates to a single function (D-03 "one function, many callers").

## Tasks

1. **Generalize validator resolution** in `domains/loader.py`: select the module-defined
   class whose name ends with `Validator` and exposes `validate_document()`, instead of
   hardcoding `HealthcareValidator`. Backward compatible (healthcare still resolves).
2. **Add `scaffold_domain()`** in new `domains/scaffold.py`: validate name, create the
   pack tree, write templated files (domain-neutral prompts + a `<Pascal>Validator`).
3. **Wire CLI**: add a `domain` Typer sub-app with a `new` command delegating to
   `scaffold_domain()`, printing next-steps guidance.
4. **Trim stale maintainer notes** in `CODE_OF_CONDUCT.md` (obsolete) and `SECURITY.md`
   (keep only the "enable private vulnerability reporting" action).
5. **Update `domains/README.md`** "Authoring a new pack" to lead with `klake domain new`.
6. **Tests** (`tests/unit/test_domain_scaffold.py`): files created, name validation,
   force/overwrite behavior, and a round-trip load of the scaffolded pack via `DomainLoader`.

## Verification

- `uv run ruff check src/` clean.
- `uv run pytest tests/unit/test_domain_scaffold.py tests/unit/test_domain_loader.py -q` green.
- `uv run klake domain new demo-pack --root /tmp/klake-scaffold` produces a loadable pack.

## Out of scope

- Fixing the `domains/local/` load path (from_name hardcodes the `domains/` segment) —
  pre-existing, tracked separately.
