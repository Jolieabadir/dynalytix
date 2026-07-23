"""
FastAPI application for data collection UI.

Clean REST API with proper error handling and validation.
Three-lens labeling schema: Environment / Strategy / Outcome
"""
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, status
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
    Video, Move, Environment, Outcome, FrameTag,
    APPROACHES, SIZES, MOVE_TAGS, TIMINGS, DYNO_STYLES,
    WALL_ANGLES, HOLD_TYPES, HOLD_QUALITIES,
    RESULTS, REACH_DETAILS, CONFIDENCE_LEVELS,
    TAG_TYPES, BODY_PARTS, SIDES, TRACTION_SOURCES
)
from ..labeling.exporter import Exporter

# Initialize FastAPI app
app = FastAPI(
    title="Dynalytix Climbing Data Collection API",
    description="API for labeling climbing movement data",
    version="2.0.0"
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


# --- Move Schemas (Lens 2: Strategy) ---

class MoveCreate(BaseModel):
    """Schema for creating a move."""
    video_id: int
    frame_start: int
    frame_end: int
    timestamp_start_ms: float
    timestamp_end_ms: float
    approach: str  # static | dynamic | coordination
    size: str  # small | medium | large
    move_tags: List[str] = []  # multi-select from MOVE_TAGS
    timing: Optional[str] = None  # simultaneous | sequential | alternating
    dyno_style: Optional[str] = None  # double_clutch | paddle | single_arm_catch
    form_quality: int = Field(ge=1, le=5, default=3)
    effort_level: int = Field(ge=0, le=10, default=5)
    contextual_data: dict = {}
    tags: List[str] = []
    description: str = ""


class MoveUpdate(BaseModel):
    """Schema for updating a move."""
    frame_start: Optional[int] = None
    frame_end: Optional[int] = None
    timestamp_start_ms: Optional[float] = None
    timestamp_end_ms: Optional[float] = None
    approach: Optional[str] = None
    size: Optional[str] = None
    move_tags: Optional[List[str]] = None
    timing: Optional[str] = None
    dyno_style: Optional[str] = None
    form_quality: Optional[int] = Field(None, ge=1, le=5)
    effort_level: Optional[int] = Field(None, ge=0, le=10)
    contextual_data: Optional[dict] = None
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
    approach: str
    size: str
    move_tags: List[str]
    timing: Optional[str]
    dyno_style: Optional[str]
    form_quality: int
    effort_level: int
    contextual_data: dict
    tags: List[str]
    description: str
    labeled_at: str
    frame_tag_count: int = 0


# --- Environment Schemas (Lens 1: Environment) ---

class EnvironmentCreate(BaseModel):
    """Schema for creating an environment record."""
    move_id: int
    wall_angle: str  # slab | vertical | gentle_overhang | steep
    hold_type_reaching: Optional[str] = None  # nullable for no_hands moves
    hold_type_non_reaching: Optional[str] = None  # nullable for no_hands moves
    hold_quality: List[str] = []  # multi-select: incut | sloped | small


class EnvironmentUpdate(BaseModel):
    """Schema for updating an environment record."""
    wall_angle: Optional[str] = None
    hold_type_reaching: Optional[str] = None
    hold_type_non_reaching: Optional[str] = None
    hold_quality: Optional[List[str]] = None


class EnvironmentResponse(BaseModel):
    """Schema for environment response."""
    id: int
    move_id: int
    wall_angle: str
    hold_type_reaching: str
    hold_type_non_reaching: str
    hold_quality: List[str]


# --- Outcome Schemas (Lens 3: Outcome) ---

class OutcomeCreate(BaseModel):
    """Schema for creating an outcome record."""
    move_id: int
    result: str  # success | fall
    reach_detail: str  # reached_controlled | reached_not_controlled | didnt_reach
    foot_cut: bool = False
    confidence: str  # low | med | high


class OutcomeUpdate(BaseModel):
    """Schema for updating an outcome record."""
    result: Optional[str] = None
    reach_detail: Optional[str] = None
    foot_cut: Optional[bool] = None
    confidence: Optional[str] = None


class OutcomeResponse(BaseModel):
    """Schema for outcome response."""
    id: int
    move_id: int
    result: str
    reach_detail: str
    foot_cut: bool
    confidence: str


# --- Frame Tag Schemas (Sensation) ---

class FrameTagCreate(BaseModel):
    """Schema for creating a frame tag."""
    move_id: int
    frame_number: int
    timestamp_ms: float
    tag_type: str
    level: Optional[int] = Field(None, ge=0, le=10)
    locations: List[str] = []
    side: Optional[str] = None  # left | right | null
    traction_source: Optional[str] = None  # hip | hand | null
    traction_direction: Optional[str] = None  # free text
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
    side: Optional[str]
    traction_source: Optional[str]
    traction_direction: Optional[str]
    note: str
    tagged_at: str


# --- Config Schema ---

class ConfigResponse(BaseModel):
    """Schema for configuration data - complete taxonomy."""
    # Lens 2: Strategy
    approaches: List[str]
    sizes: List[str]
    move_tags: List[str]
    timings: List[str]
    dyno_styles: List[str]
    # Lens 1: Environment
    wall_angles: List[str]
    hold_types: List[str]
    hold_qualities: List[str]
    # Lens 3: Outcome
    results: List[str]
    reach_details: List[str]
    confidence_levels: List[str]
    # Sensation (Frame Tags)
    tag_types: dict
    body_parts: List[str]
    sides: List[str]
    traction_sources: List[str]


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
        approach=move.approach,
        size=move.size,
        move_tags=move.move_tags,
        timing=move.timing,
        dyno_style=move.dyno_style,
        form_quality=move.form_quality,
        effort_level=move.effort_level,
        contextual_data=move.contextual_data,
        tags=move.tags,
        description=move.description,
        labeled_at=move.labeled_at.isoformat() if move.labeled_at else "",
        frame_tag_count=len(tags)
    )


