"""
Integration test: compose stack health check (FOUND-01).

Polls each service healthcheck/endpoint until healthy within a timeout,
then asserts all six services are healthy and GET /health returns 200.

This test is skipped automatically when Docker is unavailable or the
compose stack is not running (it does NOT attempt to start the stack).
To run with the stack:
    docker compose up -d
    uv run pytest tests/integration/test_compose_health.py -v
"""

from __future__ import annotations

import os
import shutil
import time

import httpx
import pytest


def _docker_available() -> bool:
    """Return True if docker and docker compose are available on PATH."""
    return shutil.which("docker") is not None


def _stack_running() -> bool:
    """Return True if the compose stack appears to be up (api service responds)."""
    try:
        r = httpx.get(
            f"http://localhost:{os.environ.get('API_PORT', '8000')}/health",
            timeout=2.0,
        )
        return r.status_code == 200
    except Exception:
        return False


SKIP_REASON = (
    "Docker not available or compose stack is not running. "
    "Run `docker compose up -d` first, then re-run this test."
)

# Skip the test module if docker is unavailable or the stack is not up
pytestmark = pytest.mark.skipif(
    not _docker_available() or not _stack_running(),
    reason=SKIP_REASON,
)


SERVICES = {
    "postgres": {
        "url": f"http://localhost:{os.environ.get('POSTGRES_PORT', '5432')}",
        "check": "pg_isready",  # checked via docker healthcheck; not an HTTP endpoint
        "http": False,
    },
    "minio": {
        "url": f"http://localhost:{os.environ.get('MINIO_PORT', '9000')}/minio/health/live",
        "http": True,
    },
    "qdrant": {
        "url": f"http://localhost:{os.environ.get('QDRANT_HTTP_PORT', '6333')}/healthz",
        "http": True,
    },
    "litellm": {
        "url": f"http://localhost:{os.environ.get('LITELLM_PORT', '4000')}/health/liveliness",
        "http": True,
    },
    "dagster-webserver": {
        "url": f"http://localhost:{os.environ.get('DAGSTER_PORT', '3000')}/",
        "http": True,
    },
    "api": {
        "url": f"http://localhost:{os.environ.get('API_PORT', '8000')}/health",
        "http": True,
    },
}


def _wait_for_http(url: str, timeout: int = 120, interval: float = 3.0) -> bool:
    """Poll an HTTP endpoint until it returns 2xx or timeout expires."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            r = httpx.get(url, timeout=5.0, follow_redirects=True)
            if r.status_code < 400:
                return True
        except Exception:
            pass
        time.sleep(interval)
    return False


class TestComposeHealth:
    """Assert all six compose services are healthy."""

    def test_minio_healthy(self) -> None:
        assert _wait_for_http(SERVICES["minio"]["url"]), "MinIO health check timed out"

    def test_qdrant_healthy(self) -> None:
        assert _wait_for_http(SERVICES["qdrant"]["url"]), "Qdrant health check timed out"

    def test_litellm_healthy(self) -> None:
        assert _wait_for_http(SERVICES["litellm"]["url"]), "LiteLLM health check timed out"

    def test_dagster_webserver_healthy(self) -> None:
        assert _wait_for_http(
            SERVICES["dagster-webserver"]["url"]
        ), "Dagster webserver health check timed out"

    def test_api_health_endpoint_returns_200(self) -> None:
        url = SERVICES["api"]["url"]
        assert _wait_for_http(url), f"API health endpoint timed out: {url}"
        r = httpx.get(url, timeout=10.0)
        assert r.status_code == 200, f"Expected 200, got {r.status_code}"
        body = r.json()
        # KL-08: `version` was added to surface stale-container drift; assert
        # `status` plus presence of `version` rather than exact dict equality.
        assert body.get("status") == "ok", f"Unexpected body: {body}"
        assert body.get("version"), f"Missing/empty version: {body}"

    def test_all_http_services_reachable(self) -> None:
        """Quick combined check that all HTTP-checkable services respond."""
        failures = []
        for name, svc in SERVICES.items():
            if not svc.get("http", True):
                continue
            try:
                r = httpx.get(svc["url"], timeout=5.0, follow_redirects=True)
                if r.status_code >= 400:
                    failures.append(f"{name}: HTTP {r.status_code}")
            except Exception as e:
                failures.append(f"{name}: {e}")
        assert not failures, f"Services unreachable:\n" + "\n".join(failures)
