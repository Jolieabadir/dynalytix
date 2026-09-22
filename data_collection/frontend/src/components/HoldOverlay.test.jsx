/**
 * HoldOverlay in read-only mode: boxes stay visible and pickable, but a click
 * never deletes and a drag never draws.
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import HoldOverlay from './HoldOverlay';

const HOLDS = [{ id: 7, bbox_x: 0.1, bbox_y: 0.1, bbox_w: 0.2, bbox_h: 0.2, source: 'manual' }];

describe('HoldOverlay — readOnly', () => {
  it('does not delete on click and does not draw on drag', async () => {
    const user = userEvent.setup();
    const onDelete = vi.fn();
    const onCreate = vi.fn();
    render(<HoldOverlay holds={HOLDS} pickSlot={null} onCreate={onCreate} onDelete={onDelete} onPick={() => {}} readOnly />);

    const box = screen.getByRole('button', { name: 'Hold 7' });
    await user.click(box);
    expect(onDelete).not.toHaveBeenCalled();

    const surface = screen.getByTestId('hold-overlay');
    surface.getBoundingClientRect = () => ({ left: 0, top: 0, width: 100, height: 100 });
    fireEvent.pointerDown(surface, { clientX: 10, clientY: 10, pointerId: 1 });
    fireEvent.pointerMove(surface, { clientX: 60, clientY: 60, pointerId: 1 });
    fireEvent.pointerUp(surface, { clientX: 60, clientY: 60, pointerId: 1 });
    expect(onCreate).not.toHaveBeenCalled();
  });

  it('still hands a box to the form while picking', async () => {
    const user = userEvent.setup();
    const onPick = vi.fn();
    render(
      <HoldOverlay holds={HOLDS} pickSlot={{ slot: 'end' }} onCreate={() => {}} onDelete={() => {}} onPick={onPick} readOnly />
    );

    await user.click(screen.getByRole('button', { name: 'Assign hold 7' }));
    expect(onPick).toHaveBeenCalledWith(HOLDS[0]);
  });

  it('keeps deleting on click when not read-only (Dataset B unchanged)', async () => {
    const user = userEvent.setup();
    const onDelete = vi.fn();
    render(<HoldOverlay holds={HOLDS} pickSlot={null} onCreate={() => {}} onDelete={onDelete} onPick={() => {}} />);

    await user.click(screen.getByRole('button', { name: 'Delete hold 7' }));
    expect(onDelete).toHaveBeenCalledWith(HOLDS[0]);
  });
});
