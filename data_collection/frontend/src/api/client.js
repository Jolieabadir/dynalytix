/**
 * API client for communicating with the backend.
 *
 * All API calls go through this module for easy maintenance.
 */
import axios from 'axios';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

// ==================== CONFIGURATION ====================

export const getConfig = async () => {
  const response = await api.get('/api/config');
  return response.data;
};

// ==================== VIDEOS ====================

export const uploadVideo = async (file) => {
  const formData = new FormData();
  formData.append('file', file);

  const response = await api.post('/api/videos/upload', formData, {
    headers: {
      'Content-Type': 'multipart/form-data',
    },
  });
  return response.data;
};

export const getVideos = async () => {
  const response = await api.get('/api/videos');
  return response.data;
};

export const getVideo = async (videoId) => {
  const response = await api.get(`/api/videos/${videoId}`);
  return response.data;
};

export const getVideoCSV = async (videoId) => {
  const response = await api.get(`/api/videos/${videoId}/csv`);
  return response.data;
};

/**
 * Export labeled data for a video.
 * @param {number} videoId - The video ID to export
 * @param {boolean} deleteVideo - If true, delete the video file after export
 * @returns {Promise<{path: string, video_deleted: boolean}>}
 */
export const exportVideo = async (videoId, deleteVideo = true) => {
  const response = await api.post(`/api/videos/${videoId}/export?delete_video=${deleteVideo}`);
  return response.data;
};

/**
 * Download the exported CSV file.
 * @param {number} videoId - The video ID
 */
export const downloadExport = async (videoId) => {
  const response = await api.get(`/api/videos/${videoId}/export/download`, {
    responseType: 'blob',
  });

  // Create download link
  const url = window.URL.createObjectURL(new Blob([response.data]));
  const link = document.createElement('a');
  link.href = url;
  link.setAttribute('download', `video_${videoId}_labeled.csv`);
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.URL.revokeObjectURL(url);
};

// ==================== ASSESSMENTS ====================

export const createAssessment = async (assessmentData) => {
  const response = await api.post('/api/assessments', assessmentData);
  return response.data;
};

export const getAssessments = async (videoId) => {
  const response = await api.get(`/api/videos/${videoId}/assessments`);
  return response.data;
};

export const getAssessment = async (assessmentId) => {
  const response = await api.get(`/api/assessments/${assessmentId}`);
  return response.data;
};

export const updateAssessment = async (assessmentId, assessmentData) => {
  const response = await api.put(`/api/assessments/${assessmentId}`, assessmentData);
  return response.data;
};

export const deleteAssessment = async (assessmentId) => {
  await api.delete(`/api/assessments/${assessmentId}`);
};

// ==================== FRAME TAGS ====================

export const createFrameTag = async (tagData) => {
  const response = await api.post('/api/frame-tags', tagData);
  return response.data;
};

export const getFrameTags = async (assessmentId) => {
  const response = await api.get(`/api/assessments/${assessmentId}/frame-tags`);
  return response.data;
};

export const deleteFrameTag = async (tagId) => {
  await api.delete(`/api/frame-tags/${tagId}`);
};

// ==================== FMS REPORTS ====================

export const getFMSPatientReport = async (videoId) => {
  const response = await api.get(`/api/fms/report/${videoId}`);
  return response.data;
};

export const getFMSProviderReport = async (videoId) => {
  const response = await api.get(`/api/fms/findings/${videoId}`);
  return response.data;
};

/**
 * Score dual-angle assessment (front + side views).
 * @param {number|null} frontVideoId - Front view video ID
 * @param {number|null} sideVideoId - Side view video ID
 * @returns {Promise<object>} Dual-angle scoring results
 */
export const scoreDualAngle = async (frontVideoId, sideVideoId) => {
  const params = new URLSearchParams();
  if (frontVideoId) params.append('front_video_id', frontVideoId);
  if (sideVideoId) params.append('side_video_id', sideVideoId);
  const response = await api.post(`/api/fms/score-dual?${params.toString()}`);
  return response.data;
};

export default api;
