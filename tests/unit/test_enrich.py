"""Tests for pipeline/enrich.py — cached, budget-capped LLM enrichment (ENRICH-01, 03, 04, 05).

Uses an in-memory-SQLite-backed session (mirrors tests/unit/test_registry.py's
engine/session fixtures) with knowledge_lake.registry.db.get_engine monkeypatched
so enrich_document()'s own get_session() calls resolve against the same
in-memory database. StorageBackend is patched at the pipeline.enrich module
level so no real S3 client is constructed. litellm.completion is mocked via
unittest.mock.patch (mirrors tests/unit/test_quality_scorer.py /
tests/unit/test_builtin_plugins.py's mocking style).
"""

from __future__ import annotations

import inspect
import json
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import knowledge_lake.pipeline.enrich as enrich_module
import knowledge_lake.registry.db as registry_db
from knowledge_lake.config.settings import Settings
from knowledge_lake.pipeline.deterministic import extract_deterministic_fields
from knowledge_lake.plugins.protocols import ParsedDoc, Section

CLEANED_TEXT = "The HIPAA Security Rule requires administrative safeguards."

VALID_PAYLOAD = {
    "summary": "This document describes HIPAA administrative safeguards.",
    "document_type": "regulation",
    "organization": "HHS",
    "jurisdiction": "US",
    "keywords": ["hipaa", "security"],
    "entities": ["HHS"],
    "quality_score": 0.9,
}


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def engine():
    """In-memory SQLite engine, shared connection via StaticPool so multiple
    Session() instances (opened by separate get_session() calls) all see the
    same database.
    """
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
    """Route registry.db.get_session() at the enrich_document() call sites to
    the in-memory test engine.
    """
    monkeypatch.setattr(registry_db, "get_engine", lambda: engine)


@pytest.fixture()
def session(engine):
    with Session(engine) as sess:
        yield sess


@pytest.fixture()
def seeded(session):
    """Seed a Source -> raw -> parsed -> cleaned_document artifact chain."""
    from knowledge_lake.registry import repo as registry_repo

    source = registry_repo.create_source(session, name="Test Source", source_type="web")
    raw = registry_repo.create_raw_artifact(
        session,
        source_id=source.id,
        content_hash="raw_h",
        storage_uri="s3://b/raw/raw_h.pdf",
    )
    parsed = registry_repo.create_parsed_artifact(
        session,
        source_id=source.id,
        parent_artifact_id=raw.id,
        content_hash="parsed_h",
        storage_uri="s3://b/silver/parsed_h.md",
    )
    cleaned = registry_repo.create_cleaned_artifact(
        session,
        source_id=source.id,
        parent_artifact_id=parsed.id,
        content_hash="cleaned_h",
        storage_uri="s3://b/silver/cleaned_h.md",
    )
    session.commit()
    return {"source_id": source.id, "cleaned_artifact_id": cleaned.id}


@pytest.fixture()
def fake_storage(monkeypatch):
    """Patch StorageBackend used inside pipeline.enrich to return canned bytes."""
    fake = MagicMock()
    fake.get_object.return_value = CLEANED_TEXT.encode("utf-8")
    monkeypatch.setattr(enrich_module, "StorageBackend", lambda *_a, **_k: fake)
    return fake


@pytest.fixture()
def parsed_doc() -> ParsedDoc:
    return ParsedDoc(
        text=CLEANED_TEXT,
        sections=[Section(heading="Administrative Safeguards", section_path="§1", page=1)],
        metadata={},
    )


@pytest.fixture()
def test_settings() -> Settings:
    return Settings(_env_file=None)  # type: ignore[call-arg]


def _mock_llm_response(payload: dict, prompt_tokens: int = 100, completion_tokens: int = 50):
    resp = MagicMock()
    resp.choices = [MagicMock(message=MagicMock(content=json.dumps(payload)))]
    resp.usage = MagicMock(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)
    return resp


# ── Tests ─────────────────────────────────────────────────────────────────────


def test_no_hardcoded_provider_model_ids() -> None:
    """pipeline/enrich.py must never contain a hardcoded provider model ID literal."""
    source = inspect.getsource(enrich_module)
    forbidden = [
        "anthropic/",
        "claude-",
        "amazon.titan",
        "bedrock/",
        "gpt-",
        "text-embedding-",
    ]
    for fragment in forbidden:
        assert fragment not in source, f"Found hardcoded provider ID fragment {fragment!r}"


