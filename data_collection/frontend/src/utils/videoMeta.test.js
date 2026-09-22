import { describe, it, expect } from 'vitest';
import { provisionalRegisterPayload, PROVISIONAL_FPS } from './videoMeta';

describe('provisionalRegisterPayload', () => {
  it('sends the browser-measurable fields and a provisional 30fps', () => {
    const file = new File(['x'], 'IMG_1.mov', { type: 'video/quicktime' });
    const payload = provisionalRegisterPayload(file, { durationSeconds: 4.338, width: 1080, height: 1920 });
    expect(PROVISIONAL_FPS).toBe(30);
    expect(payload).toEqual({
      filename: 'IMG_1.mov',
      fps: 30,
      total_frames: 130,
      duration_ms: 4338,
      width: 1080,
      height: 1920,
    });
    expect(payload).not.toHaveProperty('csv_data');
  });

  it('sends null dimensions when the element could not measure them', () => {
    const file = new File(['x'], 'a.mp4', { type: 'video/mp4' });
    const payload = provisionalRegisterPayload(file, { durationSeconds: 0, width: 0, height: 0 });
    expect(payload.width).toBeNull();
    expect(payload.height).toBeNull();
    expect(payload.total_frames).toBe(0);
  });
});
