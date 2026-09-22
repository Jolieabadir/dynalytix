/**
 * ProfileGate: the one-screen rater profile that stands between sign-in and
 * everything else until POST /api/me/profile has succeeded.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

vi.mock('../api/client', () => ({
  createMyProfile: vi.fn(),
}));

import ProfileGate from './ProfileGate';
import { createMyProfile } from '../api/client';

beforeEach(() => {
  vi.mocked(createMyProfile).mockResolvedValue({
    user_id: 'u1',
    display_name: 'Jo',
    tier: 'open',
    is_admin: false,
  });
});

describe('ProfileGate', () => {
  it('renders the five profile fields and nothing about tier', () => {
    render(<ProfileGate onCreated={() => {}} />);
    expect(screen.getByLabelText('Display name')).toBeInTheDocument();
    expect(screen.getByLabelText('Years climbing')).toBeInTheDocument();
    expect(screen.getByLabelText('Highest grade climbed')).toBeInTheDocument();
    expect(screen.getByLabelText(/Coaching certification/)).toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: /research background/i })).toBeInTheDocument();
    // Tier is set by an admin, never self-declared.
    expect(screen.queryByLabelText(/tier/i)).not.toBeInTheDocument();
  });

  it('refuses an empty display name without calling the API', async () => {
    const user = userEvent.setup();
    render(<ProfileGate onCreated={() => {}} />);

    await user.click(screen.getByRole('button', { name: 'Save profile' }));

    expect(await screen.findByText('Enter a display name.')).toBeInTheDocument();
    expect(createMyProfile).not.toHaveBeenCalled();
  });

  it('posts the profile in the API shape and hands the result up', async () => {
    const user = userEvent.setup();
    const onCreated = vi.fn();
    render(<ProfileGate onCreated={onCreated} />);

    await user.type(screen.getByLabelText('Display name'), 'Jo');
    await user.type(screen.getByLabelText('Years climbing'), '7');
    await user.type(screen.getByLabelText('Highest grade climbed'), 'V6');
    await user.click(screen.getByRole('checkbox', { name: /research background/i }));
    await user.click(screen.getByRole('button', { name: 'Save profile' }));

    await waitFor(() =>
      expect(createMyProfile).toHaveBeenCalledWith({
        display_name: 'Jo',
        years_climbing: 7,
        highest_grade: 'V6',
        coaching_cert: null,
        research_background: true,
      })
    );
    expect(onCreated).toHaveBeenCalledWith(expect.objectContaining({ display_name: 'Jo' }));
  });

  it('shows the server detail when the POST fails', async () => {
    vi.mocked(createMyProfile).mockRejectedValue({
      response: { status: 409, data: { detail: 'Profile already exists' } },
    });
    const user = userEvent.setup();
    render(<ProfileGate onCreated={() => {}} />);

    await user.type(screen.getByLabelText('Display name'), 'Jo');
    await user.click(screen.getByRole('button', { name: 'Save profile' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Profile already exists');
  });
});
