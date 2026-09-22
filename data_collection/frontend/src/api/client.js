/**
 * API client for communicating with the backend.
 *
 * All API calls go through this module for easy maintenance.
 * Updated for three-lens schema: Environment / Strategy / Outcome
 */
import axios from 'axios';
import { authHeader, requireAccessToken, refreshSession } from './auth';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Every /api route except /api/health requires a Supabase bearer token.
api.interceptors.request.use(async (config) => {
  if (config.url && config.url.includes('/api/health')) return config;
  Object.assign(config.headers, await authHeader());
  return config;
});

/**
 * Refresh once on 401, then replay the request.
 *
 * A labeling session runs long enough for an access token to expire mid-way
 * (the status poll alone runs for minutes). Rather than dumping the labeler
 * back at the sign-in screen, force a refresh and retry exactly once. `_retriedAfterRefresh` guards against a loop
 * when the refresh token is dead too — in that case the 401 propagates and the
 * auth state listener in App will show the sign-in screen.
 */
api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const original = error.config;
    const isAuthFailure = error.response?.status === 401;

    if (!isAuthFailure || !original || original._retriedAfterRefresh) {
      return Promise.reject(error);
    }

    original._retriedAfterRefresh = true;
    const token = await refreshSession();
    if (!token) return Promise.reject(error);

    original.headers = { ...original.headers, Authorization: `Bearer ${token}` };
    return api(original);
  }
);

// ==================== CONFIGURATION ====================

export const getConfig = async () => {
  const response = await api.get('/api/config');
  return response.data;
};

// ==================== VIDEOS ====================

/**
 * Register a video before uploading it.
 *
 * The payload is the browser's provisional metadata (utils/videoMeta): the
 * worker overwrites fps/total_frames/duration_ms/width/height when it has run
 * ffprobe. No CSV is sent any more.
 *
 * Retried with exponential backoff. Only transport failures and 5xx are
 * retried — a 401 will not become true on a second attempt.
 *
 * @param {{filename: string, fps: number, total_frames: number, duration_ms: number, width?: number|null, height?: number|null}} payload
 * @param {{attempts?: number, baseDelayMs?: number, onRetry?: (attempt: number, delayMs: number, err: Error) => void, signal?: AbortSignal}} [options]
 */
export const registerVideo = async (payload, options = {}) => {
  const { attempts = 3, baseDelayMs = 1000, onRetry, signal } = options;

  // Surface a missing session before spending a retry budget on a guaranteed 401.
  await requireAccessToken();

  let lastError;
  for (let attempt = 1; attempt <= attempts; attempt++) {
    try {
      const response = await api.post('/api/videos/register', payload, { signal });
      return response.data;
    } catch (err) {
      lastError = err;

      const status = err.response?.status;
      const retriable = status === undefined || status >= 500;
      if (!retriable || attempt === attempts || signal?.aborted) break;

      // 1s, 2s, 4s with jitter, so parallel clients don't retry in lockstep.
      const delay = baseDelayMs * 2 ** (attempt - 1) * (0.5 + Math.random());
      if (onRetry) onRetry(attempt, delay, err);
      await new Promise((resolve) => setTimeout(resolve, delay));
    }
  }

  const detail = lastError?.response?.data?.detail;
  throw new Error(detail || lastError?.message || 'Failed to register video');
};

/** Presigned PUT URL for uploading the original video straight to R2. */
export const getUploadUrl = async (videoId, contentType = 'video/mp4') => {
  const response = await api.post(`/api/videos/${videoId}/upload-url`, {
    content_type: contentType,
  });
  return response.data;
};

/**
 * Upload the original video to R2.
 *
 * The Content-Type must match the one the presigned URL was signed with, or R2
 * rejects the signature. Sent without credentials — the signature is the auth.
 */
export const putVideoToR2 = async (url, file, contentType = 'video/mp4') => {
  const response = await fetch(url, {
    method: 'PUT',
    body: file,
    headers: { 'Content-Type': contentType },
  });
  if (!response.ok) {
    throw new Error(`Video upload failed (${response.status})`);
  }
  return response;
};

/**
 * Upload the original video to R2 with progress.
 *
 * XMLHttpRequest rather than fetch because fetch has no upload progress
 * events, and a multi-hundred-megabyte phone clip needs a visible bar.
 * Same rules as putVideoToR2: Content-Type must match the presign, no auth.
 *
 * @param {string} url presigned PUT URL
 * @param {File} file
 * @param {string} contentType
 * @param {{onProgress?: (fraction: number) => void, signal?: AbortSignal}} [options]
 */
