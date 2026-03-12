"""
FastAPI application for data collection UI.

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
    Video, Move, FrameTag,
    MOVE_TYPES, MOVE_TYPE_QUESTIONS, BODY_PARTS, TAG_TYPES, TECHNIQUE_MODIFIERS
)
from ..labeling.exporter import Exporter

# Initialize FastAPI app
app = FastAPI(
    title="Dynalytics Data Collection API",
    description="API for labeling climbing movement data",
    version="1.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize database
db = Database('data/labels.db')
db.init()

# Initialize exporter
exporter = Exporter(db)

# Ensure directories exist
Path('videos').mkdir(exist_ok=True)
Path('data').mkdir(exist_ok=True)

# Mount static files for video serving
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


class MoveCreate(BaseModel):
    """Schema for creating a move."""
    video_id: int
    frame_start: int
    frame_end: int
    timestamp_start_ms: float
    timestamp_end_ms: float
    move_type: str
    form_quality: int = Field(ge=1, le=5)
    effort_level: int = Field(ge=0, le=10)
    contextual_data: dict = {}
    technique_modifiers: List[str] = []
    tags: List[str] = []
    description: str = ""


class MoveUpdate(BaseModel):
    """Schema for updating a move."""
    frame_start: Optional[int] = None
    frame_end: Optional[int] = None
    timestamp_start_ms: Optional[float] = None
    timestamp_end_ms: Optional[float] = None
    move_type: Optional[str] = None
    form_quality: Optional[int] = Field(None, ge=1, le=5)
    effort_level: Optional[int] = Field(None, ge=0, le=10)
    contextual_data: Optional[dict] = None
    technique_modifiers: Optional[List[str]] = None
    tags: Optional[List[str]] = None
    description: Optional[str] = None


class MoveResponse(BaseModel):
    """Schema for move response."""
    id: int
    video_id: int
    frame_start: int
    frame_end: int
    timestamp_start_ms: float
    timestamp_end_ms: float
    move_type: str
    form_quality: int
    effort_level: int
    contextual_data: dict
    technique_modifiers: List[str] = []
    tags: List[str]
    description: str
    labeled_at: str
    frame_tag_count: int = 0


class FrameTagCreate(BaseModel):
    """Schema for creating a frame tag."""
    move_id: int
    frame_number: int
    timestamp_ms: float
    tag_type: str
    level: Optional[int] = Field(None, ge=0, le=10)
    locations: List[str] = []
    note: str = ""


class FrameTagResponse(BaseModel):
    """Schema for frame tag response."""
    id: int
    move_id: int
    frame_number: int
    timestamp_ms: float
    tag_type: str
    level: Optional[int]
    locations: List[str]
    note: str
    tagged_at: str


class ConfigResponse(BaseModel):
    """Schema for configuration data."""
    move_types: List[str]
    move_type_questions: dict
    technique_modifiers: List[dict]
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
    main_py_path = Path('/app/main.py') if Path('/app/main.py').exists() else Path('../../main.py')
    result = subprocess.run(
        [sys.executable, str(main_py_path), str(video_path), '--output', str(csv_path), '--landmarks'],
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


def move_to_response(move: Move) -> MoveResponse:
    """Convert Move model to response schema."""
    # Get frame tag count
    tags = db.get_frame_tags_for_move(move.id)
    
    return MoveResponse(
        id=move.id,
        video_id=move.video_id,
        frame_start=move.frame_start,
        frame_end=move.frame_end,
        timestamp_start_ms=move.timestamp_start_ms,
        timestamp_end_ms=move.timestamp_end_ms,
        move_type=move.move_type,
        form_quality=move.form_quality,
        effort_level=move.effort_level,
        contextual_data=move.contextual_data,
        technique_modifiers=move.technique_modifiers,
        tags=move.tags,
        description=move.description,
        labeled_at=move.labeled_at.isoformat() if move.labeled_at else "",
        frame_tag_count=len(tags)
    )


def frame_tag_to_response(tag: FrameTag) -> FrameTagResponse:
    """Convert FrameTag model to response schema."""
    return FrameTagResponse(
        id=tag.id,
        move_id=tag.move_id,
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
    return {"status": "ok", "message": "Dynalytics API is running"}


@app.get("/api/config", response_model=ConfigResponse)
async def get_config():
    """Get configuration data (move types, questions, body parts, etc.)."""
    return ConfigResponse(
        move_types=MOVE_TYPES,
        move_type_questions=MOVE_TYPE_QUESTIONS,
        technique_modifiers=TECHNIQUE_MODIFIERS,
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
    
    Combines pose data with move/tag labels into a single CSV.
    Optionally deletes the video file after export to save storage.
    
    Query params:
        delete_video: If true, delete the video file after successful export
    """
    try:
        export_path = exporter.export_video(video_id, delete_video=delete_video)

        # Auto-sync to GitHub
        try:
            from ..labeling.data_sync import push_csv_to_github
            push_csv_to_github(export_path)
        except Exception as e:
            print(f"GitHub sync failed (non-blocking): {e}")

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


