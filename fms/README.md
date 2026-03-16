# Movement Assessment Engine

Automated scoring, clinical reporting, and billing for movement assessments.

## Architecture

```
fms/
├── scoring/
│   ├── deep_squat.py       # Rule engine: CSV → score (0-3) + criteria details
│   ├── dual_angle.py       # Dual-angle scoring (front + side views merged)
│   └── thresholds.py       # Angle thresholds (tunable, research-backed)
├── reporting/
│   ├── report_generator.py # LLM API calls → clinical narrative + billing descriptions
│   └── templates.py        # Prompt templates for the LLM
├── billing/
│   └── cpt_codes.py        # Billing categories + rule-based suggestions
│                            #   BillingDescription (base tier, no CPT codes)
│                            #   CPTSuggestion (Pro tier, behind include_cpt_codes flag)
├── ehr/                     # EHR integration layer
│   ├── payload.py           # Standardized payload schema (Dynalytix → MedStatix contract)
│   ├── adapter.py           # Abstract gateway interface
│   ├── medstatix.py         # MedStatix gateway (stub, awaiting API docs)
│   ├── events.py            # Webhook event types from MedStatix
│   ├── clinic_codes.py      # Local cache of clinic billing code mappings (auto-mapping)
│   └── approval.py          # Provider approval workflow (draft → approved → pushed)
├── disclaimer.py            # Clinical + billing disclaimers (required on all reports)
├── pipeline.py              # Ties it all together: CSV → score + report + billing
├── integration.py           # FastAPI routes + auto-run on export
└── __main__.py              # CLI entry point
```

## Two Modes

### Quick Mode (no API key needed)
```bash
python -m fms.pipeline path/to/video_labeled.csv
```
Runs the rule engine + rule-based billing categories. Instant results.

### Full Mode (requires Anthropic API key)
```bash
export ANTHROPIC_API_KEY=your-key-here
python -m fms.pipeline path/to/video_labeled.csv --full-report
```
Adds LLM-generated clinical narrative + smarter billing suggestions.

## Options
```
--pain          Flag that patient reported pain (auto-scores 0)
--json          Output raw JSON
--output FILE   Save results to a file
--full-report   Enable LLM-powered clinical report generation
--cpt           Include CPT codes in output (Pro tier, requires AMA license)
--front-csv     Path to front view CSV (dual-angle mode)
--side-csv      Path to side view CSV (dual-angle mode)
```

## Dual-Angle Processing

The patient performs the squat **twice** — once filmed from the front, once from
the side. These are two separate performances, not simultaneous recordings.

Each recording is scored independently, then merged at the criterion level:

| Criterion | Preferred View | Reason |
|-----------|---------------|--------|
| Squat Depth | Side | Sagittal plane knee flexion more accurate |
| Torso-Tibia Alignment | Side | Sagittal trunk/tibia inclination |
| Knee-Over-Foot Alignment | Front | Frontal plane valgus/varus |
| Heel Position | Side | Ankle dorsiflexion visibility |
| Lumbar Flexion Control | Side | Sagittal trunk angle change |
| Bilateral Differences | Front | Frontal plane asymmetry |

### CLI Usage
```bash
# Dual-angle (both views)
python -m fms.pipeline --front-csv front_video.csv --side-csv side_video.csv

# Single view only (falls back to that view for all criteria)
python -m fms.pipeline --side-csv side_video.csv

# With options
python -m fms.pipeline --front-csv front.csv --side-csv side.csv --pain --json
```

### API Usage
```
POST /api/fms/score-dual?front_video_id=123&side_video_id=456
```

### Python Usage
```python
from fms.pipeline import run_quick_dual

# Both views
result = run_quick_dual(
    front_csv_path="front.csv",
    side_csv_path="side.csv",
)
# result["view_sources"] shows which view was used for each criterion

# Single view (falls back)
result = run_quick_dual(side_csv_path="side.csv")
```

## Billing Model

Reports use **descriptive billing categories** by default (no CPT codes):
- "Physical Performance Testing" instead of "97750"
- "Therapeutic Exercise" instead of "97110"

Each billing item includes a `practice_code` placeholder field (initially `null`).
When MedStatix EHR integration is live, this field is populated with the
clinic's own code for that service category.

CPT codes are available behind the `--cpt` flag or `?cpt=true` API parameter
(Pro tier, requires AMA license).

## EHR Integration

**Architecture:** `Dynalytix → MedStatix Gateway → EHR`

Dynalytix never talks to EHR systems directly. We push a standardized
`AssessmentPayload` (defined in `fms/ehr/payload.py`) to MedStatix, and they handle:
- Patient lookup in the clinic's EHR
- Mapping billing categories to the clinic's own codes (fills `practice_code` slots)
- Formatting clinical narrative for the clinic's documentation template
- Pushing the assessment into the patient's chart

**Status:** Stub. Awaiting MedStatix API docs and sandbox credentials.