def test_enrich_produces_valid_result(
    engine, seeded, fake_storage, parsed_doc, test_settings
) -> None:
    """A mocked litellm.completion returning valid JSON creates an enriched_document
    artifact parented on the cleaned artifact, with the deterministic title merged in.
    """
    from knowledge_lake.registry import repo as registry_repo

    mock_completion = MagicMock(return_value=_mock_llm_response(VALID_PAYLOAD))
    with patch("litellm.completion", mock_completion):
        result = enrich_module.enrich_document(
            seeded["cleaned_artifact_id"],
            seeded["source_id"],
            parsed_doc=parsed_doc,
            settings=test_settings,
        )

    assert result["status"] == "enriched"
    assert result["quality_score"] == pytest.approx(0.9)
    assert result["artifact_id"] is not None
    mock_completion.assert_called_once()
    # cheap_model task alias only — never a hardcoded provider model ID.
    # "openai/" is the wire-protocol prefix the LiteLLM proxy requires, not a
    # provider ID (Phase 4 checkpoint finding).
    assert mock_completion.call_args.kwargs["model"] == "openai/cheap_model"

    expected_title = extract_deterministic_fields(
        parsed_doc.metadata, parsed_doc.sections, CLEANED_TEXT
    )["title"]

    with Session(engine) as check_session:
        artifact = registry_repo.get_artifact(check_session, result["artifact_id"])
        assert artifact is not None
        assert artifact.parent_artifact_id == seeded["cleaned_artifact_id"]
        assert artifact.metadata_["title"] == expected_title


def test_enrich_cache_hit_is_noop(engine, seeded, fake_storage, parsed_doc, test_settings) -> None:
    """Calling enrich_document twice for the same cleaned artifact + prompt_version
    makes exactly one litellm.completion call (the second call is a cache hit).
    """
    mock_completion = MagicMock(return_value=_mock_llm_response(VALID_PAYLOAD))
    with patch("litellm.completion", mock_completion):
        first = enrich_module.enrich_document(
            seeded["cleaned_artifact_id"],
            seeded["source_id"],
            parsed_doc=parsed_doc,
            settings=test_settings,
        )
        second = enrich_module.enrich_document(
            seeded["cleaned_artifact_id"],
            seeded["source_id"],
            parsed_doc=parsed_doc,
            settings=test_settings,
        )

    assert first["status"] == "enriched"
    assert second["status"] == "cached"
    assert second["cached"] is True
    assert second["artifact_id"] == first["artifact_id"]
    assert mock_completion.call_count == 1


def test_budget_exceeded_halts_gracefully(
    engine, seeded, fake_storage, parsed_doc, test_settings
) -> None:
    """When llm_spend already meets/exceeds the budget, enrich_document halts
    gracefully without calling the LLM or raising.
    """
    from knowledge_lake.registry import repo as registry_repo

    with Session(engine) as seed_session:
        registry_repo.record_llm_spend(seed_session, "global", test_settings.enrich.budget_usd)
        seed_session.commit()

    mock_completion = MagicMock(return_value=_mock_llm_response(VALID_PAYLOAD))
    with patch("litellm.completion", mock_completion):
        result = enrich_module.enrich_document(
            seeded["cleaned_artifact_id"],
            seeded["source_id"],
            parsed_doc=parsed_doc,
            settings=test_settings,
        )

    assert result["status"] == "skipped_budget_exceeded"
    assert result["artifact_id"] is None
    mock_completion.assert_not_called()


def test_enrich_integrity_error_on_race_is_treated_as_cache_hit(
    engine, seeded, fake_storage, parsed_doc, test_settings
) -> None:
    """Regression for WR-02: if a concurrent enrich_document() call wins the
    race and commits the enriched_document row for this synthetic_hash first,
    the resulting UNIQUE(content_hash, artifact_type) IntegrityError raised by
    this call's own insert must be caught and treated as a cache hit — never
    propagated as an unhandled exception.
    """
    from knowledge_lake.registry import repo as registry_repo

    original_create = registry_repo.create_enriched_artifact
    winner: dict = {}

    def _racing_create(session, **kwargs):
        # Simulate a concurrent writer winning the race: commit the same
        # (content_hash, artifact_type) row in a completely separate
        # session/transaction, right before this call attempts its own insert.
        if not winner:
            with Session(engine) as race_session:
                race_artifact = original_create(
                    race_session,
                    source_id=kwargs["source_id"],
                    parent_artifact_id=kwargs["parent_artifact_id"],
                    content_hash=kwargs["content_hash"],
                    metadata={"summary": "race winner"},
                    quality_score=0.5,
                )
                race_session.commit()
                winner["artifact_id"] = race_artifact.id
        return original_create(session, **kwargs)

    mock_completion = MagicMock(return_value=_mock_llm_response(VALID_PAYLOAD))
    with patch("litellm.completion", mock_completion), patch.object(
        registry_repo, "create_enriched_artifact", side_effect=_racing_create
    ):
        result = enrich_module.enrich_document(
            seeded["cleaned_artifact_id"],
            seeded["source_id"],
            parsed_doc=parsed_doc,
            settings=test_settings,
        )

    assert winner, "test setup bug: the racing insert never ran"
    assert result["status"] == "cached"
    assert result["cached"] is True
    assert result["artifact_id"] == winner["artifact_id"]


