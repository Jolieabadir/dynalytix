/**
 * Resumable upload of the original video, in R2 multipart parts.
 *
 * Why this exists: iOS Safari evicts a backgrounded page. A single PUT of a
 * 300 MB clip dies with it and starts from zero. Here the file goes up in
 * independently signed parts, each retried on its own, and the parts already
 * accepted are remembered — so locking the phone costs one part, and a page
 * that was evicted outright resumes as soon as the labeler picks the same
 * file again.
 *
 * What is remembered, and where: the upload id, the key, the part size and
 * the ETag of every finished part, in localStorage under a key derived from
 * the video id. The file itself is NOT remembered — a browser cannot hold a
 * File across a page load, which is exactly why resuming asks for the same
 * file again and verifies it by name, size and mtime before trusting the
 * saved parts.
 *
 * The laptop path does not come through here: VideoUpload picks the
 * single-shot PUT when the file is small enough that a retry is cheap.
 */
import {
  createMultipartUpload,
  signUploadPart,
  completeMultipartUpload,
  abortMultipartUpload,
} from '../api/client';

/** Files at or above this go up in parts. Below it, one PUT is cheaper. */
export const RESUMABLE_THRESHOLD_BYTES = 8 * 1024 * 1024;

/** How many parts are in flight at once. Two is kind to a phone radio. */
const CONCURRENCY = 2;

/** Attempts per part before the whole upload gives up. */
const PART_ATTEMPTS = 4;

const STORAGE_PREFIX = 'dynalytix.upload.';

const storageKey = (videoId) => `${STORAGE_PREFIX}${videoId}`;

/**
 * Identity of a picked file, as far as a browser can tell.
 *
 * Name, size and last-modified together are what we have; there is no hash
 * without reading the whole file, which on a phone is the cost we are trying
 * to avoid. Good enough to catch "the labeler picked a different clip".
 */
export function fileSignature(file) {
  return `${file.name}:${file.size}:${file.lastModified}`;
}

/** localStorage, but never fatal — Safari private mode throws on write. */
function readSession(videoId) {
  try {
    const raw = localStorage.getItem(storageKey(videoId));
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

function writeSession(videoId, session) {
  try {
    localStorage.setItem(storageKey(videoId), JSON.stringify(session));
  } catch {
    // Out of quota or blocked: the upload still works, it just cannot resume.
  }
}

export function clearSession(videoId) {
  try {
    localStorage.removeItem(storageKey(videoId));
  } catch {
    // Nothing to do.
  }
}

/**
 * The saved upload for this video, but only if it matches the file in hand.
 * @returns {{upload_id: string, key: string, part_size: number, parts: object}|null}
 */
export function resumableSessionFor(videoId, file) {
  const session = readSession(videoId);
  if (!session) return null;
  if (session.signature !== fileSignature(file)) {
    // A different file under the same video id: the saved parts are garbage.
    clearSession(videoId);
    return null;
  }
  return session;
}

/** Byte range of a 1-based part number. */
export function partRange(partNumber, partSize, fileSize) {
  const start = (partNumber - 1) * partSize;
  return { start, end: Math.min(start + partSize, fileSize) };
}

/** How many parts a file of this size needs. */
export function partCount(fileSize, partSize) {
  return Math.max(1, Math.ceil(fileSize / partSize));
}

/**
 * PUT one part, with progress, and hand back the ETag R2 answered.
 *
 * XMLHttpRequest rather than fetch, because fetch has no upload progress and
 * a phone upload without a moving bar reads as a hang. No Content-Type: the
 * part presign does not sign one, and an unsigned header breaks the
 * signature.
 */
function putPart(url, blob, { onProgress, signal } = {}) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('PUT', url, true);
    xhr.upload.onprogress = (event) => {
      if (onProgress && event.lengthComputable && event.total > 0) {
        onProgress(event.loaded);
      }
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        const etag = xhr.getResponseHeader('ETag');
        if (!etag) {
          reject(new Error('R2 did not return an ETag — check the bucket CORS ExposeHeaders'));
          return;
        }
        if (onProgress) onProgress(blob.size);
        resolve(etag);
      } else {
        reject(new Error(`Part upload failed (${xhr.status})`));
      }
    };
    xhr.onerror = () => reject(new Error('Part upload failed (network error)'));
    xhr.onabort = () => reject(new DOMException('Upload cancelled', 'AbortError'));
    if (signal) {
      if (signal.aborted) {
        xhr.abort();
        return;
      }
      signal.addEventListener('abort', () => xhr.abort(), { once: true });
    }
    xhr.send(blob);
  });
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/**
 * Upload one part, retrying it alone.
 *
 * The part URL is re-signed on every attempt rather than reused: an upload
 * interrupted by a long lock screen can outlive the presign, and re-signing
 * costs one small request against the alternative of failing the whole clip.
 */
