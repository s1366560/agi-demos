import { renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';

import { useSandboxDetection } from '@/hooks/useSandboxDetection';
import { useSandboxStore } from '@/stores/sandbox';

describe('useSandboxDetection', () => {
  beforeEach(() => {
    useSandboxStore.getState().reset();
  });

  it('tracks sandbox id changes after the hook is mounted', async () => {
    const { rerender } = renderHook(
      ({ sandboxId }: { sandboxId: string | null | undefined }) =>
        useSandboxDetection({ sandboxId, autoOpenPanel: false }),
      {
        initialProps: { sandboxId: 'sandbox-1' as string | null | undefined },
      }
    );

    await waitFor(() => {
      expect(useSandboxStore.getState().activeSandboxId).toBe('sandbox-1');
    });

    rerender({ sandboxId: 'sandbox-2' });

    await waitFor(() => {
      expect(useSandboxStore.getState().activeSandboxId).toBe('sandbox-2');
    });

    rerender({ sandboxId: null });

    await waitFor(() => {
      expect(useSandboxStore.getState().activeSandboxId).toBeNull();
    });
  });
});
