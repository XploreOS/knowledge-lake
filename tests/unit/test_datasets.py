"""Tests for pipeline/datasets.py — dataset generation (DATA-01, DATA-02, DATA-03).

Uses an in-memory-SQLite-backed session (mirrors tests/unit/test_enrich.py's
engine/_patch_engine/session/seeded/fake_storage/_mock_llm_response pattern)
with knowledge_lake.registry.db.get_engine monkeypatched so generate_qa_example()
and generate_instruction_example()'s own get_session() calls resolve against the
same in-memory database.

Test coverage:
  - test_qa_generation_produces_valid_result (DATA-01)
  - test_instruction_generation_produces_valid_result (DATA-02)
  - test_dataset_examples_lineage (DATA-03)
  - test_dataset_generation_uses_distinct_budget_scope (separate from enrich "global" scope)
  - test_citation_chunk_id_never_llm_producible (AI-SPEC Common Pitfall 1)
  - test_llm_call_failure_is_skipped_not_raised (D-05 discipline)
"""

from __future__ import annotations

import inspect
import json
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import knowledge_lake.registry.db as registry_db
from knowledge_lake.config.settings import Settings


# ── Constants ─────────────────────────────────────────────────────────────────

CHUNK_TEXT = "The HIPAA Security Rule requires administrative safeguards for ePHI."

CLEANED_TEXT = "This is a comprehensive healthcare document describing the HIPAA Security Rule."

ENRICHED_METADATA = {
    "summary": "Document describing HIPAA administrative safeguards.",
    "keywords": ["hipaa", "security", "ePHI"],
    "document_type": "regulation",
    "organization": "HHS",
    "jurisdiction": "US",
    "entities": ["HHS", "ePHI"],
    "quality_score": 0.85,
}

VALID_QA_PAYLOAD = {
    "question": "What does the HIPAA Security Rule require for ePHI?",
    "answer": "The HIPAA Security Rule requires administrative safeguards to protect electronic protected health information.",
}

