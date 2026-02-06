/**
 * Theme Store Mock for Testing
 */

import { vi } from 'vitest';

export const useThemeStore = vi.fn(() => ({
  computedTheme: 'light',
  theme: 'light',
}));

vi.mock('@/stores/theme', () => ({
  useThemeStore,
}));
