/**
 * VideoMetadataPanel: the prep strip. Admins get the metadata form and "Mark
 * ready to rate"; a non-admin owner gets the badge, and a locked banner once
 * the video is ready or closed — with the store flagged read-only so the
 * player and moves list hide their mutation controls.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

vi.mock('../api/client', () => ({
  adminUpdateVideoMetadata: vi.fn(),
  adminMarkReady: vi.fn(),
  adminReopenVideo: vi.fn(),
}));

import VideoMetadataPanel from './VideoMetadataPanel';
import useStore from '../store/useStore';
import { adminUpdateVideoMetadata, adminMarkReady } from '../api/client';

const VIDEO = { id: 3, filename: 'prep.mp4', dataset: 'B', prep_status: 'draft', route_grade: null, gym: null };

beforeEach(() => {
  useStore.getState().resetVideoState();
  vi.mocked(adminMarkReady).mockResolvedValue({ ...VIDEO, dataset: 'A', prep_status: 'ready' });
  vi.mocked(adminUpdateVideoMetadata).mockImplementation(async (id, fields) => ({ ...VIDEO, ...fields }));
  vi.spyOn(window, 'confirm').mockReturnValue(true);
});

describe('VideoMetadataPanel — non-admin owner', () => {
  it('shows the prep status badge and no Mark ready button on a draft', () => {
    useStore.setState({ currentVideo: VIDEO, profile: { is_admin: false } });
    render(<VideoMetadataPanel />);

    expect(screen.getByTestId('prep-status')).toHaveTextContent('draft');
    expect(screen.queryByRole('button', { name: 'Mark ready to rate' })).not.toBeInTheDocument();
    expect(screen.queryByTestId('locked-banner')).not.toBeInTheDocument();
    expect(useStore.getState().readOnlyStructure).toBe(false);
  });

  it('shows the locked banner and flags the store read-only once the video is ready', () => {
    useStore.setState({ currentVideo: { ...VIDEO, prep_status: 'ready' }, profile: { is_admin: false } });
    render(<VideoMetadataPanel />);

    expect(screen.getByTestId('locked-banner')).toHaveTextContent('holds and moves are locked');
    expect(useStore.getState().readOnlyStructure).toBe(true);
  });

  it('shows metadata read-only, not as inputs', async () => {
    const user = userEvent.setup();
    useStore.setState({ currentVideo: { ...VIDEO, route_grade: 'V5' }, profile: { is_admin: false } });
    render(<VideoMetadataPanel />);

    await user.click(screen.getByRole('button', { name: 'Video details' }));
    expect(screen.getByText('V5')).toBeInTheDocument();
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
  });
});

describe('VideoMetadataPanel — admin', () => {
  it('saves the metadata form through the admin endpoint', async () => {
    const user = userEvent.setup();
    useStore.setState({ currentVideo: VIDEO, profile: { is_admin: true } });
    render(<VideoMetadataPanel />);

    await user.click(screen.getByRole('button', { name: 'Video details' }));
    await user.type(screen.getByLabelText('Route grade'), 'V5');
    await user.type(screen.getByLabelText('Climber height (cm)'), '172');
    await user.type(screen.getByLabelText('Gym'), 'BKB');
    await user.click(screen.getByRole('button', { name: 'Save details' }));

    await waitFor(() =>
      expect(adminUpdateVideoMetadata).toHaveBeenCalledWith(
        3,
        expect.objectContaining({ route_grade: 'V5', climber_height_cm: 172, gym: 'BKB' })
      )
    );
    // Untouched integer fields are omitted, not sent as 0 or "".
    expect(adminUpdateVideoMetadata.mock.calls[0][1]).not.toHaveProperty('climber_ape_index_cm');
    expect(useStore.getState().currentVideo.route_grade).toBe('V5');
  });

  it('marks the video ready and keeps editing rights (no read-only flag for admins)', async () => {
    const user = userEvent.setup();
    useStore.setState({ currentVideo: VIDEO, profile: { is_admin: true } });
    render(<VideoMetadataPanel />);

    await user.click(screen.getByRole('button', { name: 'Mark ready to rate' }));

    await waitFor(() => expect(adminMarkReady).toHaveBeenCalledWith(3));
    expect(await screen.findByTestId('prep-status')).toHaveTextContent('ready');
    expect(screen.getByRole('button', { name: 'Reopen for editing' })).toBeInTheDocument();
    expect(useStore.getState().readOnlyStructure).toBe(false);
    expect(screen.queryByTestId('locked-banner')).not.toBeInTheDocument();
  });
});
