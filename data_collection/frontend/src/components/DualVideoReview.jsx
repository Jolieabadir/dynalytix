/**
 * DualVideoReview — Shows both front and side videos with skeleton overlays
 * while the scoring pipeline runs in the background.
 */
import useStore from '../store/useStore';

function DualVideoReview({ isScoring, scoringError }) {
  const { frontVideoBlobUrl, sideVideoBlobUrl } = useStore();

  return (
    <div className="dual-video-review">
      <div className="scoring-status">
        {isScoring ? (
          <>
            <div className="spinner" />
            <p>Analyzing movement from both angles...</p>
          </>
        ) : scoringError ? (
          <p className="error-text">Scoring error: {scoringError}</p>
        ) : (
          <p>Scoring complete! Loading results...</p>
        )}
      </div>

      <div className="dual-video-container">
        {/* Front View */}
        <div className="video-panel">
          <h3>Front View</h3>
          {frontVideoBlobUrl ? (
            <div className="video-wrapper">
              <video
                src={frontVideoBlobUrl}
                controls
                loop
                muted
                playsInline
                className="review-video"
              />
            </div>
          ) : (
            <div className="video-placeholder">
              <p>No front view uploaded</p>
            </div>
          )}
        </div>

        {/* Side View */}
        <div className="video-panel">
          <h3>Side View</h3>
          {sideVideoBlobUrl ? (
            <div className="video-wrapper">
              <video
                src={sideVideoBlobUrl}
                controls
                loop
                muted
                playsInline
                className="review-video"
              />
            </div>
          ) : (
            <div className="video-placeholder">
              <p>No side view uploaded (single-angle scoring)</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default DualVideoReview;
