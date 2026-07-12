# Contributing to Knowledge Lake

Thanks for your interest in contributing! Knowledge Lake is a domain-agnostic
framework for turning domain resources into AI-ready assets with full lineage.
This guide explains how to set up your environment, the conventions we follow,
and how to get changes merged.

By participating in this project you agree to abide by our
[Code of Conduct](CODE_OF_CONDUCT.md).

## Table of Contents

- [Ways to Contribute](#ways-to-contribute)
- [Development Environment](#development-environment)
- [Project Conventions](#project-conventions)
- [Running Checks and Tests](#running-checks-and-tests)
- [Commit and PR Guidelines](#commit-and-pr-guidelines)
- [Extending the Framework](#extending-the-framework)
- [Reporting Bugs and Security Issues](#reporting-bugs-and-security-issues)

## Ways to Contribute

- **Report bugs** and **request features** via [GitHub Issues](../../issues)
  using the provided templates.
- **Improve documentation** in `README.md` and `docs/`.
- **Add or refine domain packs** under `domains/`.
- **Write plugins** (parsers, embedders, vector stores, crawlers, discovery).
- **Fix bugs** and **add tests**.

If you're planning a large change, please open an issue first to discuss the
approach before investing significant time.

## Development Environment

### Prerequisites

- **Python 3.12+**
- **[uv](https://docs.astral.sh/uv/getting-started/installation/)** — package &
  environment manager
- **Docker + Docker Compose** — runs Postgres, MinIO, Qdrant, LiteLLM, SearXNG

### Setup

```bash
# 1. Fork and clone
git clone https://github.com/<your-username>/knowledge-lake.git
cd knowledge-lake

# 2. Install all dependencies (runtime + dev)
make dev-install        # == uv sync --extra dev

# 3. Configure environment
cp .env.example .env
# edit .env — at minimum set KLAKE_STORAGE__ACCESS_KEY_ID and
# KLAKE_STORAGE__SECRET_ACCESS_KEY (these have no defaults by design)

# 4. Bring up the local stack
make up                 # == docker compose up -d

# 5. Smoke test
uv run klake demo
```

Never commit real secrets. `.env`, `*.pem`, and `*.key` are git-ignored.

## Project Conventions

These framework invariants are non-negotiable — PRs that break them will be
asked to change:

- **LLM gateway**: all model calls go through **LiteLLM** — no direct provider
  SDK calls in business logic.
- **Storage**: S3-compatible only (MinIO/S3). No local filesystem as a
  production store.
- **Orchestration**: pipelines are **Dagster** assets — no ad-hoc scripts.
- **Immutability**: the raw zone is never modified after write.
- **Lineage**: every artifact traces back to its source with stable IDs,
  content hashes, and timestamps.
- **Legal**: respect `robots.txt`, track source licenses, never scrape
  private/restricted content.
- **Models**: use task-based aliases (`cheap_model`, `strong_model`,
  `eval_model`, `embedding_model`) — no hardcoded provider model IDs.
- **Deterministic first**: prefer regex/heuristic extraction before LLM
  enrichment.

### Code style

- **Formatting & linting**: [Ruff](https://docs.astral.sh/ruff/) — line length
  100, target `py312`. Run `make lint` (and `uv run ruff format` to autoformat).
- **Types**: [mypy](https://mypy.readthedocs.io/) — run `make typecheck`. Add
  type hints to all new public functions.
- **Logging**: structured logging via `structlog`.
- **Retries**: use `tenacity` for external calls (HTTP, LLM, services).

## Running Checks and Tests

Run the same checks CI runs before opening a PR:

```bash
make lint          # ruff check src/
make typecheck     # mypy src/
make test-unit     # fast unit tests (no services required)
```

Integration and end-to-end tests need the Docker stack running:

```bash
make up
make test-integration          # tests/integration
uv run pytest tests/e2e        # end-to-end
make test                      # full suite with coverage
```

Test layout:

- `tests/unit/` — pure logic, no external services. Must pass in CI.
- `tests/integration/` — require running services (Postgres, MinIO, Qdrant, …).
- `tests/e2e/` — full pipeline runs.

Markers: `-m "not browser"` skips tests needing a Playwright Chromium binary;
`-m integration` selects integration tests.

Please add tests for any behavior change and keep the unit suite green.

## Commit and PR Guidelines

### Commits

This project uses [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<optional scope>): <description>

feat(crawl): add best-first deep crawl strategy
fix(registry): prevent duplicate source registration on retry
docs(readme): document export contracts
chore(deps): bump qdrant-client to 1.18.0
test(dedup): cover minhash edge cases
```

Common types: `feat`, `fix`, `docs`, `chore`, `test`, `refactor`, `perf`,
`build`, `ci`. Keep commits focused and atomic.

### Pull requests

1. Create a topic branch off `main` (e.g. `feat/best-first-crawl`).
2. Make your change with tests and docs.
3. Ensure `make lint`, `make typecheck`, and `make test-unit` pass.
4. Open a PR using the template; link the related issue.
5. Keep the PR scoped — large unrelated refactors should be separate PRs.

A maintainer will review; address feedback by pushing follow-up commits.
Squash-and-merge is the default merge strategy.

## Extending the Framework

Knowledge Lake treats external tools as replaceable plugins registered through
Python entry points in `pyproject.toml`.

### Add a plugin

1. Implement the relevant Protocol in a new module under
   `src/knowledge_lake/plugins/builtin/` (or your own package).
2. Register it under the matching entry-point group in `pyproject.toml`:
   `knowledge_lake.parsers`, `knowledge_lake.embedders`,
   `knowledge_lake.vectorstores`, `knowledge_lake.crawlers`, or
   `knowledge_lake.discovery`.
3. Add tests and document any new configuration/env vars.

### Add a domain pack

Create a directory under `domains/<name>/` containing:

- `domain.yaml` — pack metadata
- `sources.yaml` — sources to register
- `taxonomy.yaml` — domain taxonomy
- `prompts/` — Jinja enrichment/QA templates
- `validators/` — domain-specific validation

Register all its sources with `uv run klake init --domain <name>`.

## Reporting Bugs and Security Issues

- **Bugs / features**: open a [GitHub Issue](../../issues) with the appropriate
  template.
- **Security vulnerabilities**: do **not** open a public issue. Follow the
  process in [SECURITY.md](SECURITY.md).

---

Thank you for helping make Knowledge Lake better!
