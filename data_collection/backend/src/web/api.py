"""
FastAPI application for FMS assessment data collection.

Clean REST API with proper error handling and validation.
"""
from fastapi import FastAPI, UploadFile, File, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from typing import List, Optional
from pathlib import Path
from datetime import datetime
import shutil
import sys
import subprocess

from ..labeling.database import Database
from ..labeling.models import (
    Video, Assessment, FrameTag,
    FMS_TESTS, FMS_SCORING_CRITERIA, FMS_SCORES, COMPENSATION_PATTERNS, BODY_PARTS, TAG_TYPES
)
from ..labeling.exporter import Exporter

# FMS Integration - auto-score assessments on export
import sys as _sys
for _depth in range(len(Path(__file__).resolve().parents)):
    _candidate = str(Path(__file__).resolve().parents[_depth])
    if (Path(_candidate) / 'fms' / '__init__.py').exists():
        if _candidate not in _sys.path:
            _sys.path.insert(0, _candidate)
        break
try:
    from fms.integration import register_fms_routes, run_fms_on_export
    FMS_AVAILABLE = True
except ImportError:
    FMS_AVAILABLE = False
    print("Warning: FMS module not found. FMS auto-scoring disabled.")

# Initialize FastAPI app
app = FastAPI(
    title="Dynalytix FMS Assessment API",
    description="API for FMS movement assessment data",
    version="1.0.0"
)

# CORS middleware for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # Vite dev server
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize database
db = Database('data/labels.db')
db.init()

# Initialize exporter
exporter = Exporter(db)

# Register FMS API routes if available
if FMS_AVAILABLE:
    register_fms_routes(app)

# Ensure directories exist
Path('videos').mkdir(exist_ok=True)
Path('data').mkdir(exist_ok=True)

# Mount static files
app.mount("/videos", StaticFiles(directory="videos"), name="videos")


# ==================== PYDANTIC SCHEMAS ====================

class VideoCreate(BaseModel):
    """Schema for creating a video."""
    filename: str


class VideoResponse(BaseModel):
    """Schema for video response."""
    id: int
    filename: str
    path: str
    csv_path: str
    fps: float
    total_frames: int
    duration_ms: float
    uploaded_at: str


class AssessmentCreate(BaseModel):
    """Schema for creating an assessment."""
    video_id: int
    frame_start: int
    frame_end: int
    timestamp_start_ms: float
    timestamp_end_ms: float
    test_type: str
    score: int = Field(ge=0, le=3)
    criteria_data: dict = {}
    compensations: List[str] = []
    tags: List[str] = []
    notes: str = ""


class AssessmentUpdate(BaseModel):
    """Schema for updating an assessment."""
    frame_start: Optional[int] = None
    frame_end: Optional[int] = None
    timestamp_start_ms: Optional[float] = None
    timestamp_end_ms: Optional[float] = None
    test_type: Optional[str] = None
    score: Optional[int] = Field(None, ge=0, le=3)
    criteria_data: Optional[dict] = None
    compensations: Optional[List[str]] = None
    tags: Optional[List[str]] = None
    notes: Optional[str] = None


class AssessmentResponse(BaseModel):
    """Schema for assessment response."""
    id: int
    video_id: int
    frame_start: int
    frame_end: int
    timestamp_start_ms: float
    timestamp_end_ms: float
    test_type: str
    score: int
    criteria_data: dict
    compensations: List[str] = []
    tags: List[str]
    notes: str
    assessed_at: str
    frame_tag_count: int = 0


class FrameTagCreate(BaseModel):
    """Schema for creating a frame tag."""
    assessment_id: int
    frame_number: int
    timestamp_ms: float
    tag_type: str
    level: Optional[int] = Field(None, ge=0, le=10)
    locations: List[str] = []
    note: str = ""


class FrameTagResponse(BaseModel):
    """Schema for frame tag response."""
    id: int
    assessment_id: int
    frame_number: int
    timestamp_ms: float
    tag_type: str
    level: Optional[int]
    locations: List[str]
    note: str
    tagged_at: str


class ConfigResponse(BaseModel):
    """Schema for configuration data."""
    fms_tests: List[str]
    fms_scoring_criteria: dict
    fms_scores: dict
    compensation_patterns: List[dict]
    body_parts: List[str]
    tag_types: dict


