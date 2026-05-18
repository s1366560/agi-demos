import { beforeEach, describe, expect, it, vi } from 'vitest';

describe('layout mode store persistence', () => {
  beforeEach(() => {
    localStorage.clear();
    vi.resetModules();
  });

  it('restores split ratio from the persisted mode default', async () => {
    localStorage.setItem(
      'layout-mode-store',
      JSON.stringify({
        state: {
          mode: 'code',
          chatPanelVisible: true,
          rightPanelTab: 'desktop',
          splitRatio: 1,
        },
        version: 0,
      })
    );

    const { useLayoutModeStore } = await import('../../stores/layoutMode');

    expect(useLayoutModeStore.getState().mode).toBe('code');
    expect(useLayoutModeStore.getState().rightPanelTab).toBe('desktop');
    expect(useLayoutModeStore.getState().splitRatio).toBe(0.5);
  });
});
