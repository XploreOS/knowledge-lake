"""Domain pack loader for the Knowledge Lake framework (DOMAIN-01).

Loads a domain pack from a domains/{name}/ directory tree:
  - domain.yaml     → DomainManifest (Pydantic-validated)
  - sources.yaml    → list[SourceEntry] (Pydantic-validated)
  - taxonomy.yaml   → dict (raw, flexible)
  - prompts/        → Jinja2 Environment with autoescape=False (RESEARCH.md Pitfall 3)
  - validators/validate.py → loaded via importlib.util (RESEARCH.md Pitfall 1)

Security considerations:
  - Domain name validated against r'^[a-zA-Z][a-zA-Z0-9_-]{0,63}$' (T-06-01, path traversal guard)
  - yaml.safe_load used exclusively — never yaml.load (T-06-04, RESEARCH.md Pitfall 2)
  - jinja2.Environment(autoescape=False) for prompt templates (T-06-05, RESEARCH.md Pitfall 3)
  - importlib.util.spec_from_file_location without sys.path manipulation (RESEARCH.md Pitfall 7)
"""

from __future__ import annotations

import importlib.util
import os
import re
import sys
from pathlib import Path
from typing import Any

import yaml
from jinja2 import Environment, FileSystemLoader

from knowledge_lake.domains.models import DomainManifest, SourceEntry

# Domain name allow-list: alphanumeric + hyphen/underscore, 1-64 chars, start with letter.
# Same regex as _SWAP_KEY_RE in settings.py — path traversal guard (T-06-01, ASVS V5).
_DOMAIN_NAME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]{0,63}$")


