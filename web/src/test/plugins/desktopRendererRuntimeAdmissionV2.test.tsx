import { renderHook } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { useDesktopRendererRuntimeAdmissionV2 } from '../../../../agi-stack/apps/desktop/src/hooks/useDesktopRendererRuntimeAdmissionV2';

// Use the test renderer's real dispatcher across the separate workspace installs.
vi.mock('../../../../agi-stack/apps/desktop/node_modules/react', async () => import('react'));

describe('native renderer runtime admission', () => {
  it('defers authenticated business refresh until a generation is committed', () => {
    const refresh = vi.fn();
    const { result, rerender } = renderHook(
      ({ authenticated, digest }) =>
        useDesktopRendererRuntimeAdmissionV2(authenticated, digest, refresh),
      { initialProps: { authenticated: false, digest: undefined as string | undefined } }
    );
    const admitted = result.current;
    expect(admitted()).toBe(false);
    rerender({ authenticated: true, digest: undefined });
    expect(admitted()).toBe(false);
    expect(refresh).not.toHaveBeenCalled();
    rerender({ authenticated: true, digest: 'generation-a' });
    expect(result.current).toBe(admitted);
    expect(admitted()).toBe(true);
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it('uses the latest refresh callback without starting a render loop', () => {
    const beforeLogin = vi.fn();
    const signedIn = vi.fn();
    const changedConfig = vi.fn();
    const { rerender } = renderHook(
      ({ digest, refresh }) => useDesktopRendererRuntimeAdmissionV2(true, digest, refresh),
      { initialProps: { digest: undefined as string | undefined, refresh: beforeLogin } }
    );
    rerender({ digest: undefined, refresh: signedIn });
    rerender({ digest: 'generation-a', refresh: signedIn });
    expect(beforeLogin).not.toHaveBeenCalled();
    expect(signedIn).toHaveBeenCalledTimes(1);
    rerender({ digest: 'generation-a', refresh: changedConfig });
    expect(changedConfig).not.toHaveBeenCalled();
    rerender({ digest: 'generation-b', refresh: changedConfig });
    expect(changedConfig).toHaveBeenCalledTimes(1);
  });

  it('closes admission on logout and unmount and refreshes after a new login', () => {
    const refresh = vi.fn();
    const { result, rerender, unmount } = renderHook(
      ({ authenticated }) =>
        useDesktopRendererRuntimeAdmissionV2(authenticated, 'retained-generation', refresh),
      { initialProps: { authenticated: true } }
    );
    const admitted = result.current;
    expect(admitted()).toBe(true);
    rerender({ authenticated: false });
    expect(admitted()).toBe(false);
    expect(refresh).toHaveBeenCalledTimes(1);
    rerender({ authenticated: true });
    expect(admitted()).toBe(true);
    expect(refresh).toHaveBeenCalledTimes(2);
    unmount();
    expect(admitted()).toBe(false);
  });

  it('closes admission while no generation is retained and recovers automatically', () => {
    const refresh = vi.fn();
    const { result, rerender } = renderHook(
      ({ digest }) => useDesktopRendererRuntimeAdmissionV2(true, digest, refresh),
      { initialProps: { digest: 'generation-a' as string | undefined } }
    );
    const admitted = result.current;
    rerender({ digest: undefined });
    expect(admitted()).toBe(false);
    expect(refresh).toHaveBeenCalledTimes(1);
    rerender({ digest: 'generation-b' });
    expect(admitted()).toBe(true);
    expect(refresh).toHaveBeenCalledTimes(2);
  });
});
