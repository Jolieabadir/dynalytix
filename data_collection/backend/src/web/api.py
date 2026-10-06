"""
FastAPI application for data collection UI.

Clean REST API with proper error handling and validation.
Three-lens labeling schema: Environment / Strategy / Outcome

Storage: labels in Supabase Postgres, blobs in Cloudflare R2. Nothing is
written to the container filesystem, which Railway wipes on every deploy.
Every route below /api (except health) requires a Supabase JWT and is scoped to
that token's user.

Access model (single dataset, runbook W2). Every video-bound request resolves
the caller to one of three roles via _require_video_access:

    owner   videos.user_id = caller. For a non-admin this is the dormant
            community self-upload flow, which only works while
            SELF_UPLOAD_ENABLED is on. Full access while prep_status =
            'draft'; holds and moves lock at 'ready'.
    rater   the caller holds a video_assignments row on the video. May read the
            video, holds, canonical moves and pose CSV; may write only its own
            environment / outcome / frame_tag rows. Never sees another rater's
            rows (404, never 403).
    admin   rater_profiles.is_admin. Everything, including locked structure.

Anyone else gets 404, so ids stay private. 403 is reserved for "you can see
this but may not change it": structure writes on a locked video, rater writes
on a finished assignment, admin routes for non-admins.
"""
import hmac
import logging
import os
import secrets

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field
from typing import List, Optional
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import date, datetime, timezone

import psycopg

from ..labeling.database import Database, SchemaNotApplied
from ..labeling import pose_queue
from ..labeling.models import (
    Video, Hold, Move, Environment, Outcome, FrameTag, Strategy, Athlete,
    RaterProfile, VideoAssignment,
    APPROACHES, SIZES, MOVE_TAGS,
    WALL_ANGLES, HOLD_TYPES, HOLD_QUALITIES, HOLD_SLOTS, HOLD_SOURCES,
    RESULTS, REACH_DETAILS, CONFIDENCE_LEVELS,
    TAG_TYPES, BODY_PARTS, SIDES,
    DEFINITIONS,
    TAXONOMY_VERSION,
    SOURCE_TYPES, PAPER_SOURCE_TYPES, COMMUNITY_SOURCE_TYPE,
    HEIGHT_SOURCES, ATHLETE_CATEGORIES, MIN_AGE_YEAR_GAP,
)
from ..labeling.exporter import Exporter, AdminExporter
from ..storage import r2
from .auth import get_current_user_id

log = logging.getLogger(__name__)

# fps the browser reports at register when it cannot measure one. The worker
# overwrites it from ffprobe; see VideoRegister.
PROVISIONAL_FPS = 30.0

DEFAULT_IRR_OVERLAP_RATE = 0.25

# Camera-check thresholds (runbook W2 Worker). Placeholders until calibrated
# on real clips: see backend REPORT.md. Motion is the p95 per-frame background
# displacement as a fraction of the frame diagonal; zoom is max/min scale.
DEFAULT_CAMERA_MOTION_MAX = 0.002
DEFAULT_CAMERA_ZOOM_MAX = 1.05


def _float_env(name: str, default: float) -> float:
    raw = os.environ.get(name, '').strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        log.warning('%s=%r is not a number; using %s', name, raw, default)
        return default


def camera_thresholds() -> tuple:
    """(CAMERA_MOTION_MAX, CAMERA_ZOOM_MAX), read per call."""
    return (_float_env('CAMERA_MOTION_MAX', DEFAULT_CAMERA_MOTION_MAX),
            _float_env('CAMERA_ZOOM_MAX', DEFAULT_CAMERA_ZOOM_MAX))


def camera_problems(video: Video) -> List[str]:
    """Why a clip fails the camera check ([] when it passes). Ignores the
    override, so the admin view can still show what was overridden."""
    if video.pose_status != 'done':
        return []  # nothing measured yet; the ready gate reports pose separately
    if video.camera_motion_score is None or video.camera_zoom_range is None or video.has_cut is None:
        return ['camera check did not run on this clip']
    motion_max, zoom_max = camera_thresholds()
    problems = []
    if video.has_cut:
        frames = ', '.join(str(f) for f in (video.cut_frames or [])[:5])
        problems.append(f'camera cut detected (frames {frames})' if frames else 'camera cut detected')
    if video.camera_motion_score > motion_max:
        problems.append(
            f'camera moves too much (score {video.camera_motion_score:.4f} > {motion_max:.4f})'
        )
    if video.camera_zoom_range > zoom_max:
        problems.append(f'camera zooms (range {video.camera_zoom_range:.3f} > {zoom_max:.3f})')
    return problems


def self_upload_enabled() -> bool:
    """SELF_UPLOAD_ENABLED: the dormant community self-upload flow.

    Off by default. Read on every call (not cached) so a test, or a Railway
    variable change plus restart, takes effect without code changes.
    """
    return os.environ.get('SELF_UPLOAD_ENABLED', '').strip().lower() in ('1', 'true', 'yes', 'on')


def irr_overlap_rate() -> float:
    """IRR_OVERLAP_RATE: share of videos drawn into the 3-rater overlap subset."""
    raw = os.environ.get('IRR_OVERLAP_RATE', '').strip()
    try:
        rate = float(raw) if raw else DEFAULT_IRR_OVERLAP_RATE
    except ValueError:
        log.warning('IRR_OVERLAP_RATE=%r is not a number; using %s', raw, DEFAULT_IRR_OVERLAP_RATE)
        return DEFAULT_IRR_OVERLAP_RATE
    return min(max(rate, 0.0), 1.0)


# Cryptographic RNG for the overlap draw: unpredictable, so nobody can steer
# which videos land in the reliability subset.
_overlap_rng = secrets.SystemRandom()


# Most holds accepted in one bulk create. A bouldering wall in frame is tens of
# holds; anything past this is a runaway detector, not a real wall.
MAX_HOLDS_PER_REQUEST = 200

