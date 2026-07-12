---
gsd_summary_version: 1.0
quick_id: 260712-nyq
slug: add-klake-domain-new-name-scaffold-comma
date: 2026-07-12
branch: feat/klake-domain-new
status: complete
---

# Summary: `klake domain new <name>` scaffold command

## Outcome

Authoring a domain pack is now a first-class command instead of copy-paste.
`klake domain new <name>` generates a valid, immediately loadable pack skeleton,
and the loader no longer hardcodes a single domain's validator class.

## Changes

- **`refactor(domains)` (48058ef)** — `DomainLoader` resolves the validator class
  generically (the module-defined `*Validator` class exposing `validate_document()`)
  instead of hardcoding `mod.HealthcareValidator()`. Backward compatible; healthcare
  still resolves.
- **`feat(cli)` (0e5917c)** — new `knowledge_lake/domains/scaffold.py` (`scaffold_domain()`),
  a `domain` Typer sub-app with a `new` command, and `tests/unit/test_domain_scaffold.py`
  (7 tests incl. a round-trip `DomainLoader` load of a scaffolded non-healthcare pack).
  `domains/README.md` now leads with the command.
- **`docs` (071ace2)** — trimmed the stale maintainer contact reminders in
  `CODE_OF_CONDUCT.md` and `SECURITY.md`.

## Design decisions

- Default scaffold target is `domains/<name>` (loadable via `klake init --domain <name>`);
  `--root` overrides (e.g. `domains/local` for a git-ignored scratch pack).
- Validator class is named after the domain (`FoodScienceValidator`), enabled by the
  loader generalization.
- Prompt templates use sentinel placeholders so Jinja `{{ }}` / JSON `{ }` braces survive.

## Verification

- `uv run klake domain new demo-pack --root <tmp>` → pack created and loads via
  `DomainLoader` (validator `DemoPackValidator`, prompts render).
- `uv run ruff check src/` → clean.
- `uv run pytest tests/unit -m "not browser"` → **529 passed** (+7 new), 1 xfailed, 39 xpassed.

## Out of scope

- The `domains/local/` load path (`from_name` hardcodes the `domains/` segment) — pre-existing.
