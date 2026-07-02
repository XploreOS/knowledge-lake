# Knowledge Lake API Dockerfile
# Builds the FastAPI service container

FROM python:3.12-slim

# Install system utilities needed for healthchecks and operations
RUN apt-get update -qq && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install uv for fast dependency installation
RUN pip install --no-cache-dir uv

# Copy project metadata
COPY pyproject.toml uv.lock README.md ./

# Copy source code before installing (needed for editable install)
COPY src/ ./src/

# Install the package and runtime dependencies
# Use uv sync without --frozen to allow cross-platform resolution
RUN uv sync --no-dev

# Expose API port
EXPOSE 8000

# Run the FastAPI app via uvicorn
CMD ["uv", "run", "uvicorn", "knowledge_lake.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
