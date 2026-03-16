/**
 * AssessmentResults — Displays scoring results after auto-scoring completes.
 */
import { useState } from 'react';

const SCORE_LABELS = {
  3: { label: 'Perfect', color: '#22c55e', description: 'Movement performed correctly without compensation' },
  2: { label: 'Compensation', color: '#f59e0b', description: 'Movement completed with compensation patterns' },
  1: { label: 'Cannot Complete', color: '#ef4444', description: 'Unable to complete the movement pattern' },
  0: { label: 'Pain', color: '#991b1b', description: 'Pain reported during movement' },
};

function AssessmentResults({ results, error, frontVideoId, sideVideoId, onStartNew }) {
  const [reportTab, setReportTab] = useState('provider'); // 'patient' | 'provider'

  if (error && !results) {
    return (
      <div className="assessment-results">
        <div className="results-error">
          <h2>Scoring Error</h2>
          <p>{error}</p>
          <button className="primary-button" onClick={onStartNew}>Start New Assessment</button>
        </div>
      </div>
    );
  }

  if (!results) {
    return (
      <div className="assessment-results">
        <div className="results-loading">
          <div className="spinner" />
          <p>Loading results...</p>
        </div>
      </div>
    );
  }

  const score = results.score ?? 0;
  const scoreInfo = SCORE_LABELS[score] || SCORE_LABELS[1];
  const criteria = results.criteria || [];
  const billingDescriptions = results.billing_descriptions || [];
  const viewSources = results.view_sources || {};
  const isDualAngle = results.dual_angle === true;
  const disclaimer = results.disclaimer || '';

  // Extract bilateral differences from criteria or results
  const bilateralDiffs = results.bilateral_differences || results.merged?.left_right_differences || {};

  return (
    <div className="assessment-results">
      {/* Score Header */}
      <div className="score-header" style={{ borderColor: scoreInfo.color }}>
        <div className="score-circle" style={{ backgroundColor: scoreInfo.color }}>
          <span className="score-number">{score}</span>
          <span className="score-max">/3</span>
        </div>
        <div className="score-info">
          <h2>{scoreInfo.label}</h2>
          <p>{scoreInfo.description}</p>
          {isDualAngle && (
            <div className="dual-scores">
              {results.front_score != null && (
                <span className="sub-score">Front: {results.front_score}/3</span>
              )}
              {results.side_score != null && (
                <span className="sub-score">Side: {results.side_score}/3</span>
              )}
              <span className="sub-score merged">Merged: {score}/3</span>
            </div>
          )}
        </div>
      </div>

      {/* Tab buttons */}
      <div className="report-tabs">
        <button
          className={`tab-button ${reportTab === 'provider' ? 'active' : ''}`}
          onClick={() => setReportTab('provider')}
        >
          Provider Report
        </button>
        <button
          className={`tab-button ${reportTab === 'patient' ? 'active' : ''}`}
          onClick={() => setReportTab('patient')}
        >
          Patient Report
        </button>
      </div>

      {/* Scoring Criteria */}
      <div className="criteria-section">
        <h3>Scoring Criteria</h3>
        {criteria.length === 0 ? (
          <p className="no-criteria">No criteria available</p>
        ) : (
          criteria.map((c, i) => (
            <div key={i} className={`criterion-card ${c.passed ? 'pass' : 'fail'}`}>
              <div className="criterion-header">
                <span className={`criterion-icon ${c.passed ? 'pass' : 'fail'}`}>
                  {c.passed ? '\u2713' : '\u2717'}
                </span>
                <strong>{c.name}</strong>
                {c.value != null && c.threshold != null && (
                  <span className="criterion-values">
                    — {typeof c.value === 'number' ? c.value.toFixed(1) : c.value}°
                    (threshold: {typeof c.threshold === 'number' ? c.threshold.toFixed(1) : c.threshold}°)
                  </span>
                )}
              </div>
              <p className="criterion-detail">{c.detail}</p>
              {viewSources[c.name] && (
                <span className="view-source-tag">{viewSources[c.name]}</span>
              )}
            </div>
          ))
        )}
      </div>

      {/* Bilateral Differences */}
      {Object.keys(bilateralDiffs).length > 0 && (
        <div className="bilateral-section">
          <h3>Bilateral Differences</h3>
          <table className="bilateral-table">
            <thead>
              <tr>
                <th>Joint</th>
                <th>Difference</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(bilateralDiffs).map(([joint, diff]) => (
                <tr key={joint} className={Math.abs(diff) > 10 ? 'asymmetry' : ''}>
                  <td>{joint}</td>
                  <td>{diff > 0 ? '+' : ''}{typeof diff === 'number' ? diff.toFixed(1) : diff}°</td>
                  <td>{Math.abs(diff) > 10 ? 'ASYMMETRY' : ''}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Billing Categories (provider tab only) */}
      {reportTab === 'provider' && billingDescriptions.length > 0 && (
        <div className="billing-section">
          <h3>Billing Categories</h3>
          <p className="billing-disclaimer">
            Billing categories are suggestions. The treating provider selects appropriate codes.
          </p>
          {billingDescriptions.map((b, i) => (
            <div key={i} className="billing-item">
              <div className="billing-category">{b.category}</div>
              <div className="billing-details">
                <span className="billing-type">{b.service_type}</span>
                {b.units && <span className="billing-units">({b.units} units)</span>}
                <p>{b.justification}</p>
                {b.practice_code ? (
                  <span className="billing-code mapped">Code: {b.practice_code}</span>
                ) : (
                  <span className="billing-code unmapped">Code: Mapped on EHR sync</span>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Disclaimer */}
      {disclaimer && (
        <div className="disclaimer-section">
          <p>{disclaimer}</p>
        </div>
      )}

      {/* Actions */}
      <div className="results-actions">
        <button className="primary-button" onClick={onStartNew}>
          Start New Assessment
        </button>
      </div>
    </div>
  );
}

export default AssessmentResults;
