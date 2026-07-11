"""Skill presence + registry-tracking gate (SKILL-01, threat T-12-SKILL).

Asserts the four Claude Code skill files exist with valid ``name``/``description``
frontmatter, each drives its D-16 journey by MCP tool name, and — critically — that
every tool a skill mentions exists in the live ``TOOLS`` registry. A skill can
therefore never reference a renamed/removed tool (T-12-SKILL mitigation), because
the skills track the single source of truth.

Exactly four skills are enforced — SKILL-01 scopes precisely four (a fifth is a
Deferred Idea, not this phase).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from knowledge_lake.agent.registry import TOOLS

_SKILLS_DIR = Path(__file__).parents[2] / "skills"

_REGISTRY_NAMES = {t.name for t in TOOLS}

# The four D-16 journeys, keyed by file → the tool names each journey drives.
_SKILL_TOOL_MAP: dict[str, list[str]] = {
    "build-corpus.md": ["add_source", "crawl", "crawl_all", "process_crawled", "search"],
    "search-knowledge.md": ["search", "lineage"],
    "add-source.md": ["add_source", "ingest_url"],
    "export-dataset.md": ["export", "stats"],
}

_EXPECTED_SKILLS = sorted(_SKILL_TOOL_MAP)

# Tokens that are backticked identifiers but are NOT tools: every tool input-model
# field name (derived live so this allowlist self-maintains), plus a few literal
# values/return-keys that appear in the skill prose.
_FIELD_NAMES: set[str] = set()
for _t in TOOLS:
    _FIELD_NAMES |= set(_t.input_model.model_json_schema().get("properties", {}))

_LITERAL_ALLOWLIST = {
    "is_new",  # add_source return field
    "unknown",  # default license_type value
    "hybrid",
    "dense",
    "sparse",  # search modes
    "html",
    "pdf",  # format values
    "true",
    "false",  # booleans in prose
    "healthcare",
    "legal",  # domain examples
    "raw_document",  # artifact type in prose
    "processed",  # process_crawled return key
    "finetune",
    "pretrain",  # export kind values (rag-corpus is hyphenated → never matches)
}

_NON_TOOL_TOKENS = _FIELD_NAMES | _LITERAL_ALLOWLIST

# A backticked simple identifier: `foo`, `add_source`, `top_k` (no hyphens/slashes/dots).
_BACKTICK_IDENT = re.compile(r"`([a-z][a-z0-9_]*)`")


def _read(skill_file: str) -> str:
    return (_SKILLS_DIR / skill_file).read_text(encoding="utf-8")


def _frontmatter(content: str) -> dict:
    """Parse the leading YAML frontmatter block (between the first two ---)."""
    assert content.startswith("---"), "missing YAML frontmatter (--- delimiter)"
    parts = content.split("---", 2)
    assert len(parts) >= 3, "frontmatter is not closed by a second ---"
    return yaml.safe_load(parts[1]) or {}


def _mentioned_tokens(content: str) -> set[str]:
    """All backticked lowercase identifiers used in a skill body."""
    return set(_BACKTICK_IDENT.findall(content))


# ── existence + count ─────────────────────────────────────────────────────────


def test_skills_directory_exists() -> None:
    assert _SKILLS_DIR.is_dir(), f"skills/ directory does not exist at {_SKILLS_DIR}"


@pytest.mark.parametrize("skill_file", _EXPECTED_SKILLS)
def test_skill_file_exists(skill_file: str) -> None:
    assert (_SKILLS_DIR / skill_file).exists(), f"skills/{skill_file} does not exist"


def test_exactly_four_skill_files() -> None:
    """SKILL-01 scopes exactly four skills — no fifth (a fifth is Deferred)."""
    present = {p.name for p in _SKILLS_DIR.glob("*.md")}
    assert present == set(_EXPECTED_SKILLS), (
        f"skills/ must contain exactly the four SKILL-01 files; found {sorted(present)}"
    )


# ── frontmatter ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize("skill_file", _EXPECTED_SKILLS)
def test_skill_has_valid_frontmatter(skill_file: str) -> None:
    fm = _frontmatter(_read(skill_file))
    assert isinstance(fm, dict), f"skills/{skill_file} frontmatter is not a mapping"
    assert fm.get("name"), f"skills/{skill_file} frontmatter missing non-empty 'name'"
    assert fm.get("description"), (
        f"skills/{skill_file} frontmatter missing non-empty 'description'"
    )


@pytest.mark.parametrize("skill_file", _EXPECTED_SKILLS)
def test_skill_name_matches_filename(skill_file: str) -> None:
    fm = _frontmatter(_read(skill_file))
    assert fm["name"] == skill_file[: -len(".md")], (
        f"skills/{skill_file} 'name' ({fm['name']!r}) does not match its filename"
    )


# ── journey coverage: each skill drives its D-16 tools ────────────────────────


@pytest.mark.parametrize("skill_file,tool_names", _SKILL_TOOL_MAP.items())
def test_skill_references_its_journey_tools(
    skill_file: str, tool_names: list[str]
) -> None:
    """Each skill body must reference every tool in its D-16 journey by name."""
    tokens = _mentioned_tokens(_read(skill_file))
    for tool_name in tool_names:
        assert tool_name in _REGISTRY_NAMES, (
            f"journey tool {tool_name!r} for {skill_file} is not in the registry"
        )
        assert tool_name in tokens, (
            f"skills/{skill_file} does not reference journey tool `{tool_name}`"
        )


# ── registry-tracking gate: no stale/foreign tool references (T-12-SKILL) ─────


@pytest.mark.parametrize("skill_file", _EXPECTED_SKILLS)
def test_skill_mentions_only_registry_tools(skill_file: str) -> None:
    """Every tool-shaped token a skill mentions must exist in TOOLS.

    Backticked identifiers that are known input-model field names or literal
    values are excluded; whatever remains must be a real registry tool. A skill
    referencing a renamed/removed tool (e.g. `crawl_site`) fails here.
    """
    candidates = _mentioned_tokens(_read(skill_file)) - _NON_TOOL_TOKENS
    stale = candidates - _REGISTRY_NAMES
    assert not stale, (
        f"skills/{skill_file} references tool name(s) not in the registry: "
        f"{sorted(stale)} (registry: {sorted(_REGISTRY_NAMES)})"
    )
