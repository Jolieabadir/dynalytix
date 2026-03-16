# Movement Assessment Engine

Automated scoring, clinical reporting, and billing for movement assessments.

## Architecture

```
fms/
├── scoring/
│   ├── deep_squat.py       # Rule engine: CSV → score (0-3) + criteria details
│   └── thresholds.py       # Angle thresholds (tunable, research-backed)
├── reporting/
│   ├── report_generator.py # LLM API calls → clinical narrative + billing descriptions
│   └── templates.py        # Prompt templates for the LLM
├── billing/
│   └── cpt_codes.py        # Billing categories + rule-based suggestions
│                            #   BillingDescription (base tier, no CPT codes)
│                            #   CPTSuggestion (Pro tier, behind include_cpt_codes flag)
├── ehr/                     # EHR integration layer (stubs)
│   ├── payload.py           # Standardized payload schema (Dynalytix → MedStatix contract)
│   ├── adapter.py           # Abstract gateway interface
│   ├── medstatix.py         # MedStatix gateway (stub, awaiting API docs)
│   └── events.py            # Webhook event types from MedStatix
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

## API Endpoints

### Assessment Reports
```
GET  /api/fms/report/{video_id}              # Patient-facing report (no billing codes)
GET  /api/fms/findings/{video_id}            # Provider report (billing categories + practice_code slots)
GET  /api/fms/findings/{video_id}?cpt=true   # Provider report with CPT codes (Pro tier)
GET  /api/fms/findings/{video_id}/csv        # Download findings as CSV
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
from fms.pipeline import run_quick

result = run_quick("path/to/exported.csv")
# Returns: score, criteria, billing_descriptions (with practice_code slots)

# Build EHR payload:
from fms.ehr.payload import AssessmentPayload
payload = AssessmentPayload.from_pipeline_result(result)
```
