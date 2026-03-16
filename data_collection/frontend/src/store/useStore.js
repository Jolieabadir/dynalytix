/**
 * Global state management using Zustand.
 * 
 * Keeps track of:
 * - Current video
 * - List of moves
 * - Current move being edited
 * - Frame tags for current move
 * - Video player state
 */
import { create } from 'zustand';

const useStore = create((set, get) => ({
  // ==================== VIDEO STATE ====================
  currentVideo: null,
  videos: [],
  videoBlobUrl: null,  // Local blob URL for client-side video
  csvData: null,       // Parsed CSV data from client-side extraction
  csvString: null,     // Raw CSV string to send to server

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
  
  addMove: (move) => set((state) => ({
    moves: [...state.moves, move]
  })),
  
  updateMoveInList: (moveId, updatedMove) => set((state) => ({
    moves: state.moves.map(m => m.id === moveId ? updatedMove : m)
  })),
  
  removeMoveFromList: (moveId) => set((state) => ({
    moves: state.moves.filter(m => m.id !== moveId)
  })),
  
  // ==================== FRAME TAGS STATE ====================
  frameTags: [],
  
  setFrameTags: (tags) => set({ frameTags: tags }),
  
  addFrameTag: (tag) => set((state) => ({
    frameTags: [...state.frameTags, tag].sort((a, b) => a.frame_number - b.frame_number)
  })),
  
  removeFrameTag: (tagId) => set((state) => ({
    frameTags: state.frameTags.filter(t => t.id !== tagId)
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
  setShowTagPopup: (show, type = null) => set({ 
    showTagPopup: show, 
    tagPopupType: type 
  }),
  
  // ==================== CONFIG ====================
  config: null,

  setConfig: (config) => set({ config }),

  // ==================== DUAL-ANGLE ASSESSMENT ====================
  // Phase: 'front' | 'side' | 'complete'
  assessmentPhase: 'front',
  frontVideoId: null,
  sideVideoId: null,
  frontVideoBlobUrl: null,
  sideVideoBlobUrl: null,

  setAssessmentPhase: (phase) => set({ assessmentPhase: phase }),
  setFrontVideoId: (id) => set({ frontVideoId: id }),
  setSideVideoId: (id) => set({ sideVideoId: id }),
  setFrontVideoBlobUrl: (url) => set({ frontVideoBlobUrl: url }),
  setSideVideoBlobUrl: (url) => set({ sideVideoBlobUrl: url }),

  // Reset dual-angle state for new assessment
  resetDualAngle: () => set({
    assessmentPhase: 'front',
    frontVideoId: null,
    sideVideoId: null,
    frontVideoBlobUrl: null,
    sideVideoBlobUrl: null,
  }),
}));

export default useStore;
