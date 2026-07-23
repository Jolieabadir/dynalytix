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

const useStore = create((set, get) => ({
  // ==================== VIDEO STATE ====================
  currentVideo: null,
  videos: [],
  videoBlobUrl: null, // Local blob URL for client-side video
  csvData: null, // Parsed CSV data from client-side extraction
  csvString: null, // Raw CSV string to send to server

  setCurrentVideo: (video) => set({ currentVideo: video }),
  setVideos: (videos) => set({ videos }),
  setVideoBlobUrl: (url) => set({ videoBlobUrl: url }),
  setCsvData: (data) => set({ csvData: data }),
  setCsvString: (str) => set({ csvString: str }),

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
  // Stores the last environment values to prefill for new moves
  previousEnvironment: {
    wall_angle: '',
    hold_type_reaching: '',
    hold_type_non_reaching: '',
    hold_quality: [],
  },

  setPreviousEnvironment: (env) =>
    set({
      previousEnvironment: {
        wall_angle: env.wall_angle || '',
        hold_type_reaching: env.hold_type_reaching || '',
        hold_type_non_reaching: env.hold_type_non_reaching || '',
        hold_quality: env.hold_quality || [],
      },
    }),
}));

export default useStore;
