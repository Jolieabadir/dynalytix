/**
 * ThankYouModal - Post-export results screen with report access.
 *
 * Shows after export completes. Offers two report views:
 * - Patient Report (no billing codes, plain language)
 * - Provider Report (full clinical data with billing categories)
 *
 * Supports dual-angle assessments (front + side views).
 */
import { useState } from 'react';
import useStore from '../store/useStore';
import { getFMSPatientReport, getFMSProviderReport } from '../api/client';

function ThankYouModal({ show, onClose, videoId, frontVideoId, sideVideoId, dualAngleResults }) {
  const { setCurrentVideo, setCurrentMove, setFrameTags, setMode, resetDualAngle } = useStore();
  const [activeReport, setActiveReport] = useState(null);
  const [reportData, setReportData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const isDualAngle = frontVideoId && sideVideoId;

  if (!show) return null;

  const handleFinish = () => {
    setMode('define');
    setCurrentMove(null);
    setFrameTags([]);
    setCurrentVideo(null);
    resetDualAngle();
    setActiveReport(null);
    setReportData(null);
    if (onClose) onClose();
  };

  const handleViewReport = async (type) => {
    setLoading(true);
    setError(null);
    try {
      const data = type === 'patient'
        ? await getFMSPatientReport(videoId)
        : await getFMSProviderReport(videoId);
      setReportData(data);
      setActiveReport(type);
    } catch (err) {
      console.error(`Failed to load ${type} report:`, err);
      setError('Could not load report. The assessment may still be processing.');
    } finally {
      setLoading(false);
    }
  };

  const handleBack = () => {
    setActiveReport(null);
    setReportData(null);
    setError(null);
  };

  if (!activeReport) {
    return (
      <div className="thank-you-overlay">
        <div className="thank-you-modal">
          <h2>Assessment Complete</h2>
          <p className="export-success">✅ Data exported and scored successfully!</p>

          {isDualAngle && (
            <div className="dual-angle-summary">
              <span className="dual-badge">Dual-Angle Assessment</span>
              <p>Front view + Side view analyzed</p>
              {dualAngleResults && (
                <div className="dual-scores">
                  <span className="view-score">Front: {dualAngleResults.front_score}/3</span>
                  <span className="view-score">Side: {dualAngleResults.side_score}/3</span>
                  <span className="merged-score">Merged: {dualAngleResults.score}/3</span>
                </div>
              )}
            </div>
          )}

          <div className="report-buttons">
            <button onClick={() => handleViewReport('patient')} className="report-btn patient-btn" disabled={loading}>
              {loading ? 'Loading...' : '📋 Patient Report'}
              <span className="report-btn-desc">Movement summary & recommendations</span>
            </button>
            <button onClick={() => handleViewReport('provider')} className="report-btn provider-btn" disabled={loading}>
              {loading ? 'Loading...' : '🏥 Provider Report'}
              <span className="report-btn-desc">Full clinical data & billing categories</span>
            </button>
          </div>
          {error && <p className="report-error">{error}</p>}
          <button onClick={handleFinish} className="upload-another-btn">Upload Another Video</button>
        </div>
      </div>
    );
  }

  if (activeReport === 'patient' && reportData) {
    return (
      <div className="thank-you-overlay">
        <div className="thank-you-modal report-modal">
          <div className="report-header">
            <button onClick={handleBack} className="back-link">← Back</button>
            <h2>Patient Report</h2>
          </div>
          <div className="report-content">
            <div className="score-display">
              <div className="score-circle">
                <span className="score-number">{reportData.score}</span>
                <span className="score-max">/{reportData.max_score}</span>
              </div>
              <h3>{reportData.test}</h3>
            </div>
            <p className="interpretation">{reportData.interpretation}</p>
            <div className="criteria-list">
              <h4>Assessment Details</h4>
              {reportData.criteria?.map((c, i) => (
                <div key={i} className={`criterion-item ${c.status === 'Pass' ? 'pass' : 'fail'}`}>
                  <span className="criterion-status">{c.status === 'Pass' ? '✓' : '⚠'}</span>
                  <div>
                    <strong>{c.name}</strong>
                    <p>{c.detail}</p>
                  </div>
                </div>
              ))}
            </div>
            {reportData.asymmetries?.length > 0 && (
              <div className="asymmetries">
                <h4>Asymmetries Detected</h4>
                {reportData.asymmetries.map((a, i) => (
                  <p key={i}>⚠ {a.note}</p>
                ))}
              </div>
            )}
            {reportData.focus_areas?.length > 0 && (
              <div className="focus-areas">
                <h4>Recommended Focus Areas</h4>
                {reportData.focus_areas.map((area, i) => (
                  <p key={i}>→ {area}</p>
                ))}
              </div>
            )}
          </div>
          <button onClick={handleFinish} className="upload-another-btn">Upload Another Video</button>
        </div>
      </div>
    );
  }

  if (activeReport === 'provider' && reportData) {
    return (
      <div className="thank-you-overlay">
        <div className="thank-you-modal report-modal">
          <div className="report-header">
            <button onClick={handleBack} className="back-link">← Back</button>
            <h2>Provider Report</h2>
          </div>
          <div className="report-content">
            <div className="score-display">
              <div className="score-circle">
                <span className="score-number">{reportData.score}</span>
                <span className="score-max">/3</span>
              </div>
              <h3>Deep Squat Assessment</h3>
              <p className="assessment-date">
                {reportData.assessment_date ? new Date(reportData.assessment_date).toLocaleDateString() : ''}
              </p>
            </div>
            <div className="criteria-list">
              <h4>Scoring Criteria</h4>
              {reportData.criteria?.map((c, i) => (
                <div key={i} className={`criterion-item ${c.passed ? 'pass' : 'fail'}`}>
                  <span className="criterion-status">{c.passed ? '✓' : '✗'}</span>
                  <div>
                    <strong>{c.name}</strong>
                    {c.value != null && <span className="criterion-value"> — {c.value.toFixed(1)}° (threshold: {c.threshold?.toFixed(1)}°)</span>}
                    <p>{c.detail}</p>
                  </div>
                </div>
              ))}
            </div>
            {reportData.bilateral_differences && (
              <div className="bilateral-section">
                <h4>Bilateral Differences</h4>
                {Object.entries(reportData.bilateral_differences).map(([joint, diff]) => (
                  <div key={joint} className={`bilateral-item ${Math.abs(diff) > 10 ? 'asymmetry' : ''}`}>
                    <span>{joint}</span>
                    <span className="bilateral-value">{diff > 0 ? '+' : ''}{diff.toFixed(1)}°</span>
                    {Math.abs(diff) > 10 && <span className="asymmetry-flag">⚠ ASYMMETRY</span>}
                  </div>
                ))}
              </div>
            )}
            {reportData.billing_descriptions?.length > 0 && (
              <div className="cpt-section">
                <h4>Billing Categories</h4>
                <p className="cpt-disclaimer">⚠ Review and approve before billing. Consult your practice's billing guidelines for specific codes.</p>
                {reportData.billing_descriptions.map((b, i) => (
                  <div key={i} className="cpt-item">
                    <div className="cpt-code">{b.practice_code || 'unmapped'}</div>
                    <div>
                      <strong>{b.category}</strong>
                      <span className="cpt-units"> [{b.service_type}]</span>
                      {b.units && <span className="cpt-units"> ({b.units} units)</span>}
                      <p>{b.justification}</p>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
          <button onClick={handleFinish} className="upload-another-btn">Upload Another Video</button>
        </div>
      </div>
    );
  }

  return null;
}

export default ThankYouModal;
