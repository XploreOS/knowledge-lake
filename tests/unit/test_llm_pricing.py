"""Regression tests for KL-02 — LLM cost attribution must reflect real spend.

.planning/E2E-GAP-ANALYSIS.md KL-02: bootstrap_llm_pricing() registered prices
keyed by Bedrock model ID, but every call goes through the LiteLLM proxy and
returns response.model as the task alias — the keys never matched, so
litellm.completion_cost() raised on every call and compute_call_cost()
silently fell back to a flat estimate that understated real spend by 2.4x-9x.

A live proxy probe established response._hidden_params["response_cost"] as
the proxy's own authoritative, correctly-computed cost. These tests cover the
resulting ordered fallback chain in compute_call_cost():
    1. response._hidden_params["response_cost"] when present and > 0
    2. litellm.completion_cost(completion_response=response)
    3. flat per-1k-token estimate (last resort, logged at warning)

and that bootstrap_llm_pricing() registers all three alias keys
(cheap_model, strong_model, eval_model) rather than Bedrock model IDs.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest


@pytest.fixture()
def settings():
    from knowledge_lake.config.settings import Settings

    return Settings(_env_file=None)  # type: ignore[call-arg]


def _make_response(*, hidden_params=None, usage=None):
    """Build a minimal fake litellm ModelResponse-shaped object."""
    resp = SimpleNamespace()
    if hidden_params is not None:
        resp._hidden_params = hidden_params
    if usage is not None:
        resp.usage = usage
    return resp


class TestComputeCallCostPreferResponseCost:
    """Fallback level 1: response._hidden_params["response_cost"] is authoritative."""

    def test_prefers_hidden_params_response_cost_when_present(self, settings):
        from knowledge_lake.llm.pricing import compute_call_cost

        response = _make_response(hidden_params={"response_cost": 3.74e-05})

        # litellm.completion_cost must NOT even be consulted when response_cost
        # is present and > 0 — patch it to raise, proving it was never called.
        with patch("litellm.completion_cost", side_effect=AssertionError("should not be called")):
            cost = compute_call_cost(response, settings)

        assert cost == pytest.approx(3.74e-05)

    def test_ignores_hidden_params_when_zero(self, settings):
        """response_cost == 0.0 is not trusted (proxy sometimes reports 0 for
        unpriced models) — falls through to the next level."""
        from knowledge_lake.llm.pricing import compute_call_cost

        response = _make_response(hidden_params={"response_cost": 0.0})

        with patch("litellm.completion_cost", return_value=2.72e-05) as mock_cost:
            cost = compute_call_cost(response, settings)

        mock_cost.assert_called_once()
        assert cost == pytest.approx(2.72e-05)

    def test_ignores_missing_hidden_params(self, settings):
        """No _hidden_params attribute at all falls through cleanly (never raises)."""
        from knowledge_lake.llm.pricing import compute_call_cost

        response = _make_response()

        with patch("litellm.completion_cost", return_value=1.0e-05) as mock_cost:
            cost = compute_call_cost(response, settings)

        mock_cost.assert_called_once()
        assert cost == pytest.approx(1.0e-05)


class TestComputeCallCostFallsBackToCompletionCost:
    """Fallback level 2: litellm.completion_cost() once alias names are registered."""

    def test_falls_back_to_completion_cost_when_response_cost_absent(self, settings):
        from knowledge_lake.llm.pricing import compute_call_cost

        response = _make_response(hidden_params={})

        with patch("litellm.completion_cost", return_value=0.0048) as mock_cost:
            cost = compute_call_cost(response, settings)

        mock_cost.assert_called_once_with(completion_response=response)
        assert cost == pytest.approx(0.0048)


class TestComputeCallCostFlatEstimateFallback:
    """Fallback level 3: flat per-1k-token estimate, last resort, warns."""

    def test_falls_back_to_flat_estimate_when_both_unavailable(self, settings):
        from knowledge_lake.llm.pricing import compute_call_cost

        usage = SimpleNamespace(prompt_tokens=1000, completion_tokens=1000)
        response = _make_response(usage=usage)  # no _hidden_params at all

        with patch("litellm.completion_cost", side_effect=RuntimeError("not mapped yet")):
            cost = compute_call_cost(response, settings)

        expected = (
            1000 / 1000 * settings.enrich.fallback_cost_per_1k_input
            + 1000 / 1000 * settings.enrich.fallback_cost_per_1k_output
        )
        assert cost == pytest.approx(expected)

    def test_flat_estimate_logs_warning_not_bare_cost_calc_failed(self, settings):
        """KL-02 fix design: warn explicitly that cost is under-estimated,
        not the old bare 'enrich.cost_calc_failed' with no context.

        Mirrors tests/unit/test_route.py's pattern of patching the
        module-level `log` object directly and capturing calls, rather than
        reconfiguring the global structlog processor chain.
        """
        import knowledge_lake.llm.pricing as pricing_module

        usage = SimpleNamespace(prompt_tokens=500, completion_tokens=500)
        response = _make_response(usage=usage)

        log_events: list[dict] = []

        with (
            patch.object(pricing_module, "log") as mock_log,
            patch("litellm.completion_cost", side_effect=RuntimeError("not mapped yet")),
        ):
            mock_log.warning.side_effect = lambda event, **kw: log_events.append({"event": event, **kw})
            pricing_module.compute_call_cost(response, settings)

        warning_events = [e for e in log_events if e["event"] == "enrich.cost_calc_fallback_estimate"]
        assert warning_events, f"Expected enrich.cost_calc_fallback_estimate warning, got events: {log_events}"
        note = warning_events[0].get("note", "")
        assert "under" in note, f"Expected under-estimation notice in warning note, got: {note!r}"

    def test_never_raises_when_no_usage_and_no_response_cost(self, settings):
        """D-05: pricing must never raise out of compute_call_cost — a pricing
        failure must never break enrichment."""
        from knowledge_lake.llm.pricing import compute_call_cost

        response = _make_response()  # no _hidden_params, no usage

        with patch("litellm.completion_cost", side_effect=RuntimeError("not mapped yet")):
            cost = compute_call_cost(response, settings)

        assert cost == 0.0


class TestBootstrapLlmPricingRegistersAliasKeys:
    """bootstrap_llm_pricing() must register cheap_model/strong_model/eval_model
    alias names — NOT Bedrock model IDs — since the proxy returns the alias
    in response.model, not the backend model ID (KL-02 root cause)."""

    def test_registers_all_three_alias_keys(self, settings):
        from knowledge_lake.llm.pricing import bootstrap_llm_pricing

        with patch("litellm.register_model") as mock_register:
            bootstrap_llm_pricing(settings)

        mock_register.assert_called_once()
        (registered,), _kwargs = mock_register.call_args
        assert set(registered.keys()) == {"cheap_model", "strong_model", "eval_model"}, (
            f"Expected exactly the three task aliases, got {list(registered.keys())}"
        )
        for alias, entry in registered.items():
            assert entry["litellm_provider"] == "openai", (
                f"{alias} must be registered under litellm_provider='openai' "
                "(the wire protocol the proxy speaks), got {entry['litellm_provider']!r}"
            )
            assert entry["input_cost_per_token"] > 0
            assert entry["output_cost_per_token"] > 0

    def test_eval_model_price_mirrors_strong_model(self, settings):
        """eval_model previously had no registered price at all (KL-02).
        Its defaults mirror strong_model since both map to the same Sonnet
        backend per infra/litellm/config.yaml."""
        assert settings.enrich.eval_model_input_cost_per_token == pytest.approx(
            settings.enrich.strong_model_input_cost_per_token
        )
        assert settings.enrich.eval_model_output_cost_per_token == pytest.approx(
            settings.enrich.strong_model_output_cost_per_token
        )

    def test_never_raises_on_registration_failure(self, settings):
        """D-05: pricing bootstrap must never raise — a failure only degrades
        cost tracking, never enrichment correctness."""
        from knowledge_lake.llm.pricing import bootstrap_llm_pricing

        with patch("litellm.register_model", side_effect=RuntimeError("proxy unreachable")):
            bootstrap_llm_pricing(settings)  # must not raise
