/**
 * What the browser can learn about a picked video without decoding it.
 *
 * The <video> element reports duration and intrinsic size as soon as metadata
 * loads — enough to start labeling. It does NOT report the frame rate, so
 * register sends PROVISIONAL_FPS and the pose worker overwrites fps (and the
 * frame count it implies) from ffprobe when it finishes. See usePoseStatus for
 * how the store picks that up.
 */
import { totalFrames } from './frames';

/** The frame rate assumed until the worker measures the real one. */
export const PROVISIONAL_FPS = 30;

/**
 * @param {string} objectUrl a URL.createObjectURL(file) for the picked file
 * @returns {Promise<{durationSeconds: number, width: number, height: number}>}
 */
export function readVideoMetadata(objectUrl) {
  return new Promise((resolve, reject) => {
    const video = document.createElement('video');
    video.preload = 'metadata';
    video.muted = true;
    video.playsInline = true;
    video.onloadedmetadata = () => {
      const durationSeconds = Number.isFinite(video.duration) ? video.duration : 0;
      resolve({
        durationSeconds,
        width: video.videoWidth || 0,
        height: video.videoHeight || 0,
      });
      video.removeAttribute('src');
      video.load();
    };
    video.onerror = () => reject(new Error('This file could not be read as a video.'));
    video.src = objectUrl;
  });
}

/** The register payload from a file plus its metadata. */
export function provisionalRegisterPayload(file, meta) {
  const fps = PROVISIONAL_FPS;
  return {
    filename: file.name,
    fps,
    total_frames: totalFrames(meta.durationSeconds, fps),
    duration_ms: Math.round(meta.durationSeconds * 1000),
    width: meta.width > 0 ? meta.width : null,
    height: meta.height > 0 ? meta.height : null,
  };
}