class DomainLoader:
    """Reads a domain pack from the domains/{name}/ directory convention.

    After construction:
      - self.manifest  — DomainManifest (name, version, description)
      - self.sources   — list[SourceEntry] (from sources.yaml)
      - self.taxonomy  — dict (from taxonomy.yaml — raw for flexibility)
      - self.validator — the pack's *Validator instance (from validators/validate.py)
      - self.render_prompt(name, **kwargs) — renders a Jinja2 .j2 template from prompts/

    All YAML is loaded via yaml.safe_load (never yaml.load) per T-06-04.
    Jinja2 environment uses autoescape=False so clinical codes pass verbatim (T-06-05).
    Validator module is loaded via importlib.util without sys.path manipulation (Pitfall 7).

    Usage:
        loader = DomainLoader.from_name("healthcare")
        prompt = loader.render_prompt("enrich.j2", title="T", dates=[], headings=[], excerpt="...")
        result = loader.validator.validate_document({"text": "..."})
    """

    def __init__(self, domain_dir: Path) -> None:
        """Load a domain pack from the given directory.

        Args:
            domain_dir: Absolute path to the domain pack directory (e.g. /project/domains/healthcare).

        Raises:
            FileNotFoundError: If domain_dir or required files (domain.yaml, sources.yaml,
                               taxonomy.yaml, prompts/, validators/validate.py) are missing.
            pydantic.ValidationError: If domain.yaml or sources.yaml fail schema validation.
        """
        self.domain_dir = domain_dir

        # 1. Load and validate domain.yaml (DomainManifest)
        domain_yaml_path = domain_dir / "domain.yaml"
        if not domain_yaml_path.exists():
            raise FileNotFoundError(f"domain.yaml not found in domain pack: {domain_dir}")
        self.manifest: DomainManifest = DomainManifest.model_validate(
            yaml.safe_load(domain_yaml_path.read_text(encoding="utf-8"))
        )

        # 2. Load and validate sources.yaml (list[SourceEntry])
        sources_yaml_path = domain_dir / "sources.yaml"
        if not sources_yaml_path.exists():
            raise FileNotFoundError(f"sources.yaml not found in domain pack: {domain_dir}")
        raw_sources: list[Any] = yaml.safe_load(sources_yaml_path.read_text(encoding="utf-8"))
        self.sources: list[SourceEntry] = [
            SourceEntry.model_validate(s) for s in (raw_sources or [])
        ]

        # 3. Load taxonomy.yaml as raw dict (flexible — no strict schema)
        taxonomy_yaml_path = domain_dir / "taxonomy.yaml"
        if not taxonomy_yaml_path.exists():
            raise FileNotFoundError(f"taxonomy.yaml not found in domain pack: {domain_dir}")
        self.taxonomy: dict = yaml.safe_load(taxonomy_yaml_path.read_text(encoding="utf-8")) or {}

        # 4. Set up Jinja2 environment for prompts/ directory.
        # autoescape=False is mandatory — prompts are not HTML; autoescape would corrupt
        # clinical codes containing angle brackets like <E11.9> (T-06-05, RESEARCH.md Pitfall 3).
        prompts_dir = domain_dir / "prompts"
        if not prompts_dir.exists():
            raise FileNotFoundError(f"prompts/ directory not found in domain pack: {domain_dir}")
        self._jinja_env = Environment(
            loader=FileSystemLoader(str(prompts_dir)),
            autoescape=False,
        )

        # 5. Load validators/validate.py dynamically via importlib.util (Pitfall 7).
        # Never use sys.path manipulation — spec_from_file_location handles arbitrary paths.
        validator_path = domain_dir / "validators" / "validate.py"
        if not validator_path.exists():
            raise FileNotFoundError(
                f"validators/validate.py not found in domain pack: {domain_dir}"
            )
        spec = importlib.util.spec_from_file_location(
            f"domain_{self.manifest.name}_validator", str(validator_path)
        )
        if spec is None or spec.loader is None:
            raise ImportError(f"Could not create module spec for {validator_path}")
        module_name = f"domain_{self.manifest.name}_validator"
        mod = importlib.util.module_from_spec(spec)
        # Register in sys.modules BEFORE exec_module so that @dataclass decorator
        # can resolve cls.__module__ during class construction (Python 3.12 requirement).
        sys.modules[module_name] = mod
        try:
            spec.loader.exec_module(mod)  # type: ignore[union-attr]
        except Exception:
            sys.modules.pop(module_name, None)
            raise

        # Resolve the validator class generically (domain-agnostic): pick the
        # class defined in validate.py whose name ends with "Validator" and that
        # exposes a callable validate_document(). This avoids hardcoding any one
        # domain's class name (e.g. HealthcareValidator) so scaffolded packs and
        # third-party domains load without renaming their validator (DOMAIN-01).
        validator_cls: type | None = None
        for attr_name in dir(mod):
            candidate = getattr(mod, attr_name)
            if (
                isinstance(candidate, type)
                and getattr(candidate, "__module__", None) == module_name
                and attr_name.endswith("Validator")
                and callable(getattr(candidate, "validate_document", None))
            ):
                validator_cls = candidate
                break
        if validator_cls is None:
            raise ImportError(
                "validators/validate.py must define a class named '*Validator' with a "
                f"validate_document() method (domain pack: {domain_dir})"
            )
        self.validator = validator_cls()

    def render_prompt(self, template_name: str, **kwargs: Any) -> str:
        """Render a Jinja2 prompt template from the domain pack's prompts/ directory.

        Args:
            template_name: Template filename (e.g. 'enrich.j2', 'qa_generation.j2').
            **kwargs:       Variables to pass to the template.

        Returns:
            Rendered template string. No HTML escaping — autoescape=False.
        """
        tmpl = self._jinja_env.get_template(template_name)
        return tmpl.render(**kwargs)

    @classmethod
    def from_name(cls, name: str, root: Path | None = None) -> DomainLoader:
        """Load a domain pack by name from the project root domains/ directory.

        Args:
            name: Domain pack name (e.g. 'healthcare'). Validated against
                  r'^[a-zA-Z][a-zA-Z0-9_-]{0,63}$' to prevent path traversal (T-06-01).
            root: Optional project root path containing the domains/ subdirectory.
                  Defaults to: value of KLAKE_DOMAINS_ROOT env var, or Path.cwd() if
                  the env var is not set (RESEARCH.md Pitfall 1 — never __file__-relative
                  because the installed package resolves to .venv/lib/... not the project root).

        Returns:
            DomainLoader instance loaded from domains/{name}/.

        Raises:
            ValueError: If name does not match the allowed pattern (path traversal guard).
            FileNotFoundError: If the domain pack directory does not exist.
        """
        # Path traversal guard (T-06-01): validate name before constructing path.
        if not _DOMAIN_NAME_RE.match(name):
            raise ValueError(
                f"Invalid domain name {name!r}: must match "
                r"^[a-zA-Z][a-zA-Z0-9_-]{0,63}$ (path traversal guard)"
            )

        # Resolve root: explicit arg → KLAKE_DOMAINS_ROOT env var → cwd.
        # NEVER use __file__-relative resolution here (RESEARCH.md Pitfall 1):
        # when installed, loader.py is under .venv/lib/.../knowledge_lake/domains/loader.py
        # which is nowhere near the project's domains/ directory.
        if root is None:
            env_root = os.environ.get("KLAKE_DOMAINS_ROOT", "")
            root = Path(env_root) if env_root else Path.cwd()

        domain_dir = root / "domains" / name

        if not domain_dir.exists():
            raise FileNotFoundError(
                f"Domain pack not found: {domain_dir}. "
                f"Set KLAKE_DOMAINS_ROOT to the project root or pass root= explicitly."
            )

        return cls(domain_dir)
