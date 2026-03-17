# Dynalytix - Movement Assessment Automation

AI-powered movement screening to automate functional movement assessments.

## Website
https://www.dynalytix.org/

## What This Does

Dynalytix uses computer vision to analyze movement patterns from video, automatically scoring movement assessments that currently require manual observation by trained professionals.

### Current Demo: Deep Squat Assessment

- Upload video of deep squat test
- Automatic pose extraction (joint angles, body position)
- Score 0-3 based on movement assessment criteria
- Quick Mode for fast labeling, Detailed Mode for full criteria capture

## Current Status

### Phase 1: Pose Extraction (Complete)
- [x] MediaPipe integration for pose landmark extraction
- [x] 12 joint angles tracked per frame
- [x] CLI tool for batch processing
- [x] CSV export with timestamps

### Phase 2: Data Collection UI (Complete)
- [x] Video upload with automatic pose extraction
- [x] Assessment boundary marking
- [x] Movement scoring (Quick Mode + Detailed Mode)
- [x] Frame tagging for observations
- [x] Labeled data export

### Phase 3: Movement Scoring Engine (Complete) ✅
- [x] Rule-based Deep Squat scoring engine (0-3)
- [x] Scoring criteria: squat depth, torso-tibia alignment, knee-over-foot alignment, heel position, lumbar flexion control
- [x] Bilateral asymmetry detection
- [x] Auto-scoring on export (hooks into data collection pipeline)
- [x] Findings saved as CSV and JSON
- [x] Descriptive billing categories with practice code placeholder slots
- [x] Patient-facing report API (no billing codes, with disclaimer)
- [x] Provider-facing report API (billing categories + practice code slots)
- [x] Post-export UI with Patient Report and Provider Report views
- [x] LLM clinical report generation (stub, requires API key)
- [x] Clinical + billing disclaimers on all reports
- [x] EHR integration stubs (MedStatix gateway, payload schema, webhooks)
- [x] Clinic code sync and auto-mapping (codes pre-filled before provider review)
- [x] Provider approval workflow (draft → approved → pushed, FDA CDS compliant)
- [x] Dual-angle processing (front + side views scored independently, merged at criterion level)
- [ ] Threshold calibration against PT-scored videos
- [ ] MedStatix EHR integration go-live
- [ ] Additional movement assessments (hurdle step, inline lunge, etc.)

### Phase 4: Patient-Facing Assessment Flow (Complete) ✅
- [x] Dual-angle video upload (front view → side view, with skip option)
- [x] Client-side pose extraction (MediaPipe JS, video never leaves browser)
- [x] Video review screen with dual video display (both angles side-by-side)
- [x] Skeleton overlay on both videos with frame-by-frame scrubbing
- [x] Toggle skeleton visibility per video
- [x] Auto-scoring runs in background while patient reviews videos
- [x] "View Results" button (user controls transition, no auto-redirect)
- [x] Results page with score, criteria cards, bilateral differences, billing categories
- [x] Back navigation throughout (Re-upload ← Review ← Results)
- [x] "Start New Assessment" to reset flow

## Model Training Approaches

### Rule-Based Engine (Recommended for Movement Assessments)

Movement scoring criteria are explicit and well-defined, making a rule-based approach viable:

- "Torso parallel to tibia + femur below horizontal + knees over feet = Score 3"
- Works immediately without training data
- PTs validate edge cases rather than label everything

### Data-Labeled ML (Used for complex movements)

For subjective assessments like climbing injury risk, we use ML trained on labeled data. This requires 500-2000+ labeled examples but catches subtle patterns rules might miss.

### Recommended Path for Movement Assessments

1. Build rule engine from movement scoring criteria
2. Have PTs review sample of AI predictions
3. Collect targeted training data only where rules fail
4. Hybrid: rules + ML for edge cases

## Tech Stack

**Phase 1-2 (Complete):**
- **Pose Estimation:** MediaPipe
- **Data Collection UI:** React + FastAPI
- **Tracking:** 12 joint angles per frame

**Phase 3 (Complete):**
- **Movement Scoring:** Rule-based engine with research-backed thresholds
- **Reporting:** Anthropic Claude API (optional, for clinical narratives)
- **Billing:** Descriptive billing categories with practice code slots (CPT codes behind Pro flag)
- **EHR Integration:** MedStatix gateway stubs (Dynalytix → MedStatix → EHR)
- **Disclaimers:** Clinical + billing disclaimers on all generated reports

## Tracked Measurements

### Joint Angles (12 per frame)
| Angle | Points | What it measures |
|-------|--------|------------------|
| Left elbow | shoulder → elbow → wrist | Arm bend |
| Right elbow | shoulder → elbow → wrist | Arm bend |
| Left shoulder | hip → shoulder → elbow | Arm raise relative to torso |
| Right shoulder | hip → shoulder → elbow | Arm raise relative to torso |
| Left hip | shoulder → hip → knee | Leg position relative to torso |
| Right hip | shoulder → hip → knee | Leg position relative to torso |
| Left knee | hip → knee → ankle | Leg bend |
| Right knee | hip → knee → ankle | Leg bend |
| Left ankle | knee → ankle → heel | Foot flex |
| Right ankle | knee → ankle → heel | Foot flex |
| Upper back | left shoulder → shoulder midpoint → right shoulder | Shoulder hunch/openness |
| Lower back | shoulder midpoint → hip midpoint → knee midpoint | Torso arch/round |

