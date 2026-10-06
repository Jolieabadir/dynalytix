/**
 * client.js — the Dataset A helpers that do more than wrap one axios call.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('./auth', () => ({
  authHeader: vi.fn(async () => ({ Authorization: 'Bearer tok' })),
  requireAccessToken: vi.fn(),
  refreshSession: vi.fn(),
}));

import {
  downloadAdminExport,
  completeAssignment,
  getMyProfile,
  createStrategy,
  getStrategyForMove,
  updateStrategy,
  adminListAthletes,
  adminCreateAthlete,
  adminUpdateAthlete,
  adminSetOverlap,
  adminSetCameraOverride,
  adminCreateAssignment,
} from './client';
import api from './client';

describe('downloadAdminExport', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn());
  });

  it('fetches with the bearer token and hands the blob to the saver with the server filename', async () => {
    const body = 'video_id,irr_overlap\n1,true\n';
    vi.mocked(fetch).mockResolvedValue({
      ok: true,
      headers: { get: (k) => (k === 'Content-Disposition' ? 'attachment; filename="dynalytix_long.csv"' : null) },
      blob: async () => new Blob([body], { type: 'text/csv' }),
    });
    const saveBlob = vi.fn();

    const name = await downloadAdminExport('long', {}, saveBlob);

    expect(name).toBe('dynalytix_long.csv');
    const [url, init] = vi.mocked(fetch).mock.calls[0];
    expect(url).toMatch(/\/api\/admin\/export\/long$/);
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

  it('sends include_community and overlap_only as query flags (overlap only on long)', async () => {
    vi.mocked(fetch).mockResolvedValue({
      ok: true,
      headers: { get: () => null },
      blob: async () => new Blob(['x']),
    });
    const saveBlob = vi.fn();

    await downloadAdminExport('long', { include_community: true, overlap_only: true }, saveBlob);
    expect(vi.mocked(fetch).mock.calls[0][0]).toMatch(
      /\/api\/admin\/export\/long\?include_community=true&overlap_only=true$/
    );

    await downloadAdminExport('full', { include_community: true, overlap_only: true }, saveBlob);
    expect(vi.mocked(fetch).mock.calls[1][0]).toMatch(/\/api\/admin\/export\/full\?include_community=true$/);

    // Unset flags are not sent at all (the server defaults them to false).
    await downloadAdminExport('long', { include_community: false, overlap_only: false }, saveBlob);
    expect(vi.mocked(fetch).mock.calls[2][0]).toMatch(/\/api\/admin\/export\/long$/);
    expect(vi.mocked(fetch).mock.calls[2][0]).not.toMatch(/dataset/);
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

describe('strategies (per rater)', () => {
  it('creates, reads and updates the caller\'s strategy row', async () => {
    const payload = { move_id: 4, approach: 'static', size: 'small', move_tags: ['dyno'], form_quality: 4, confidence: 'high' };
    const post = vi.spyOn(api, 'post').mockResolvedValue({ data: { id: 70, ...payload } });
    const get = vi.spyOn(api, 'get').mockResolvedValue({ data: { id: 70, ...payload } });
    const put = vi.spyOn(api, 'put').mockResolvedValue({ data: { id: 70, ...payload, size: 'large' } });

    expect(await createStrategy(payload)).toEqual({ id: 70, ...payload });
    expect(post).toHaveBeenCalledWith('/api/strategies', payload);

    expect(await getStrategyForMove(4)).toEqual({ id: 70, ...payload });
    expect(get).toHaveBeenCalledWith('/api/moves/4/strategy');

    expect((await updateStrategy(70, { size: 'large' })).size).toBe('large');
    expect(put).toHaveBeenCalledWith('/api/strategies/70', { size: 'large' });

    post.mockRestore();
    get.mockRestore();
    put.mockRestore();
  });

  it('maps a 404 on GET to null, like the other lenses, and rethrows anything else', async () => {
    const get = vi.spyOn(api, 'get').mockRejectedValue({ response: { status: 404 } });
    expect(await getStrategyForMove(4)).toBeNull();
    get.mockRejectedValue({ response: { status: 403 } });
    await expect(getStrategyForMove(4)).rejects.toBeTruthy();
    get.mockRestore();
  });
});

describe('athletes (admin)', () => {
  it('lists, creates and updates athletes', async () => {
    const athlete = { athlete_id: 'a-1', ifsc_profile_url: 'https://ifsc.test/1', height_cm: 170, height_source: 'ifsc_profile', birth_year: 1999, category: 'women' };
    const get = vi.spyOn(api, 'get').mockResolvedValue({ data: [athlete] });
    const post = vi.spyOn(api, 'post').mockResolvedValue({ data: athlete });
    const put = vi.spyOn(api, 'put').mockResolvedValue({ data: { ...athlete, height_cm: 171 } });

    expect(await adminListAthletes()).toEqual([athlete]);
    expect(get).toHaveBeenCalledWith('/api/admin/athletes');

    const fields = { ifsc_profile_url: 'https://ifsc.test/1', height_cm: 170, birth_year: 1999, category: 'women' };
    expect(await adminCreateAthlete(fields)).toEqual(athlete);
    expect(post).toHaveBeenCalledWith('/api/admin/athletes', fields);

    expect((await adminUpdateAthlete('a-1', { height_cm: 171 })).height_cm).toBe(171);
    expect(put).toHaveBeenCalledWith('/api/admin/athletes/a-1', { height_cm: 171 });

    get.mockRestore();
    post.mockRestore();
    put.mockRestore();
  });
});

describe('admin video + assignment helpers', () => {
  it('adminSetOverlap PUTs a boolean irr_overlap', async () => {
    const put = vi.spyOn(api, 'put').mockResolvedValue({ data: { id: 3, irr_overlap: true, rater_target: 3 } });
    expect(await adminSetOverlap(3, true)).toEqual({ id: 3, irr_overlap: true, rater_target: 3 });
    expect(put).toHaveBeenCalledWith('/api/admin/videos/3/overlap', { irr_overlap: true });
    put.mockRestore();
  });

  it('adminSetCameraOverride PUTs the flag and the note (null when empty)', async () => {
    const put = vi.spyOn(api, 'put').mockResolvedValue({ data: { id: 3, camera_override: true } });
    await adminSetCameraOverride(3, true, 'pan before move 1');
    expect(put).toHaveBeenCalledWith('/api/admin/videos/3/camera-override', { override: true, note: 'pan before move 1' });
    await adminSetCameraOverride(3, false);
    expect(put).toHaveBeenLastCalledWith('/api/admin/videos/3/camera-override', { override: false, note: null });
    put.mockRestore();
  });

  it('adminCreateAssignment sends no cohort', async () => {
    const post = vi.spyOn(api, 'post').mockResolvedValue({ data: { id: 1 } });
    await adminCreateAssignment({ video_id: 2, rater_user_id: 'r-1', cohort: 'overlap' });
    expect(post).toHaveBeenCalledWith('/api/admin/assignments', { video_id: 2, rater_user_id: 'r-1' });
    post.mockRestore();
  });
});
