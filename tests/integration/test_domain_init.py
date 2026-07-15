"""Wave 0 integration test stubs for klake init --domain (DOMAIN-01, IFACE-01).

Tests that 'klake init --domain healthcare' registers sources from sources.yaml
into the registry database. Requires live PostgreSQL (compose stack).
"""

from __future__ import annotations

import pytest

try:
    from typer.testing import CliRunner
    from knowledge_lake.cli.app import app
    _IMPORT_OK = True
except ImportError:
    CliRunner = None  # type: ignore[assignment, misc]
    app = None  # type: ignore[assignment]
    _IMPORT_OK = False


@pytest.mark.integration
def test_klake_init_domain_registers_sources() -> None:
    """klake init --domain healthcare registers at least 1 source with domain=='healthcare' in DB."""
    if not _IMPORT_OK:
        pytest.skip("CLI app import failed")

    runner = CliRunner()
    result = runner.invoke(app, ["init", "--domain", "healthcare"])

    # Command must exit without error
    assert result.exit_code == 0, (
        f"klake init --domain healthcare exited {result.exit_code}. "
        f"Output: {result.output!r}"
    )

    # At least one source must be registered with domain == 'healthcare'
    from sqlalchemy import select
    from knowledge_lake.registry.db import get_session
    from knowledge_lake.registry.models import Source

    with get_session() as session:
        stmt = select(Source).where(
            Source.config["domain"].as_string() == "healthcare"  # type: ignore[index]
        ).limit(1)
        source = session.execute(stmt).scalar_one_or_none()

    assert source is not None, (
        "Expected at least 1 source with config.domain == 'healthcare' in DB after "
        "klake init --domain healthcare"
    )
