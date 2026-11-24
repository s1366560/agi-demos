import { useSyncExternalStore } from 'react';

// The signed-page bridge mirrors the host appearance onto the isolated document.
function subscribe(listener: () => void) {
  const observer = new MutationObserver(listener);
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
  return () => observer.disconnect();
}

export function useHostAppearance(): 'light' | 'dark' {
  return useSyncExternalStore(subscribe, () =>
    document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light'
  );
}

export function useThemeColor(property: string, fallback = '') {
  useHostAppearance();
  return getComputedStyle(document.documentElement).getPropertyValue(property).trim() || fallback;
}
