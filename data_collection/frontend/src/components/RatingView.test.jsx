/**
 * RatingView: the rater's read-only-structure labeling view.
 *
 * Holds and canonical moves cannot be changed; Environment and Outcome are
 * the rater's own; Complete renders the API's 422 `missing` list inline and
 * turns the view read-only on 200.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

vi.mock('../api/client', () => ({
  getVideo: vi.fn(),
  getHolds: vi.fn(),
  getMoves: vi.fn(),
  // Pose rows now arrive through usePoseStatus (header chip), not this view.
  getPoseStatus: vi.fn(),
  fetchPoseCsvText: vi.fn(),
  retryPose: vi.fn(),
  updateMove: vi.fn(),
  getVideoPlaybackUrl: vi.fn(),
  getEnvironmentForMove: vi.fn(),
  getOutcomeForMove: vi.fn(),
  startAssignment: vi.fn(),
  completeAssignment: vi.fn(),
  createEnvironment: vi.fn(),
  updateEnvironment: vi.fn(),
  createOutcome: vi.fn(),
  updateOutcome: vi.fn(),
  deleteMove: vi.fn(),
}));

// The player needs a real <video> and a canvas; neither exists in jsdom. The
// rating view's contract with it is the store (readOnlyStructure), asserted
// directly below.
vi.mock('./VideoPlayer', () => ({
  default: () => <div data-testid="video-player-stub" />,
}));
vi.mock('./TaggingMode', () => ({
  default: () => <div data-testid="tagging-stub" />,
}));

import RatingView from './RatingView';
import useStore from '../store/useStore';
import {
  getVideo,
  getHolds,
  getMoves,
  getVideoPlaybackUrl,
  getEnvironmentForMove,
  getOutcomeForMove,
  startAssignment,
  completeAssignment,
  createEnvironment,
  createOutcome,
} from '../api/client';

const CONFIG = {
  approaches: ['static', 'dynamic'],
  sizes: ['small', 'large'],
  move_tags: ['dyno', 'no_hands'],
  wall_angles: ['slab', 'steep'],
  hold_types: ['jug', 'crimp'],
  hold_qualities: ['incut', 'small'],
  hold_slots: ['start_left', 'start_right', 'end', 'foot'],
  results: ['success', 'fall'],
  reach_details: ['reached_controlled', 'didnt_reach'],
  confidence_levels: ['low', 'high'],
  tag_types: { pumped: 'Pumped' },
  body_parts: ['left_wrist'],
  sides: ['left', 'right'],
  definitions: {},
};

const VIDEO = {
  id: 5,
  filename: 'crimp_ladder.mp4',
  fps: 30,
  total_frames: 900,
  width: 1080,
  height: 1920,
  dataset: 'A',
  prep_status: 'ready',
  access_role: 'rater',
  owner_user_id: 'admin',
};

const HOLDS = [
  { id: 101, video_id: 5, bbox_x: 0.1, bbox_y: 0.1, bbox_w: 0.05, bbox_h: 0.05, source: 'manual' },
  { id: 102, video_id: 5, bbox_x: 0.5, bbox_y: 0.5, bbox_w: 0.05, bbox_h: 0.05, source: 'detected' },
];

const MOVES = [
  {
    id: 21, video_id: 5, frame_start: 10, frame_end: 40, timestamp_start_ms: 333, timestamp_end_ms: 1333,
    approach: 'static', size: 'small', move_tags: ['dyno'], form_quality: 4, effort_level: 6,
    confidence: 'high', description: 'first', frame_tag_count: 0,
  },
  {
    id: 22, video_id: 5, frame_start: 50, frame_end: 90, timestamp_start_ms: 1666, timestamp_end_ms: 3000,
    approach: 'dynamic', size: 'large', move_tags: [], form_quality: 3, effort_level: 8,
    confidence: 'low', description: '', frame_tag_count: 0,
  },
];

const ASSIGNMENT = {
  id: 11, video_id: 5, rater_user_id: 'u1', cohort: 'validated', status: 'in_progress',
  assigned_at: '2026-09-20T10:00:00Z', completed_at: null,
};

beforeEach(() => {
  useStore.getState().resetVideoState();
  useStore.setState({
    config: CONFIG,
    currentAssignment: ASSIGNMENT,
    currentVideo: VIDEO,
    assignments: [{ assignment: ASSIGNMENT, video: VIDEO, move_count: 2 }],
    profile: { user_id: 'u1', display_name: 'Rater', tier: 'validated', is_admin: false },
  });
  vi.mocked(getVideo).mockResolvedValue(VIDEO);
  vi.mocked(getHolds).mockResolvedValue(HOLDS);
  vi.mocked(getMoves).mockResolvedValue(MOVES);
  vi.mocked(getVideoPlaybackUrl).mockResolvedValue('https://r2.test/video.mp4');
  vi.mocked(getEnvironmentForMove).mockResolvedValue(null);
  vi.mocked(getOutcomeForMove).mockResolvedValue(null);
  vi.mocked(startAssignment).mockResolvedValue({ ...ASSIGNMENT, status: 'in_progress' });
  vi.mocked(createEnvironment).mockImplementation(async (d) => ({ id: 900, ...d }));
  vi.mocked(createOutcome).mockImplementation(async (d) => ({ id: 901, ...d }));
});

async function renderLoaded() {
  const utils = render(<RatingView onExit={() => {}} />);
  await screen.findByText('Canonical Moves');
  return utils;
}

describe('RatingView — read-only structure', () => {
  it('loads the canonical holds and moves, flags the store read-only, and offers no delete', async () => {
    await renderLoaded();

    expect(getHolds).toHaveBeenCalledWith(5);
    expect(getMoves).toHaveBeenCalledWith(5);
    expect(useStore.getState().readOnlyStructure).toBe(true);
    expect(useStore.getState().holds).toEqual(HOLDS);
    expect(useStore.getState().videoPlaybackUrl).toBe('https://r2.test/video.mp4');

    // Two canonical moves, no ✕ delete button on either.
    expect(screen.getByTestId('move-card-21')).toBeInTheDocument();
    expect(screen.getByTestId('move-card-22')).toBeInTheDocument();
    expect(screen.queryByTitle('Delete move')).not.toBeInTheDocument();
    // And no Define-mode entry points.
    expect(screen.queryByText('Create Move')).not.toBeInTheDocument();
    expect(screen.queryByText('Finish & Export')).not.toBeInTheDocument();
  });

  it('never carries labels across videos: exiting resets the video-scoped store', async () => {
    await renderLoaded();
    useStore.setState({ frameTags: [{ id: 1 }], moves: MOVES });

    useStore.getState().resetVideoState();

    const s = useStore.getState();
    expect(s.moves).toEqual([]);
    expect(s.frameTags).toEqual([]);
    expect(s.holds).toEqual([]);
    expect(s.currentVideo).toBeNull();
    expect(s.currentAssignment).toBeNull();
    expect(s.readOnlyStructure).toBe(false);
    expect(s.previousEnvironment.wall_angle).toBe('');
  });
});

describe('RatingView — rating a move', () => {
  it('shows Strategy read-only and lets the rater save Environment + Outcome', async () => {
    const user = userEvent.setup();
    await renderLoaded();

    await user.click(within(screen.getByTestId('move-card-21')).getByRole('button', { name: 'Rate' }));

    const form = await screen.findByTestId('rater-move-form');
    // Strategy: displayed, not editable — no approach radios anywhere.
    const strategy = within(form).getByTestId('strategy-summary');
    expect(strategy).toHaveTextContent('Static');
    expect(strategy).toHaveTextContent('Dyno');
    expect(within(form).queryByRole('radio', { name: /Static/ })).not.toBeInTheDocument();
    expect(within(form).queryByRole('slider')).not.toBeInTheDocument();

    // Hold slots pick only from the locked holds.
    const leftSelect = within(form).getByRole('combobox', { name: 'Hold for Start Left' });
    const options = within(leftSelect).getAllByRole('option').map((o) => o.textContent);
    expect(options).toEqual(['No hold chosen', 'Hold #101', 'Hold #102']);

    await user.click(within(form).getByRole('radio', { name: /Steep/ }));
    for (const slot of ['start_left', 'start_right', 'end']) {
      await user.click(within(screen.getByTestId(`hold-slot-${slot}`)).getByRole('radio', { name: /Jug/ }));
    }
    await user.selectOptions(leftSelect, '101');
    await user.click(within(form).getByRole('radio', { name: /Success/ }));
    await user.click(within(form).getByRole('radio', { name: /Reached Controlled/ }));
    await user.click(within(form).getByRole('radio', { name: /^High/ }));
    await user.click(within(form).getByRole('button', { name: 'Save Rating' }));

    await waitFor(() => expect(createEnvironment).toHaveBeenCalled());
    expect(createEnvironment).toHaveBeenCalledWith(
      expect.objectContaining({
        move_id: 21,
        wall_angle: 'steep',
        start_left: expect.objectContaining({ hold_id: 101, hold_type: 'jug' }),
      })
    );
    expect(createOutcome).toHaveBeenCalledWith({
      move_id: 21,
      result: 'success',
      reach_detail: 'reached_controlled',
      confidence: 'high',
    });
    expect(await within(form).findByRole('status')).toHaveTextContent('Saved.');
  });
});

describe('RatingView — Complete', () => {
  it('renders the 422 missing list inline, per move', async () => {
    vi.mocked(completeAssignment).mockResolvedValue({
      incomplete: true,
      detail: '2 of 2 moves are incomplete',
      missing: [
        { move_id: 21, move_index: 0, missing: ['outcome'] },
        { move_id: 22, move_index: 1, missing: ['environment', 'outcome'] },
      ],
    });
    const user = userEvent.setup();
    await renderLoaded();

    await user.click(screen.getByRole('button', { name: 'Complete' }));

    const box = await screen.findByTestId('complete-error');
    expect(box).toHaveTextContent('2 of 2 moves are incomplete');
    expect(box).toHaveTextContent('Move 1: missing Outcome');
    expect(box).toHaveTextContent('Move 2: missing Environment and Outcome');
    // Still open for rating.
    expect(screen.getByRole('button', { name: 'Complete' })).toBeInTheDocument();
    expect(useStore.getState().currentAssignment.status).toBe('in_progress');
  });

  it('on 200 shows done and makes the view read-only', async () => {
    vi.mocked(completeAssignment).mockResolvedValue({
      incomplete: false,
      assignment: { ...ASSIGNMENT, status: 'done', completed_at: '2026-09-22T12:00:00Z' },
    });
    const user = userEvent.setup();
    await renderLoaded();

    await user.click(screen.getByRole('button', { name: 'Complete' }));

    await waitFor(() => expect(useStore.getState().currentAssignment.status).toBe('done'));
    expect(screen.queryByRole('button', { name: 'Complete' })).not.toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('Rating submitted');
    expect(screen.getByTestId('rating-counts')).toHaveTextContent('Done');
    // The queue entry follows.
    expect(useStore.getState().assignments[0].assignment.status).toBe('done');

    // Opening a move now shows the form locked: no Save, controls disabled.
    await user.click(within(screen.getByTestId('move-card-21')).getByRole('button', { name: 'Rate' }));
    const form = await screen.findByTestId('rater-move-form');
    expect(within(form).queryByRole('button', { name: /Save Rating|Update Rating/ })).not.toBeInTheDocument();
    expect(within(form).getByRole('radio', { name: /Steep/ })).toBeDisabled();
  });
});
