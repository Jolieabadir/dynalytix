/**
 * Main App — Movement Assessment Tool
 *
 * Three-state flow:
 * 1. Upload (front + side videos)
 * 2. Review (both videos with playback controls, scoring runs in background)
 * 3. Results (score, criteria, billing, disclaimer)
 *
 * Navigation: User controls transitions via buttons (no auto-transition)
 */
import { useEffect, useState } from 'react';
import useStore from './store/useStore';
import { getConfig, scoreDualAngle, exportVideo, getFMSProviderReport } from './api/client';
import VideoUpload from './components/VideoUpload';
import DualVideoReview from './components/DualVideoReview';
import AssessmentResults from './components/AssessmentResults';
import './App.css';

function App() {
  const { config, setConfig, assessmentPhase, frontVideoId, sideVideoId, resetDualAngle } = useStore();
  const [appState, setAppState] = useState('upload'); // 'upload' | 'review' | 'results'
  const [scoringResults, setScoringResults] = useState(null);
  const [scoringError, setScoringError] = useState(null);
  const [isScoring, setIsScoring] = useState(false);

  useEffect(() => {
    const loadConfig = async () => {
      try {
        const configData = await getConfig();
        setConfig(configData);
      } catch (error) {
        console.error('Failed to load config:', error);
      }
    };
    loadConfig();
  }, [setConfig]);

  // When assessmentPhase becomes 'complete', transition to review + auto-score
  useEffect(() => {
    if (assessmentPhase === 'complete' && appState === 'upload') {
      setAppState('review');
      runAutoScore();
    }
  }, [assessmentPhase]);

  const runAutoScore = async () => {
    setIsScoring(true);
    setScoringError(null);
    try {
      // Export both videos (triggers pose CSV creation + single-angle auto-score)
      const exportPromises = [];
      const currentFrontVideoId = useStore.getState().frontVideoId;
      const currentSideVideoId = useStore.getState().sideVideoId;

      if (currentFrontVideoId) exportPromises.push(exportVideo(currentFrontVideoId));
      if (currentSideVideoId && currentSideVideoId !== currentFrontVideoId) {
        exportPromises.push(exportVideo(currentSideVideoId));
      }
      await Promise.all(exportPromises);

      // Run dual-angle scoring if both views available
      let results = null;
      if (currentFrontVideoId && currentSideVideoId) {
        results = await scoreDualAngle(currentFrontVideoId, currentSideVideoId);
      } else {
        // Single-angle — fetch the report from the single video
        const videoId = currentFrontVideoId || currentSideVideoId;
        try {
          results = await getFMSProviderReport(videoId);
        } catch (e) {
          console.error('Single-angle report fetch failed:', e);
        }
      }

      setScoringResults(results);
      // Do NOT auto-transition to results — stay on review screen
      // User will click "View Results" when ready
    } catch (err) {
      console.error('Auto-scoring failed:', err);
      setScoringError(err.message || 'Scoring failed');
      // Stay on review screen — user can still view available results
    } finally {
      setIsScoring(false);
    }
  };

  // Navigation handlers
  const handleViewResults = () => {
    setAppState('results');
  };

  const handleBackToUpload = () => {
    resetDualAngle();
    setScoringResults(null);
    setScoringError(null);
    setAppState('upload');
  };

  const handleBackToReview = () => {
    setAppState('review');
  };

  const handleStartNew = () => {
    resetDualAngle();
    setScoringResults(null);
    setScoringError(null);
    setAppState('upload');
  };

  if (!config) {
    return (
      <div className="loading">
        <h2>Loading Dynalytix...</h2>
      </div>
    );
  }

  return (
    <div className="app">
      <header className="app-header">
        <h1>Dynalytix</h1>
        <p>Movement Assessment</p>
      </header>

      {appState === 'upload' && <VideoUpload />}

      {appState === 'review' && (
        <DualVideoReview
          isScoring={isScoring}
          scoringError={scoringError}
          scoringComplete={scoringResults !== null}
          onViewResults={handleViewResults}
          onBackToUpload={handleBackToUpload}
        />
      )}

      {appState === 'results' && (
        <AssessmentResults
          results={scoringResults}
          error={scoringError}
          frontVideoId={frontVideoId}
          sideVideoId={sideVideoId}
          onStartNew={handleStartNew}
          onBackToReview={handleBackToReview}
        />
      )}
    </div>
  );
}

export default App;
