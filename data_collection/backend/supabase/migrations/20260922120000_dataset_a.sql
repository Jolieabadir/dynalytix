-- =============================================================================
-- Dataset A: prep/rating split, rater assignments, validated-rater profiles
-- (runbook W1 Backend, 2026-09-22)
--
-- Additive only. No table is dropped or rewritten, no column is renamed, and
-- schema_version is NOT bumped (database.check_schema() requires an exact
-- match against SCHEMA_VERSION, so a bump would refuse to start the API on a
-- database that has not had this file applied - see the dimensions migration
-- for the same reasoning). Every new NOT NULL column carries a DEFAULT so
-- existing rows backfill in place.
--
-- Design (see claude-ops/runbook-w1-backend.md):
--   * Prep pass (admin / uploader): upload, draw holds, define canonical moves,
--     fill metadata, mark ready. Holds and moves lock at 'ready'.
--   * Rating pass (assigned rater): reads the video, its holds, its canonical
--     moves and pose CSV; writes only its own environment / outcome /
--     frame_tag rows (user_id = the rater). Never sees another rater's rows.
--   * Dataset B (the existing self-upload flow) is untouched: dataset
--     defaults to 'B', prep_status to 'draft', and a draft video behaves
--     exactly as before.
--
-- videos.user_id is NOT renamed. Its meaning is now "owner / prepper"
-- (owner_user_id semantics): the uploader on Dataset B, the admin who prepped
-- the video on Dataset A. The column keeps its name so nothing that already
-- reads it has to change.
-- =============================================================================

-- ---------------------------------------------------------------------------
-- videos: dataset, prep status, prep metadata
-- ---------------------------------------------------------------------------
ALTER TABLE public.videos
    ADD COLUMN IF NOT EXISTS dataset     text NOT NULL DEFAULT 'B'
        CHECK (dataset IN ('A', 'B')),
    ADD COLUMN IF NOT EXISTS prep_status text NOT NULL DEFAULT 'draft'
        CHECK (prep_status IN ('draft', 'ready', 'closed')),
    ADD COLUMN IF NOT EXISTS route_grade          text,
    ADD COLUMN IF NOT EXISTS wall_type            text,
    ADD COLUMN IF NOT EXISTS climber_experience   text,
    ADD COLUMN IF NOT EXISTS climber_height_cm    integer
        CHECK (climber_height_cm IS NULL OR climber_height_cm > 0),
    ADD COLUMN IF NOT EXISTS climber_ape_index_cm integer,
    ADD COLUMN IF NOT EXISTS camera_angle         text,
    ADD COLUMN IF NOT EXISTS gym                  text,
    ADD COLUMN IF NOT EXISTS notes                text;

COMMENT ON COLUMN public.videos.user_id IS
    'Owner / prepper of the video (owner_user_id semantics). The uploader on Dataset B; the admin who prepped it on Dataset A. Not renamed so existing readers keep working.';
COMMENT ON COLUMN public.videos.dataset IS
    'A = prepped once, rated independently by assigned raters. B = the self-upload flow (owner labels their own video).';
COMMENT ON COLUMN public.videos.prep_status IS
    'draft: holds/moves editable by the owner. ready: locked, open to assigned raters. closed: locked, rating finished.';

CREATE INDEX IF NOT EXISTS idx_videos_dataset_status ON public.videos (dataset, prep_status);

