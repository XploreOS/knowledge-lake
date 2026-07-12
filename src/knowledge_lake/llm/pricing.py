"""LiteLLM cost-tracking bootstrap and per-call cost computation (ENRICH-05).

RESEARCH.md Pitfall 1: ``litellm.completion_cost()`` raises for this project's
configured Bedrock model IDs until ``litellm.register_model()`` has been called
with explicit per-token pricing. ``bootstrap_llm_pricing`` must run before
``compute_call_cost`` is trusted for a real dollar figure.

Functions:
    bootstrap_llm_pricing — register the project's Bedrock model IDs with LiteLLM
    compute_call_cost     — compute the USD cost of a single completion() call
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from knowledge_lake.config.settings import Settings

log = structlog.get_logger(__name__)


def bootstrap_llm_pricing(settings: Settings) -> None:
    """Register the project's configured Bedrock model IDs with LiteLLM's pricing map.

    Calls litellm.register_model() once with entries for
    settings.enrich.cheap_model_bedrock_id and settings.enrich.strong_model_bedrock_id.
    Never raises — any failure is logged as a warning and swallowed, since a
    failed registration only degrades cost tracking (compute_call_cost falls
    back to a token-count estimate), never enrichment correctness.
    """
    try:
        import litellm  # noqa: PLC0415 — lazy import, avoids proxy dependency at import time

        litellm.register_model(
            {
                settings.enrich.cheap_model_bedrock_id: {
                    "input_cost_per_token": settings.enrich.cheap_model_input_cost_per_token,
                    "output_cost_per_token": settings.enrich.cheap_model_output_cost_per_token,
                    "litellm_provider": "bedrock",
                    "mode": "chat",
                },
                settings.enrich.strong_model_bedrock_id: {
                    "input_cost_per_token": settings.enrich.strong_model_input_cost_per_token,
                    "output_cost_per_token": settings.enrich.strong_model_output_cost_per_token,
                    "litellm_provider": "bedrock",
                    "mode": "chat",
                },
            }
        )
    except Exception as exc:  # noqa: BLE001 — never let pricing bootstrap block enrichment
        log.warning("llm.pricing_bootstrap_failed", error=str(exc))


def compute_call_cost(response: object, settings: Settings) -> float:
    """Compute the USD cost of a single litellm.completion() call.

    Tries litellm.completion_cost() first (accurate, requires bootstrap_llm_pricing
    to have registered the model). Falls back to a token-count-based estimate
    using settings.enrich.fallback_cost_per_1k_input/output if completion_cost
    raises for any reason.
    """
    try:
        import litellm  # noqa: PLC0415

        return float(litellm.completion_cost(completion_response=response))
    except Exception as exc:  # noqa: BLE001
        log.warning("enrich.cost_calc_failed", error=str(exc))
        usage = getattr(response, "usage", None)
        if usage is None:
            return 0.0
        prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
        completion_tokens = getattr(usage, "completion_tokens", 0) or 0
        return (
            prompt_tokens / 1000 * settings.enrich.fallback_cost_per_1k_input
        ) + (
            completion_tokens / 1000 * settings.enrich.fallback_cost_per_1k_output
        )
