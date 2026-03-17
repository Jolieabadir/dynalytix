/**
 * DualVideoReview — Shows both front and side videos with skeleton overlays
 * while the scoring pipeline runs in the background.
 *
 * User can scrub through both videos to review their movement.
 * When scoring completes, a "View Results" button appears.
 */
import { useRef, useState, useEffect } from 'react';
import useStore from '../store/useStore';
import SkeletonOverlay from './SkeletonOverlay';

function DualVideoReview({ isScoring, scoringError, scoringComplete, onViewResults, onBackToUpload }) {
  const { frontVideoBlobUrl, sideVideoBlobUrl, frontCsvData, sideCsvData } = useStore();

  // Refs for video elements
  const frontVideoRef = useRef(null);
  const sideVideoRef = useRef(null);

  // Current frame tracking for skeleton overlay
  const [frontFrame, setFrontFrame] = useState(0);
  const [sideFrame, setSideFrame] = useState(0);

  // Skeleton visibility toggles
  const [showFrontSkeleton, setShowFrontSkeleton] = useState(true);
  const [showSideSkeleton, setShowSideSkeleton] = useState(true);

  // Update frame numbers based on video time
  useEffect(() => {
    const frontVideo = frontVideoRef.current;
    const sideVideo = sideVideoRef.current;

    const updateFrontFrame = () => {
      if (frontVideo && frontCsvData) {
        const fps = 30;
        const frame = Math.floor(frontVideo.currentTime * fps);
        setFrontFrame(Math.min(frame, frontCsvData.length - 1));
      }
    };

    const updateSideFrame = () => {
      if (sideVideo && sideCsvData) {
        const fps = 30;
        const frame = Math.floor(sideVideo.currentTime * fps);
        setSideFrame(Math.min(frame, sideCsvData.length - 1));
      }
    };

    if (frontVideo) {
      frontVideo.addEventListener('timeupdate', updateFrontFrame);
      frontVideo.addEventListener('seeked', updateFrontFrame);
    }
    if (sideVideo) {
      sideVideo.addEventListener('timeupdate', updateSideFrame);
      sideVideo.addEventListener('seeked', updateSideFrame);
    }

    return () => {
      if (frontVideo) {
        frontVideo.removeEventListener('timeupdate', updateFrontFrame);
        frontVideo.removeEventListener('seeked', updateFrontFrame);
      }
      if (sideVideo) {
        sideVideo.removeEventListener('timeupdate', updateSideFrame);
        sideVideo.removeEventListener('seeked', updateSideFrame);
      }
    };
  }, [frontCsvData, sideCsvData]);

  return (
    <div className="dual-video-review">
      {/* Back button */}
      <button className="back-button" onClick={onBackToUpload}>
        ← Re-upload Videos
      </button>

      <h2>Review Your Assessment</h2>
      <p className="review-subtitle">Scrub through both videos to review your movement</p>

      {/* Both videos side by side */}
      <div className="dual-video-container">
        <div className="video-panel">
          <div className="video-panel-header">
            <h3>Front View</h3>
            {frontCsvData && (
              <button
                className={`toggle-skeleton ${showFrontSkeleton ? 'active' : ''}`}
                onClick={() => setShowFrontSkeleton(!showFrontSkeleton)}
              >
                {showFrontSkeleton ? '🦴 Hide Skeleton' : '🦴 Show Skeleton'}
              </button>
            )}
          </div>
          {frontVideoBlobUrl ? (
            <div className="video-wrapper">
              <video
                ref={frontVideoRef}
                src={frontVideoBlobUrl}
                controls
                loop
                muted
                playsInline
                className="review-video"
              />
              {showFrontSkeleton && frontCsvData && (
                <SkeletonOverlay
                  videoRef={frontVideoRef}
                  currentFrame={frontFrame}
                  csvData={frontCsvData}
                />
              )}
            </div>
          ) : (
            <div className="video-placeholder">
              <p>No front view uploaded</p>
            </div>
          )}
        </div>

        <div className="video-panel">
          <div className="video-panel-header">
            <h3>Side View</h3>
            {sideCsvData && (
              <button
                className={`toggle-skeleton ${showSideSkeleton ? 'active' : ''}`}
                onClick={() => setShowSideSkeleton(!showSideSkeleton)}
              >
                {showSideSkeleton ? '🦴 Hide Skeleton' : '🦴 Show Skeleton'}
              </button>
            )}
          </div>
          {sideVideoBlobUrl ? (
            <div className="video-wrapper">
              <video
                ref={sideVideoRef}
                src={sideVideoBlobUrl}
                controls
                loop
                muted
                playsInline
                className="review-video"
              />
              {showSideSkeleton && sideCsvData && (
                <SkeletonOverlay
                  videoRef={sideVideoRef}
                  currentFrame={sideFrame}
                  csvData={sideCsvData}
                />
              )}
            </div>
          ) : (
            <div className="video-placeholder">
              <p>No side view (single-angle scoring)</p>
            </div>
          )}
        </div>
      </div>

      {/* Scoring status + action button */}
      <div className="review-actions">
        {isScoring && (
          <div className="scoring-in-progress">
            <div className="spinner" />
            <p>Analyzing movement from both angles...</p>
          </div>
        )}

        {scoringError && !isScoring && (
          <div className="scoring-error">
            <p>⚠ {scoringError}</p>
            <button className="primary-button" onClick={onViewResults}>
              View Available Results →
            </button>
          </div>
        )}

        {scoringComplete && !isScoring && !scoringError && (
          <div className="scoring-complete">
            <p className="scoring-success">✓ Scoring complete</p>
            <button className="primary-button view-results-button" onClick={onViewResults}>
              View Results →
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

export default DualVideoReview;
