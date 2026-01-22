# Dynalytics - FMS Assessment Data Collection

Web interface for labeling FMS (Functional Movement Screen) assessment data.

## Overview

This UI allows you to:
1. **Upload** assessment videos (automatically processed for pose data)
2. **Define assessments** by marking start/end frames
3. **Score assessments** using FMS 0-3 scale
4. **Tag frames** with observations (pain, compensation, weakness, etc.)
5. **Export** labeled training data as ML-ready CSV

## Features

### Assessment Modes

**Quick Mode (Default)**
- FMS Score buttons (0-3)
- Pain checkbox (auto-sets score to 0)
- Notes field
- Best for rapid labeling by experienced PTs

**Detailed Mode**
- All scoring criteria observations
- Compensation pattern checkboxes
- Full clinical notes
- Best for training data collection and edge case documentation

### FMS Scoring Scale

| Score | Label | Description |
|-------|-------|-------------|
| 3 | Perfect | Performs movement correctly without compensation |
| 2 | Compensation | Completes movement with compensation patterns |
| 1 | Cannot Complete | Unable to complete the movement pattern |
| 0 | Pain | Pain reported during any part of the movement |

### Deep Squat Scoring Criteria

- Dowel position (overhead aligned / forward / lost)
- Torso alignment (parallel to tibia / forward lean)
- Knee alignment (over toes / valgus)
- Squat depth (below/at/above parallel)
- Heel contact (down / rise / elevated)
- Femur position (below/at/above horizontal)

### Compensation Patterns

- Heel Rise
- Excessive Forward Lean
- Knee Valgus
- Arms Fall Forward
- Lumbar Flexion

### Observation Tags

- Pain
- Tightness
- Weakness
- Asymmetry
- Compensation
- Loss of Balance

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `←` / `→` | Previous/Next frame |
| `Space` | Play/Pause |
| `[` | Mark assessment start |
| `]` | Mark assessment end |
| `S` | Toggle skeleton overlay |

## Setup

### Backend
```bash
cd data_collection/backend
source ../../venv/bin/activate
pip install -r requirements.txt
uvicorn src.web.api:app --reload --port 8000
```

### Frontend
```bash
cd data_collection/frontend
npm install
npm run dev
```

- Backend: http://localhost:8000
- Frontend: http://localhost:5173
- API Docs: http://localhost:8000/docs

## Data Flow

```
1. Upload Video
   └── Pose extraction (MediaPipe) → data/{video}.csv

2. Define Assessment
   └── Mark frame boundaries → SQLite database

3. Score Assessment
   └── FMS score, criteria, compensations → SQLite database

4. Tag Frames (optional)
   └── Observations, body parts, intensity → SQLite database

5. Export (Done button)
   └── Merge pose CSV + labels → data/exports/{video}_labeled.csv
   └── Delete video file to save storage
```

## Exported CSV Format

The labeled CSV contains:
- **Pose data**: frame_number, timestamp, joint angles, landmark positions
- **Assessment labels**: assessment_id, test_type, score, compensations
- **Frame tags**: tag_type, tag_level, tag_locations, tag_note

Example row with labels:
```csv
frame,timestamp_ms,...,assessment_id,test_type,score,compensations,tag_type,tag_level,tag_locations,tag_note
29,964.01,...,7,deep_squat,2,heel_rise,weakness,5,left_knee,
```

## API Endpoints

### Videos
- `POST /api/videos/upload` - Upload & process video
- `GET /api/videos` - List all videos
- `GET /api/videos/{id}` - Get video details
- `POST /api/videos/{id}/export` - Export labeled data

### Assessments
- `POST /api/assessments` - Create assessment
- `GET /api/videos/{id}/assessments` - Get assessments for video
- `PUT /api/assessments/{id}` - Update assessment
- `DELETE /api/assessments/{id}` - Delete assessment

### Frame Tags
- `POST /api/frame-tags` - Create frame tag
- `GET /api/assessments/{id}/frame-tags` - Get tags for assessment
- `DELETE /api/frame-tags/{id}` - Delete tag

## Project Structure

```
data_collection/
├── backend/
│   ├── src/
│   │   ├── labeling/
│   │   │   ├── models.py      # Video, Assessment, FrameTag dataclasses
│   │   │   ├── database.py    # SQLite operations
│   │   │   └── exporter.py    # CSV export logic
│   │   └── web/
│   │       └── api.py         # FastAPI routes
│   ├── data/
│   │   ├── labels.db          # SQLite database
│   │   └── exports/           # Labeled CSV files
│   └── videos/                # Uploaded videos (temporary)
│
└── frontend/
    └── src/
        ├── components/
        │   ├── VideoUpload.jsx
        │   ├── VideoPlayer.jsx
        │   ├── MovesList.jsx
        │   ├── MoveForm.jsx      # Quick Mode + Detailed Mode
        │   ├── TaggingMode.jsx
        │   ├── DoneButton.jsx
        │   └── ThankYouModal.jsx
        ├── api/
        │   ├── client.js
        │   └── ExportService.js
        └── store/
            └── useStore.js    # Zustand state management
```

## Model Training Approaches

### Rule-Based Engine

Best for **FMS assessments** because the scoring criteria are explicit and well-defined. The FMS manual provides specific, measurable criteria that can be directly translated into rules:

- Example: "torso parallel to tibia + femur below horizontal = score 3"
- Example: "heels lift off floor during squat = score 2 maximum"
- Example: "loss of balance at any point = score 1"

**Advantages:**
- Works immediately without training data
- 100% explainable - can show exactly why a score was given
- Easy to audit and adjust based on PT feedback
- PTs only need to validate edge cases, not label thousands of videos

### Data-Labeled ML

Required for **complex movement analysis** where patterns are subjective:

- No standardized "correct" form
- Risk factors are subtle and context-dependent
- Individual variation in safe movement patterns

**Requirements:**
- 500-2000+ labeled examples for reliable predictions
- Diverse dataset covering different body types and conditions
- Expert labelers who can identify subtle patterns

## Recommended Approach for FMS

### Start Rule-Based, Validate with Data

1. **Build rules from FMS criteria**
   - Translate the official FMS scoring manual into pose-based rules
   - Use joint angles, body segment alignment, and timing from MediaPipe data

2. **Have PTs review AI predictions**
   - Run the rule engine on sample videos
   - PTs mark where they agree/disagree with automated scores

3. **Collect targeted training data only where rules fail**
   - Identify systematic disagreements between rules and PT scores
   - These edge cases become your training data

4. **Hybrid system**
   - Rules handle clear-cut cases (majority of assessments)
   - ML model handles ambiguous cases flagged by rules

This approach minimizes labeling effort while maximizing accuracy where it matters most.
