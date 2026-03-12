import { PoseLandmarker, FilesetResolver } from '@mediapipe/tasks-vision';

// MediaPipe landmark indices we care about (maps to our landmark names)
const LANDMARK_MAP = {
  0: 'nose',
  11: 'left_shoulder',
  12: 'right_shoulder',
  13: 'left_elbow',
  14: 'right_elbow',
  15: 'left_wrist',
  16: 'right_wrist',
  23: 'left_hip',
  24: 'right_hip',
  25: 'left_knee',
  26: 'right_knee',
  27: 'left_ankle',
  28: 'right_ankle',
  29: 'left_heel',
  30: 'right_heel',
};

// Angle definitions: [name, pointA, pointB (vertex), pointC]
const ANGLE_DEFINITIONS = [
  ['left_elbow', 'left_shoulder', 'left_elbow', 'left_wrist'],
  ['right_elbow', 'right_shoulder', 'right_elbow', 'right_wrist'],
  ['left_shoulder', 'left_hip', 'left_shoulder', 'left_elbow'],
  ['right_shoulder', 'right_hip', 'right_shoulder', 'right_elbow'],
  ['left_hip', 'left_shoulder', 'left_hip', 'left_knee'],
  ['right_hip', 'right_shoulder', 'right_hip', 'right_knee'],
  ['left_knee', 'left_hip', 'left_knee', 'left_ankle'],
  ['right_knee', 'right_hip', 'right_knee', 'right_ankle'],
  ['left_ankle', 'left_knee', 'left_ankle', 'left_heel'],
  ['right_ankle', 'right_knee', 'right_ankle', 'right_heel'],
];

function angleBetween(a, b, c) {
  // Calculate angle at point b given three landmarks
  const ab = { x: a.x - b.x, y: a.y - b.y };
  const cb = { x: c.x - b.x, y: c.y - b.y };
  const dot = ab.x * cb.x + ab.y * cb.y;
  const magAB = Math.sqrt(ab.x ** 2 + ab.y ** 2);
  const magCB = Math.sqrt(cb.x ** 2 + cb.y ** 2);
  if (magAB === 0 || magCB === 0) return null;
  const cosAngle = Math.max(-1, Math.min(1, dot / (magAB * magCB)));
  return Math.acos(cosAngle) * (180 / Math.PI);
}

function midpoint(a, b) {
  return {
    x: (a.x + b.x) / 2,
    y: (a.y + b.y) / 2,
    z: (a.z + b.z) / 2,
  };
}

function calculateUpperBack(landmarks) {
  const ls = landmarks['left_shoulder'];
  const rs = landmarks['right_shoulder'];
  if (!ls || !rs) return null;
  const mid = midpoint(ls, rs);
  return angleBetween(ls, mid, rs);
}

function calculateLowerBack(landmarks) {
  const ls = landmarks['left_shoulder'];
  const rs = landmarks['right_shoulder'];
  const lh = landmarks['left_hip'];
  const rh = landmarks['right_hip'];
  const lk = landmarks['left_knee'];
  const rk = landmarks['right_knee'];
  if (!ls || !rs || !lh || !rh || !lk || !rk) return null;
  const shoulderMid = midpoint(ls, rs);
  const hipMid = midpoint(lh, rh);
  const kneeMid = midpoint(lk, rk);
  return angleBetween(shoulderMid, hipMid, kneeMid);
}

function distance(a, b) {
  return Math.sqrt((a.x - b.x) ** 2 + (a.y - b.y) ** 2);
}

export class PoseExtractor {
  constructor() {
    this.poseLandmarker = null;
    this.previousLandmarks = null;
    this.previousTimestamp = null;
  }

  async initialize() {
    const vision = await FilesetResolver.forVisionTasks(
      'https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@latest/wasm'
    );
    this.poseLandmarker = await PoseLandmarker.createFromOptions(vision, {
      baseOptions: {
        modelAssetPath: 'https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_full/float16/1/pose_landmarker_full.task',
        delegate: 'GPU',
      },
      runningMode: 'VIDEO',
      numPoses: 1,
      minPoseDetectionConfidence: 0.5,
      minTrackingConfidence: 0.5,
    });
  }

