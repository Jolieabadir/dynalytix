/**
 * The iPhone-first pass, as behaviour rather than stylesheet.
 *
 * Everything here turns on one question — `(pointer: coarse)` — so each case
 * is run against a stubbed matchMedia, and the pointer-device expectations
 * are asserted alongside the touch ones: the constraint is one UI, and a
 * regression that "fixes" the phone by breaking the laptop must fail.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

vi.mock('../api/client', () => ({
  createMove: vi.fn(),
  createEnvironment: vi.fn(),
  createOutcome: vi.fn(),
  deleteMove: vi.fn(),
}));

import MoveForm from './MoveForm';
import HoldOverlay from './HoldOverlay';
import InstallPrompt from './InstallPrompt';
import OnboardingBanner, { BANNER_CAPTURE, BANNER_DEFINE } from './OnboardingBanner';
import useStore from '../store/useStore';

const CONFIG = {
  approaches: ['static', 'dynamic'],
  sizes: ['small', 'large'],
  move_tags: ['dyno'],
  wall_angles: ['slab', 'vertical'],
  hold_types: ['jug', 'pinch'],
  hold_qualities: ['incut'],
  hold_slots: ['start_left', 'start_right', 'end', 'foot'],
  hold_sources: ['detected', 'manual'],
  results: ['success', 'fall'],
  reach_details: ['reached_controlled', 'didnt_reach'],
  confidence_levels: ['low', 'high'],
  tag_types: {},
  body_parts: [],
  sides: [],
  definitions: {},
};

/** Point matchMedia at a finger or a mouse. */
function setPointer(kind) {
  window.matchMedia = vi.fn().mockImplementation((query) => ({
    matches: query.includes('pointer: coarse') ? kind === 'touch' : false,
    media: query,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }));
}

beforeEach(() => {
  useStore.setState({
    config: CONFIG,
    currentVideo: { id: 1, fps: 30, total_frames: 300 },
    moveStart: 10,
    moveEnd: 40,
    holds: [],
    holdPickSlot: null,
    csvData: null,
    dismissedBanners: {},
  });
});

afterEach(() => {
  delete window.matchMedia;
  delete window.navigator.standalone;
});

// ==================== STEPPED BOTTOM SHEET ====================

describe('MoveForm on a phone', () => {
  it('shows one lens at a time, starting at Environment', () => {
    setPointer('touch');
    render(<MoveForm />);

    expect(screen.getByTestId('sheet-stepper')).toHaveTextContent('Step 1 of 3');
    expect(screen.getByTestId('sheet-stepper')).toHaveTextContent('Environment');
    // Strategy's controls are not on this screen.
    expect(screen.queryByText('Approach')).not.toBeInTheDocument();
  });

  it('is a sheet, not the side panel', () => {
    setPointer('touch');
    render(<MoveForm />);
    expect(screen.getByTestId('move-form-panel').className).toContain('sheet');
  });

  it('Next walks Environment → Strategy → Outcome', async () => {
    setPointer('touch');
    const user = userEvent.setup();
    render(<MoveForm />);

    await user.click(screen.getByRole('button', { name: 'Next' }));
    expect(screen.getByTestId('sheet-stepper')).toHaveTextContent('Step 2 of 3');
    expect(screen.getByText('Approach')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Next' }));
    expect(screen.getByTestId('sheet-stepper')).toHaveTextContent('Step 3 of 3');
  });

  it('Save appears only on the last step', async () => {
    setPointer('touch');
    const user = userEvent.setup();
    render(<MoveForm />);

    expect(screen.queryByRole('button', { name: /Save Move/ })).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Next' }));
    await user.click(screen.getByRole('button', { name: 'Next' }));
    expect(screen.getByRole('button', { name: /Save Move/ })).toBeInTheDocument();
  });

  it('Back steps returns, and on the first screen it cancels instead', async () => {
    setPointer('touch');
    const user = userEvent.setup();
    render(<MoveForm />);

    // First screen: the left button is Cancel, because there is nothing behind it.
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Next' }));
    await user.click(screen.getByRole('button', { name: 'Back' }));
    expect(screen.getByTestId('sheet-stepper')).toHaveTextContent('Step 1 of 3');
  });
});

describe('MoveForm on a laptop is untouched', () => {
  it('shows all three lenses at once, with no stepper', () => {
    setPointer('pointer');
    render(<MoveForm />);

    expect(screen.queryByTestId('sheet-stepper')).not.toBeInTheDocument();
    expect(screen.getByTestId('move-form-panel').className).not.toContain('sheet');
    // Strategy and Outcome are on screen with Environment.
    expect(screen.getByText('Approach')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Save Move/ })).toBeInTheDocument();
  });
});

