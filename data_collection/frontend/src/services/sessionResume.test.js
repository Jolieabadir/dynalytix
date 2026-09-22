/**
 * What survives an eviction.
 *
 * The contract these pin down: only a pointer is kept in the browser, and a
 * pointer the server will not honour is dropped rather than retried.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../api/client', () => ({
  getVideo: vi.fn(),
  getHolds: vi.fn(),
  getMoves: vi.fn(),
  getVideoPlaybackUrl: vi.fn(),
}));

import { getVideo, getHolds, getMoves, getVideoPlaybackUrl } from '../api/client';
import { rememberSession, readSession, forgetSession, restoreSession } from './sessionResume';

beforeEach(() => {
  localStorage.clear();
  vi.clearAllMocks();
});

describe('remembering', () => {
  it('keeps only the pointer, never the labels', () => {
    rememberSession({ videoId: 42, view: 'rating', assignmentId: 7 });
    const saved = readSession();
    expect(saved.videoId).toBe(42);
    expect(saved.view).toBe('rating');
    expect(saved.assignmentId).toBe(7);
    // Nothing resembling label data is in there.
    expect(JSON.stringify(saved)).not.toMatch(/move|environment|outcome/i);
  });

  it('a null snapshot clears it', () => {
    rememberSession({ videoId: 42, view: 'videos' });
    rememberSession(null);
    expect(readSession()).toBeNull();
  });

  it('reads back nothing when there is nothing', () => {
    expect(readSession()).toBeNull();
  });

  it('survives corrupt storage', () => {
    localStorage.setItem('dynalytix.session', '{{');
    expect(readSession()).toBeNull();
  });

  it('forgetSession removes it', () => {
    rememberSession({ videoId: 1, view: 'videos' });
    forgetSession();
    expect(readSession()).toBeNull();
  });
});

describe('restoring', () => {
  it('re-fetches the video, holds and moves from the server', async () => {
    getVideo.mockResolvedValue({ id: 42, fps: 30 });
    getHolds.mockResolvedValue([{ id: 1 }]);
    getMoves.mockResolvedValue([{ id: 9 }]);
    getVideoPlaybackUrl.mockResolvedValue('https://r2/video');

    const restored = await restoreSession({ videoId: 42 });

    expect(restored.video.id).toBe(42);
    expect(restored.holds).toHaveLength(1);
    expect(restored.moves).toHaveLength(1);
    expect(restored.playbackUrl).toBe('https://r2/video');
  });

  it('a missing original still gives back a usable session', async () => {
    getVideo.mockResolvedValue({ id: 42 });
    getHolds.mockResolvedValue([]);
    getMoves.mockResolvedValue([{ id: 9 }]);
    getVideoPlaybackUrl.mockRejectedValue(new Error('gone'));

    const restored = await restoreSession({ videoId: 42 });
    expect(restored.playbackUrl).toBeNull();
    expect(restored.moves).toHaveLength(1);
  });

  it('a video the server will not serve is forgotten, not retried', async () => {
    rememberSession({ videoId: 42, view: 'rating' });
    getVideo.mockRejectedValue(Object.assign(new Error('nope'), { response: { status: 404 } }));

    expect(await restoreSession({ videoId: 42 })).toBeNull();
    expect(readSession()).toBeNull();
  });

  it('nothing to restore is not an error', async () => {
    expect(await restoreSession(null)).toBeNull();
    expect(getVideo).not.toHaveBeenCalled();
  });
});
