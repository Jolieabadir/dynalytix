/**
 * VideoPlayer after the skeleton removal: no skeleton overlay, no toggle,
 * and the `S` key is no longer a shortcut. `H` (hold boxes) still is.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';

vi.mock('../api/client', () => ({
  createHold: vi.fn(),
  deleteHold: vi.fn(),
  updateHold: vi.fn(),
}));

import VideoPlayer from './VideoPlayer';
import useStore from '../store/useStore';

beforeEach(() => {
  window.matchMedia = vi.fn().mockImplementation((query) => ({
    matches: false,
    media: query,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }));
  useStore.getState().resetVideoState();
  useStore.setState({
    currentVideo: { id: 1, fps: 30, total_frames: 300, width: 1920, height: 1080 },
    // Pose done and rows loaded: the old skeleton's exact trigger.
    poseStatus: { video_id: 1, pose_status: 'done' },
    csvData: [{ frame_number: '0' }],
    holds: [],
    showHoldOverlay: true,
  });
});

afterEach(() => {
  delete window.matchMedia;
});

describe('VideoPlayer — no skeleton', () => {
  it('renders no skeleton overlay and no skeleton toggle, even with pose data loaded', () => {
    const { container } = render(<VideoPlayer />);

    expect(container.querySelector('canvas')).toBeNull();
    expect(screen.queryByRole('button', { name: /skeleton/i })).not.toBeInTheDocument();
    expect(screen.queryByText(/skeleton/i)).not.toBeInTheDocument();
    // The hold toggle is still there.
    expect(screen.getByRole('button', { name: /Holds/ })).toBeInTheDocument();
  });

  it('ignores the S key but still toggles holds with H', () => {
    render(<VideoPlayer />);

    const before = useStore.getState();
    const sEvent = new KeyboardEvent('keydown', { key: 's', bubbles: true, cancelable: true });
    window.dispatchEvent(sEvent);
    expect(sEvent.defaultPrevented).toBe(false);
    expect(useStore.getState().showHoldOverlay).toBe(before.showHoldOverlay);

    fireEvent.keyDown(window, { key: 'h' });
    expect(useStore.getState().showHoldOverlay).toBe(!before.showHoldOverlay);
  });
});
