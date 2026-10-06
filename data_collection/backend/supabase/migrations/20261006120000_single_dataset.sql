-- =============================================================================
-- Single dataset + public-source clips (runbook W2 Backend + Amendment, 2026-10-06)
--
-- Scope flip: the paper uses public footage (IFSC broadcasts, CC / open
-- research footage), rated by validated raters. One dataset, with a random
-- ~25% overlap subset rated by 3 raters for inter-rater reliability. The old
-- self-upload flow survives as the dormant "community" source type behind
-- SELF_UPLOAD_ENABLED.
--
--   * videos: dataset -> gone; irr_overlap (+ set_by); public-source fields;
--     athlete link. Old climber_* / gym prep columns dropped (they now live
--     on athletes, or do not apply to broadcast footage).
--   * athletes: pseudonymous athlete table (no names), admin-only.
--   * video_assignments: cohort -> gone (the overlap flag is per video).
--   * rater_profiles: tier ('validated'|'open') -> is_validated bool.
--   * strategies: per-rater Strategy lens rows (one per move per rater), so
--     approach / tags / size / form quality are rated independently like
--     Environment and Outcome. The strategy columns on `moves` stay: they are
--     the owner's own labels on community videos.
--
-- schema_version is NOT bumped, for the same reason as the earlier additive
-- migrations (database.check_schema() requires an exact match).
--
-- Existing rows: there is no study data yet. Videos that were Dataset B
-- (self-uploads) become source_type 'community'; everything else defaults to
-- 'public_broadcast'. Profiles with tier 'validated' keep that as
-- is_validated = true.
-- =============================================================================

-- ---------------------------------------------------------------------------
-- athletes
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.athletes (
    athlete_id       uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    -- Admin-only lookup key so the same athlete is not entered twice. Never
    -- exported; the release identifies athletes by athlete_id only.
    ifsc_profile_url text        UNIQUE,
    height_cm        integer     CHECK (height_cm IS NULL OR (height_cm BETWEEN 100 AND 250)),
    height_source    text        NOT NULL DEFAULT 'missing'
        CHECK (height_source IN ('ifsc_profile', 'missing')),
    birth_year       integer     CHECK (birth_year IS NULL OR (birth_year BETWEEN 1900 AND 2100)),
    category         text        CHECK (category IS NULL OR category IN ('men', 'women')),
    created_at       timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE public.athletes IS
    'Pseudonymous athletes for public-source clips. No names by design. Height and birth year from public IFSC profiles.';

ALTER TABLE public.athletes ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS athletes_select ON public.athletes;
DROP POLICY IF EXISTS athletes_insert ON public.athletes;
DROP POLICY IF EXISTS athletes_update ON public.athletes;
DROP POLICY IF EXISTS athletes_delete ON public.athletes;
CREATE POLICY athletes_select ON public.athletes FOR SELECT USING (public.is_admin());
CREATE POLICY athletes_insert ON public.athletes FOR INSERT WITH CHECK (public.is_admin());
CREATE POLICY athletes_update ON public.athletes FOR UPDATE
    USING (public.is_admin()) WITH CHECK (public.is_admin());
CREATE POLICY athletes_delete ON public.athletes FOR DELETE USING (public.is_admin());

-- ---------------------------------------------------------------------------
-- videos
-- ---------------------------------------------------------------------------
ALTER TABLE public.videos
    ADD COLUMN IF NOT EXISTS source_type text NOT NULL DEFAULT 'public_broadcast'
        CHECK (source_type IN ('public_broadcast', 'cc_license', 'research_dataset', 'community'));

-- Former self-uploads are community videos. Guarded: a re-run after `dataset`
-- is gone is a no-op.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'videos' AND column_name = 'dataset'
    ) THEN
        UPDATE public.videos SET source_type = 'community' WHERE dataset = 'B';
    END IF;
END $$;

DROP INDEX IF EXISTS public.idx_videos_dataset_status;

