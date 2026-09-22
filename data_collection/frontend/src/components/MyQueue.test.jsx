/**
 * MyQueue: the rater's assignments as /api/me/assignments returns them.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

vi.mock('../api/client', () => ({
  getMyAssignments: vi.fn(),
}));

import MyQueue from './MyQueue';
import useStore from '../store/useStore';
import { getMyAssignments } from '../api/client';

const ITEMS = [
  {
    assignment: {
      id: 11,
      video_id: 5,
      rater_user_id: 'u1',
      cohort: 'validated',
      status: 'assigned',
      assigned_at: '2026-09-20T10:00:00Z',
      completed_at: null,
    },
    video: { id: 5, filename: 'crimp_ladder.mp4', dataset: 'A', prep_status: 'ready', access_role: 'rater' },
    move_count: 3,
  },
  {
    assignment: {
      id: 12,
      video_id: 6,
      rater_user_id: 'u1',
      cohort: 'overlap',
      status: 'done',
      assigned_at: '2026-09-21T10:00:00Z',
      completed_at: '2026-09-22T10:00:00Z',
    },
    video: { id: 6, filename: 'slab_dance.mov', dataset: 'A', prep_status: 'ready', access_role: 'rater' },
    move_count: 4,
  },
];

beforeEach(() => {
  useStore.setState({ assignments: [] });
  vi.mocked(getMyAssignments).mockResolvedValue(ITEMS);
});

describe('MyQueue', () => {
  it('lists each assignment with filename, cohort, status and date', async () => {
    render(<MyQueue onOpen={() => {}} />);

    expect(await screen.findByText('crimp_ladder.mp4')).toBeInTheDocument();
    expect(screen.getByText('slab_dance.mov')).toBeInTheDocument();
    expect(screen.getByText('validated')).toBeInTheDocument();
    expect(screen.getByText('overlap')).toBeInTheDocument();
    expect(screen.getByText('Not started')).toBeInTheDocument();
    expect(screen.getByText('Done')).toBeInTheDocument();
    expect(useStore.getState().assignments).toHaveLength(2);
  });

  it('opens an assignment with its video when Rate is clicked', async () => {
    const user = userEvent.setup();
    const onOpen = vi.fn();
    render(<MyQueue onOpen={onOpen} />);

    await user.click(await screen.findByRole('button', { name: 'Rate' }));

    expect(onOpen).toHaveBeenCalledWith(
      expect.objectContaining({
        assignment: expect.objectContaining({ id: 11 }),
        video: expect.objectContaining({ id: 5 }),
      })
    );
    // A finished one offers Review instead.
    expect(screen.getByRole('button', { name: 'Review' })).toBeInTheDocument();
  });

  it('says so when nothing is assigned', async () => {
    vi.mocked(getMyAssignments).mockResolvedValue([]);
    render(<MyQueue onOpen={() => {}} />);
    expect(await screen.findByText(/Nothing assigned yet/)).toBeInTheDocument();
  });
});