# ==================== MOVE ENDPOINTS ====================

@app.post("/api/moves", response_model=MoveResponse, status_code=status.HTTP_201_CREATED)
async def create_move(move_data: MoveCreate):
    """Create a new move."""
    # Validate video exists
    video = db.get_video(move_data.video_id)
    if not video:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Video {move_data.video_id} not found"
        )
    
    # Validate move type
    if move_data.move_type not in MOVE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid move type: {move_data.move_type}"
        )
    
    # Validate technique modifiers
    valid_modifier_ids = [m['id'] for m in TECHNIQUE_MODIFIERS]
    for modifier in move_data.technique_modifiers:
        if modifier not in valid_modifier_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid technique modifier: {modifier}"
            )
    
    # Create move
    move = Move(
        video_id=move_data.video_id,
        frame_start=move_data.frame_start,
        frame_end=move_data.frame_end,
        timestamp_start_ms=move_data.timestamp_start_ms,
        timestamp_end_ms=move_data.timestamp_end_ms,
        move_type=move_data.move_type,
        form_quality=move_data.form_quality,
        effort_level=move_data.effort_level,
        contextual_data=move_data.contextual_data,
        technique_modifiers=move_data.technique_modifiers,
        tags=move_data.tags,
        description=move_data.description,
        labeled_at=datetime.now()
    )
    
    move.id = db.create_move(move)
    
    return move_to_response(move)


@app.get("/api/videos/{video_id}/moves", response_model=List[MoveResponse])
async def list_moves(video_id: int):
    """Get all moves for a video."""
    # Validate video exists
    video = db.get_video(video_id)
    if not video:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Video {video_id} not found"
        )
    
    moves = db.get_moves_for_video(video_id)
    return [move_to_response(m) for m in moves]


@app.get("/api/moves/{move_id}", response_model=MoveResponse)
async def get_move(move_id: int):
    """Get a specific move by ID."""
    move = db.get_move(move_id)
    if not move:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Move {move_id} not found"
        )
    return move_to_response(move)


@app.put("/api/moves/{move_id}", response_model=MoveResponse)
async def update_move(move_id: int, move_data: MoveUpdate):
    """Update an existing move."""
    move = db.get_move(move_id)
    if not move:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Move {move_id} not found"
        )
    
    # Update fields
    if move_data.frame_start is not None:
        move.frame_start = move_data.frame_start
    if move_data.frame_end is not None:
        move.frame_end = move_data.frame_end
    if move_data.timestamp_start_ms is not None:
        move.timestamp_start_ms = move_data.timestamp_start_ms
    if move_data.timestamp_end_ms is not None:
        move.timestamp_end_ms = move_data.timestamp_end_ms
    if move_data.move_type is not None:
        move.move_type = move_data.move_type
    if move_data.form_quality is not None:
        move.form_quality = move_data.form_quality
    if move_data.effort_level is not None:
        move.effort_level = move_data.effort_level
    if move_data.contextual_data is not None:
        move.contextual_data = move_data.contextual_data
    if move_data.technique_modifiers is not None:
        move.technique_modifiers = move_data.technique_modifiers
    if move_data.tags is not None:
        move.tags = move_data.tags
    if move_data.description is not None:
        move.description = move_data.description
    
    db.update_move(move)
    
    return move_to_response(move)


@app.delete("/api/moves/{move_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_move(move_id: int):
    """Delete a move and its frame tags."""
    success = db.delete_move(move_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Move {move_id} not found"
        )
    return None


# ==================== FRAME TAG ENDPOINTS ====================

@app.post("/api/frame-tags", response_model=FrameTagResponse, status_code=status.HTTP_201_CREATED)
async def create_frame_tag(tag_data: FrameTagCreate):
    """Create a new frame tag."""
    # Validate move exists
    move = db.get_move(tag_data.move_id)
    if not move:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Move {tag_data.move_id} not found"
        )
    
    # Validate tag type
    if tag_data.tag_type not in TAG_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid tag type: {tag_data.tag_type}"
        )
    
    # Create tag
    tag = FrameTag(
        move_id=tag_data.move_id,
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


@app.get("/api/moves/{move_id}/frame-tags", response_model=List[FrameTagResponse])
async def list_frame_tags(move_id: int):
    """Get all frame tags for a move."""
    # Validate move exists
    move = db.get_move(move_id)
    if not move:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Move {move_id} not found"
        )
    
    tags = db.get_frame_tags_for_move(move_id)
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
