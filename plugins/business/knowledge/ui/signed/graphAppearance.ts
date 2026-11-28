import { useHostAppearance } from './appearance';

export function useThemeStore() {
  return { computedTheme: useHostAppearance() };
}
