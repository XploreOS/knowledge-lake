"""LiteLLM cost-tracking bootstrap and per-call cost computation (ENRICH-05).

KL-02 (E2E-GAP-ANALYSIS.md): bootstrap_llm_pricing() used to register prices
keyed by Bedrock model ID, but every call goes through the LiteLLM proxy and
comes back with response.model == the task alias (e.g. "cheap_model"). The
keys never matched, so litellm.completion_cost() raised on every call and
compute_call_cost() silently fell back to a flat estimate that under-priced
real spend by 2.4x-9x -- making budget_usd mean something other than what it
says.

A live proxy probe established that response._hidden_params["response_cost"]
is already the authoritative, correctly-computed cost (derived by the proxy
from the real backend model's pricing) -- it needs no per-alias maintenance
and covers eval_model and any future alias for free. compute_call_cost() now
prefers it.

Functions:
    bootstrap_llm_pricing — register the project's alias names with LiteLLM
    compute_call_cost     — compute the USD cost of a single completion() call
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from knowledge_lake.config.settings import Settings

log = structlog.get_logger(__name__)


def bootstrap_llm_pricing(settings: Settings) -> None:
    """Register the project's LiteLLM task aliases with LiteLLM's pricing map.

    Calls litellm.register_model() once with entries for the alias names
    actually sent as `model=` to the proxy ("cheap_model", "strong_model",
    "eval_model") -- not the underlying Bedrock model IDs, which the proxy
    never echoes back in response.model. Registered under
    litellm_provider="openai" (the wire protocol the proxy speaks).

    This is a fallback path only (see compute_call_cost): the proxy's own
    response._hidden_params["response_cost"] is authoritative and preferred
    when present. Registering the alias keys makes litellm.completion_cost()
    resolve as a second-line fallback instead of raising on every call.

    Never raises — any failure is logged as a warning and swallowed, since a
    failed registration only degrades cost tracking (compute_call_cost falls
    back further, to a token-count estimate), never enrichment correctness
    (D-05: pricing must never break enrichment).
    """
    try:
        import litellm  # noqa: PLC0415 — lazy import, avoids proxy dependency at import time

        litellm.register_model(
            {
                "cheap_model": {
                    "input_cost_per_token": settings.enrich.cheap_model_input_cost_per_token,
                    "output_cost_per_token": settings.enrich.cheap_model_output_cost_per_token,
                    "litellm_provider": "openai",
                    "mode": "chat",
                },
                "strong_model": {
                    "input_cost_per_token": settings.enrich.strong_model_input_cost_per_token,
                    "output_cost_per_token": settings.enrich.strong_model_output_cost_per_token,
                    "litellm_provider": "openai",
                    "mode": "chat",
                },
                "eval_model": {
                    "input_cost_per_token": settings.enrich.eval_model_input_cost_per_token,
                    "output_cost_per_token": settings.enrich.eval_model_output_cost_per_token,
                    "litellm_provider": "openai",
                    "mode": "chat",
                },
            }
        )
    except Exception as exc:  # noqa: BLE001 — never let pricing bootstrap block enrichment
        log.warning("llm.pricing_bootstrap_failed", error=str(exc))


def compute_call_cost(response: object, settings: Settings) -> float:
    """Compute the USD cost of a single litellm.completion() call.

    Ordered fallback chain (KL-02):
    1. response._hidden_params["response_cost"] — the LiteLLM proxy's own,
       authoritative cost, computed server-side from the real backend
       model's pricing. Used whenever present and > 0.
    2. litellm.completion_cost(completion_response=response) — resolves once
       bootstrap_llm_pricing() has registered the alias names.
    3. A flat token-count estimate from settings.enrich.fallback_cost_per_1k_*
       — last resort. Logged at WARNING with an explicit under-estimation
       notice, since this path silently degrades budget-gate accuracy.

    Never raises (D-05: pricing must never break enrichment) — any exception
    while probing a fallback level falls through to the next one.
    """
    hidden_params = getattr(response, "_hidden_params", None)
    if isinstance(hidden_params, dict):
        response_cost = hidden_params.get("response_cost")
        if response_cost is not None:
            try:
                cost = float(response_cost)
            except (TypeError, ValueError):
                cost = 0.0
            if cost > 0:
                return cost

    try:
        import litellm  # noqa: PLC0415

        return float(litellm.completion_cost(completion_response=response))
    except Exception as exc:  # noqa: BLE001
        usage = getattr(response, "usage", None)
        if usage is None:
            log.warning(
                "enrich.cost_calc_failed",
                error=str(exc),
                note="no response_cost and no usage — cost under-estimated as $0.00",
            )
            return 0.0
        prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
        completion_tokens = getattr(usage, "completion_tokens", 0) or 0
        fallback_cost = (
            prompt_tokens / 1000 * settings.enrich.fallback_cost_per_1k_input
        ) + (
            completion_tokens / 1000 * settings.enrich.fallback_cost_per_1k_output
        )
        log.warning(
            "enrich.cost_calc_fallback_estimate",
            error=str(exc),
            estimated_cost=fallback_cost,
            note="using flat per-1k-token estimate — real spend may be understated",
        )
        return fallback_cost
