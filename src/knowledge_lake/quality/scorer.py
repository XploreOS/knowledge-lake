"""Heuristic quality scorer for ParsedDoc output (PARSE-04, D-04).

Deterministic-first: always computes a weighted heuristic score. Optional
LLM spot-check fires only in the configurable gray zone (D-04).

Design:
  - compute_quality_score() — fast heuristic scorer, always runs synchronously
  - maybe_llm_spot_check()  — optional LLM refinement in the gray zone only

The LLM import is deferred to inside maybe_llm_spot_check() so tests that
do not exercise the LLM path do not require a running LiteLLM proxy.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

import structlog

from knowledge_lake.plugins.protocols import ParsedDoc

if TYPE_CHECKING:
    from knowledge_lake.config.settings import Settings

log = structlog.get_logger(__name__)


def compute_quality_score(
    parsed_doc: ParsedDoc,
    mime_type: str = "",
    settings: Optional["Settings"] = None,
) -> float:
    """Compute a heuristic quality score for a ParsedDoc (D-04, PARSE-04).

    Uses weighted heuristics with weights summing to 1.0:
      - text_length_score  (0.35): min(len(text) / 200, 1.0)
      - section_score      (0.20): min(section_count / 3, 1.0)
      - encoding_score     (0.25): 1 - unicode_replacement_char_ratio * 100
      - empty_section_score(0.20): 1 - empty_sections / total_sections

    Args:
        parsed_doc: The parsed document output from a ParserPlugin.
        mime_type:  MIME type of the source (used for debug logging only).
        settings:   Unused for pure heuristic path; reserved for future
                    per-format weight tuning.

    Returns:
        float in [0.0, 1.0] — higher is better.
    """
    text = parsed_doc.text
    text_len = len(text)
    sections = parsed_doc.sections

    # Short-circuit: truly empty document → score 0.0
    if text_len == 0 and not sections:
        log.debug(
            "quality_scorer.heuristic",
            mime_type=mime_type,
            text_len=0,
            section_count=0,
            final_score=0.0,
        )
        return 0.0

    # Heuristic 1: text length (at least 200 chars expected for a useful doc)
    text_length_score = min(text_len / 200, 1.0)

    # Heuristic 2: structural sections (at least 3 is considered well-structured)
    section_score = min(len(sections) / 3, 1.0)

    # Heuristic 3: encoding health (unicode replacement char indicates garbled text)
    if text_len > 0:
        replacement_ratio = text.count("�") / text_len
    else:
        replacement_ratio = 0.0
    encoding_score = 1.0 - min(replacement_ratio * 100, 1.0)

    # Heuristic 4: empty section ratio
    if sections:
        empty_count = sum(1 for s in sections if not s.text.strip())
        empty_section_score = 1.0 - (empty_count / len(sections))
    else:
        # No sections extracted — neutral score (structure unknown)
        empty_section_score = 0.5

    # Weighted aggregate (weights sum to 1.0)
    score = (
        text_length_score * 0.35
        + section_score * 0.20
        + encoding_score * 0.25
        + empty_section_score * 0.20
    )

    # Clamp to [0.0, 1.0] for safety against floating-point edge cases
    score = max(0.0, min(1.0, score))

    log.debug(
        "quality_scorer.heuristic",
        mime_type=mime_type,
        text_len=text_len,
        section_count=len(sections),
        text_length_score=round(text_length_score, 3),
        section_score=round(section_score, 3),
        encoding_score=round(encoding_score, 3),
        empty_section_score=round(empty_section_score, 3),
        final_score=round(score, 3),
    )
    return score


def maybe_llm_spot_check(
    parsed_doc: ParsedDoc,
    score: float,
    settings: "Settings",
) -> float:
    """Optionally refine the quality score using an LLM coherence check (D-04).

    Fires only when:
      1. settings.parse.llm_spot_check is True
      2. score falls inside settings.parse.quality_gray_zone

    Makes a single LiteLLM call via settings.litellm_url using the cheap_model
    task alias. Parses the JSON response for {score: float}. Returns the LLM
    score if successful, otherwise returns the original heuristic score unchanged.

    Args:
        parsed_doc: The parsed document (used to build the LLM prompt).
        score:      The heuristic quality score to potentially refine.
        settings:   Application settings (litellm_url, parse sub-model).

    Returns:
        float in [0.0, 1.0] — either the LLM-refined score or the original.
    """
    gray_lo, gray_hi = settings.parse.quality_gray_zone
    if not settings.parse.llm_spot_check or not (gray_lo <= score <= gray_hi):
        return score

    log.debug(
        "quality_scorer.llm_spot_check_triggered",
        score=score,
        gray_zone=(gray_lo, gray_hi),
    )

    try:
        import json as _json
        import litellm  # lazy import — avoids proxy dependency in unit tests

        # Sample up to 1000 chars of document text for the coherence check
        sample_text = parsed_doc.text[:1000]
        prompt = (
            "Rate the coherence and readability of the following extracted document text "
            "on a scale from 0.0 (incoherent/garbled) to 1.0 (clear/well-structured). "
            "Respond ONLY with valid JSON in the form {\"score\": <float>}.\n\n"
            f"Text:\n{sample_text}"
        )

        response = litellm.completion(
            model="cheap_model",
            messages=[{"role": "user", "content": prompt}],
            api_base=settings.litellm_url,
            max_tokens=32,
        )
        content = response.choices[0].message.content or ""
        parsed = _json.loads(content)
        llm_score = float(parsed["score"])
        llm_score = max(0.0, min(1.0, llm_score))
        log.debug("quality_scorer.llm_spot_check_result", llm_score=llm_score)
        return llm_score

    except Exception as exc:
        log.warning(
            "quality_scorer.llm_spot_check_failed",
            error=str(exc),
            original_score=score,
        )
        return score