VALID_INSTRUCTION_PAYLOAD = {
    "instruction": "Summarize the key requirements of the HIPAA Security Rule described in this document.",
    "input": "The HIPAA Security Rule requires administrative safeguards for ePHI management.",
    "output": "The HIPAA Security Rule mandates administrative safeguards including risk analysis, training, and access controls to protect electronic protected health information.",
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
    """Route registry.db.get_session() at the generate_qa_example()/generate_instruction_example()
    call sites to the in-memory test engine.
    """
    monkeypatch.setattr(registry_db, "get_engine", lambda: engine)


@pytest.fixture()
def session(engine):
    with Session(engine) as sess:
        yield sess


@pytest.fixture()
def seeded(session):
    """Seed a Source -> raw -> parsed -> cleaned -> chunk + enriched_document chain."""
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
    # chunk artifact (for QA generation — DATA-01)
    chunk = registry_repo.create_chunk_artifact(
        session,
        source_id=source.id,
        parent_artifact_id=parsed.id,
        content_hash="chunk_h",
        storage_uri=None,
        metadata={"text": CHUNK_TEXT},
    )
    # enriched_document artifact (for instruction generation — DATA-02)
    enriched = registry_repo.create_enriched_artifact(
        session,
        source_id=source.id,
        parent_artifact_id=cleaned.id,
        content_hash="enriched_h",
        metadata=ENRICHED_METADATA,
        quality_score=0.85,
    )
    session.commit()
    return {
        "source_id": source.id,
        "cleaned_artifact_id": cleaned.id,
        "chunk_id": chunk.id,
        "enriched_document_id": enriched.id,
    }


@pytest.fixture()
def fake_storage(monkeypatch):
    """Patch StorageBackend used inside pipeline.datasets to return canned bytes."""
    import knowledge_lake.pipeline.datasets as datasets_module

    fake = MagicMock()
    fake.get_object.return_value = CLEANED_TEXT.encode("utf-8")
    monkeypatch.setattr(datasets_module, "StorageBackend", lambda *_a, **_k: fake)
    return fake


@pytest.fixture()
def test_settings() -> Settings:
    return Settings(_env_file=None)  # type: ignore[call-arg]


def _mock_llm_response(payload: dict, prompt_tokens: int = 100, completion_tokens: int = 50):
    resp = MagicMock()
    resp.choices = [MagicMock(message=MagicMock(content=json.dumps(payload)))]
    resp.usage = MagicMock(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)
    return resp


# ── Tests ─────────────────────────────────────────────────────────────────────


def test_qa_generation_produces_valid_result(
    engine, seeded, fake_storage, test_settings
) -> None:
    """DATA-01: generate_qa_example produces a valid QAPairResult, creates a
    dataset_examples row with citation_chunk_id == chunk_id (caller-assigned,
    not LLM-produced), and routes the call through the eval_model alias.
    """
    import knowledge_lake.pipeline.datasets as datasets_module
    from knowledge_lake.registry import repo as registry_repo

    mock_completion = MagicMock(return_value=_mock_llm_response(VALID_QA_PAYLOAD))
    with patch("litellm.completion", mock_completion):
        result = datasets_module.generate_qa_example(
            seeded["chunk_id"], "test-dataset", settings=test_settings
        )

    assert result["status"] == "generated"
    assert result["example_id"] is not None
    assert result["dataset_id"] is not None
    # eval_model task alias (openai/ is the wire-protocol prefix, not a provider claim)
    assert mock_completion.call_args.kwargs["model"] == "openai/eval_model"

    # Verify the dataset_examples row has citation_chunk_id == chunk_id (DATA-01)
    with Session(engine) as check_session:
        from knowledge_lake.registry.models import DatasetExample
        from sqlalchemy import select

        stmt = select(DatasetExample).where(DatasetExample.id == result["example_id"])
        row = check_session.execute(stmt).scalar_one_or_none()
        assert row is not None
        assert row.payload["citation_chunk_id"] == seeded["chunk_id"]
        assert row.source_artifact_id == seeded["chunk_id"]


def test_instruction_generation_produces_valid_result(
    engine, seeded, fake_storage, test_settings
) -> None:
    """DATA-02: generate_instruction_example produces a valid InstructionPairResult
    and routes the call through the strong_model alias.
    """
    import knowledge_lake.pipeline.datasets as datasets_module

    mock_completion = MagicMock(return_value=_mock_llm_response(VALID_INSTRUCTION_PAYLOAD))
    with patch("litellm.completion", mock_completion):
        result = datasets_module.generate_instruction_example(
            seeded["enriched_document_id"], "test-dataset-instr", settings=test_settings
        )

    assert result["status"] == "generated"
    assert result["example_id"] is not None
    # strong_model task alias (openai/ is the wire-protocol prefix)
    assert mock_completion.call_args.kwargs["model"] == "openai/strong_model"


def test_dataset_examples_lineage(
    engine, seeded, fake_storage, test_settings
) -> None:
    """DATA-03: two QA examples generated for the same dataset_name share the SAME
    dataset_id (get-or-create, not two Dataset rows), and each row's source_artifact_id
    resolves back to its originating chunk via registry_repo.get_artifact().
    """
    import knowledge_lake.pipeline.datasets as datasets_module
    from knowledge_lake.registry import repo as registry_repo
    from knowledge_lake.registry.models import DatasetExample
    from sqlalchemy import select

    # Seed a second chunk artifact so we can generate two examples
    with Session(engine) as extra_session:
        chunk2 = registry_repo.create_chunk_artifact(
            extra_session,
            source_id=seeded["source_id"],
            parent_artifact_id=seeded["chunk_id"],  # parent doesn't need to be parsed_doc for this test
            content_hash="chunk_h2",
            storage_uri=None,
            metadata={"text": "Another HIPAA chunk about technical safeguards."},
        )
        extra_session.commit()
        chunk2_id = chunk2.id

    mock_completion = MagicMock(return_value=_mock_llm_response(VALID_QA_PAYLOAD))
    with patch("litellm.completion", mock_completion):
        result1 = datasets_module.generate_qa_example(
            seeded["chunk_id"], "lineage-dataset", settings=test_settings
        )
        result2 = datasets_module.generate_qa_example(
            chunk2_id, "lineage-dataset", settings=test_settings
        )

    assert result1["status"] == "generated"
    assert result2["status"] == "generated"
    # Both examples share the SAME dataset_id (get-or-create semantics)
    assert result1["dataset_id"] == result2["dataset_id"]

    # Each source_artifact_id resolves back to a real chunk artifact
    with Session(engine) as check_session:
        for example_id, expected_chunk_id in [
            (result1["example_id"], seeded["chunk_id"]),
            (result2["example_id"], chunk2_id),
        ]:
            stmt = select(DatasetExample).where(DatasetExample.id == example_id)
            row = check_session.execute(stmt).scalar_one_or_none()
            assert row is not None
            assert row.source_artifact_id == expected_chunk_id
            # DATA-03: source_artifact_id resolves back to the originating artifact
            artifact = registry_repo.get_artifact(check_session, row.source_artifact_id)
            assert artifact is not None
            assert artifact.artifact_type == "chunk"


def test_dataset_generation_uses_distinct_budget_scope(
    engine, seeded, fake_storage, test_settings
) -> None:
    """Regression for AI-SPEC Common Pitfall 2: dataset generation must never
    share the 'global' LlmSpend scope used by enrich.py. A fully-exhausted
    'global' scope must NOT block dataset generation, which uses its own
    'dataset_generation' scope starting at 0.0.
    """
    import knowledge_lake.pipeline.datasets as datasets_module
    from knowledge_lake.registry import repo as registry_repo

    # Exhaust the enrich 'global' budget entirely
    with Session(engine) as seed_session:
        registry_repo.record_llm_spend(seed_session, "global", 9999.0)
        seed_session.commit()

    mock_completion = MagicMock(return_value=_mock_llm_response(VALID_QA_PAYLOAD))
    with patch("litellm.completion", mock_completion):
        result = datasets_module.generate_qa_example(
            seeded["chunk_id"], "budget-test-dataset", settings=test_settings
        )

    # dataset generation's own 'dataset_generation' scope starts at 0.0 → proceeds
    assert result["status"] == "generated", (
        f"Expected 'generated' but got {result['status']!r} — "
        "dataset generation incorrectly shared enrich's 'global' budget scope"
    )
    mock_completion.assert_called_once()


def test_citation_chunk_id_never_llm_producible() -> None:
    """AI-SPEC Common Pitfall 1 guardrail: QAPairResult must NOT declare a
    citation_chunk_id field — the caller assigns it programmatically from the
    already-known chunk_id, never from LLM output.
    """
    import knowledge_lake.pipeline.datasets as datasets_module

    assert "citation_chunk_id" not in datasets_module.QAPairResult.model_fields, (
        "QAPairResult must not expose citation_chunk_id as an LLM-facing field. "
        "The caller assigns it programmatically after validation (AI-SPEC Section 6 Pitfall 1)."
    )


def test_llm_call_failure_is_skipped_not_raised(
    engine, seeded, fake_storage, test_settings
) -> None:
    """D-05 discipline: when litellm.completion raises on every attempt,
    generate_qa_example returns status='skipped_generation_failed' and does
    NOT raise out of the function (never-raise discipline from enrich.py).
    """
    import knowledge_lake.pipeline.datasets as datasets_module

    mock_completion = MagicMock(side_effect=RuntimeError("gateway unavailable"))
    with patch("litellm.completion", mock_completion):
        result = datasets_module.generate_qa_example(
            seeded["chunk_id"], "fail-test-dataset", settings=test_settings
        )

    assert result["status"] == "skipped_generation_failed"
    assert result.get("example_id") is None
