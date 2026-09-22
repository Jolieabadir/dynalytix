/**
 * Main App component.
 *
 * Boot order matters here. /api/config now requires a bearer token, so the
 * config load has to wait for a session — otherwise a signed-out user 401s and
 * sits on a loading screen with no way forward, which is exactly what the old
 * build did.
 *
 *   no session  → AuthGate
 *   session     → load config → load profile (404 → ProfileGate)
 *               → load assignments → land on My queue if any, else My videos
 *
 * Dataset A adds the profile gate, the nav, "My queue" + the rating view, and
 * the Admin view. "My videos" is the Dataset B flow and is unchanged.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import useStore from './store/useStore';
import {
  getConfig,
  getMyProfile,
  getMyAssignments,
  getVideoPlaybackUrl,
  getHolds,
} from './api/client';
import { exportVideo, getExportDownloadUrl } from './api/client';
import { getSession, onAuthChange, signOut } from './api/auth';
import AuthGate from './components/AuthGate';
import ProfileGate from './components/ProfileGate';
import AppNav from './components/AppNav';
import MyQueue from './components/MyQueue';
import RatingView from './components/RatingView';
import AdminView from './components/AdminView';
import VideoMetadataPanel from './components/VideoMetadataPanel';
import VideoUpload from './components/VideoUpload';
import VideoPlayer from './components/VideoPlayer';
import MovesList from './components/MovesList';
import MoveForm from './components/MoveForm';
import TaggingMode from './components/TaggingMode';
import ThankYouModal from './components/ThankYouModal';
import ProgressStrip from './components/ProgressStrip';
import PoseStatusChip from './components/PoseStatusChip';
import OnboardingBanner, { BANNER_DEFINE, BANNER_CAPTURE } from './components/OnboardingBanner';
import InstallPrompt from './components/InstallPrompt';
import {
  rememberSession,
  readSession,
  forgetSession,
  restoreSession,
} from './services/sessionResume';
import './App.css';

function App() {
  const mode = useStore((s) => s.mode);
  const config = useStore((s) => s.config);
  const setConfig = useStore((s) => s.setConfig);
  const session = useStore((s) => s.session);
  const setSession = useStore((s) => s.setSession);
  const resetForSignOut = useStore((s) => s.resetForSignOut);
  const profile = useStore((s) => s.profile);
  const setProfile = useStore((s) => s.setProfile);
  const setAssignments = useStore((s) => s.setAssignments);
  const view = useStore((s) => s.view);
  const setView = useStore((s) => s.setView);
  const setCurrentAssignment = useStore((s) => s.setCurrentAssignment);
  const resetVideoState = useStore((s) => s.resetVideoState);
  const setCurrentVideo = useStore((s) => s.setCurrentVideo);
  const setVideoPlaybackUrl = useStore((s) => s.setVideoPlaybackUrl);
  const setHolds = useStore((s) => s.setHolds);

  const [authChecked, setAuthChecked] = useState(false);
  const [configError, setConfigError] = useState(null);
  // 'loading' | 'missing' (404 → gate) | 'ready' | 'error'
  const [profileState, setProfileState] = useState('loading');
  const [profileError, setProfileError] = useState(null);
  const [landed, setLanded] = useState(false);
  // Safari can evict this page at any moment. A ref, not state: this only
  // guards the effect from running twice and must not cause a render.
  const resumeStarted = useRef(false);

  // Read the persisted session once, then follow it.
  useEffect(() => {
    let active = true;

    getSession()
      .then((s) => {
        if (active) {
          setSession(s);
          setAuthChecked(true);
        }
      })
      .catch(() => active && setAuthChecked(true));

    const unsubscribe = onAuthChange((s) => {
      if (!s) {
        // Expired or signed out elsewhere. Clear everything video-scoped the
        // same way the sign-out button does, so a different user signing in
        // on this tab never inherits the previous user's moves, holds,
        // labels, profile or queue. The next sign-in re-runs the gate.
        forgetSession();
        resetForSignOut();
        setConfig(null);
        setProfileState('loading');
        setLanded(false);
      } else {
        setSession(s);
      }
      setAuthChecked(true);
    });

    return () => {
      active = false;
      unsubscribe();
    };
  }, [setSession, resetForSignOut, setConfig]);

  // Config needs the token, so it waits for the session.
  useEffect(() => {
    if (!session) return;
    let active = true;

    getConfig()
      .then((data) => active && setConfig(data))
      .catch((error) => {
        console.error('Failed to load config:', error);
        if (active) {
          setConfigError(
            error.response?.data?.detail ||
              error.message ||
              'Could not load the labeling taxonomy from the server.'
          );
        }
      });

    return () => {
      active = false;
    };
  }, [session, setConfig]);

  // Profile: the gate. Waits for the session like config does.
  useEffect(() => {
    // Signed out: handleSignOut already reset profileState/landed.
    if (!session) return;
    let active = true;
    getMyProfile()
      .then((p) => {
        if (!active) return;
        if (p) {
          setProfile(p);
          setProfileState('ready');
        } else {
          setProfileState('missing');
        }
      })
      .catch((error) => {
        console.error('Failed to load profile:', error);
        if (active) {
          setProfileError(error.response?.data?.detail || error.message || 'Could not load your profile.');
          setProfileState('error');
        }
      });
    return () => {
      active = false;
    };
  }, [session, setProfile]);

  // Landing: once the profile exists, load the queue; a rater with at least
  // one assignment lands on it, everyone else on My videos (Dataset B).
  useEffect(() => {
    if (profileState !== 'ready' || landed || resumeStarted.current) return;
    // A page that was evicted mid-session resumes instead of landing.
    if (readSession()) return;
    let active = true;
    getMyAssignments()
      .then((items) => {
        if (!active) return;
        setAssignments(items);
        if (items.length > 0) setView('queue');
      })
      .catch((error) => {
        console.warn('Could not load assignments:', error);
      })
      .finally(() => active && setLanded(true));
    return () => {
      active = false;
    };
  }, [profileState, landed, setAssignments, setView]);

  /**
   * Remember which video is open, so an evicted page can come back to it.
   *
   * Only the pointer is stored — every label is already on the server. See
   * services/sessionResume.
   */
  useEffect(() => {
    if (!session) return;
    const unsubscribe = useStore.subscribe((state) => {
      const videoId = state.currentVideo?.id;
      if (!videoId || state.view === 'admin') {
        rememberSession(null);
        return;
      }
      rememberSession({
        videoId,
        view: state.view,
        assignmentId: state.currentAssignment?.id ?? null,
      });
    });
    return unsubscribe;
  }, [session]);

  /**
   * Rebuild the session the page was in the middle of.
   *
   * Runs once the profile is ready and before landing decides where to put
   * the labeler, so a reload returns to the video rather than the queue. The
   * server is the authority: a video it will not serve is simply forgotten.
   */
  useEffect(() => {
    if (profileState !== 'ready' || landed || resumeStarted.current) return;
    const saved = readSession();
    if (!saved) return;

    let active = true;
    resumeStarted.current = true;
    restoreSession(saved)
      .then((restored) => {
        if (!active || !restored) return;
        resetVideoState();
        setCurrentVideo(restored.video);
        setHolds(restored.holds);
        useStore.getState().setMoves(restored.moves);
        setVideoPlaybackUrl(restored.playbackUrl);
        if (saved.view === 'rating' && saved.assignmentId) {
          setCurrentAssignment({ id: saved.assignmentId, video_id: saved.videoId });
          useStore.getState().setReadOnlyStructure(true);
        }
        setView(saved.view === 'rating' ? 'rating' : 'videos');
        // Already where we want to be; skip the queue landing.
        setLanded(true);
      })
      .catch((error) => {
        console.warn('Could not resume the previous session:', error);
        forgetSession();
      })
      .finally(() => {
        // Nothing to resume any more, whichever way it went.
        if (active) setLanded(true);
      });

    return () => {
      active = false;
    };
  }, [
    profileState,
    landed,
    resetVideoState,
    setCurrentVideo,
    setHolds,
    setVideoPlaybackUrl,
    setCurrentAssignment,
    setView,
  ]);

  const handleSignOut = useCallback(async () => {
    await signOut();
    // Never leave a pointer to this user's video for the next one.
    forgetSession();
    resetForSignOut();
    setConfig(null);
    setProfileState('loading');
    setLanded(false);
  }, [resetForSignOut, setConfig]);

  const handleProfileCreated = useCallback(
    (p) => {
      setProfile(p);
      setProfileState('ready');
    },
    [setProfile]
  );

  /** From My queue: open one assignment in the rating view. */
  const handleOpenAssignment = useCallback(
    ({ assignment, video }) => {
      resetVideoState();
      setCurrentAssignment(assignment);
      setCurrentVideo(video);
      setView('rating');
    },
    [resetVideoState, setCurrentAssignment, setCurrentVideo, setView]
  );

  const handleExitRating = useCallback(() => {
    resetVideoState();
    setView('queue');
  }, [resetVideoState, setView]);

  /**
   * From Admin: open any video in the prep (Define) flow. Nothing of it is in
   * this session, so the holds and a playback URL are fetched the way the
   * upload path would have produced them; the pose rows arrive through
   * usePoseStatus (the header chip polls /status and loads the CSV once the
   * worker is done). Each is best-effort: a missing original still leaves
   * the moves list usable.
   */
  const handleOpenVideoForPrep = useCallback(
    async (video) => {
      resetVideoState();
      setCurrentVideo(video);
      setView('videos');
      const [holds, playbackUrl] = await Promise.all([
        getHolds(video.id).catch((error) => {
          console.warn('Could not load holds for video', video.id, error);
          return [];
        }),
        getVideoPlaybackUrl(video.id).catch((error) => {
          console.warn('No playback URL for video', video.id, error);
          return null;
        }),
      ]);
      // The user may have moved on while these loaded.
      if (useStore.getState().currentVideo?.id !== video.id) return;
      setHolds(holds ?? []);
      setVideoPlaybackUrl(playbackUrl);
    },
    [resetVideoState, setCurrentVideo, setView, setVideoPlaybackUrl, setHolds]
  );

  if (!authChecked) {
    return (
      <div className="loading">
        <h2>Loading Dynalytix…</h2>
      </div>
    );
  }

  if (!session) return <AuthGate />;

  if (configError) {
    return (
      <div className="loading">
        <h2>Dynalytix</h2>
        <div className="error-message">
          <p><strong>Could not load configuration.</strong></p>
          <p>{configError}</p>
          <p>Check that the backend is running and reachable.</p>
        </div>
        <button className="btn-secondary" onClick={handleSignOut}>
          Sign out
        </button>
      </div>
    );
  }

  if (profileState === 'error') {
    return (
      <div className="loading">
        <h2>Dynalytix</h2>
        <div className="error-message">
          <p><strong>Could not load your rater profile.</strong></p>
          <p>{profileError}</p>
        </div>
        <button className="btn-secondary" onClick={handleSignOut}>
          Sign out
        </button>
      </div>
    );
  }

  if (profileState === 'missing') {
    return (
      <ProfileGate
        email={session.user?.email}
        onCreated={handleProfileCreated}
        onSignOut={handleSignOut}
      />
    );
  }

  if (!config || profileState !== 'ready' || !landed) {
    return (
      <div className="loading">
        <h2>Loading Dynalytix…</h2>
      </div>
    );
  }

  let body;
  if (view === 'rating') {
    body = <RatingView onExit={handleExitRating} />;
  } else if (view === 'queue') {
    body = <MyQueue onOpen={handleOpenAssignment} />;
  } else if (view === 'admin' && profile?.is_admin) {
    body = <AdminView onOpenVideo={handleOpenVideoForPrep} />;
  } else {
    body = mode === 'define' ? <DefineMode /> : <TaggingMode />;
  }

  return (
    <div className="app">
      <header className="app-header">
        <div className="app-header-titles">
          <h1>Dynalytix</h1>
          <p>Climbing Movement Data Collection</p>
        </div>
        <AppNav />
        <div className="app-header-account">
          <PoseStatusChip />
          <span className="account-email" title={session.user?.email}>
            {profile?.display_name || session.user?.email}
            {profile?.tier === 'validated' && <span className="tier-badge">validated</span>}
          </span>
          <button type="button" className="signout-btn" onClick={handleSignOut}>
            Sign out
          </button>
        </div>
      </header>

      <InstallPrompt />

      {body}
    </div>
  );
}

