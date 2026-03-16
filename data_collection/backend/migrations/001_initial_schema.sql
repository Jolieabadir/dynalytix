-- ============================================================================
-- Dynalytix PostgreSQL Schema (Supabase)
-- Migration 001: Initial schema — auth, clinics, providers, patients, assessments
-- ============================================================================

-- Enable UUID generation
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================================================
-- CLINICS
-- ============================================================================
CREATE TABLE clinics (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name TEXT NOT NULL,
    ehr_system TEXT DEFAULT '',                  -- e.g. "webpt", "clinicient"
    medstatix_clinic_id TEXT DEFAULT '',         -- MedStatix's ID for this clinic
    timezone TEXT DEFAULT 'America/New_York',
    billing_email TEXT DEFAULT '',
    stripe_customer_id TEXT DEFAULT '',          -- For Stripe billing
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================================
-- PROVIDERS (linked to Supabase auth.users)
-- ============================================================================
CREATE TABLE providers (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    auth_user_id UUID UNIQUE REFERENCES auth.users(id) ON DELETE CASCADE,
    clinic_id UUID NOT NULL REFERENCES clinics(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    email TEXT NOT NULL,
    npi TEXT DEFAULT '',                         -- National Provider Identifier
    role TEXT NOT NULL DEFAULT 'provider',       -- 'provider' | 'clinic_admin'
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_providers_clinic ON providers(clinic_id);
CREATE INDEX idx_providers_auth_user ON providers(auth_user_id);

-- ============================================================================
-- PATIENTS
-- ============================================================================
CREATE TABLE patients (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    clinic_id UUID NOT NULL REFERENCES clinics(id) ON DELETE CASCADE,
    first_name TEXT DEFAULT '',
    last_name TEXT DEFAULT '',
    email TEXT DEFAULT '',
    phone TEXT DEFAULT '',
    dob DATE,
    ehr_patient_id TEXT DEFAULT '',              -- Patient's ID in the clinic's EHR
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_patients_clinic ON patients(clinic_id);

-- ============================================================================
-- PATIENT ACCESS TOKENS (secure link auth)
-- ============================================================================
CREATE TABLE patient_tokens (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    patient_id UUID NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    clinic_id UUID NOT NULL REFERENCES clinics(id) ON DELETE CASCADE,
    provider_id UUID NOT NULL REFERENCES providers(id),  -- Who requested this assessment
    token TEXT UNIQUE NOT NULL,                  -- The secure random token in the URL
    assessment_type TEXT NOT NULL DEFAULT 'deep_squat',
    expires_at TIMESTAMPTZ NOT NULL,            -- Token expiration (e.g. 7 days)
    used_at TIMESTAMPTZ,                        -- When patient submitted their assessment
    is_used BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_patient_tokens_token ON patient_tokens(token);
CREATE INDEX idx_patient_tokens_patient ON patient_tokens(patient_id);

-- ============================================================================
-- VIDEOS (migrated from SQLite)
-- ============================================================================
CREATE TABLE videos (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    clinic_id UUID REFERENCES clinics(id),       -- NULL for non-clinical (climbing) videos
    patient_id UUID REFERENCES patients(id),     -- NULL for non-clinical videos
    provider_id UUID REFERENCES providers(id),   -- Who requested this assessment
    patient_token_id UUID REFERENCES patient_tokens(id),  -- Which token was used
    filename TEXT NOT NULL,
    path TEXT NOT NULL,
    csv_path TEXT NOT NULL,
    fps REAL NOT NULL DEFAULT 0,
    total_frames INTEGER NOT NULL DEFAULT 0,
    duration_ms REAL NOT NULL DEFAULT 0,
    uploaded_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_videos_clinic ON videos(clinic_id);
CREATE INDEX idx_videos_patient ON videos(patient_id);

-- ============================================================================
-- ASSESSMENTS (migrated from SQLite)
-- ============================================================================
CREATE TABLE assessments (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    video_id UUID NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    clinic_id UUID REFERENCES clinics(id),
    patient_id UUID REFERENCES patients(id),
    provider_id UUID REFERENCES providers(id),
    frame_start INTEGER NOT NULL DEFAULT 0,
    frame_end INTEGER NOT NULL DEFAULT 0,
    timestamp_start_ms REAL NOT NULL DEFAULT 0,
    timestamp_end_ms REAL NOT NULL DEFAULT 0,
    test_type TEXT NOT NULL DEFAULT 'deep_squat',
    score INTEGER NOT NULL DEFAULT 2,
    criteria_data JSONB NOT NULL DEFAULT '{}',
    compensations JSONB NOT NULL DEFAULT '[]',
    tags JSONB NOT NULL DEFAULT '[]',
    notes TEXT NOT NULL DEFAULT '',
    -- Scoring pipeline results
    billing_descriptions JSONB DEFAULT '[]',     -- From fms pipeline
    angles_at_depth JSONB DEFAULT '{}',
    bilateral_differences JSONB DEFAULT '{}',
    clinical_narrative TEXT DEFAULT '',
    disclaimer TEXT DEFAULT '',
    -- Approval workflow
    approval_status TEXT NOT NULL DEFAULT 'draft',  -- draft|provider_review|approved|rejected|pushed
    approved_by UUID REFERENCES providers(id),
    approved_at TIMESTAMPTZ,
    approval_notes TEXT DEFAULT '',
    provider_modified_score BOOLEAN DEFAULT FALSE,
    provider_modified_billing BOOLEAN DEFAULT FALSE,
    -- EHR push tracking
    ehr_record_id TEXT DEFAULT '',
    pushed_at TIMESTAMPTZ,
    -- Metadata
    assessed_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_assessments_video ON assessments(video_id);
CREATE INDEX idx_assessments_clinic ON assessments(clinic_id);
CREATE INDEX idx_assessments_patient ON assessments(patient_id);
CREATE INDEX idx_assessments_status ON assessments(approval_status);

-- ============================================================================
-- FRAME TAGS (migrated from SQLite)
-- ============================================================================
CREATE TABLE frame_tags (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    assessment_id UUID NOT NULL REFERENCES assessments(id) ON DELETE CASCADE,
    frame_number INTEGER NOT NULL,
    timestamp_ms REAL NOT NULL,
    tag_type TEXT NOT NULL,
    level INTEGER,
    locations JSONB NOT NULL DEFAULT '[]',
    note TEXT NOT NULL DEFAULT '',
    tagged_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_frame_tags_assessment ON frame_tags(assessment_id);

-- ============================================================================
-- CLINIC CODE MAPPINGS (replaces JSON file cache from fms/ehr/clinic_codes.py)
-- ============================================================================
CREATE TABLE clinic_code_mappings (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    clinic_id UUID NOT NULL REFERENCES clinics(id) ON DELETE CASCADE,
    billing_category TEXT NOT NULL,              -- e.g. "Physical Performance Testing"
    practice_code TEXT NOT NULL,                 -- e.g. "97750"
    practice_description TEXT DEFAULT '',
    modifier TEXT DEFAULT '',                    -- e.g. "GP", "59"
    unit_rate REAL DEFAULT 0,                   -- Reimbursement rate per unit
    synced_from TEXT DEFAULT 'medstatix',        -- Source of this mapping
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(clinic_id, billing_category)         -- One mapping per category per clinic
);

CREATE INDEX idx_code_mappings_clinic ON clinic_code_mappings(clinic_id);

-- ============================================================================
-- SCREENING USAGE TRACKING ($10/screening billing model)
-- ============================================================================
CREATE TABLE screening_usage (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    clinic_id UUID NOT NULL REFERENCES clinics(id),
    assessment_id UUID NOT NULL REFERENCES assessments(id),
    patient_id UUID REFERENCES patients(id),
    provider_id UUID REFERENCES providers(id),
    assessment_type TEXT NOT NULL DEFAULT 'deep_squat',
    billable BOOLEAN DEFAULT TRUE,               -- FALSE for free pilots
    amount_cents INTEGER DEFAULT 1000,            -- $10.00 = 1000 cents
    billing_period TEXT DEFAULT '',               -- e.g. "2026-03" (year-month)
    stripe_invoice_item_id TEXT DEFAULT '',       -- For Stripe reconciliation
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_screening_usage_clinic ON screening_usage(clinic_id);
CREATE INDEX idx_screening_usage_period ON screening_usage(billing_period);

-- ============================================================================
-- ROW LEVEL SECURITY (RLS)
-- ============================================================================

-- Enable RLS on all tables
ALTER TABLE clinics ENABLE ROW LEVEL SECURITY;
ALTER TABLE providers ENABLE ROW LEVEL SECURITY;
ALTER TABLE patients ENABLE ROW LEVEL SECURITY;
ALTER TABLE patient_tokens ENABLE ROW LEVEL SECURITY;
ALTER TABLE videos ENABLE ROW LEVEL SECURITY;
ALTER TABLE assessments ENABLE ROW LEVEL SECURITY;
ALTER TABLE frame_tags ENABLE ROW LEVEL SECURITY;
ALTER TABLE clinic_code_mappings ENABLE ROW LEVEL SECURITY;
ALTER TABLE screening_usage ENABLE ROW LEVEL SECURITY;

-- Providers can only see their own clinic's data
CREATE POLICY providers_own_clinic ON providers
    FOR ALL USING (
        clinic_id IN (
            SELECT clinic_id FROM providers WHERE auth_user_id = auth.uid()
        )
    );

CREATE POLICY patients_own_clinic ON patients
    FOR ALL USING (
        clinic_id IN (
            SELECT clinic_id FROM providers WHERE auth_user_id = auth.uid()
        )
    );

CREATE POLICY videos_own_clinic ON videos
    FOR ALL USING (
        clinic_id IS NULL  -- Allow non-clinical videos (climbing app)
        OR clinic_id IN (
            SELECT clinic_id FROM providers WHERE auth_user_id = auth.uid()
        )
    );

CREATE POLICY assessments_own_clinic ON assessments
    FOR ALL USING (
        clinic_id IS NULL
        OR clinic_id IN (
            SELECT clinic_id FROM providers WHERE auth_user_id = auth.uid()
        )
    );

CREATE POLICY frame_tags_own_clinic ON frame_tags
    FOR ALL USING (
        assessment_id IN (
            SELECT id FROM assessments WHERE clinic_id IS NULL
            OR clinic_id IN (
                SELECT clinic_id FROM providers WHERE auth_user_id = auth.uid()
            )
        )
    );

CREATE POLICY tokens_own_clinic ON patient_tokens
    FOR ALL USING (
        clinic_id IN (
            SELECT clinic_id FROM providers WHERE auth_user_id = auth.uid()
        )
    );

CREATE POLICY code_mappings_own_clinic ON clinic_code_mappings
    FOR ALL USING (
        clinic_id IN (
            SELECT clinic_id FROM providers WHERE auth_user_id = auth.uid()
        )
    );

CREATE POLICY usage_own_clinic ON screening_usage
    FOR ALL USING (
        clinic_id IN (
            SELECT clinic_id FROM providers WHERE auth_user_id = auth.uid()
        )
    );

-- Clinic admins can see their own clinic
CREATE POLICY clinics_own ON clinics
    FOR ALL USING (
        id IN (
            SELECT clinic_id FROM providers WHERE auth_user_id = auth.uid()
        )
    );

-- Service role bypasses all RLS (used by backend for admin operations)
-- This is handled automatically by Supabase when using the service_role key.

-- ============================================================================
-- HELPER FUNCTIONS
-- ============================================================================

-- Get the current user's clinic_id
CREATE OR REPLACE FUNCTION get_my_clinic_id()
RETURNS UUID AS $$
    SELECT clinic_id FROM providers WHERE auth_user_id = auth.uid() LIMIT 1;
$$ LANGUAGE sql SECURITY DEFINER;

-- Auto-update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER clinics_updated_at BEFORE UPDATE ON clinics FOR EACH ROW EXECUTE FUNCTION update_updated_at();
CREATE TRIGGER providers_updated_at BEFORE UPDATE ON providers FOR EACH ROW EXECUTE FUNCTION update_updated_at();
CREATE TRIGGER patients_updated_at BEFORE UPDATE ON patients FOR EACH ROW EXECUTE FUNCTION update_updated_at();
CREATE TRIGGER assessments_updated_at BEFORE UPDATE ON assessments FOR EACH ROW EXECUTE FUNCTION update_updated_at();
CREATE TRIGGER code_mappings_updated_at BEFORE UPDATE ON clinic_code_mappings FOR EACH ROW EXECUTE FUNCTION update_updated_at();
