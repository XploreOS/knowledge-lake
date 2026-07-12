"""Unit tests for `klake domain new` domain-pack scaffolding.

Covers the scaffold_domain() function, the generalized validator resolution in
DomainLoader (a scaffolded non-healthcare pack must load), and the CLI command.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from knowledge_lake.cli.app import app
from knowledge_lake.domains.loader import DomainLoader
from knowledge_lake.domains.scaffold import _pascal_case, scaffold_domain

runner = CliRunner()

_EXPECTED_FILES = [
    "domain.yaml",
    "sources.yaml",
    "taxonomy.yaml",
    "prompts/enrich.j2",
    "prompts/qa_generation.j2",
    "validators/__init__.py",
    "validators/validate.py",
]


def test_pascal_case():
    assert _pascal_case("food-science") == "FoodScience"
    assert _pascal_case("legal") == "Legal"
    assert _pascal_case("multi_word-name") == "MultiWordName"


def test_scaffold_creates_all_required_files(tmp_path):
    result = scaffold_domain("food-science", root=tmp_path)

    pack_dir = tmp_path / "food-science"
    assert Path(result["path"]) == pack_dir
    assert result["name"] == "food-science"
    for rel in _EXPECTED_FILES:
        assert (pack_dir / rel).is_file(), f"missing scaffolded file: {rel}"

    # Validator class is named after the domain, not hardcoded to healthcare.
    validate_src = (pack_dir / "validators" / "validate.py").read_text()
    assert "class FoodScienceValidator:" in validate_src
    assert "HealthcareValidator" not in validate_src

    # domain.yaml carries the pack name.
    assert "name: food-science" in (pack_dir / "domain.yaml").read_text()


def test_scaffolded_pack_loads_via_domain_loader(tmp_path):
    """The scaffolded pack must load cleanly — exercises generalized validator lookup."""
    scaffold_domain("legal", root=tmp_path)

    loader = DomainLoader(tmp_path / "legal")

    assert loader.manifest.name == "legal"
    assert loader.sources == []  # empty sources.yaml → no seed sources
    # Generalized validator resolution picked LegalValidator (not HealthcareValidator).
    assert type(loader.validator).__name__ == "LegalValidator"
    result = loader.validator.validate_document({"text": "hello world"})
    assert result.passed is True

    # Prompt templates render with the documented enrich variables.
    rendered = loader.render_prompt(
        "enrich.j2", title="T", dates=[], headings=[], excerpt="body"
    )
    assert "legal domain" in rendered
    assert "body" in rendered


def test_scaffold_rejects_path_traversal_names(tmp_path):
    for bad in ["../evil", "with/slash", "9leading-digit", "has space", ""]:
        with pytest.raises(ValueError):
            scaffold_domain(bad, root=tmp_path)


def test_scaffold_refuses_existing_dir_without_force(tmp_path):
    scaffold_domain("dup", root=tmp_path)
    with pytest.raises(FileExistsError):
        scaffold_domain("dup", root=tmp_path)
    # force overwrites without raising
    result = scaffold_domain("dup", root=tmp_path, force=True)
    assert Path(result["path"]).is_dir()


def test_cli_domain_new_creates_loadable_pack(tmp_path):
    res = runner.invoke(app, ["domain", "new", "my-domain", "--root", str(tmp_path)])
    assert res.exit_code == 0, res.output
    assert "Created domain pack 'my-domain'" in res.output
    # Files really exist and load.
    loader = DomainLoader(tmp_path / "my-domain")
    assert loader.manifest.name == "my-domain"


def test_cli_domain_new_rejects_bad_name(tmp_path):
    res = runner.invoke(app, ["domain", "new", "../evil", "--root", str(tmp_path)])
    assert res.exit_code == 1
    assert "Invalid domain name" in res.output
