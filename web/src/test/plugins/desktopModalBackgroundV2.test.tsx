import { createRef } from 'react';
import { renderHook } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { useDesktopModalBackgroundV2 } from '../../../../agi-stack/apps/desktop/src/hooks/useDesktopModalBackgroundV2';

vi.mock('../../../../agi-stack/apps/desktop/node_modules/react', async () => import('react'));

describe('native modal background ownership', () => {
  it('restores the login root when logout removes the authenticated shell', () => {
    const root = document.createElement('div');
    root.id = 'root';
    const shell = document.createElement('main');
    root.append(shell);
    document.body.append(root);
    const ref = createRef<HTMLElement>();
    ref.current = shell;
    const { rerender, unmount } = renderHook(
      ({ authenticated }) => useDesktopModalBackgroundV2(ref, authenticated),
      { initialProps: { authenticated: true } }
    );
    try {
      expect(root.hasAttribute('inert')).toBe(true);
      expect(root.getAttribute('aria-hidden')).toBe('true');
      shell.remove();
      ref.current = null;
      rerender({ authenticated: false });
      expect(root.hasAttribute('inert')).toBe(false);
      expect(root.hasAttribute('aria-hidden')).toBe(false);
    } finally {
      unmount();
      root.remove();
    }
  });

  it('restores previous attributes when the modal owner unmounts', () => {
    const root = document.createElement('div');
    root.id = 'root';
    root.setAttribute('aria-hidden', 'false');
    const shell = document.createElement('main');
    shell.setAttribute('inert', 'prior-owner');
    root.append(shell);
    document.body.append(root);
    const ref = createRef<HTMLElement>();
    ref.current = shell;
    const { unmount } = renderHook(() => useDesktopModalBackgroundV2(ref, true));
    unmount();
    try {
      expect(root.getAttribute('aria-hidden')).toBe('false');
      expect(root.hasAttribute('inert')).toBe(false);
      expect(shell.getAttribute('inert')).toBe('prior-owner');
      expect(shell.hasAttribute('aria-hidden')).toBe(false);
    } finally {
      root.remove();
    }
  });
});
