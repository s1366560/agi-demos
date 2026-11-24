import { useHostAppearance } from './useHostAppearance';

export function useThemeColor(property: string, fallback = '') {
  useHostAppearance();
  return getComputedStyle(document.documentElement).getPropertyValue(property).trim() || fallback;
}
