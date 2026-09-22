/**
 * Global state management using Zustand.
 *
 * Updated for three-lens schema: Environment / Strategy / Outcome
 *
 * Keeps track of:
 * - Current video
 * - List of moves
 * - Current move being edited
 * - Frame tags for current move
 * - Video player state
 * - Previous environment values for prefilling
 */
import { create } from 'zustand';

/**
 * The four hold slots an environment can reference, in the order the form
 * shows them. Mirrors HOLD_SLOTS in the backend's models.py; /api/config
 * serves the same list as `hold_slots` and is the runtime source of truth.
 */
export const HOLD_SLOT_KEYS = ['start_left', 'start_right', 'end', 'foot'];

/** Environment prefill in its empty state. */
const EMPTY_PREVIOUS_ENVIRONMENT = {
  wall_angle: '',
  start_left: { hold_id: null, hold_type: '', hold_quality: [] },
  start_right: { hold_id: null, hold_type: '', hold_quality: [] },
  end: { hold_id: null, hold_type: '', hold_quality: [] },
  foot: { hold_id: null, hold_type: '', hold_quality: [] },
};

/**
 * Everything that belongs to one open video. Cleared whenever a different
 * video (or a different user) takes its place, so nothing a rater saw on one
 * assignment can leak into the next — the API never returns another rater's
 * labels, and this keeps the client from caching its own across videos.
 */
const VIDEO_SCOPED_RESET = {
  currentVideo: null,
  videoBlobUrl: null,
  videoPlaybackUrl: null,
  csvData: null,
  csvString: null,
  moves: [],
  currentMove: null,
  frameTags: [],
  holds: [],
  holdPickSlot: null,
  currentFrame: 0,
  isPlaying: false,
  moveStart: null,
  moveEnd: null,
  mode: 'define',
  showMoveForm: false,
  previousEnvironment: EMPTY_PREVIOUS_ENVIRONMENT,
  readOnlyStructure: false,
  currentAssignment: null,
};