def test_retry_cost_is_accumulated_not_dropped(
    engine, seeded, fake_storage, parsed_doc, test_settings, monkeypatch
) -> None:
    """Regression for WR-03: a first attempt that returns malformed JSON is a
    real, billable Bedrock call — its cost must still be counted even though
    tenacity retries and the second attempt succeeds. cost_usd must reflect
    both attempts, not just the final one.
    """
    import tenacity

    from knowledge_lake.pipeline import enrich as enrich_module_ref

    # Zero out the retry backoff so this test doesn't sleep between attempts.
    monkeypatch.setattr(
        enrich_module_ref._call_llm_for_enrichment.retry, "wait", tenacity.wait_none()
    )

    malformed_response = _mock_llm_response({"not": "a valid enrichment payload"})
    valid_response = _mock_llm_response(VALID_PAYLOAD)
    mock_completion = MagicMock(side_effect=[malformed_response, valid_response])

    with patch("litellm.completion", mock_completion):
        result = enrich_module.enrich_document(
            seeded["cleaned_artifact_id"],
            seeded["source_id"],
            parsed_doc=parsed_doc,
            settings=test_settings,
        )

    assert result["status"] == "enriched"
    assert mock_completion.call_count == 2

    # Each mocked attempt reports the same usage (100/50 tokens), so with the
    # fallback per-1k pricing the two billable attempts must sum to exactly
    # double a single attempt's cost — never just the final attempt's cost.
    per_attempt_cost = (100 / 1000 * test_settings.enrich.fallback_cost_per_1k_input) + (
        50 / 1000 * test_settings.enrich.fallback_cost_per_1k_output
    )
    assert result["cost_usd"] == pytest.approx(per_attempt_cost * 2)


def test_enrich_title_recovered_via_registry_reconstruction_when_parsed_doc_none(
    engine, seeded, fake_storage, test_settings
) -> None:
    """Regression for CR-01: api/app.py's enrich_endpoint and cli/app.py's
    cmd_enrich no longer call enrich_document() with parsed_doc=None — they
    reconstruct a minimal ParsedDoc from the cleaned artifact's parent
    parsed_document artifact's stored metadata_ (which now carries a "title"
    key persisted by pipeline.parse.parse(), per the CR-01 fix) and pass that
    in. This test replicates that exact reconstruction and asserts the
    persisted enriched artifact's title is non-empty — i.e. the CLI/API path
    no longer silently persists title: "".
    """
    from sqlalchemy.orm import Session as _Session

    from knowledge_lake.registry import repo as registry_repo

    # Seed a parsed_document artifact with a "title" key in its metadata_,
    # exactly as pipeline.parse.parse() now persists post-CR-01-fix, then
    # point the seeded cleaned artifact's parent at it.
    with Session(engine) as seed_session:
        cleaned_artifact = registry_repo.get_artifact(seed_session, seeded["cleaned_artifact_id"])
        parsed_artifact = registry_repo.get_artifact(
            seed_session, cleaned_artifact.parent_artifact_id
        )
        parsed_artifact.metadata_ = {
            "quality_score": 0.8,
            "parser_used": "docling",
            "title": "HIPAA Security Rule Overview",
        }
        seed_session.commit()

    # Replicate exactly what enrich_endpoint / cmd_enrich now do: fetch the
    # cleaned artifact's parent parsed_document artifact and reconstruct a
    # minimal ParsedDoc from its metadata_ before calling enrich_document().
    with _Session(engine) as session:
        cleaned_artifact = registry_repo.get_artifact(session, seeded["cleaned_artifact_id"])
        parsed_artifact = registry_repo.get_artifact(session, cleaned_artifact.parent_artifact_id)
        parsed_metadata = (parsed_artifact.metadata_ if parsed_artifact else None) or {}

    reconstructed_parsed_doc = ParsedDoc(text="", sections=[], metadata=parsed_metadata)

    mock_completion = MagicMock(return_value=_mock_llm_response(VALID_PAYLOAD))
    with patch("litellm.completion", mock_completion):
        result = enrich_module.enrich_document(
            seeded["cleaned_artifact_id"],
            seeded["source_id"],
            parsed_doc=reconstructed_parsed_doc,
            settings=test_settings,
        )

    assert result["status"] == "enriched"
    with Session(engine) as check_session:
        artifact = registry_repo.get_artifact(check_session, result["artifact_id"])
        assert artifact is not None
        assert artifact.metadata_["title"] == "HIPAA Security Rule Overview"
        assert artifact.metadata_["title"] != ""


