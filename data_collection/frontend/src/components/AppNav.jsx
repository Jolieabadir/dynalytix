/**
 * AppNav — the top-level tabs.
 *
 * "My queue" is the rater's assignment list. "Admin" only exists for a
 * profile with `is_admin`. The videos flow (upload + prep) is "Upload & prep"
 * for an admin; for anyone else it exists only when the server's
 * `self_upload_enabled` flag is on, as the community "My videos" flow.
 *
 * Switching tabs leaves the rating view, which drops its video-scoped state
 * so nothing from one assignment lingers into the next.
 */
import useStore from '../store/useStore';

const TABS = [
  { id: 'videos', label: 'My videos', adminLabel: 'Upload & prep', needsVideos: true },
  { id: 'queue', label: 'My queue' },
  { id: 'admin', label: 'Admin', adminOnly: true },
];

function AppNav() {
  const view = useStore((s) => s.view);
  const setView = useStore((s) => s.setView);
  const profile = useStore((s) => s.profile);
  const assignments = useStore((s) => s.assignments);
  const resetVideoState = useStore((s) => s.resetVideoState);
  const config = useStore((s) => s.config);

  const isAdmin = Boolean(profile?.is_admin);
  const canUseVideos = isAdmin || config?.self_upload_enabled === true;
  // App collapses 'videos' to 'queue' for a user without the videos flow.
  const shownView = view === 'videos' && !canUseVideos ? 'queue' : view;
  const openCount = assignments.filter((a) => a.assignment?.status !== 'done').length;

  const go = (id) => {
    if (id === view) return;
    // The rating view owns the video-scoped state; leaving it clears it.
    // The videos flow keeps its upload alive across a tab switch.
    if (view === 'rating') resetVideoState();
    setView(id);
  };

  return (
    <nav className="app-nav" aria-label="Sections">
      {TABS.filter((t) => (!t.adminOnly || isAdmin) && (!t.needsVideos || canUseVideos)).map((tab) => {
        const active = shownView === tab.id || (tab.id === 'queue' && shownView === 'rating');
        return (
          <button
            key={tab.id}
            type="button"
            className={`app-nav-tab ${active ? 'active' : ''}`}
            aria-current={active ? 'page' : undefined}
            onClick={() => go(tab.id)}
          >
            {isAdmin && tab.adminLabel ? tab.adminLabel : tab.label}
            {tab.id === 'queue' && openCount > 0 && (
              <span className="app-nav-badge" aria-label={`${openCount} open`}>
                {openCount}
              </span>
            )}
          </button>
        );
      })}
    </nav>
  );
}

export default AppNav;
