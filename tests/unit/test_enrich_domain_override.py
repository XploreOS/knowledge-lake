"""Tests for pipeline/enrich.py domain_system_prompt override (06-02, DOMAIN-03).

Verifies that:
- enrich_document(..., domain_system_prompt="CUSTOM") passes "CUSTOM" as messages[0]["content"]
  to litellm.completion, overriding the generic _ENRICHMENT_SYSTEM_PROMPT.
- enrich_document() without domain_system_prompt uses the generic _ENRICHMENT_SYSTEM_PROMPT.

Uses the same fixture/mock pattern as tests/unit/test_enrich.py.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import knowledge_lake.pipeline.enrich as enrich_module
import knowledge_lake.registry.db as registry_db
from knowledge_lake.config.settings import Settings
from knowledge_lake.pipeline.enrich import _ENRICHMENT_SYSTEM_PROMPT

CLEANED_TEXT = "The HIPAA Privacy Rule requires PHI safeguards."

VALID_PAYLOAD = {
    "summary": "Healthcare privacy regulation document.",
    "document_type": "regulation",
    "organization": "HHS",
    "jurisdiction": "US",
    "keywords": ["hipaa", "privacy"],
    "entities": ["HHS"],
    "quality_score": 0.85,
}


# ── Fixtures ───────────────────────────────────────────────────────────────────


@pytest.fixture()
def engine():
    """In-memory SQLite engine, shared connection via StaticPool."""
    from knowledge_lake.registry.models import Base

    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture(autouse=True)
def _patch_engine(monkeypatch, engine):
    """Route registry.db.get_session() to the in-memory test engine."""
    monkeypatch.setattr(registry_db, "get_engine", lambda: engine)


@pytest.fixture()
def session(engine):
    with Session(engine) as sess:
        yield sess


@pytest.fixture()
def seeded(session):
    """Seed a Source -> raw -> parsed -> cleaned_document artifact chain."""
    from knowledge_lake.registry import repo as registry_repo

    source = registry_repo.create_source(session, name="Domain Test Source", source_type="web")
    raw = registry_repo.create_raw_artifact(
        session,
        source_id=source.id,
        content_hash="raw_domain_h",
        storage_uri="s3://b/raw/raw_domain_h.pdf",
    )
    parsed = registry_repo.create_parsed_artifact(
        session,
        source_id=source.id,
        parent_artifact_id=raw.id,
        content_hash="parsed_domain_h",
        storage_uri="s3://b/silver/parsed_domain_h.md",
    )
    cleaned = registry_repo.create_cleaned_artifact(
        session,
        source_id=source.id,
        parent_artifact_id=parsed.id,
        content_hash="cleaned_domain_h",
        storage_uri="s3://b/silver/cleaned_domain_h.md",
    )
    session.commit()
    return {"source_id": source.id, "cleaned_artifact_id": cleaned.id}


@pytest.fixture()
def fake_storage(monkeypatch):
    """Patch StorageBackend to return canned bytes."""
    fake = MagicMock()
    fake.get_object.return_value = CLEANED_TEXT.encode("utf-8")
    monkeypatch.setattr(enrich_module, "StorageBackend", lambda *_a, **_k: fake)
    return fake


@pytest.fixture()
def test_settings() -> Settings:
    return Settings(_env_file=None)  # type: ignore[call-arg]


def _mock_llm_response(payload: dict, prompt_tokens: int = 100, completion_tokens: int = 50):
    resp = MagicMock()
    resp.choices = [MagicMock(message=MagicMock(content=json.dumps(payload)))]
    resp.usage = MagicMock(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)
    return resp


# ── Tests ──────────────────────────────────────────────────────────────────────


def test_domain_system_prompt_replaces_generic(
    engine, seeded, fake_storage, test_settings
) -> None:
    """When enrich_document is called with domain_system_prompt='CUSTOM SYSTEM',
    the litellm.completion call receives messages[0]['content'] == 'CUSTOM SYSTEM'.
    """
    captured_calls: list = []

    def _mock_completion(**kwargs):
        captured_calls.append(kwargs)
        return _mock_llm_response(VALID_PAYLOAD)

    with patch("litellm.completion", side_effect=_mock_completion):
        result = enrich_module.enrich_document(
            seeded["cleaned_artifact_id"],
            seeded["source_id"],
            domain_system_prompt="CUSTOM SYSTEM",
            settings=test_settings,
        )

    assert result["status"] == "enriched"
    assert len(captured_calls) == 1
    messages = captured_calls[0]["messages"]
    assert messages[0]["role"] == "system"
    assert messages[0]["content"] == "CUSTOM SYSTEM"


def test_no_domain_prompt_uses_generic(
    engine, seeded, fake_storage, test_settings
) -> None:
    """When enrich_document is called without domain_system_prompt,
    messages[0]['content'] == _ENRICHMENT_SYSTEM_PROMPT (generic unchanged).
    """
    captured_calls: list = []

    def _mock_completion(**kwargs):
        captured_calls.append(kwargs)
        return _mock_llm_response(VALID_PAYLOAD)

    with patch("litellm.completion", side_effect=_mock_completion):
        result = enrich_module.enrich_document(
            seeded["cleaned_artifact_id"],
            seeded["source_id"],
            settings=test_settings,
        )

    assert result["status"] == "enriched"
    assert len(captured_calls) == 1
    messages = captured_calls[0]["messages"]
    assert messages[0]["role"] == "system"
    assert messages[0]["content"] == _ENRICHMENT_SYSTEM_PROMPT


def test_build_enrichment_prompt_with_domain_override() -> None:
    """Unit-level test: _build_enrichment_prompt returns domain_system_prompt when provided."""
    from knowledge_lake.pipeline.enrich import _build_enrichment_prompt

    system, _user = _build_enrichment_prompt(
        excerpt="test excerpt",
        deterministic={"title": "Test", "dates": [], "headings": []},
        domain_system_prompt="DOMAIN OVERRIDE SYSTEM",
    )
    assert system == "DOMAIN OVERRIDE SYSTEM"


def test_build_enrichment_prompt_without_override_uses_generic() -> None:
    """Unit-level test: _build_enrichment_prompt returns _ENRICHMENT_SYSTEM_PROMPT when domain_system_prompt=None."""
    from knowledge_lake.pipeline.enrich import _ENRICHMENT_SYSTEM_PROMPT, _build_enrichment_prompt

    system, _user = _build_enrichment_prompt(
        excerpt="test excerpt",
        deterministic={"title": "Test", "dates": [], "headings": []},
    )
    assert system == _ENRICHMENT_SYSTEM_PROMPT