class ExportResponse(BaseModel):
    """Schema for export response."""
    path: str
    video_deleted: bool


# ==================== HELPER FUNCTIONS ====================

def process_video(video_path: Path) -> dict:
    """
    Run pose extraction on video using main.py.
    Returns video metadata.
    """
    import cv2

    print(f"DEBUG: About to process video: {video_path}")

    # Get video metadata
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise ValueError(f"Could not open video: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration_ms = (total_frames / fps) * 1000 if fps > 0 else 0
    cap.release()

    # Run pose extraction
    csv_path = Path('data') / f"{video_path.stem}.csv"
    result = subprocess.run(
        [sys.executable, '../../main.py', str(video_path), '--output', str(csv_path), '--landmarks'],
        capture_output=True,
        text=True
    )

    if result.returncode != 0:
        raise RuntimeError(f"Pose extraction failed: {result.stderr}")

    metadata = {
        'fps': fps,
        'total_frames': total_frames,
        'duration_ms': duration_ms,
        'csv_path': str(csv_path)
    }

    print(f"DEBUG: Processing complete: {metadata}")

    return metadata


def video_to_response(video: Video) -> VideoResponse:
    """Convert Video model to response schema."""
    return VideoResponse(
        id=video.id,
        filename=video.filename,
        path=video.path,
        csv_path=video.csv_path,
        fps=video.fps,
        total_frames=video.total_frames,
        duration_ms=video.duration_ms,
        uploaded_at=video.uploaded_at.isoformat() if video.uploaded_at else ""
    )


def assessment_to_response(assessment: Assessment) -> AssessmentResponse:
    """Convert Assessment model to response schema."""
    # Get frame tag count
    tags = db.get_frame_tags_for_assessment(assessment.id)

    return AssessmentResponse(
        id=assessment.id,
        video_id=assessment.video_id,
        frame_start=assessment.frame_start,
        frame_end=assessment.frame_end,
        timestamp_start_ms=assessment.timestamp_start_ms,
        timestamp_end_ms=assessment.timestamp_end_ms,
        test_type=assessment.test_type,
        score=assessment.score,
        criteria_data=assessment.criteria_data,
        compensations=assessment.compensations,
        tags=assessment.tags,
        notes=assessment.notes,
        assessed_at=assessment.assessed_at.isoformat() if assessment.assessed_at else "",
        frame_tag_count=len(tags)
    )


def frame_tag_to_response(tag: FrameTag) -> FrameTagResponse:
    """Convert FrameTag model to response schema."""
    return FrameTagResponse(
        id=tag.id,
        assessment_id=tag.assessment_id,
        frame_number=tag.frame_number,
        timestamp_ms=tag.timestamp_ms,
        tag_type=tag.tag_type,
        level=tag.level,
        locations=tag.locations,
        note=tag.note,
        tagged_at=tag.tagged_at.isoformat() if tag.tagged_at else ""
    )


# ==================== API ROUTES ====================

@app.get("/")
async def root():
    """Health check endpoint."""
    return {"status": "ok", "message": "Dynalytix FMS API is running"}


@app.get("/api/config", response_model=ConfigResponse)
async def get_config():
    """Get configuration data (FMS tests, scoring criteria, body parts, etc.)."""
    return ConfigResponse(
        fms_tests=FMS_TESTS,
        fms_scoring_criteria=FMS_SCORING_CRITERIA,
        fms_scores=FMS_SCORES,
        compensation_patterns=COMPENSATION_PATTERNS,
        body_parts=BODY_PARTS,
        tag_types=TAG_TYPES
    )


# ==================== VIDEO ENDPOINTS ====================

@app.post("/api/videos/upload", response_model=VideoResponse, status_code=status.HTTP_201_CREATED)
async def upload_video(file: UploadFile = File(...)):
    """
    Upload and process a video.

    1. Saves video file
    2. Runs pose extraction
    3. Stores metadata in database
    """
    # Validate file type
    if not file.filename.endswith(('.mov', '.mp4', '.avi')):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid file type. Please upload .mov, .mp4, or .avi"
        )

    # Generate unique filename to avoid collisions
    import uuid
    unique_id = uuid.uuid4().hex
    safe_filename = f"video_{unique_id}_{file.filename}"
    video_path = Path('videos') / safe_filename

    # Save file
    try:
        with open(video_path, 'wb') as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save video: {str(e)}"
        )

    # Process video (pose extraction)
    try:
        metadata = process_video(video_path)
    except Exception as e:
        # Clean up on failure
        video_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Video processing failed: {str(e)}"
        )

    # Create database record
    video = Video(
        filename=safe_filename,
        path=str(video_path),
        csv_path=metadata['csv_path'],
        fps=metadata['fps'],
        total_frames=metadata['total_frames'],
        duration_ms=metadata['duration_ms'],
        uploaded_at=datetime.now()
    )

    video.id = db.create_video(video)

    return video_to_response(video)


