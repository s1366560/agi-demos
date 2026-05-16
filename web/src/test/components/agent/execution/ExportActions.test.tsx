import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom/vitest';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { ExportActions } from '../../../../components/agent/execution/ExportActions';

describe('ExportActions', () => {
  let writeTextSpy: ReturnType<typeof vi.spyOn> | undefined;

  afterEach(() => {
    writeTextSpy?.mockRestore();
    writeTextSpy = undefined;
  });

  it('copies a routable agent workspace link for sharing', async () => {
    writeTextSpy = vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValue(undefined);

    render(<ExportActions conversationId="conversation-1" showLabels variant="inline" />);

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Share conversation link' }));
    });

    await waitFor(() => {
      expect(writeTextSpy).toHaveBeenCalledWith(
        `${window.location.origin}/tenant/agent-workspace/conversation-1`
      );
    });
    expect(writeTextSpy.mock.calls[0]?.[0]).not.toContain('/shared/');
  });
});
