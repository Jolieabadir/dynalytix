/**
 * Main App component.
 */
import { useEffect, useState } from 'react';
import useStore from './store/useStore';
import { getConfig } from './api/client';
import { exportVideo } from './api/ExportService';
import VideoUpload from './components/VideoUpload';
import VideoPlayer from './components/VideoPlayer';
import MovesList from './components/MovesList';
import MoveForm from './components/MoveForm';
import TaggingMode from './components/TaggingMode';
import ThankYouModal from './components/ThankYouModal';
import DoneButton from './components/DoneButton';
import './App.css';

function App() {
  const { mode, config, setConfig } = useStore();

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
        <p>Movement Data Collection</p>
      </header>

      {mode === 'define' ? <DefineMode /> : <TaggingMode />}
    </div>
  );
}

/**
 * Define Mode - Main view for creating moves
 */
function DefineMode() {
  const { currentVideo } = useStore();
  const [showThankYou, setShowThankYou] = useState(false);
  const [exporting, setExporting] = useState(false);

  if (!currentVideo) {
    return <VideoUpload />;
  }

  const handleDone = async () => {
    setExporting(true);
    try {
      await exportVideo(currentVideo.id);
      setShowThankYou(true);
    } catch (err) {
      console.error('Export failed:', err);
      // Still show thank you - data is saved in db
      setShowThankYou(true);
    } finally {
      setExporting(false);
    }
  };

  return (
    <div className="define-mode">
      <div className="define-header">
        <DoneButton onClick={handleDone} disabled={exporting} />
        {exporting && <span className="exporting-text">Exporting...</span>}
      </div>
      <div className="main-area">
        <VideoPlayer />
        <MovesList />
      </div>
      <MoveForm />
      <ThankYouModal show={showThankYou} onClose={() => setShowThankYou(false)} videoId={currentVideo?.id} />
    </div>
  );
}

export default App;
