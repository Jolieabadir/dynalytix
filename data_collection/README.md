# Dynalytics - Data Collection UI

Web interface for labeling climbing movement data to train injury prevention ML models.

## Overview

This UI allows you to:
1. **Upload** climbing videos (automatically processed for pose data)
2. **Define moves** by marking start/end frames
3. **Label moves** with type, quality, effort level, and contextual details
4. **Tag frames** with sensations (pain, instability, weakness, etc.)
5. **Export** labeled training data as ML-ready CSV
6. **Auto-cleanup** - videos are deleted after export to save storage

## Features

### ✅ Complete
- **Video Upload** - Drag & drop with automatic pose extraction via MediaPipe
- **Video Player** - Frame-by-frame controls with keyboard shortcuts
- **Move Definition** - Mark start/end frames with `[` and `]` keys
- **Move Labeling** - Two-step form with contextual questions per move type
- **Frame Tagging** - Tag specific frames with sensations and body parts
- **Skeleton Overlay** - Toggle pose visualization on video
- **Moves List** - View, edit, and delete labeled moves
- **Export System** - Combines pose CSV with labels into ML-ready format
- **Storage Management** - Videos deleted after export to save space
- **Thank You Modal** - Confirmation when labeling session is complete

### Move Types
- Static, Deadpoint, Dyno, Lock-off, Gaston, Undercling
- Drop Knee, Heel Hook, Toe Hook, Flag, Mantle, Campus

### Sensation Tags
- 🔴 Sharp Pain
- 🟠 Dull Pain  
- 🟣 Pop
- 🟡 Unstable
- 🩷 Stretch/Awkward
- 🟢 Strong/Controlled
- ⚫ Weak
- 🔵 Pumped
- 🟤 Fatigue

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `←` / `→` | Previous/Next frame |
| `Space` | Play/Pause |
| `[` | Mark move start |
| `]` | Mark move end |
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

2. Define Moves
   └── Mark frame boundaries → SQLite database

3. Label Moves
   └── Type, quality, effort, contextual data → SQLite database

4. Tag Frames
   └── Sensations, body parts, intensity → SQLite database

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
- `POST /api/videos/{id}/export` - Export labeled data (with optional video deletion)

### Moves
- `POST /api/moves` - Create move
- `GET /api/videos/{id}/moves` - Get moves for video
- `PUT /api/moves/{id}` - Update move
- `DELETE /api/moves/{id}` - Delete move

### Frame Tags
- `POST /api/frame-tags` - Create frame tag
- `GET /api/moves/{id}/frame-tags` - Get tags for move
- `DELETE /api/frame-tags/{id}` - Delete tag

## Project Structure

```
data_collection/
├── backend/
│   ├── src/
│   │   ├── labeling/
│   │   │   ├── models.py      # Video, Move, FrameTag dataclasses
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
        │   ├── MoveForm.jsx
        │   ├── TaggingMode.jsx
        │   ├── DoneButton.jsx
        │   └── ThankYouModal.jsx
        ├── api/
        │   ├── client.js
        │   └── ExportService.js
        └── store/
            └── useStore.js    # Zustand state management
```

## Future Improvements

- [ ] Multiple tags per frame in export
- [ ] Undo/Redo for tagging actions
- [ ] Batch video processing
- [ ] Progress indicator for labeling sessions
- [ ] Skeleton overlay scaling fix

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

**Best for:** Standardized assessments with published scoring criteria (FMS, Y-Balance, movement screens)

### Data-Labeled ML

Required for **climbing injury prevention** because movement patterns are complex and subjective:

- No standardized "correct" form for dynamic movements
- Risk factors are subtle and context-dependent
- Individual variation in safe movement patterns
- Injury indicators may involve timing, load distribution, and fatigue patterns

**Requirements:**
- 500-2000+ labeled examples for reliable predictions
- Diverse dataset covering different climbers, styles, and conditions
- Expert labelers who can identify subtle risk patterns

**Advantages:**
- Can catch patterns humans might miss
- Learns from real-world injury correlation data
- Handles complex, multi-factor assessments
- Improves over time with more data

**Best for:** Complex movement analysis, injury prediction, performance optimization

## Recommended Approach for FMS

### Start Rule-Based, Validate with Data

The most efficient path for FMS scoring:

1. **Build rules from FMS criteria**
   - Translate the official FMS scoring manual into pose-based rules
   - Use joint angles, body segment alignment, and timing from MediaPipe data
   - Implement each test's specific scoring thresholds

2. **Have PTs review AI predictions**
   - Run the rule engine on sample videos
   - PTs mark where they agree/disagree with automated scores
   - Focus review time on borderline cases (e.g., score 2 vs 3)

3. **Collect targeted training data only where rules fail**
   - Identify systematic disagreements between rules and PT scores
   - These edge cases become your training data
   - May only need 50-100 examples per problematic pattern

4. **Hybrid system**
   - Rules handle clear-cut cases (majority of assessments)
   - ML model handles ambiguous cases flagged by rules
   - Continuous improvement as edge cases are identified

This approach minimizes labeling effort while maximizing accuracy where it matters most.