// ==================== TAP TO PLACE HOLDS ====================

/** Give the overlay a box so normalized coordinates mean something. */
function stubSurface() {
  const surface = screen.getByTestId('hold-overlay');
  surface.getBoundingClientRect = () => ({
    left: 0,
    top: 0,
    width: 400,
    height: 400,
    right: 400,
    bottom: 400,
    x: 0,
    y: 0,
  });
  return surface;
}

describe('HoldOverlay with a finger', () => {
  it('a tap on empty space drops a box centred on the tap', () => {
    const onCreate = vi.fn();
    render(<HoldOverlay holds={[]} onCreate={onCreate} onDelete={vi.fn()} onPick={vi.fn()} touch />);
    const surface = stubSurface();

    fireEvent.pointerDown(surface, { pointerId: 1, clientX: 200, clientY: 200 });
    fireEvent.pointerUp(surface, { pointerId: 1, clientX: 200, clientY: 200 });

    expect(onCreate).toHaveBeenCalledTimes(1);
    const box = onCreate.mock.calls[0][0];
    expect(box.bbox_x + box.bbox_w / 2).toBeCloseTo(0.5, 2);
    expect(box.bbox_y + box.bbox_h / 2).toBeCloseTo(0.5, 2);
  });

  it('a horizontal swipe steps a frame and places nothing', () => {
    const onCreate = vi.fn();
    const onSwipeFrames = vi.fn();
    render(
      <HoldOverlay
        holds={[]}
        onCreate={onCreate}
        onDelete={vi.fn()}
        onPick={vi.fn()}
        onSwipeFrames={onSwipeFrames}
        touch
      />
    );
    const surface = stubSurface();

    fireEvent.pointerDown(surface, { pointerId: 1, clientX: 300, clientY: 200 });
    fireEvent.pointerMove(surface, { pointerId: 1, clientX: 200, clientY: 205 });
    fireEvent.pointerUp(surface, { pointerId: 1, clientX: 200, clientY: 205 });

    expect(onSwipeFrames).toHaveBeenCalledWith(1);
    expect(onCreate).not.toHaveBeenCalled();
  });

  it('a mostly vertical drag is a page scroll: no hold, no scrub', () => {
    const onCreate = vi.fn();
    const onSwipeFrames = vi.fn();
    render(
      <HoldOverlay
        holds={[]}
        onCreate={onCreate}
        onDelete={vi.fn()}
        onPick={vi.fn()}
        onSwipeFrames={onSwipeFrames}
        touch
      />
    );
    const surface = stubSurface();

    fireEvent.pointerDown(surface, { pointerId: 1, clientX: 200, clientY: 100 });
    fireEvent.pointerMove(surface, { pointerId: 1, clientX: 210, clientY: 300 });
    fireEvent.pointerUp(surface, { pointerId: 1, clientX: 210, clientY: 300 });

    expect(onCreate).not.toHaveBeenCalled();
    expect(onSwipeFrames).not.toHaveBeenCalled();
  });

  it('a read-only overlay places nothing, however it is tapped', () => {
    const onCreate = vi.fn();
    render(
      <HoldOverlay holds={[]} onCreate={onCreate} onDelete={vi.fn()} onPick={vi.fn()} touch readOnly />
    );
    const surface = stubSurface();

    fireEvent.pointerDown(surface, { pointerId: 1, clientX: 200, clientY: 200 });
    fireEvent.pointerUp(surface, { pointerId: 1, clientX: 200, clientY: 200 });

    expect(onCreate).not.toHaveBeenCalled();
  });

  it('a tap on a hold selects it rather than deleting it', () => {
    const onDelete = vi.fn();
    const holds = [{ id: 5, bbox_x: 0.4, bbox_y: 0.4, bbox_w: 0.2, bbox_h: 0.2, source: 'manual' }];
    render(<HoldOverlay holds={holds} onCreate={vi.fn()} onDelete={onDelete} onPick={vi.fn()} touch />);
    const surface = stubSurface();

    fireEvent.pointerDown(surface, { pointerId: 1, clientX: 200, clientY: 200 });
    fireEvent.pointerUp(surface, { pointerId: 1, clientX: 200, clientY: 200 });

    // Deleting is press-and-hold; a tap must never lose a labeler's work.
    expect(onDelete).not.toHaveBeenCalled();
    expect(screen.getByText(/Pinch to resize/)).toBeInTheDocument();
  });

  it('tapping a hold in pick mode assigns it', () => {
    const onPick = vi.fn();
    const holds = [{ id: 5, bbox_x: 0.4, bbox_y: 0.4, bbox_w: 0.2, bbox_h: 0.2, source: 'manual' }];
    render(
      <HoldOverlay
        holds={holds}
        pickSlot={{ slot: 'end' }}
        onCreate={vi.fn()}
        onDelete={vi.fn()}
        onPick={onPick}
        touch
      />
    );
    const surface = stubSurface();

    fireEvent.pointerDown(surface, { pointerId: 1, clientX: 200, clientY: 200 });
    fireEvent.pointerUp(surface, { pointerId: 1, clientX: 200, clientY: 200 });

    expect(onPick).toHaveBeenCalledWith(holds[0]);
  });
});

