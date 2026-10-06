-- =============================================================================
-- Camera-motion + cut check (runbook W2 Worker, 2026-10-06)
--
-- Broadcast cameras pan, zoom and cut, which breaks hold boxes drawn on frame
-- 1 and mixes camera motion into pixel-space pose velocity. The pose worker
-- measures each clip (worker/camera_check.py) and writes these columns with
-- its 'done' result; the API refuses to mark a paper clip ready when a cut is
-- found or motion / zoom exceed CAMERA_MOTION_MAX / CAMERA_ZOOM_MAX, unless an
-- admin sets camera_override with a note.
--
-- Additive; schema_version unchanged. Written only by the worker (service
-- role) and the API's admin routes: no UPDATE grant to `authenticated`.
-- =============================================================================

ALTER TABLE public.videos
    ADD COLUMN IF NOT EXISTS has_cut                  boolean,
    ADD COLUMN IF NOT EXISTS cut_frames               jsonb,
    ADD COLUMN IF NOT EXISTS camera_motion_score      real
        CHECK (camera_motion_score IS NULL OR camera_motion_score >= 0),
    ADD COLUMN IF NOT EXISTS camera_zoom_range        real
        CHECK (camera_zoom_range IS NULL OR camera_zoom_range >= 1),
    ADD COLUMN IF NOT EXISTS camera_motion_frames_pct real
        CHECK (camera_motion_frames_pct IS NULL OR (camera_motion_frames_pct BETWEEN 0 AND 100)),
    ADD COLUMN IF NOT EXISTS camera_override          boolean NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS camera_override_note     text;

COMMENT ON COLUMN public.videos.camera_motion_score IS
    'p95 per-frame background displacement as a fraction of the frame diagonal (worker camera_check.py). NULL = not measured.';
COMMENT ON COLUMN public.videos.camera_zoom_range IS
    'max/min cumulative background scale over the clip (1.0 = no zoom).';
COMMENT ON COLUMN public.videos.camera_override IS
    'Admin accepted the clip despite failing the camera check; camera_override_note says why.';
