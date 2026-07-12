# Security Policy

The Knowledge Lake team and community take security seriously. We appreciate
responsible disclosure of vulnerabilities and will work with you to verify and
address them promptly.

## Supported Versions

Knowledge Lake is pre-1.0 and under active development. Security fixes are
applied to the `main` branch and the most recent release.

| Version | Supported          |
| ------- | ------------------ |
| `main`  | :white_check_mark: |
| latest release (`0.1.x`) | :white_check_mark: |
| older pre-releases | :x: |

## Reporting a Vulnerability

**Please do not report security vulnerabilities through public GitHub issues,
discussions, or pull requests.**

Instead, use GitHub's private vulnerability reporting:

1. Go to the repository's **Security** tab.
2. Click **Report a vulnerability** to open a private advisory.
3. Provide as much detail as possible (see below).

If you are unable to use GitHub Security Advisories, email the maintainers at
**security@xploreos.dev** with the same information.

> **Maintainers:** update the contact address above to a monitored inbox and
> enable "Private vulnerability reporting" in the repository's Security settings
> before publishing.

### What to include

- A description of the vulnerability and its potential impact.
- Steps to reproduce, or a proof-of-concept.
- Affected version(s), component(s), and configuration.
- Any suggested remediation, if known.

### What to expect

- **Acknowledgement** within 3 business days.
- **Initial assessment** and severity triage within 7 business days.
- Coordinated disclosure: we will agree on a disclosure timeline with you,
  typically within 90 days, and credit you in the advisory unless you prefer to
  remain anonymous.

## Scope and Handling Notes

Because Knowledge Lake ingests untrusted external content (crawled pages,
uploaded documents) and orchestrates external tools, please pay particular
attention to:

- Credential and secret handling (`.env`, LiteLLM keys, storage keys).
- SSRF / request forgery via crawl and discovery inputs.
- Parser and deserialization surfaces (document parsing, YAML/JSON ingestion).
- Injection into downstream LLM prompts and export artifacts.
- Robots.txt / license-compliance bypass in crawling.

When operating an instance, never commit real secrets. The `.gitignore` excludes
`.env`, `*.pem`, and `*.key`; keep production credentials in a secrets manager.
