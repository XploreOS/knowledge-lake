"""Zero-I/O constants and helpers for the quality predicate package (QUAL-01).

Imports only ``datatrove``'s static constants (never its tokenizer factory —
see RESEARCH.md Pitfall 1: ``datatrove.utils.text.split_into_words()`` raises
``AttributeError`` in this environment because it lazily probes for a spaCy
backend via ``importlib.metadata``) and instantiates its own ``tiktoken``
encoder rather than importing ``pipeline.chunk.token_count`` (which would pull
in ``registry.db``/``storage.s3`` at module scope and violate this package's
zero-I/O contract). This duplication-for-isolation idiom mirrors the
already-established precedent in ``crawl.py``'s ``_GATE_BOILERPLATE_PATTERNS``
(Phase 18, GATE-01).
"""

from __future__ import annotations

import re

import tiktoken as _tiktoken
from datatrove.pipeline.filters.gopher_quality_filter import STOP_WORDS
from datatrove.utils.text import TERMINAL_PUNCTUATION

# Static DataTrove constants — safe, cheap, zero-I/O imports (verified in
# RESEARCH.md: importing these does not invoke the tokenizer factory that
# crashes in this environment).
STOP_WORDS_SET = frozenset(STOP_WORDS)
TERMINAL_PUNCTUATION_SET = frozenset(TERMINAL_PUNCTUATION)

# Detects bare URLs and markdown-style links `[text](url)`.
_LINK_PATTERN = re.compile(r"https?://\S+|\[[^\]]*\]\([^)]*\)")

# Module-level tiktoken encoder — instantiated once, mirroring pipeline/chunk.py's
# idiom exactly. NEVER import token_count from pipeline.chunk: that module
# imports registry.db/storage.s3 at module scope, which would violate QUAL-01's
# zero-I/O contract transitively even though token_count() itself is pure.
_encoder = _tiktoken.get_encoding("cl100k_base")


def token_count(text: str) -> int:
    """Return the number of cl100k_base tokens in ``text``.

    Duplicated from pipeline/chunk.py's identical function (not imported) so
    that pipeline.quality never transitively pulls in registry.db/storage.s3.
    """
    return len(_encoder.encode(text))