@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Close the connection pool on shutdown, if this module opened it."""
    yield
    if _db is not None and _db_owned:
        _db.close()


app = FastAPI(
    title="Dynalytix Climbing Data Collection API",
    description="API for labeling climbing movement data",
    version="3.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Lazily built so the module imports without DATABASE_URL (tests, tooling).
_db: Optional[Database] = None
_exporter: Optional[Exporter] = None
_admin_exporter: Optional[AdminExporter] = None
# True only when this module opened the pool, so an injected one (tests) is
# never closed out from under its owner on app shutdown.
_db_owned: bool = False


def get_db() -> Database:
    """Return the process-wide Database, opening the pool on first use."""
    global _db, _db_owned
    if _db is None:
        _db = Database()
        _db_owned = True
    return _db


def get_exporter() -> Exporter:
    """Return the process-wide Exporter."""
    global _exporter
    if _exporter is None:
        _exporter = Exporter(get_db())
    return _exporter


def get_admin_exporter() -> AdminExporter:
    """Return the process-wide AdminExporter (cross-user CSVs)."""
    global _admin_exporter
    if _admin_exporter is None or _admin_exporter.db is not get_db():
        _admin_exporter = AdminExporter(get_db())
    return _admin_exporter


# ==================== PYDANTIC SCHEMAS ====================

class VideoRegister(BaseModel):
    """Schema for registering a video before its upload.

    Everything here is PROVISIONAL. The browser knows duration and dimensions
    from the <video> element the moment the file is picked, but not the frame
    rate, so it sends fps=30 (PROVISIONAL_FPS) and total_frames derived from
    it. The pose worker overwrites fps, total_frames, duration_ms, width and
    height from ffprobe when it finishes; until pose_status is 'done', frame
    numbers computed from these are approximate on a non-30fps clip.
    """
    filename: str
    fps: float = Field(default=PROVISIONAL_FPS, gt=0)
    total_frames: int = Field(default=0, ge=0)
    duration_ms: float = Field(default=0, ge=0)
    width: Optional[int] = Field(default=None, gt=0)
    height: Optional[int] = Field(default=None, gt=0)


class VideoResponse(BaseModel):
    """Schema for video response."""
    id: int
    filename: str
    fps: float
    total_frames: int
    duration_ms: float
    width: Optional[int] = None
    height: Optional[int] = None
    r2_video_key: Optional[str]
    r2_pose_csv_key: Optional[str]
    r2_export_key: Optional[str]
    uploaded_at: str
    # owner_user_id is videos.user_id (the prepper, or a community uploader).
    # A rater reading an assigned video sees the owner's id here.
    owner_user_id: str = ""
    prep_status: str = "draft"
    # Inter-rater reliability subset (3 raters) and the resulting target.
    irr_overlap: bool = False
    irr_overlap_set_by: Optional[str] = None
    rater_target: int = 1
    # Public-source provenance.
    source_type: str = "public_broadcast"
    source_url: Optional[str] = None
    clip_start_ms: Optional[int] = None
    clip_end_ms: Optional[int] = None
    license: Optional[str] = None
    event_name: Optional[str] = None
    event_date: Optional[str] = None
    athlete_id: Optional[str] = None
    # Camera check (worker) and the admin override. camera_problems lists why
    # the clip fails (empty = passes), whether or not it is overridden.
    has_cut: Optional[bool] = None
    cut_frames: List[int] = []
    camera_motion_score: Optional[float] = None
    camera_zoom_range: Optional[float] = None
    camera_motion_frames_pct: Optional[float] = None
    camera_override: bool = False
    camera_override_note: Optional[str] = None
    camera_problems: List[str] = []
    route_grade: Optional[str] = None
    wall_type: Optional[str] = None
    camera_angle: Optional[str] = None
    notes: Optional[str] = None
    # The caller's relationship to this video: owner | rater | admin.
    access_role: str = "owner"
    # Server-side pose job (runbook-w1-worker). fps/total_frames/duration_ms/
    # width/height above are provisional until pose_status is 'done'.
    pose_status: str = 'pending'
    pose_error: Optional[str] = None
    pose_started_at: Optional[str] = None
    pose_finished_at: Optional[str] = None


class VideoMetadataUpdate(BaseModel):
    """Admin prep metadata. Every field optional; omitted fields stay.

    Pass "" to clear a nullable text field (athlete_id and event_date too).
    The keys match the sidecar JSON written by scripts/prepare_clip.py, so the
    admin form can import one directly. irr_overlap is not here: it is drawn
    at random on mark-ready (see PUT .../overlap for the override).
    """
    source_type: Optional[str] = None
    source_url: Optional[str] = None
    clip_start_ms: Optional[int] = Field(default=None, ge=0)
    clip_end_ms: Optional[int] = Field(default=None, ge=0)
    license: Optional[str] = None
    event_name: Optional[str] = None
    event_date: Optional[str] = None  # YYYY-MM-DD, or "" to clear
    athlete_id: Optional[str] = None  # an athletes.athlete_id, or "" to clear
    route_grade: Optional[str] = None
    wall_type: Optional[str] = None
    camera_angle: Optional[str] = None
    notes: Optional[str] = None


class CameraOverride(BaseModel):
    """Admin accepts a clip that fails the camera check. A note is required
    when turning the override on."""
    override: bool
    note: Optional[str] = None


class OverlapUpdate(BaseModel):
    """Admin override of the random overlap draw."""
    irr_overlap: bool


# --- Athletes (admin only) ---

class AthleteCreate(BaseModel):
    """A pseudonymous athlete. No name field by design."""
    ifsc_profile_url: Optional[str] = None
    height_cm: Optional[int] = Field(default=None, ge=100, le=250)
    birth_year: Optional[int] = Field(default=None, ge=1900, le=2100)
    category: Optional[str] = None  # men | women
    # Defaults to 'ifsc_profile' when height_cm is given, else 'missing'.
    height_source: Optional[str] = None


class AthleteUpdate(BaseModel):
    """Every field optional; "" clears ifsc_profile_url / category."""
    ifsc_profile_url: Optional[str] = None
    height_cm: Optional[int] = Field(default=None, ge=100, le=250)
    birth_year: Optional[int] = Field(default=None, ge=1900, le=2100)
    category: Optional[str] = None
    height_source: Optional[str] = None


class AthleteResponse(BaseModel):
    """An athlete as the admin sees it (profile URL included; never exported)."""
    athlete_id: str
    ifsc_profile_url: Optional[str]
    height_cm: Optional[int]
    height_source: str
    birth_year: Optional[int]
    category: Optional[str]
    created_at: str


class AdminVideoListItem(BaseModel):
    """One row in the admin video list."""
    video: VideoResponse
    assignment_count: int
    done_count: int


class PoseStatusResponse(BaseModel):
    """What the header chip polls."""
    video_id: int
    pose_status: str
    pose_error: Optional[str] = None
    pose_started_at: Optional[str] = None
    pose_finished_at: Optional[str] = None
    fps: float
    total_frames: int
    duration_ms: float
    width: Optional[int] = None
    height: Optional[int] = None
    r2_pose_csv_key: Optional[str] = None


class PoseResult(BaseModel):
    """Worker -> backend callback body (fallback to the worker writing Postgres)."""
    status: str
    error: Optional[str] = None
    # Camera check (worker camera_check.py), sent with 'done'.
    has_cut: Optional[bool] = None
    cut_frames: Optional[List[int]] = None
    camera_motion_score: Optional[float] = Field(default=None, ge=0)
    camera_zoom_range: Optional[float] = Field(default=None, ge=1)
    camera_motion_frames_pct: Optional[float] = Field(default=None, ge=0, le=100)
    fps: Optional[float] = Field(default=None, gt=0)
    total_frames: Optional[int] = Field(default=None, ge=0)
    duration_ms: Optional[float] = Field(default=None, ge=0)
    width: Optional[int] = Field(default=None, gt=0)
    height: Optional[int] = Field(default=None, gt=0)
    r2_pose_csv_key: Optional[str] = None


class PoseCsvUrlResponse(BaseModel):
    """Presigned GET URL for the pose CSV, for the browser to fetch directly."""
    url: str
    expires_in: int


class UploadUrlRequest(BaseModel):
    """Schema for requesting a presigned video upload URL."""
    content_type: str = 'video/mp4'


class UploadUrlResponse(BaseModel):
    """Schema for a presigned upload URL."""
    url: str
    key: str
    expires_in: int


class PlaybackUrlResponse(BaseModel):
    """A presigned GET URL for the original video, for in-browser playback."""
    url: str
    expires_in: int


class ConfirmUploadRequest(BaseModel):
    """Schema for confirming a completed direct upload."""
    key: Optional[str] = None


# --- Resumable multipart upload (iPhone) ---

class CreateMultipartRequest(BaseModel):
    """Begin a resumable upload of the original video."""
    content_type: str = 'video/mp4'


class CreateMultipartResponse(BaseModel):
    """Everything the browser needs to drive, and later resume, the upload."""
    key: str
    upload_id: str
    part_size: int


class SignPartRequest(BaseModel):
    """Sign one part. Part numbers are 1-based, as S3 requires."""
    key: str
    upload_id: str
    part_number: int = Field(ge=1, le=10000)


class SignPartResponse(BaseModel):
    """A presigned URL for exactly one part."""
    url: str
    part_number: int
    expires_in: int


class CompletedPart(BaseModel):
    """One part the browser has finished, with the ETag R2 answered."""
    part_number: int = Field(ge=1, le=10000)
    etag: str


class CompleteMultipartRequest(BaseModel):
    """Assemble the parts into the final object."""
    key: str
    upload_id: str
    parts: List[CompletedPart]


class AbortMultipartRequest(BaseModel):
    """Throw away an unfinished multipart upload."""
    key: str
    upload_id: str


# --- Hold Schemas ---

class HoldItem(BaseModel):
    """One bounding box in a bulk hold create. video_id comes from the path."""
    bbox_x: float = Field(ge=0, le=1)
    bbox_y: float = Field(ge=0, le=1)
    bbox_w: float = Field(ge=0, le=1)
    bbox_h: float = Field(ge=0, le=1)
    source: str = 'manual'  # detected | manual


class HoldCreate(BaseModel):
    """Schema for creating a hold."""
    video_id: int
    bbox_x: float = Field(ge=0, le=1)
    bbox_y: float = Field(ge=0, le=1)
    bbox_w: float = Field(ge=0, le=1)
    bbox_h: float = Field(ge=0, le=1)
    source: str = 'manual'  # detected | manual


class HoldBulkCreate(BaseModel):
    """Schema for creating many holds on one video in a single request."""
    holds: List[HoldItem] = []


class HoldUpdate(BaseModel):
    """Schema for updating a hold. Every field optional; omitted fields stay."""
    bbox_x: Optional[float] = Field(default=None, ge=0, le=1)
    bbox_y: Optional[float] = Field(default=None, ge=0, le=1)
    bbox_w: Optional[float] = Field(default=None, ge=0, le=1)
    bbox_h: Optional[float] = Field(default=None, ge=0, le=1)
    source: Optional[str] = None


class HoldResponse(BaseModel):
    """Schema for hold response."""
    id: int
    video_id: int
    bbox_x: float
    bbox_y: float
    bbox_w: float
    bbox_h: float
    source: str
    created_at: str


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
    form_quality: int = Field(ge=1, le=5, default=3)
    effort_level: int = Field(ge=0, le=10, default=5)
    confidence: Optional[str] = None  # low | med | high
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
    form_quality: Optional[int] = Field(None, ge=1, le=5)
    effort_level: Optional[int] = Field(None, ge=0, le=10)
    confidence: Optional[str] = None
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
    form_quality: int
    effort_level: int
    confidence: Optional[str]
    description: str
    labeled_at: str
    frame_tag_count: int = 0


# --- Environment Schemas (Lens 1: Environment) ---

class HoldSlot(BaseModel):
    """One of the four hold slots on an environment. Every field optional."""
    hold_id: Optional[int] = None
    hold_type: Optional[str] = None
    hold_quality: List[str] = []


class EnvironmentCreate(BaseModel):
    """Schema for creating an environment record."""
    move_id: int
    wall_angle: str  # slab | vertical | gentle_overhang | steep
    start_left: HoldSlot = Field(default_factory=HoldSlot)
    start_right: HoldSlot = Field(default_factory=HoldSlot)
    end: HoldSlot = Field(default_factory=HoldSlot)
    foot: HoldSlot = Field(default_factory=HoldSlot)  # optional by design


class EnvironmentUpdate(BaseModel):
    """Schema for updating an environment record."""
    wall_angle: Optional[str] = None
    start_left: Optional[HoldSlot] = None
    start_right: Optional[HoldSlot] = None
    end: Optional[HoldSlot] = None
    foot: Optional[HoldSlot] = None


class EnvironmentResponse(BaseModel):
    """Schema for environment response."""
    id: int
    move_id: int
    wall_angle: str
    start_left: HoldSlot
    start_right: HoldSlot
    end: HoldSlot
    foot: HoldSlot
    taxonomy_version: str = ""
    is_gold: bool = False


# --- Outcome Schemas (Lens 3: Outcome) ---

class OutcomeCreate(BaseModel):
    """Schema for creating an outcome record."""
    move_id: int
    result: str  # success | fall
    reach_detail: str  # reached_controlled | reached_not_controlled | didnt_reach
    confidence: Optional[str] = None  # low | med | high


class OutcomeUpdate(BaseModel):
    """Schema for updating an outcome record."""
    result: Optional[str] = None
    reach_detail: Optional[str] = None
    confidence: Optional[str] = None


class OutcomeResponse(BaseModel):
    """Schema for outcome response."""
    id: int
    move_id: int
    result: str
    reach_detail: str
    confidence: Optional[str]
    taxonomy_version: str = ""
    is_gold: bool = False


# --- Strategy Schemas (Lens 2, per rater) ---

class StrategyCreate(BaseModel):
    """A rater's own Strategy labels on a canonical move."""
    move_id: int
    approach: str  # static | dynamic | coordination
    size: str  # small | medium | large
    move_tags: List[str] = []
    form_quality: int = Field(ge=1, le=5)
    confidence: Optional[str] = None  # low | med | high


class StrategyUpdate(BaseModel):
    """Every field optional."""
    approach: Optional[str] = None
    size: Optional[str] = None
    move_tags: Optional[List[str]] = None
    form_quality: Optional[int] = Field(default=None, ge=1, le=5)
    confidence: Optional[str] = None


class StrategyResponse(BaseModel):
    """A rater's Strategy row."""
    id: int
    move_id: int
    approach: str
    size: str
    move_tags: List[str]
    form_quality: int
    confidence: Optional[str]
    taxonomy_version: str = ""
    is_gold: bool = False


# --- Frame Tag Schemas (Sensation) ---

class FrameTagCreate(BaseModel):
    """Schema for creating a frame tag."""
    move_id: int
    frame_number: int
    timestamp_ms: float
    tag_type: str
    side: Optional[str] = None  # left | right | null
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
    side: Optional[str]
    level: Optional[int]
    locations: List[str]
    note: str
    tagged_at: str
    taxonomy_version: str = ""
    is_gold: bool = False


# --- Rater profile / assignment / admin Schemas ---

class ProfileCreate(BaseModel):
    """What a rater fills in at first sign-in. is_validated / is_admin are
    not here: only an admin sets those."""
    display_name: str = Field(min_length=1, max_length=120)
    years_climbing: Optional[int] = Field(default=None, ge=0, le=100)
    bio: Optional[str] = Field(default=None, max_length=1000)
    highest_grade: Optional[str] = None
    research_background: bool = False


class ProfileResponse(BaseModel):
    """A rater profile. is_admin tells the app whether to show admin views."""
    user_id: str
    display_name: str
    is_validated: bool
    years_climbing: Optional[int]
    bio: Optional[str]
    highest_grade: Optional[str]
    research_background: bool
    validation_note: Optional[str]
    is_admin: bool
    created_at: str


class ProfileUpdate(BaseModel):
    """What a rater may change on their own profile later. Every field
    optional; is_validated / validation_note / is_admin are admin-only and absent."""
    display_name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    years_climbing: Optional[int] = Field(default=None, ge=0, le=100)
    bio: Optional[str] = Field(default=None, max_length=1000)
    highest_grade: Optional[str] = None
    research_background: Optional[bool] = None


class RaterUpdate(BaseModel):
    """Admin-only edits to a profile. Every field optional."""
    is_validated: Optional[bool] = None
    validation_note: Optional[str] = None
    is_admin: Optional[bool] = None
    display_name: Optional[str] = None


class AssignmentCreate(BaseModel):
    """Admin assigns one validated rater to one ready video."""
    video_id: int
    rater_user_id: str


class AssignmentResponse(BaseModel):
    """An assignment row."""
    id: int
    video_id: int
    rater_user_id: str
    status: str  # assigned | in_progress | done
    assigned_at: str
    completed_at: Optional[str]


class MyAssignmentItem(BaseModel):
    """One entry in the rater's queue: the assignment plus its video."""
    assignment: AssignmentResponse
    video: VideoResponse
    move_count: int


class MissingLens(BaseModel):
    """One canonical move the rater has not finished."""
    move_id: int
    move_index: int
    missing: List[str]


# --- Config / export / health Schemas ---

class ConfigResponse(BaseModel):
    """Schema for configuration data - complete taxonomy."""
    # Taxonomy version, stamped into every label row written under it.
    version: str
    # Lens 2: Strategy
    approaches: List[str]
    sizes: List[str]
    move_tags: List[str]
    # Lens 1: Environment
    wall_angles: List[str]
    hold_types: List[str]
    hold_qualities: List[str]
    hold_slots: List[str]
    hold_sources: List[str]
    # Lens 3: Outcome
    results: List[str]
    reach_details: List[str]
    confidence_levels: List[str]
    # Sensation (Frame Tags)
    tag_types: dict
    body_parts: List[str]
    sides: List[str]
    # Plain-language definitions for every option above, and optional
    # display_label overrides. {taxonomy_key: {value: {description, display_label?}}}
    definitions: dict
    # Feature flags the frontend reads at runtime (no Vite rebuild needed).
    self_upload_enabled: bool = False
    source_types: List[str] = []


class ExportResponse(BaseModel):
    """Schema for export response."""
    video_id: int
    r2_export_key: str


class ExportListItem(BaseModel):
    """One row in the current user's export list."""
    video_id: int
    filename: str
    r2_export_key: str
    uploaded_at: str


class HealthResponse(BaseModel):
    """Schema for the health check."""
    status: str
    database: str
    r2: str
    schema_version: Optional[int] = None


# ==================== HELPER FUNCTIONS ====================

def _iso(value: Optional[datetime]) -> str:
    return value.isoformat() if value else ""


def video_to_response(video: Video, access_role: str = 'owner') -> VideoResponse:
    """Convert Video model to response schema.

    A rater does not learn whether the video is in the reliability subset
    (that could change how carefully they label it), nor the prepper's notes
    or camera-override note: those fields come back neutral.
    """
    response = _video_response(video, access_role)
    if access_role == 'rater':
        response.irr_overlap = False
        response.irr_overlap_set_by = None
        response.rater_target = 1
        response.notes = None
        if hasattr(response, 'camera_override_note'):
            response.camera_override_note = None
    return response


