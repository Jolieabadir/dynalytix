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

describe('VideoPlayer — undo hold edits', () => {
  const HOLD = { id: 7, bbox_x: 0.1, bbox_y: 0.1, bbox_w: 0.2, bbox_h: 0.2, source: 'detected' };

  it('starts disabled and brings a deleted hold back', async () => {
    const { createHold, deleteHold } = await import('../api/client');
    deleteHold.mockResolvedValue();
    createHold.mockResolvedValue({ ...HOLD, id: 8 });
    useStore.setState({ holds: [HOLD] });
    render(<VideoPlayer />);

    const undo = screen.getByRole('button', { name: 'Undo last hold edit' });
    expect(undo).toBeDisabled();

    fireEvent.click(screen.getByRole('button', { name: 'Delete hold 7' }));
    await vi.waitFor(() => expect(undo).not.toBeDisabled());
    expect(useStore.getState().holds).toEqual([]);

    fireEvent.click(undo);
    await vi.waitFor(() => expect(useStore.getState().holds).toEqual([{ ...HOLD, id: 8 }]));
    expect(createHold).toHaveBeenCalledWith(1, {
      bbox_x: 0.1, bbox_y: 0.1, bbox_w: 0.2, bbox_h: 0.2, source: 'detected',
    });
    expect(undo).toBeDisabled();
  });

  it('says to box the holds first when there are none', () => {
    render(<VideoPlayer />);
    expect(screen.getByText('First, box the holds.')).toBeInTheDocument();
  });
});
