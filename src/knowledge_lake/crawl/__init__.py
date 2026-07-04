"""Crawl subsystem — robots parsing, rate limiting, and crawler orchestration.

This package provides the politeness primitives required before any crawl:
  - robots.py  — Protego-backed robots.txt parsing (Disallow rules + Crawl-delay)
  - ratelimit.py — three-tier rate-limit resolver (D-12) + per-host async limiter
"""
