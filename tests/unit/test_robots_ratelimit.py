"""
Unit tests for robots.txt parsing and three-tier rate-limit resolver (INGEST-09, D-12).

Tests verify:
  - resolve_delay: four-permutation table test covering all three tiers
  - robots.py: Protego-backed parsing of Disallow rules and Crawl-delay extraction
  - Per-host limiter keyed on registrable domain via tldextract
"""

from __future__ import annotations

import pytest


# ── Three-tier rate-limit resolver (D-12) ─────────────────────────────────────


class TestResolveDelay:
    """resolve_delay returns the strictest applicable delay per D-12 tier order.

    Tier 1: Source.config['rate_limit_seconds'] (per-source override)
    Tier 2: robots.txt Crawl-delay (site-wide signal)
    Tier 3: Global default from CrawlSettings.rate_limit_seconds
    """

    def test_tier1_source_config_overrides_all(self):
        """Source config rate_limit_seconds takes priority over robots and global."""
        from knowledge_lake.crawl.ratelimit import resolve_delay

        result = resolve_delay(
            source_config={"rate_limit_seconds": 5},
            robots_crawl_delay=2.0,
            global_default=1.0,
        )
        assert result == 5.0

    def test_tier2_robots_delay_when_no_source_config(self):
        """Robots Crawl-delay used when source config has no rate_limit_seconds."""
        from knowledge_lake.crawl.ratelimit import resolve_delay

        result = resolve_delay(
            source_config=None,
            robots_crawl_delay=2.0,
            global_default=1.0,
        )
        assert result == 2.0

    def test_tier3_global_default_when_nothing_else(self):
        """Global default used when no source config and no robots Crawl-delay."""
        from knowledge_lake.crawl.ratelimit import resolve_delay

        result = resolve_delay(
            source_config=None,
            robots_crawl_delay=None,
            global_default=1.0,
        )
        assert result == 1.0

    def test_tier3_global_default_with_empty_source_config(self):
        """Empty source config (no rate_limit_seconds key) falls through to tier 3."""
        from knowledge_lake.crawl.ratelimit import resolve_delay

        result = resolve_delay(
            source_config={},
            robots_crawl_delay=None,
            global_default=1.0,
        )
        assert result == 1.0

    def test_source_config_float_conversion(self):
        """Source config value is converted to float."""
        from knowledge_lake.crawl.ratelimit import resolve_delay

        result = resolve_delay(
            source_config={"rate_limit_seconds": 3},
            robots_crawl_delay=None,
            global_default=1.0,
        )
        assert isinstance(result, float)
        assert result == 3.0

    @pytest.mark.xfail(strict=False, reason="Phase 8 CRAWL-01 — not yet implemented")
    def test_rate_limit_rps_tier1(self):
        """resolve_delay({'rate_limit_rps': 2.0}, None, 1.0) returns 0.5."""
        from knowledge_lake.crawl.ratelimit import resolve_delay

        result = resolve_delay({"rate_limit_rps": 2.0}, None, 1.0)
        assert result == pytest.approx(0.5)

    @pytest.mark.xfail(strict=False, reason="Phase 8 CRAWL-01 — not yet implemented")
    def test_backoff_extra_raises_floor(self):
        """resolve_delay({}, None, 1.0, backoff_extra=3.0) returns >= 1.0 + 3.0."""
        from knowledge_lake.crawl.ratelimit import resolve_delay

        result = resolve_delay({}, None, 1.0, backoff_extra=3.0)
        assert result >= 4.0


# ── Robots.txt parsing (Protego-backed, T-02-06) ─────────────────────────────


ROBOTS_FIXTURE = """\
User-agent: *
Disallow: /private/
Disallow: /admin/
Crawl-delay: 3

User-agent: Googlebot
Disallow: /secret/
Crawl-delay: 5
"""


