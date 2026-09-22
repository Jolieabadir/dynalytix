/**
 * App boot for Dataset A: the profile gate, the nav, and the landing rule.
 *
 * The important negative: a non-admin with no assignments must land in the
 * Dataset B flow with no Admin tab — exactly the app as it was.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
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
  getVideoCsvText: vi.fn(),
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

import App from './App';
import useStore from './store/useStore';
import { getSession } from './api/auth';
import { getConfig, getMyProfile, getMyAssignments, createMyProfile } from './api/client';

const SESSION = { access_token: 'tok', user: { id: 'u1', email: 'labeler@dynalytix.test' } };
const CONFIG = { version: '3.1.0', tag_types: {}, body_parts: [], sides: [] };
const PROFILE = { user_id: 'u1', display_name: 'Labeler', tier: 'open', is_admin: false };

beforeEach(() => {
  useStore.getState().resetForSignOut();
  useStore.setState({ config: null });
  vi.mocked(getSession).mockResolvedValue(SESSION);
  vi.mocked(getConfig).mockResolvedValue(CONFIG);
  vi.mocked(getMyProfile).mockResolvedValue(PROFILE);
  vi.mocked(getMyAssignments).mockResolvedValue([]);
});

describe('App — Dataset B unchanged for a plain user', () => {
  it('lands a non-admin with no assignments on My videos, with no Admin tab', async () => {
    render(<App />);

    expect(await screen.findByText('Upload Climbing Video')).toBeInTheDocument();
    const nav = screen.getByRole('navigation', { name: 'Sections' });
    expect(nav).toHaveTextContent('My videos');
    expect(nav).toHaveTextContent('My queue');
    expect(nav).not.toHaveTextContent('Admin');
    expect(screen.getByRole('button', { name: 'My videos' })).toHaveAttribute('aria-current', 'page');
    expect(useStore.getState().view).toBe('videos');
    expect(useStore.getState().profile).toEqual(PROFILE);
  });
});

describe('App — profile gate', () => {
  it('blocks on the profile form when GET /api/me/profile is 404, then continues', async () => {
    vi.mocked(getMyProfile).mockResolvedValue(null);
    vi.mocked(createMyProfile).mockResolvedValue(PROFILE);
    const user = userEvent.setup();
    render(<App />);

    expect(await screen.findByTestId('profile-form')).toBeInTheDocument();
    expect(screen.queryByText('Upload Climbing Video')).not.toBeInTheDocument();
    expect(screen.queryByRole('navigation')).not.toBeInTheDocument();

    await user.type(screen.getByLabelText('Display name'), 'Labeler');
    await user.click(screen.getByRole('button', { name: 'Save profile' }));

    expect(await screen.findByText('Upload Climbing Video')).toBeInTheDocument();
  });
});

describe('App — landing and admin', () => {
  it('lands a rater with an assignment on My queue', async () => {
    vi.mocked(getMyAssignments).mockResolvedValue([
      {
        assignment: { id: 1, video_id: 2, cohort: 'validated', status: 'assigned', assigned_at: '2026-09-20T00:00:00Z' },
        video: { id: 2, filename: 'v.mp4' },
        move_count: 3,
      },
    ]);
    render(<App />);

    expect(await screen.findByText('v.mp4')).toBeInTheDocument();
    expect(useStore.getState().view).toBe('queue');
    expect(screen.queryByText('Upload Climbing Video')).not.toBeInTheDocument();
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
