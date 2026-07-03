"""
Knowledge Lake registry package (FOUND-05, FOUND-09).

Provides the PostgreSQL registry that is the source of truth for all entities
and lineage. The registry stores sources, artifacts (raw documents, parsed
documents, and chunks), and lineage events.

Sub-modules:
    models  — SQLAlchemy 2.0 declarative ORM models
    db      — Engine / session factory built from Settings.database_url
    repo    — Repository layer (create_source, create_*_artifact, get_*,
              list_children)
"""
