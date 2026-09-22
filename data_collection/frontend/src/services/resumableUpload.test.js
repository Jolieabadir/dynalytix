/**
 * The resumable uploader's bookkeeping.
 *
 * The network half is covered by the backend's multipart tests; what matters
 * here is the part arithmetic and the saved session, because those are what
 * decide whether a locked phone resumes or starts the clip over.
 */
import { describe, it, expect, beforeEach } from 'vitest';
import {
  partRange,
  partCount,
  fileSignature,
  resumableSessionFor,
  clearSession,
  RESUMABLE_THRESHOLD_BYTES,
} from './resumableUpload';

const MiB = 1024 * 1024;

function fakeFile({ name = 'climb.mov', size = 20 * MiB, lastModified = 1700000000000 } = {}) {
  return { name, size, lastModified, type: 'video/quicktime' };
}

function saveSession(videoId, session) {
  localStorage.setItem(`dynalytix.upload.${videoId}`, JSON.stringify(session));
}

beforeEach(() => {
  localStorage.clear();
});

describe('part arithmetic', () => {
  it('splits a file into whole parts, the last one short', () => {
    expect(partCount(20 * MiB, 8 * MiB)).toBe(3);
    expect(partRange(1, 8 * MiB, 20 * MiB)).toEqual({ start: 0, end: 8 * MiB });
    expect(partRange(2, 8 * MiB, 20 * MiB)).toEqual({ start: 8 * MiB, end: 16 * MiB });
    expect(partRange(3, 8 * MiB, 20 * MiB)).toEqual({ start: 16 * MiB, end: 20 * MiB });
  });

  it('never reads past the end of the file', () => {
    const { end } = partRange(3, 8 * MiB, 17 * MiB);
    expect(end).toBe(17 * MiB);
  });

  it('a file smaller than one part is still one part', () => {
    expect(partCount(100, 8 * MiB)).toBe(1);
  });

  it('an exact multiple does not produce a trailing empty part', () => {
    expect(partCount(16 * MiB, 8 * MiB)).toBe(2);
  });

  it('the threshold clears R2 minimum part size', () => {
    expect(RESUMABLE_THRESHOLD_BYTES).toBeGreaterThanOrEqual(5 * MiB);
  });
});

describe('file signature', () => {
  it('changes when the file does', () => {
    const a = fileSignature(fakeFile());
    expect(fileSignature(fakeFile())).toBe(a);
    expect(fileSignature(fakeFile({ size: 21 * MiB }))).not.toBe(a);
    expect(fileSignature(fakeFile({ name: 'other.mov' }))).not.toBe(a);
    expect(fileSignature(fakeFile({ lastModified: 1 }))).not.toBe(a);
  });
});

describe('saved session', () => {
  it('is returned when the same file is picked again — this is the resume', () => {
    const file = fakeFile();
    saveSession(7, {
      upload_id: 'u-1',
      key: 'videos/me/7/climb.mov',
      part_size: 8 * MiB,
      signature: fileSignature(file),
      parts: { 1: '"a"', 2: '"b"' },
    });

    const session = resumableSessionFor(7, file);
    expect(session).not.toBeNull();
    expect(session.upload_id).toBe('u-1');
    expect(Object.keys(session.parts)).toEqual(['1', '2']);
  });

  it('is discarded when a different file is picked', () => {
    const file = fakeFile();
    saveSession(7, {
      upload_id: 'u-1',
      key: 'videos/me/7/climb.mov',
      part_size: 8 * MiB,
      signature: fileSignature(file),
      parts: { 1: '"a"' },
    });

    expect(resumableSessionFor(7, fakeFile({ name: 'different.mov' }))).toBeNull();
    // and the stale parts are gone, not left to corrupt a later upload
    expect(localStorage.getItem('dynalytix.upload.7')).toBeNull();
  });

  it('is null when there is nothing saved', () => {
    expect(resumableSessionFor(99, fakeFile())).toBeNull();
  });

  it('clearSession removes it', () => {
    const file = fakeFile();
    saveSession(7, { upload_id: 'u', key: 'k', part_size: 8 * MiB, signature: fileSignature(file), parts: {} });
    clearSession(7);
    expect(resumableSessionFor(7, file)).toBeNull();
  });

  it('survives corrupt JSON without throwing', () => {
    localStorage.setItem('dynalytix.upload.7', 'not json');
    expect(() => resumableSessionFor(7, fakeFile())).not.toThrow();
    expect(resumableSessionFor(7, fakeFile())).toBeNull();
  });
});
