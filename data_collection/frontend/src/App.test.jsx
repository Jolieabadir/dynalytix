/**
 * App boot: the profile gate, the validation gate, the nav, the self-upload
 * flag, and the landing rule.
 *
 * The important negatives: with `self_upload_enabled` off (the default) a
 * non-admin never sees upload / "My videos"; an unvalidated rater sees
 * "Waiting for validation", never the queue; the pose chip is not mounted in
 * the rating view.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

vi.mock('./api/auth', () => ({
  getSession: vi.fn(),
  onAuthChange: vi.fn(() => () => {}),
  signOut: vi.fn(),
  isAuthConfigured: vi.fn(() => true),
  authHeader: vi.fn(async () => ({})),
  requireAccessToken: vi.fn(),
  refreshSession: vi.fn(),
  NotSignedInError: class extends Error {},
}));

vi.mock('./api/client', () => ({
  getConfig: vi.fn(),
  getMyProfile: vi.fn(),
  createMyProfile: vi.fn(),
  getMyAssignments: vi.fn(),
  getVideoPlaybackUrl: vi.fn(),
  exportVideo: vi.fn(),
  getExportDownloadUrl: vi.fn(),
  adminListVideos: vi.fn(async () => []),
  adminListRaters: vi.fn(async () => []),
  getMoves: vi.fn(async () => []),
  getHolds: vi.fn(async () => []),
  getVideo: vi.fn(),
  getPoseStatus: vi.fn(),
  fetchPoseCsvText: vi.fn(),
  retryPose: vi.fn(),
  updateMove: vi.fn(),
  getEnvironmentForMove: vi.fn(),
  getOutcomeForMove: vi.fn(),
  startAssignment: vi.fn(),
  completeAssignment: vi.fn(),
}));

// The upload screen pulls in the pose extractor and the hold detector; a stub
// that says what the real one says is enough to prove the flow is reachable.
vi.mock('./components/VideoUpload', () => ({
  default: () => (
    <div className="video-upload">
      <h2>Upload Climbing Video</h2>
    </div>
  ),
}));
vi.mock('./components/VideoPlayer', () => ({ default: () => <div /> }));
vi.mock('./components/TaggingMode', () => ({ default: () => <div /> }));
// The chip's own behaviour is covered in PoseStatusChip.test; here only where
// App mounts it matters.
vi.mock('./components/PoseStatusChip', () => ({ default: () => <div data-testid="pose-chip-stub" /> }));
vi.mock('./components/RatingView', () => ({ default: () => <div data-testid="rating-view-stub" /> }));

import App from './App';
import useStore from './store/useStore';
import { getSession, onAuthChange } from './api/auth';
import { getConfig, getMyProfile, getMyAssignments, createMyProfile } from './api/client';

const SESSION = { access_token: 'tok', user: { id: 'u1', email: 'labeler@dynalytix.test' } };
const CONFIG = { version: '3.1.0', tag_types: {}, body_parts: [], sides: [], self_upload_enabled: false };
const PROFILE = { user_id: 'u1', display_name: 'Labeler', is_validated: true, is_admin: false };
const ASSIGNMENT_ITEM = {
  assignment: { id: 1, video_id: 2, status: 'assigned', assigned_at: '2026-09-20T00:00:00Z' },
  video: { id: 2, filename: 'v.mp4' },
  move_count: 3,
};

beforeEach(() => {
  useStore.getState().resetForSignOut();
  useStore.setState({ config: null });
  vi.mocked(getSession).mockResolvedValue(SESSION);
  vi.mocked(getConfig).mockResolvedValue(CONFIG);
  vi.mocked(getMyProfile).mockResolvedValue(PROFILE);
  vi.mocked(getMyAssignments).mockResolvedValue([]);
});

describe('App — self-upload flag off (default)', () => {
  it('lands a validated non-admin with no assignments on My queue, with no upload, My videos or Admin', async () => {
    render(<App />);

    expect(await screen.findByRole('heading', { name: 'My queue' })).toBeInTheDocument();
    expect(await screen.findByText(/Nothing assigned yet/)).toBeInTheDocument();
    const nav = screen.getByRole('navigation', { name: 'Sections' });
    expect(nav).toHaveTextContent('My queue');
    expect(nav).not.toHaveTextContent('My videos');
    expect(nav).not.toHaveTextContent('Upload');
    expect(nav).not.toHaveTextContent('Admin');
    expect(screen.queryByText('Upload Climbing Video')).not.toBeInTheDocument();
    await waitFor(() => expect(useStore.getState().view).toBe('queue'));
    expect(useStore.getState().profile).toEqual(PROFILE);
    // The validated badge replaces the old tier badge.
    expect(screen.getByTestId('validated-badge')).toHaveTextContent('validated');
  });

  it('never renders the upload flow for a non-admin, even if the view says videos', async () => {
    render(<App />);
    await screen.findByRole('heading', { name: 'My queue' });

    act(() => useStore.getState().setView('videos'));

    await waitFor(() => expect(useStore.getState().view).toBe('queue'));
    expect(screen.queryByText('Upload Climbing Video')).not.toBeInTheDocument();
  });

  it('still lets an admin upload and prep, under "Upload & prep"', async () => {
    vi.mocked(getMyProfile).mockResolvedValue({ ...PROFILE, is_admin: true });
    const user = userEvent.setup();
    render(<App />);

    const nav = await screen.findByRole('navigation', { name: 'Sections' });
    expect(nav).toHaveTextContent('Admin');
    // An admin with an empty queue lands on the upload/prep flow.
    expect(await screen.findByText('Upload Climbing Video')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'My queue' }));
    await user.click(screen.getByRole('button', { name: 'Upload & prep' }));
    expect(await screen.findByText('Upload Climbing Video')).toBeInTheDocument();
  });
});

describe('App — self-upload flag on', () => {
  it('shows the community "My videos" flow to a non-admin and lands there when the queue is empty', async () => {
    vi.mocked(getConfig).mockResolvedValue({ ...CONFIG, self_upload_enabled: true });
    render(<App />);

    expect(await screen.findByText('Upload Climbing Video')).toBeInTheDocument();
    const nav = screen.getByRole('navigation', { name: 'Sections' });
    expect(nav).toHaveTextContent('My videos');
    expect(nav).not.toHaveTextContent('Admin');
    expect(screen.getByRole('button', { name: 'My videos' })).toHaveAttribute('aria-current', 'page');
  });
});

describe('App — validation gate', () => {
  it('shows "Waiting for validation" to an unvalidated non-admin instead of the queue', async () => {
    vi.mocked(getMyProfile).mockResolvedValue({ ...PROFILE, is_validated: false });
    render(<App />);

    const waiting = await screen.findByTestId('waiting-for-validation');
    expect(waiting).toHaveTextContent('Waiting for validation');
    expect(waiting).toHaveTextContent(/an admin needs to approve your rater profile/i);
    expect(screen.queryByRole('heading', { name: 'My queue' })).not.toBeInTheDocument();
    expect(screen.queryByText('Upload Climbing Video')).not.toBeInTheDocument();
    expect(screen.queryByTestId('validated-badge')).not.toBeInTheDocument();
  });

  it('does not gate an admin, validated or not', async () => {
    vi.mocked(getMyProfile).mockResolvedValue({ ...PROFILE, is_validated: false, is_admin: true });
    const user = userEvent.setup();
    render(<App />);

    await user.click(await screen.findByRole('button', { name: 'My queue' }));
    expect(await screen.findByRole('heading', { name: 'My queue' })).toBeInTheDocument();
    expect(screen.queryByTestId('waiting-for-validation')).not.toBeInTheDocument();
  });
});

describe('App — profile gate', () => {
  it('blocks on the profile form when GET /api/me/profile is 404, then waits for validation', async () => {
    vi.mocked(getMyProfile).mockResolvedValue(null);
    // A brand-new profile is never validated.
    vi.mocked(createMyProfile).mockResolvedValue({ ...PROFILE, is_validated: false });
    const user = userEvent.setup();
    render(<App />);

    expect(await screen.findByTestId('profile-form')).toBeInTheDocument();
    expect(screen.queryByText('Upload Climbing Video')).not.toBeInTheDocument();
    expect(screen.queryByRole('navigation')).not.toBeInTheDocument();

    await user.type(screen.getByLabelText('Display name'), 'Labeler');
    await user.click(screen.getByRole('button', { name: 'Save profile' }));

    expect(await screen.findByTestId('waiting-for-validation')).toBeInTheDocument();
  });
});

describe('App — landing and admin', () => {
  it('lands a rater with an assignment on My queue', async () => {
    vi.mocked(getMyAssignments).mockResolvedValue([ASSIGNMENT_ITEM]);
    render(<App />);

    expect(await screen.findByText('v.mp4')).toBeInTheDocument();
    expect(useStore.getState().view).toBe('queue');
    expect(screen.queryByText('Upload Climbing Video')).not.toBeInTheDocument();
  });

  it('mounts the pose chip outside the rating view only', async () => {
    vi.mocked(getMyAssignments).mockResolvedValue([ASSIGNMENT_ITEM]);
    const user = userEvent.setup();
    render(<App />);

    await screen.findByText('v.mp4');
    expect(screen.getByTestId('pose-chip-stub')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Rate' }));
    expect(await screen.findByTestId('rating-view-stub')).toBeInTheDocument();
    expect(screen.queryByTestId('pose-chip-stub')).not.toBeInTheDocument();
  });

  it('shows the Admin tab only for an admin profile, and it opens the admin view', async () => {
    vi.mocked(getMyProfile).mockResolvedValue({ ...PROFILE, is_admin: true });
    const user = userEvent.setup();
    render(<App />);

    const adminTab = await screen.findByRole('button', { name: 'Admin' });
    await user.click(adminTab);

    await waitFor(() => expect(useStore.getState().view).toBe('admin'));
    expect(await screen.findByRole('heading', { name: 'Admin' })).toBeInTheDocument();
  });
});

describe('App — dead session clears the previous user', () => {
  it('resets video-scoped state and the profile when onAuthChange reports no session', async () => {
    let authCallback;
    vi.mocked(onAuthChange).mockImplementation((cb) => {
      authCallback = cb;
      return () => {};
    });
    render(<App />);
    expect(await screen.findByRole('heading', { name: 'My queue' })).toBeInTheDocument();
    expect(useStore.getState().profile).toEqual(PROFILE);

    // User A had a video open with moves, holds and labels in the store.
    useStore.setState({
      currentVideo: { id: 7, filename: 'a.mp4' },
      moves: [{ id: 1, video_id: 7 }],
      holds: [{ id: 3, video_id: 7 }],
      frameTags: [{ id: 9, move_id: 1 }],
      assignments: [{ assignment: { id: 1 }, video: { id: 7 } }],
      currentAssignment: { id: 1 },
      view: 'queue',
    });

    // The session dies (expired, or signed out in another tab).
    act(() => authCallback(null));

    await waitFor(() => expect(useStore.getState().session).toBeNull());
    const state = useStore.getState();
    expect(state.currentVideo).toBeNull();
    expect(state.moves).toEqual([]);
    expect(state.holds).toEqual([]);
    expect(state.frameTags).toEqual([]);
    expect(state.assignments).toEqual([]);
    expect(state.currentAssignment).toBeNull();
    expect(state.profile).toBeNull();
    expect(state.config).toBeNull();
    expect(state.view).toBe('videos');
    expect(screen.queryByRole('heading', { name: 'My queue' })).not.toBeInTheDocument();

    // User B signs in on the same tab: the gate runs again for B, with a clean store.
    const PROFILE_B = { user_id: 'u2', display_name: 'Other', is_validated: true, is_admin: false };
    vi.mocked(getMyProfile).mockResolvedValue(PROFILE_B);
    act(() => authCallback({ access_token: 'tok2', user: { id: 'u2', email: 'b@dynalytix.test' } }));

    await waitFor(() => expect(useStore.getState().profile).toEqual(PROFILE_B));
    expect(useStore.getState().moves).toEqual([]);
    expect(useStore.getState().holds).toEqual([]);
    expect(useStore.getState().currentVideo).toBeNull();
  });
});
