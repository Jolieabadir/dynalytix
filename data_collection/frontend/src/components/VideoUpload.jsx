/**
 * VideoUpload component.
 *
 * Handles client-side pose extraction using MediaPipe JS.
 * Video never leaves the browser - only CSV data is sent to server.
 */
import { useState, useRef } from 'react';
import { getAssessments } from '../api/client';
import useStore from '../store/useStore';
import PoseExtractor from '../services/PoseExtractor';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

function VideoUpload() {
  const [processing, setProcessing] = useState(false);
  const [progress, setProgress] = useState('');
  const [progressPercent, setProgressPercent] = useState(0);
  const [error, setError] = useState(null);
  const videoRef = useRef(null);

  const {
    setCurrentVideo,
    setMoves,
    setVideoBlobUrl,
    setCsvData,
    setCsvString,
  } = useStore();

  const handleFileSelect = async (e) => {
    const file = e.target.files[0];
    if (!file) return;

    // Validate file type
    const validTypes = ['video/quicktime', 'video/mp4', 'video/x-msvideo'];
    if (!validTypes.includes(file.type) && !file.name.match(/\.(mov|mp4|avi)$/i)) {
      setError('Please upload a .mov, .mp4, or .avi file');
      return;
    }

    try {
      setProcessing(true);
      setError(null);
      setProgress('Initializing pose detection...');
      setProgressPercent(0);

      // Create blob URL for local video playback
      const blobUrl = URL.createObjectURL(file);
      setVideoBlobUrl(blobUrl);

      // Create hidden video element for processing
      const video = document.createElement('video');
      video.src = blobUrl;
      video.muted = true;
      video.playsInline = true;

      // Wait for video metadata to load
      await new Promise((resolve, reject) => {
        video.onloadedmetadata = resolve;
        video.onerror = () => reject(new Error('Failed to load video'));
      });

      const fps = 30; // Standard fps assumption
      const duration = video.duration;
      const totalFrames = Math.floor(duration * fps);
      const durationMs = duration * 1000;

      setProgress('Loading MediaPipe model...');

      // Initialize pose extractor
      const extractor = new PoseExtractor();
      await extractor.initialize();

      setProgress('Extracting poses...');

      // Extract poses from all frames
      const frames = await extractor.extractFromVideo(video, fps, (frame, total) => {
        const percent = Math.round((frame / total) * 100);
        setProgressPercent(percent);
        setProgress(`Processing frame ${frame + 1} / ${total}...`);
      });

      // Convert to CSV
      setProgress('Generating CSV data...');
      const csvString = extractor.framesToCSV(frames);
      setCsvString(csvString);

      // Parse CSV for local use
      const lines = csvString.split('\n');
      const headers = lines[0].split(',');
      const csvData = lines.slice(1).map(line => {
        const values = line.split(',');
        const row = {};
        headers.forEach((header, i) => {
          row[header.trim()] = values[i]?.trim();
        });
        return row;
      }).filter(row => row.frame_number);
      setCsvData(csvData);

      // Clean up extractor
      extractor.close();

      // Register video with server (send only CSV, not video file)
      setProgress('Registering with server...');
      const formData = new FormData();
      formData.append('filename', file.name);
      formData.append('fps', fps.toString());
      formData.append('total_frames', totalFrames.toString());
      formData.append('duration_ms', durationMs.toString());
      formData.append('csv_data', csvString);

      const response = await fetch(`${API_BASE_URL}/api/videos/register`, {
        method: 'POST',
        body: formData,
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || 'Failed to register video');
      }

      const videoData = await response.json();

      setProgress('Processing complete!');

      // Load video and its assessments
      setCurrentVideo(videoData);
      const assessments = await getAssessments(videoData.id);
      setMoves(assessments);

    } catch (err) {
      console.error('Processing error:', err);
      setError(err.message || 'Processing failed. Please try again.');
      setProcessing(false);
      setProgress('');
      setProgressPercent(0);
    }
  };

  return (
    <div className="video-upload">
      <div className="upload-container">
        <h2>Upload Deep Squat Assessment</h2>
        <p>Upload a video to begin movement assessment</p>

        {!processing ? (
          <div className="upload-area">
            <input
              type="file"
              id="video-upload"
              accept=".mov,.mp4,.avi"
              onChange={handleFileSelect}
              style={{ display: 'none' }}
            />
            <label htmlFor="video-upload" className="upload-button">
              Choose Video File
            </label>
            <p className="upload-hint">Supports .mov, .mp4, .avi</p>
            <p className="upload-hint" style={{ marginTop: '8px', fontSize: '12px', color: '#888' }}>
              Video is processed locally in your browser
            </p>
          </div>
        ) : (
          <div className="upload-progress">
            <div className="spinner"></div>
            <p>{progress}</p>
            {progressPercent > 0 && (
              <div className="progress-bar-container">
                <div
                  className="progress-bar"
                  style={{ width: `${progressPercent}%` }}
                />
              </div>
            )}
            <p className="progress-detail">
              Pose extraction runs in your browser using MediaPipe
            </p>
          </div>
        )}

        {error && (
          <div className="error-message">
            <p>{error}</p>
          </div>
        )}
      </div>

      {/* Hidden video element for metadata */}
      <video ref={videoRef} style={{ display: 'none' }} />
    </div>
  );
}

export default VideoUpload;
