# Dynalytix - FMS Assessment Automation

AI-powered movement screening to automate Functional Movement Screen (FMS) assessments.

## Website
https://www.dynalytics.org/

## What This Does

Dynalytix uses computer vision to analyze movement patterns from video, automatically scoring FMS assessments that currently require manual observation by trained professionals.

### Current Demo: Deep Squat Assessment

- Upload video of deep squat test
- Automatic pose extraction (joint angles, body position)
- Score 0-3 based on FMS criteria
- Quick Mode for fast labeling, Detailed Mode for full criteria capture

## Model Training Approaches

### Rule-Based Engine (Recommended for FMS)

FMS scoring criteria are explicit and well-defined, making a rule-based approach viable:

- "Torso parallel to tibia + femur below horizontal + knees over feet = Score 3"
- Works immediately without training data
- PTs validate edge cases rather than label everything

### Data-Labeled ML (Used for complex movements)

For subjective assessments like climbing injury risk, we use ML trained on labeled data. This requires 500-2000+ labeled examples but catches subtle patterns rules might miss.

### Recommended Path for FMS

1. Build rule engine from FMS scoring criteria
2. Have PTs review sample of AI predictions
3. Collect targeted training data only where rules fail
4. Hybrid: rules + ML for edge cases

## Tech Stack

- **Pose Estimation:** MediaPipe
- **Data Collection UI:** React + FastAPI
- **Tracking:** 12 joint angles per frame

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

### Web UI: FMS Assessment Labeling

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

**Workflow:**
1. Upload a deep squat assessment video
2. Mark assessment boundaries with `[` and `]` keys
3. Score using FMS 0-3 scale (Quick Mode or Detailed Mode)
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

## FMS Scoring Scale

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

## Broader Applications

While currently demonstrating FMS assessment, the methodology applies to:
- **Movement Screens:** FMS, Y-Balance, overhead squat assessment
- **Sports Analysis:** Form analysis for any sport
- **Rehabilitation:** Physical therapy movement tracking
- **Injury Prevention:** Pattern recognition across any repetitive movement

## License

MIT

---

Development by [@jolieabadir](https://github.com/jolieabadir)