class TestRobotsPolicy:
    """RobotsPolicy wraps Protego for is_allowed and crawl_delay extraction."""

    def test_disallow_private_path(self):
        """Pages under /private/ are disallowed."""
        from knowledge_lake.crawl.robots import RobotsPolicy

        policy = RobotsPolicy.from_robots_txt(ROBOTS_FIXTURE)
        assert policy.is_allowed("/private/x") is False

    def test_disallow_admin_path(self):
        """Pages under /admin/ are disallowed."""
        from knowledge_lake.crawl.robots import RobotsPolicy

        policy = RobotsPolicy.from_robots_txt(ROBOTS_FIXTURE)
        assert policy.is_allowed("/admin/dashboard") is False

    def test_allow_public_path(self):
        """Pages not matching any Disallow rule are allowed."""
        from knowledge_lake.crawl.robots import RobotsPolicy

        policy = RobotsPolicy.from_robots_txt(ROBOTS_FIXTURE)
        assert policy.is_allowed("/public/y") is True

    def test_allow_open_path(self):
        """Root-level paths are allowed when not disallowed."""
        from knowledge_lake.crawl.robots import RobotsPolicy

        policy = RobotsPolicy.from_robots_txt(ROBOTS_FIXTURE)
        assert policy.is_allowed("/open") is True

    def test_crawl_delay_default_agent(self):
        """Crawl-delay for * user agent is extracted correctly."""
        from knowledge_lake.crawl.robots import RobotsPolicy

        policy = RobotsPolicy.from_robots_txt(ROBOTS_FIXTURE)
        delay = policy.crawl_delay()
        assert delay == 3.0

    def test_crawl_delay_specific_agent(self):
        """Crawl-delay for a specific user agent is extracted correctly."""
        from knowledge_lake.crawl.robots import RobotsPolicy

        policy = RobotsPolicy.from_robots_txt(ROBOTS_FIXTURE)
        delay = policy.crawl_delay(user_agent="Googlebot")
        assert delay == 5.0

    def test_crawl_delay_none_when_absent(self):
        """Returns None when no Crawl-delay directive is present."""
        from knowledge_lake.crawl.robots import RobotsPolicy

        robots_no_delay = "User-agent: *\nDisallow: /secret/\n"
        policy = RobotsPolicy.from_robots_txt(robots_no_delay)
        delay = policy.crawl_delay()
        assert delay is None

    def test_empty_robots_allows_everything(self):
        """An empty robots.txt allows all paths."""
        from knowledge_lake.crawl.robots import RobotsPolicy

        policy = RobotsPolicy.from_robots_txt("")
        assert policy.is_allowed("/anything") is True
        assert policy.crawl_delay() is None


# ── Per-host async limiter ────────────────────────────────────────────────────


class TestPerHostLimiter:
    """Per-host limiter is keyed on registrable domain via tldextract."""

    def test_same_registrable_domain_shares_limiter(self):
        """Subdomains of the same registrable domain share a single limiter key."""
        from knowledge_lake.crawl.ratelimit import _domain_key

        key1 = _domain_key("https://www.example.com/page1")
        key2 = _domain_key("https://api.example.com/page2")
        assert key1 == key2, "Same registrable domain should share a limiter"

    def test_different_domains_get_different_keys(self):
        """Different registrable domains get separate limiter keys."""
        from knowledge_lake.crawl.ratelimit import _domain_key

        key1 = _domain_key("https://example.com/page")
        key2 = _domain_key("https://other.org/page")
        assert key1 != key2, "Different domains should have different keys"


# ── Phase 8: TestAdaptiveRateLimiter stubs (CRAWL-03) ────────────────────────


class TestAdaptiveRateLimiter:
    """Phase 8 stubs for CRAWL-03: adaptive rate limiting with error backoff."""

    @pytest.mark.xfail(strict=False, reason="Phase 8 CRAWL-03 — not yet implemented")
    def test_record_error_increments_count(self):
        """After record_error('http://example.com'), consecutive_errors for
        'example.com' key is 1.
        """
        from knowledge_lake.crawl.ratelimit import PerHostLimiter

        limiter = PerHostLimiter()
        limiter.record_error("http://example.com")
        assert limiter.consecutive_errors.get("example.com", 0) == 1

    @pytest.mark.xfail(strict=False, reason="Phase 8 CRAWL-03 — not yet implemented")
    def test_reset_errors_clears_count(self):
        """After record_error then reset_errors, consecutive_errors key is absent or 0."""
        from knowledge_lake.crawl.ratelimit import PerHostLimiter

        limiter = PerHostLimiter()
        limiter.record_error("http://example.com")
        limiter.reset_errors("http://example.com")
        assert limiter.consecutive_errors.get("example.com", 0) == 0

    @pytest.mark.xfail(strict=False, reason="Phase 8 CRAWL-03 — not yet implemented")
    def test_backoff_extra_exponential(self):
        """record_error twice on 'http://example.com', backoff_extra returns
        min(base * 4, MAX_BACKOFF_SECONDS).
        """
        from knowledge_lake.crawl.ratelimit import MAX_BACKOFF_SECONDS, PerHostLimiter

        limiter = PerHostLimiter()
        limiter.record_error("http://example.com")
        limiter.record_error("http://example.com")
        extra = limiter.backoff_extra("http://example.com")
        base = getattr(limiter, "_backoff_base", 1.0)
        expected = min(base * 4, MAX_BACKOFF_SECONDS)
        assert extra == pytest.approx(expected)

    @pytest.mark.xfail(strict=False, reason="Phase 8 CRAWL-03 — not yet implemented")
    def test_backoff_extra_capped(self):
        """After enough errors, backoff_extra must not exceed MAX_BACKOFF_SECONDS."""
        from knowledge_lake.crawl.ratelimit import MAX_BACKOFF_SECONDS, PerHostLimiter

        limiter = PerHostLimiter()
        for _ in range(20):
            limiter.record_error("http://example.com")
        extra = limiter.backoff_extra("http://example.com")
        assert extra <= MAX_BACKOFF_SECONDS