async function uploadPartWithRetry(videoId, session, file, partNumber, handlers) {
  const { start, end } = partRange(partNumber, session.part_size, file.size);
  const blob = file.slice(start, end);
  let lastError;

  for (let attempt = 1; attempt <= PART_ATTEMPTS; attempt++) {
    if (handlers.signal?.aborted) throw new DOMException('Upload cancelled', 'AbortError');
    try {
      const { url } = await signUploadPart(videoId, {
        key: session.key,
        upload_id: session.upload_id,
        part_number: partNumber,
      });
      return await putPart(url, blob, {
        onProgress: (loaded) => handlers.onPartProgress(partNumber, loaded),
        signal: handlers.signal,
      });
    } catch (err) {
      if (err?.name === 'AbortError') throw err;
      lastError = err;
      // This part starts over, so its progress does too.
      handlers.onPartProgress(partNumber, 0);
      if (attempt === PART_ATTEMPTS) break;
      await sleep(500 * 2 ** (attempt - 1) * (0.5 + Math.random()));
    }
  }
  throw lastError || new Error(`Part ${partNumber} failed`);
}

/**
 * Upload a file to R2 in resumable parts and finish the job.
 *
 * Resolves to the confirmed video row (complete-multipart enqueues the pose
 * worker, exactly as confirm-upload does on the single-shot path).
 *
 * @param {number} videoId
 * @param {File} file
 * @param {{onProgress?: (fraction: number) => void, signal?: AbortSignal}} [options]
 */
export async function uploadResumable(videoId, file, options = {}) {
  const { onProgress, signal } = options;

  let session = resumableSessionFor(videoId, file);
  if (!session) {
    const started = await createMultipartUpload(videoId, file.type || 'video/mp4');
    session = {
      upload_id: started.upload_id,
      key: started.key,
      part_size: started.part_size,
      signature: fileSignature(file),
      parts: {},
    };
    writeSession(videoId, session);
  }

  const total = partCount(file.size, session.part_size);
  const done = new Set(Object.keys(session.parts).map(Number));

  // Bytes already banked, plus live progress of the parts in flight.
  const inFlight = new Map();
  const bankedBytes = () =>
    [...done].reduce((sum, n) => {
      const { start, end } = partRange(n, session.part_size, file.size);
      return sum + (end - start);
    }, 0);

  const report = () => {
    if (!onProgress) return;
    const live = [...inFlight.values()].reduce((a, b) => a + b, 0);
    onProgress(Math.min(1, (bankedBytes() + live) / Math.max(1, file.size)));
  };
  report();

  const handlers = {
    signal,
    onPartProgress: (partNumber, loaded) => {
      inFlight.set(partNumber, loaded);
      report();
    },
  };

  const queue = [];
  for (let n = 1; n <= total; n++) if (!done.has(n)) queue.push(n);

  async function worker() {
    for (;;) {
      const partNumber = queue.shift();
      if (partNumber === undefined) return;
      const etag = await uploadPartWithRetry(videoId, session, file, partNumber, handlers);
      inFlight.delete(partNumber);
      done.add(partNumber);
      session.parts[partNumber] = etag;
      // Written after every part: this is the thing that survives eviction.
      writeSession(videoId, session);
      report();
    }
  }

  await Promise.all(Array.from({ length: Math.min(CONCURRENCY, queue.length || 1) }, worker));

  const parts = Object.entries(session.parts).map(([partNumber, etag]) => ({
    part_number: Number(partNumber),
    etag,
  }));

  const confirmed = await completeMultipartUpload(videoId, {
    key: session.key,
    upload_id: session.upload_id,
    parts,
  });

  clearSession(videoId);
  if (onProgress) onProgress(1);
  return confirmed;
}

/** Give up on a saved upload and stop R2 billing for its parts. */
export async function abandonResumable(videoId) {
  const session = readSession(videoId);
  clearSession(videoId);
  if (!session) return false;
  try {
    await abortMultipartUpload(videoId, { key: session.key, upload_id: session.upload_id });
    return true;
  } catch {
    return false;
  }
}