def _video_response(video: Video, access_role: str) -> VideoResponse:
    return VideoResponse(
        id=video.id,
        filename=video.filename,
        fps=video.fps,
        total_frames=video.total_frames,
        duration_ms=video.duration_ms,
        width=video.width,
        height=video.height,
        r2_video_key=video.r2_video_key,
        r2_pose_csv_key=video.r2_pose_csv_key,
        r2_export_key=video.r2_export_key,
        uploaded_at=_iso(video.uploaded_at),
        owner_user_id=video.user_id,
        prep_status=video.prep_status,
        irr_overlap=bool(video.irr_overlap),
        irr_overlap_set_by=video.irr_overlap_set_by,
        rater_target=video.rater_target(),
        source_type=video.source_type,
        source_url=video.source_url,
        clip_start_ms=video.clip_start_ms,
        clip_end_ms=video.clip_end_ms,
        license=video.license,
        event_name=video.event_name,
        event_date=video.event_date.isoformat() if video.event_date else None,
        athlete_id=video.athlete_id,
        has_cut=video.has_cut,
        cut_frames=list(video.cut_frames or []),
        camera_motion_score=video.camera_motion_score,
        camera_zoom_range=video.camera_zoom_range,
        camera_motion_frames_pct=video.camera_motion_frames_pct,
        camera_override=bool(video.camera_override),
        camera_override_note=video.camera_override_note,
        camera_problems=camera_problems(video),
        route_grade=video.route_grade,
        wall_type=video.wall_type,
        camera_angle=video.camera_angle,
        notes=video.notes,
        access_role=access_role,
        pose_status=video.pose_status or 'pending',
        pose_error=video.pose_error,
        pose_started_at=_iso(video.pose_started_at) or None,
        pose_finished_at=_iso(video.pose_finished_at) or None,
    )


def profile_to_response(profile: RaterProfile) -> ProfileResponse:
    """Convert RaterProfile model to response schema."""
    return ProfileResponse(
        user_id=profile.user_id,
        display_name=profile.display_name,
        is_validated=bool(profile.is_validated),
        years_climbing=profile.years_climbing,
        bio=profile.bio,
        highest_grade=profile.highest_grade,
        research_background=profile.research_background,
        validation_note=profile.validation_note,
        is_admin=profile.is_admin,
        created_at=_iso(profile.created_at),
    )


def assignment_to_response(assignment: VideoAssignment) -> AssignmentResponse:
    """Convert VideoAssignment model to response schema."""
    return AssignmentResponse(
        id=assignment.id,
        video_id=assignment.video_id,
        rater_user_id=assignment.rater_user_id,
        status=assignment.status,
        assigned_at=_iso(assignment.assigned_at),
        completed_at=_iso(assignment.completed_at) or None,
    )


def athlete_to_response(athlete: Athlete) -> AthleteResponse:
    """Convert Athlete model to response schema."""
    return AthleteResponse(
        athlete_id=athlete.athlete_id,
        ifsc_profile_url=athlete.ifsc_profile_url,
        height_cm=athlete.height_cm,
        height_source=athlete.height_source,
        birth_year=athlete.birth_year,
        category=athlete.category,
        created_at=_iso(athlete.created_at),
    )


def strategy_to_response(strategy: Strategy) -> StrategyResponse:
    """Convert Strategy model to response schema."""
    return StrategyResponse(
        id=strategy.id,
        move_id=strategy.move_id,
        approach=strategy.approach,
        size=strategy.size,
        move_tags=strategy.move_tags,
        form_quality=strategy.form_quality,
        confidence=strategy.confidence or None,
        taxonomy_version=strategy.taxonomy_version,
        is_gold=strategy.is_gold,
    )


def pose_status_to_response(video: Video) -> PoseStatusResponse:
    return PoseStatusResponse(
        video_id=video.id,
        pose_status=video.pose_status or 'pending',
        pose_error=video.pose_error,
        pose_started_at=_iso(video.pose_started_at) or None,
        pose_finished_at=_iso(video.pose_finished_at) or None,
        fps=video.fps,
        total_frames=video.total_frames,
        duration_ms=video.duration_ms,
        width=video.width,
        height=video.height,
        r2_pose_csv_key=video.r2_pose_csv_key,
    )


def _enqueue_or_fail(video: Video) -> Video:
    """Hand the job to the worker; on any failure mark the row 'failed'.

    Never raises: the upload has already succeeded and the labeler can keep
    working. The failure lands in pose_error and the retry-pose route
    re-attempts it.
    """
    db = get_db()
    if not video.r2_video_key:
        db.set_pose_status(video.id, 'failed', 'no video uploaded yet', user_id=video.user_id)
        video.pose_status, video.pose_error = 'failed', 'no video uploaded yet'
        return video

    try:
        pose_queue.enqueue_pose_job(video.id, video.user_id, video.r2_video_key)
    except pose_queue.PoseQueueError as exc:
        log.warning('video %s: pose job not enqueued: %s', video.id, exc)
        db.set_pose_status(video.id, 'failed', str(exc)[:500], user_id=video.user_id)
        video.pose_status, video.pose_error = 'failed', str(exc)[:500]
        return video

    db.set_pose_status(video.id, 'pending', user_id=video.user_id)
    video.pose_status, video.pose_error = 'pending', None
    video.pose_started_at = video.pose_finished_at = None
    return video


def _require_worker_secret(request: Request) -> None:
    """Authenticate the worker callback with the shared secret header."""
    expected = os.environ.get('MODAL_WEBHOOK_SECRET', '').strip()
    provided = (request.headers.get(pose_queue.SECRET_HEADER) or '').strip()
    if not expected or not provided or not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='bad worker secret')


def hold_to_response(hold: Hold) -> HoldResponse:
    """Convert Hold model to response schema."""
    return HoldResponse(
        id=hold.id,
        video_id=hold.video_id,
        bbox_x=hold.bbox_x,
        bbox_y=hold.bbox_y,
        bbox_w=hold.bbox_w,
        bbox_h=hold.bbox_h,
        source=hold.source,
        created_at=_iso(hold.created_at),
    )


def move_to_response(move: Move, user_id: str, role: str = 'owner') -> MoveResponse:
    """Convert Move model to response schema.

    A rater gets the move's boundaries only: the strategy / effort /
    description on the move row are the prepper's, and showing them would
    anchor the rater's own Strategy labels (which feed the reliability
    analysis). They come back blank.
    """
    tags = get_db().get_frame_tags_for_move(move.id, user_id)
    if role == 'rater':
        return MoveResponse(
            id=move.id, video_id=move.video_id,
            frame_start=move.frame_start, frame_end=move.frame_end,
            timestamp_start_ms=move.timestamp_start_ms, timestamp_end_ms=move.timestamp_end_ms,
            approach='', size='', move_tags=[], form_quality=0, effort_level=0,
            confidence=None, description='', labeled_at=_iso(move.labeled_at),
            frame_tag_count=len(tags),
        )

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
        form_quality=move.form_quality,
        effort_level=move.effort_level,
        confidence=move.confidence or None,
        description=move.description,
        labeled_at=_iso(move.labeled_at),
        frame_tag_count=len(tags),
    )


def environment_to_response(env: Environment) -> EnvironmentResponse:
    """Convert Environment model to response schema."""
    slots = {
        slot: HoldSlot(
            hold_id=getattr(env, f'{slot}_hold_id'),
            hold_type=getattr(env, f'{slot}_hold_type'),
            hold_quality=getattr(env, f'{slot}_hold_quality') or [],
        )
        for slot in HOLD_SLOTS
    }
    return EnvironmentResponse(
        id=env.id,
        move_id=env.move_id,
        wall_angle=env.wall_angle,
        start_left=slots['start_left'],
        start_right=slots['start_right'],
        end=slots['end'],
        foot=slots['foot'],
        taxonomy_version=env.taxonomy_version,
        is_gold=env.is_gold,
    )


def outcome_to_response(outcome: Outcome) -> OutcomeResponse:
    """Convert Outcome model to response schema."""
    return OutcomeResponse(
        id=outcome.id,
        move_id=outcome.move_id,
        result=outcome.result,
        reach_detail=outcome.reach_detail,
        confidence=outcome.confidence or None,
        taxonomy_version=outcome.taxonomy_version,
        is_gold=outcome.is_gold,
    )


def frame_tag_to_response(tag: FrameTag) -> FrameTagResponse:
    """Convert FrameTag model to response schema."""
    return FrameTagResponse(
        id=tag.id,
        move_id=tag.move_id,
        frame_number=tag.frame_number,
        timestamp_ms=tag.timestamp_ms,
        tag_type=tag.tag_type,
        side=tag.side,
        level=tag.level,
        locations=tag.locations,
        note=tag.note,
        tagged_at=_iso(tag.tagged_at),
        taxonomy_version=tag.taxonomy_version,
        is_gold=tag.is_gold,
    )


