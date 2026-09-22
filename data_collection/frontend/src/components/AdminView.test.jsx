/**
 * AdminView: the cross-user video table, assignment actions, rater tiers and
 * the two exports — all against the mocked client.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
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
  adminUpdateRater: vi.fn(),
  downloadAdminExport: vi.fn(),
}));

import AdminView from './AdminView';
import {
  adminListVideos,
  adminListRaters,
  adminListAssignments,
  adminCreateAssignment,
  adminDeleteAssignment,
  adminMarkReady,
  adminCloseVideo,
  adminUpdateRater,
  downloadAdminExport,
} from '../api/client';

const video = (over) => ({
  id: 1,
  filename: 'a.mp4',
  owner_user_id: 'admin-1',
  dataset: 'B',
  prep_status: 'draft',
  access_role: 'admin',
  route_grade: null,
  ...over,
});

const VIDEOS = [
  { video: video({ id: 1, filename: 'a.mp4' }), assignment_count: 0, done_count: 0 },
  { video: video({ id: 2, filename: 'b.mp4', dataset: 'A', prep_status: 'ready' }), assignment_count: 2, done_count: 1 },
];

const RATERS = [
  { user_id: 'admin-1', display_name: 'Jolie', tier: 'validated', is_admin: true, years_climbing: 10, highest_grade: 'V8', research_background: true, validation_note: 'PI' },
  { user_id: 'r-1', display_name: 'Rater One', tier: 'open', is_admin: false, years_climbing: 3, highest_grade: 'V4', bio: 'Coach at a local gym.', research_background: false, validation_note: null },
  { user_id: 'r-2', display_name: 'Rater Two', tier: 'open', is_admin: false, years_climbing: 6, highest_grade: 'V6', research_background: false, validation_note: null },
];

beforeEach(() => {
  vi.mocked(adminListVideos).mockResolvedValue(VIDEOS);
  vi.mocked(adminListRaters).mockResolvedValue(RATERS);
  vi.mocked(adminListAssignments).mockResolvedValue([
    { id: 50, video_id: 2, rater_user_id: 'r-1', cohort: 'validated', status: 'done', assigned_at: '2026-09-20T00:00:00Z', completed_at: null },
  ]);
  vi.mocked(adminCreateAssignment).mockResolvedValue({ id: 51, video_id: 2, rater_user_id: 'r-2', cohort: 'overlap', status: 'assigned' });
  vi.mocked(adminDeleteAssignment).mockResolvedValue(undefined);
  vi.mocked(adminMarkReady).mockImplementation(async (id) => video({ id, filename: 'a.mp4', dataset: 'A', prep_status: 'ready' }));
  vi.mocked(adminCloseVideo).mockImplementation(async (id) => video({ id, filename: 'b.mp4', dataset: 'A', prep_status: 'closed' }));
  vi.mocked(adminUpdateRater).mockImplementation(async (userId, fields) => ({
    ...RATERS.find((r) => r.user_id === userId),
    ...fields,
  }));
  vi.mocked(downloadAdminExport).mockResolvedValue('dynalytix_long.csv');
  vi.spyOn(window, 'confirm').mockReturnValue(true);
});

describe('AdminView — videos table', () => {
  it('lists every video with owner, dataset, prep status and assignment count', async () => {
    render(<AdminView />);

    const rowA = await screen.findByTestId('admin-video-1');
    expect(rowA).toHaveTextContent('a.mp4');
    expect(rowA).toHaveTextContent('Jolie'); // owner resolved through the rater roster
    expect(rowA).toHaveTextContent('draft');
    const rowB = screen.getByTestId('admin-video-2');
    expect(rowB).toHaveTextContent('ready');
    expect(rowB).toHaveTextContent('2');
    expect(rowB).toHaveTextContent('(1 done)');
  });

  it('marks a draft video ready and a ready one closed', async () => {
    const user = userEvent.setup();
    render(<AdminView />);

    const rowA = await screen.findByTestId('admin-video-1');
    await user.click(within(rowA).getByRole('button', { name: 'Mark ready' }));
    await waitFor(() => expect(adminMarkReady).toHaveBeenCalledWith(1));
    expect(await within(screen.getByTestId('admin-video-1')).findByText('ready')).toBeInTheDocument();

    const rowB = screen.getByTestId('admin-video-2');
    await user.click(within(rowB).getByRole('button', { name: 'Close' }));
    await waitFor(() => expect(adminCloseVideo).toHaveBeenCalledWith(2));
    expect(await within(screen.getByTestId('admin-video-2')).findByText('closed')).toBeInTheDocument();
  });

  it('assigns a rater from the roster with a cohort, and removes one', async () => {
    const user = userEvent.setup();
    render(<AdminView />);

    const rowB = await screen.findByTestId('admin-video-2');
    await user.click(within(rowB).getByRole('button', { name: 'Assign rater' }));

    const panel = await screen.findByTestId('admin-assignments-2');
    expect(await within(panel).findByText('Rater One')).toBeInTheDocument();

    // Already-assigned raters are not offered again.
    const raterSelect = within(panel).getByRole('combobox', { name: 'Rater' });
    const names = within(raterSelect).getAllByRole('option').map((o) => o.textContent);
    expect(names.some((n) => n.startsWith('Rater One'))).toBe(false);
    expect(names.some((n) => n.startsWith('Rater Two'))).toBe(true);

    await user.selectOptions(raterSelect, 'r-2');
    await user.selectOptions(within(panel).getByRole('combobox', { name: 'Cohort' }), 'overlap');
    await user.click(within(panel).getByRole('button', { name: 'Assign' }));

    await waitFor(() =>
      expect(adminCreateAssignment).toHaveBeenCalledWith({ video_id: 2, rater_user_id: 'r-2', cohort: 'overlap' })
    );

    await user.click(within(panel).getByRole('button', { name: 'Remove Rater One' }));
    await waitFor(() => expect(adminDeleteAssignment).toHaveBeenCalledWith(50));
  });

  it('shows the 409 as "already assigned"', async () => {
    vi.mocked(adminCreateAssignment).mockRejectedValue({ response: { status: 409, data: { detail: 'dup' } } });
    const user = userEvent.setup();
    render(<AdminView />);

    await user.click(within(await screen.findByTestId('admin-video-2')).getByRole('button', { name: 'Assign rater' }));
    const panel = await screen.findByTestId('admin-assignments-2');
    await within(panel).findByText('Rater One');
    await user.selectOptions(within(panel).getByRole('combobox', { name: 'Rater' }), 'r-2');
    await user.click(within(panel).getByRole('button', { name: 'Assign' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('already assigned');
  });
});

describe('AdminView — raters and exports', () => {
  it('sets a rater tier and validation note through PUT /api/admin/raters', async () => {
    const user = userEvent.setup();
    render(<AdminView />);

    const row = await screen.findByTestId('admin-rater-r-1');
    await user.selectOptions(within(row).getByRole('combobox', { name: 'Tier for Rater One' }), 'validated');
    await user.type(within(row).getByRole('textbox', { name: 'Validation note for Rater One' }), 'coach, 3 yrs');
    await user.click(within(row).getByRole('button', { name: 'Save' }));

    await waitFor(() =>
      expect(adminUpdateRater).toHaveBeenCalledWith('r-1', { tier: 'validated', validation_note: 'coach, 3 yrs' })
    );
  });

  it('shows a rater bio in the raters panel', async () => {
    render(<AdminView />);
    const row = await screen.findByTestId('admin-rater-r-1');
    expect(within(row).getByText('Coach at a local gym.')).toBeInTheDocument();
    expect(within(screen.getByTestId('admin-rater-r-2')).queryByText(/gym/)).not.toBeInTheDocument();
  });

  it('downloads the long and full CSVs through the authenticated export helper', async () => {
    const user = userEvent.setup();
    render(<AdminView />);
    await screen.findByTestId('admin-video-1');

    await user.click(screen.getByRole('button', { name: 'Export long CSV' }));
    await waitFor(() => expect(downloadAdminExport).toHaveBeenCalledWith('long', { dataset: 'A' }));

    await user.selectOptions(screen.getByRole('combobox', { name: 'Export dataset' }), 'all');
    await user.click(screen.getByRole('button', { name: 'Export full CSV' }));
    await waitFor(() => expect(downloadAdminExport).toHaveBeenCalledWith('full', { dataset: 'all' }));
    expect(await screen.findByRole('status')).toHaveTextContent('Downloaded dynalytix_long.csv');
  });
});
