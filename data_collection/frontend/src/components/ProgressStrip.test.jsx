import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import ProgressStrip from './ProgressStrip';
import useStore from '../store/useStore';

beforeEach(() => {
  useStore.getState().resetForSignOut();
});

describe('ProgressStrip export gating', () => {
  it('disables Finish & Export with a reason until the pose is done', () => {
    render(
      <ProgressStrip
        onSaveAndNext={() => {}}
        onFinish={() => {}}
        canExport={false}
        exportBlockedReason="Export is available once the server has finished extracting the pose."
      />
    );
    const button = screen.getByRole('button', { name: 'Finish & Export' });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute('title', 'Export is available once the server has finished extracting the pose.');
  });

  it('enables it once the pose is done', () => {
    render(<ProgressStrip onSaveAndNext={() => {}} onFinish={() => {}} canExport />);
    const button = screen.getByRole('button', { name: 'Finish & Export' });
    expect(button).toBeEnabled();
    expect(button).not.toHaveAttribute('title');
  });
});
