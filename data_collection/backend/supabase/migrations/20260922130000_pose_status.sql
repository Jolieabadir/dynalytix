-- ============================================================================
-- Server-side pose extraction: job state on videos
-- ============================================================================
--
-- Why: pose extraction moved from the browser to an async worker (Modal). The
-- browser now registers a video, uploads it to R2 and confirms; the backend
-- enqueues a job; the worker writes the pose CSV to R2 later. Labeling starts
-- immediately, so the UI, the exporter and the worker need one place that says
-- where the job is.
--
-- Additive and backwards compatible: every column has a default or is nullable,
-- so a v3 reader that never heard of pose_status keeps working. Rows that
-- already carry a pose CSV (browser-extracted, before this migration) are
-- backfilled to 'done' so their exports keep working without a worker run.
--
-- Like the dimensions migration this does NOT bump schema_version:
-- database.check_schema() requires an exact match, and the change is purely
-- additive.

ALTER TABLE public.videos
    ADD COLUMN IF NOT EXISTS pose_status text NOT NULL DEFAULT 'pending'
        CHECK (pose_status IN ('pending', 'processing', 'done', 'failed')),
    ADD COLUMN IF NOT EXISTS pose_error       text,
    ADD COLUMN IF NOT EXISTS pose_started_at  timestamptz,
    ADD COLUMN IF NOT EXISTS pose_finished_at timestamptz;

COMMENT ON COLUMN public.videos.pose_status IS
    'Pose extraction job state: pending (no job yet / queued), processing (worker running), done (CSV at r2_pose_csv_key), failed (see pose_error).';
COMMENT ON COLUMN public.videos.pose_error IS
    'Last failure reason from the worker or the enqueue step. NULL unless pose_status = failed.';
COMMENT ON COLUMN public.videos.pose_started_at IS
    'When the worker picked the job up (set on processing).';
COMMENT ON COLUMN public.videos.pose_finished_at IS
    'When the job reached done or failed.';

-- Videos extracted in the browser before the worker existed already have a
-- CSV; treat them as finished so export keeps working for them.
UPDATE public.videos
   SET pose_status = 'done',
       pose_finished_at = COALESCE(pose_finished_at, uploaded_at)
 WHERE r2_pose_csv_key IS NOT NULL
   AND pose_status = 'pending';

-- The worker polls nothing (it is pushed a job), but the retry path and any
-- future sweeper look up stuck jobs by state.
CREATE INDEX IF NOT EXISTS idx_videos_pose_status ON public.videos (pose_status);

-- RLS on public.videos is row-scoped by user_id, so the new columns are
-- covered by the existing policies. The worker connects with the service role
-- (DATABASE_URL), which bypasses RLS.