def environment_to_response(env: Environment) -> EnvironmentResponse:
    """Convert Environment model to response schema."""
    return EnvironmentResponse(
        id=env.id,
        move_id=env.move_id,
        wall_angle=env.wall_angle,
        hold_type_reaching=env.hold_type_reaching,
        hold_type_non_reaching=env.hold_type_non_reaching,
        hold_quality=env.hold_quality
    )


def outcome_to_response(outcome: Outcome) -> OutcomeResponse:
    """Convert Outcome model to response schema."""
    return OutcomeResponse(
        id=outcome.id,
        move_id=outcome.move_id,
        result=outcome.result,
        reach_detail=outcome.reach_detail,
        foot_cut=outcome.foot_cut,
        confidence=outcome.confidence
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
        side=tag.side,
        traction_source=tag.traction_source,
        traction_direction=tag.traction_direction,
        note=tag.note,
        tagged_at=tag.tagged_at.isoformat() if tag.tagged_at else ""
    )


# ==================== API ROUTES ====================

@app.get("/")
async def root():
    """Health check endpoint."""
    return {"status": "ok", "message": "Dynalytix Climbing API is running"}


@app.get("/api/config", response_model=ConfigResponse)
async def get_config():
    """Get configuration data - complete taxonomy for all three lenses."""
    return ConfigResponse(
        # Lens 2: Strategy
        approaches=APPROACHES,
        sizes=SIZES,
        move_tags=MOVE_TAGS,
        timings=TIMINGS,
        dyno_styles=DYNO_STYLES,
        # Lens 1: Environment
        wall_angles=WALL_ANGLES,
        hold_types=HOLD_TYPES,
        hold_qualities=HOLD_QUALITIES,
        # Lens 3: Outcome
        results=RESULTS,
        reach_details=REACH_DETAILS,
        confidence_levels=CONFIDENCE_LEVELS,
        # Sensation (Frame Tags)
        tag_types=TAG_TYPES,
        body_parts=BODY_PARTS,
        sides=SIDES,
        traction_sources=TRACTION_SOURCES
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


@app.post("/api/videos/register", response_model=VideoResponse, status_code=status.HTTP_201_CREATED)
async def register_video(
    filename: str = Form(...),
    fps: float = Form(...),
    total_frames: int = Form(...),
    duration_ms: float = Form(...),
    csv_data: str = Form(...),
):
    """
    Register a video that was processed client-side.
    Receives the CSV data directly instead of a video file.
    The video stays in the browser - only pose data is sent.
    """
    import uuid
    unique_id = uuid.uuid4().hex
    safe_filename = f"video_{unique_id}_{filename}"

    # Save CSV data
    csv_path = Path('data') / f"{Path(safe_filename).stem}.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.write_text(csv_data)

    # Create database record (no video file path needed)
    video = Video(
        filename=safe_filename,
        path="",  # No server-side video
        csv_path=str(csv_path),
        fps=fps,
        total_frames=total_frames,
        duration_ms=duration_ms,
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

    # Validate approach
    if move_data.approach not in APPROACHES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid approach: {move_data.approach}. Must be one of: {APPROACHES}"
        )

    # Validate size
    if move_data.size not in SIZES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid size: {move_data.size}. Must be one of: {SIZES}"
        )

    # Validate move_tags
    for tag in move_data.move_tags:
        if tag not in MOVE_TAGS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid move tag: {tag}. Must be one of: {MOVE_TAGS}"
            )

    # Validate timing if provided
    if move_data.timing is not None and move_data.timing not in TIMINGS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid timing: {move_data.timing}. Must be one of: {TIMINGS}"
        )

    # Validate dyno_style if provided (no dependency check - store what's sent)
    if move_data.dyno_style is not None and move_data.dyno_style not in DYNO_STYLES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid dyno_style: {move_data.dyno_style}. Must be one of: {DYNO_STYLES}"
        )

    # Create move
    move = Move(
        video_id=move_data.video_id,
        frame_start=move_data.frame_start,
        frame_end=move_data.frame_end,
        timestamp_start_ms=move_data.timestamp_start_ms,
        timestamp_end_ms=move_data.timestamp_end_ms,
        approach=move_data.approach,
        size=move_data.size,
        move_tags=move_data.move_tags,
        timing=move_data.timing,
        dyno_style=move_data.dyno_style,
        form_quality=move_data.form_quality,
        effort_level=move_data.effort_level,
        contextual_data=move_data.contextual_data,
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

    # Validate and update fields
    if move_data.approach is not None:
        if move_data.approach not in APPROACHES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid approach: {move_data.approach}"
            )
        move.approach = move_data.approach
    if move_data.size is not None:
        if move_data.size not in SIZES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid size: {move_data.size}"
            )
        move.size = move_data.size
    if move_data.move_tags is not None:
        for tag in move_data.move_tags:
            if tag not in MOVE_TAGS:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid move tag: {tag}"
                )
        move.move_tags = move_data.move_tags
    if move_data.timing is not None:
        if move_data.timing not in TIMINGS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid timing: {move_data.timing}"
            )
        move.timing = move_data.timing
    if move_data.dyno_style is not None:
        if move_data.dyno_style not in DYNO_STYLES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid dyno_style: {move_data.dyno_style}"
            )
        move.dyno_style = move_data.dyno_style
    if move_data.frame_start is not None:
        move.frame_start = move_data.frame_start
    if move_data.frame_end is not None:
        move.frame_end = move_data.frame_end
    if move_data.timestamp_start_ms is not None:
        move.timestamp_start_ms = move_data.timestamp_start_ms
    if move_data.timestamp_end_ms is not None:
        move.timestamp_end_ms = move_data.timestamp_end_ms
    if move_data.form_quality is not None:
        move.form_quality = move_data.form_quality
    if move_data.effort_level is not None:
        move.effort_level = move_data.effort_level
    if move_data.contextual_data is not None:
        move.contextual_data = move_data.contextual_data
    if move_data.tags is not None:
        move.tags = move_data.tags
    if move_data.description is not None:
        move.description = move_data.description

    db.update_move(move)

    return move_to_response(move)


