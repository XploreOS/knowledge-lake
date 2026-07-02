# Knowledge Lake — Makefile
# Usage: make <target>

.PHONY: help install dev-install lint typecheck test test-unit test-integration spike up down

help: ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

install: ## Install runtime dependencies via uv
	uv sync

dev-install: ## Install all deps including dev
	uv sync --extra dev

lint: ## Run ruff linter on src/
	uv run ruff check src/

typecheck: ## Run mypy type checker
	uv run mypy src/

test: ## Run full test suite
	uv run pytest --cov=knowledge_lake

test-unit: ## Run unit tests only
	uv run pytest tests/unit/ -x -q

test-integration: ## Run integration tests (requires docker compose stack up)
	uv run pytest tests/integration/ -x -q

up: ## Bring up the full compose stack
	docker compose up -d

down: ## Tear down the compose stack
	docker compose down

spike: ## Run the end-to-end demo spike (added in plan 01-05)
	uv run klake demo
