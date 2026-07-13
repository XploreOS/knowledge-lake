"""Deterministic anti-bot / CAPTCHA challenge-page detection (Finding 3).

Crawlers occasionally receive an anti-bot interstitial (Cloudflare "Just a
moment...", a CAPTCHA gate, an Akamai/Incapsula block page) instead of the real
document. These pages often score ABOVE the heuristic quality threshold — they
have plenty of text and clean encoding — so the parse quality gate lets them
through and they poison the chunk/embed/index stages (data tampering, T-QF-01).

``is_challenge_page`` is a pure, deterministic, LLM-free phrase filter. It scans
text once against a curated list of known challenge markers and returns a
human-readable reason for the first match, or None for ordinary document text.

SINGLE EXTENSION POINT: ``_CHALLENGE_PATTERNS`` below is the only thing to edit
to cover a new anti-bot provider — append a ``(compiled_regex, reason)`` tuple.
Every pattern is compiled case-insensitively. Keep patterns specific enough that
they never match legitimate domain prose (e.g. a medical article that happens to
mention "cookies" must NOT be flagged — that is why the markers are full
challenge phrases, not single words).
"""

from __future__ import annotations

import re

# (compiled case-insensitive regex, human-readable reason) — the ONLY extension
# point. Append a tuple here to cover a new provider/marker.
_CHALLENGE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Generic human-verification interstitials
    (re.compile(r"confirm you are human", re.IGNORECASE), "human-verification prompt"),
    (re.compile(r"verify you are (?:not a bot|human)", re.IGNORECASE), "bot-verification prompt"),
    (
        re.compile(r"complete the security check before continuing", re.IGNORECASE),
        "security-check interstitial",
    ),
    (
        re.compile(r"enable javascript and cookies to continue", re.IGNORECASE),
        "JavaScript/cookies-required interstitial",
    ),
    # Cloudflare
    (re.compile(r"just a moment\.\.\.", re.IGNORECASE), "Cloudflare 'Just a moment' challenge"),
    (
        re.compile(r"checking your browser before accessing", re.IGNORECASE),
        "Cloudflare browser-check interstitial",
    ),
    (re.compile(r"attention required", re.IGNORECASE), "Cloudflare 'Attention Required' block"),
    (re.compile(r"cf-browser-verification", re.IGNORECASE), "Cloudflare cf-browser-verification"),
    (re.compile(r"cf-challenge", re.IGNORECASE), "Cloudflare cf-challenge"),
    # Akamai
    (re.compile(r"akamaighost", re.IGNORECASE), "Akamai bot block page"),
    (re.compile(r"access denied.{0,40}reference #", re.IGNORECASE | re.DOTALL), "Akamai access-denied reference"),
    # Incapsula / Imperva
    (re.compile(r"incapsula incident id", re.IGNORECASE), "Incapsula/Imperva incident block"),
    (re.compile(r"_incapsula_resource", re.IGNORECASE), "Incapsula/Imperva challenge resource"),
]


def is_challenge_page(text: str) -> str | None:
    """Return a reason string if *text* is an anti-bot/challenge page, else None.

    Deterministic and pure: no LLM call, no network I/O. Scans *text* once
    against ``_CHALLENGE_PATTERNS`` and returns the first matched marker's
    descriptive reason. Ordinary document text returns None.

    Args:
        text: The parsed document text to inspect.

    Returns:
        A human-readable reason (e.g. "Cloudflare 'Just a moment' challenge")
        when a known challenge marker is present, otherwise None.
    """
    if not text:
        return None
    for pattern, reason in _CHALLENGE_PATTERNS:
        if pattern.search(text):
            return reason
    return None