@app.delete("/api/moves/{move_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_move(move_id: int):
    """Delete a move and its frame tags, environment, and outcome."""
    success = db.delete_move(move_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Move {move_id} not found"
        )
    return None


# ==================== ENVIRONMENT ENDPOINTS (Lens 1) ====================

@app.post("/api/environments", response_model=EnvironmentResponse, status_code=status.HTTP_201_CREATED)
async def create_environment(env_data: EnvironmentCreate):
    """Create an environment record for a move."""
    # Validate move exists
    move = db.get_move(env_data.move_id)
    if not move:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Move {env_data.move_id} not found"
        )

    # Check if environment already exists for this move
    existing = db.get_environment_for_move(env_data.move_id)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Environment already exists for move {env_data.move_id}. Use PUT to update."
        )

    # Validate wall_angle
    if env_data.wall_angle not in WALL_ANGLES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid wall_angle: {env_data.wall_angle}. Must be one of: {WALL_ANGLES}"
        )

    # Validate hold_type_reaching (nullable for no_hands moves)
    if env_data.hold_type_reaching and env_data.hold_type_reaching not in HOLD_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid hold_type_reaching: {env_data.hold_type_reaching}. Must be one of: {HOLD_TYPES}"
        )

    # Validate hold_type_non_reaching (nullable for no_hands moves)
    if env_data.hold_type_non_reaching and env_data.hold_type_non_reaching not in HOLD_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid hold_type_non_reaching: {env_data.hold_type_non_reaching}. Must be one of: {HOLD_TYPES}"
        )

    # Validate hold_quality
    for quality in env_data.hold_quality:
        if quality not in HOLD_QUALITIES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid hold_quality: {quality}. Must be one of: {HOLD_QUALITIES}"
            )

    # Create environment
    env = Environment(
        move_id=env_data.move_id,
        wall_angle=env_data.wall_angle,
        hold_type_reaching=env_data.hold_type_reaching or '',
        hold_type_non_reaching=env_data.hold_type_non_reaching or '',
        hold_quality=env_data.hold_quality
    )

    env.id = db.create_environment(env)

    return environment_to_response(env)


