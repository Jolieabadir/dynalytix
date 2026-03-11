# Dynalytix - Backend API

FastAPI backend for the data collection UI.

## Architecture

```
src/
├── labeling/           # Data layer (pure Python)
│   ├── models.py       # Dataclasses (Video, Move, FrameTag)
│   ├── database.py     # SQLite operations
│   ├── exporter.py     # CSV export with label merging
│   └── __init__.py
└── web/                # API layer
    ├── api.py          # FastAPI routes
    └── __init__.py
```

**Key Design Principles:**
- ✅ **Clear encapsulation** - Models know nothing about database, database knows nothing about API
- ✅ **Easy iteration** - Change one layer without affecting others
- ✅ **Testable** - Each layer can be tested independently

## Setup

```bash
# Install dependencies
pip install -r requirements.txt

# Run API server
uvicorn src.web.api:app --reload --port 8000
```

## API Documentation

Once running, visit:
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

## API Endpoints

### Configuration
```
GET  /api/config                    # Get move types, questions, body parts, tag types
```

### Videos
```
POST /api/videos/upload             # Upload & process video (runs pose extraction)
GET  /api/videos                    # List all videos
GET  /api/videos/{id}               # Get video details
GET  /api/videos/{id}/csv           # Download raw pose CSV
POST /api/videos/{id}/export        # Export labeled CSV (optional: ?delete_video=true)
GET  /api/videos/{id}/export/download  # Download exported labeled CSV
```

### Moves
```
POST /api/moves                     # Create move
GET  /api/moves/{id}                # Get move details
PUT  /api/moves/{id}                # Update move
DELETE /api/moves/{id}              # Delete move (+ frame tags)
GET  /api/videos/{id}/moves         # Get all moves for video
```

### Frame Tags
```
POST /api/frame-tags                # Create frame tag
GET  /api/moves/{id}/frame-tags     # Get frame tags for move
DELETE /api/frame-tags/{id}         # Delete frame tag
```

### FMS Reports
```
GET  /api/fms/report/{video_id}        # Patient-facing report (no billing codes)
GET  /api/fms/findings/{video_id}      # Provider-facing report (full data + CPT codes)
GET  /api/fms/findings/{video_id}/csv  # Download findings CSV
```

## Export System

The export endpoint merges pose data with labels:

```
POST /api/videos/{id}/export?delete_video=true
```

**Process:**
1. Reads raw pose CSV (`data/{video}.csv`)
2. Fetches moves and frame tags from database
3. Merges by frame number
4. Outputs to `data/exports/{video}_labeled.csv`
5. Optionally deletes video file to save storage

**Exported columns added:**
- `move_id`, `move_type`, `form_quality`, `effort_level`
- `tag_type`, `tag_level`, `tag_locations`, `tag_note`

## Data Models

### Video
```json
{
    "id": 1,
    "filename": "climb.mov",
    "path": "videos/climb.mov",
    "csv_path": "data/climb.csv",
    "fps": 30.0,
    "total_frames": 900,
    "duration_ms": 30000.0,
    "uploaded_at": "2026-01-14T19:30:00"
}
```

### Move
```json
{
    "id": 1,
    "video_id": 1,
    "frame_start": 150,
    "frame_end": 200,
    "timestamp_start_ms": 5000.0,
    "timestamp_end_ms": 6666.7,
    "move_type": "dyno",
    "form_quality": 4,
    "effort_level": 7,
    "contextual_data": {
        "catching_hand": "right_hand",
        "push_foot": "left_foot"
    },
    "tags": ["controlled"],
    "description": "Big move from left foot",
    "labeled_at": "2026-01-14T19:35:00",
    "frame_tag_count": 2
}
```

### Frame Tag
```json
{
    "id": 1,
    "move_id": 1,
    "frame_number": 155,
    "timestamp_ms": 5166.7,
    "tag_type": "sharp_pain",
    "level": 6,
    "locations": ["Left Elbow"],
    "note": "Sharp pain on push",
    "tagged_at": "2026-01-14T19:36:00"
}
```

## Move Types

Defined in `models.py`:
- static, deadpoint, dyno, lock_off, gaston, undercling
- drop_knee, heel_hook, toe_hook, flag, mantle, campus

Each has contextual questions that appear in the labeling form.

## Tag Types

- `sharp_pain`, `dull_pain`, `pop`, `unstable`, `stretch_awkward`
- `strong_controlled`, `weak`, `pumped`, `fatigue`

## Database

SQLite at `data/labels.db`:

```sql
videos: id, filename, path, csv_path, fps, total_frames, duration_ms, uploaded_at

moves: id, video_id, frame_start, frame_end, timestamp_start_ms, timestamp_end_ms,
       move_type, form_quality, effort_level, contextual_data, tags, description, labeled_at

frame_tags: id, move_id, frame_number, timestamp_ms, tag_type, level, locations, note, tagged_at
```

## Directory Structure

```
backend/
├── data/
│   ├── labels.db              # SQLite database
│   ├── {video}.csv            # Raw pose data
│   └── exports/
│       └── {video}_labeled.csv  # Exported labeled data
├── videos/                    # Uploaded videos (deleted after export)
├── src/
│   ├── labeling/
│   └── web/
└── requirements.txt
```

## Error Handling

- `200` - Success
- `201` - Created
- `204` - No Content (delete)
- `400` - Bad Request
- `404` - Not Found
- `500` - Internal Server Error