def test_llm_call_failure_is_skipped_not_raised(
    engine, seeded, fake_storage, parsed_doc, test_settings
) -> None:
    """When litellm.completion raises on every attempt, enrich_document returns
    a skipped status and does not raise.
    """
    mock_completion = MagicMock(side_effect=RuntimeError("gateway unavailable"))
    with patch("litellm.completion", mock_completion):
        result = enrich_module.enrich_document(
            seeded["cleaned_artifact_id"],
            seeded["source_id"],
            parsed_doc=parsed_doc,
            settings=test_settings,
        )

    assert result["status"] == "skipped_enrichment_failed"
    assert result["artifact_id"] is None


# ── Phase 8: Partial enrichment stubs (ENRICH-07) ────────────────────────────


@pytest.mark.xfail(strict=False, reason="Phase 8 ENRICH-07 — not yet implemented")
def test_partial_enrichment(engine, seeded, fake_storage, parsed_doc, test_settings) -> None:
    """When LiteLLM response has finish_reason='length' with truncated JSON,
    enrich_document returns status='enriched' with is_partial=True in the result dict.
    """
    # Build a mock response with finish_reason='length' and truncated JSON content
    truncated_payload = '{"summary": "truncated..."'  # intentionally malformed/truncated
    resp = MagicMock()
    resp.choices = [
        MagicMock(
            message=MagicMock(content=truncated_payload),
            finish_reason="length",
        )
    ]
    resp.usage = MagicMock(prompt_tokens=100, completion_tokens=50)

    mock_completion = MagicMock(return_value=resp)
    with patch("litellm.completion", mock_completion):
        result = enrich_module.enrich_document(
            seeded["cleaned_artifact_id"],
            seeded["source_id"],
            parsed_doc=parsed_doc,
            settings=test_settings,
        )

    assert result["status"] == "enriched"
    assert result.get("is_partial") is True


@pytest.mark.xfail(strict=False, reason="Phase 8 ENRICH-07 — not yet implemented")
def test_partial_cache_key(engine, seeded, fake_storage, parsed_doc, test_settings) -> None:
    """When finish_reason='length', the enriched artifact is stored under a
    content_hash starting with 'partial:' not the normal synthetic hash.
    """
    from sqlalchemy.orm import Session as _Session

    from knowledge_lake.registry import repo as registry_repo

    truncated_payload = '{"summary": "truncated..."'
    resp = MagicMock()
    resp.choices = [
        MagicMock(
            message=MagicMock(content=truncated_payload),
            finish_reason="length",
        )
    ]
    resp.usage = MagicMock(prompt_tokens=100, completion_tokens=50)

    mock_completion = MagicMock(return_value=resp)
    with patch("litellm.completion", mock_completion):
        result = enrich_module.enrich_document(
            seeded["cleaned_artifact_id"],
            seeded["source_id"],
            parsed_doc=parsed_doc,
            settings=test_settings,
        )

    assert result.get("artifact_id") is not None
    with _Session(engine) as check_session:
        artifact = registry_repo.get_artifact(check_session, result["artifact_id"])
        assert artifact is not None
        assert artifact.content_hash.startswith("partial:")


@pytest.mark.xfail(strict=False, reason="Phase 8 ENRICH-07 — not yet implemented")
def test_partial_not_returned_as_complete(
    engine, seeded, fake_storage, parsed_doc, test_settings
) -> None:
    """After a partial enrichment, calling enrich_document again for the same
    content returns status != 'cached' (partial is not a cache hit for complete).
    """
    truncated_payload = '{"summary": "truncated..."'
    resp_partial = MagicMock()
    resp_partial.choices = [
        MagicMock(
            message=MagicMock(content=truncated_payload),
            finish_reason="length",
        )
    ]
    resp_partial.usage = MagicMock(prompt_tokens=100, completion_tokens=50)

    resp_complete = MagicMock()
    resp_complete.choices = [MagicMock(message=MagicMock(content=json.dumps(VALID_PAYLOAD)))]
    resp_complete.usage = MagicMock(prompt_tokens=100, completion_tokens=50)

    with patch("litellm.completion", MagicMock(return_value=resp_partial)):
        enrich_module.enrich_document(
            seeded["cleaned_artifact_id"],
            seeded["source_id"],
            parsed_doc=parsed_doc,
            settings=test_settings,
        )

    with patch("litellm.completion", MagicMock(return_value=resp_complete)):
        second = enrich_module.enrich_document(
            seeded["cleaned_artifact_id"],
            seeded["source_id"],
            parsed_doc=parsed_doc,
            settings=test_settings,
        )

    assert second["status"] != "cached"