const useStore = create((set, get) => ({
  // ==================== VIDEO STATE ====================
  currentVideo: null,
  videos: [],
  videoBlobUrl: null, // Local blob URL for client-side video
  // Presigned URL for a video not extracted in this session (rating view,
  // or an owner reopening an upload). videoBlobUrl wins when both exist.
  videoPlaybackUrl: null,
  csvData: null, // Parsed CSV data from client-side extraction
  csvString: null, // Raw CSV string to send to server

  setCurrentVideo: (video) => set({ currentVideo: video }),
  setVideos: (videos) => set({ videos }),
  setVideoBlobUrl: (url) => set({ videoBlobUrl: url }),
  setVideoPlaybackUrl: (url) => set({ videoPlaybackUrl: url }),
  setCsvData: (data) => set({ csvData: data }),
  setCsvString: (str) => set({ csvString: str }),

  /** Drop everything tied to the open video. See VIDEO_SCOPED_RESET. */
  resetVideoState: () => set({ ...VIDEO_SCOPED_RESET }),

  // ==================== DATASET A: PROFILE / NAV / ASSIGNMENTS ====================
  // The rater profile from /api/me/profile (null until loaded or created).
  // `profile.is_admin` gates the Admin view; `profile.tier` is informational.
  profile: null,
  setProfile: (profile) => set({ profile }),

  // Top-level view: 'videos' (Dataset B, the existing flow) | 'queue' | 'admin'
  // | 'rating'. Only 'rating' carries video-scoped state.
  view: 'videos',
  setView: (view) => set({ view }),

  // The rater's queue, as returned by /api/me/assignments.
  assignments: [],
  setAssignments: (assignments) => set({ assignments }),

  // The assignment open in the rating view, and the flag that turns the
  // labeling UI read-only on structure (holds + canonical moves).
  currentAssignment: null,
  setCurrentAssignment: (assignment) => set({ currentAssignment: assignment }),
  readOnlyStructure: false,
  setReadOnlyStructure: (flag) => set({ readOnlyStructure: Boolean(flag) }),

  // ==================== MOVES STATE ====================
  moves: [],
  currentMove: null,

  setMoves: (moves) => set({ moves }),
  setCurrentMove: (move) => set({ currentMove: move }),

  addMove: (move) =>
    set((state) => ({
      moves: [...state.moves, move],
    })),

  updateMoveInList: (moveId, updatedMove) =>
    set((state) => ({
      moves: state.moves.map((m) => (m.id === moveId ? updatedMove : m)),
    })),

  removeMoveFromList: (moveId) =>
    set((state) => ({
      moves: state.moves.filter((m) => m.id !== moveId),
    })),

  // ==================== FRAME TAGS STATE ====================
  frameTags: [],

  setFrameTags: (tags) => set({ frameTags: tags }),

  addFrameTag: (tag) =>
    set((state) => ({
      frameTags: [...state.frameTags, tag].sort(
        (a, b) => a.frame_number - b.frame_number
      ),
    })),

  removeFrameTag: (tagId) =>
    set((state) => ({
      frameTags: state.frameTags.filter((t) => t.id !== tagId),
    })),

  // ==================== VIDEO PLAYER STATE ====================
  currentFrame: 0,
  isPlaying: false,

  setCurrentFrame: (frame) => set({ currentFrame: frame }),
  setIsPlaying: (playing) => set({ isPlaying: playing }),

  // ==================== MOVE CREATION STATE ====================
  moveStart: null,
  moveEnd: null,

  setMoveStart: (frame) => set({ moveStart: frame }),
  setMoveEnd: (frame) => set({ moveEnd: frame }),
  clearMoveSelection: () => set({ moveStart: null, moveEnd: null }),

  // ==================== UI STATE ====================
  mode: 'define', // 'define' or 'tagging'
  showMoveForm: false,
  showTagPopup: false,
  tagPopupType: null,

  setMode: (mode) => set({ mode }),
  setShowMoveForm: (show) => set({ showMoveForm: show }),
  setShowTagPopup: (show, type = null) =>
    set({
      showTagPopup: show,
      tagPopupType: type,
    }),

  // ==================== CONFIG ====================
  config: null,

  setConfig: (config) => set({ config }),

  // ==================== PREVIOUS ENVIRONMENT (Lens 1 prefill) ====================
  // Last environment values, prefilled into the next move. Schema v3 shape:
  // wall angle plus four named hold slots. Only wall_angle and the hold types
  // and qualities carry over — hold_id never does, because the next move is on
  // different holds.
  previousEnvironment: EMPTY_PREVIOUS_ENVIRONMENT,

  setPreviousEnvironment: (env) =>
    set({
      previousEnvironment: {
        wall_angle: env.wall_angle || '',
        ...Object.fromEntries(
          HOLD_SLOT_KEYS.map((slot) => [
            slot,
            {
              // Deliberately dropped: the next move is on different holds, so
              // carrying an id over would point at the wrong box.
              hold_id: null,
              hold_type: env[slot]?.hold_type || '',
              hold_quality: env[slot]?.hold_quality || [],
            },
          ])
        ),
      },
    }),

  // ==================== HOLDS ====================
  // Bounding boxes normalized 0-1, per video. Landmarks are stored in pixels,
  // so anything comparing the two must normalize first (services/holdMatching,
  // which is the single source of that geometry).
  holds: [],
  showHoldOverlay: true,
  // When set, clicking a box on the video assigns it to this MoveForm slot.
  holdPickSlot: null,

  setHolds: (holds) => set({ holds }),
  addHold: (hold) => set((state) => ({ holds: [...state.holds, hold] })),
  addHolds: (holds) => set((state) => ({ holds: [...state.holds, ...holds] })),
  removeHold: (holdId) =>
    set((state) => ({ holds: state.holds.filter((h) => h.id !== holdId) })),
  setShowHoldOverlay: (show) => set({ showHoldOverlay: show }),
  setHoldPickSlot: (slot) => set({ holdPickSlot: slot }),

  // ==================== ONBOARDING BANNERS ====================
  // Session-only by design: no localStorage. A labeler who reloads is starting
  // over anyway, and the reminder costs one click to dismiss.
  dismissedBanners: {},

  dismissBanner: (key) =>
    set((state) => ({
      dismissedBanners: { ...state.dismissedBanners, [key]: true },
    })),

  isBannerDismissed: (key) => Boolean(get().dismissedBanners[key]),

  // ==================== AUTH ====================
  session: null,
  setSession: (session) => set({ session }),

  // Everything video-scoped, cleared on sign-out so the next user starts clean.
  resetForSignOut: () =>
    set({
      ...VIDEO_SCOPED_RESET,
      session: null,
      videos: [],
      dismissedBanners: {},
      profile: null,
      view: 'videos',
      assignments: [],
    }),
}));

export default useStore;
