import { describe, it, expect } from 'vitest';
import { parseCsv } from './csv';

describe('parseCsv', () => {
  it('keys cells by header and keeps row N as frame N', () => {
    const rows = parseCsv('frame_number,timestamp_ms,landmark_nose_x\n0,0,12.5\n1,33.3,\n2,66.7,14');
    expect(rows).toHaveLength(3);
    expect(rows[0]).toEqual({ frame_number: '0', timestamp_ms: '0', landmark_nose_x: '12.5' });
    expect(rows[1].landmark_nose_x).toBe('');
    expect(rows[2].frame_number).toBe('2');
  });

  it('drops blank trailing lines and handles empty input', () => {
    expect(parseCsv('frame_number,timestamp_ms\n0,0\n')).toHaveLength(1);
    expect(parseCsv('')).toEqual([]);
    expect(parseCsv(null)).toEqual([]);
  });
});
