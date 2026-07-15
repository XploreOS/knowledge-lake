# Knowledge Lake API Dockerfile
# Builds the FastAPI service container

FROM python:3.12-slim
# Pinned to 3.12 to match .python-version / pyproject.toml (requires-python
# ">=3.12"). A prior drift bump to 3.14-slim (88116e7) left the image
# unbuildable: greenlet 3.1.1 (transitive via SQLAlchemy) uses CPython
# internals (`_PyInterpreterFrame` layout, `c_recursion_remaining`) that
# changed in 3.14, so its C extension fails to compile — not a missing-wheel
# problem, a genuine incompatibility. Reverted while fixing KL-08, which
# required a successful rebuild to verify the new bind mount.

# Install system utilities needed for healthchecks and operations
RUN apt-get update -qq && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install uv for fast dependency installation
RUN pip install --no-cache-dir uv

# Copy project metadata
# LICENSE + NOTICE must be present at build time: pyproject.toml declares
# license-files = ["LICENSE", "NOTICE"] and `uv sync` fails the build
# ("license-files glob ... did not match any files") without them.
COPY pyproject.toml uv.lock README.md LICENSE NOTICE ./

# Copy source code before installing (needed for editable install)
COPY src/ ./src/

# Install the package and runtime dependencies
# Use uv sync without --frozen to allow cross-platform resolution
RUN uv sync --no-dev

# Install Playwright browser binaries (Chromium + OS deps) for SPA crawling (INGEST-06, Pitfall 5)
# Must run AFTER uv sync so the playwright CLI is available.
# crawl4ai-setup pre-caches browser state needed by the crawl4ai async browser mode.
RUN uv run playwright install --with-deps chromium && \
    uv run crawl4ai-setup || true

# Expose API port
EXPOSE 8000

# Run the FastAPI app via uvicorn
CMD ["uv", "run", "uvicorn", "knowledge_lake.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
