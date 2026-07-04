"""Scrapy adapter — subprocess-based web crawler plugin (INGEST-05, T-02-14).

Implements CrawlerPlugin for Scrapy 2.16.x, running each crawl job in a fresh
child process to avoid Twisted's ReactorNotRestartable limitation.

Architecture:
  start_crawl  → validate_public_url(source_url), build temp dir, spawn subprocess
  poll_status  → check proc.poll(); map exit code to status string
  get_results  → parse completed JSONL written by the child spider

Security mitigations:
  T-02-14: Each crawl runs in a separate subprocess — reactor dies with the child.
  T-02-15: validate_public_url is called before spawning; the child re-validates every URL.
  T-02-16: ROBOTSTXT_OBEY=True is set in the child's Scrapy settings.
  T-02-17: DOWNLOAD_MAXSIZE=50 MB + AUTOTHROTTLE + per-host delay from config.

Entry point:
    [project.entry-points."knowledge_lake.crawlers"]
    scrapy = "knowledge_lake.plugins.builtin.scrapy_adapter:ScrapyAdapter"
"""

from __future__ import annotations

import base64
import datetime
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import structlog

from knowledge_lake.pipeline.ingest import validate_public_url
from knowledge_lake.plugins.protocols import CrawlJob, CrawlPageResult, CrawlerPlugin

log = structlog.get_logger(__name__)


