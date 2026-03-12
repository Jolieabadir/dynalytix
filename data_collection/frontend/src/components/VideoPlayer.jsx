/**
 * VideoPlayer component with skeleton overlay.
 * 
 * Plays video with frame-accurate scrubbing and optional pose visualization.
 */
import { useRef, useEffect, useState } from 'react';
import useStore from '../store/useStore';
import SkeletonOverlay from './SkeletonOverlay';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

function VideoPlayer() {
  const videoRef = useRef(null);
  const [duration, setDuration] = useState(0);
  const [csvData, setCsvData] = useState(null);
  const [showSkeleton, setShowSkeleton] = useState(true);
  
  const {
    currentVideo,
    currentFrame,
    isPlaying,
    moveStart,
    moveEnd,
    videoBlobUrl,
    csvData: storeCsvData,
    setCurrentFrame,
    setIsPlaying,
    setMoveStart,
    setMoveEnd,
    setShowMoveForm,
    clearMoveSelection,
  } = useStore();

  const fps = currentVideo?.fps || 30;

  // Load CSV data when video changes
  // Use store data if available (client-side extraction), otherwise fetch from server
  useEffect(() => {
    if (!currentVideo) return;

    // If we have CSV data in the store from client-side extraction, use it
    if (storeCsvData && storeCsvData.length > 0) {
      setCsvData(storeCsvData);
      console.log(`Using ${storeCsvData.length} frames of pose data from client-side extraction`);
      return;
    }

    // Fallback: fetch from server (for videos uploaded via old server-side flow)
    const loadCSV = async () => {
      try {
        const response = await fetch(`${API_BASE_URL}/api/videos/${currentVideo.id}/csv`);
        const csvText = await response.text();

        // Parse CSV
        const lines = csvText.split('\n');
        const headers = lines[0].split(',');

        const data = lines.slice(1).map(line => {
          const values = line.split(',');
          const row = {};
          headers.forEach((header, i) => {
            row[header.trim()] = values[i]?.trim();
          });
          return row;
        }).filter(row => row.frame_number); // Remove empty rows

        setCsvData(data);
        console.log(`Loaded ${data.length} frames of pose data from server`);
      } catch (error) {
        console.error('Failed to load CSV:', error);
      }
    };

    loadCSV();
  }, [currentVideo, storeCsvData]);

  // Update current frame as video plays
  useEffect(() => {
    if (!videoRef.current) return;

    const updateFrame = () => {
      const frame = Math.floor(videoRef.current.currentTime * fps);
      setCurrentFrame(frame);
    };

    const video = videoRef.current;
    video.addEventListener('timeupdate', updateFrame);
    
    return () => video.removeEventListener('timeupdate', updateFrame);
  }, [fps, setCurrentFrame]);

  // Keyboard shortcuts
  useEffect(() => {
    const handleKeyPress = (e) => {
      // Ignore if typing in input
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;

      switch (e.key) {
        case 'ArrowLeft':
          e.preventDefault();
          seekToFrame(currentFrame - 1);
          break;
        case 'ArrowRight':
          e.preventDefault();
          seekToFrame(currentFrame + 1);
          break;
        case ' ':
          e.preventDefault();
          togglePlay();
          break;
        case '[':
          e.preventDefault();
          setMoveStart(currentFrame);
          break;
        case ']':
          e.preventDefault();
          setMoveEnd(currentFrame);
          break;
        case 's':
        case 'S':
          e.preventDefault();
          setShowSkeleton(prev => !prev);
          break;
      }
    };

    window.addEventListener('keydown', handleKeyPress);
    return () => window.removeEventListener('keydown', handleKeyPress);
  }, [currentFrame, moveStart]);

  const seekToFrame = (frame) => {
    if (!videoRef.current) return;
    const time = frame / fps;
    videoRef.current.currentTime = time;
    setCurrentFrame(frame);
  };

  const togglePlay = () => {
    if (!videoRef.current) return;
    
    if (isPlaying) {
      videoRef.current.pause();
    } else {
      videoRef.current.play();
    }
    setIsPlaying(!isPlaying);
  };

  const handleLoadedMetadata = () => {
    if (videoRef.current) {
      setDuration(videoRef.current.duration);
    }
  };

  const handleCreateMove = () => {
    if (moveStart !== null && moveEnd !== null) {
      setShowMoveForm(true);
    }
  };

  if (!currentVideo) return null;

  return (
    <div className="video-player">
      <div className="video-container">
        {/* Wrapper keeps video and canvas aligned */}
        <div className="video-wrapper">
          <video
            ref={videoRef}
            src={videoBlobUrl || `${API_BASE_URL}/videos/${currentVideo.filename}`}
            onLoadedMetadata={handleLoadedMetadata}
          />
          
          {showSkeleton && csvData && (
            <SkeletonOverlay
              videoRef={videoRef}
              currentFrame={currentFrame}
              csvData={csvData}
            />
          )}
        </div>
      </div>

      <div className="video-controls">
        <button onClick={() => seekToFrame(currentFrame - 10)}>⏮ -10</button>
        <button onClick={() => seekToFrame(currentFrame - 1)}>◀</button>
        <button onClick={togglePlay} className="play-btn">{isPlaying ? '⏸' : '▶'}</button>
        <button onClick={() => seekToFrame(currentFrame + 1)}>▶▶</button>
        <button onClick={() => seekToFrame(currentFrame + 10)}>+10 ⏭</button>

        <span className="frame-counter">
          Frame: {currentFrame} / {currentVideo.total_frames}
          {' '}({(currentFrame / fps).toFixed(2)}s)
        </span>

        <button 
          onClick={() => setShowSkeleton(!showSkeleton)}
          className={`toggle-skeleton ${showSkeleton ? 'active' : ''}`}
          title="Toggle skeleton (S key)"
        >
          {showSkeleton ? '👁️ Hide' : '👁️ Show'} Skeleton
        </button>
      </div>

      <div className="timeline">
        <input
          type="range"
          min="0"
          max={currentVideo.total_frames}
          value={currentFrame}
          onChange={(e) => seekToFrame(parseInt(e.target.value))}
          className="timeline-slider"
        />
        {moveStart !== null && (
          <div 
            className="move-marker start"
            style={{ left: `${(moveStart / currentVideo.total_frames) * 100}%` }}
          />
        )}
        {moveEnd !== null && (
          <div 
            className="move-marker end"
            style={{ left: `${(moveEnd / currentVideo.total_frames) * 100}%` }}
          />
        )}
      </div>

      <div className="move-selection-controls">
        <button 
          onClick={() => setMoveStart(currentFrame)}
          className={moveStart !== null ? 'active' : ''}
        >
          [ Mark Start
        </button>
        <button 
          onClick={() => setMoveEnd(currentFrame)}
          disabled={moveStart === null}
        >
          ] Mark End
        </button>
        
        {moveStart !== null && moveEnd !== null && (
          <>
            <span className="selection-info">
              Selected: {moveStart} - {moveEnd} ({moveEnd - moveStart} frames)
            </span>
            <button 
              onClick={handleCreateMove}
              className="create-move-btn"
            >
              Create Move
            </button>
            <button 
              onClick={clearMoveSelection}
              className="clear-selection-btn"
            >
              Clear Selection
            </button>
          </>
        )}
      </div>
    </div>
  );
}

export default VideoPlayer;