// ==================== CAPTURE GUIDANCE ====================

describe('capture guidance', () => {
  it('tells a phone labeler to shoot 1080p30', () => {
    setPointer('touch');
    render(<OnboardingBanner id={BANNER_CAPTURE} />);
    expect(screen.getByRole('note')).toHaveTextContent('30fps');
  });

  it('is not shown on a laptop — it is advice about the device in your hand', () => {
    setPointer('pointer');
    render(<OnboardingBanner id={BANNER_CAPTURE} />);
    expect(screen.queryByRole('note')).not.toBeInTheDocument();
  });

  it('stays dismissed across sessions, unlike the screen tips', async () => {
    setPointer('touch');
    const user = userEvent.setup();
    const { unmount } = render(<OnboardingBanner id={BANNER_CAPTURE} />);
    await user.click(screen.getByRole('button', { name: /Dismiss/ }));
    unmount();

    // A fresh session: the store is empty again, localStorage is not.
    useStore.setState({ dismissedBanners: {} });
    render(<OnboardingBanner id={BANNER_CAPTURE} />);
    expect(screen.queryByRole('note')).not.toBeInTheDocument();
  });

  it('the define tip speaks about taps on touch, and about [ and ] on a laptop', () => {
    setPointer('touch');
    const { unmount } = render(<OnboardingBanner id={BANNER_DEFINE} />);
    expect(screen.getByRole('note')).toHaveTextContent(/Swipe the video/);
    unmount();

    setPointer('pointer');
    render(<OnboardingBanner id={BANNER_DEFINE} />);
    expect(screen.getByRole('note')).toHaveTextContent('[');
  });
});

// ==================== PWA ====================

describe('Add to Home Screen', () => {
  const setUserAgent = (ua) =>
    Object.defineProperty(window.navigator, 'userAgent', { value: ua, configurable: true });

  it('gives an iPhone the Share-sheet steps, since iOS fires no install event', () => {
    setPointer('touch');
    setUserAgent('Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15');
    render(<InstallPrompt />);
    expect(screen.getByTestId('install-prompt')).toHaveTextContent('Add to Home Screen');
  });

  it('says nothing on a laptop', () => {
    setPointer('pointer');
    setUserAgent('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36');
    render(<InstallPrompt />);
    expect(screen.queryByTestId('install-prompt')).not.toBeInTheDocument();
  });

  it('says nothing once the app is already installed', () => {
    setPointer('touch');
    setUserAgent('Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15');
    window.navigator.standalone = true;
    render(<InstallPrompt />);
    expect(screen.queryByTestId('install-prompt')).not.toBeInTheDocument();
  });

  it('stays dismissed across sessions', async () => {
    setPointer('touch');
    setUserAgent('Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15');
    const user = userEvent.setup();
    const { unmount } = render(<InstallPrompt />);
    await user.click(screen.getByRole('button', { name: /Dismiss/ }));
    unmount();

    render(<InstallPrompt />);
    expect(screen.queryByTestId('install-prompt')).not.toBeInTheDocument();
  });
});
