"""
Pipeline version helper for Knowledge Lake (D-04, FOUND-06).

Every artifact row in the registry carries a ``pipeline_version`` field that
stamps which version of the framework produced it.  The format is::

    "<package_version>+<short_git_sha>"   # inside a git checkout
    "<package_version>"                    # outside a git checkout / CI

This makes artifacts traceable across code revisions without coupling to any
external version-control system.

Usage::

    from knowledge_lake.version import pipeline_version

    pv = pipeline_version()   # e.g. "0.1.0+abc1234"
"""

from __future__ import annotations

import importlib.metadata
import subprocess

_PACKAGE_NAME = "knowledge-lake"
"""Distribution name as registered in pyproject.toml."""


def pipeline_version() -> str:
    """Return the pipeline version string for stamping on artifacts.

    The result is ``"<pkg_version>+<short_sha>"`` when running inside a git
    checkout, or ``"<pkg_version>"`` when git is unavailable (e.g. inside a
    Docker image built without the ``.git`` directory).

    Falls back to ``"0.0.0"`` when the package is not installed (development
    editable installs should still report the correct version via
    ``importlib.metadata``).

    This function must never raise — it is called on every artifact write.
    """
    # 1. Resolve the installed package version; fall back to "0.0.0".
    try:
        base = importlib.metadata.version(_PACKAGE_NAME)
    except importlib.metadata.PackageNotFoundError:
        base = "0.0.0"

    # 2. Try to append the short git SHA for precise source traceability.
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        sha = result.stdout.strip()
        if sha:
            return f"{base}+{sha}"
    except Exception:  # noqa: BLE001  # git unavailable or timeout — graceful
        pass

    return base
