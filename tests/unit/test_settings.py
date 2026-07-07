"""
Tests for knowledge_lake.config.settings (FOUND-02).

Behavior under test:
  - Defaults load with no env set
  - Nested StorageSettings loads from KLAKE_STORAGE__* env vars
  - KLAKE_EMBEDDER=litellm overrides the default (env precedence)
  - Invalid types raise a validation error at construction
  - get_settings() returns a cached Settings instance
  - Only knowledge_lake.config.settings reads env vars (no os.getenv sprinkles)
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest


class TestSettingsDefaults:
    """Settings loads sensible defaults with empty environment."""

    def test_default_database_url_is_postgresql(self) -> None:
        from knowledge_lake.config.settings import Settings

        s = Settings(_env_file=None)  # type: ignore[call-arg]
        assert s.database_url.startswith("postgresql+psycopg://")

    def test_default_qdrant_url(self) -> None:
        from knowledge_lake.config.settings import Settings

        s = Settings(_env_file=None)  # type: ignore[call-arg]
        assert s.qdrant_url.startswith("http://")

    def test_default_litellm_url(self) -> None:
        from knowledge_lake.config.settings import Settings

        s = Settings(_env_file=None)  # type: ignore[call-arg]
        assert s.litellm_url.startswith("http://")

    def test_default_embedder_is_local(self) -> None:
        from knowledge_lake.config.settings import Settings

        s = Settings(_env_file=None)  # type: ignore[call-arg]
        assert s.embedder == "local"

    def test_default_parser_is_docling(self) -> None:
        from knowledge_lake.config.settings import Settings

        s = Settings(_env_file=None)  # type: ignore[call-arg]
        assert s.parser == "docling"

    def test_default_vectorstore_is_qdrant(self) -> None:
        from knowledge_lake.config.settings import Settings

        s = Settings(_env_file=None)  # type: ignore[call-arg]
        assert s.vectorstore == "qdrant"

    def test_default_storage_has_no_credentials(self) -> None:
        from knowledge_lake.config.settings import Settings

        s = Settings(_env_file=None)  # type: ignore[call-arg]
        # dev-safe defaults: endpoint and credentials are optional (None)
        assert s.storage.access_key_id is None
        assert s.storage.secret_access_key is None

    def test_default_storage_has_bucket_name(self) -> None:
        from knowledge_lake.config.settings import Settings

        s = Settings(_env_file=None)  # type: ignore[call-arg]
        assert isinstance(s.storage.bucket, str) and len(s.storage.bucket) > 0


class TestNestedStorageSettings:
    """Nested StorageSettings loads from KLAKE_STORAGE__* via env_nested_delimiter."""

    def test_storage_endpoint_url_from_env(self) -> None:
        from knowledge_lake.config.settings import Settings

        env = {"KLAKE_STORAGE__ENDPOINT_URL": "http://minio-test:9000"}
        with patch.dict(os.environ, env, clear=False):
            s = Settings(_env_file=None)  # type: ignore[call-arg]
        assert s.storage.endpoint_url == "http://minio-test:9000"

    def test_storage_bucket_from_env(self) -> None:
        from knowledge_lake.config.settings import Settings

        env = {"KLAKE_STORAGE__BUCKET": "my-test-bucket"}
        with patch.dict(os.environ, env, clear=False):
            s = Settings(_env_file=None)  # type: ignore[call-arg]
        assert s.storage.bucket == "my-test-bucket"

    def test_storage_credentials_from_env(self) -> None:
        from knowledge_lake.config.settings import Settings

        env = {
            "KLAKE_STORAGE__ACCESS_KEY_ID": "test-access-key",
            "KLAKE_STORAGE__SECRET_ACCESS_KEY": "test-secret-key",
        }
        with patch.dict(os.environ, env, clear=False):
            s = Settings(_env_file=None)  # type: ignore[call-arg]
        assert s.storage.access_key_id == "test-access-key"
        assert s.storage.secret_access_key == "test-secret-key"

    def test_storage_region_from_env(self) -> None:
        from knowledge_lake.config.settings import Settings

        env = {"KLAKE_STORAGE__REGION": "eu-west-1"}
        with patch.dict(os.environ, env, clear=False):
            s = Settings(_env_file=None)  # type: ignore[call-arg]
        assert s.storage.region == "eu-west-1"


class TestEnvPrecedence:
    """Env vars override defaults (env > .env > defaults)."""

    def test_klake_embedder_env_overrides_default(self) -> None:
        from knowledge_lake.config.settings import Settings

        env = {"KLAKE_EMBEDDER": "litellm"}
        with patch.dict(os.environ, env, clear=False):
            s = Settings(_env_file=None)  # type: ignore[call-arg]
        assert s.embedder == "litellm"

    def test_klake_database_url_env_overrides_default(self) -> None:
        from knowledge_lake.config.settings import Settings

        custom_url = "postgresql+psycopg://user:pass@myhost:5432/mydb"
        env = {"KLAKE_DATABASE_URL": custom_url}
        with patch.dict(os.environ, env, clear=False):
            s = Settings(_env_file=None)  # type: ignore[call-arg]
        assert s.database_url == custom_url

    def test_klake_parser_env_overrides_default(self) -> None:
        from knowledge_lake.config.settings import Settings

        env = {"KLAKE_PARSER": "unstructured"}
        with patch.dict(os.environ, env, clear=False):
            s = Settings(_env_file=None)  # type: ignore[call-arg]
        assert s.parser == "unstructured"


class TestEnrichAndIndexSettings:
    """EnrichSettings/IndexSettings load with correct defaults and env overrides."""

    def test_default_enrich_budget_usd(self) -> None:
        from knowledge_lake.config.settings import Settings

        s = Settings(_env_file=None)  # type: ignore[call-arg]
        assert s.enrich.budget_usd == 5.0

    def test_default_enrich_prompt_version(self) -> None:
        from knowledge_lake.config.settings import Settings

        s = Settings(_env_file=None)  # type: ignore[call-arg]
        assert s.enrich.prompt_version == "v1"

    def test_default_index_collection_alias(self) -> None:
        from knowledge_lake.config.settings import Settings

        s = Settings(_env_file=None)  # type: ignore[call-arg]
        assert s.index.collection_alias == "klake_chunks"

    def test_enrich_budget_usd_env_override(self) -> None:
        from knowledge_lake.config.settings import Settings

        env = {"KLAKE_ENRICH__BUDGET_USD": "10.5"}
        with patch.dict(os.environ, env, clear=False):
            s = Settings(_env_file=None)  # type: ignore[call-arg]
        assert s.enrich.budget_usd == 10.5


class TestGetSettings:
    """get_settings() returns a validated Settings instance (cached singleton)."""

    def test_get_settings_returns_settings_instance(self) -> None:
        from knowledge_lake.config.settings import Settings, get_settings

        s = get_settings()
        assert isinstance(s, Settings)

    def test_get_settings_uses_klake_prefix(self) -> None:
        """Verify the prefix is KLAKE_ — any unknown env var without prefix is ignored."""
        from knowledge_lake.config.settings import get_settings

        env = {"DATABASE_URL": "postgresql+psycopg://other:other@other:5432/other"}
        with patch.dict(os.environ, env, clear=False):
            s = get_settings()
        # The unprefixed DATABASE_URL must not override the KLAKE_-prefixed setting
        assert "other@other" not in s.database_url


class TestBedrockPricingIdsMatchLiteLLMConfig:
    """Regression for WR-01: the Bedrock IDs registered for cost tracking must
    exactly match the model IDs infra/litellm/config.yaml actually configures
    for the cheap_model/strong_model task aliases — otherwise
    litellm.completion_cost() silently fails to resolve pricing and
    compute_call_cost() falls back to the coarse estimate for every call.
    """

    @staticmethod
    def _config_path() -> "Path":
        from pathlib import Path

        return Path(__file__).parent.parent.parent / "infra" / "litellm" / "config.yaml"

    def test_cheap_and_strong_model_ids_match_config_yaml(self) -> None:
        yaml = pytest.importorskip("yaml")
        from knowledge_lake.config.settings import Settings

        config_path = self._config_path()
        assert config_path.exists(), f"infra/litellm/config.yaml not found at {config_path}"
        config = yaml.safe_load(config_path.read_text())

        model_by_name = {entry["model_name"]: entry["litellm_params"]["model"] for entry in config["model_list"]}

        s = Settings(_env_file=None)  # type: ignore[call-arg]
        assert s.enrich.cheap_model_bedrock_id == model_by_name["cheap_model"], (
            "settings.enrich.cheap_model_bedrock_id has drifted from "
            "infra/litellm/config.yaml's cheap_model mapping (WR-01)"
        )
        assert s.enrich.strong_model_bedrock_id == model_by_name["strong_model"], (
            "settings.enrich.strong_model_bedrock_id has drifted from "
            "infra/litellm/config.yaml's strong_model mapping (WR-01)"
        )


class TestDomainSettings:
    """DomainSettings nested model loads with correct defaults and env overrides (DOMAIN-01)."""

    def test_default_domain_name_is_none(self) -> None:
        from knowledge_lake.config.settings import Settings

        s = Settings(_env_file=None)  # type: ignore[call-arg]
        assert s.domain.domain_name is None

    def test_default_domains_root_is_domains(self) -> None:
        from knowledge_lake.config.settings import Settings

        s = Settings(_env_file=None)  # type: ignore[call-arg]
        assert s.domain.domains_root == "domains"

    def test_domain_name_from_env(self) -> None:
        import os
        from unittest.mock import patch as _patch

        from knowledge_lake.config.settings import Settings

        env = {"KLAKE_DOMAIN__DOMAIN_NAME": "healthcare"}
        with _patch.dict(os.environ, env, clear=False):
            s = Settings(_env_file=None)  # type: ignore[call-arg]
        assert s.domain.domain_name == "healthcare"

    def test_domains_root_from_env(self) -> None:
        import os
        from unittest.mock import patch as _patch

        from knowledge_lake.config.settings import Settings

        env = {"KLAKE_DOMAIN__DOMAINS_ROOT": "/custom/domains"}
        with _patch.dict(os.environ, env, clear=False):
            s = Settings(_env_file=None)  # type: ignore[call-arg]
        assert s.domain.domains_root == "/custom/domains"

    def test_domain_settings_class_exists(self) -> None:
        from knowledge_lake.config.settings import DomainSettings

        ds = DomainSettings()
        assert ds.domain_name is None
        assert ds.domains_root == "domains"