@app.get("/api/moves/{move_id}/environment", response_model=EnvironmentResponse)
async def get_environment(move_id: int):
    """Get the environment record for a move."""
    # Validate move exists
    move = db.get_move(move_id)
    if not move:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Move {move_id} not found"
        )

    env = db.get_environment_for_move(move_id)
    if not env:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No environment record for move {move_id}"
        )

    return environment_to_response(env)


@app.put("/api/environments/{env_id}", response_model=EnvironmentResponse)
async def update_environment(env_id: int, env_data: EnvironmentUpdate):
    """Update an environment record."""
    env = db.get_environment(env_id)
    if not env:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Environment {env_id} not found"
        )

    # Validate and update fields
    if env_data.wall_angle is not None:
        if env_data.wall_angle not in WALL_ANGLES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid wall_angle: {env_data.wall_angle}"
            )
        env.wall_angle = env_data.wall_angle
    if env_data.hold_type_reaching is not None:
        # Allow empty string (for no_hands moves) or valid hold type
        if env_data.hold_type_reaching and env_data.hold_type_reaching not in HOLD_TYPES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid hold_type_reaching: {env_data.hold_type_reaching}"
            )
        env.hold_type_reaching = env_data.hold_type_reaching
    if env_data.hold_type_non_reaching is not None:
        # Allow empty string (for no_hands moves) or valid hold type
        if env_data.hold_type_non_reaching and env_data.hold_type_non_reaching not in HOLD_TYPES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid hold_type_non_reaching: {env_data.hold_type_non_reaching}"
            )
        env.hold_type_non_reaching = env_data.hold_type_non_reaching
    if env_data.hold_quality is not None:
        for quality in env_data.hold_quality:
            if quality not in HOLD_QUALITIES:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid hold_quality: {quality}"
                )
        env.hold_quality = env_data.hold_quality

    db.update_environment(env)

    return environment_to_response(env)


# ==================== OUTCOME ENDPOINTS (Lens 3) ====================

