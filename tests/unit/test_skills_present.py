"""Wave 0 RED scaffold: Claude Code skill files assertions (SKILL-01).

Asserts that the four ``skills/*.md`` files exist with valid ``name`` and
``description`` frontmatter, and that the tool names referenced in their
frontmatter exist in the tool registry.

Tests that check file content are xfail until Plan 04 creates the skill files.
Tests that check the registry are xfail until Plan 02 builds the registry.
"""

from __future__ import annotations

from pathlib import Path

import pytest

try:
    from knowledge_lake.agent.registry import TOOLS
    _IMPORT_OK = True
except ImportError:
    TOOLS = None  # type: ignore[assignment]
    _IMPORT_OK = False

_SKILLS_DIR = Path(__file__).parents[2] / "skills"

_EXPECTED_SKILLS = [
    "build-corpus.md",
    "search-knowledge.md",
    "add-source.md",
    "export-dataset.md",
]

# Tool names referenced in each skill (per plan artifacts list)
_SKILL_TOOL_MAP = {
    "build-corpus.md": ["crawl_all", "process_crawled"],
    "search-knowledge.md": ["search"],
    "add-source.md": ["add_source", "ingest_url"],
    "export-dataset.md": ["export"],
}


@pytest.mark.xfail(reason="Wave 0 scaffold — skills/*.md not yet created (Plan 04)", strict=False)
def test_skills_directory_exists() -> None:
    """skills/ directory must exist at project root."""
    assert _SKILLS_DIR.exists(), f"skills/ directory does not exist at {_SKILLS_DIR}"
    assert _SKILLS_DIR.is_dir(), f"{_SKILLS_DIR} is not a directory"


@pytest.mark.xfail(reason="Wave 0 scaffold — skills/*.md not yet created (Plan 04)", strict=False)
@pytest.mark.parametrize("skill_file", _EXPECTED_SKILLS)
def test_skill_file_exists(skill_file: str) -> None:
    """Each expected skill file must exist in skills/."""
    skill_path = _SKILLS_DIR / skill_file
    assert skill_path.exists(), (
        f"skills/{skill_file} does not exist. Run Plan 04 to create skill files."
    )


@pytest.mark.xfail(reason="Wave 0 scaffold — skills/*.md not yet created (Plan 04)", strict=False)
@pytest.mark.parametrize("skill_file", _EXPECTED_SKILLS)
def test_skill_has_name_frontmatter(skill_file: str) -> None:
    """Each skill file must have a 'name' field in YAML frontmatter."""
    skill_path = _SKILLS_DIR / skill_file
    if not skill_path.exists():
        pytest.skip(f"skills/{skill_file} not yet created")
    content = skill_path.read_text(encoding="utf-8")
    assert content.startswith("---"), f"skills/{skill_file} missing YAML frontmatter (--- delimiter)"
    # Simple line-based check for name: field
    fm_lines = content.split("---")[1] if "---" in content else ""
    assert "name:" in fm_lines, f"skills/{skill_file} frontmatter missing 'name' field"


@pytest.mark.xfail(reason="Wave 0 scaffold — skills/*.md not yet created (Plan 04)", strict=False)
@pytest.mark.parametrize("skill_file", _EXPECTED_SKILLS)
def test_skill_has_description_frontmatter(skill_file: str) -> None:
    """Each skill file must have a 'description' field in YAML frontmatter."""
    skill_path = _SKILLS_DIR / skill_file
    if not skill_path.exists():
        pytest.skip(f"skills/{skill_file} not yet created")
    content = skill_path.read_text(encoding="utf-8")
    fm_lines = content.split("---")[1] if content.count("---") >= 2 else ""
    assert "description:" in fm_lines, (
        f"skills/{skill_file} frontmatter missing 'description' field"
    )


@pytest.mark.xfail(
    not _IMPORT_OK,
    reason="Wave 0 scaffold — agent.registry or skills/*.md not yet implemented",
    strict=False,
)
@pytest.mark.parametrize("skill_file,tool_names", _SKILL_TOOL_MAP.items())
def test_skill_tool_names_exist_in_registry(skill_file: str, tool_names: list[str]) -> None:
    """Tool names referenced in each skill must exist in the registry (D-11)."""
    assert TOOLS is not None
    registry_names = {t.name for t in TOOLS}
    for tool_name in tool_names:
        assert tool_name in registry_names, (
            f"skills/{skill_file} references tool {tool_name!r} "
            f"which is not in the registry: {sorted(registry_names)}"
        )
