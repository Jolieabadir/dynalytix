/**
 * VideoMetadataPanel: the prep strip. Admins get the provenance form (source,
 * clip window, license, event, athlete), "Import metadata JSON" and "Mark
 * ready to rate"; a non-admin owner gets the badge, and a locked banner once
 * the video is ready or closed — with the store flagged read-only so the
 * player and moves list hide their mutation controls.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

vi.mock('../api/client', () => ({
  adminUpdateVideoMetadata: vi.fn(),
  adminMarkReady: vi.fn(),
  adminReopenVideo: vi.fn(),
  adminListAthletes: vi.fn(),
}));

import VideoMetadataPanel from './VideoMetadataPanel';
import useStore from '../store/useStore';
import { adminUpdateVideoMetadata, adminMarkReady, adminListAthletes } from '../api/client';
import { parseMetadataJson } from '../utils/prepMetadata';

const VIDEO = {
  id: 3,
  filename: 'prep.mp4',
  prep_status: 'draft',
  irr_overlap: false,
  irr_overlap_set_by: null,
  rater_target: 1,
  source_type: 'public_broadcast',
  source_url: null,
  clip_start_ms: null,
  clip_end_ms: null,
  license: null,
  event_name: null,
  event_date: null,
  athlete_id: null,
  route_grade: null,
  wall_type: null,
  camera_angle: null,
  notes: null,
};

const CONFIG = { source_types: ['public_broadcast', 'cc_license', 'research_dataset'] };

const ATHLETE_ID = 'a1b2c3d4-0000-4000-8000-000000000001';
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

function jsonFile(content, name = 'clip.json') {
  return new File([content], name, { type: 'application/json' });
}

beforeEach(() => {
  useStore.getState().resetVideoState();
  useStore.setState({ config: CONFIG });
  vi.mocked(adminMarkReady).mockResolvedValue({
    ...VIDEO,
    prep_status: 'ready',
    irr_overlap: true,
    irr_overlap_set_by: 'random',
    rater_target: 3,
  });
  vi.mocked(adminUpdateVideoMetadata).mockImplementation(async (id, fields) => ({ ...VIDEO, ...fields }));
  vi.mocked(adminListAthletes).mockResolvedValue(ATHLETES);
  vi.spyOn(window, 'confirm').mockReturnValue(true);
});

describe('VideoMetadataPanel — non-admin owner', () => {
  it('shows the prep status badge and no Mark ready or import button on a draft', () => {
    useStore.setState({ currentVideo: VIDEO, profile: { is_admin: false } });
    render(<VideoMetadataPanel />);

    expect(screen.getByTestId('prep-status')).toHaveTextContent('draft');
    expect(screen.queryByText(/dataset/i)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Mark ready to rate' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Import metadata JSON' })).not.toBeInTheDocument();
    expect(screen.queryByTestId('locked-banner')).not.toBeInTheDocument();
    expect(useStore.getState().readOnlyStructure).toBe(false);
    expect(adminListAthletes).not.toHaveBeenCalled();
  });

  it('shows the locked banner and flags the store read-only once the video is ready', () => {
    useStore.setState({ currentVideo: { ...VIDEO, prep_status: 'ready' }, profile: { is_admin: false } });
    render(<VideoMetadataPanel />);

    expect(screen.getByTestId('locked-banner')).toHaveTextContent('holds and moves are locked');
    expect(useStore.getState().readOnlyStructure).toBe(true);
  });

  it('shows metadata read-only, not as inputs', async () => {
    const user = userEvent.setup();
    useStore.setState({ currentVideo: { ...VIDEO, route_grade: 'V5' }, profile: { is_admin: false } });
    render(<VideoMetadataPanel />);

    await user.click(screen.getByRole('button', { name: 'Video details' }));
    expect(screen.getByText('V5')).toBeInTheDocument();
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
  });
});

describe('VideoMetadataPanel — admin', () => {
  it('shows prep_status and the overlap flag read-only', () => {
    useStore.setState({
      currentVideo: { ...VIDEO, prep_status: 'ready', irr_overlap: true, irr_overlap_set_by: 'random', rater_target: 3 },
      profile: { is_admin: true },
    });
    render(<VideoMetadataPanel />);

    expect(screen.getByTestId('prep-status')).toHaveTextContent('ready');
    expect(screen.getByTestId('overlap-status')).toHaveTextContent('overlap: yes (random)');
    expect(screen.getByTestId('overlap-status')).toHaveTextContent('target 3 raters');
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
  });

  it('has the provenance fields and none of the dropped climber / gym fields', async () => {
    const user = userEvent.setup();
    useStore.setState({ currentVideo: VIDEO, profile: { is_admin: true } });
    render(<VideoMetadataPanel />);

    await user.click(screen.getByRole('button', { name: 'Video details' }));
    for (const label of [
      'Source type', 'Source URL', 'Clip start (ms)', 'Clip end (ms)', 'License', 'Event name',
      'Event date', 'Athlete', 'Route grade', 'Wall type', 'Camera angle', 'Notes',
    ]) {
      expect(screen.getByLabelText(label)).toBeInTheDocument();
    }
    for (const gone of [/Climber/i, /Ape index/i, /^Gym$/]) {
      expect(screen.queryByLabelText(gone)).not.toBeInTheDocument();
    }
    const sourceOptions = within(screen.getByLabelText('Source type')).getAllByRole('option').map((o) => o.value);
    expect(sourceOptions).toEqual(['public_broadcast', 'cc_license', 'research_dataset']);
    expect(screen.getByLabelText('Event date')).toHaveAttribute('type', 'date');
  });

  it('saves the metadata form through the admin endpoint, athlete picked from the list', async () => {
    const user = userEvent.setup();
    useStore.setState({ currentVideo: VIDEO, profile: { is_admin: true } });
    render(<VideoMetadataPanel />);

    await user.click(screen.getByRole('button', { name: 'Video details' }));
    await user.selectOptions(screen.getByLabelText('Source type'), 'cc_license');
    await user.type(screen.getByLabelText('Source URL'), 'https://youtu.be/abc');
    await user.type(screen.getByLabelText('Clip start (ms)'), '12000');
    await user.type(screen.getByLabelText('License'), 'CC BY 4.0');
    await user.type(screen.getByLabelText('Event name'), 'IFSC WC Bern 2025');
    fireEvent.change(screen.getByLabelText('Event date'), { target: { value: '2025-07-04' } });
    const athleteSelect = screen.getByLabelText('Athlete');
    await within(athleteSelect).findByText(/a1b2c3d4 · ifsc.results.info\/athlete\/1234 · 168 cm · b. 1998/);
    await user.selectOptions(athleteSelect, ATHLETE_ID);
    await user.type(screen.getByLabelText('Route grade'), 'V5');
    await user.click(screen.getByRole('button', { name: 'Save details' }));

    await waitFor(() =>
      expect(adminUpdateVideoMetadata).toHaveBeenCalledWith(
        3,
        expect.objectContaining({
          source_type: 'cc_license',
          source_url: 'https://youtu.be/abc',
          clip_start_ms: 12000,
          license: 'CC BY 4.0',
          event_name: 'IFSC WC Bern 2025',
          event_date: '2025-07-04',
          athlete_id: ATHLETE_ID,
          route_grade: 'V5',
        })
      )
    );
    const payload = adminUpdateVideoMetadata.mock.calls[0][1];
    // Untouched integer fields are omitted, not sent as 0 or "".
    expect(payload).not.toHaveProperty('clip_end_ms');
    for (const gone of ['climber_height_cm', 'climber_ape_index_cm', 'climber_experience', 'gym', 'dataset']) {
      expect(payload).not.toHaveProperty(gone);
    }
    expect(useStore.getState().currentVideo.route_grade).toBe('V5');
  });

  it('imports a metadata JSON sidecar into the form, ignoring unknown keys, without saving', async () => {
    const user = userEvent.setup();
    useStore.setState({ currentVideo: VIDEO, profile: { is_admin: true } });
    render(<VideoMetadataPanel />);

    const sidecar = JSON.stringify({
      source_type: 'research_dataset',
      source_url: 'https://dataset.test/clip/7',
      clip_start_ms: 1500,
      clip_end_ms: 9800,
      license: 'CC BY-NC 4.0',
      event_name: 'Lab session 3',
      event_date: '2024-05-17',
      athlete_id: ATHLETE_ID,
      notes: 'trimmed by prepare_clip.py',
      route_grade: 'V9', // not importable
      sha256: 'deadbeef', // unknown
      dataset: 'A', // stale
    });
    await user.upload(screen.getByTestId('metadata-json-input'), jsonFile(sidecar));

    expect(await screen.findByRole('status')).toHaveTextContent('Filled 9 fields from clip.json');
    expect(screen.getByRole('status')).toHaveTextContent('Ignored: route_grade, sha256, dataset');
    expect(screen.getByLabelText('Source type')).toHaveValue('research_dataset');
    expect(screen.getByLabelText('Source URL')).toHaveValue('https://dataset.test/clip/7');
    expect(screen.getByLabelText('Clip start (ms)')).toHaveValue(1500);
    expect(screen.getByLabelText('Clip end (ms)')).toHaveValue(9800);
    expect(screen.getByLabelText('License')).toHaveValue('CC BY-NC 4.0');
    expect(screen.getByLabelText('Event name')).toHaveValue('Lab session 3');
    expect(screen.getByLabelText('Event date')).toHaveValue('2024-05-17');
    await waitFor(() => expect(screen.getByLabelText('Athlete')).toHaveValue(ATHLETE_ID));
    expect(screen.getByLabelText('Notes')).toHaveValue('trimmed by prepare_clip.py');
    expect(screen.getByLabelText('Route grade')).toHaveValue('');
    // Nothing is saved until the admin clicks Save.
    expect(adminUpdateVideoMetadata).not.toHaveBeenCalled();

    await user.click(screen.getByRole('button', { name: 'Save details' }));
    await waitFor(() =>
      expect(adminUpdateVideoMetadata).toHaveBeenCalledWith(
        3,
        expect.objectContaining({ source_type: 'research_dataset', clip_end_ms: 9800, athlete_id: ATHLETE_ID })
      )
    );
    expect(adminUpdateVideoMetadata.mock.calls[0][1]).not.toHaveProperty('sha256');
  });

  it('shows a friendly error for a file that is not JSON', async () => {
    const user = userEvent.setup();
    useStore.setState({ currentVideo: VIDEO, profile: { is_admin: true } });
    render(<VideoMetadataPanel />);

    await user.upload(screen.getByTestId('metadata-json-input'), jsonFile('{"source_url": ', 'broken.json'));

    expect(await screen.findByRole('alert')).toHaveTextContent('not valid JSON');
    expect(adminUpdateVideoMetadata).not.toHaveBeenCalled();
  });

  it('marks the video ready and keeps editing rights (no read-only flag for admins)', async () => {
    const user = userEvent.setup();
    useStore.setState({ currentVideo: VIDEO, profile: { is_admin: true } });
    render(<VideoMetadataPanel />);

    await user.click(screen.getByRole('button', { name: 'Mark ready to rate' }));

    await waitFor(() => expect(adminMarkReady).toHaveBeenCalledWith(3));
    expect(await screen.findByTestId('prep-status')).toHaveTextContent('ready');
    expect(screen.getByTestId('overlap-status')).toHaveTextContent('overlap: yes (random)');
    expect(screen.getByRole('button', { name: 'Reopen for editing' })).toBeInTheDocument();
    expect(useStore.getState().readOnlyStructure).toBe(false);
    expect(screen.queryByTestId('locked-banner')).not.toBeInTheDocument();
  });

  it('lists the 422 problems when Mark ready is refused', async () => {
    vi.mocked(adminMarkReady).mockRejectedValue({
      response: {
        status: 422,
        data: {
          detail: 'Video cannot be marked ready: …',
          problems: ["athlete's birth_year is missing (needed for the 18+ check)", 'source_url is missing'],
        },
      },
    });
    const user = userEvent.setup();
    useStore.setState({ currentVideo: VIDEO, profile: { is_admin: true } });
    render(<VideoMetadataPanel />);

    await user.click(screen.getByRole('button', { name: 'Mark ready to rate' }));

    const list = await screen.findByTestId('ready-problems');
    expect(within(list).getAllByRole('listitem').map((li) => li.textContent)).toEqual([
      "athlete's birth_year is missing (needed for the 18+ check)",
      'source_url is missing',
    ]);
    expect(screen.getByTestId('prep-status')).toHaveTextContent('draft');
  });
});

describe('parseMetadataJson', () => {
  it('keeps only the importable keys, as form strings', () => {
    expect(parseMetadataJson('{"clip_start_ms": 0, "event_date": null, "foo": 1}')).toEqual({
      values: { clip_start_ms: '0', event_date: '' },
      ignored: ['foo'],
    });
  });

  it('rejects non-objects', () => {
    expect(() => parseMetadataJson('[1, 2]')).toThrow('not a metadata object');
    expect(() => parseMetadataJson('nope')).toThrow('not valid JSON');
  });
});