@app.post("/api/outcomes", response_model=OutcomeResponse, status_code=status.HTTP_201_CREATED)
async def create_outcome(outcome_data: OutcomeCreate):
    """Create an outcome record for a move."""
    # Validate move exists
    move = db.get_move(outcome_data.move_id)
    if not move:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Move {outcome_data.move_id} not found"
        )

    # Check if outcome already exists for this move
    existing = db.get_outcome_for_move(outcome_data.move_id)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Outcome already exists for move {outcome_data.move_id}. Use PUT to update."
        )

    # Validate result
    if outcome_data.result not in RESULTS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid result: {outcome_data.result}. Must be one of: {RESULTS}"
        )

    # Validate reach_detail
    if outcome_data.reach_detail not in REACH_DETAILS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid reach_detail: {outcome_data.reach_detail}. Must be one of: {REACH_DETAILS}"
        )

    # Validate confidence
    if outcome_data.confidence not in CONFIDENCE_LEVELS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid confidence: {outcome_data.confidence}. Must be one of: {CONFIDENCE_LEVELS}"
        )

    # Create outcome
    outcome = Outcome(
        move_id=outcome_data.move_id,
        result=outcome_data.result,
        reach_detail=outcome_data.reach_detail,
        foot_cut=outcome_data.foot_cut,
        confidence=outcome_data.confidence
    )

    outcome.id = db.create_outcome(outcome)

    return outcome_to_response(outcome)


@app.get("/api/moves/{move_id}/outcome", response_model=OutcomeResponse)
async def get_outcome(move_id: int):
    """Get the outcome record for a move."""
    # Validate move exists
    move = db.get_move(move_id)
    if not move:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Move {move_id} not found"
        )

    outcome = db.get_outcome_for_move(move_id)
    if not outcome:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No outcome record for move {move_id}"
        )

    return outcome_to_response(outcome)


@app.put("/api/outcomes/{outcome_id}", response_model=OutcomeResponse)
async def update_outcome(outcome_id: int, outcome_data: OutcomeUpdate):
    """Update an outcome record."""
    outcome = db.get_outcome(outcome_id)
    if not outcome:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Outcome {outcome_id} not found"
        )

    # Validate and update fields
    if outcome_data.result is not None:
        if outcome_data.result not in RESULTS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid result: {outcome_data.result}"
            )
        outcome.result = outcome_data.result
    if outcome_data.reach_detail is not None:
        if outcome_data.reach_detail not in REACH_DETAILS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid reach_detail: {outcome_data.reach_detail}"
            )
        outcome.reach_detail = outcome_data.reach_detail
    if outcome_data.foot_cut is not None:
        outcome.foot_cut = outcome_data.foot_cut
    if outcome_data.confidence is not None:
        if outcome_data.confidence not in CONFIDENCE_LEVELS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid confidence: {outcome_data.confidence}"
            )
        outcome.confidence = outcome_data.confidence

    db.update_outcome(outcome)

    return outcome_to_response(outcome)


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
            detail=f"Invalid tag type: {tag_data.tag_type}. Must be one of: {list(TAG_TYPES.keys())}"
        )

    # Validate side if provided
    if tag_data.side is not None and tag_data.side not in SIDES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid side: {tag_data.side}. Must be one of: {SIDES}"
        )

    # Validate traction_source if provided
    if tag_data.traction_source is not None and tag_data.traction_source not in TRACTION_SOURCES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid traction_source: {tag_data.traction_source}. Must be one of: {TRACTION_SOURCES}"
        )

    # Validate locations
    for loc in tag_data.locations:
        if loc not in BODY_PARTS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid body part: {loc}. Must be one of: {BODY_PARTS}"
            )

    # Create tag
    tag = FrameTag(
        move_id=tag_data.move_id,
        frame_number=tag_data.frame_number,
        timestamp_ms=tag_data.timestamp_ms,
        tag_type=tag_data.tag_type,
        level=tag_data.level,
        locations=tag_data.locations,
        side=tag_data.side,
        traction_source=tag_data.traction_source,
        traction_direction=tag_data.traction_direction,
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