**Webhook events:** MedStatix POSTs to `/api/ehr/webhook` for events like
push confirmations, patient scheduling, and code mapping updates.
See `fms/ehr/events.py` for event types.

## Clinic Code Sync & Auto-Mapping

When a clinic connects via MedStatix, their billing code mappings are synced
to Dynalytix and cached locally (`data/clinic_codes/{clinic_id}.json`).

Every assessment auto-maps billing categories to the clinic's own codes
**before** the provider sees the results. The provider doesn't manually select
codes — they just click "approve."

**Flow:**
1. Clinic connects via MedStatix, code mappings are synced
2. Patient films assessment at home
3. Scoring pipeline runs, billing categories auto-mapped
4. Provider opens dashboard, sees pre-filled codes
5. Provider clicks approve → ready for EHR push

**Sync triggers:**
- MedStatix webhook: `clinic.code_mapping_updated`
- Manual: `POST /api/ehr/clinic/{clinic_id}/sync-codes`

## Provider Approval Workflow

Every assessment follows this lifecycle:

```
draft → provider_review → approved (or rejected) → pushed
```

The provider **must** review and approve before results can be pushed to the
patient's chart. This is required for FDA CDS exemption (Criterion 4: the HCP
independently reviews the basis for the recommendation).

**Statuses:**
- `draft` — Scoring complete, not yet reviewed by provider
- `provider_review` — Provider has opened/viewed the assessment
- `approved` — Provider approved, ready for EHR push
- `rejected` — Provider rejected, needs re-assessment or manual override
- `pushed` — Successfully pushed to patient's EHR chart

**Storage:** JSON sidecar files in `data/exports/fms_findings/{stem}_approval.json`
(Future: migrate to PostgreSQL when chart DB is built)

## API Endpoints

### Assessment Reports
```
GET  /api/fms/report/{video_id}              # Patient-facing report (no billing codes)
GET  /api/fms/findings/{video_id}            # Provider report (includes approval status)
GET  /api/fms/findings/{video_id}?cpt=true   # Provider report with CPT codes (Pro tier)
GET  /api/fms/findings/{video_id}/csv        # Download findings as CSV
POST /api/fms/score-dual                     # Score dual-angle (front + side videos)
```

### Provider Approval
```
GET  /api/fms/findings/{video_id}/approval   # Get approval status
POST /api/fms/findings/{video_id}/approve    # Provider approves (requires provider_id)
POST /api/fms/findings/{video_id}/reject     # Provider rejects (requires provider_id)
POST /api/fms/findings/{video_id}/mark-reviewed  # Mark as viewed by provider
```

### Clinic Code Sync
```
POST /api/ehr/clinic/{clinic_id}/sync-codes  # Sync code mappings for a clinic
GET  /api/ehr/clinic/{clinic_id}/codes       # Get cached code mappings
GET  /api/ehr/clinics                        # List all clinics with cached mappings
DELETE /api/ehr/clinic/{clinic_id}/codes     # Delete cached code mappings
```

### EHR Integration (stubs — return 501 until MedStatix is live)
```
POST /api/ehr/push/{video_id}                # Push assessment to EHR via MedStatix
POST /api/ehr/map-codes/{video_id}           # Preview code mapping for a clinic
GET  /api/ehr/clinic/{clinic_id}/config      # Get clinic's EHR configuration
POST /api/ehr/webhook                        # Receive events from MedStatix
GET  /api/ehr/status/{gateway_request_id}    # Check push status
```

## Threshold Tuning

Thresholds in `scoring/thresholds.py` are from Butler et al. 2010 and Heredia et al. 2021.
Calibrate against PT-scored videos:
1. Record 10-20 deep squat videos
2. Have a certified PT score each one (1, 2, or 3)
3. Run each through the engine, compare, adjust thresholds

## Integration

```python
from fms.pipeline import run_quick, run_quick_dual

# Single-angle (basic usage)
result = run_quick("path/to/exported.csv")

# Single-angle with auto-mapping for a clinic
result = run_quick("path/to/exported.csv", clinic_id="clinic_abc123")
# Returns: score, criteria, billing_descriptions (with practice_code filled in)

# Dual-angle scoring (front + side views)
result = run_quick_dual(
    front_csv_path="front_video.csv",
    side_csv_path="side_video.csv",
    clinic_id="clinic_abc123",
)
# Returns: merged score, view_sources dict, front_score, side_score

# Build EHR payload (works with both single and dual-angle):
from fms.ehr.payload import AssessmentPayload
payload = AssessmentPayload.from_pipeline_result(result)
# payload.dual_angle, payload.view_sources, payload.front_score, payload.side_score

# Check/update approval status:
from fms.ehr.approval import get_approval, approve
approval = get_approval("video_abc123_labeled")
if approval.status.value == "draft":
    approve("video_abc123_labeled", provider_id="dr_smith", provider_name="Dr. Smith")
```
