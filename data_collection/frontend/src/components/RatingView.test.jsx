/**
 * RatingView: the rater's read-only-structure, observer-only labeling view.
 *
 * Holds and canonical moves cannot be changed; Strategy, Environment and
 * Outcome are all the rater's own (no effort, no frame tagging, no hold
 * auto-suggest, and the prepper's Strategy is not shown); Complete renders
 * the API's 422 `missing` list inline and turns the view read-only on 200.
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
  getStrategyForMove: vi.fn(),
  createStrategy: vi.fn(),
  updateStrategy: vi.fn(),
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

// The player needs a real <video>, which jsdom lacks. The rating view's
// contract with it is the store (readOnlyStructure), asserted directly below.
vi.mock('./VideoPlayer', () => ({
  default: () => <div data-testid="video-player-stub" />,
}));

import RatingView from './RatingView';
import useStore from '../store/useStore';
import {
  getVideo,
  getHolds,
  getMoves,
  getVideoPlaybackUrl,
  getStrategyForMove,
  createStrategy,
  updateStrategy,
  getEnvironmentForMove,
  getOutcomeForMove,
  startAssignment,
  completeAssignment,
  createEnvironment,
  updateEnvironment,
  createOutcome,
  updateOutcome,
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
  prep_status: 'ready',
  irr_overlap: true,
  irr_overlap_set_by: 'random',
  rater_target: 3,
  source_type: 'public_broadcast',
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
  id: 11, video_id: 5, rater_user_id: 'u1', status: 'in_progress',
  assigned_at: '2026-09-20T10:00:00Z', completed_at: null,
};

beforeEach(() => {
  useStore.getState().resetVideoState();
  useStore.setState({
    config: CONFIG,
    currentAssignment: ASSIGNMENT,
    currentVideo: VIDEO,
    assignments: [{ assignment: ASSIGNMENT, video: VIDEO, move_count: 2 }],
    profile: { user_id: 'u1', display_name: 'Rater', is_validated: true, is_admin: false },
    // Pose rows in the store must not turn into pre-filled hold slots here.
    csvData: [{ frame_number: '10' }, { frame_number: '40' }],
  });
  vi.mocked(getVideo).mockResolvedValue(VIDEO);
  vi.mocked(getHolds).mockResolvedValue(HOLDS);
  vi.mocked(getMoves).mockResolvedValue(MOVES);
  vi.mocked(getVideoPlaybackUrl).mockResolvedValue('https://r2.test/video.mp4');
  vi.mocked(getStrategyForMove).mockResolvedValue(null);
  vi.mocked(getEnvironmentForMove).mockResolvedValue(null);
  vi.mocked(getOutcomeForMove).mockResolvedValue(null);
  vi.mocked(startAssignment).mockResolvedValue({ ...ASSIGNMENT, status: 'in_progress' });
  vi.mocked(createEnvironment).mockImplementation(async (d) => ({ id: 900, ...d }));
  vi.mocked(createOutcome).mockImplementation(async (d) => ({ id: 901, ...d }));
  vi.mocked(createStrategy).mockImplementation(async (d) => ({ id: 950, ...d }));
  vi.mocked(updateStrategy).mockImplementation(async (id, d) => ({ id, move_id: 21, ...d }));
  vi.mocked(updateEnvironment).mockImplementation(async (id, d) => ({ id, move_id: 21, ...d }));
  vi.mocked(updateOutcome).mockImplementation(async (id, d) => ({ id, move_id: 21, ...d }));
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

  it('is observer-only: no frame tagging, and the prepper\'s Strategy is not shown', async () => {
    await renderLoaded();

    expect(screen.queryByRole('button', { name: 'Tag Frames' })).not.toBeInTheDocument();
    expect(screen.queryByTitle('Add frame tags')).not.toBeInTheDocument();
    const card = screen.getByTestId('move-card-21');
    expect(card).toHaveTextContent('Move 1');
    expect(card).not.toHaveTextContent('Static');
    expect(card).not.toHaveTextContent('Dyno');
    expect(card).not.toHaveTextContent('Effort');
    expect(card).not.toHaveTextContent('first'); // the prepper's note
    // Strategy is one of the lenses the rater must finish.
    expect(screen.getByTestId('rating-status-21')).toHaveTextContent('Strategy');
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

async function openMove(user, moveId) {
  await user.click(within(screen.getByTestId(`move-card-${moveId}`)).getByRole('button', { name: /Rate|Edit rating/ }));
  return screen.findByTestId('rater-move-form');
}

async function fillEnvironmentAndOutcome(user, form) {
  const env = within(form).getByTestId('environment-lens');
  await user.click(within(env).getByRole('radio', { name: /Steep/ }));
  for (const slot of ['start_left', 'start_right', 'end']) {
    await user.click(within(screen.getByTestId(`hold-slot-${slot}`)).getByRole('radio', { name: /Jug/ }));
  }
  await user.selectOptions(within(form).getByRole('combobox', { name: 'Hold for Start Left' }), '101');
  const outcome = within(form).getByTestId('outcome-lens');
  await user.click(within(outcome).getByRole('radio', { name: /Success/ }));
  await user.click(within(outcome).getByRole('radio', { name: /Reached Controlled/ }));
  await user.click(within(outcome).getByRole('radio', { name: /^High/ }));
}

describe('RatingView — rating a move', () => {
  it('gives the rater editable Strategy fields with no effort input and no tagging', async () => {
    const user = userEvent.setup();
    await renderLoaded();
    const form = await openMove(user, 21);

    const strategy = within(form).getByTestId('strategy-lens');
    expect(within(strategy).getByRole('radio', { name: /Static/ })).not.toBeChecked();
    expect(within(strategy).getByRole('radio', { name: /Large/ })).toBeInTheDocument();
    expect(within(strategy).getByRole('button', { name: 'Dyno' })).toBeInTheDocument();
    expect(within(strategy).getByRole('group', { name: 'Form quality' })).toBeInTheDocument();
    // No effort for raters, and no sensation tagging.
    expect(within(form).queryByRole('slider')).not.toBeInTheDocument();
    expect(within(form).queryByText(/Effort/)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Tag Frames' })).not.toBeInTheDocument();
    expect(screen.queryByTestId('strategy-summary')).not.toBeInTheDocument();
  });

  it('pre-fills no hold slot from the pose data: raters pick holds from the locked set', async () => {
    const user = userEvent.setup();
    await renderLoaded();
    const form = await openMove(user, 21);

    await waitFor(() => expect(getStrategyForMove).toHaveBeenCalledWith(21));
    for (const label of ['Hold for Start Left', 'Hold for Start Right', 'Hold for End']) {
      expect(within(form).getByRole('combobox', { name: label })).toHaveValue('');
    }
    expect(within(form).queryByText('suggested')).not.toBeInTheDocument();
    // Hold slots pick only from the locked holds.
    const options = within(within(form).getByRole('combobox', { name: 'Hold for Start Left' }))
      .getAllByRole('option')
      .map((o) => o.textContent);
    expect(options).toEqual(['No hold chosen', 'Hold #101', 'Hold #102']);
  });

  it('requires Strategy before saving', async () => {
    const user = userEvent.setup();
    await renderLoaded();
    const form = await openMove(user, 21);

    await fillEnvironmentAndOutcome(user, form);
    await user.click(within(form).getByRole('button', { name: 'Save Rating' }));

    expect(await within(form).findByText('Please select Approach and Size')).toBeInTheDocument();
    expect(createStrategy).not.toHaveBeenCalled();
    expect(createEnvironment).not.toHaveBeenCalled();
  });

  it('creates Strategy + Environment + Outcome on first save, then updates all three', async () => {
    const user = userEvent.setup();
    await renderLoaded();
    const form = await openMove(user, 21);

    const strategy = within(form).getByTestId('strategy-lens');
    await user.click(within(strategy).getByRole('radio', { name: /Static/ }));
    await user.click(within(strategy).getByRole('radio', { name: /Small/ }));
    await user.click(within(strategy).getByRole('button', { name: 'Dyno' }));
    await user.click(within(strategy).getByRole('button', { name: '4' }));
    await fillEnvironmentAndOutcome(user, form);
    await user.click(within(form).getByRole('button', { name: 'Save Rating' }));

    await waitFor(() => expect(createOutcome).toHaveBeenCalled());
    expect(createStrategy).toHaveBeenCalledWith({
      move_id: 21,
      approach: 'static',
      size: 'small',
      move_tags: ['dyno'],
      form_quality: 4,
      confidence: null,
    });
    expect(createStrategy.mock.calls[0][0]).not.toHaveProperty('effort_level');
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
    // The card now counts the move as rated on all three lenses.
    expect(screen.getByTestId('rating-counts')).toHaveTextContent('1 of 2 moves rated');

    // Second save: PUT, never a second POST.
    await user.click(within(strategy).getByRole('radio', { name: /Large/ }));
    await user.click(within(strategy).getByRole('radio', { name: /^Low/ }));
    await user.click(within(form).getByRole('button', { name: 'Update Rating' }));

    await waitFor(() => expect(updateStrategy).toHaveBeenCalled());
    expect(updateStrategy).toHaveBeenCalledWith(950, {
      approach: 'static',
      size: 'large',
      move_tags: ['dyno'],
      form_quality: 4,
      confidence: 'low',
    });
    expect(updateEnvironment).toHaveBeenCalledWith(900, expect.objectContaining({ wall_angle: 'steep' }));
    expect(updateOutcome).toHaveBeenCalledWith(901, expect.objectContaining({ result: 'success' }));
    expect(createStrategy).toHaveBeenCalledTimes(1);
    expect(createEnvironment).toHaveBeenCalledTimes(1);
    expect(createOutcome).toHaveBeenCalledTimes(1);
  });

  it('loads an existing Strategy row and updates it', async () => {
    vi.mocked(getStrategyForMove).mockResolvedValue({
      id: 77, move_id: 21, approach: 'dynamic', size: 'large', move_tags: ['no_hands'], form_quality: 2, confidence: 'high',
    });
    const user = userEvent.setup();
    await renderLoaded();
    const form = await openMove(user, 21);

    const strategy = within(form).getByTestId('strategy-lens');
    await waitFor(() => expect(within(strategy).getByRole('radio', { name: /Dynamic/ })).toBeChecked());
    expect(within(strategy).getByRole('button', { name: 'No Hands' })).toHaveAttribute('aria-pressed', 'true');
    expect(within(strategy).getByRole('button', { name: '2' })).toHaveAttribute('aria-pressed', 'true');
    // The rater's own No Hands tag hides the hand slots.
    expect(screen.queryByTestId('hold-slot-start_left')).not.toBeInTheDocument();
    expect(within(form).getByRole('button', { name: 'Update Rating' })).toBeInTheDocument();
  });
});

describe('RatingView — Complete', () => {
  it('renders the 422 missing list inline, per move', async () => {
    vi.mocked(completeAssignment).mockResolvedValue({
      incomplete: true,
      detail: '2 of 2 moves are incomplete',
      missing: [
        { move_id: 21, move_index: 0, missing: ['strategy'] },
        { move_id: 22, move_index: 1, missing: ['strategy', 'environment', 'outcome'] },
      ],
    });
    const user = userEvent.setup();
    await renderLoaded();

    await user.click(screen.getByRole('button', { name: 'Complete' }));

    const box = await screen.findByTestId('complete-error');
    expect(box).toHaveTextContent('2 of 2 moves are incomplete');
    expect(box).toHaveTextContent('Move 1: missing Strategy');
    expect(box).toHaveTextContent('Move 2: missing Strategy, Environment and Outcome');
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
    expect(within(within(form).getByTestId('strategy-lens')).getByRole('radio', { name: /Static/ })).toBeDisabled();
  });
});
