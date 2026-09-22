/**
 * The status poll: 5-second cadence, stops on done/failed, loads the CSV and
 * corrects provisional frame numbers when the worker reports a different fps.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import useStore from '../store/useStore';
import usePoseStatus, { POLL_INTERVAL_MS, movesToRescale, rescaleFrame } from './usePoseStatus';
import * as client from '../api/client';

vi.mock('../api/client', () => ({
  getPoseStatus: vi.fn(),
  retryPose: vi.fn(),
  fetchPoseCsvText: vi.fn(),
  updateMove: vi.fn(),
}));

const VIDEO = { id: 7, filename: 'a.mov', fps: 30, total_frames: 130, width: 1080, height: 1920 };

const statusOf = (pose_status, extra = {}) => ({
  video_id: 7, pose_status, pose_error: null, pose_started_at: null, pose_finished_at: null,
  fps: 30, total_frames: 130, duration_ms: 4338, width: 1080, height: 1920, r2_pose_csv_key: null,
  ...extra,
});

beforeEach(() => {
  useStore.getState().resetForSignOut();
  useStore.setState({ currentVideo: VIDEO, poseStatus: null, csvData: null, moves: [] });
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

const flush = async () => {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
};

describe('usePoseStatus', () => {
  it('polls every 5 seconds while pending/processing and stops on done', async () => {
    client.getPoseStatus
      .mockResolvedValueOnce(statusOf('pending'))
      .mockResolvedValueOnce(statusOf('processing'))
      .mockResolvedValueOnce(statusOf('done', { r2_pose_csv_key: 'pose/u/7.csv' }));
    client.fetchPoseCsvText.mockResolvedValue('frame_number,timestamp_ms,landmark_nose_x\n0,0,1\n1,33,2');

    const { result } = renderHook(() => usePoseStatus());
    await flush();
    expect(client.getPoseStatus).toHaveBeenCalledTimes(1);
    expect(result.current.state).toBe('pending');

    await act(async () => { vi.advanceTimersByTime(POLL_INTERVAL_MS - 1); });
    expect(client.getPoseStatus).toHaveBeenCalledTimes(1);
    await act(async () => { vi.advanceTimersByTime(1); });
    await flush();
    expect(client.getPoseStatus).toHaveBeenCalledTimes(2);
    expect(result.current.state).toBe('processing');

    await act(async () => { vi.advanceTimersByTime(POLL_INTERVAL_MS); });
    await flush();
    expect(client.getPoseStatus).toHaveBeenCalledTimes(3);
    expect(result.current.isDone).toBe(true);
    expect(useStore.getState().csvData).toHaveLength(2);
    expect(useStore.getState().currentVideo.pose_status).toBe('done');

    await act(async () => { vi.advanceTimersByTime(POLL_INTERVAL_MS * 3); });
    expect(client.getPoseStatus).toHaveBeenCalledTimes(3);
  });

  it('stops polling on failed and exposes the error and a retry', async () => {
    client.getPoseStatus.mockResolvedValueOnce(statusOf('failed', { pose_error: 'worker not configured' }));
    client.retryPose.mockResolvedValue(statusOf('pending'));

    const { result } = renderHook(() => usePoseStatus());
    await flush();
    expect(result.current.state).toBe('failed');
    expect(result.current.poseError).toBe('worker not configured');

    await act(async () => { vi.advanceTimersByTime(POLL_INTERVAL_MS * 2); });
    expect(client.getPoseStatus).toHaveBeenCalledTimes(1);

    client.getPoseStatus.mockResolvedValue(statusOf('processing'));
    await act(async () => { await result.current.retry(); });
    await flush();
    await flush();
    expect(client.retryPose).toHaveBeenCalledWith(7);
    // The retry restarts the poll loop.
    expect(client.getPoseStatus).toHaveBeenCalledTimes(2);
    expect(result.current.state).toBe('processing');
  });

  it('adopts the measured fps and rescales saved moves and the selection', async () => {
    useStore.setState({
      moves: [
        { id: 1, frame_start: 30, frame_end: 60, timestamp_start_ms: 1000, timestamp_end_ms: 2000 },
        { id: 2, frame_start: 3, frame_end: 6, timestamp_start_ms: 100, timestamp_end_ms: 200 },
      ],
      moveStart: 15,
      moveEnd: null,
      currentFrame: 45,
    });
    client.getPoseStatus.mockResolvedValueOnce(
      statusOf('done', { fps: 60, total_frames: 260, width: 1080, height: 1920, r2_pose_csv_key: 'k' })
    );
    client.updateMove.mockImplementation(async (id, fields) => ({ id, ...fields }));
    client.fetchPoseCsvText.mockResolvedValue('frame_number,timestamp_ms\n0,0');

    renderHook(() => usePoseStatus());
    for (let i = 0; i < 4; i++) await flush();

    const state = useStore.getState();
    expect(state.currentVideo.fps).toBe(60);
    expect(state.currentVideo.total_frames).toBe(260);
    expect(state.moveStart).toBe(30);
    expect(state.moveEnd).toBeNull();
    expect(state.currentFrame).toBe(90);
    expect(client.updateMove).toHaveBeenCalledWith(1, { frame_start: 60, frame_end: 120 });
    expect(client.updateMove).toHaveBeenCalledWith(2, { frame_start: 6, frame_end: 12 });
    expect(state.moves[0]).toMatchObject({ frame_start: 60, frame_end: 120 });
    expect(state.moves[1]).toMatchObject({ frame_start: 6, frame_end: 12 });
    expect(state.csvData).toHaveLength(1);
  });

  it('does not touch moves when the fps was right all along', async () => {
    useStore.setState({
      moves: [{ id: 1, frame_start: 30, frame_end: 60, timestamp_start_ms: 1000, timestamp_end_ms: 2000 }],
    });
    client.getPoseStatus.mockResolvedValueOnce(statusOf('done', { fps: 30, r2_pose_csv_key: 'k' }));
    client.fetchPoseCsvText.mockResolvedValue('frame_number,timestamp_ms\n0,0');
    renderHook(() => usePoseStatus());
    await flush();
    await flush();
    expect(client.updateMove).not.toHaveBeenCalled();
  });

  it('keeps polling through a transient status failure', async () => {
    client.getPoseStatus
      .mockRejectedValueOnce(new Error('Network Error'))
      .mockResolvedValueOnce(statusOf('pending'));
    const { result } = renderHook(() => usePoseStatus());
    await flush();
    expect(result.current.error).toBe('Network Error');
    await act(async () => { vi.advanceTimersByTime(POLL_INTERVAL_MS); });
    await flush();
    expect(client.getPoseStatus).toHaveBeenCalledTimes(2);
    expect(result.current.error).toBeNull();
  });
});

describe('rescale helpers', () => {
  it('rescaleFrame goes through time', () => {
    expect(rescaleFrame(30, 30, 60)).toBe(60);
    expect(rescaleFrame(45, 30, 24)).toBe(36);
    expect(rescaleFrame(45, 30, 30)).toBe(45);
    expect(rescaleFrame(45, 0, 30)).toBe(45);
  });

  it('movesToRescale trusts timestamps', () => {
    const moves = [
      { id: 1, frame_start: 30, frame_end: 60, timestamp_start_ms: 1000, timestamp_end_ms: 2000 },
      { id: 2, frame_start: 60, frame_end: 120, timestamp_start_ms: 1000, timestamp_end_ms: 2000 },
    ];
    expect(movesToRescale(moves, 60)).toEqual([{ move: moves[0], fields: { frame_start: 60, frame_end: 120 } }]);
    expect(movesToRescale(moves, 0)).toEqual([]);
  });
});
