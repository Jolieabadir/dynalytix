/**
 * AdminView: the cross-user video table (overlap flag, rater target, source,
 * athlete), assignment actions, rater validation, the athletes panel and the
 * two exports — all against the mocked client.
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
  adminSetOverlap: vi.fn(),
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
  adminListAssignments,
  adminCreateAssignment,
  adminDeleteAssignment,
  adminMarkReady,
  adminCloseVideo,
  adminSetOverlap,
  adminUpdateRater,
  adminListAthletes,
  adminCreateAthlete,
  adminUpdateAthlete,
  downloadAdminExport,
} from '../api/client';

const ATHLETE_ID = 'a1b2c3d4-0000-4000-8000-000000000001';

const video = (over) => ({
  id: 1,
  filename: 'a.mp4',
  owner_user_id: 'admin-1',
  prep_status: 'draft',
  access_role: 'admin',
  route_grade: null,
  irr_overlap: false,
  irr_overlap_set_by: null,
  rater_target: 1,
  source_type: 'public_broadcast',
  athlete_id: null,
  ...over,
});

const VIDEOS = [
  { video: video({ id: 1, filename: 'a.mp4' }), assignment_count: 0, done_count: 0 },
  {
    video: video({
      id: 2,
      filename: 'b.mp4',
      prep_status: 'ready',
      irr_overlap: true,
      irr_overlap_set_by: 'random',
      rater_target: 3,
      athlete_id: ATHLETE_ID,
      event_name: 'IFSC WC Bern 2025',
    }),
    assignment_count: 2,
    done_count: 1,
  },
  {
    video: video({ id: 3, filename: 'c.mp4', prep_status: 'ready', irr_overlap: false, irr_overlap_set_by: 'random', rater_target: 1, source_type: 'cc_license' }),
    assignment_count: 1,
    done_count: 0,
  },
  {
    video: video({ id: 4, filename: 'd.mp4', prep_status: 'ready', irr_overlap: false, irr_overlap_set_by: 'random', rater_target: 1 }),
    assignment_count: 0,
    done_count: 0,
  },
];

const RATERS = [
  { user_id: 'admin-1', display_name: 'Jolie', is_validated: true, is_admin: true, years_climbing: 10, highest_grade: 'V8', research_background: true, validation_note: 'PI' },
  { user_id: 'r-1', display_name: 'Rater One', is_validated: true, is_admin: false, years_climbing: 3, highest_grade: 'V4', bio: 'Coach at a local gym.', research_background: false, validation_note: null },
  { user_id: 'r-2', display_name: 'Rater Two', is_validated: true, is_admin: false, years_climbing: 6, highest_grade: 'V6', research_background: false, validation_note: null },
  { user_id: 'r-3', display_name: 'Rater Three', is_validated: false, is_admin: false, years_climbing: 1, highest_grade: 'V2', research_background: false, validation_note: null },
];

const ATHLETES = [
  {
    athlete_id: ATHLETE_ID,
    ifsc_profile_url: 'https://ifsc.results.info/athlete/1234',
    height_cm: 168,
    height_source: 'ifsc_profile',
    birth_year: 1998,
    category: 'women',
    created_at: '2026-10-01T00:00:00Z',
  },
];

beforeEach(() => {
  vi.mocked(adminListVideos).mockResolvedValue(VIDEOS);
  vi.mocked(adminListRaters).mockResolvedValue(RATERS);
  vi.mocked(adminListAthletes).mockResolvedValue(ATHLETES);
  vi.mocked(adminListAssignments).mockImplementation(async (videoId) =>
    videoId === 2
      ? [{ id: 50, video_id: 2, rater_user_id: 'r-1', status: 'done', assigned_at: '2026-09-20T00:00:00Z', completed_at: null }]
      : videoId === 3
        ? [{ id: 60, video_id: 3, rater_user_id: 'r-2', status: 'assigned', assigned_at: '2026-09-20T00:00:00Z', completed_at: null }]
        : []
  );
  vi.mocked(adminCreateAssignment).mockResolvedValue({ id: 51, video_id: 2, rater_user_id: 'r-2', status: 'assigned' });
  vi.mocked(adminDeleteAssignment).mockResolvedValue(undefined);
  vi.mocked(adminMarkReady).mockImplementation(async (id) =>
    video({ id, filename: 'a.mp4', prep_status: 'ready', irr_overlap: true, irr_overlap_set_by: 'random', rater_target: 3 })
  );
  vi.mocked(adminCloseVideo).mockImplementation(async (id) => video({ id, filename: 'b.mp4', prep_status: 'closed' }));
  vi.mocked(adminSetOverlap).mockImplementation(async (id, value) =>
    video({ id, filename: 'a.mp4', irr_overlap: value, irr_overlap_set_by: 'admin_override', rater_target: value ? 3 : 1 })
  );
  vi.mocked(adminUpdateRater).mockImplementation(async (userId, fields) => ({
    ...RATERS.find((r) => r.user_id === userId),
    ...fields,
  }));
  vi.mocked(adminCreateAthlete).mockImplementation(async (fields) => ({
    athlete_id: 'ffff0000-0000-4000-8000-000000000002',
    height_source: fields.height_cm ? 'ifsc_profile' : 'missing',
    created_at: '2026-10-06T00:00:00Z',
    ifsc_profile_url: null,
    height_cm: null,
    birth_year: null,
    category: null,
    ...fields,
  }));
  vi.mocked(adminUpdateAthlete).mockImplementation(async (id, fields) => ({
    ...ATHLETES.find((a) => a.athlete_id === id),
    ...fields,
  }));
  vi.mocked(downloadAdminExport).mockResolvedValue('dynalytix_long.csv');
  vi.spyOn(window, 'confirm').mockReturnValue(true);
});

describe('AdminView — videos table', () => {
  it('lists every video with owner, source, athlete, prep status, overlap and n / target raters — no dataset', async () => {
    render(<AdminView />);

    const rowA = await screen.findByTestId('admin-video-1');
    expect(rowA).toHaveTextContent('a.mp4');
    expect(rowA).toHaveTextContent('Jolie'); // owner resolved through the rater roster
    expect(rowA).toHaveTextContent('draft');
    expect(screen.getByTestId('admin-source-1')).toHaveTextContent('Public Broadcast');
    expect(screen.getByTestId('admin-overlap-1')).toHaveTextContent('no');
    expect(screen.getByTestId('admin-overlap-1')).toHaveTextContent('not drawn yet');
    expect(screen.getByTestId('admin-raters-1')).toHaveTextContent('0 / 1');

    const rowB = screen.getByTestId('admin-video-2');
    expect(rowB).toHaveTextContent('ready');
    expect(rowB).toHaveTextContent('a1b2c3d4'); // athlete short id
    expect(screen.getByTestId('admin-overlap-2')).toHaveTextContent('yes');
    expect(screen.getByTestId('admin-overlap-2')).toHaveTextContent('Random');
    expect(screen.getByTestId('admin-raters-2')).toHaveTextContent('2 / 3');
    expect(screen.getByTestId('admin-raters-2')).toHaveTextContent('(1 done)');
    expect(screen.getByTestId('admin-source-3')).toHaveTextContent('Cc License');

    expect(screen.queryByText('Dataset')).not.toBeInTheDocument();
    expect(screen.queryByRole('combobox', { name: 'Cohort' })).not.toBeInTheDocument();
  });

  it('marks a draft video ready and a ready one closed', async () => {
    const user = userEvent.setup();
    render(<AdminView />);

    const rowA = await screen.findByTestId('admin-video-1');
    await user.click(within(rowA).getByRole('button', { name: 'Mark ready' }));
    await waitFor(() => expect(adminMarkReady).toHaveBeenCalledWith(1));
    expect(await within(screen.getByTestId('admin-video-1')).findByText('ready')).toBeInTheDocument();
    expect(screen.getByTestId('admin-overlap-1')).toHaveTextContent('yes');

    const rowB = screen.getByTestId('admin-video-2');
    await user.click(within(rowB).getByRole('button', { name: 'Close' }));
    await waitFor(() => expect(adminCloseVideo).toHaveBeenCalledWith(2));
    expect(await within(screen.getByTestId('admin-video-2')).findByText('closed')).toBeInTheDocument();
  });

  it('shows the 422 problems list when Mark ready is refused', async () => {
    vi.mocked(adminMarkReady).mockRejectedValue({
      response: {
        status: 422,
        data: {
          detail: 'Video cannot be marked ready: athlete is not set; event_date is missing',
          problems: ['event_date is missing', 'athlete is not set'],
        },
      },
    });
    const user = userEvent.setup();
    render(<AdminView />);

    await user.click(within(await screen.findByTestId('admin-video-1')).getByRole('button', { name: 'Mark ready' }));

    const list = await screen.findByTestId('ready-problems');
    const items = within(list).getAllByRole('listitem').map((li) => li.textContent);
    expect(items).toEqual(['event_date is missing', 'athlete is not set']);
    expect(screen.getByRole('alert')).toHaveTextContent('Mark ready refused');
    expect(within(screen.getByTestId('admin-video-1')).getByText('draft')).toBeInTheDocument();
  });

  it('toggles overlap while no rater is assigned, and disables the toggle once one is', async () => {
    const user = userEvent.setup();
    render(<AdminView />);
    await screen.findByTestId('admin-video-1');

    // Assignments exist on b.mp4 and c.mp4: locked.
    expect(screen.getByRole('checkbox', { name: 'Overlap for b.mp4' })).toBeDisabled();
    expect(screen.getByRole('checkbox', { name: 'Overlap for c.mp4' })).toBeDisabled();

    const toggle = screen.getByRole('checkbox', { name: 'Overlap for a.mp4' });
    expect(toggle).toBeEnabled();
    expect(toggle).not.toBeChecked();
    await user.click(toggle);

    await waitFor(() => expect(adminSetOverlap).toHaveBeenCalledWith(1, true));
    expect(await screen.findByRole('status')).toHaveTextContent('overlap on (3 raters)');
    expect(screen.getByRole('checkbox', { name: 'Overlap for a.mp4' })).toBeChecked();
    expect(screen.getByTestId('admin-overlap-1')).toHaveTextContent('Admin Override');
    expect(screen.getByTestId('admin-raters-1')).toHaveTextContent('0 / 3');
  });

  it('offers only validated raters, assigns without a cohort, and removes one', async () => {
    const user = userEvent.setup();
    render(<AdminView />);

    const rowB = await screen.findByTestId('admin-video-2');
    await user.click(within(rowB).getByRole('button', { name: 'Raters' }));

    const panel = await screen.findByTestId('admin-assignments-2');
    expect(await within(panel).findByText('Rater One')).toBeInTheDocument();
    expect(within(panel).queryByRole('combobox', { name: 'Cohort' })).not.toBeInTheDocument();

    // Already-assigned and unvalidated raters are not offered.
    const raterSelect = within(panel).getByRole('combobox', { name: 'Rater' });
    const names = within(raterSelect).getAllByRole('option').map((o) => o.textContent);
    expect(names).not.toContain('Rater One');
    expect(names).not.toContain('Rater Three');
    expect(names).toContain('Rater Two');

    await user.selectOptions(raterSelect, 'r-2');
    await user.click(within(panel).getByRole('button', { name: 'Assign' }));

    await waitFor(() =>
      expect(adminCreateAssignment).toHaveBeenCalledWith({ video_id: 2, rater_user_id: 'r-2' })
    );

    await user.click(within(panel).getByRole('button', { name: 'Remove Rater One' }));
    await waitFor(() => expect(adminDeleteAssignment).toHaveBeenCalledWith(50));
  });

  it('disables Assign once the video has its rater_target', async () => {
    const user = userEvent.setup();
    render(<AdminView />);

    // c.mp4: 1 / 1 already.
    await user.click(within(await screen.findByTestId('admin-video-3')).getByRole('button', { name: 'Raters' }));
    const panel = await screen.findByTestId('admin-assignments-3');
    await within(panel).findByText('Rater Two');

    expect(within(panel).getByRole('button', { name: 'Assign' })).toBeDisabled();
    expect(within(panel).getByRole('combobox', { name: 'Rater' })).toBeDisabled();
    expect(within(panel).getByTestId('assign-blocked-3')).toHaveTextContent('Rater target reached (1 / 1)');
  });

  it('disables Assign on a video that is not ready', async () => {
    const user = userEvent.setup();
    render(<AdminView />);

    await user.click(within(await screen.findByTestId('admin-video-1')).getByRole('button', { name: 'Raters' }));
    const panel = await screen.findByTestId('admin-assignments-1');
    expect(await within(panel).findByTestId('assign-blocked-1')).toHaveTextContent('Mark the video ready');
    expect(within(panel).getByRole('button', { name: 'Assign' })).toBeDisabled();
  });

  it('shows the server’s 409 reason', async () => {
    vi.mocked(adminCreateAssignment).mockRejectedValue({
      response: { status: 409, data: { detail: 'Rater is already assigned to this video' } },
    });
    const user = userEvent.setup();
    render(<AdminView />);

    await user.click(within(await screen.findByTestId('admin-video-4')).getByRole('button', { name: 'Raters' }));
    const panel = await screen.findByTestId('admin-assignments-4');
    await within(panel).findByText(/No raters assigned yet/);
    await user.selectOptions(within(panel).getByRole('combobox', { name: 'Rater' }), 'r-2');
    await user.click(within(panel).getByRole('button', { name: 'Assign' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('already assigned');
  });
});

describe('AdminView — raters', () => {
  it('sets is_validated and a validation note through PUT /api/admin/raters', async () => {
    const user = userEvent.setup();
    render(<AdminView />);

    const row = await screen.findByTestId('admin-rater-r-3');
    const toggle = within(row).getByRole('checkbox', { name: 'Validated: Rater Three' });
    expect(toggle).not.toBeChecked();
    expect(within(row).queryByRole('combobox')).not.toBeInTheDocument(); // no tier select
    await user.click(toggle);
    await user.type(within(row).getByRole('textbox', { name: 'Validation note for Rater Three' }), 'coach, 3 yrs');
    await user.click(within(row).getByRole('button', { name: 'Save' }));

    await waitFor(() =>
      expect(adminUpdateRater).toHaveBeenCalledWith('r-3', { is_validated: true, validation_note: 'coach, 3 yrs' })
    );
  });

  it('shows a rater bio in the raters panel', async () => {
    render(<AdminView />);
    const row = await screen.findByTestId('admin-rater-r-1');
    expect(within(row).getByText('Coach at a local gym.')).toBeInTheDocument();
    expect(within(screen.getByTestId('admin-rater-r-2')).queryByText(/gym/)).not.toBeInTheDocument();
  });
});

describe('AdminView — athletes', () => {
  it('lists athletes by short id + profile URL + height + birth year (no names)', async () => {
    render(<AdminView />);
    const row = await screen.findByTestId(`admin-athlete-${ATHLETE_ID}`);
    expect(row).toHaveTextContent('a1b2c3d4');
    expect(row).toHaveTextContent('ifsc.results.info/athlete/1234');
    expect(row).toHaveTextContent('168 cm');
    expect(row).toHaveTextContent('1998');
    expect(row).toHaveTextContent('women');
  });

  it('creates an athlete from the form', async () => {
    const user = userEvent.setup();
    render(<AdminView />);
    const panel = await screen.findByTestId('admin-athletes');

    await user.type(within(panel).getByLabelText('New athlete IFSC profile URL'), 'https://ifsc.results.info/athlete/999');
    await user.type(within(panel).getByLabelText('New athlete height (cm)'), '181');
    await user.type(within(panel).getByLabelText('New athlete birth year'), '2001');
    await user.selectOptions(within(panel).getByLabelText('New athlete category'), 'men');
    await user.click(within(panel).getByRole('button', { name: 'Add athlete' }));

    await waitFor(() =>
      expect(adminCreateAthlete).toHaveBeenCalledWith({
        ifsc_profile_url: 'https://ifsc.results.info/athlete/999',
        height_cm: 181,
        birth_year: 2001,
        category: 'men',
      })
    );
    expect(await screen.findByTestId('admin-athlete-ffff0000-0000-4000-8000-000000000002')).toHaveTextContent('181 cm');
    // The form resets for the next one.
    expect(within(panel).getByLabelText('New athlete IFSC profile URL')).toHaveValue('');
  });

  it('refuses to create an athlete without a profile URL', async () => {
    const user = userEvent.setup();
    render(<AdminView />);
    const panel = await screen.findByTestId('admin-athletes');

    await user.type(within(panel).getByLabelText('New athlete birth year'), '2001');
    await user.click(within(panel).getByRole('button', { name: 'Add athlete' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('IFSC profile URL');
    expect(adminCreateAthlete).not.toHaveBeenCalled();
  });

  it('edits an athlete inline', async () => {
    const user = userEvent.setup();
    render(<AdminView />);
    const row = await screen.findByTestId(`admin-athlete-${ATHLETE_ID}`);

    await user.click(within(row).getByRole('button', { name: 'Edit athlete a1b2c3d4' }));
    const editing = screen.getByTestId(`admin-athlete-${ATHLETE_ID}`);
    const year = within(editing).getByLabelText('Athlete a1b2c3d4 birth year');
    await user.clear(year);
    await user.type(year, '1997');
    await user.click(within(editing).getByRole('button', { name: 'Save' }));

    await waitFor(() =>
      expect(adminUpdateAthlete).toHaveBeenCalledWith(ATHLETE_ID, {
        ifsc_profile_url: 'https://ifsc.results.info/athlete/1234',
        height_cm: 168,
        birth_year: 1997,
        category: 'women',
      })
    );
    expect(await screen.findByTestId(`admin-athlete-${ATHLETE_ID}`)).toHaveTextContent('1997');
  });
});

describe('AdminView — exports', () => {
  it('downloads Long (IRR input) and Full with the community / overlap checkboxes', async () => {
    const user = userEvent.setup();
    render(<AdminView />);
    await screen.findByTestId('admin-video-1');

    expect(screen.queryByRole('combobox', { name: 'Export dataset' })).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Long (IRR input)' }));
    await waitFor(() =>
      expect(downloadAdminExport).toHaveBeenCalledWith('long', { include_community: false, overlap_only: false })
    );

    await user.click(screen.getByRole('checkbox', { name: 'Include community videos' }));
    await user.click(screen.getByRole('checkbox', { name: 'Overlap subset only (long)' }));
    await user.click(screen.getByRole('button', { name: 'Long (IRR input)' }));
    await waitFor(() =>
      expect(downloadAdminExport).toHaveBeenLastCalledWith('long', { include_community: true, overlap_only: true })
    );

    // Full ignores the overlap filter.
    await user.click(screen.getByRole('button', { name: 'Full' }));
    await waitFor(() => expect(downloadAdminExport).toHaveBeenLastCalledWith('full', { include_community: true }));
    expect(await screen.findByRole('status')).toHaveTextContent('Downloaded dynalytix_long.csv');
  });
});
