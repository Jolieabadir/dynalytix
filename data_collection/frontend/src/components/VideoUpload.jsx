/**
 * VideoUpload component.
 * 
 * Allows user to upload a video file.
 * Shows processing progress while backend extracts pose data.
 */
import { useState } from 'react';
import { uploadVideo, getAssessments } from '../api/client';
import useStore from '../store/useStore';

function VideoUpload() {
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState('');
  const [error, setError] = useState(null);
  
  const { setCurrentVideo, setMoves } = useStore();

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
      setUploading(true);
      setError(null);
      setProgress('Uploading video...');

      // Upload and process
      const video = await uploadVideo(file);
      
      setProgress('Processing complete!');
      
      // Load video and its moves
      setCurrentVideo(video);
      const moves = await getAssessments(video.id);
      setMoves(moves);
      
    } catch (err) {
      console.error('Upload error:', err);
      setError(err.response?.data?.detail || 'Upload failed. Please try again.');
      setUploading(false);
      setProgress('');
    }
  };

  return (
    <div className="video-upload">
      <div className="upload-container">
        <h2>Upload Deep Squat Assessment</h2>
        <p>Upload a video to begin FMS assessment</p>

        {!uploading ? (
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
          </div>
        ) : (
          <div className="upload-progress">
            <div className="spinner"></div>
            <p>{progress}</p>
            <p className="progress-detail">
              This may take a minute while we extract pose data...
            </p>
          </div>
        )}

        {error && (
          <div className="error-message">
            <p>{error}</p>
          </div>
        )}
      </div>
    </div>
  );
}

export default VideoUpload;