class ScrapyAdapter:
    """Scrapy-backed CrawlerPlugin implementation using subprocess isolation.

    Satisfies the CrawlerPlugin Protocol (runtime_checkable).

    The adapter drives each Scrapy crawl in a fresh child process by spawning:
        python -m knowledge_lake.plugins.builtin.scrapy_spider <url> <out.jsonl> <config.json>

    This guarantees no ReactorNotRestartable errors on repeated in-process crawls
    (Pitfall 1 from RESEARCH.md; scrapy/scrapy#2941).

    Protocol attributes:
        name = 'scrapy'
    """

    name: str = "scrapy"

    def __init__(self) -> None:
        self._jobs: dict[str, CrawlJob] = {}
        self._procs: dict[str, subprocess.Popen[bytes]] = {}
        self._out_paths: dict[str, Path] = {}
        self._tmp_dirs: dict[str, tempfile.TemporaryDirectory[str]] = {}

    def start_crawl(self, source_url: str, config: dict[str, Any]) -> CrawlJob:
        """Validate URL, write config file, spawn child spider process.

        SECURITY (T-02-15): validate_public_url is called BEFORE spawning the
        child. If it raises, no subprocess is created.

        Args:
            source_url: The seed URL to crawl (must be https://).
            config:     Crawler configuration dict (max_pages, max_depth,
                        per_host_delay, etc.).

        Returns:
            CrawlJob with status 'running'.

        Raises:
            ValueError: If source_url fails SSRF validation.
        """
        # SSRF guard — must run before any subprocess spawn (T-02-15)
        validate_public_url(source_url)

        from knowledge_lake.ids import new_id

        job_id = new_id("crawl_job")

        # Create a temp dir that lives for the duration of this crawl
        tmp_dir = tempfile.TemporaryDirectory(prefix=f"klake_scrapy_{job_id}_")
        tmp_path = Path(tmp_dir.name)
        out_jsonl = tmp_path / "results.jsonl"
        config_json = tmp_path / "config.json"

        # Serialize config for the child process
        config_json.write_text(json.dumps(config), encoding="utf-8")

        log.info(
            "scrapy_adapter.start_crawl",
            job_id=job_id,
            source_url=source_url,
            out_jsonl=str(out_jsonl),
        )

        # Spawn the child spider (T-02-14: never call CrawlerProcess.start() in-process)
        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "knowledge_lake.plugins.builtin.scrapy_spider",
                source_url,
                str(out_jsonl),
                str(config_json),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        job = CrawlJob(
            job_id=job_id,
            source_url=source_url,
            crawler=self.name,
            status="running",
            config=config,
        )

        self._jobs[job_id] = job
        self._procs[job_id] = proc
        self._out_paths[job_id] = out_jsonl
        self._tmp_dirs[job_id] = tmp_dir

        return job

    def poll_status(self, job_id: str) -> str:
        """Check the current status of a crawl job by polling the child process.

        Mapping:
          proc.poll() is None → "running"   (child still active)
          proc.poll() == 0    → "complete"  (child exited cleanly)
          proc.poll() != 0    → "failed"    (child exited with error)

        Args:
            job_id: The job ID returned by start_crawl().

        Returns:
            Current status string: 'running', 'complete', 'failed', or 'unknown'.
        """
        if job_id not in self._procs:
            return "unknown"

        proc = self._procs[job_id]
        exit_code = proc.poll()

        if exit_code is None:
            return "running"
        elif exit_code == 0:
            # Update job record
            if job_id in self._jobs:
                self._jobs[job_id].status = "complete"
            return "complete"
        else:
            if job_id in self._jobs:
                self._jobs[job_id].status = "failed"
            return "failed"

    def get_results(self, job_id: str) -> list[CrawlPageResult]:
        """Parse JSONL output from the completed child spider.

        Reads the JSONL file written by scrapy_spider and maps each record to
        a CrawlPageResult. HTML is base64-encoded in the JSONL (binary-safe).

        Must only be called after poll_status returns 'complete' or 'failed'.

        Args:
            job_id: The job ID of a crawl job.

        Returns:
            List of CrawlPageResult objects, one per page attempted.

        Raises:
            RuntimeError: If no results file exists for this job.
        """
        if job_id not in self._out_paths:
            raise RuntimeError(f"No results path recorded for job {job_id}")

        out_path = self._out_paths[job_id]

        if not out_path.exists():
            # Empty crawl (no pages reached) or child exited before writing
            log.warning("scrapy_adapter.no_results_file", job_id=job_id, path=str(out_path))
            return []

        results: list[CrawlPageResult] = []
        fetched_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

        for line in out_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                log.warning("scrapy_adapter.parse_error", line=line[:80], error=str(exc))
                continue

            url = obj.get("url", "")
            status = obj.get("status", "failed")
            error = obj.get("error")

            # Decode base64-encoded HTML bytes
            html: bytes | None = None
            html_b64 = obj.get("html_b64")
            if html_b64:
                try:
                    html = base64.b64decode(html_b64)
                except Exception:
                    html = None

            # Map robots-blocked status from child
            if status == "robots_blocked":
                results.append(
                    CrawlPageResult(
                        url=url,
                        status="robots_blocked",
                        html=None,
                        markdown=None,
                    )
                )
            elif status == "complete":
                results.append(
                    CrawlPageResult(
                        url=url,
                        status="complete",
                        html=html,
                        markdown=obj.get("markdown"),
                        fetched_at=fetched_at,
                    )
                )
            else:
                results.append(
                    CrawlPageResult(
                        url=url,
                        status="failed",
                        html=None,
                        markdown=None,
                        error=error,
                    )
                )

        log.info(
            "scrapy_adapter.results_parsed",
            job_id=job_id,
            count=len(results),
        )
        return results

    def wait_for_completion(self, job_id: str, timeout: float | None = None) -> str:
        """Block until the child process exits and return final status.

        Helper for synchronous usage (e.g., tests, CLI).

        Args:
            job_id:  The job ID.
            timeout: Optional timeout in seconds (raises TimeoutError on expiry).

        Returns:
            Final status: 'complete' or 'failed'.
        """
        if job_id not in self._procs:
            return "unknown"
        proc = self._procs[job_id]
        try:
            exit_code = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            raise TimeoutError(f"Scrapy crawl job {job_id} timed out after {timeout}s")

        if exit_code == 0:
            if job_id in self._jobs:
                self._jobs[job_id].status = "complete"
            return "complete"
        else:
            _, stderr_bytes = proc.communicate() if proc.stderr else (None, b"")
            stderr_text = (stderr_bytes or b"").decode("utf-8", errors="replace")
            log.warning(
                "scrapy_adapter.child_failed",
                job_id=job_id,
                exit_code=exit_code,
                stderr=stderr_text[-500:],
            )
            if job_id in self._jobs:
                self._jobs[job_id].status = "failed"
            return "failed"

    def cleanup(self, job_id: str) -> None:
        """Release temp dir and process handle for a completed job.

        Call after get_results() to free filesystem resources.
        """
        tmp_dir = self._tmp_dirs.pop(job_id, None)
        if tmp_dir:
            try:
                tmp_dir.cleanup()
            except OSError:
                pass
        self._procs.pop(job_id, None)
        self._out_paths.pop(job_id, None)


# Runtime check: ScrapyAdapter must satisfy CrawlerPlugin protocol at import time
assert isinstance(ScrapyAdapter(), CrawlerPlugin), (
    "ScrapyAdapter does not satisfy CrawlerPlugin protocol — check start_crawl/poll_status/get_results"
)
