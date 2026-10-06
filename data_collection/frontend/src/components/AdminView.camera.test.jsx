/**
 * AdminView camera column (W2 worker): steady clips show "steady", failing
 * clips list their problems and take an override only with a note, an
 * override can be undone, and clips without a pose say so.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

vi.mock('../api/client', () => ({
  adminListVideos: vi.fn(),
  adminListRaters: vi.fn(),
  adminListAssignments: vi.fn(),
  adminCreateAssignment: vi.fn(),
  adminDeleteAssignment: vi.fn(),
  adminMarkReady: vi.fn(),
  adminCloseVideo: vi.fn(),
  adminReopenVideo: vi.fn(),
  adminSetOverlap: vi.fn(),
  adminSetCameraOverride: vi.fn(),
  adminUpdateRater: vi.fn(),
  adminListAthletes: vi.fn(),
  adminCreateAthlete: vi.fn(),
  adminUpdateAthlete: vi.fn(),
  downloadAdminExport: vi.fn(),
}));

import AdminView from './AdminView';
import {
  adminListVideos,
  adminListRaters,
  adminListAthletes,
  adminSetCameraOverride,
} from '../api/client';

const base = {
  owner_user_id: 'admin-1',
  prep_status: 'draft',
  access_role: 'admin',
  irr_overlap: false,
  irr_overlap_set_by: null,
  rater_target: 1,
  source_type: 'public_broadcast',
  athlete_id: null,
  pose_status: 'done',
  camera_override: false,
  camera_override_note: null,
};

const steady = { ...base, id: 1, filename: 'steady.mp4', camera_problems: [], camera_motion_score: 0.0002, camera_zoom_range: 1.0, has_cut: false };
const panning = { ...base, id: 2, filename: 'pan.mp4', camera_problems: ['camera moves too much (score 0.0190 > 0.0020)'], camera_motion_score: 0.019, camera_zoom_range: 1.0, has_cut: false };
const pending = { ...base, id: 3, filename: 'pending.mp4', pose_status: 'processing', camera_problems: [] };
const community = { ...base, id: 4, filename: 'mine.mp4', source_type: 'community', camera_problems: [] };

beforeEach(() => {
  vi.mocked(adminListVideos).mockResolvedValue(
    [steady, panning, pending, community].map((video) => ({ video, assignment_count: 0, done_count: 0 }))
  );
  vi.mocked(adminListRaters).mockResolvedValue([]);
  vi.mocked(adminListAthletes).mockResolvedValue([]);
  vi.mocked(adminSetCameraOverride).mockReset();
});

describe('AdminView camera column', () => {
  it('shows steady, failing, waiting and community states', async () => {
    render(<AdminView />);
    const steadyCell = await screen.findByTestId('admin-camera-1');
    expect(within(steadyCell).getByText('steady')).toBeInTheDocument();
    expect(within(steadyCell).getByText(/motion 0\.0002 · zoom 1\.00/)).toBeInTheDocument();

    const panCell = screen.getByTestId('admin-camera-2');
    expect(within(panCell).getByText('fails')).toBeInTheDocument();
    expect(within(panCell).getByText(/camera moves too much/)).toBeInTheDocument();

    expect(within(screen.getByTestId('admin-camera-3')).getByText('waiting for pose')).toBeInTheDocument();
    expect(within(screen.getByTestId('admin-camera-4')).getByText('not checked')).toBeInTheDocument();
  });

  it('overrides only with a note, then can undo', async () => {
    const user = userEvent.setup();
    vi.mocked(adminSetCameraOverride).mockResolvedValueOnce({
      ...panning, camera_override: true, camera_override_note: 'pan ends before move 1',
    });
    render(<AdminView />);
    const cell = await screen.findByTestId('admin-camera-2');
    const button = within(cell).getByRole('button', { name: 'Override' });
    expect(button).toBeDisabled();

    await user.type(within(cell).getByLabelText(/Camera override note/), '  pan ends before move 1 ');
    expect(button).toBeEnabled();
    await user.click(button);
    expect(adminSetCameraOverride).toHaveBeenCalledWith(2, true, 'pan ends before move 1');

    const updated = await screen.findByTestId('admin-camera-2');
    expect(within(updated).getByText('overridden')).toBeInTheDocument();
    expect(within(updated).getByText(/Note: pan ends before move 1/)).toBeInTheDocument();
    // The problem stays listed so it is clear what was accepted.
    expect(within(updated).getByText(/camera moves too much/)).toBeInTheDocument();
    expect(await screen.findByText(/camera check overridden/)).toBeInTheDocument();

    vi.mocked(adminSetCameraOverride).mockResolvedValueOnce({ ...panning });
    await user.click(within(updated).getByRole('button', { name: 'Undo override' }));
    expect(adminSetCameraOverride).toHaveBeenLastCalledWith(2, false, '');
    expect(await screen.findByText(/camera check enforced again/)).toBeInTheDocument();
  });

  it('explains a 400 from the API', async () => {
    const user = userEvent.setup();
    vi.mocked(adminSetCameraOverride).mockRejectedValueOnce({ response: { status: 400, data: {} } });
    render(<AdminView />);
    const cell = await screen.findByTestId('admin-camera-2');
    await user.type(within(cell).getByLabelText(/Camera override note/), 'x');
    await user.click(within(cell).getByRole('button', { name: 'Override' }));
    expect(await screen.findByText(/Add a note saying why/)).toBeInTheDocument();
  });
});