## Installation

```bash
git clone https://github.com/jolieabadir/dynalytics.git
cd dynalytics
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

> Note: Requires Python 3.11 (MediaPipe doesn't support 3.13+ yet)

## Usage

### CLI: Extract Pose Data

```bash
# Basic usage - outputs angles and speeds to CSV
python main.py path/to/video.mov

# Include raw landmark positions
python main.py path/to/video.mov --landmarks

# Specify output path
python main.py path/to/video.mov --output my_data.csv
```

### Web UI: Movement Assessment Labeling

```bash
# Terminal 1 - Backend
cd data_collection/backend
source ../../venv/bin/activate
uvicorn src.web.api:app --reload --port 8000

# Terminal 2 - Frontend
cd data_collection/frontend
npm install  # first time only
npm run dev
```

Open http://localhost:5173

**Patient Assessment Flow (fms-demo branch):**
1. Upload front view video → poses extracted in browser
2. Upload side view video (or skip for single-angle)
3. Review both videos with skeleton overlays, scrub through frames
4. Scoring runs automatically in background
5. Click "View Results" to see score, criteria, and recommendations
6. Use back buttons to review videos or start new assessment

**Data Collection Flow (main branch):**
1. Upload a deep squat assessment video
2. Mark assessment boundaries with `[` and `]` keys
3. Score using 0-3 movement assessment scale (Quick Mode or Detailed Mode)
4. Optionally tag specific frames with observations
5. Click "Done" to export labeled data

**Keyboard Shortcuts:**
| Key | Action |
|-----|--------|
| `←` / `→` | Previous/Next frame |
| `Space` | Play/Pause |
| `[` | Mark assessment start |
| `]` | Mark assessment end |
| `S` | Toggle skeleton overlay |

## Movement Scoring Scale

| Score | Label | Description |
|-------|-------|-------------|
| 3 | Perfect | Performs movement correctly without compensation |
| 2 | Compensation | Completes movement with compensation patterns |
| 1 | Cannot Complete | Unable to complete the movement pattern |
| 0 | Pain | Pain reported during any part of the movement |

## Project Structure

```
dynalytics/
├── src/                        # Core pose analysis
│   ├── core/                   # Landmark and angle classes
│   ├── pose/                   # MediaPipe wrapper
│   ├── analysis/               # Joint angle calculations
│   └── export/                 # CSV export
├── fms/                        # Movement scoring engine
│   ├── scoring/
│   │   ├── deep_squat.py       # Rule engine (CSV → score 0-3)
│   │   ├── dual_angle.py       # Dual-angle scoring (front + side views)
│   │   └── thresholds.py       # Angle thresholds (tunable)
│   ├── reporting/
│   │   ├── report_generator.py # LLM-powered clinical reports
│   │   └── templates.py        # Prompt templates
│   ├── billing/
│   │   └── cpt_codes.py        # Billing categories + CPT code suggestions
│   ├── ehr/                    # EHR integration (MedStatix gateway)
│   │   ├── payload.py          # Assessment payload schema (→ MedStatix)
│   │   ├── adapter.py          # Abstract gateway interface
│   │   ├── medstatix.py        # MedStatix gateway (stub)
│   │   ├── events.py           # Webhook event types
│   │   ├── clinic_codes.py     # Local cache of clinic billing code mappings
│   │   └── approval.py         # Provider approval workflow
│   ├── disclaimer.py           # Clinical + billing disclaimers
│   ├── integration.py          # FastAPI hooks + auto-run on export
│   └── pipeline.py             # CLI: CSV → score + report + billing
├── data_collection/
│   ├── backend/                # FastAPI server
│   │   ├── src/
│   │   │   ├── labeling/       # Assessment models & database
│   │   │   └── web/            # REST API
│   │   └── data/               # SQLite DB & exports
│   └── frontend/               # React app
│       └── src/
│           ├── components/     # UI components
│           ├── api/            # API client
│           └── store/          # Zustand state
├── main.py                     # CLI pose extraction
└── visualizer_live.py          # Video player with overlay
```

## Data Pipeline

```
Raw Video
    ↓
Dynalytix (pose extraction)
    ↓
Raw Angles CSV
    ↓
+ Labels (via Data Collection UI)
    ↓
Labeled Data CSV
    ↓
Movement Scoring Engine (auto-runs on export)
    ↓
├── Findings CSV + JSON
├── Patient Report (no billing codes, with disclaimer)
├── Provider Report (billing categories + practice code slots)
├── → EHR Push via MedStatix (when connected)
    ↓
ML Training (future)
```

## Broader Applications

While currently demonstrating the deep squat assessment, the methodology applies to:
- **Movement Screens:** Deep squat, Y-Balance, overhead squat assessment
- **Sports Analysis:** Form analysis for any sport
- **Rehabilitation:** Physical therapy movement tracking
- **Injury Prevention:** Pattern recognition across any repetitive movement

## License

MIT

---

Development by [@jolieabadir](https://github.com/jolieabadir)