def _bad_request(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


def _not_found(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


def _forbidden(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


def _conflict(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)


def _require_video(video_id: int, user_id: str) -> Video:
    """Fetch one of this user's OWN videos or 404.

    Owner-only routes (upload, export) use this. Another user's video is
    indistinguishable from a missing one. Raters and admins do not get in
    here; see _require_video_access for shared reads.
    """
    video = get_db().get_video(video_id, user_id)
    if not video:
        raise _not_found(f"Video {video_id} not found")
    return video


def _self_upload_forbidden() -> HTTPException:
    return _forbidden(
        'Self-upload is switched off (SELF_UPLOAD_ENABLED). '
        'Videos are uploaded and prepped by an admin.'
    )


def _require_uploader(user_id: str) -> bool:
    """Who may register and upload a video: an admin always; anyone else only
    while the community self-upload flag is on. Returns is_admin."""
    if get_db().is_admin(user_id):
        return True
    if not self_upload_enabled():
        raise _self_upload_forbidden()
    return False


def _require_upload_video(video_id: int, user_id: str) -> Video:
    """One of the caller's own videos for an upload step, or 404 / 403.

    Same ownership rule as _require_video, plus the self-upload gate for
    non-admins, so turning the flag off also stops a half-finished community
    upload rather than only hiding the button.
    """
    video = _require_video(video_id, user_id)
    _require_uploader(user_id)
    return video


def _require_pose_done(video: Video) -> None:
    """409 until the worker has written the pose CSV."""
    if video.pose_status != 'done' or not video.r2_pose_csv_key:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f'pose extraction not finished (status={video.pose_status or "pending"})',
        )


@dataclass
class VideoAccess:
    """The caller's resolved relationship to one video."""
    video: Video
    role: str  # owner | rater | admin
    user_id: str
    assignment: Optional[VideoAssignment] = None

    @property
    def is_admin(self) -> bool:
        return self.role == 'admin'


def _require_video_access(video_id: int, user_id: str) -> VideoAccess:
    """Resolve the caller to owner / rater / admin on a video, or 404.

    Order matters for the Dataset B fast path: an owner of a draft video is
    resolved with a single query and never pays for the admin lookup. An owner
    of a locked video is checked for admin so an admin prepping their own
    upload can still edit it after marking it ready.
    """
    db = get_db()
    video = db.get_video(video_id, user_id)
    if video:
        if video.is_locked() and db.is_admin(user_id):
            return VideoAccess(video, 'admin', user_id)
        return VideoAccess(video, 'owner', user_id)

    video = db.get_video_any(video_id)
    if not video:
        raise _not_found(f"Video {video_id} not found")

    if db.is_admin(user_id):
        return VideoAccess(video, 'admin', user_id)

    assignment = db.get_assignment_for(video_id, user_id)
    if assignment:
        return VideoAccess(video, 'rater', user_id, assignment)

    # Not yours, not assigned, not admin: indistinguishable from missing.
    raise _not_found(f"Video {video_id} not found")


def _require_structure_write(access: VideoAccess):
    """Holds and canonical moves: owner while draft, admin always, rater never.

    403 rather than 404 because the caller can see the video; what they may
    not do is change its structure. Locked means locked: the owner of a ready
    or closed video is refused too, unless they are an admin.
    """
    if access.is_admin:
        return
    if access.role == 'rater':
        raise _forbidden('Raters cannot create, edit or delete holds or moves')
    # A non-admin owner is the community flow, which the flag switches off.
    if not self_upload_enabled() and not get_db().is_admin(access.user_id):
        raise _self_upload_forbidden()
    if access.video.is_locked():
        raise _forbidden(
            f"Video {access.video.id} is {access.video.prep_status}: holds and moves are locked"
        )


def _require_label_write(access: VideoAccess):
    """Environment / outcome / frame_tag rows: owner, admin, or a rater whose
    assignment is still open on a video that is not closed.

    A rater's first label write moves their assignment to in_progress. A
    non-admin owner labeling their own video is the community flow and needs
    SELF_UPLOAD_ENABLED.
    """
    if access.role == 'owner':
        if not self_upload_enabled() and not get_db().is_admin(access.user_id):
            raise _self_upload_forbidden()
        return
    if access.role != 'rater':
        return
    if access.video.prep_status == 'closed':
        raise _forbidden(f"Video {access.video.id} is closed to rating")
    assignment = access.assignment
    if not assignment.is_open():
        raise _forbidden(f"Assignment {assignment.id} is already {assignment.status}")
    if assignment.status == 'assigned':
        get_db().set_assignment_status(assignment.id, 'in_progress')
        assignment.status = 'in_progress'


def _require_move_access(move_id: int, user_id: str) -> tuple:
    """Fetch a move the caller may read, with their access to its video, or 404."""
    move = get_db().get_move_any(move_id)
    if not move:
        raise _not_found(f"Move {move_id} not found")
    try:
        access = _require_video_access(move.video_id, user_id)
    except HTTPException:
        # The video 404 would leak nothing, but keep the message about the move.
        raise _not_found(f"Move {move_id} not found")
    return move, access


def _require_move(move_id: int, user_id: str) -> Move:
    """Fetch a move the caller may read, or 404."""
    move, _ = _require_move_access(move_id, user_id)
    return move


def _require_hold_access(hold_id: int, user_id: str) -> VideoAccess:
    """Access to the video a hold sits on, or 404 for the hold."""
    hold = get_db().get_hold_any(hold_id)
    if not hold:
        raise _not_found(f"Hold {hold_id} not found")
    try:
        return _require_video_access(hold.video_id, user_id)
    except HTTPException:
        raise _not_found(f"Hold {hold_id} not found")


def _validate_slot(name: str, slot: HoldSlot, user_id: str, video_id: int):
    """Validate a hold slot's type, qualities and that the hold belongs to the
    move's video (and so is one the caller may see).

    A hold on a video the caller cannot access is 404, as before. A hold the
    caller can see but on a different video is 400: slots reference the
    locked hold set of the move's own video.
    """
    if slot.hold_type and slot.hold_type not in HOLD_TYPES:
        raise _bad_request(
            f"Invalid {name}.hold_type: {slot.hold_type}. Must be one of: {HOLD_TYPES}"
        )
    for quality in slot.hold_quality:
        if quality not in HOLD_QUALITIES:
            raise _bad_request(
                f"Invalid {name}.hold_quality: {quality}. Must be one of: {HOLD_QUALITIES}"
            )
    if slot.hold_id is None:
        return
    hold = get_db().get_hold_any(slot.hold_id)
    if not hold:
        raise _not_found(f"Hold {slot.hold_id} not found")
    if hold.video_id != video_id:
        try:
            _require_video_access(hold.video_id, user_id)
        except HTTPException:
            raise _not_found(f"Hold {slot.hold_id} not found")
        raise _bad_request(
            f"Hold {slot.hold_id} belongs to video {hold.video_id}, not video {video_id}"
        )


def _apply_slots_to_env(env: Environment, data, user_id: str, video_id: int):
    """Copy the four slot objects onto an Environment model."""
    for slot_name in HOLD_SLOTS:
        slot = getattr(data, slot_name, None)
        if slot is None:
            continue
        _validate_slot(slot_name, slot, user_id, video_id)
        setattr(env, f'{slot_name}_hold_id', slot.hold_id)
        setattr(env, f'{slot_name}_hold_type', slot.hold_type)
        setattr(env, f'{slot_name}_hold_quality', slot.hold_quality)


async def require_admin(user_id: str = Depends(get_current_user_id)) -> str:
    """FastAPI dependency: the caller's user id, or 403 if not an admin.

    403 (not 404) on purpose: the admin routes are not secret, they are
    simply not for this caller.
    """
    if not get_db().is_admin(user_id):
        raise _forbidden('Admin only')
    return user_id


# ==================== HEALTH / CONFIG ====================

@app.get("/")
async def root():
    """Unauthenticated liveness probe."""
    return {"status": "ok", "message": "Dynalytix Climbing API is running"}


@app.get("/api/health", response_model=HealthResponse)
async def health():
    """Unauthenticated readiness probe: reports Postgres and R2 reachability.

    Left open deliberately - Railway's health check has no JWT to present.
    """
    database_status = 'ok'
    schema_version = None
    try:
        schema_version = get_db().check_schema()
    except SchemaNotApplied as exc:
        database_status = f'schema: {exc}'
    except Exception as exc:
        database_status = f'error: {type(exc).__name__}'

    r2_status = 'ok' if r2.is_configured() else 'not configured'

    overall = 'ok' if database_status == 'ok' and r2_status == 'ok' else 'degraded'
    return HealthResponse(
        status=overall,
        database=database_status,
        r2=r2_status,
        schema_version=schema_version,
    )


@app.get("/api/config", response_model=ConfigResponse)
async def get_config(user_id: str = Depends(get_current_user_id)):
    """Get configuration data - complete taxonomy for all three lenses."""
    return ConfigResponse(
        version=TAXONOMY_VERSION,
        # Lens 2: Strategy
        approaches=APPROACHES,
        sizes=SIZES,
        move_tags=MOVE_TAGS,
        # Lens 1: Environment
        wall_angles=WALL_ANGLES,
        hold_types=HOLD_TYPES,
        hold_qualities=HOLD_QUALITIES,
        hold_slots=HOLD_SLOTS,
        hold_sources=HOLD_SOURCES,
        # Lens 3: Outcome
        results=RESULTS,
        reach_details=REACH_DETAILS,
        confidence_levels=CONFIDENCE_LEVELS,
        # Sensation (Frame Tags)
        tag_types=TAG_TYPES,
        body_parts=BODY_PARTS,
        sides=SIDES,
        # Definitions rendered as an "i" tooltip beside each option.
        definitions=DEFINITIONS,
        self_upload_enabled=self_upload_enabled(),
        source_types=PAPER_SOURCE_TYPES,
    )


# ==================== VIDEO ENDPOINTS ====================

@app.post("/api/videos/register", response_model=VideoResponse, status_code=status.HTTP_201_CREATED)
async def register_video(
    payload: VideoRegister,
    user_id: str = Depends(get_current_user_id),
):
    """
    Register a video the browser is about to upload.

    Creates the row with the browser's provisional metadata (see
    VideoRegister) and pose_status 'pending'. No CSV is accepted any more:
    the flow is register -> upload-url -> PUT to R2 -> confirm-upload, and
    confirm-upload enqueues the pose worker, which writes the CSV.

    Admin only, unless SELF_UPLOAD_ENABLED: then anyone may register, and a
    non-admin's video is a community video (excluded from paper exports).
    """
    is_admin = _require_uploader(user_id)
    video = Video(
        user_id=user_id,
        source_type='public_broadcast' if is_admin else COMMUNITY_SOURCE_TYPE,
        filename=payload.filename,
        fps=payload.fps,
        total_frames=payload.total_frames,
        duration_ms=payload.duration_ms,
        width=payload.width,
        height=payload.height,
        uploaded_at=datetime.now(timezone.utc),
        pose_status='pending',
    )
    video.id = get_db().create_video(video)
    return video_to_response(video)


@app.post("/api/videos/{video_id}/upload-url", response_model=UploadUrlResponse)
async def create_upload_url(
    video_id: int,
    payload: UploadUrlRequest,
    user_id: str = Depends(get_current_user_id),
):
    """Presigned PUT URL so the browser uploads the original video to R2 directly."""
    video = _require_upload_video(video_id, user_id)

    key = r2.video_key(user_id, video_id, video.filename)
    expires_in = 3600
    try:
        url = r2.presigned_put_url(key, content_type=payload.content_type, expires_in=expires_in)
    except r2.R2NotConfigured as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f'Object storage unavailable: {exc}',
        )

    return UploadUrlResponse(url=url, key=key, expires_in=expires_in)


def _multipart_key(video, user_id: str) -> str:
    """The one key a multipart upload for this video is allowed to write."""
    return r2.video_key(user_id, video.id, video.filename)


def _guard_multipart_key(video, user_id: str, key: str) -> str:
    """Refuse any key but this video's own, so a client cannot assemble parts
    into another user's object."""
    expected = _multipart_key(video, user_id)
    if key != expected:
        raise _bad_request('Key does not belong to this video')
    return key


@app.post("/api/videos/{video_id}/upload/create-multipart", response_model=CreateMultipartResponse)
async def create_multipart(
    video_id: int,
    payload: CreateMultipartRequest,
    user_id: str = Depends(get_current_user_id),
):
    """Start a resumable upload.

    The phone is the primary client and iOS Safari kills a page on app switch
    or lock, so the original video goes up in independently signed parts. The
    browser holds on to `upload_id` and resumes from the first part it has no
    ETag for.
    """
    video = _require_upload_video(video_id, user_id)
    key = _multipart_key(video, user_id)

    try:
        upload_id = r2.create_multipart_upload(key, content_type=payload.content_type)
    except r2.R2NotConfigured as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f'Object storage unavailable: {exc}',
        )

    return CreateMultipartResponse(
        key=key, upload_id=upload_id, part_size=r2.MULTIPART_PART_SIZE
    )


@app.post("/api/videos/{video_id}/upload/sign-part", response_model=SignPartResponse)
async def sign_upload_part(
    video_id: int,
    payload: SignPartRequest,
    user_id: str = Depends(get_current_user_id),
):
    """Presign one part. Called again on resume, and again on a part retry."""
    video = _require_upload_video(video_id, user_id)
    key = _guard_multipart_key(video, user_id, payload.key)

    expires_in = 3600
    try:
        url = r2.presigned_upload_part_url(
            key, payload.upload_id, payload.part_number, expires_in=expires_in
        )
    except r2.R2NotConfigured as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f'Object storage unavailable: {exc}',
        )

    return SignPartResponse(
        url=url, part_number=payload.part_number, expires_in=expires_in
    )


@app.post("/api/videos/{video_id}/upload/complete-multipart", response_model=VideoResponse)
async def complete_multipart(
    video_id: int,
    payload: CompleteMultipartRequest,
    user_id: str = Depends(get_current_user_id),
):
    """Assemble the parts, record the key, and enqueue the pose worker.

    This is confirm-upload for the multipart path: same post-conditions, one
    round trip instead of two, because the phone may not get another.
    """
    video = _require_upload_video(video_id, user_id)
    key = _guard_multipart_key(video, user_id, payload.key)

    if not payload.parts:
        raise _bad_request('No parts to complete')

    try:
        r2.complete_multipart_upload(
            key,
            payload.upload_id,
            [{'PartNumber': part.part_number, 'ETag': part.etag} for part in payload.parts],
        )
    except r2.R2NotConfigured as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f'Object storage unavailable: {exc}',
        )

    get_db().set_video_r2_keys(video_id, user_id, r2_video_key=key)
    video.r2_video_key = key
    return video_to_response(_enqueue_or_fail(video))


@app.post("/api/videos/{video_id}/upload/abort-multipart")
async def abort_multipart(
    video_id: int,
    payload: AbortMultipartRequest,
    user_id: str = Depends(get_current_user_id),
):
    """Discard an abandoned upload so R2 stops billing for its parts."""
    video = _require_upload_video(video_id, user_id)
    key = _guard_multipart_key(video, user_id, payload.key)

    try:
        r2.abort_multipart_upload(key, payload.upload_id)
    except r2.R2NotConfigured as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f'Object storage unavailable: {exc}',
        )

    return {'aborted': True, 'key': key}


@app.post("/api/videos/{video_id}/confirm-upload", response_model=VideoResponse)
async def confirm_upload(
    video_id: int,
    payload: ConfirmUploadRequest,
    user_id: str = Depends(get_current_user_id),
):
    """Record the R2 key once the browser's direct upload has finished, then
    enqueue pose extraction.

    Always 200 once the key is recorded: an enqueue failure (worker down or not
    configured) is reported through pose_status='failed' + pose_error rather
    than failing the confirm, because the upload itself succeeded.
    """
    video = _require_upload_video(video_id, user_id)

    key = payload.key or r2.video_key(user_id, video_id, video.filename)

    # Never let a client point a row at another user's prefix.
    if not key.startswith(f'videos/{user_id}/'):
        raise _bad_request('Key does not belong to this user')

    get_db().set_video_r2_keys(video_id, user_id, r2_video_key=key)
    video.r2_video_key = key
    return video_to_response(_enqueue_or_fail(video))


@app.get("/api/videos/{video_id}/status", response_model=PoseStatusResponse)
async def get_pose_status(video_id: int, user_id: str = Depends(get_current_user_id)):
    """Pose job state, polled by the header chip until done/failed.

    Owner, assigned rater or admin: a rater's rating view waits on the same
    skeleton the owner does.
    """
    return pose_status_to_response(_require_video_access(video_id, user_id).video)