export const putVideoToR2WithProgress = (url, file, contentType = 'video/mp4', options = {}) =>
  new Promise((resolve, reject) => {
    const { onProgress, signal } = options;
    const xhr = new XMLHttpRequest();
    xhr.open('PUT', url, true);
    xhr.setRequestHeader('Content-Type', contentType);
    xhr.upload.onprogress = (event) => {
      if (onProgress && event.lengthComputable && event.total > 0) {
        onProgress(event.loaded / event.total);
      }
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        if (onProgress) onProgress(1);
        resolve(xhr);
      } else {
        reject(new Error(`Video upload failed (${xhr.status})`));
      }
    };
    xhr.onerror = () => reject(new Error('Video upload failed (network error)'));
    xhr.onabort = () => reject(new DOMException('Upload cancelled', 'AbortError'));
    if (signal) {
      if (signal.aborted) {
        xhr.abort();
        return;
      }
      signal.addEventListener('abort', () => xhr.abort(), { once: true });
    }
    xhr.send(file);
  });

/**
 * Record the R2 key once the direct upload has finished.
 *
 * The backend enqueues the pose worker here and answers with the video row,
 * including `pose_status` — 'pending' when the job was accepted, 'failed'
 * with `pose_error` when the worker could not be reached (retry later).
 */
export const confirmUpload = async (videoId, key) => {
  const response = await api.post(`/api/videos/${videoId}/confirm-upload`, { key });
  return response.data;
};

/**
 * Full original-video upload: presign → PUT to R2 (with progress) → confirm.
 *
 * @param {number} videoId
 * @param {File} file
 * @param {{onProgress?: (fraction: number) => void, signal?: AbortSignal}} [options]
 * @returns {Promise<object>} the confirmed video row (carries pose_status)
 */
export const uploadOriginalVideo = async (videoId, file, options = {}) => {
  const contentType = file.type || 'video/mp4';
  const { url, key } = await getUploadUrl(videoId, contentType);
  await putVideoToR2WithProgress(url, file, contentType, options);
  return confirmUpload(videoId, key);
};

// ==================== POSE JOB ====================

/**
 * The pose job's state, polled by the header chip.
 *
 * @returns {Promise<{video_id: number, pose_status: 'pending'|'processing'|'done'|'failed', pose_error: string|null, pose_started_at: string|null, pose_finished_at: string|null, fps: number, total_frames: number, duration_ms: number, width: number|null, height: number|null, r2_pose_csv_key: string|null}>}
 */
export const getPoseStatus = async (videoId) => {
  const response = await api.get(`/api/videos/${videoId}/status`);
  return response.data;
};

/** Re-enqueue a failed job. 409 if it is processing or already done. */
export const retryPose = async (videoId) => {
  const response = await api.post(`/api/videos/${videoId}/retry-pose`);
  return response.data;
};

/** Presigned GET URL for the pose CSV (409 until pose_status is done). */
export const getPoseCsvUrl = async (videoId) => {
  const response = await api.get(`/api/videos/${videoId}/pose-csv-url`);
  return response.data.url;
};

/**
 * The pose CSV as text, once the worker has finished.
 *
 * The presigned R2 URL is fetched bare: it rejects an Authorization header,
 * and the signature is the auth.
 */