@app.get("/api/videos", response_model=List[VideoResponse])
async def list_videos():
    """Get all uploaded videos."""
    videos = db.get_all_videos()
    return [video_to_response(v) for v in videos]


@app.get("/api/videos/{video_id}", response_model=VideoResponse)
async def get_video(video_id: int):
    """Get a specific video by ID."""
    video = db.get_video(video_id)
    if not video:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Video {video_id} not found"
        )
    return video_to_response(video)


@app.get("/api/videos/{video_id}/csv")
async def get_video_csv(video_id: int):
    """Download the CSV file for a video."""
    video = db.get_video(video_id)
    if not video:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Video {video_id} not found"
        )

    csv_path = Path(video.csv_path)
    if not csv_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="CSV file not found"
        )

    return FileResponse(csv_path, media_type='text/csv', filename=csv_path.name)


@app.post("/api/videos/{video_id}/export", response_model=ExportResponse)
async def export_video_endpoint(video_id: int, delete_video: bool = False):
    """
    Export labeled data for a video.

    Combines pose data with assessment labels into a single CSV.
    Optionally deletes the video file after export to save storage.

    Query params:
        delete_video: If true, delete the video file after successful export
    """
    try:
        export_path = exporter.export_video(video_id, delete_video=delete_video)

        # Auto-run FMS assessment on the exported CSV
        if FMS_AVAILABLE:
            try:
                fms_result = run_fms_on_export(export_path)
                print(f"FMS auto-score: {fms_result.get('score', 'N/A')}/3")
            except Exception as fms_err:
                print(f"FMS scoring failed (non-blocking): {fms_err}")

        return ExportResponse(path=export_path, video_deleted=delete_video)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )


@app.get("/api/videos/{video_id}/export/download")
async def download_export(video_id: int):
    """Download the exported labeled CSV file."""
    video = db.get_video(video_id)
    if not video:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Video {video_id} not found"
        )

    raw_csv_path = Path(video.csv_path)
    export_path = Path('data/exports') / f"{raw_csv_path.stem}_labeled.csv"

    if not export_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Export not found. Run export first."
        )

    return FileResponse(export_path, media_type='text/csv', filename=export_path.name)


# ==================== ASSESSMENT ENDPOINTS ====================

@app.post("/api/assessments", response_model=AssessmentResponse, status_code=status.HTTP_201_CREATED)
async def create_assessment(assessment_data: AssessmentCreate):
    """Create a new assessment."""
    # Validate video exists
    video = db.get_video(assessment_data.video_id)
    if not video:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Video {assessment_data.video_id} not found"
        )

    # Validate test type
    if assessment_data.test_type not in FMS_TESTS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid test type: {assessment_data.test_type}"
        )

    # Validate compensation patterns
    valid_compensation_ids = [c['id'] for c in COMPENSATION_PATTERNS]
    for compensation in assessment_data.compensations:
        if compensation not in valid_compensation_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid compensation pattern: {compensation}"
            )

    # Create assessment
    assessment = Assessment(
        video_id=assessment_data.video_id,
        frame_start=assessment_data.frame_start,
        frame_end=assessment_data.frame_end,
        timestamp_start_ms=assessment_data.timestamp_start_ms,
        timestamp_end_ms=assessment_data.timestamp_end_ms,
        test_type=assessment_data.test_type,
        score=assessment_data.score,
        criteria_data=assessment_data.criteria_data,
        compensations=assessment_data.compensations,
        tags=assessment_data.tags,
        notes=assessment_data.notes,
        assessed_at=datetime.now()
    )

    assessment.id = db.create_assessment(assessment)

    return assessment_to_response(assessment)


