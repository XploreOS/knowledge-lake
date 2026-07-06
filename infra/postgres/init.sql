-- PostgreSQL initialization script
-- Creates the registry database/user and a separate Dagster database
-- (Open Question 5: separate Dagster DB so its tables never touch the registry schema)
--
-- This file runs when the postgres container starts from a clean data volume.
-- Do NOT use manual DDL for the registry schema — that's Alembic's job (FOUND-09).

-- ── Registry database ─────────────────────────────────────────────────────
-- The 'klake' user and 'klake' database are created by POSTGRES_USER / POSTGRES_DB env vars.
-- We only need to ensure the Alembic migration schema is set up at first migration run.

-- ── Dagster database ──────────────────────────────────────────────────────
-- Dagster needs its own storage. Use a separate DB so its tables don't touch
-- the klake registry schema (FOUND-09 / research Open Question 5).
SELECT 'CREATE DATABASE dagster_storage OWNER klake'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'dagster_storage') \gexec

-- Grant the klake user full access to dagster_storage
\c dagster_storage
GRANT ALL PRIVILEGES ON DATABASE dagster_storage TO klake;
\c klake

-- ── LiteLLM proxy database ─────────────────────────────────────────────────
-- The LiteLLM proxy's budget/spend-tracking and managed-files hooks require a
-- Prisma-backed DATABASE_URL — without one, /chat/completions and /embeddings
-- return "400 No connected db" for every model call. Same separate-DB rationale
-- as dagster_storage: LiteLLM's own Prisma-managed tables must never touch the
-- klake registry schema (Phase 4 checkpoint finding).
SELECT 'CREATE DATABASE litellm_storage OWNER klake'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'litellm_storage') \gexec

-- Grant the klake user full access to litellm_storage
\c litellm_storage
GRANT ALL PRIVILEGES ON DATABASE litellm_storage TO klake;
\c klake
