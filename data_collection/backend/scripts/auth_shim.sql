-- Minimal stand-in for Supabase's `auth` schema, for a throwaway local Postgres.
--
-- The v3 migration's RLS policies call auth.uid() and auth.role(). Those are
-- provided by Supabase's GoTrue, not by Postgres, so on a plain instance the
-- migration fails at CREATE POLICY — the function has to resolve at policy
-- creation time, before any row is ever read.
--
-- These read the same session GUCs Supabase uses, so a test can impersonate a
-- user with:
--
--     SET request.jwt.claims = '{"sub":"<uuid>","role":"authenticated"}';
--
-- and get exactly the behaviour production RLS would give it.
--
-- ⚠️ TEST FIXTURE ONLY. Never apply this to the Supabase project — it would
-- shadow the real auth schema. It exists so `pytest` can build a schema that
-- matches production without needing Supabase running.

CREATE SCHEMA IF NOT EXISTS auth;

-- The signed-in user's id, or NULL when there are no claims on the session.
CREATE OR REPLACE FUNCTION auth.uid()
RETURNS uuid
LANGUAGE sql
STABLE
AS $$
  SELECT NULLIF(
    current_setting('request.jwt.claims', true)::json ->> 'sub',
    ''
  )::uuid;
$$;

-- The signed-in user's role. Defaults to 'anon', matching Supabase, so a
-- session that has set no claims is treated as signed out rather than
-- accidentally authenticated.
CREATE OR REPLACE FUNCTION auth.role()
RETURNS text
LANGUAGE sql
STABLE
AS $$
  SELECT COALESCE(
    NULLIF(current_setting('request.jwt.claims', true)::json ->> 'role', ''),
    'anon'
  );
$$;

-- ---------------------------------------------------------------------------
-- The PostgREST roles. Supabase creates `anon` and `authenticated` and gives
-- them privileges on every new table in public via default privileges; the
-- Dataset A migration REVOKEs / GRANTs column privileges from them and the
-- RLS tests impersonate them with:
--
--     SET ROLE authenticated;
--     SET request.jwt.claims = '{"sub":"<uuid>","role":"authenticated"}';
--
-- Idempotent: safe to apply again to an existing scratch database.
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        CREATE ROLE anon NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        CREATE ROLE authenticated NOLOGIN;
    END IF;
END $$;

GRANT USAGE ON SCHEMA public, auth TO anon, authenticated;
-- Tables that already exist (a scratch database built before this shim grew
-- the roles): grant now; the Dataset A migration revokes on top of this.
GRANT ALL ON ALL TABLES IN SCHEMA public TO anon, authenticated;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO anon, authenticated;
-- Tables the migrations create from here on get the same broad grants
-- Supabase applies, so the migration's REVOKEs mean what they mean there.
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO anon, authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO anon, authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT EXECUTE ON FUNCTIONS TO anon, authenticated;
