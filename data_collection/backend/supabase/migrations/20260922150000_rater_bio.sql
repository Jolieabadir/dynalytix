-- ---------------------------------------------------------------------------
-- Rater profile: free-text bio replaces coaching_cert. Additive to the
-- Dataset A migration (20260922120000): the column is added, the old one
-- dropped, and the rater's column-level INSERT/UPDATE privilege on bio is
-- granted the same way display_name etc. are. Dropping coaching_cert removes
-- it from the existing column grants automatically. Idempotent.
-- ---------------------------------------------------------------------------
ALTER TABLE public.rater_profiles ADD COLUMN IF NOT EXISTS bio text;
ALTER TABLE public.rater_profiles DROP COLUMN IF EXISTS coaching_cert;

-- Rater-editable, like display_name / years_climbing / highest_grade.
-- tier / validation_note / is_admin stay admin-only (no grant).
GRANT INSERT (bio) ON public.rater_profiles TO authenticated;
GRANT UPDATE (bio) ON public.rater_profiles TO authenticated;