@app.post("/api/videos/{video_id}/retry-pose", response_model=PoseStatusResponse)
async def retry_pose(video_id: int, user_id: str = Depends(get_current_user_id)):
    """Re-enqueue a failed (or stuck pending) job. 409 while processing or done.

    Owner or admin. A rater can see the failure on /status but 403s here:
    re-running the worker is the prepper's (or admin's) call.
    """
    access = _require_video_access(video_id, user_id)
    if access.role == 'rater':
        raise _forbidden('Only the video owner or an admin can retry pose extraction')
    if access.role == 'owner':
        _require_uploader(user_id)  # a non-admin owner needs SELF_UPLOAD_ENABLED
    video = access.video
    if video.pose_status in ('processing', 'done'):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f'pose extraction is {video.pose_status}; nothing to retry',
        )
    if not video.r2_video_key:
        raise _bad_request('Upload the video before retrying pose extraction')
    return pose_status_to_response(_enqueue_or_fail(video))


@app.post("/api/videos/{video_id}/pose-result", response_model=PoseStatusResponse)
async def pose_result(video_id: int, payload: PoseResult, request: Request):
    """Worker callback (secret-authenticated, no user JWT).

    Fallback to the worker writing Postgres directly: the same row update,
    behind the backend's connection pool. `status` moves the job and the
    measured fps/total_frames/duration_ms/width/height overwrite the
    browser's provisional values.
    """
    _require_worker_secret(request)
    if payload.status not in ('processing', 'done', 'failed'):
        raise _bad_request(f'Invalid status: {payload.status}')
    if payload.status == 'done' and not payload.r2_pose_csv_key:
        raise _bad_request('done requires r2_pose_csv_key')

    db = get_db()
    updated = db.record_pose_result(
        video_id,
        payload.status,
        error=payload.error,
        fps=payload.fps,
        total_frames=payload.total_frames,
        duration_ms=payload.duration_ms,
        width=payload.width,
        height=payload.height,
        r2_pose_csv_key=payload.r2_pose_csv_key,
        has_cut=payload.has_cut,
        cut_frames=payload.cut_frames,
        camera_motion_score=payload.camera_motion_score,
        camera_zoom_range=payload.camera_zoom_range,
        camera_motion_frames_pct=payload.camera_motion_frames_pct,
    )
    if not updated:
        raise _not_found(f"Video {video_id} not found")

    with db.get_connection() as conn:
        row = conn.execute('SELECT * FROM videos WHERE id = %s', (video_id,)).fetchone()
    return pose_status_to_response(db._row_to_video(row))


@app.get("/api/videos/{video_id}/pose-csv-url", response_model=PoseCsvUrlResponse)
async def get_pose_csv_url(video_id: int, user_id: str = Depends(get_current_user_id)):
    """Presigned GET URL for the pose CSV, as JSON (no redirect to unwrap).

    Owner, assigned rater or admin. 409 until the worker has finished, like
    export.
    """
    video = _require_video_access(video_id, user_id).video
    _require_pose_done(video)
    expires_in = 3600
    try:
        url = r2.presigned_get_url(video.r2_pose_csv_key, expires_in=expires_in)
    except r2.R2NotConfigured as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f'Object storage unavailable: {exc}',
        )
    return PoseCsvUrlResponse(url=url, expires_in=expires_in)


@app.get("/api/videos", response_model=List[VideoResponse])
async def list_videos(user_id: str = Depends(get_current_user_id)):
    """Get all of the current user's videos."""
    return [video_to_response(v) for v in get_db().get_all_videos(user_id)]


@app.get("/api/videos/{video_id}", response_model=VideoResponse)
async def get_video(video_id: int, user_id: str = Depends(get_current_user_id)):
    """Get a specific video by ID. Owner, assigned rater or admin."""
    access = _require_video_access(video_id, user_id)
    return video_to_response(access.video, access.role)


@app.get("/api/videos/{video_id}/csv")
async def get_video_csv(video_id: int, user_id: str = Depends(get_current_user_id)):
    """Redirect to a presigned URL for the raw pose CSV. Owner, rater or admin.
    409 until the pose worker has finished."""
    video = _require_video_access(video_id, user_id).video
    _require_pose_done(video)

    url = r2.presigned_get_url(
        video.r2_pose_csv_key,
        download_filename=f'{video.filename}.csv',
    )
    return RedirectResponse(url=url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)


@app.get("/api/videos/{video_id}/video-url", response_model=PlaybackUrlResponse)
async def get_video_playback_url(video_id: int, user_id: str = Depends(get_current_user_id)):
    """Presigned GET URL for the original video. Owner, rater or admin.

    A rater never had the file in their browser, so without this the rating
    view has nothing to play. Returned as JSON rather than a redirect so the
    client can drop it straight into a <video src>. 404 when the original was
    never uploaded (the pose CSV is registered separately and may exist alone).
    """
    video = _require_video_access(video_id, user_id).video
    if not video.r2_video_key:
        raise _not_found("No original video stored for this video")

    expires_in = 3600
    try:
        url = r2.presigned_get_url(video.r2_video_key, expires_in=expires_in)
    except r2.R2NotConfigured as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f'Object storage unavailable: {exc}',
        )
    return PlaybackUrlResponse(url=url, expires_in=expires_in)


@app.post("/api/videos/{video_id}/export", response_model=ExportResponse)
async def export_video_endpoint(video_id: int, user_id: str = Depends(get_current_user_id)):
    """
    Export labeled data for a video.

    Streams the pose CSV out of R2, joins the labels from Postgres and writes
    the result back to R2, recording the key on the video row. 409 until the
    pose worker has finished.
    """
    _require_pose_done(_require_video(video_id, user_id))

    try:
        key = get_exporter().export_video(video_id, user_id)
    except ValueError as exc:
        raise _not_found(str(exc))
    except r2.R2NotConfigured as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f'Object storage unavailable: {exc}',
        )

    return ExportResponse(video_id=video_id, r2_export_key=key)


@app.get("/api/videos/{video_id}/export/download")
async def download_export(video_id: int, user_id: str = Depends(get_current_user_id)):
    """Redirect to a presigned URL for the labeled export."""
    video = _require_video(video_id, user_id)
    _require_pose_done(video)
    if not video.r2_export_key:
        raise _not_found("Export not found. Run export first.")

    url = r2.presigned_get_url(
        video.r2_export_key,
        download_filename=f'{video.filename}_labeled.csv',
    )
    return RedirectResponse(url=url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)


@app.get("/api/exports/mine", response_model=List[ExportListItem])
async def list_my_exports(user_id: str = Depends(get_current_user_id)):
    """List the current user's exports."""
    return [
        ExportListItem(
            video_id=v.id,
            filename=v.filename,
            r2_export_key=v.r2_export_key,
            uploaded_at=_iso(v.uploaded_at),
        )
        for v in get_db().get_videos_with_exports(user_id)
    ]


# ==================== HOLD ENDPOINTS ====================

@app.post("/api/holds", response_model=HoldResponse, status_code=status.HTTP_201_CREATED)
async def create_hold(hold_data: HoldCreate, user_id: str = Depends(get_current_user_id)):
    """Mark a hold on a video. Owner of a draft video, or admin."""
    _require_structure_write(_require_video_access(hold_data.video_id, user_id))

    if hold_data.source not in HOLD_SOURCES:
        raise _bad_request(
            f"Invalid source: {hold_data.source}. Must be one of: {HOLD_SOURCES}"
        )

    hold = Hold(
        video_id=hold_data.video_id,
        user_id=user_id,
        bbox_x=hold_data.bbox_x,
        bbox_y=hold_data.bbox_y,
        bbox_w=hold_data.bbox_w,
        bbox_h=hold_data.bbox_h,
        source=hold_data.source,
        created_at=datetime.now(timezone.utc),
    )
    hold.id = get_db().create_hold(hold)
    return hold_to_response(hold)


@app.get("/api/videos/{video_id}/holds", response_model=List[HoldResponse])
async def list_holds(video_id: int, user_id: str = Depends(get_current_user_id)):
    """Get all holds marked on a video. Owner, rater or admin."""
    _require_video_access(video_id, user_id)
    return [hold_to_response(h) for h in get_db().get_holds_for_video_any(video_id)]