ALTER TABLE public.videos
    DROP COLUMN IF EXISTS dataset,
    DROP COLUMN IF EXISTS climber_experience,
    DROP COLUMN IF EXISTS climber_height_cm,
    DROP COLUMN IF EXISTS climber_ape_index_cm,
    DROP COLUMN IF EXISTS gym,
    ADD COLUMN IF NOT EXISTS irr_overlap        boolean NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS irr_overlap_set_by text
        CHECK (irr_overlap_set_by IS NULL OR irr_overlap_set_by IN ('random', 'admin_override')),
    ADD COLUMN IF NOT EXISTS source_url    text,
    ADD COLUMN IF NOT EXISTS clip_start_ms integer CHECK (clip_start_ms IS NULL OR clip_start_ms >= 0),
    ADD COLUMN IF NOT EXISTS clip_end_ms   integer CHECK (clip_end_ms IS NULL OR clip_end_ms >= 0),
    ADD COLUMN IF NOT EXISTS license       text,
    ADD COLUMN IF NOT EXISTS event_name    text,
    ADD COLUMN IF NOT EXISTS event_date    date,
    ADD COLUMN IF NOT EXISTS athlete_id    uuid REFERENCES public.athletes (athlete_id) ON DELETE SET NULL;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'videos_clip_range_check') THEN
        ALTER TABLE public.videos ADD CONSTRAINT videos_clip_range_check
            CHECK (clip_start_ms IS NULL OR clip_end_ms IS NULL OR clip_end_ms > clip_start_ms);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_videos_source_status ON public.videos (source_type, prep_status);
CREATE INDEX IF NOT EXISTS idx_videos_athlete ON public.videos (athlete_id);

COMMENT ON COLUMN public.videos.irr_overlap IS
    'In the inter-rater reliability subset: rated by 3 raters instead of 1. Drawn at random when the video is marked ready.';
COMMENT ON COLUMN public.videos.source_type IS
    'public_broadcast | cc_license | research_dataset = paper footage, admin-prepped. community = dormant self-upload flow (SELF_UPLOAD_ENABLED).';

-- Column privileges for signed-in users (PostgREST). Mirrors the Dataset A
-- grant minus the dropped columns; overlap, source and athlete fields are set
-- only through the API's admin routes.
REVOKE UPDATE ON public.videos FROM authenticated, anon;
GRANT UPDATE (
    filename, fps, total_frames, duration_ms, width, height,
    r2_video_key, r2_pose_csv_key, r2_export_key,
    route_grade, wall_type, camera_angle, notes
) ON public.videos TO authenticated;

-- ---------------------------------------------------------------------------
-- video_assignments: cohort is now a per-video flag
-- ---------------------------------------------------------------------------
ALTER TABLE public.video_assignments DROP COLUMN IF EXISTS cohort;

-- ---------------------------------------------------------------------------
-- rater_profiles: tier -> is_validated
-- ---------------------------------------------------------------------------
ALTER TABLE public.rater_profiles
    ADD COLUMN IF NOT EXISTS is_validated boolean NOT NULL DEFAULT false;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'rater_profiles' AND column_name = 'tier'
    ) THEN
        UPDATE public.rater_profiles SET is_validated = true WHERE tier = 'validated';
    END IF;
END $$;

ALTER TABLE public.rater_profiles DROP COLUMN IF EXISTS tier;
-- is_validated is admin-only: no INSERT / UPDATE grant to authenticated (the
-- Dataset A column grants already exclude it).

-- ---------------------------------------------------------------------------
-- strategies: per-rater Strategy lens
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.strategies (
    id               bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    move_id          bigint      NOT NULL REFERENCES public.moves (id) ON DELETE CASCADE,
    user_id          uuid        NOT NULL,
    approach         text        NOT NULL,
    size             text        NOT NULL,
    move_tags        jsonb       NOT NULL DEFAULT '[]'::jsonb,
    form_quality     integer     NOT NULL CHECK (form_quality BETWEEN 1 AND 5),
    confidence       text,
    taxonomy_version text        NOT NULL DEFAULT '3.1.0',
    is_gold          boolean     NOT NULL DEFAULT false,
    labeled_at       timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT strategies_move_user_key UNIQUE (move_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_strategies_move ON public.strategies (move_id);
CREATE INDEX IF NOT EXISTS idx_strategies_user ON public.strategies (user_id);

ALTER TABLE public.strategies ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS strategies_select ON public.strategies;
DROP POLICY IF EXISTS strategies_insert ON public.strategies;
DROP POLICY IF EXISTS strategies_update ON public.strategies;
DROP POLICY IF EXISTS strategies_delete ON public.strategies;
CREATE POLICY strategies_select ON public.strategies FOR SELECT
    USING (auth.uid() = user_id OR public.is_admin());
CREATE POLICY strategies_insert ON public.strategies FOR INSERT
    WITH CHECK (auth.uid() = user_id);
CREATE POLICY strategies_update ON public.strategies FOR UPDATE
    USING (auth.uid() = user_id OR public.is_admin())
    WITH CHECK (auth.uid() = user_id OR public.is_admin());
CREATE POLICY strategies_delete ON public.strategies FOR DELETE
    USING (auth.uid() = user_id OR public.is_admin());