export const fetchPoseCsvText = async (videoId) => {
  const url = await getPoseCsvUrl(videoId);
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Could not load pose data (${response.status})`);
  }
  return response.text();
};

export const getVideos = async () => {
  const response = await api.get('/api/videos');
  return response.data;
};

export const getVideo = async (videoId) => {
  const response = await api.get(`/api/videos/${videoId}`);
  return response.data;
};

/**
 * Export labeled data for a video.
 *
 * v3 takes no query params — the video is no longer deleted as a side effect
 * of exporting. Answers 409 ("pose extraction not finished") until the
 * worker's CSV exists; the UI disables the button until then.
 *
 * @param {number} videoId - The video ID to export
 * @returns {Promise<{video_id: number, r2_export_key: string}>}
 */
export const exportVideo = async (videoId) => {
  const response = await api.post(`/api/videos/${videoId}/export`);
  return response.data;
};

/**
 * Presigned URL for the exported CSV.
 *
 * v3 answers `307` to a presigned R2 URL rather than streaming a body. Axios
 * follows redirects transparently in the browser, and the presigned URL rejects
 * the Authorization header we would otherwise attach, so this uses a bare fetch
 * with redirect: 'manual' to read the Location out instead of following it.
 *
 * Falls back to following the redirect and reading `response.url` on browsers
 * where an opaque redirect hides the Location header.
 *
 * @param {number} videoId
 * @returns {Promise<string>} a URL that downloads the CSV
 */
export const getExportDownloadUrl = async (videoId) => {
  const headers = await authHeader();
  const target = `${API_BASE_URL}/api/videos/${videoId}/export/download`;

  const manual = await fetch(target, { method: 'GET', headers, redirect: 'manual' });
  const location = manual.headers.get('Location');
  if (location) return location;

  // Opaque redirect: follow it and use where we landed.
  const followed = await fetch(target, { method: 'GET', headers });
  if (!followed.ok) {
    throw new Error(`Could not get the download link (${followed.status})`);
  }
  return followed.url;
};

/**
 * Download the exported CSV file by navigating to its presigned URL.
 * @param {number} videoId - The video ID
 */
export const downloadExport = async (videoId) => {
  const url = await getExportDownloadUrl(videoId);
  window.location.assign(url);
};

// ==================== HOLDS ====================

/**
 * Every hold marked on a video. `bbox_*` are normalized 0-1, so they must be
 * compared against landmarks only after normalizing those — see
 * services/holdMatching, which is the single source of that geometry.
 */
export const getHolds = async (videoId) => {
  const response = await api.get(`/api/videos/${videoId}/holds`);
  return response.data;
};

/**
 * Create many holds at once — what the detector posts after the first frame.
 * @param {number} videoId
 * @param {Array<{bbox_x:number,bbox_y:number,bbox_w:number,bbox_h:number,source?:string}>} holds
 */
export const createHoldsBulk = async (videoId, holds) => {
  const response = await api.post(`/api/videos/${videoId}/holds`, { holds });
  return response.data;
};

/** Create a single hold — what drag-to-add posts. */
export const createHold = async (videoId, hold) => {
  const response = await api.post('/api/holds', { video_id: videoId, ...hold });
  return response.data;
};

/** Move, resize, or re-source a hold. */
export const updateHold = async (holdId, fields) => {
  const response = await api.put(`/api/holds/${holdId}`, fields);
  return response.data;
};

/** Delete a hold. */
export const deleteHold = async (holdId) => {
  await api.delete(`/api/holds/${holdId}`);
};

// ==================== MOVES (Lens 2: Strategy) ====================

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

// ==================== ENVIRONMENTS (Lens 1) ====================

export const createEnvironment = async (envData) => {
  const response = await api.post('/api/environments', envData);
  return response.data;
};

export const getEnvironmentForMove = async (moveId) => {
  try {
    const response = await api.get(`/api/moves/${moveId}/environment`);
    return response.data;
  } catch (err) {
    if (err.response?.status === 404) {
      return null; // No environment yet
    }
    throw err;
  }
};

export const updateEnvironment = async (envId, envData) => {
  const response = await api.put(`/api/environments/${envId}`, envData);
  return response.data;
};

// ==================== OUTCOMES (Lens 3) ====================

export const createOutcome = async (outcomeData) => {
  const response = await api.post('/api/outcomes', outcomeData);
  return response.data;
};

export const getOutcomeForMove = async (moveId) => {
  try {
    const response = await api.get(`/api/moves/${moveId}/outcome`);
    return response.data;
  } catch (err) {
    if (err.response?.status === 404) {
      return null; // No outcome yet
    }
    throw err;
  }
};

export const updateOutcome = async (outcomeId, outcomeData) => {
  const response = await api.put(`/api/outcomes/${outcomeId}`, outcomeData);
  return response.data;
};

// ==================== FRAME TAGS (Sensation) ====================

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

// ==================== PLAYBACK ====================

/**
 * Presigned URL for the original video, for a video that was not uploaded in
 * this session — a rater's assignment, or an owner's reload. Resolves to null
 * (rather than throwing) when no original was ever uploaded, because the pose
 * CSV can exist without it and the labeling UI still works on the skeleton.
 */
export const getVideoPlaybackUrl = async (videoId) => {
  try {
    const response = await api.get(`/api/videos/${videoId}/video-url`);
    return response.data?.url ?? null;
  } catch (err) {
    if (err.response?.status === 404) return null;
    throw err;
  }
};

// ==================== RATER PROFILE (Dataset A) ====================

/** The caller's rater profile, or null on 404 — which is what opens the gate. */
export const getMyProfile = async () => {
  try {
    const response = await api.get('/api/me/profile');
    return response.data;
  } catch (err) {
    if (err.response?.status === 404) return null;
    throw err;
  }
};

export const createMyProfile = async (profile) => {
  const response = await api.post('/api/me/profile', profile);
  return response.data;
};

export const updateMyProfile = async (fields) => {
  const response = await api.put('/api/me/profile', fields);
  return response.data;
};

// ==================== RATER QUEUE (Dataset A) ====================

/** `[{ assignment, video, move_count }]`, oldest first. */
export const getMyAssignments = async () => {
  const response = await api.get('/api/me/assignments');
  return response.data;
};

export const startAssignment = async (assignmentId) => {
  const response = await api.post(`/api/assignments/${assignmentId}/start`);
  return response.data;
};

/**
 * Mark an assignment done. Resolves to the assignment on 200. On 422 the
 * server lists what is missing; that is a normal outcome here, not an
 * exception, so it comes back as `{ incomplete: true, detail, missing }`.
 */
export const completeAssignment = async (assignmentId) => {
  try {
    const response = await api.post(`/api/assignments/${assignmentId}/complete`);
    return { incomplete: false, assignment: response.data };
  } catch (err) {
    if (err.response?.status === 422 && Array.isArray(err.response.data?.missing)) {
      return {
        incomplete: true,
        detail: err.response.data.detail,
        missing: err.response.data.missing,
      };
    }
    throw err;
  }
};

export const deleteEnvironment = async (envId) => {
  await api.delete(`/api/environments/${envId}`);
};

export const deleteOutcome = async (outcomeId) => {
  await api.delete(`/api/outcomes/${outcomeId}`);
};

// ==================== ADMIN (Dataset A) ====================

/** `[{ video, assignment_count, done_count }]`, newest first. Admin only. */
export const adminListVideos = async () => {
  const response = await api.get('/api/admin/videos');
  return response.data;
};

export const adminUpdateVideoMetadata = async (videoId, fields) => {
  const response = await api.put(`/api/admin/videos/${videoId}/metadata`, fields);
  return response.data;
};

export const adminMarkReady = async (videoId) => {
  const response = await api.post(`/api/admin/videos/${videoId}/ready`);
  return response.data;
};

export const adminCloseVideo = async (videoId) => {
  const response = await api.post(`/api/admin/videos/${videoId}/close`);
  return response.data;
};

export const adminReopenVideo = async (videoId) => {
  const response = await api.post(`/api/admin/videos/${videoId}/reopen`);
  return response.data;
};

export const adminListAssignments = async (videoId) => {
  const response = await api.get('/api/admin/assignments', {
    params: videoId != null ? { video_id: videoId } : {},
  });
  return response.data;
};

export const adminCreateAssignment = async ({ video_id, rater_user_id, cohort }) => {
  const response = await api.post('/api/admin/assignments', { video_id, rater_user_id, cohort });
  return response.data;
};

export const adminDeleteAssignment = async (assignmentId) => {
  await api.delete(`/api/admin/assignments/${assignmentId}`);
};

export const adminListRaters = async () => {
  const response = await api.get('/api/admin/raters');
  return response.data;
};

export const adminUpdateRater = async (userId, fields) => {
  const response = await api.put(`/api/admin/raters/${userId}`, fields);
  return response.data;
};

/**
 * Download an admin export as a file.
 *
 * The export endpoints are plain authenticated GETs — not presigned, so a
 * bare link would 401. Fetch with the bearer token, read the body as a blob,
 * and hand it to the browser through a temporary object URL. The filename
 * comes from Content-Disposition when the server sends one.
 *
 * `saveBlob` is injectable so a test can capture the blob instead of touching
 * the DOM's download machinery.
 *
 * @param {'long'|'full'} kind
 * @param {{dataset?: 'A'|'B'|'all', video_id?: number}} [params]
 */
export const downloadAdminExport = async (kind, params = {}, saveBlob = saveBlobAsFile) => {
  const headers = await authHeader();
  const query = new URLSearchParams();
  if (params.dataset) query.set('dataset', params.dataset);
  if (params.video_id != null) query.set('video_id', String(params.video_id));
  const suffix = query.toString() ? `?${query}` : '';

  const response = await fetch(`${API_BASE_URL}/api/admin/export/${kind}${suffix}`, { headers });
  if (!response.ok) {
    let detail = '';
    try {
      detail = (await response.json())?.detail || '';
    } catch {
      // Not JSON; the status is the message.
    }
    throw new Error(detail || `Export failed (${response.status})`);
  }

  const disposition = response.headers.get('Content-Disposition') || '';
  const match = disposition.match(/filename="?([^";]+)"?/);
  const filename = match ? match[1] : `dynalytix_${kind}.csv`;
  const blob = await response.blob();
  saveBlob(blob, filename);
  return filename;
};

function saveBlobAsFile(blob, filename) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  // Give the click a tick to start before the URL goes away.
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export default api;