@app.get("/api/videos/{video_id}/assessments", response_model=List[AssessmentResponse])
async def list_assessments(video_id: int):
    """Get all assessments for a video."""
    # Validate video exists
    video = db.get_video(video_id)
    if not video:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Video {video_id} not found"
        )

    assessments = db.get_assessments_for_video(video_id)
    return [assessment_to_response(a) for a in assessments]


@app.get("/api/assessments/{assessment_id}", response_model=AssessmentResponse)
async def get_assessment(assessment_id: int):
    """Get a specific assessment by ID."""
    assessment = db.get_assessment(assessment_id)
    if not assessment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Assessment {assessment_id} not found"
        )
    return assessment_to_response(assessment)


@app.put("/api/assessments/{assessment_id}", response_model=AssessmentResponse)
async def update_assessment(assessment_id: int, assessment_data: AssessmentUpdate):
    """Update an existing assessment."""
    assessment = db.get_assessment(assessment_id)
    if not assessment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Assessment {assessment_id} not found"
        )

    # Update fields
    if assessment_data.frame_start is not None:
        assessment.frame_start = assessment_data.frame_start
    if assessment_data.frame_end is not None:
        assessment.frame_end = assessment_data.frame_end
    if assessment_data.timestamp_start_ms is not None:
        assessment.timestamp_start_ms = assessment_data.timestamp_start_ms
    if assessment_data.timestamp_end_ms is not None:
        assessment.timestamp_end_ms = assessment_data.timestamp_end_ms
    if assessment_data.test_type is not None:
        assessment.test_type = assessment_data.test_type
    if assessment_data.score is not None:
        assessment.score = assessment_data.score
    if assessment_data.criteria_data is not None:
        assessment.criteria_data = assessment_data.criteria_data
    if assessment_data.compensations is not None:
        assessment.compensations = assessment_data.compensations
    if assessment_data.tags is not None:
        assessment.tags = assessment_data.tags
    if assessment_data.notes is not None:
        assessment.notes = assessment_data.notes

    db.update_assessment(assessment)

    return assessment_to_response(assessment)


@app.delete("/api/assessments/{assessment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_assessment(assessment_id: int):
    """Delete an assessment and its frame tags."""
    success = db.delete_assessment(assessment_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Assessment {assessment_id} not found"
        )
    return None


# ==================== FRAME TAG ENDPOINTS ====================

@app.post("/api/frame-tags", response_model=FrameTagResponse, status_code=status.HTTP_201_CREATED)
async def create_frame_tag(tag_data: FrameTagCreate):
    """Create a new frame tag."""
    # Validate assessment exists
    assessment = db.get_assessment(tag_data.assessment_id)
    if not assessment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Assessment {tag_data.assessment_id} not found"
        )

    # Validate tag type
    if tag_data.tag_type not in TAG_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid tag type: {tag_data.tag_type}"
        )

    # Create tag
    tag = FrameTag(
        assessment_id=tag_data.assessment_id,
        frame_number=tag_data.frame_number,
        timestamp_ms=tag_data.timestamp_ms,
        tag_type=tag_data.tag_type,
        level=tag_data.level,
        locations=tag_data.locations,
        note=tag_data.note,
        tagged_at=datetime.now()
    )

    tag.id = db.create_frame_tag(tag)

    return frame_tag_to_response(tag)


@app.get("/api/assessments/{assessment_id}/frame-tags", response_model=List[FrameTagResponse])
async def list_frame_tags(assessment_id: int):
    """Get all frame tags for an assessment."""
    # Validate assessment exists
    assessment = db.get_assessment(assessment_id)
    if not assessment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Assessment {assessment_id} not found"
        )

    tags = db.get_frame_tags_for_assessment(assessment_id)
    return [frame_tag_to_response(t) for t in tags]


@app.delete("/api/frame-tags/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_frame_tag(tag_id: int):
    """Delete a frame tag."""
    success = db.delete_frame_tag(tag_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Frame tag {tag_id} not found"
        )
    return None


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