  processFrame(videoElement, timestampMs) {
    if (!this.poseLandmarker) return null;

    const result = this.poseLandmarker.detectForVideo(videoElement, timestampMs);

    if (!result.landmarks || result.landmarks.length === 0) {
      return null;
    }

    const rawLandmarks = result.landmarks[0];
    const videoWidth = videoElement.videoWidth;
    const videoHeight = videoElement.videoHeight;

    // Convert normalized coords to pixel coords and map to our names
    const landmarks = {};
    for (const [index, name] of Object.entries(LANDMARK_MAP)) {
      const lm = rawLandmarks[parseInt(index)];
      if (lm) {
        landmarks[name] = {
          x: lm.x * videoWidth,
          y: lm.y * videoHeight,
          z: lm.z,
          visibility: lm.visibility || 0,
        };
      }
    }

    // Calculate 10 standard angles
    const angles = {};
    for (const [angleName, ptA, ptB, ptC] of ANGLE_DEFINITIONS) {
      if (landmarks[ptA] && landmarks[ptB] && landmarks[ptC]) {
        angles[angleName] = angleBetween(landmarks[ptA], landmarks[ptB], landmarks[ptC]);
      } else {
        angles[angleName] = null;
      }
    }
    // 2 back angles
    angles['upper_back'] = calculateUpperBack(landmarks);
    angles['lower_back'] = calculateLowerBack(landmarks);

    // Center of mass speed
    let comSpeed = 0;
    if (landmarks['left_hip'] && landmarks['right_hip']) {
      const com = midpoint(landmarks['left_hip'], landmarks['right_hip']);
      if (this.previousLandmarks && this.previousTimestamp !== null) {
        const prevCom = this.previousLandmarks._com;
        const dt = (timestampMs - this.previousTimestamp) / 1000; // seconds
        if (prevCom && dt > 0) {
          comSpeed = distance(com, prevCom) / dt;
        }
      }
      // Store for next frame
      landmarks._com = com;
    }

    this.previousLandmarks = landmarks;
    this.previousTimestamp = timestampMs;

    return { landmarks, angles, comSpeed };
  }

  async extractFromVideo(videoElement, fps, onProgress) {
    // Process all frames by seeking through the video
    const duration = videoElement.duration;
    const totalFrames = Math.floor(duration * fps);
    const frames = [];

    this.previousLandmarks = null;
    this.previousTimestamp = null;

    for (let frameNum = 0; frameNum < totalFrames; frameNum++) {
      const timestampMs = (frameNum / fps) * 1000;
      videoElement.currentTime = timestampMs / 1000;

      // Wait for seek to complete
      await new Promise(resolve => {
        videoElement.onseeked = resolve;
      });

      const result = this.processFrame(videoElement, timestampMs);
      frames.push({ frameNum, timestampMs, result });

      if (onProgress) {
        onProgress(frameNum, totalFrames);
      }
    }

    return frames;
  }

  framesToCSV(frames) {
    // Build CSV string matching Python pipeline format exactly
    const landmarkNames = Object.values(LANDMARK_MAP);

    // Header
    const headers = [
      'frame_number', 'timestamp_ms', 'speed_center_of_mass',
      ...ANGLE_DEFINITIONS.map(([name]) => `angle_${name}`),
      'angle_upper_back', 'angle_lower_back',
    ];
    for (const name of landmarkNames) {
      headers.push(`landmark_${name}_x`, `landmark_${name}_y`, `landmark_${name}_z`, `landmark_${name}_visibility`);
    }

    const rows = [headers.join(',')];

    for (const frame of frames) {
      const row = [
        frame.frameNum,
        frame.timestampMs,
        frame.result ? frame.result.comSpeed : 0,
      ];

      // Angles
      for (const [angleName] of ANGLE_DEFINITIONS) {
        row.push(frame.result?.angles?.[angleName] ?? '');
      }
      row.push(frame.result?.angles?.['upper_back'] ?? '');
      row.push(frame.result?.angles?.['lower_back'] ?? '');

      // Landmarks
      for (const name of landmarkNames) {
        const lm = frame.result?.landmarks?.[name];
        if (lm) {
          row.push(lm.x, lm.y, lm.z, lm.visibility);
        } else {
          row.push('', '', '', '');
        }
      }

      rows.push(row.join(','));
    }

    return rows.join('\n');
  }

  close() {
    if (this.poseLandmarker) {
      this.poseLandmarker.close();
    }
  }
}

export default PoseExtractor;
