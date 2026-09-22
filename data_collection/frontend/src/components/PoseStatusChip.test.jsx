/**
 * The header chip: upload progress first, then the worker's state, with a
 * retry only when the job failed.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import PoseStatusChip from './PoseStatusChip';
import useStore from '../store/useStore';
import * as client from '../api/client';

vi.mock('../api/client', () => ({
  getPoseStatus: vi.fn(),
  retryPose: vi.fn(),
  fetchPoseCsvText: vi.fn(),
  updateMove: vi.fn(),
}));

const VIDEO = { id: 3, filename: 'a.mov', fps: 30, total_frames: 90 };
const statusOf = (pose_status, extra = {}) => ({
  video_id: 3, pose_status, pose_error: null, fps: 30, total_frames: 90, ...extra,
});

beforeEach(() => {
  useStore.getState().resetForSignOut();
  useStore.setState({ currentVideo: VIDEO });
  client.getPoseStatus.mockResolvedValue(statusOf('pending'));
});

describe('PoseStatusChip', () => {
  it('renders nothing without a video', () => {
    useStore.setState({ currentVideo: null });
    render(<PoseStatusChip />);
    expect(screen.queryByTestId('pose-status-chip')).not.toBeInTheDocument();
  });

  it('shows upload progress while the file is going up', async () => {
    useStore.setState({ upload: { state: 'uploading', fraction: 0.42, error: null } });
    render(<PoseStatusChip />);
    expect(await screen.findByText('Uploading video… 42%')).toBeInTheDocument();
  });

  it('shows the queued state, then processing from the poll', async () => {
    client.getPoseStatus.mockResolvedValueOnce(statusOf('processing'));
    render(<PoseStatusChip />);
    expect(await screen.findByText('Extracting pose on the server…')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /retry/i })).not.toBeInTheDocument();
  });

  it('turns green on done', async () => {
    client.getPoseStatus.mockResolvedValueOnce(statusOf('done', { r2_pose_csv_key: 'k' }));
    client.fetchPoseCsvText.mockResolvedValue('frame_number,timestamp_ms\n0,0');
    render(<PoseStatusChip />);
    const chip = await screen.findByTestId('pose-status-chip');
    await waitFor(() => expect(chip).toHaveTextContent('Pose ready'));
    expect(chip.className).toContain('pose-chip-done');
  });

  it('shows the error and a retry button on failed, and retries', async () => {
    const user = userEvent.setup();
    client.getPoseStatus.mockResolvedValueOnce(statusOf('failed', { pose_error: 'worker unreachable: ConnectError' }));
    client.retryPose.mockResolvedValue(statusOf('pending'));
    render(<PoseStatusChip />);

    expect(await screen.findByText('Pose extraction failed')).toBeInTheDocument();
    expect(screen.getByText('worker unreachable: ConnectError')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Retry' }));
    expect(client.retryPose).toHaveBeenCalledWith(3);
    await waitFor(() => expect(screen.getByText('Pose extraction queued')).toBeInTheDocument());
  });

  it('reports an upload failure without a pose retry', async () => {
    useStore.setState({ upload: { state: 'failed', fraction: 0.2, error: 'Video upload failed (403)' } });
    render(<PoseStatusChip />);
    expect(await screen.findByText('Upload failed')).toBeInTheDocument();
    expect(screen.getByText('Video upload failed (403)')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /retry/i })).not.toBeInTheDocument();
  });
});
