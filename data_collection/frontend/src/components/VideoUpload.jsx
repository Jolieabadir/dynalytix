/**
 * VideoUpload component.
 *
 * Zero-wait start. Picking a file:
 *
 *   1. makes an object URL and reads duration/size off a <video> element
 *      (tens of milliseconds);
 *   2. registers the video with that provisional metadata (fps assumed 30 —
 *      the browser cannot measure it; the worker corrects it);
 *   3. hands the labeler the player IMMEDIATELY (currentVideo is set);
 *   4. uploads the file to R2 in the background with a progress chip, then
 *      confirms, which enqueues the pose worker.
 *
 * Pose extraction happens on the server. The skeleton, hold suggestions and
 * export switch on by themselves when the worker reports done (see
 * hooks/usePoseStatus and components/PoseStatusChip).
 */
import { useState } from 'react';
import {
  getMoves,
  registerVideo,
  uploadOriginalVideo,
  createHoldsBulk,
  getHolds,
} from '../api/client';
import { detectHolds, HOLD_DETECTION_ENABLED } from '../services/holdDetector';
import { NotSignedInError } from '../api/auth';
import useStore from '../store/useStore';
import { readVideoMetadata, provisionalRegisterPayload } from '../utils/videoMeta';

const VALID_TYPES = ['video/quicktime', 'video/mp4', 'video/x-msvideo'];

/**
 * Grab the first frame of the clip and run the detector over it.
 *
 * Uses a detached <video> rather than the player, so this can run before the
 * player has mounted. Seeks to 0 and waits for a frame to actually be
 * available — `loadeddata` fires once there is one.
 */
async function detectFirstFrameHolds(blobUrl) {
  const video = document.createElement('video');
  video.src = blobUrl;
  video.muted = true;
  video.playsInline = true;

  await new Promise((resolve, reject) => {
    video.onloadeddata = resolve;
    video.onerror = () => reject(new Error('Could not read the first frame'));
  });

  video.currentTime = 0;
  await new Promise((resolve) => {
    if (video.readyState >= 2) resolve();
    else video.onseeked = resolve;
  });

  return detectHolds(video);
}

/**
 * The background half: upload → confirm (enqueues the worker) → holds.
 * Runs after the labeler already has the player. Never throws: every failure
 * is reported through the store so the chip can show it.
 */
async function runBackgroundJobs(videoId, file, blobUrl) {
  const store = useStore.getState();

  store.setUpload({ state: 'uploading', fraction: 0, error: null });
  try {
    const confirmed = await uploadOriginalVideo(videoId, file, {
      onProgress: (fraction) => {
        const current = useStore.getState().upload;
        if (current.state === 'uploading') {
          useStore.getState().setUpload({ fraction });
        }
      },
    });
    useStore.getState().setUpload({ state: 'done', fraction: 1, error: null });
    // confirm-upload answers with the row, including whether the worker took
    // the job; showing that now saves a poll.
    if (useStore.getState().currentVideo?.id === videoId) {
      useStore.getState().setPoseStatus({
        video_id: videoId,
        pose_status: confirmed.pose_status,
        pose_error: confirmed.pose_error ?? null,
        pose_started_at: confirmed.pose_started_at ?? null,
        pose_finished_at: confirmed.pose_finished_at ?? null,
        fps: confirmed.fps,
        total_frames: confirmed.total_frames,
        duration_ms: confirmed.duration_ms,
        width: confirmed.width,
        height: confirmed.height,
        r2_pose_csv_key: confirmed.r2_pose_csv_key ?? null,
      });
    }
  } catch (uploadErr) {
    console.error('[VideoUpload] Upload failed:', uploadErr);
    useStore.getState().setUpload({
      state: 'failed',
      error: uploadErr?.message || 'The upload failed. Pick the file again to retry.',
    });
    return;
  }

  // Holds: detect on the first frame and post them, if the detector is
  // enabled. Best-effort — a missing or failing detector must never cost the
  // labeler anything, and every hold can be placed by hand.
  try {
    let holds = [];
    if (HOLD_DETECTION_ENABLED) {
      const boxes = await detectFirstFrameHolds(blobUrl);
      if (boxes.length) {
        holds = await createHoldsBulk(videoId, boxes);
      }
    }
    if (useStore.getState().currentVideo?.id === videoId) {
      useStore.getState().setHolds(holds.length ? holds : await getHolds(videoId));
    }
  } catch (holdErr) {
    console.warn('[VideoUpload] Hold detection skipped:', holdErr);
  }
}

