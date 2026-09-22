/**
 * AppNav — the top-level tabs.
 *
 * "My videos" is the existing Dataset B self-upload flow and stays exactly
 * as it was. "My queue" is the rater's assignment list (Dataset A). "Admin"
 * only exists for a profile with `is_admin`.
 *
 * Switching tabs leaves the rating view, which drops its video-scoped state
 * so nothing from one assignment lingers into the next.
 */
import useStore from '../store/useStore';

const TABS = [
  { id: 'videos', label: 'My videos' },
  { id: 'queue', label: 'My queue' },
  { id: 'admin', label: 'Admin', adminOnly: true },
];

function AppNav() {
  const view = useStore((s) => s.view);
  const setView = useStore((s) => s.setView);
  const profile = useStore((s) => s.profile);
  const assignments = useStore((s) => s.assignments);
  const resetVideoState = useStore((s) => s.resetVideoState);

  const isAdmin = Boolean(profile?.is_admin);
  const openCount = assignments.filter((a) => a.assignment?.status !== 'done').length;

  const go = (id) => {
    if (id === view) return;
    // The rating view owns the video-scoped state; leaving it clears it.
    // The Dataset B flow keeps its upload alive across a tab switch.
    if (view === 'rating') resetVideoState();
    setView(id);
  };

  return (
    <nav className="app-nav" aria-label="Sections">
      {TABS.filter((t) => !t.adminOnly || isAdmin).map((tab) => {
        const active = view === tab.id || (tab.id === 'queue' && view === 'rating');
        return (
          <button
            key={tab.id}
            type="button"
            className={`app-nav-tab ${active ? 'active' : ''}`}
            aria-current={active ? 'page' : undefined}
            onClick={() => go(tab.id)}
          >
            {tab.label}
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
