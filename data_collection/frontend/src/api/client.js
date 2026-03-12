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

// ==================== MOVES ====================

export const createMove = async (moveData) => {
  const response = await api.post('/api/moves', moveData);
  return response.data;
};

export const getMoves = async (videoId) => {
  const response = await api.get(`/api/videos/${videoId}/moves`);
  return response.data;
};

export const getMove = async (moveId) => {
  const response = await api.get(`/api/moves/${moveId}`);
  return response.data;
};

export const updateMove = async (moveId, moveData) => {
  const response = await api.put(`/api/moves/${moveId}`, moveData);
  return response.data;
};

export const deleteMove = async (moveId) => {
  await api.delete(`/api/moves/${moveId}`);
};

// ==================== FRAME TAGS ====================

export const createFrameTag = async (tagData) => {
  const response = await api.post('/api/frame-tags', tagData);
  return response.data;
};

export const getFrameTags = async (moveId) => {
  const response = await api.get(`/api/moves/${moveId}/frame-tags`);
  return response.data;
};

export const deleteFrameTag = async (tagId) => {
  await api.delete(`/api/frame-tags/${tagId}`);
};

export default api;
