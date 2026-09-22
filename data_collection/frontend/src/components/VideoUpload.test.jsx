/**
 * Zero-wait start: the labeler gets the player as soon as the video is
 * registered, and the upload/confirm runs behind it with progress.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import VideoUpload from './VideoUpload';
import useStore from '../store/useStore';
import * as client from '../api/client';
import * as videoMeta from '../utils/videoMeta';

vi.mock('../api/client', () => ({
  getMoves: vi.fn(),
  registerVideo: vi.fn(),
  uploadOriginalVideo: vi.fn(),
  createHoldsBulk: vi.fn(),
  getHolds: vi.fn(),
}));

vi.mock('../services/holdDetector', () => ({
  detectHolds: vi.fn(),
  HOLD_DETECTION_ENABLED: false,
}));

vi.mock('../utils/videoMeta', async (importOriginal) => {
  const actual = await importOriginal();
  return { ...actual, readVideoMetadata: vi.fn() };
});

const REGISTERED = {
  id: 11, filename: 'clip.mov', fps: 30, total_frames: 130, duration_ms: 4338,
  width: 1080, height: 1920, r2_video_key: null, r2_pose_csv_key: null, pose_status: 'pending', pose_error: null,
};

beforeEach(() => {
  useStore.getState().resetForSignOut();
  window.URL.createObjectURL = vi.fn(() => 'blob:clip');
  window.URL.revokeObjectURL = vi.fn();
  videoMeta.readVideoMetadata.mockResolvedValue({ durationSeconds: 4.338, width: 1080, height: 1920 });
  client.registerVideo.mockResolvedValue(REGISTERED);
  client.getMoves.mockResolvedValue([]);
  client.getHolds.mockResolvedValue([]);
});

const pick = async (user) => {
  const file = new File(['bytes'], 'clip.mov', { type: 'video/quicktime' });
  await user.upload(document.querySelector('#video-upload'), file);
  return file;
};

describe('VideoUpload', () => {
  it('registers with provisional metadata and no CSV, then hands over the player before the upload finishes', async () => {
    const user = userEvent.setup();
    let finishUpload;
    client.uploadOriginalVideo.mockImplementation(
      () => new Promise((resolve) => { finishUpload = resolve; })
    );

    render(<VideoUpload />);
    await pick(user);

    await waitFor(() => expect(useStore.getState().currentVideo?.id).toBe(11));
    expect(client.registerVideo).toHaveBeenCalledTimes(1);
    const [payload] = client.registerVideo.mock.calls[0];
    expect(payload).toEqual({
      filename: 'clip.mov', fps: 30, total_frames: 130, duration_ms: 4338, width: 1080, height: 1920,
    });
    expect(payload).not.toHaveProperty('csv_data');

    // The player is live while the upload is still in flight.
    expect(useStore.getState().videoBlobUrl).toBe('blob:clip');
    expect(useStore.getState().upload.state).toBe('uploading');
    expect(useStore.getState().poseStatus).toMatchObject({ video_id: 11, pose_status: 'pending' });
    expect(client.uploadOriginalVideo).toHaveBeenCalledWith(11, expect.any(File), expect.objectContaining({ onProgress: expect.any(Function) }));

    // Progress flows into the store...
    const { onProgress } = client.uploadOriginalVideo.mock.calls[0][2];
    onProgress(0.5);
    expect(useStore.getState().upload.fraction).toBe(0.5);

    // ...and confirm's answer (the worker took the job) lands as the status.
    finishUpload({ ...REGISTERED, r2_video_key: 'videos/u/11/clip.mov', pose_status: 'pending' });
    await waitFor(() => expect(useStore.getState().upload.state).toBe('done'));
    expect(useStore.getState().poseStatus.pose_status).toBe('pending');
  });

  it('surfaces a failed enqueue from confirm-upload as the pose status', async () => {
    const user = userEvent.setup();
    client.uploadOriginalVideo.mockResolvedValue({
      ...REGISTERED, r2_video_key: 'videos/u/11/clip.mov', pose_status: 'failed',
      pose_error: 'worker not configured: set MODAL_ENDPOINT_URL and MODAL_WEBHOOK_SECRET',
    });
    render(<VideoUpload />);
    await pick(user);
    await waitFor(() => expect(useStore.getState().poseStatus?.pose_status).toBe('failed'));
    expect(useStore.getState().poseStatus.pose_error).toMatch(/worker not configured/);
    expect(useStore.getState().currentVideo.id).toBe(11);
  });

  it('marks the upload failed without losing the player', async () => {
    const user = userEvent.setup();
    client.uploadOriginalVideo.mockRejectedValue(new Error('Video upload failed (403)'));
    render(<VideoUpload />);
    await pick(user);
    await waitFor(() => expect(useStore.getState().upload.state).toBe('failed'));
    expect(useStore.getState().upload.error).toBe('Video upload failed (403)');
    expect(useStore.getState().currentVideo.id).toBe(11);
  });

  it('shows an error and stays on the picker when register fails', async () => {
    const user = userEvent.setup();
    client.registerVideo.mockRejectedValue(new Error('Failed to register video'));
    render(<VideoUpload />);
    await pick(user);
    expect(await screen.findByText('Failed to register video')).toBeInTheDocument();
    expect(useStore.getState().currentVideo).toBeNull();
    expect(window.URL.revokeObjectURL).toHaveBeenCalledWith('blob:clip');
    expect(client.uploadOriginalVideo).not.toHaveBeenCalled();
  });

  it('rejects a non-video file up front', async () => {
    render(<VideoUpload />);
    const input = document.querySelector('#video-upload');
    // userEvent honours `accept`, so drive the change event directly.
    const file = new File(['x'], 'notes.txt', { type: 'text/plain' });
    Object.defineProperty(input, 'files', { value: [file], configurable: true });
    fireEvent.change(input);
    expect(await screen.findByText('Unsupported file')).toBeInTheDocument();
    expect(client.registerVideo).not.toHaveBeenCalled();
  });
});