function VideoUpload() {
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState('');
  const [error, setError] = useState(null);

  const setCurrentVideo = useStore((s) => s.setCurrentVideo);
  const setHolds = useStore((s) => s.setHolds);
  const setMoves = useStore((s) => s.setMoves);
  const setVideoBlobUrl = useStore((s) => s.setVideoBlobUrl);
  const setCsvData = useStore((s) => s.setCsvData);
  const setUpload = useStore((s) => s.setUpload);
  const setPoseStatus = useStore((s) => s.setPoseStatus);

  const handleFileSelect = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    // Let the same file be chosen again after an error.
    e.target.value = '';

    if (!VALID_TYPES.includes(file.type) && !file.name.match(/\.(mov|mp4|avi)$/i)) {
      setError({ title: 'Unsupported file', message: 'Please upload a .mov, .mp4, or .avi file' });
      return;
    }

    setBusy(true);
    setError(null);
    setStatus('Reading video…');

    const blobUrl = URL.createObjectURL(file);
    try {
      const meta = await readVideoMetadata(blobUrl);

      setStatus('Registering…');
      const videoData = await registerVideo(provisionalRegisterPayload(file, meta), {
        onRetry: (attempt, delayMs) => {
          setStatus(`Network problem — retrying (${attempt}/3) in ${Math.round(delayMs / 1000)}s…`);
        },
      });

      // The labeler gets the player now. Everything below runs behind it.
      setVideoBlobUrl(blobUrl);
      setCsvData(null);
      setHolds([]);
      setMoves([]);
      setUpload({ state: 'idle', fraction: 0, error: null });
      setPoseStatus({ video_id: videoData.id, pose_status: videoData.pose_status || 'pending', pose_error: null });
      setCurrentVideo({
        ...videoData,
        // A backend that predates the dimensions column echoes null; keep the
        // measured size so hold matching can normalize once the CSV lands.
        width: videoData.width ?? (meta.width || null),
        height: videoData.height ?? (meta.height || null),
      });

      runBackgroundJobs(videoData.id, file, blobUrl);
      getMoves(videoData.id)
        .then((moves) => {
          if (useStore.getState().currentVideo?.id === videoData.id) setMoves(moves);
        })
        .catch((err) => console.warn('[VideoUpload] Could not load moves:', err));
    } catch (err) {
      console.error('Processing error:', err);
      URL.revokeObjectURL(blobUrl);
      if (err instanceof NotSignedInError || err?.name === 'NotSignedIn') {
        setError({ title: 'Not signed in', message: err.message });
      } else {
        setError({
          title: 'Could not start',
          message: err?.message || 'Something went wrong. Please try again.',
        });
      }
      setBusy(false);
      setStatus('');
    }
  };

  return (
    <div className="video-upload">
      <div className="upload-container">
        <h2>Upload Climbing Video</h2>
        <p>Pick a video to begin labeling climbing movements</p>

        {!busy ? (
          <div className="upload-area">
            <input
              type="file"
              id="video-upload"
              accept=".mov,.mp4,.avi,video/*"
              onChange={handleFileSelect}
              style={{ display: 'none' }}
            />
            <label htmlFor="video-upload" className="upload-button">
              Choose Video File
            </label>
            <p className="upload-hint">Supports .mov, .mp4, .avi</p>
            <p className="upload-hint" style={{ marginTop: '8px', fontSize: '12px', color: '#888' }}>
              You can start labeling right away. The video uploads in the background and the
              pose skeleton appears when the server has processed it.
            </p>
          </div>
        ) : (
          <div className="upload-progress">
            <div className="spinner"></div>
            <p>{status}</p>
          </div>
        )}

        {error && (
          <div className="error-message">
            <p>
              <strong>{error.title}</strong>
            </p>
            <p>{error.message}</p>
          </div>
        )}
      </div>
    </div>
  );
}

export default VideoUpload;