-- ---------------------------------------------------------------------------
-- rater_profiles
--
-- One row per signed-in user who labels. Collected at first sign-in by the
-- app. Admin flag lives here (an is_admin bool rather than a separate
-- users_admin table): one row per user already exists, one fewer join, and
-- the "who is an admin" question is answered by the same query that gates
-- labeling. Flip it with:
--   UPDATE public.rater_profiles SET is_admin = true WHERE user_id = '<uuid>';
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.rater_profiles (
    user_id             uuid        PRIMARY KEY,
    display_name        text        NOT NULL,
    tier                text        NOT NULL DEFAULT 'open'
        CHECK (tier IN ('validated', 'open')),
    years_climbing      integer     CHECK (years_climbing IS NULL OR years_climbing >= 0),
    coaching_cert       text,
    highest_grade       text,
    research_background boolean     NOT NULL DEFAULT false,
    -- Why this rater counts as validated. Set by an admin.
    validation_note     text,
    is_admin            boolean     NOT NULL DEFAULT false,
    created_at          timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- video_assignments
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.video_assignments (
    id            bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    video_id      bigint      NOT NULL REFERENCES public.videos (id) ON DELETE CASCADE,
    rater_user_id uuid        NOT NULL,
    cohort        text        NOT NULL
        CHECK (cohort IN ('validated', 'overlap')),
    status        text        NOT NULL DEFAULT 'assigned'
        CHECK (status IN ('assigned', 'in_progress', 'done')),
    assigned_at   timestamptz NOT NULL DEFAULT now(),
    completed_at  timestamptz,
    UNIQUE (video_id, rater_user_id)
);

CREATE INDEX IF NOT EXISTS idx_video_assignments_rater ON public.video_assignments (rater_user_id, status);
CREATE INDEX IF NOT EXISTS idx_video_assignments_video ON public.video_assignments (video_id);

-- ---------------------------------------------------------------------------
-- environments / outcomes / frame_tags: taxonomy_version + is_gold
--
-- taxonomy_version is stamped by the API from its TAXONOMY_VERSION constant on
-- every insert and update. Rows written before this migration are backfilled
-- to '3.0.0', the taxonomy they were labeled under; the default is kept so a
-- direct insert without the column still satisfies NOT NULL.
-- ---------------------------------------------------------------------------
ALTER TABLE public.environments
    ADD COLUMN IF NOT EXISTS taxonomy_version text    NOT NULL DEFAULT '3.0.0',
    ADD COLUMN IF NOT EXISTS is_gold          boolean NOT NULL DEFAULT false;

ALTER TABLE public.outcomes
    ADD COLUMN IF NOT EXISTS taxonomy_version text    NOT NULL DEFAULT '3.0.0',
    ADD COLUMN IF NOT EXISTS is_gold          boolean NOT NULL DEFAULT false;

ALTER TABLE public.frame_tags
    ADD COLUMN IF NOT EXISTS taxonomy_version text    NOT NULL DEFAULT '3.0.0',
    ADD COLUMN IF NOT EXISTS is_gold          boolean NOT NULL DEFAULT false;

-- ---------------------------------------------------------------------------
-- environments / outcomes: one per (move, rater) instead of one per move
--
-- Three raters each need their own environment and outcome on the same
-- canonical move. The v3 constraint was UNIQUE (move_id); it becomes
-- UNIQUE (move_id, user_id). Dataset B is unaffected: an owner is still the
-- only user writing to their own moves, so one-per-move still holds there.
-- ---------------------------------------------------------------------------
ALTER TABLE public.environments DROP CONSTRAINT IF EXISTS environments_move_id_key;
ALTER TABLE public.environments ADD CONSTRAINT environments_move_user_key UNIQUE (move_id, user_id);

ALTER TABLE public.outcomes DROP CONSTRAINT IF EXISTS outcomes_move_id_key;
ALTER TABLE public.outcomes ADD CONSTRAINT outcomes_move_user_key UNIQUE (move_id, user_id);

-- =============================================================================
-- Row Level Security
--
-- As before, the API connects over the Postgres role in DATABASE_URL, which
-- bypasses RLS; the API enforces the same rules itself (see src/web/api.py,
-- _require_video_access). These policies protect the tables from direct
-- PostgREST / anon-key access with a user's own JWT.
--
-- Two helpers, SECURITY DEFINER so a policy on rater_profiles can consult
-- rater_profiles without recursing into its own policy:
--   public.is_admin()                 the caller's profile has is_admin
--   public.has_assignment(video_id)   the caller is an assigned rater on it
--
-- The existing per-table policies are replaced (DROP + CREATE under the same
-- names) rather than supplemented, so every data table still carries exactly
-- four policies: select / insert / update / delete.
-- =============================================================================

CREATE OR REPLACE FUNCTION public.is_admin()
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
    SELECT COALESCE(
        (SELECT p.is_admin FROM public.rater_profiles p WHERE p.user_id = auth.uid()),
        false
    );
$$;

CREATE OR REPLACE FUNCTION public.has_assignment(target_video_id bigint)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
    SELECT EXISTS (
        SELECT 1 FROM public.video_assignments a
        WHERE a.video_id = target_video_id AND a.rater_user_id = auth.uid()
    );
$$;

-- Helper: is the video's structure (holds / moves) still editable by its owner?
CREATE OR REPLACE FUNCTION public.video_is_draft(target_video_id bigint)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
    SELECT EXISTS (
        SELECT 1 FROM public.videos v
        WHERE v.id = target_video_id AND v.prep_status = 'draft'
    );
$$;

-- videos: owner, assigned rater (read only) or admin
DROP POLICY IF EXISTS videos_select ON public.videos;
DROP POLICY IF EXISTS videos_insert ON public.videos;
DROP POLICY IF EXISTS videos_update ON public.videos;
DROP POLICY IF EXISTS videos_delete ON public.videos;
CREATE POLICY videos_select ON public.videos FOR SELECT
    USING (auth.uid() = user_id OR public.has_assignment(id) OR public.is_admin());
CREATE POLICY videos_insert ON public.videos FOR INSERT
    WITH CHECK (auth.uid() = user_id OR public.is_admin());
CREATE POLICY videos_update ON public.videos FOR UPDATE
    USING (auth.uid() = user_id OR public.is_admin())
    WITH CHECK (auth.uid() = user_id OR public.is_admin());
CREATE POLICY videos_delete ON public.videos FOR DELETE
    USING (auth.uid() = user_id OR public.is_admin());

-- holds: readable by whoever can read the video; writable by the owner while
-- the video is a draft, or by an admin at any time.
DROP POLICY IF EXISTS holds_select ON public.holds;
DROP POLICY IF EXISTS holds_insert ON public.holds;
DROP POLICY IF EXISTS holds_update ON public.holds;
DROP POLICY IF EXISTS holds_delete ON public.holds;
CREATE POLICY holds_select ON public.holds FOR SELECT
    USING (auth.uid() = user_id OR public.has_assignment(video_id) OR public.is_admin());
CREATE POLICY holds_insert ON public.holds FOR INSERT
    WITH CHECK ((auth.uid() = user_id AND public.video_is_draft(video_id)) OR public.is_admin());
CREATE POLICY holds_update ON public.holds FOR UPDATE
    USING ((auth.uid() = user_id AND public.video_is_draft(video_id)) OR public.is_admin())
    WITH CHECK ((auth.uid() = user_id AND public.video_is_draft(video_id)) OR public.is_admin());
CREATE POLICY holds_delete ON public.holds FOR DELETE
    USING ((auth.uid() = user_id AND public.video_is_draft(video_id)) OR public.is_admin());

-- moves: same shape as holds. user_id stays the creator.
DROP POLICY IF EXISTS moves_select ON public.moves;
DROP POLICY IF EXISTS moves_insert ON public.moves;
DROP POLICY IF EXISTS moves_update ON public.moves;
DROP POLICY IF EXISTS moves_delete ON public.moves;
CREATE POLICY moves_select ON public.moves FOR SELECT
    USING (auth.uid() = user_id OR public.has_assignment(video_id) OR public.is_admin());
CREATE POLICY moves_insert ON public.moves FOR INSERT
    WITH CHECK ((auth.uid() = user_id AND public.video_is_draft(video_id)) OR public.is_admin());
CREATE POLICY moves_update ON public.moves FOR UPDATE
    USING ((auth.uid() = user_id AND public.video_is_draft(video_id)) OR public.is_admin())
    WITH CHECK ((auth.uid() = user_id AND public.video_is_draft(video_id)) OR public.is_admin());
CREATE POLICY moves_delete ON public.moves FOR DELETE
    USING ((auth.uid() = user_id AND public.video_is_draft(video_id)) OR public.is_admin());

-- environments / outcomes / frame_tags: label rows. Strictly the rater's own
-- (user_id = auth.uid()); an admin can read everything. No rater can read
-- another rater's rows on the same move.
DROP POLICY IF EXISTS environments_select ON public.environments;
DROP POLICY IF EXISTS environments_insert ON public.environments;
DROP POLICY IF EXISTS environments_update ON public.environments;
DROP POLICY IF EXISTS environments_delete ON public.environments;
CREATE POLICY environments_select ON public.environments FOR SELECT
    USING (auth.uid() = user_id OR public.is_admin());
CREATE POLICY environments_insert ON public.environments FOR INSERT
    WITH CHECK (auth.uid() = user_id);
CREATE POLICY environments_update ON public.environments FOR UPDATE
    USING (auth.uid() = user_id OR public.is_admin())
    WITH CHECK (auth.uid() = user_id OR public.is_admin());
CREATE POLICY environments_delete ON public.environments FOR DELETE
    USING (auth.uid() = user_id OR public.is_admin());

DROP POLICY IF EXISTS outcomes_select ON public.outcomes;
DROP POLICY IF EXISTS outcomes_insert ON public.outcomes;
DROP POLICY IF EXISTS outcomes_update ON public.outcomes;
DROP POLICY IF EXISTS outcomes_delete ON public.outcomes;
CREATE POLICY outcomes_select ON public.outcomes FOR SELECT
    USING (auth.uid() = user_id OR public.is_admin());
CREATE POLICY outcomes_insert ON public.outcomes FOR INSERT
    WITH CHECK (auth.uid() = user_id);
CREATE POLICY outcomes_update ON public.outcomes FOR UPDATE
    USING (auth.uid() = user_id OR public.is_admin())
    WITH CHECK (auth.uid() = user_id OR public.is_admin());
CREATE POLICY outcomes_delete ON public.outcomes FOR DELETE
    USING (auth.uid() = user_id OR public.is_admin());

DROP POLICY IF EXISTS frame_tags_select ON public.frame_tags;
DROP POLICY IF EXISTS frame_tags_insert ON public.frame_tags;
DROP POLICY IF EXISTS frame_tags_update ON public.frame_tags;
DROP POLICY IF EXISTS frame_tags_delete ON public.frame_tags;
CREATE POLICY frame_tags_select ON public.frame_tags FOR SELECT
    USING (auth.uid() = user_id OR public.is_admin());
CREATE POLICY frame_tags_insert ON public.frame_tags FOR INSERT
    WITH CHECK (auth.uid() = user_id);
CREATE POLICY frame_tags_update ON public.frame_tags FOR UPDATE
    USING (auth.uid() = user_id OR public.is_admin())
    WITH CHECK (auth.uid() = user_id OR public.is_admin());
CREATE POLICY frame_tags_delete ON public.frame_tags FOR DELETE
    USING (auth.uid() = user_id OR public.is_admin());

-- rater_profiles: a user reads and creates their own row; tier / is_admin /
-- validation_note can only be set by an admin (a self-insert or self-update
-- must leave them at their non-privileged values).
ALTER TABLE public.rater_profiles ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS rater_profiles_select ON public.rater_profiles;
DROP POLICY IF EXISTS rater_profiles_insert ON public.rater_profiles;
DROP POLICY IF EXISTS rater_profiles_update ON public.rater_profiles;
DROP POLICY IF EXISTS rater_profiles_delete ON public.rater_profiles;
CREATE POLICY rater_profiles_select ON public.rater_profiles FOR SELECT
    USING (auth.uid() = user_id OR public.is_admin());
CREATE POLICY rater_profiles_insert ON public.rater_profiles FOR INSERT
    WITH CHECK (
        public.is_admin()
        OR (auth.uid() = user_id AND is_admin = false AND tier = 'open' AND validation_note IS NULL)
    );
CREATE POLICY rater_profiles_update ON public.rater_profiles FOR UPDATE
    USING (auth.uid() = user_id OR public.is_admin())
    WITH CHECK (
        public.is_admin()
        OR (auth.uid() = user_id AND is_admin = false AND tier = 'open' AND validation_note IS NULL)
    );
CREATE POLICY rater_profiles_delete ON public.rater_profiles FOR DELETE
    USING (public.is_admin());

-- video_assignments: a rater sees their own; only an admin creates or deletes;
-- a rater may update their own row (status transitions).
ALTER TABLE public.video_assignments ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS video_assignments_select ON public.video_assignments;
DROP POLICY IF EXISTS video_assignments_insert ON public.video_assignments;
DROP POLICY IF EXISTS video_assignments_update ON public.video_assignments;
DROP POLICY IF EXISTS video_assignments_delete ON public.video_assignments;
CREATE POLICY video_assignments_select ON public.video_assignments FOR SELECT
    USING (auth.uid() = rater_user_id OR public.is_admin());
CREATE POLICY video_assignments_insert ON public.video_assignments FOR INSERT
    WITH CHECK (public.is_admin());
CREATE POLICY video_assignments_update ON public.video_assignments FOR UPDATE
    USING (auth.uid() = rater_user_id OR public.is_admin())
    WITH CHECK (auth.uid() = rater_user_id OR public.is_admin());
CREATE POLICY video_assignments_delete ON public.video_assignments FOR DELETE
    USING (public.is_admin());
