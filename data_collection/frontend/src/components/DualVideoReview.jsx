/**
 * DualVideoReview — Shows both front and side videos with playback controls
 * while the scoring pipeline runs in the background.
 *
 * User can scrub through both videos to review their movement.
 * When scoring completes, a "View Results" button appears.
 */
import useStore from '../store/useStore';

function DualVideoReview({ isScoring, scoringError, scoringComplete, onViewResults, onBackToUpload }) {
  const { frontVideoBlobUrl, sideVideoBlobUrl } = useStore();

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
          <h3>Front View</h3>
          {frontVideoBlobUrl ? (
            <video
              src={frontVideoBlobUrl}
              controls
              loop
              muted
              playsInline
              className="review-video"
            />
          ) : (
            <div className="video-placeholder">
              <p>No front view uploaded</p>
            </div>
          )}
        </div>

        <div className="video-panel">
          <h3>Side View</h3>
          {sideVideoBlobUrl ? (
            <video
              src={sideVideoBlobUrl}
              controls
              loop
              muted
              playsInline
              className="review-video"
            />
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
