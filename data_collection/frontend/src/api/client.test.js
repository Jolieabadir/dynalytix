/**
 * client.js — the Dataset A helpers that do more than wrap one axios call.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('./auth', () => ({
  authHeader: vi.fn(async () => ({ Authorization: 'Bearer tok' })),
  requireAccessToken: vi.fn(),
  refreshSession: vi.fn(),
}));

import { downloadAdminExport, completeAssignment, getMyProfile } from './client';
import api from './client';

describe('downloadAdminExport', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn());
  });

  it('fetches with the bearer token and hands the blob to the saver with the server filename', async () => {
    const body = 'video_id,dataset\n1,A\n';
    vi.mocked(fetch).mockResolvedValue({
      ok: true,
      headers: { get: (k) => (k === 'Content-Disposition' ? 'attachment; filename="dynalytix_long.csv"' : null) },
      blob: async () => new Blob([body], { type: 'text/csv' }),
    });
    const saveBlob = vi.fn();

    const name = await downloadAdminExport('long', { dataset: 'A' }, saveBlob);

    expect(name).toBe('dynalytix_long.csv');
    const [url, init] = vi.mocked(fetch).mock.calls[0];
    expect(url).toMatch(/\/api\/admin\/export\/long\?dataset=A$/);
    expect(init.headers).toEqual({ Authorization: 'Bearer tok' });
    expect(saveBlob).toHaveBeenCalledWith(expect.any(Blob), 'dynalytix_long.csv');
    expect(await saveBlob.mock.calls[0][0].text()).toBe(body);
  });

  it('narrows by video_id and falls back to a default filename', async () => {
    vi.mocked(fetch).mockResolvedValue({
      ok: true,
      headers: { get: () => null },
      blob: async () => new Blob(['x']),
    });
    const saveBlob = vi.fn();

    await downloadAdminExport('full', { video_id: 7 }, saveBlob);

    expect(vi.mocked(fetch).mock.calls[0][0]).toMatch(/\/api\/admin\/export\/full\?video_id=7$/);
    expect(saveBlob).toHaveBeenCalledWith(expect.any(Blob), 'dynalytix_full.csv');
  });

  it('throws the server detail on a non-OK response and saves nothing', async () => {
    vi.mocked(fetch).mockResolvedValue({
      ok: false,
      status: 403,
      headers: { get: () => null },
      json: async () => ({ detail: 'Admin only' }),
    });
    const saveBlob = vi.fn();

    await expect(downloadAdminExport('long', {}, saveBlob)).rejects.toThrow('Admin only');
    expect(saveBlob).not.toHaveBeenCalled();
  });
});

describe('completeAssignment', () => {
  it('returns the 422 missing list as a value, not an exception', async () => {
    const post = vi.spyOn(api, 'post').mockRejectedValue({
      response: { status: 422, data: { detail: '1 of 2 moves are incomplete', missing: [{ move_id: 3, move_index: 1, missing: ['outcome'] }] } },
    });

    const result = await completeAssignment(9);

    expect(post).toHaveBeenCalledWith('/api/assignments/9/complete');
    expect(result).toEqual({
      incomplete: true,
      detail: '1 of 2 moves are incomplete',
      missing: [{ move_id: 3, move_index: 1, missing: ['outcome'] }],
    });
    post.mockRestore();
  });

  it('returns the assignment on 200 and rethrows anything else', async () => {
    const post = vi.spyOn(api, 'post').mockResolvedValue({ data: { id: 9, status: 'done' } });
    expect(await completeAssignment(9)).toEqual({ incomplete: false, assignment: { id: 9, status: 'done' } });

    post.mockRejectedValue({ response: { status: 404, data: { detail: 'nope' } } });
    await expect(completeAssignment(9)).rejects.toBeTruthy();
    post.mockRestore();
  });
});

describe('getMyProfile', () => {
  it('maps a 404 to null so the app can open the profile gate', async () => {
    const get = vi.spyOn(api, 'get').mockRejectedValue({ response: { status: 404 } });
    expect(await getMyProfile()).toBeNull();
    get.mockRestore();
  });
});
