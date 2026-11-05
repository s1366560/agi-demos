import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

describe('theme initialization from persisted preferences', () => {
  let initialClasses: string;

  beforeEach(() => {
    vi.resetModules();
    initialClasses = document.documentElement.className;
    document.documentElement.classList.remove('dark', 'high-contrast');
    localStorage.removeItem('theme-storage');
  });

  afterEach(() => {
    document.documentElement.className = initialClasses;
    localStorage.removeItem('theme-storage');
    vi.restoreAllMocks();
  });

  it.each([
    { theme: 'light', cached: 'dark', systemDark: true, expected: 'light' },
    { theme: 'dark', cached: 'light', systemDark: false, expected: 'dark' },
    { theme: 'system', cached: 'dark', systemDark: false, expected: 'light' },
    { theme: 'system', cached: 'light', systemDark: true, expected: 'dark' },
    { theme: 'high-contrast', cached: 'light', systemDark: false, expected: 'dark' },
  ])(
    'keeps AntD and document classes aligned for $theme with cached $cached',
    async ({ theme, cached, systemDark, expected }) => {
      vi.spyOn(window, 'matchMedia').mockReturnValue({
        matches: systemDark,
        addEventListener: vi.fn(),
      } as unknown as MediaQueryList);
      localStorage.setItem(
        'theme-storage',
        JSON.stringify({ state: { theme, computedTheme: cached }, version: 0 })
      );

      const { useThemeStore } = await import('../../stores/theme');

      expect(useThemeStore.persist.hasHydrated()).toBe(true);
      expect(useThemeStore.getState().computedTheme).toBe(expected);
      expect(document.documentElement.classList.contains('dark')).toBe(expected === 'dark');
      expect(document.documentElement.classList.contains('high-contrast')).toBe(
        theme === 'high-contrast'
      );
      expect(JSON.parse(localStorage.getItem('theme-storage') ?? '{}').state).toEqual({ theme });
    }
  );

  it('applies the current system preference when there is no saved theme', async () => {
    vi.spyOn(window, 'matchMedia').mockReturnValue({
      matches: true,
      addEventListener: vi.fn(),
    } as unknown as MediaQueryList);

    const { useThemeStore } = await import('../../stores/theme');

    expect(useThemeStore.persist.hasHydrated()).toBe(true);
    expect(useThemeStore.getState().computedTheme).toBe('dark');
    expect(document.documentElement.classList.contains('dark')).toBe(true);
  });
});