/**
 * Define Mode — video on the left, moves list and the labeling panel on the
 * right. The form is a panel rather than a modal so the video and skeleton stay
 * visible and scrubbable while labeling.
 */
function DefineMode() {
  const currentVideo = useStore((s) => s.currentVideo);
  const readOnlyStructure = useStore((s) => s.readOnlyStructure);
  const showMoveForm = useStore((s) => s.showMoveForm);
  const setShowMoveForm = useStore((s) => s.setShowMoveForm);
  const moveStart = useStore((s) => s.moveStart);
  const moveEnd = useStore((s) => s.moveEnd);
  const clearMoveSelection = useStore((s) => s.clearMoveSelection);
  const poseStatus = useStore((s) => s.poseStatus);

  const [showThankYou, setShowThankYou] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [downloadUrl, setDownloadUrl] = useState(null);
  const [exportError, setExportError] = useState(null);

  if (!currentVideo) {
    return <VideoUpload />;
  }

  const poseDone =
    poseStatus?.video_id === currentVideo.id && poseStatus?.pose_status === 'done';
  const exportBlockedReason = poseDone
    ? ''
    : poseStatus?.pose_status === 'failed'
      ? 'Pose extraction failed — retry it from the chip in the header, then export.'
      : 'Export is available once the server has finished extracting the pose.';

  /**
   * Finish & Export: run the export, then resolve the presigned download link
   * and show it. A failed link is not a failed export — the labels are saved
   * either way, and the modal says so.
   */
  const handleFinish = async () => {
    setExporting(true);
    setExportError(null);
    setDownloadUrl(null);
    try {
      await exportVideo(currentVideo.id);
      setShowThankYou(true);
      try {
        setDownloadUrl(await getExportDownloadUrl(currentVideo.id));
      } catch (linkErr) {
        console.warn('Export succeeded but the download link failed:', linkErr);
      }
    } catch (err) {
      console.error('Export failed:', err);
      setExportError(
        err.response?.data?.detail || err.message || 'The export request failed.'
      );
      setShowThankYou(true);
    } finally {
      setExporting(false);
    }
  };

  // "Save & Next Move" clears the current selection and reopens the form for
  // the next one; with the form shut it just clears, ready for [ and ].
  const handleSaveAndNext = () => {
    setShowMoveForm(false);
    clearMoveSelection();
  };

  return (
    <div className="define-mode">
      <ProgressStrip
        onSaveAndNext={handleSaveAndNext}
        onFinish={handleFinish}
        busy={exporting}
        canSaveNext={moveStart !== null || moveEnd !== null || showMoveForm}
        canExport={poseDone}
        exportBlockedReason={exportBlockedReason}
      />

      <VideoMetadataPanel />

      {!readOnlyStructure && <OnboardingBanner id={BANNER_DEFINE} />}
      {/* Capture guidance: touch only, remembered once dismissed. */}
      <OnboardingBanner id={BANNER_CAPTURE} />

      <div className={`main-area ${showMoveForm ? 'with-panel' : ''}`}>
        <VideoPlayer />
        <div className="side-column">
          {showMoveForm && !readOnlyStructure ? (
            <MoveForm />
          ) : (
            <MovesList readOnly={readOnlyStructure} />
          )}
        </div>
      </div>

      <ThankYouModal
        show={showThankYou}
        downloadUrl={downloadUrl}
        exportError={exportError}
        onClose={() => {
          setShowThankYou(false);
          setDownloadUrl(null);
          setExportError(null);
        }}
      />
    </div>
  );
}

export default App;