@app.post(
    "/api/videos/{video_id}/holds",
    response_model=List[HoldResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_holds_bulk(
    video_id: int,
    payload: HoldBulkCreate,
    user_id: str = Depends(get_current_user_id),
):
    """Mark many holds on a video at once.

    This is what the in-browser detector posts after it runs on the first
    frame: one request for the whole wall, in one transaction, so a failure
    part-way through leaves no holds rather than a partial set.
    """
    # Shape checks first: a runaway payload is rejected without a DB round trip.
    if len(payload.holds) > MAX_HOLDS_PER_REQUEST:
        raise _bad_request(
            f'Too many holds in one request: {len(payload.holds)}. '
            f'Maximum is {MAX_HOLDS_PER_REQUEST}.'
        )
    for hold in payload.holds:
        if hold.source not in HOLD_SOURCES:
            raise _bad_request(
                f"Invalid source: {hold.source}. Must be one of: {HOLD_SOURCES}"
            )

    _require_structure_write(_require_video_access(video_id, user_id))

    if not payload.holds:
        return []

    now = datetime.now(timezone.utc)
    holds = [
        Hold(
            video_id=video_id,
            user_id=user_id,
            bbox_x=h.bbox_x,
            bbox_y=h.bbox_y,
            bbox_w=h.bbox_w,
            bbox_h=h.bbox_h,
            source=h.source,
            created_at=now,
        )
        for h in payload.holds
    ]

    ids = get_db().create_holds_bulk(holds)
    for hold, hold_id in zip(holds, ids):
        hold.id = hold_id
    return [hold_to_response(h) for h in holds]


@app.put("/api/holds/{hold_id}", response_model=HoldResponse)
async def update_hold(
    hold_id: int,
    payload: HoldUpdate,
    user_id: str = Depends(get_current_user_id),
):
    """Move or resize a hold, or change whether it is detected or manual."""
    if payload.source is not None and payload.source not in HOLD_SOURCES:
        raise _bad_request(
            f"Invalid source: {payload.source}. Must be one of: {HOLD_SOURCES}"
        )

    _require_structure_write(_require_hold_access(hold_id, user_id))

    updated = get_db().update_hold_any(
        hold_id,
        bbox_x=payload.bbox_x,
        bbox_y=payload.bbox_y,
        bbox_w=payload.bbox_w,
        bbox_h=payload.bbox_h,
        source=payload.source,
    )
    if updated is None:
        raise _not_found(f"Hold {hold_id} not found")
    return hold_to_response(updated)


@app.delete("/api/holds/{hold_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_hold(hold_id: int, user_id: str = Depends(get_current_user_id)):
    """Delete a hold. Owner of a draft video, or admin."""
    _require_structure_write(_require_hold_access(hold_id, user_id))
    if not get_db().delete_hold_any(hold_id):
        raise _not_found(f"Hold {hold_id} not found")
    return None


# ==================== MOVE ENDPOINTS ====================

@app.post("/api/moves", response_model=MoveResponse, status_code=status.HTTP_201_CREATED)
async def create_move(move_data: MoveCreate, user_id: str = Depends(get_current_user_id)):
    """Create a new move. Owner of a draft video, or admin."""
    _require_structure_write(_require_video_access(move_data.video_id, user_id))

    if move_data.approach not in APPROACHES:
        raise _bad_request(
            f"Invalid approach: {move_data.approach}. Must be one of: {APPROACHES}"
        )
    if move_data.size not in SIZES:
        raise _bad_request(f"Invalid size: {move_data.size}. Must be one of: {SIZES}")
    for tag in move_data.move_tags:
        if tag not in MOVE_TAGS:
            raise _bad_request(f"Invalid move tag: {tag}. Must be one of: {MOVE_TAGS}")
    if move_data.confidence is not None and move_data.confidence not in CONFIDENCE_LEVELS:
        raise _bad_request(
            f"Invalid confidence: {move_data.confidence}. Must be one of: {CONFIDENCE_LEVELS}"
        )

    move = Move(
        video_id=move_data.video_id,
        user_id=user_id,
        frame_start=move_data.frame_start,
        frame_end=move_data.frame_end,
        timestamp_start_ms=move_data.timestamp_start_ms,
        timestamp_end_ms=move_data.timestamp_end_ms,
        approach=move_data.approach,
        size=move_data.size,
        move_tags=move_data.move_tags,
        form_quality=move_data.form_quality,
        effort_level=move_data.effort_level,
        confidence=move_data.confidence or '',
        description=move_data.description,
        labeled_at=datetime.now(timezone.utc),
    )
    move.id = get_db().create_move(move)

    return move_to_response(move, user_id)


@app.get("/api/videos/{video_id}/moves", response_model=List[MoveResponse])
async def list_moves(video_id: int, user_id: str = Depends(get_current_user_id)):
    """Get all moves for a video: the canonical list, ordered by frame_start.

    Owner, rater or admin. frame_tag_count is the caller's own tag count.
    """
    access = _require_video_access(video_id, user_id)
    moves = get_db().get_moves_for_video_any(video_id)
    return [move_to_response(m, user_id, access.role) for m in moves]


@app.get("/api/moves/{move_id}", response_model=MoveResponse)
async def get_move(move_id: int, user_id: str = Depends(get_current_user_id)):
    """Get a specific move by ID."""
    move, access = _require_move_access(move_id, user_id)
    return move_to_response(move, user_id, access.role)


@app.put("/api/moves/{move_id}", response_model=MoveResponse)
async def update_move(
    move_id: int,
    move_data: MoveUpdate,
    user_id: str = Depends(get_current_user_id),
):
    """Update an existing move. Owner of a draft video, or admin."""
    move, access = _require_move_access(move_id, user_id)
    _require_structure_write(access)

    if move_data.approach is not None:
        if move_data.approach not in APPROACHES:
            raise _bad_request(f"Invalid approach: {move_data.approach}")
        move.approach = move_data.approach
    if move_data.size is not None:
        if move_data.size not in SIZES:
            raise _bad_request(f"Invalid size: {move_data.size}")
        move.size = move_data.size
    if move_data.move_tags is not None:
        for tag in move_data.move_tags:
            if tag not in MOVE_TAGS:
                raise _bad_request(f"Invalid move tag: {tag}")
        move.move_tags = move_data.move_tags
    if move_data.confidence is not None:
        if move_data.confidence not in CONFIDENCE_LEVELS:
            raise _bad_request(f"Invalid confidence: {move_data.confidence}")
        move.confidence = move_data.confidence
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
    if move_data.description is not None:
        move.description = move_data.description

    get_db().update_move_any(move)

    return move_to_response(move, user_id)


@app.delete("/api/moves/{move_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_move(move_id: int, user_id: str = Depends(get_current_user_id)):
    """Delete a move and every rater's frame tags, environment and outcome on
    it. Owner of a draft video, or admin."""
    _, access = _require_move_access(move_id, user_id)
    _require_structure_write(access)
    if not get_db().delete_move_any(move_id):
        raise _not_found(f"Move {move_id} not found")
    return None


# ==================== ENVIRONMENT ENDPOINTS (Lens 1) ====================

@app.post("/api/environments", response_model=EnvironmentResponse, status_code=status.HTTP_201_CREATED)
async def create_environment(
    env_data: EnvironmentCreate,
    user_id: str = Depends(get_current_user_id),
):
    """Create the caller's environment record for a move.

    One per (move, rater): a rater on a Dataset A video gets their own, and
    never sees anyone else's.
    """
    move, access = _require_move_access(env_data.move_id, user_id)
    _require_label_write(access)

    if get_db().get_environment_for_move(env_data.move_id, user_id):
        raise _conflict(
            f"Environment already exists for move {env_data.move_id}. Use PUT to update."
        )

    if env_data.wall_angle not in WALL_ANGLES:
        raise _bad_request(
            f"Invalid wall_angle: {env_data.wall_angle}. Must be one of: {WALL_ANGLES}"
        )

    env = Environment(
        move_id=env_data.move_id,
        user_id=user_id,
        wall_angle=env_data.wall_angle,
        taxonomy_version=TAXONOMY_VERSION,
    )
    _apply_slots_to_env(env, env_data, user_id, move.video_id)

    env.id = get_db().create_environment(env)
    return environment_to_response(env)


@app.get("/api/moves/{move_id}/environment", response_model=EnvironmentResponse)
async def get_environment(move_id: int, user_id: str = Depends(get_current_user_id)):
    """Get the caller's own environment record for a move (404 if none)."""
    _require_move(move_id, user_id)

    env = get_db().get_environment_for_move(move_id, user_id)
    if not env:
        raise _not_found(f"No environment record for move {move_id}")

    return environment_to_response(env)


@app.put("/api/environments/{env_id}", response_model=EnvironmentResponse)
async def update_environment(
    env_id: int,
    env_data: EnvironmentUpdate,
    user_id: str = Depends(get_current_user_id),
):
    """Update the caller's own environment record (another rater's is 404)."""
    env = get_db().get_environment(env_id, user_id)
    if not env:
        raise _not_found(f"Environment {env_id} not found")
    move, access = _require_move_access(env.move_id, user_id)
    _require_label_write(access)

    if env_data.wall_angle is not None:
        if env_data.wall_angle not in WALL_ANGLES:
            raise _bad_request(f"Invalid wall_angle: {env_data.wall_angle}")
        env.wall_angle = env_data.wall_angle

    _apply_slots_to_env(env, env_data, user_id, move.video_id)
    env.taxonomy_version = TAXONOMY_VERSION

    get_db().update_environment(env)
    return environment_to_response(env)


@app.delete("/api/environments/{env_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_environment(env_id: int, user_id: str = Depends(get_current_user_id)):
    """Delete the caller's own environment record."""
    env = get_db().get_environment(env_id, user_id)
    if not env:
        raise _not_found(f"Environment {env_id} not found")
    _, access = _require_move_access(env.move_id, user_id)
    _require_label_write(access)
    get_db().delete_environment(env_id, user_id)
    return None


# ==================== OUTCOME ENDPOINTS (Lens 3) ====================

@app.post("/api/outcomes", response_model=OutcomeResponse, status_code=status.HTTP_201_CREATED)
async def create_outcome(
    outcome_data: OutcomeCreate,
    user_id: str = Depends(get_current_user_id),
):
    """Create the caller's outcome record for a move (one per move per rater)."""
    _, access = _require_move_access(outcome_data.move_id, user_id)
    _require_label_write(access)

    if get_db().get_outcome_for_move(outcome_data.move_id, user_id):
        raise _conflict(
            f"Outcome already exists for move {outcome_data.move_id}. Use PUT to update."
        )

    if outcome_data.result not in RESULTS:
        raise _bad_request(f"Invalid result: {outcome_data.result}. Must be one of: {RESULTS}")
    if outcome_data.reach_detail not in REACH_DETAILS:
        raise _bad_request(
            f"Invalid reach_detail: {outcome_data.reach_detail}. Must be one of: {REACH_DETAILS}"
        )
    if outcome_data.confidence is not None and outcome_data.confidence not in CONFIDENCE_LEVELS:
        raise _bad_request(
            f"Invalid confidence: {outcome_data.confidence}. Must be one of: {CONFIDENCE_LEVELS}"
        )

    outcome = Outcome(
        move_id=outcome_data.move_id,
        user_id=user_id,
        result=outcome_data.result,
        reach_detail=outcome_data.reach_detail,
        confidence=outcome_data.confidence or '',
        taxonomy_version=TAXONOMY_VERSION,
    )
    outcome.id = get_db().create_outcome(outcome)

    return outcome_to_response(outcome)


@app.get("/api/moves/{move_id}/outcome", response_model=OutcomeResponse)
async def get_outcome(move_id: int, user_id: str = Depends(get_current_user_id)):
    """Get the caller's own outcome record for a move (404 if none)."""
    _require_move(move_id, user_id)

    outcome = get_db().get_outcome_for_move(move_id, user_id)
    if not outcome:
        raise _not_found(f"No outcome record for move {move_id}")

    return outcome_to_response(outcome)


@app.put("/api/outcomes/{outcome_id}", response_model=OutcomeResponse)
async def update_outcome(
    outcome_id: int,
    outcome_data: OutcomeUpdate,
    user_id: str = Depends(get_current_user_id),
):
    """Update the caller's own outcome record (another rater's is 404)."""
    outcome = get_db().get_outcome(outcome_id, user_id)
    if not outcome:
        raise _not_found(f"Outcome {outcome_id} not found")
    _, access = _require_move_access(outcome.move_id, user_id)
    _require_label_write(access)

    if outcome_data.result is not None:
        if outcome_data.result not in RESULTS:
            raise _bad_request(f"Invalid result: {outcome_data.result}")
        outcome.result = outcome_data.result
    if outcome_data.reach_detail is not None:
        if outcome_data.reach_detail not in REACH_DETAILS:
            raise _bad_request(f"Invalid reach_detail: {outcome_data.reach_detail}")
        outcome.reach_detail = outcome_data.reach_detail
    if outcome_data.confidence is not None:
        if outcome_data.confidence not in CONFIDENCE_LEVELS:
            raise _bad_request(f"Invalid confidence: {outcome_data.confidence}")
        outcome.confidence = outcome_data.confidence

    outcome.taxonomy_version = TAXONOMY_VERSION
    get_db().update_outcome(outcome)
    return outcome_to_response(outcome)


@app.delete("/api/outcomes/{outcome_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_outcome(outcome_id: int, user_id: str = Depends(get_current_user_id)):
    """Delete the caller's own outcome record."""
    outcome = get_db().get_outcome(outcome_id, user_id)
    if not outcome:
        raise _not_found(f"Outcome {outcome_id} not found")
    _, access = _require_move_access(outcome.move_id, user_id)
    _require_label_write(access)
    get_db().delete_outcome(outcome_id, user_id)
    return None


# ==================== STRATEGY ENDPOINTS (Lens 2, per rater) ====================

def _validate_strategy_fields(approach=None, size=None, move_tags=None, confidence=None):
    if approach is not None and approach not in APPROACHES:
        raise _bad_request(f"Invalid approach: {approach}. Must be one of: {APPROACHES}")
    if size is not None and size not in SIZES:
        raise _bad_request(f"Invalid size: {size}. Must be one of: {SIZES}")
    for tag in move_tags or []:
        if tag not in MOVE_TAGS:
            raise _bad_request(f"Invalid move tag: {tag}. Must be one of: {MOVE_TAGS}")
    if confidence is not None and confidence != '' and confidence not in CONFIDENCE_LEVELS:
        raise _bad_request(f"Invalid confidence: {confidence}. Must be one of: {CONFIDENCE_LEVELS}")


@app.post("/api/strategies", response_model=StrategyResponse, status_code=status.HTTP_201_CREATED)
async def create_strategy(
    data: StrategyCreate,
    user_id: str = Depends(get_current_user_id),
):
    """Create the caller's Strategy row for a move (one per move per rater).

    Raters label Strategy independently, like Environment and Outcome, so it
    enters the reliability analysis. The canonical move row only fixes the
    move's boundaries.
    """
    _, access = _require_move_access(data.move_id, user_id)
    _require_label_write(access)

    if get_db().get_strategy_for_move(data.move_id, user_id):
        raise _conflict(f"Strategy already exists for move {data.move_id}. Use PUT to update.")
    _validate_strategy_fields(data.approach, data.size, data.move_tags, data.confidence)

    strategy = Strategy(
        move_id=data.move_id,
        user_id=user_id,
        approach=data.approach,
        size=data.size,
        move_tags=list(data.move_tags),
        form_quality=data.form_quality,
        confidence=data.confidence or '',
        taxonomy_version=TAXONOMY_VERSION,
    )
    try:
        strategy.id = get_db().create_strategy(strategy)
    except psycopg.errors.UniqueViolation:
        raise _conflict(f"Strategy already exists for move {data.move_id}. Use PUT to update.")
    return strategy_to_response(strategy)


@app.get("/api/moves/{move_id}/strategy", response_model=StrategyResponse)
async def get_strategy(move_id: int, user_id: str = Depends(get_current_user_id)):
    """The caller's own Strategy row for a move (404 if none)."""
    _require_move(move_id, user_id)
    strategy = get_db().get_strategy_for_move(move_id, user_id)
    if not strategy:
        raise _not_found(f"No strategy record for move {move_id}")
    return strategy_to_response(strategy)


@app.put("/api/strategies/{strategy_id}", response_model=StrategyResponse)
async def update_strategy(
    strategy_id: int,
    data: StrategyUpdate,
    user_id: str = Depends(get_current_user_id),
):
    """Update the caller's own Strategy row (another rater's is 404)."""
    strategy = get_db().get_strategy(strategy_id, user_id)
    if not strategy:
        raise _not_found(f"Strategy {strategy_id} not found")
    _, access = _require_move_access(strategy.move_id, user_id)
    _require_label_write(access)
    _validate_strategy_fields(data.approach, data.size, data.move_tags, data.confidence)

    if data.approach is not None:
        strategy.approach = data.approach
    if data.size is not None:
        strategy.size = data.size
    if data.move_tags is not None:
        strategy.move_tags = list(data.move_tags)
    if data.form_quality is not None:
        strategy.form_quality = data.form_quality
    if data.confidence is not None:
        strategy.confidence = data.confidence
    strategy.taxonomy_version = TAXONOMY_VERSION
    get_db().update_strategy(strategy)
    return strategy_to_response(strategy)


@app.delete("/api/strategies/{strategy_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_strategy(strategy_id: int, user_id: str = Depends(get_current_user_id)):
    """Delete the caller's own Strategy row."""
    strategy = get_db().get_strategy(strategy_id, user_id)
    if not strategy:
        raise _not_found(f"Strategy {strategy_id} not found")
    _, access = _require_move_access(strategy.move_id, user_id)
    _require_label_write(access)
    get_db().delete_strategy(strategy_id, user_id)
    return None


# ==================== FRAME TAG ENDPOINTS ====================

@app.post("/api/frame-tags", response_model=FrameTagResponse, status_code=status.HTTP_201_CREATED)
async def create_frame_tag(
    tag_data: FrameTagCreate,
    user_id: str = Depends(get_current_user_id),
):
    """Create a frame tag on a move, owned by the caller."""
    _, access = _require_move_access(tag_data.move_id, user_id)
    _require_label_write(access)

    if tag_data.tag_type not in TAG_TYPES:
        raise _bad_request(
            f"Invalid tag type: {tag_data.tag_type}. Must be one of: {list(TAG_TYPES.keys())}"
        )
    if tag_data.side is not None and tag_data.side not in SIDES:
        raise _bad_request(f"Invalid side: {tag_data.side}. Must be one of: {SIDES}")
    for loc in tag_data.locations:
        if loc not in BODY_PARTS:
            raise _bad_request(f"Invalid body part: {loc}. Must be one of: {BODY_PARTS}")

    tag = FrameTag(
        move_id=tag_data.move_id,
        user_id=user_id,
        frame_number=tag_data.frame_number,
        timestamp_ms=tag_data.timestamp_ms,
        tag_type=tag_data.tag_type,
        side=tag_data.side,
        level=tag_data.level,
        locations=tag_data.locations,
        note=tag_data.note,
        tagged_at=datetime.now(timezone.utc),
        taxonomy_version=TAXONOMY_VERSION,
    )
    tag.id = get_db().create_frame_tag(tag)

    return frame_tag_to_response(tag)


@app.get("/api/moves/{move_id}/frame-tags", response_model=List[FrameTagResponse])
async def list_frame_tags(move_id: int, user_id: str = Depends(get_current_user_id)):
    """Get the caller's own frame tags on a move."""
    _require_move(move_id, user_id)
    tags = get_db().get_frame_tags_for_move(move_id, user_id)
    return [frame_tag_to_response(t) for t in tags]


@app.delete("/api/frame-tags/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_frame_tag(tag_id: int, user_id: str = Depends(get_current_user_id)):
    """Delete one of the caller's own frame tags (another rater's is 404)."""
    tag = get_db().get_frame_tag(tag_id, user_id)
    if not tag:
        raise _not_found(f"Frame tag {tag_id} not found")
    _, access = _require_move_access(tag.move_id, user_id)
    _require_label_write(access)
    get_db().delete_frame_tag(tag_id, user_id)
    return None


# ==================== RATER PROFILE (Dataset A) ====================

@app.get("/api/me/profile", response_model=ProfileResponse)
async def get_my_profile(user_id: str = Depends(get_current_user_id)):
    """The caller's rater profile, or 404 if they have not created one yet.

    The app treats the 404 as "show the profile gate".
    """
    profile = get_db().get_rater_profile(user_id)
    if not profile:
        raise _not_found('No profile for this user yet')
    return profile_to_response(profile)


@app.post("/api/me/profile", response_model=ProfileResponse, status_code=status.HTTP_201_CREATED)
async def create_my_profile(
    payload: ProfileCreate,
    user_id: str = Depends(get_current_user_id),
):
    """Create the caller's profile. Saved once; 409 if it already exists.

    is_validated and is_admin start false; only an admin changes those.
    """
    db = get_db()
    if db.get_rater_profile(user_id):
        raise _conflict('Profile already exists')
    profile = RaterProfile(
        user_id=user_id,
        display_name=payload.display_name.strip(),
        is_validated=False,
        years_climbing=payload.years_climbing,
        bio=(payload.bio or '').strip() or None,
        highest_grade=(payload.highest_grade or '').strip() or None,
        research_background=payload.research_background,
        is_admin=False,
        created_at=datetime.now(timezone.utc),
    )
    try:
        created = db.create_rater_profile(profile)
    except psycopg.errors.UniqueViolation:
        raise _conflict('Profile already exists')
    return profile_to_response(created)


@app.put("/api/me/profile", response_model=ProfileResponse)
async def update_my_profile(
    payload: ProfileUpdate,
    user_id: str = Depends(get_current_user_id),
):
    """Edit the caller's own profile. 404 if none yet (POST first).

    is_validated, validation_note and is_admin are not accepted here; an admin sets
    them through PUT /api/admin/raters/{user_id}.
    """
    db = get_db()
    if not db.get_rater_profile(user_id):
        raise _not_found('No profile for this user yet')
    fields = payload.model_dump()
    if fields.get('display_name') is not None:
        fields['display_name'] = fields['display_name'].strip()
    # "" clears an optional text field; the db layer stores None.
    for key in ('bio', 'highest_grade'):
        if fields.get(key) is not None:
            fields[key] = fields[key].strip()
    updated = db.update_rater_profile_self(user_id, **fields)
    return profile_to_response(updated)


# ==================== RATER QUEUE / ASSIGNMENTS ====================

def _require_my_assignment(assignment_id: int, user_id: str) -> VideoAssignment:
    """One of the caller's own assignments, or 404."""
    assignment = get_db().get_assignment(assignment_id)
    if not assignment or assignment.rater_user_id != user_id:
        raise _not_found(f"Assignment {assignment_id} not found")
    return assignment


@app.get("/api/me/assignments", response_model=List[MyAssignmentItem])
async def list_my_assignments(user_id: str = Depends(get_current_user_id)):
    """The caller's rating queue: every assignment with its video and move count.

    Empty until an admin has validated the caller (the app shows a "waiting
    for validation" screen from the profile's is_validated). An admin always
    sees their own queue.
    """
    db = get_db()
    profile = db.get_rater_profile(user_id)
    if not profile or not (profile.is_validated or profile.is_admin):
        return []
    items = []
    for assignment in db.list_assignments_for_rater(user_id):
        video = db.get_video_any(assignment.video_id)
        if not video:
            continue
        items.append(MyAssignmentItem(
            assignment=assignment_to_response(assignment),
            video=video_to_response(video, 'rater'),
            move_count=len(db.get_moves_for_video_any(video.id)),
        ))
    return items


@app.post("/api/assignments/{assignment_id}/start", response_model=AssignmentResponse)
async def start_assignment(assignment_id: int, user_id: str = Depends(get_current_user_id)):
    """Explicitly open an assignment (assigned -> in_progress). Idempotent.

    The first label write does this too; the app calls it when the rater
    opens the rating view so the queue reflects it immediately.
    """
    assignment = _require_my_assignment(assignment_id, user_id)
    if assignment.status == 'done':
        raise _forbidden(f"Assignment {assignment_id} is already done")
    if assignment.status == 'assigned':
        assignment = get_db().set_assignment_status(assignment_id, 'in_progress')
    return assignment_to_response(assignment)


@app.post("/api/assignments/{assignment_id}/complete", response_model=AssignmentResponse)
async def complete_assignment(assignment_id: int, user_id: str = Depends(get_current_user_id)):
    """Mark the caller's assignment done.

    Validates that every canonical move on the video has a strategy, an
    environment and an outcome written by this rater. Frame tags (sensation)
    and effort are not required: raters label what is observable. On failure:
    422 with {"detail": ..., "missing": [{move_id, move_index, missing: [...]}]}.
    """
    db = get_db()
    assignment = _require_my_assignment(assignment_id, user_id)
    if assignment.status == 'done':
        return assignment_to_response(assignment)

    moves = db.get_moves_for_video_any(assignment.video_id)
    if not moves:
        return JSONResponse(
            status_code=422,
            content={'detail': 'Video has no canonical moves to rate', 'missing': []},
        )

    missing = []
    for move_index, move in enumerate(moves):
        lenses = []
        if not db.get_strategy_for_move(move.id, user_id):
            lenses.append('strategy')
        if not db.get_environment_for_move(move.id, user_id):
            lenses.append('environment')
        if not db.get_outcome_for_move(move.id, user_id):
            lenses.append('outcome')
        if lenses:
            missing.append({'move_id': move.id, 'move_index': move_index, 'missing': lenses})

    if missing:
        return JSONResponse(
            status_code=422,
            content={
                'detail': f'{len(missing)} of {len(moves)} moves are incomplete',
                'missing': missing,
            },
        )

    done = db.set_assignment_status(assignment_id, 'done', completed_at=datetime.now(timezone.utc))
    return assignment_to_response(done)


# ==================== ADMIN ====================
#
# Every route here depends on require_admin and returns 403 for anyone else.

@app.get("/api/admin/videos", response_model=List[AdminVideoListItem])
async def admin_list_videos(_admin: str = Depends(require_admin)):
    """Every video across all users with assignment progress, newest first."""
    return [
        AdminVideoListItem(
            video=video_to_response(item['video'], 'admin'),
            assignment_count=item['assignment_count'],
            done_count=item['done_count'],
        )
        for item in get_db().list_videos_admin()
    ]


def _require_any_video(video_id: int) -> Video:
    video = get_db().get_video_any(video_id)
    if not video:
        raise _not_found(f"Video {video_id} not found")
    return video


def _parse_event_date(value: str) -> Optional[date]:
    if value == '':
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise _bad_request(f"Invalid event_date: {value!r}. Use YYYY-MM-DD.")


@app.put("/api/admin/videos/{video_id}/metadata", response_model=VideoResponse)
async def admin_update_video_metadata(
    video_id: int,
    payload: VideoMetadataUpdate,
    _admin: str = Depends(require_admin),
):
    """Set prep metadata and public-source fields on any video.

    source_type may be any paper type; 'community' is set only by the
    self-upload flow. athlete_id must name an existing athlete.
    """
    video = _require_any_video(video_id)
    fields = payload.model_dump()

    # Provenance was checked at mark-ready (18+, source). Once a video is
    # ready or closed it cannot change under the raters: reopen first, which
    # puts it back through the gate.
    locked = [k for k in PROVENANCE_FIELDS if fields.get(k) is not None]
    if video.is_locked() and locked:
        raise _conflict(
            f"Video {video_id} is {video.prep_status}: reopen it before changing "
            f"{', '.join(locked)}"
        )

    if fields['source_type'] is not None:
        if fields['source_type'] not in PAPER_SOURCE_TYPES:
            raise _bad_request(
                f"Invalid source_type: {fields['source_type']}. Must be one of: {PAPER_SOURCE_TYPES}"
            )
    if fields['event_date'] is not None:
        fields['event_date'] = _parse_event_date(fields['event_date'])
        if fields['event_date'] is None:
            fields['event_date'] = ''  # clear
    if fields['athlete_id'] is not None and fields['athlete_id'] != '':
        if not get_db().get_athlete(fields['athlete_id']):
            raise _bad_request(f"Unknown athlete_id: {fields['athlete_id']}")

    start = fields['clip_start_ms'] if fields['clip_start_ms'] is not None else video.clip_start_ms
    end = fields['clip_end_ms'] if fields['clip_end_ms'] is not None else video.clip_end_ms
    if start is not None and end is not None and end <= start:
        raise _bad_request('clip_end_ms must be greater than clip_start_ms')

    updated = get_db().update_video_fields(video_id, **fields)
    return video_to_response(updated, 'admin')


PROVENANCE_FIELDS = ('source_type', 'source_url', 'clip_start_ms', 'clip_end_ms',
                     'license', 'event_name', 'event_date', 'athlete_id')


def _ready_blockers(video: Video) -> List[str]:
    """Why a paper clip cannot be marked ready yet ([] when it can).

    Provenance must be complete and the athlete must be an adult on the event
    date. Without full birth dates, (event year - birth year) >= 19 is the
    conservative test that guarantees 18+. The pose must be extracted and the
    clip must pass the camera check (no cut, motion and zoom under
    CAMERA_MOTION_MAX / CAMERA_ZOOM_MAX) unless an admin has overridden it.
    """
    if video.is_community():
        return []
    problems = []
    if video.pose_status != 'done':
        problems.append(f'pose extraction not finished (status={video.pose_status or "pending"})')
    elif not video.camera_override:
        problems.extend(camera_problems(video))
    if not video.source_type:
        problems.append('source_type is missing')
    if video.source_type == 'research_dataset':
        if not (video.source_url or video.license):
            problems.append('source_url or license is required for research_dataset clips')
    elif not video.source_url:
        problems.append('source_url is missing')
    if not video.event_date:
        problems.append('event_date is missing')
    if not video.athlete_id:
        problems.append('athlete is not set')
    else:
        athlete = get_db().get_athlete(video.athlete_id)
        if not athlete:
            problems.append('athlete record not found')
        elif athlete.birth_year is None:
            problems.append("athlete's birth_year is missing (needed for the 18+ check)")
        elif video.event_date and video.event_date.year - athlete.birth_year < MIN_AGE_YEAR_GAP:
            problems.append(
                f'athlete may be under 18 on {video.event_date.isoformat()} '
                f'(born {athlete.birth_year}); only clips of adults can be rated'
            )
    return problems


@app.post("/api/admin/videos/{video_id}/ready", response_model=VideoResponse)
async def admin_mark_ready(video_id: int, _admin: str = Depends(require_admin)):
    """Mark a video ready to rate: prep_status -> 'ready'.

    Holds and canonical moves lock from here (admins excepted). 422 with a
    list of reasons when provenance or the 18+ check fails.

    The first time a video is marked ready its overlap flag is drawn at
    random (probability IRR_OVERLAP_RATE, default 0.25), so the reliability
    subset is not hand-picked. Re-marking a reopened video keeps the earlier
    draw, as does an admin override made before the draw.
    """
    video = _require_any_video(video_id)
    problems = _ready_blockers(video)
    if problems:
        return JSONResponse(
            status_code=422,
            content={'detail': 'Video cannot be marked ready: ' + '; '.join(problems),
                     'problems': problems},
        )

    fields = {'prep_status': 'ready'}
    if video.irr_overlap_set_by is None:
        fields['irr_overlap'] = _overlap_rng.random() < irr_overlap_rate()
        fields['irr_overlap_set_by'] = 'random'
    updated = get_db().update_video_fields(video_id, **fields)
    return video_to_response(updated, 'admin')


@app.put("/api/admin/videos/{video_id}/overlap", response_model=VideoResponse)
async def admin_set_overlap(
    video_id: int,
    payload: OverlapUpdate,
    _admin: str = Depends(require_admin),
):
    """Override the overlap flag. Only while the video has no assignments:
    once raters are on it, its rater target is fixed. 409 otherwise."""
    _require_any_video(video_id)
    updated = get_db().set_overlap_if_unassigned(video_id, payload.irr_overlap)
    if updated is None:
        raise _conflict('Overlap can only be changed before any rater is assigned')
    return video_to_response(updated, 'admin')


@app.put("/api/admin/videos/{video_id}/camera-override", response_model=VideoResponse)
async def admin_set_camera_override(
    video_id: int,
    payload: CameraOverride,
    _admin: str = Depends(require_admin),
):
    """Accept (or stop accepting) a clip that fails the camera check.

    Turning it on needs a non-empty note saying why (e.g. "pan is before the
    first labeled move"); the note and the flag go into the exports.
    """
    _require_any_video(video_id)
    note = (payload.note or '').strip()
    if payload.override and not note:
        raise _bad_request('A note is required to override the camera check')
    updated = get_db().update_video_fields(
        video_id, camera_override=payload.override,
        camera_override_note=note if payload.override else '',
    )
    return video_to_response(updated, 'admin')


@app.post("/api/admin/videos/{video_id}/close", response_model=VideoResponse)
async def admin_mark_closed(video_id: int, _admin: str = Depends(require_admin)):
    """Close a video: rating finished, no further rater writes."""
    _require_any_video(video_id)
    video = get_db().update_video_fields(video_id, prep_status='closed')
    return video_to_response(video, 'admin')


@app.post("/api/admin/videos/{video_id}/reopen", response_model=VideoResponse)
async def admin_reopen(video_id: int, _admin: str = Depends(require_admin)):
    """Put a video back to draft so its holds and moves can be edited again."""
    _require_any_video(video_id)
    video = get_db().update_video_fields(video_id, prep_status='draft')
    return video_to_response(video, 'admin')


@app.get("/api/admin/assignments", response_model=List[AssignmentResponse])
async def admin_list_assignments(
    video_id: Optional[int] = None,
    _admin: str = Depends(require_admin),
):
    """Assignments, optionally filtered to one video."""
    return [assignment_to_response(a) for a in get_db().list_assignments(video_id)]


@app.post("/api/admin/assignments", response_model=AssignmentResponse, status_code=status.HTTP_201_CREATED)
async def admin_create_assignment(
    payload: AssignmentCreate,
    _admin: str = Depends(require_admin),
):
    """Assign a validated rater to a ready video.

    404 for a missing video or rater profile; 409 when the video is not
    ready, the rater is not validated, the rater is already assigned, or the
    video already has its target number of raters (1, or 3 for the overlap
    subset).
    """
    db = get_db()
    video = _require_any_video(payload.video_id)
    profile = db.get_rater_profile(payload.rater_user_id)
    if not profile:
        raise _not_found(f"Rater profile {payload.rater_user_id} not found")
    if video.prep_status != 'ready':
        raise _conflict(f"Video {video.id} is {video.prep_status}; mark it ready before assigning raters")
    if not profile.is_validated:
        raise _conflict('Only validated raters can be assigned')
    if db.get_assignment_for(payload.video_id, payload.rater_user_id):
        raise _conflict('Rater is already assigned to this video')
    target = video.rater_target()
    try:
        created = db.create_assignment_capped(VideoAssignment(
            video_id=payload.video_id,
            rater_user_id=payload.rater_user_id,
            status='assigned',
            assigned_at=datetime.now(timezone.utc),
        ), target)
    except psycopg.errors.UniqueViolation:
        raise _conflict('Rater is already assigned to this video')
    if created is None:
        raise _conflict(
            f"Video {video.id} already has its {target} rater{'s' if target != 1 else ''}"
            f"{' (overlap subset)' if video.irr_overlap else ''}"
        )
    return assignment_to_response(created)


@app.delete("/api/admin/assignments/{assignment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def admin_delete_assignment(assignment_id: int, _admin: str = Depends(require_admin)):
    """Remove an assignment. The rater's label rows are kept."""
    if not get_db().delete_assignment(assignment_id):
        raise _not_found(f"Assignment {assignment_id} not found")
    return None


@app.get("/api/admin/raters", response_model=List[ProfileResponse])
async def admin_list_raters(_admin: str = Depends(require_admin)):
    """Every rater profile."""
    return [profile_to_response(p) for p in get_db().list_rater_profiles()]


@app.put("/api/admin/raters/{rater_user_id}", response_model=ProfileResponse)
async def admin_update_rater(
    rater_user_id: str,
    payload: RaterUpdate,
    _admin: str = Depends(require_admin),
):
    """Set is_validated, validation_note, is_admin or display_name on a profile."""
    db = get_db()
    if not db.get_rater_profile(rater_user_id):
        raise _not_found(f"Rater profile {rater_user_id} not found")
    updated = db.update_rater_profile(rater_user_id, **payload.model_dump())
    return profile_to_response(updated)


# ---------- athletes ----------

def _validate_athlete_fields(category=None, height_source=None):
    if category not in (None, '') and category not in ATHLETE_CATEGORIES:
        raise _bad_request(f"Invalid category: {category}. Must be one of: {ATHLETE_CATEGORIES}")
    if height_source is not None and height_source not in HEIGHT_SOURCES:
        raise _bad_request(f"Invalid height_source: {height_source}. Must be one of: {HEIGHT_SOURCES}")


@app.get("/api/admin/athletes", response_model=List[AthleteResponse])
async def admin_list_athletes(_admin: str = Depends(require_admin)):
    """Every athlete, oldest first."""
    return [athlete_to_response(a) for a in get_db().list_athletes()]


@app.post("/api/admin/athletes", response_model=AthleteResponse, status_code=status.HTTP_201_CREATED)
async def admin_create_athlete(payload: AthleteCreate, _admin: str = Depends(require_admin)):
    """Add a pseudonymous athlete. 409 if the IFSC profile URL is already in."""
    _validate_athlete_fields(payload.category, payload.height_source)
    height_source = payload.height_source or ('ifsc_profile' if payload.height_cm else 'missing')
    if height_source == 'ifsc_profile' and payload.height_cm is None:
        raise _bad_request("height_source 'ifsc_profile' needs height_cm")
    try:
        created = get_db().create_athlete(Athlete(
            ifsc_profile_url=(payload.ifsc_profile_url or '').strip() or None,
            height_cm=payload.height_cm,
            height_source=height_source,
            birth_year=payload.birth_year,
            category=payload.category or None,
        ))
    except psycopg.errors.UniqueViolation:
        raise _conflict('An athlete with that IFSC profile URL already exists')
    return athlete_to_response(created)


@app.put("/api/admin/athletes/{athlete_id}", response_model=AthleteResponse)
async def admin_update_athlete(
    athlete_id: str,
    payload: AthleteUpdate,
    _admin: str = Depends(require_admin),
):
    """Edit an athlete. Setting height_cm without height_source marks it
    'ifsc_profile'."""
    db = get_db()
    if not db.get_athlete(athlete_id):
        raise _not_found(f"Athlete {athlete_id} not found")
    _validate_athlete_fields(payload.category, payload.height_source)
    fields = payload.model_dump()
    # The 18+ gate ran at mark-ready against the old birth_year. A change that
    # would put any ready / closed clip of this athlete under it is refused.
    if fields['birth_year'] is not None:
        for event_date in db.athlete_video_dates(athlete_id):
            if event_date and event_date.year - fields['birth_year'] < MIN_AGE_YEAR_GAP:
                raise _conflict(
                    f"birth_year {fields['birth_year']} would make a ready clip of this athlete "
                    f"(event {event_date.isoformat()}) fail the 18+ check; reopen it first"
                )
    if fields['height_cm'] is not None and fields['height_source'] is None:
        fields['height_source'] = 'ifsc_profile'
    if fields['ifsc_profile_url'] is not None:
        fields['ifsc_profile_url'] = fields['ifsc_profile_url'].strip()
    try:
        updated = db.update_athlete(athlete_id, **fields)
    except psycopg.errors.UniqueViolation:
        raise _conflict('An athlete with that IFSC profile URL already exists')
    return athlete_to_response(updated)


def _csv_response(text: str, filename: str) -> Response:
    return Response(
        content=text,
        media_type='text/csv',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'},
    )


@app.get("/api/admin/export/long")
async def admin_export_long(
    video_id: Optional[int] = None,
    include_community: bool = False,
    overlap_only: bool = False,
    include_drafts: bool = False,
    _admin: str = Depends(require_admin),
):
    """Long-format CSV, the IRR input: one row per (video, move, rater, lens,
    field), sorted by video, move, rater, lens, field.

    Columns: see exporter.LONG_COLUMNS (video provenance, irr_overlap,
    athlete_id + height, then move/rater/lens/field/value). Lenses: strategy,
    environment, outcome, frame_tags. Multi-selects are pipe-delimited.
    Only videos that passed mark-ready (ready / closed) unless
    ?include_drafts=true; community videos excluded unless
    ?include_community=true; ?overlap_only=true keeps only the reliability
    subset; ?video_id= returns one video whatever its source or status. On
    paper footage only assigned raters' labels count. Never includes IFSC
    profile URLs.
    """
    text = get_admin_exporter().long_csv(
        video_id=video_id, include_community=include_community, overlap_only=overlap_only,
        include_drafts=include_drafts,
    )
    suffix = f'_video{video_id}' if video_id is not None else ''
    return _csv_response(text, f'dynalytix_long{suffix}.csv')


@app.get("/api/admin/export/full")
async def admin_export_full(
    video_id: Optional[int] = None,
    include_community: bool = False,
    include_drafts: bool = False,
    _admin: str = Depends(require_admin),
):
    """Full CSV: the per-video export's shape (one row per pose frame with the
    label columns appended) for every video and every rater across all users,
    with identity and provenance columns in front. Community videos are
    excluded unless ?include_community=true. Large: frames repeat per rater."""
    if video_id is not None:
        # One video: refuse loudly while its pose CSV does not exist yet. The
        # multi-video export instead keeps such videos as label-only rows
        # (AdminExporter._pose_rows returns [] until pose_status is done) so
        # one pending upload never blocks the whole dataset.
        video = get_db().get_video_any(video_id)
        if not video:
            raise _not_found(f"Video {video_id} not found")
        _require_pose_done(video)
    text = get_admin_exporter().full_csv(video_id=video_id, include_community=include_community,
                                         include_drafts=include_drafts)
    suffix = f'_video{video_id}' if video_id is not None else ''
    return _csv_response(text, f'dynalytix_full{suffix}.csv')


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
